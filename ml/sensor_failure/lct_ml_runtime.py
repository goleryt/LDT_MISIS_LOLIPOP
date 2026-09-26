"""lct_ml_runtime — единая точка входа ML для backend (ЛЦТ 2026, ДЖКХ).

Backend вызывает только этот модуль. Модели лежат ZIP-bundle'ами в одной папке; runtime сам проверяет SHA-256,
распаковывает, загружает predictor каждого bundle и отдаёт единый ответ за сутки D:
- gas        — прогноз газового bundle (сейчас G2 v3) по каналам, с maintenance_context объекта;
- incidents  — прогноз модуля реестра инцидентов по объектам (сейчас заглушка: label_source = stub);
- maintenance_context — по объектам: verified_schedule / possible_recent_silence / unknown.

Замена модели = положить новый ZIP + .sha256 в папку и (если газовых bundle'ов несколько) указать активный
в ACTIVE.json. Код backend не меняется: все поля, признаки, окно и тексты берутся из bundle.

Пример:
    rt = MLRuntime("bundles/")
    out = rt.score_day(["journal_2025.csv", "journal_2026.csv"], "catalogue.csv", "2026-06-20")
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

RUNTIME_VERSION = "lct-ml-runtime-1.1"
SILENCE_RULE_VERSION = "journal_silence_rule_v1"
RECOMMENDATION_VERSION = "manual-advisory-v1"
GAS_TYPE = "Газовый датчик"


class RuntimeContractError(ValueError):
    pass


def _recommendation(code: str, text: str, basis: list[str]) -> dict[str, Any]:
    """Advisory text only: no score threshold, priority change, or automatic work order."""
    return {"version": RECOMMENDATION_VERSION, "code": code, "text_ru": text,
            "basis_codes": basis, "automated_action_allowed": False}


def gas_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    reasons = set(row.get("reason_codes") or [])
    if "ABOVE_THRESHOLD_AT_D" in reasons:
        return _recommendation("CURRENT_ALARM_PROTOCOL",
                               "Газ уже выше порога: проверить текущую тревогу по действующему регламенту. Прогноз здесь неприменим.",
                               ["ABOVE_THRESHOLD_AT_D"])
    if "NO_GAS_READING_AT_D" in reasons:
        return _recommendation("CHECK_TELEMETRY",
                               "Проверить поступление показаний и состояние канала; прогноз не сформирован.",
                               ["NO_GAS_READING_AT_D"])
    if row.get("decision_status") == "abstain":
        return _recommendation("NO_GAS_FORECAST",
                               "Прогноз не сформирован; сверить причину отказа и полноту входных данных.",
                               sorted(reasons) or ["ABSTAIN"])
    context = row.get("maintenance_context")
    if context == "verified_schedule":
        return _recommendation("REVIEW_VERIFIED_PPR",
                               "Сверить прогноз и текущие показания с подтверждённым окном ППР; тревогу не скрывать.",
                               ["GAS_PROXY", "VERIFIED_SCHEDULE"])
    if context == "possible_recent_silence":
        return _recommendation("CHECK_MAINTENANCE_LOG",
                               "Проверить журнал работ и последние показания: недавняя пауза датчиков не подтверждает поверку.",
                               ["GAS_PROXY", "POSSIBLE_RECENT_SILENCE"])
    return _recommendation("REVIEW_GAS_TREND",
                           "Если прогноз выбран для показа, вручную проверить динамику газа и текущие тревоги.",
                           ["GAS_PROXY"])


def incident_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    reason = row.get("abstain_reason")
    if reason:
        return _recommendation("NO_INCIDENT_FORECAST",
                               "Прогноз инцидента не сформирован; проверить указанную причину.",
                               [str(reason)] + (["STUB_LABELS"] if row.get("label_source") == "stub" else []))
    if row.get("label_source") == "stub" or row.get("evidence_level") == "E4":
        return _recommendation("DEMO_ONLY",
                               "Демонстрационный результат на заглушке: не использовать для оперативных действий.",
                               ["STUB_LABELS"])
    return _recommendation("REVIEW_INCIDENT_FACTORS",
                           "Вручную проверить профильные датчики и подтверждённый реестр перед решением.",
                           ["INCIDENT_REGISTER"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LoadedBundle:
    name: str
    kind: str                  # "gas" | "incident"
    module: Any
    bundle: dict[str, Any]
    zip_sha256: str
    dir: Path
    info: dict[str, Any] = field(default_factory=dict)


def _load_module(path: Path, name: str) -> Any:
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # не писать __pycache__ внутрь bundle
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = flag
    return mod


class MLRuntime:
    def __init__(self, bundles_dir: str | Path, work_dir: str | Path | None = None,
                 silence_min_days: int = 4, silence_lookback_days: int = 21, context_history_days: int = 400):
        self.bundles_dir = Path(bundles_dir)
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="lct_ml_"))
        self.silence_min_days = silence_min_days
        self.silence_lookback_days = silence_lookback_days
        self.context_history_days = context_history_days
        self.bundles: list[LoadedBundle] = []
        zips = sorted(self.bundles_dir.glob("*.zip"))
        if not zips:
            raise RuntimeContractError(f"в {self.bundles_dir} нет ZIP-bundle'ов")
        for z in zips:
            self.bundles.append(self._load(z))
        gas = [b for b in self.bundles if b.kind == "gas"]
        if not gas:
            raise RuntimeContractError("нужен хотя бы один газовый bundle (в нём код признаков панели v3)")
        active = self.bundles_dir / "ACTIVE.json"
        want = json.loads(active.read_text(encoding="utf-8")).get("gas") if active.exists() else None
        names = [b.name for b in gas]
        if want is not None and want not in names:
            raise RuntimeContractError(f"ACTIVE.json указывает на {want}, есть только {names}")
        self.primary_gas = want or gas[0].name

    # -------------------------------------------------------------- загрузка
    def _load(self, z: Path) -> LoadedBundle:
        side = z.with_name(z.name + ".sha256")
        if not side.exists():
            raise RuntimeContractError(f"нет {side.name}: bundle без контрольной суммы не загружается")
        got = _sha256(z)
        if side.read_text(encoding="utf-8").split()[0] != got:
            raise RuntimeContractError(f"SHA-256 {z.name} не совпадает с {side.name}")
        name = z.name[:-len(".zip")]
        out = self.work_dir / name
        if out.exists():
            shutil.rmtree(out)
        with zipfile.ZipFile(z) as f:
            for m in f.namelist():
                if m.startswith("/") or ".." in Path(m).parts:
                    raise RuntimeContractError(f"недопустимый путь в {z.name}: {m}")
            f.extractall(out)
        found = sorted(out.rglob("bundle.json"))
        if not found:
            raise RuntimeContractError(f"в {z.name} нет bundle.json")
        bdir = found[0].parent
        spec = json.loads(found[0].read_text(encoding="utf-8"))
        kind = "incident" if "types" in spec else "gas"
        mod = _load_module(bdir / "predictor.py", f"lct_bundle_{re.sub(r'[^0-9A-Za-z_]', '_', name)}")
        bundle = mod.load_bundle(bdir)
        info = {"name": name, "kind": kind, "zip_sha256": got, "model_version": spec.get("model_version"),
                "feature_contract_version": spec.get("feature_contract_version"),
                "evidence_level": spec.get("evidence_level")}
        if kind == "gas":
            info.update({"target_code": spec.get("target_code"), "decision_status": spec.get("decision_status"),
                         "score_kind": spec.get("score_kind")})
        else:
            info.update({"label_source": spec.get("label_source"), "score_meaning": spec.get("score_meaning"),
                         "types": {k: t.get("decision_status") for k, t in spec["types"].items()}})
        return LoadedBundle(name, kind, mod, bundle, got, bdir, info)

    def info(self) -> dict[str, Any]:
        return {"runtime_version": RUNTIME_VERSION, "primary_gas": self.primary_gas,
                "bundles": [b.info for b in self.bundles]}

    # -------------------------------------------------------------- контекст
    def _gas(self) -> LoadedBundle:
        return next(b for b in self.bundles if b.name == self.primary_gas)

    def _context_panel(self, pl: Any, journal_files: list[Path], catalogue_file: Path, d: date) -> tuple[Any, Any]:
        g = self._gas()
        ep = g.module._panel_module(g.bundle)
        start = d - timedelta(days=self.context_history_days)
        flt = (pl.col("дата") <= d.isoformat()) & (pl.col("дата") >= start.isoformat())
        panel, _ = ep.build_event_panel(pl, journal_files, catalogue_file,
                                        g.bundle["dir"] / "features_v3" / "state_taxonomy_v3.json",
                                        config=g.bundle["spec"].get("panel_config", {}), log=lambda *a: None,
                                        channel_filter=flt, data_end=datetime.combine(d, time(23, 59, 59)))
        return panel, ep

    def maintenance_context(self, pl: Any, panel: Any, d: date, obj_raw: dict[str, str],
                            ppr_windows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
        """По объектам на конец D. possible_recent_silence: все газовые каналы объекта не давали показаний
        ≥ silence_min_days суток подряд, молчание закончилось в [D − lookback; D − 1], показания вернулись к D
        (молчание ограничено реальными показаниями с обеих сторон, как в аудите 17 v2). Только прошлое."""
        start = d - timedelta(days=self.context_history_days)
        gas = (panel.filter((pl.col("тип_датчика") == GAS_TYPE) & pl.col("d_object_key").is_not_null())
               .select("d_object_key", pl.col("d_cutoff_date").alias("day"),
                       pl.col("gas_max").cast(pl.Float64).fill_nan(None).is_not_null().alias("reading"))
               .group_by("d_object_key", "day").agg(pl.col("reading").any()))
        out: dict[str, dict[str, Any]] = {}
        days = [start + timedelta(days=i) for i in range((d - start).days + 1)]
        for key, grp in gas.group_by("d_object_key"):
            key = key[0] if isinstance(key, tuple) else key
            seen = {r[0] for r in grp.filter(pl.col("reading")).select("day").iter_rows()}
            flags = [day in seen for day in days]
            best = None
            i = 0
            while i < len(flags):
                if flags[i]:
                    i += 1
                    continue
                j = i
                while j < len(flags) and not flags[j]:
                    j += 1
                bounded = i > 0 and j < len(flags)            # показания до и после молчания
                length = j - i
                ended_ago = (d - days[j - 1]).days
                if bounded and length >= self.silence_min_days and 1 <= ended_ago <= self.silence_lookback_days:
                    best = {"silence_length_days": length, "silence_ended_days_ago": ended_ago}
                i = j
            raw = obj_raw.get(key)
            if raw is not None and best:
                out[raw] = {"maintenance_context": "possible_recent_silence", "maintenance_source": SILENCE_RULE_VERSION, **best}
        for w in ppr_windows or []:
            s, e = date.fromisoformat(str(w["start"])[:10]), date.fromisoformat(str(w["end"])[:10])
            if s <= d <= e:
                out[str(w["ид_объект"])] = {"maintenance_context": "verified_schedule", "maintenance_source": "schedule_ppr",
                                            "schedule_start": s.isoformat(), "schedule_end": e.isoformat()}
        return out

    # -------------------------------------------------------------- скоринг
    def score_day(self, journal_files: list[str | Path], catalogue_file: str | Path, as_of_date: str | date,
                  request_id: str | None = None, recent_incidents: list[dict[str, Any]] | None = None,
                  ppr_windows: list[dict[str, Any]] | None = None, all_gas_bundles: bool = False) -> dict[str, Any]:
        """Один вызов в сутки по всем объектам. journal_files — выгрузки журнала с историей ≥ 400 суток до D
        (требование газового bundle); catalogue_file — справочник каналов (ид_канала_данных, ид_объект, тип_датчика…).
        ppr_windows: [{"ид_объект", "start", "end"}] — окна ППР с подтверждённым соответствием объектов (опционально).
        all_gas_bundles=True — считать все газовые bundle'ы (shadow-сравнение), иначе только активный."""
        import polars as pl

        if not isinstance(as_of_date, date):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(as_of_date or "")):
                raise RuntimeContractError("as_of_date обязательна, формат YYYY-MM-DD")
            as_of_date = date.fromisoformat(str(as_of_date))
        d = as_of_date
        files = [Path(p) for p in journal_files]
        cat_path = Path(catalogue_file)
        panel, ep = self._context_panel(pl, files, cat_path, d)
        cat = ep.read_catalogue(pl, cat_path)
        obj_ids = [str(x) for x in cat["ид_объект"].drop_nulls().unique().to_list()] if "ид_объект" in cat.columns else []
        obj_raw = {ep.pseudo_key(o): o for o in obj_ids}
        ch_obj = ({str(a): (None if b is None else str(b)) for a, b in cat.select("ид_канала_данных", "ид_объект").iter_rows()}
                  if "ид_объект" in cat.columns else {})
        ctx = self.maintenance_context(pl, panel, d, obj_raw, ppr_windows)
        unknown = {"maintenance_context": "unknown", "maintenance_source": None}

        gas_out: list[dict[str, Any]] = []
        for b in self.bundles:
            if b.kind != "gas" or (not all_gas_bundles and b.name != self.primary_gas):
                continue
            feats = b.module.build_features(files, cat_path, d, b.bundle)
            if request_id is not None:
                feats["request_id"] = request_id
            for r in b.module.predict(feats, b.bundle):
                obj = ch_obj.get(r.get("ид_канала_данных"))
                r.update({"bundle": b.name, "is_primary": b.name == self.primary_gas, "ид_объект": obj,
                          **ctx.get(obj, unknown)})
                r["recommendation"] = gas_recommendation(r)
                gas_out.append(r)

        inc_out: list[dict[str, Any]] = []
        inc = [b for b in self.bundles if b.kind == "incident"]
        if inc:
            rows = panel.filter((pl.col("d_cutoff_date") == d) & pl.col("d_object_key").is_not_null())
            rows = rows.with_columns(pl.col("d_object_key").replace_strict(obj_raw, default=None).alias("ид_объект"))
            rows = rows.filter(pl.col("ид_объект").is_not_null())
            for b in inc:
                for r in b.module.predict(rows, b.bundle, d, request_id=request_id, object_col="ид_объект",
                                          recent_incidents=recent_incidents):
                    meaning = b.bundle["spec"].get("score_meaning") or (
                        "demo-score на искусственных метках, НЕ вероятность подтверждённого инцидента"
                        if b.bundle["spec"].get("label_source") == "stub" else None)
                    r.update({"bundle": b.name, "score_meaning": meaning,
                              **ctx.get(r["ид_объект"], unknown)})
                    r["recommendation"] = incident_recommendation(r)
                    inc_out.append(r)
        return {"runtime_version": RUNTIME_VERSION, "as_of_date": d.isoformat(), "request_id": request_id,
                "bundles": [b.info for b in self.bundles], "primary_gas": self.primary_gas,
                "gas": gas_out, "incidents": inc_out,
                "maintenance_context": [{"ид_объект": o, **v} for o, v in sorted(ctx.items())]}
