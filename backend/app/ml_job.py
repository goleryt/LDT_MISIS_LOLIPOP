"""Daily ML batch: DB -> LCT_ML_backend_v1 runtime -> `ml_scores` (+ selected -> `predictions`).

Run once per day after day D is closed, in an environment that has the ML
requirements (pinned in models/bundles/requirements.txt, Python 3.11-3.12):

    python -m scripts.run_ml_daily --ready-marker /path/ready.txt [--date YYYY-MM-DD]

The API process never imports the ML libraries; it only reads the stored rows.

Rules taken from the ML package README, not decided here:
- call only `MLRuntime.score_day` (features are built inside the bundle);
- top-K per day and a cooldown are applied by the backend, not the model;
- no automatic requests or critical notifications from a shadow score;
- the score is a proxy of an observed event, never a fire probability.
Raw journal rows are exported to a temporary directory and are never logged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import logging
import tempfile
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import ChannelCatalogue, EventsJournal
from app.db.platform import MlScore, MlRun, Prediction
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

JOURNAL_COLUMNS = ("ид_события", "ид_канала_данных", "дата", "время", "тревожное", "значение_датчика")
CATALOGUE_COLUMNS = ("ид_канала_данных", "тип_инж_системы", "тип_датчика",
                     "тег_инженерной_системы", "название_датчика", "ид_объект")
# Gas records that carry no information for the UI (the channel is simply not gas).
SKIP_REASONS = {"NOT_GAS_STREAM"}


class MlJobError(RuntimeError):
    pass


def last_closed_day(settings: Settings, now: datetime | None = None) -> date:
    now = now or datetime.now(ZoneInfo(settings.source_timezone))
    return now.astimezone(ZoneInfo(settings.source_timezone)).date() - timedelta(days=1)


def export_journal(db: Session, start: datetime, end_exclusive: datetime, out_dir: Path) -> list[Path]:
    """Journal window as raw-schema CSV, one file per calendar year (the bundle forbids a day in two files)."""
    stmt = (
        select(EventsJournal.ид_события, EventsJournal.ид_канала_данных, EventsJournal.d_event_time,
               EventsJournal.d_alarm, EventsJournal.значение_датчика)
        .where(EventsJournal.d_event_time >= start, EventsJournal.d_event_time < end_exclusive)
        .order_by(EventsJournal.d_event_time, EventsJournal.id)
        .execution_options(yield_per=20000)
    )
    files: dict[int, tuple[Any, Any, Path]] = {}
    try:
        for event_id, channel_id, when, alarm, value in db.execute(stmt):
            slot = files.get(when.year)
            if slot is None:
                path = out_dir / f"journal_{when.year}.csv"
                handle = open(path, "w", newline="", encoding="utf-8")
                writer = csv.writer(handle)
                writer.writerow(JOURNAL_COLUMNS)
                slot = files[when.year] = (handle, writer, path)
            slot[1].writerow([event_id, channel_id, when.date().isoformat(), when.time().strftime("%H:%M:%S"),
                              "" if alarm is None else str(alarm).lower(), "" if value is None else value])
    finally:
        for handle, _, _ in files.values():
            handle.close()
    return [files[year][2] for year in sorted(files)]


def export_catalogue(db: Session, path: Path) -> int:
    rows = db.execute(select(ChannelCatalogue.ид_канала_данных, ChannelCatalogue.тип_инж_системы,
                             ChannelCatalogue.тип_датчика, ChannelCatalogue.тег_инженерной_системы,
                             ChannelCatalogue.название_датчика, ChannelCatalogue.ид_объект)
                      .order_by(ChannelCatalogue.ид_канала_данных)).all()
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CATALOGUE_COLUMNS)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
    return len(rows)


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(str(value))
    except ValueError:
        # Ids in the DB are integers; anything else cannot be linked to a channel/object.
        return None


def _as_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _row(kind: str, d: date, run_id: str, record: dict[str, Any]) -> MlScore:
    return MlScore(
        as_of_date=d, run_id=run_id, kind=kind, bundle=record.get("bundle") or "",
        model_version=record.get("model_version"), target_code=record.get("target_code"),
        object_id=_as_int(record.get("ид_объект")), channel_id=_as_int(record.get("ид_канала_данных")),
        incident_type=record.get("incident_type"), score=record.get("score"),
        score_kind=record.get("score_kind"), evidence_level=record.get("evidence_level"),
        decision_status=record.get("decision_status"),
        reason_codes=list(record.get("reason_codes") or ([record["abstain_reason"]] if record.get("abstain_reason") else [])),
        window_start=_as_date(record.get("window_start")),
        window_end_exclusive=_as_date(record.get("window_end_exclusive")),
        maintenance_context=record.get("maintenance_context"), selected=False, payload=record)


def select_alerts(db: Session, d: date, rows: list[MlScore], top_k: int, cooldown_days: int) -> list[MlScore]:
    """Top-K by score among shadow forecasts, skipping channels alerted in the last `cooldown_days` days."""
    recent = {c for (c,) in db.execute(
        select(MlScore.channel_id).where(MlScore.kind == "gas", MlScore.selected.is_(True),
                                         MlScore.as_of_date < d,
                                         MlScore.as_of_date >= d - timedelta(days=cooldown_days - 1)))}
    candidates = [r for r in rows if r.kind == "gas" and r.score is not None and r.channel_id is not None
                  and r.decision_status == "experimental_shadow" and r.channel_id not in recent]
    candidates.sort(key=lambda r: (-r.score, r.channel_id))
    chosen = candidates[:top_k]
    for rank, row in enumerate(chosen, start=1):
        row.selected, row.rank = True, rank
    return chosen


def store_output(db: Session, output: dict[str, Any], settings: Settings, revision: int = 1) -> dict[str, Any]:
    """Persist an immutable day/revision, selecting shadow forecasts without automatic actions."""
    d = date.fromisoformat(output["as_of_date"])
    run_id = output.get("request_id") or f"daily-{d}"
    if revision < 1:
        raise MlJobError("INVALID_REVISION")
    digest = hashlib.sha256(json.dumps(output, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    db.execute(text("SELECT pg_advisory_xact_lock(90260926)"))
    run = db.scalar(select(MlRun).where(MlRun.as_of_date == d, MlRun.revision == revision))
    if run and run.state == "completed":
        if run.output_hash != digest:
            raise MlJobError("DAY_ALREADY_EXISTS_USE_NEW_REVISION")
        return {**(run.summary or {}), "state": "already_written"}
    if run is None:
        run = MlRun(as_of_date=d, revision=revision, state="running")
        db.add(run)
    run_id = f"{run_id}:r{revision}"
    for record in output.get("gas", []):
        score = record.get("score")
        if score is not None and (not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1):
            raise MlJobError("INVALID_SCORE")
        if score is not None and record.get("decision_status") != "experimental_shadow":
            raise MlJobError("SCORE_WITHOUT_SHADOW_STATUS")
        if record.get("label_source") == "stub" or record.get("evidence_level") == "E4":
            raise MlJobError("STUB_GAS_RESULT_REJECTED")
        if record.get("is_primary", True) and not set(record.get("reason_codes") or []) & SKIP_REASONS:
            channel = db.get(ChannelCatalogue, _as_int(record.get("ид_канала_данных")))
            if channel is None or channel.ид_объект != _as_int(record.get("ид_объект")):
                raise MlJobError("UNKNOWN_OR_MISMATCHED_CHANNEL")
        start, end = _as_date(record.get("window_start")), _as_date(record.get("window_end_exclusive"))
        if score is not None and (not start or not end or start < d + timedelta(days=2) or end <= start):
            raise MlJobError("INVALID_FORECAST_WINDOW")
    rows = [_row("gas", d, run_id, r) for r in output.get("gas", [])
            if r.get("is_primary", True) and not (set(r.get("reason_codes") or []) & SKIP_REASONS)]
    # Incident head is trained on stub labels. Never promote demo scores into production records.
    suppressed_incidents = len(output.get("incidents", []))
    channels = [r.channel_id for r in rows]
    if len(set(channels)) != len(channels):
        raise MlJobError("DUPLICATE_GAS_CHANNEL")
    chosen = select_alerts(db, d, rows, settings.ml_top_k_per_day, settings.ml_cooldown_days)
    db.add_all(rows)
    db.flush()

    tz = ZoneInfo(settings.source_timezone)
    reference_at = datetime.combine(d + timedelta(days=1), time(0), tzinfo=tz)
    calculated_at = datetime.now(timezone.utc)
    predicted = 0
    for row in chosen:
        if row.object_id is None:
            continue
        provider_id = f"{row.bundle}:{d}:{row.channel_id}:r{revision}"
        exists = db.scalar(select(Prediction.id).where(Prediction.provider_id == provider_id,
                                                       Prediction.model_version == row.model_version))
        if exists:
            continue
        # Preserve manual advice without creating work or alarms automatically.
        db.add(Prediction(provider_id=provider_id, object_id=row.object_id, channel_id=row.channel_id,
                          incident_type=row.incident_type or "gas_threshold_cross", probability=row.score,
                          horizon_hours=int((datetime.combine(row.window_start, time(0), tzinfo=tz) - reference_at).total_seconds() // 3600),
                          calculated_at=calculated_at,
                          predicted_for=datetime.combine(row.window_start, time(0), tzinfo=tz),
                          model_version=row.model_version or "unknown",
                          recommendation=(row.payload.get("recommendation") or {}).get("text_ru"),
                          ml_metadata={"as_of_date": d.isoformat(), "revision": revision,
                                       "reference_at": reference_at.isoformat(), "window_start": row.window_start.isoformat(),
                                       "window_end_exclusive": row.window_end_exclusive.isoformat(),
                                       "bundle": row.bundle, "evidence_level": row.evidence_level,
                                       "decision_status": row.decision_status, "target_code": row.target_code,
                                       "score_kind": row.score_kind, "maintenance_context": row.maintenance_context,
                                       "recommendation": row.payload.get("recommendation"),
                                       "bundles": output.get("bundles", []), "operational_ready": False}))
        predicted += 1
    gas = [r for r in rows if r.kind == "gas"]
    summary = {"gas_rows": len(gas), "gas_scored": sum(r.score is not None for r in gas),
               "incident_rows": 0, "suppressed_incident_rows": suppressed_incidents,
               "alerts_selected": len(chosen), "predictions_created": predicted}
    run.state, run.output_hash, run.summary = "completed", digest, summary
    run.finished_at, run.error_code = datetime.now(timezone.utc), None
    return summary


def _default_runtime(settings: Settings, work_dir: Path):
    # Imported here: the ML libraries exist only in the ML environment, not in the API process.
    from app.ml_runtime.lct_ml_runtime import MLRuntime

    # Deploy only the selected real gas model. The delivered incident head uses stub labels.
    active = json.loads((settings.ml_bundles_path / "ACTIVE.json").read_text())
    name = active.get("gas", "")
    if not name.startswith("gas_") or Path(name).name != name or "/" in name or "\\" in name:
        raise MlJobError("INVALID_ACTIVE_BUNDLE")
    selected = work_dir / "selected"
    selected.mkdir()
    for filename in ("ACTIVE.json", name + ".zip", name + ".zip.sha256"):
        shutil.copy2(settings.ml_bundles_path / filename, selected / filename)
    return MLRuntime(selected, work_dir=work_dir / "bundles")



def run_daily(as_of: date | None = None, settings: Settings | None = None,
              runtime_factory: Callable[[Settings, Path], Any] | None = None,
              revision: int = 1, journal_files: list[Path] | None = None,
              catalogue_file: Path | None = None, ready_marker: Path | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    d = as_of or last_closed_day(settings)
    if d > last_closed_day(settings) or revision < 1:
        raise MlJobError("DAY_NOT_CLOSED_OR_INVALID_REVISION")
    if ready_marker is None or not ready_marker.is_file() or ready_marker.read_text().strip() != d.isoformat():
        raise MlJobError("DAY_NOT_CERTIFIED_READY")
    if bool(journal_files) != bool(catalogue_file):
        raise MlJobError("JOURNAL_AND_CATALOGUE_REQUIRED_TOGETHER")
    start = datetime.combine(d - timedelta(days=settings.ml_export_days), time(0))
    end = datetime.combine(d + timedelta(days=1), time(0))
    with engine.connect() as lock:
        acquired = lock.scalar(text("SELECT pg_try_advisory_lock(90260927)"))
        lock.commit()
        if not acquired:
            raise MlJobError("ML_JOB_ALREADY_RUNNING")
        try:
            with tempfile.TemporaryDirectory(prefix="lct_ml_job_") as tmp:
                work = Path(tmp)
                if journal_files:
                    files, cat = list(journal_files), catalogue_file
                    channels = None
                else:
                    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                        with Session(bind=connection) as db:
                            files = export_journal(db, start, end, work)
                            cat = work / "catalogue.csv"
                            channels = export_catalogue(db, cat)
                if not files:
                    raise MlJobError("INSUFFICIENT_HISTORY")
                paths = files + [cat] + sorted(settings.ml_bundles_path.glob("*.zip")) + [settings.ml_bundles_path / "ACTIVE.json"]
                paths += [Path(__file__), Path(__file__).parent / "ml_runtime/lct_ml_runtime.py"]
                def fingerprint():
                    h = hashlib.sha256()
                    h.update(f"{d}:{revision}:{settings.ml_top_k_per_day}:{settings.ml_cooldown_days}".encode())
                    for path in paths:
                        h.update(path.name.encode())
                        with path.open("rb") as handle:
                            for chunk in iter(lambda: handle.read(1 << 20), b""):
                                h.update(chunk)
                    return h.hexdigest()
                digest = fingerprint()
                with SessionLocal.begin() as db:
                    previous = db.scalar(select(MlRun).where(MlRun.as_of_date == d, MlRun.revision == revision))
                    if previous and previous.state == "completed":
                        if previous.fingerprint != digest:
                            raise MlJobError("INPUT_CHANGED_USE_NEW_REVISION")
                        return {**(previous.summary or {}), "as_of_date": d.isoformat(), "state": "already_written"}
                    if previous is None:
                        previous = MlRun(as_of_date=d, revision=revision, state="running")
                        db.add(previous)
                    previous.state, previous.fingerprint, previous.error_code = "running", digest, None
                try:
                    runtime = (runtime_factory or _default_runtime)(settings, work)
                    output = runtime.score_day(files, cat, d, request_id=f"daily-{d}")
                    if output.get("as_of_date") != d.isoformat() or not output.get("gas"):
                        raise MlJobError("EMPTY_OR_WRONG_DAY_RESULT")
                    if fingerprint() != digest:
                        raise MlJobError("INPUT_CHANGED_DURING_RUN")
                    with SessionLocal.begin() as db:
                        summary = store_output(db, output, settings, revision)
                except Exception as exc:
                    # Persist failure without raw journal rows, paths or external exception text.
                    code = str(exc) if isinstance(exc, MlJobError) else type(exc).__name__
                    if "INSUFFICIENT_HISTORY" in str(exc): code = "INSUFFICIENT_HISTORY"
                    with SessionLocal.begin() as db:
                        row = db.scalar(select(MlRun).where(MlRun.as_of_date == d, MlRun.revision == revision))
                        row.state, row.error_code, row.finished_at = "failed", code[:100], datetime.now(timezone.utc)
                    raise MlJobError(code) from exc
                return {**summary, "as_of_date": d.isoformat(), "revision": revision, "channels": channels,
                        "journal_files": len(files), "runtime_version": output.get("runtime_version"), "state": "completed"}
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(90260927)"))
            lock.commit()
