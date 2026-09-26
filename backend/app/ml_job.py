"""Daily ML batch: DB -> LCT_ML_backend_v1 runtime -> `ml_scores` (+ selected -> `predictions`).

Run once per day after day D is closed, in an environment that has the ML
requirements (pinned in models/bundles/requirements.txt, Python 3.11-3.12):

    python -m scripts.run_ml_daily [--date YYYY-MM-DD]

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
import logging
import tempfile
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import ChannelCatalogue, EventsJournal
from app.db.platform import MlScore, Prediction
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

JOURNAL_COLUMNS = ("ид_события", "ид_канала_данных", "дата", "время", "тревожное", "значение_датчика")
CATALOGUE_COLUMNS = ("ид_канала_данных", "тип_инж_системы", "тип_датчика",
                     "тег_инженерной_системы", "название_датчика", "ид_объект")
# Gas records that carry no information for the UI (the channel is simply not gas).
SKIP_REASONS = {"NOT_GAS_STREAM"}
PREDICTION_HORIZON_HOURS = 24


class MlJobError(RuntimeError):
    pass


def last_closed_day(settings: Settings, now: datetime | None = None) -> date:
    now = now or datetime.now(ZoneInfo(settings.source_timezone))
    return now.date() - timedelta(days=1)


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


def store_output(db: Session, output: dict[str, Any], settings: Settings) -> dict[str, int]:
    """Replace day D in `ml_scores`, pick alerts and register them as (not confirmed) predictions."""
    d = date.fromisoformat(output["as_of_date"])
    run_id = output.get("request_id") or f"daily-{d}"
    db.execute(delete(MlScore).where(MlScore.as_of_date == d))
    rows = [_row("gas", d, run_id, r) for r in output.get("gas", [])
            if r.get("is_primary", True) and not (set(r.get("reason_codes") or []) & SKIP_REASONS)]
    rows += [_row("incident", d, run_id, r) for r in output.get("incidents", [])]
    chosen = select_alerts(db, d, rows, settings.ml_top_k_per_day, settings.ml_cooldown_days)
    db.add_all(rows)
    db.flush()

    tz = ZoneInfo(settings.source_timezone)
    calculated_at = datetime.combine(d + timedelta(days=1), time(0), tzinfo=tz)
    predicted = 0
    for row in chosen:
        if row.object_id is None:
            continue
        provider_id = f"{row.bundle}:{d}:{row.channel_id}"
        exists = db.scalar(select(Prediction.id).where(Prediction.provider_id == provider_id,
                                                       Prediction.model_version == row.model_version))
        if exists:
            continue
        # No recommendation and no notification: the shadow score must not create work or alarms by itself.
        db.add(Prediction(provider_id=provider_id, object_id=row.object_id, channel_id=row.channel_id,
                          incident_type=row.incident_type or "gas_threshold_cross", probability=row.score,
                          horizon_hours=PREDICTION_HORIZON_HOURS, calculated_at=calculated_at,
                          predicted_for=calculated_at + timedelta(hours=PREDICTION_HORIZON_HOURS),
                          model_version=row.model_version or "unknown", recommendation=None))
        predicted += 1
    gas = [r for r in rows if r.kind == "gas"]
    return {"gas_rows": len(gas), "gas_scored": sum(r.score is not None for r in gas),
            "incident_rows": len(rows) - len(gas), "alerts_selected": len(chosen), "predictions_created": predicted}


def _default_runtime(settings: Settings, work_dir: Path):
    # Imported here: the ML libraries exist only in the ML environment, not in the API process.
    from app.ml_runtime.lct_ml_runtime import MLRuntime

    return MLRuntime(settings.ml_bundles_path, work_dir=work_dir / "bundles")


def run_daily(as_of: date | None = None, settings: Settings | None = None,
              runtime_factory: Callable[[Settings, Path], Any] | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    d = as_of or last_closed_day(settings)
    start = datetime.combine(d - timedelta(days=settings.ml_export_days), time(0))
    end_exclusive = datetime.combine(d + timedelta(days=1), time(0))
    with tempfile.TemporaryDirectory(prefix="lct_ml_job_") as tmp:
        work = Path(tmp)
        with SessionLocal() as db:
            files = export_journal(db, start, end_exclusive, work)
            channels = export_catalogue(db, work / "catalogue.csv")
        if not files:
            raise MlJobError(f"в журнале нет событий за {start.date()}..{d}")
        runtime = (runtime_factory or _default_runtime)(settings, work)
        try:
            output = runtime.score_day(files, work / "catalogue.csv", d, request_id=f"daily-{d}")
        except Exception as exc:  # bundle-specific ContractError (e.g. INSUFFICIENT_HISTORY) is not importable here
            raise MlJobError(f"{type(exc).__name__}: {exc}") from exc
    with SessionLocal.begin() as db:
        summary = store_output(db, output, settings)
    summary.update({"as_of_date": d.isoformat(), "journal_files": len(files), "channels": channels,
                    "primary_gas": output.get("primary_gas"), "runtime_version": output.get("runtime_version")})
    logger.info("ML daily run finished: %s", summary)
    return summary
