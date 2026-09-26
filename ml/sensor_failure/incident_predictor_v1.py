"""Predictor модуля прогноза инцидентов по реестру (incident_head v1). Кладётся в bundle как predictor.py.

Единственный источник кода агрегации «каналы → объект»: обучение (incident_head_v1.py) импортирует отсюда
aggregate_objects, поэтому признаки при обучении и при выдаче считаются одним и тем же кодом.

Вход predict: канальные v3-векторы на конец суток D (как для газового bundle) + ключ объекта и тип датчика.
Выход: по одной записи на (объект, D, тип инцидента) с калиброванной вероятностью начала инцидента в [D+2; D+3).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

AGG_VERSION = "object-agg-v1"
INCIDENT_TYPES = {"пожар": "fire", "подтопление": "flood", "нсд": "access"}
TYPE_RU = {v: k for k, v in INCIDENT_TYPES.items()}
# Группы типов датчиков заданы заранее по названию (без взгляда на метки); первая подходящая группа выигрывает.
GROUPS = {
    "fire": r"газ|дым|тепл|температ|пожар|пламен|извещат",
    "flood": r"затоп|уров|насос|вод|дренаж|приямк|залив",
    "access": r"движ|двер|люк|охран|кд|доступ|проник",
}
GROUP_RU = {"fire": "пожарные датчики", "flood": "датчики воды и насосы", "access": "датчики доступа", "other": "прочие датчики"}
CHANNEL_SUM = ["n_events", "n_alarm", "n_link_fault", "n_power_off", "f_n_events_7d", "f_n_alarm_7d", "f_n_alarm_30d",
               "f_n_event_alarm_7d", "f_n_flood_7d", "f_n_flood_30d", "f_n_link_fault_7d", "f_n_power_off_7d",
               "f_link_onset_strict_7d", "f_power_onset_strict_7d", "f_n_tech_like_7d", "f_gas_ge_thr_n_7d",
               "f_gas_cross_n_30d"]
GROUP_COLS = ["n_alarm", "n_events", "f_n_alarm_7d", "f_n_alarm_30d", "f_n_events_7d"]
COL_RU = {"n_events": "события за сутки D", "n_alarm": "тревоги за сутки D", "n_link_fault": "потери связи за сутки D",
          "n_power_off": "обесточивания за сутки D", "f_n_events_7d": "события за 7 сут", "f_n_alarm_7d": "тревоги за 7 сут",
          "f_n_alarm_30d": "тревоги за 30 сут", "f_n_event_alarm_7d": "тревожные события за 7 сут",
          "f_n_flood_7d": "сигналы затопления за 7 сут", "f_n_flood_30d": "сигналы затопления за 30 сут",
          "f_n_link_fault_7d": "потери связи за 7 сут", "f_n_power_off_7d": "обесточивания за 7 сут",
          "f_link_onset_strict_7d": "новые потери связи за 7 сут", "f_power_onset_strict_7d": "новые обесточивания за 7 сут",
          "f_n_tech_like_7d": "технические значения за 7 сут", "f_gas_ge_thr_n_7d": "газ ≥ 1 % за 7 сут",
          "f_gas_cross_n_30d": "пересечения газа 1 % за 30 сут"}
# Правило-baseline для каждого типа: профильные признаки на конец D (сумма)
RULE_COLS = {"fire": ["grp_fire__f_n_alarm_7d", "obj__f_gas_ge_thr_n_7d"],
             "flood": ["grp_flood__f_n_alarm_7d", "obj__f_n_flood_7d"],
             "access": ["grp_access__f_n_alarm_7d"]}
KEYS = ["object_ref", "d_cutoff_date"]


class ContractError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def group_expr(pl: Any, type_col: str = "тип_датчика") -> Any:
    t = pl.col(type_col).cast(pl.String).fill_null("").str.to_lowercase()
    expr = pl.lit("other")
    for g in reversed(list(GROUPS)):
        expr = pl.when(t.str.contains(GROUPS[g])).then(pl.lit(g)).otherwise(expr)
    return expr.alias("_grp")


def aggregate_objects(pl: Any, channels: Any, object_col: str = "d_object_key") -> Any:
    """Каналы (LazyFrame/DataFrame, строка = канал × D) → объект × D. Колонки, которых нет во входе, пропускаются;
    возвращаются также служебные колонки следа _fp_<тип> (профильные тревоги самих суток; не признаки)."""
    eager = not isinstance(channels, pl.LazyFrame)
    lf = channels.lazy() if eager else channels
    cols = set(lf.collect_schema().names())
    lf = lf.filter(pl.col(object_col).is_not_null()).with_columns(group_expr(pl))
    aggs = [pl.len().alias("obj__n_channels")]
    aggs += [pl.col(c).cast(pl.Float64).sum().alias(f"obj__{c}") for c in CHANNEL_SUM if c in cols]
    for g in list(GROUPS) + ["other"]:
        m = pl.col("_grp") == g
        aggs.append(m.sum().cast(pl.Float64).alias(f"grp_{g}__n_channels"))
        aggs += [pl.col(c).cast(pl.Float64).filter(m).sum().alias(f"grp_{g}__{c}") for c in GROUP_COLS if c in cols]
    if "link_state" in cols:
        aggs.append((pl.col("link_state").cast(pl.String) != "O").mean().cast(pl.Float64).alias("obj__share_link_not_ok"))
    if "power_state" in cols:
        aggs.append((pl.col("power_state").cast(pl.String) == "F").mean().cast(pl.Float64).alias("obj__share_power_off"))
    if "gas_max" in cols:
        g = pl.col("gas_max").cast(pl.Float64).fill_nan(None)
        aggs += [g.max().alias("obj__gas_max"), (g >= 1.0).sum().cast(pl.Float64).alias("_gas_ge1_channels")]
    if "f_gas_max_7d" in cols:
        aggs.append(pl.col("f_gas_max_7d").cast(pl.Float64).fill_nan(None).max().alias("obj__f_gas_max_7d"))
    out = lf.group_by(pl.col(object_col).alias("object_ref"), "d_cutoff_date").agg(aggs)
    names = out.collect_schema().names()
    fire_fp = pl.col("grp_fire__n_alarm").fill_null(0) if "grp_fire__n_alarm" in names else pl.lit(0.0)
    if "_gas_ge1_channels" in names:
        fire_fp = fire_fp + pl.col("_gas_ge1_channels").fill_null(0)
    fp = {"fire": fire_fp,
          "flood": pl.col("grp_flood__n_alarm").fill_null(0) if "grp_flood__n_alarm" in names else pl.lit(0.0),
          "access": pl.col("grp_access__n_alarm").fill_null(0) if "grp_access__n_alarm" in names else pl.lit(0.0)}
    out = out.with_columns([e.cast(pl.Float64).alias(f"_fp_{k}") for k, e in fp.items()]
                           + [pl.col("d_cutoff_date").dt.month().cast(pl.Float64).alias("d_month")])
    drop = [c for c in ["_gas_ge1_channels"] if c in names]
    out = out.drop(drop)
    return out.collect() if eager else out


def feature_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if c not in KEYS and not c.startswith("_")]


def humanize(feature: str) -> str:
    if feature == "d_month":
        return "месяц (сезонность)"
    m = re.match(r"^(obj|grp_(\w+?))__(.+)$", feature)
    if not m:
        return feature
    scope = "объект" if m.group(1) == "obj" else GROUP_RU.get(m.group(2), m.group(2))
    col = m.group(3)
    names = {"n_channels": "число каналов", "share_link_not_ok": "доля каналов без связи",
             "share_power_off": "доля обесточенных каналов", "gas_max": "максимум газа за сутки D",
             "f_gas_max_7d": "максимум газа за 7 сут"}
    return f"{scope}: {names.get(col, COL_RU.get(col, col))}"


def rule_raw(frame: Any, kind: str) -> np.ndarray:
    s = np.zeros(frame.height)
    for c in RULE_COLS[kind]:
        if c in frame.columns:
            s = s + np.nan_to_num(frame[c].cast(float).to_numpy(), nan=0.0)
    return s


def _platt(raw: np.ndarray, p: dict[str, Any] | None, kind: str) -> np.ndarray:
    if p is None:
        return np.full(len(raw), np.nan)
    if kind == "probability":
        q = np.clip(raw, 1e-6, 1 - 1e-6)
        z = np.log(q / (1 - q))
    else:
        z = np.log1p(np.maximum(raw, 0))
    return 1 / (1 + np.exp(-(p["coef"] * z + p["intercept"])))


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------
def load_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    import lightgbm as lgb

    bdir = Path(bundle_dir)
    sums = json.loads((bdir / "SHA256SUMS.json").read_text(encoding="utf-8"))
    for name, sha in sums.items():
        if _sha256_bytes((bdir / name).read_bytes()) != sha:
            raise ContractError(f"SHA-256 {name} не совпадает с SHA256SUMS.json")
    spec = json.loads((bdir / "bundle.json").read_text(encoding="utf-8"))
    models = {}
    for kind, t in spec["types"].items():
        if t.get("model_file"):
            booster = lgb.Booster(model_str=(bdir / t["model_file"]).read_text(encoding="utf-8"))
            if list(booster.feature_name()) != [f.replace(" ", "_") for f in spec["features"]]:
                raise ContractError(f"признаки модели {kind} не совпадают с контрактом")
            models[kind] = booster
    return {"spec": spec, "models": models, "dir": str(bdir)}


def _as_frame(pl: Any, records: Any) -> Any:
    if hasattr(records, "lazy"):
        return records
    if isinstance(records, list):
        return pl.DataFrame(records, infer_schema_length=None)
    return pl.from_pandas(records)


def predict(channel_records: Any, bundle: dict[str, Any], as_of_date: str | date, request_id: str | None = None,
            object_col: str = "ид_объект", recent_incidents: list[dict[str, Any]] | None = None,
            top_factors: int = 3) -> list[dict[str, Any]]:
    """channel_records: канальные v3-векторы на конец as_of_date (polars/pandas/list of dict) с колонками object_col
    и тип_датчика. recent_incidents: [{object_col: …, "тип_инцидента": …, "начало": "YYYY-MM-DD"}] — начатые в [D−6; D]."""
    import polars as pl

    spec = bundle["spec"]
    if not isinstance(as_of_date, date):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(as_of_date or "")):
            raise ContractError("as_of_date обязательна, формат YYYY-MM-DD")
        as_of_date = date.fromisoformat(str(as_of_date))
    ch = _as_frame(pl, channel_records)
    if object_col not in ch.columns or "тип_датчика" not in ch.columns:
        raise ContractError(f"нужны колонки {object_col} и тип_датчика")
    ch = ch.with_columns(pl.lit(as_of_date).alias("d_cutoff_date"))
    obj = aggregate_objects(pl, ch, object_col=object_col)
    feats = spec["features"]
    for f in feats:
        if f not in obj.columns:
            obj = obj.with_columns(pl.lit(None, dtype=pl.Float64).alias(f))
    x = obj.select([pl.col(f).cast(pl.Float64) for f in feats]).to_numpy()
    ongoing = {(str(r[object_col]), INCIDENT_TYPES.get(r["тип_инцидента"], r["тип_инцидента"]))
               for r in (recent_incidents or [])
               if as_of_date - timedelta(days=6) <= date.fromisoformat(str(r["начало"])[:10]) <= as_of_date}
    win_s, win_e = as_of_date + timedelta(days=2), as_of_date + timedelta(days=3)
    covered = spec["coverage"].get("objects", "all")
    covered = None if covered == "all" else {str(o) for o in covered}
    out: list[dict[str, Any]] = []
    refs = [str(r) for r in obj["object_ref"].to_list()]
    for kind, t in spec["types"].items():
        status = t["decision_status"]
        score = np.full(len(refs), np.nan)
        contrib = None
        if status in ("experimental_shadow", "demo_stub") and kind in bundle["models"]:
            b = bundle["models"][kind]
            score = _platt(b.predict(x), t["platt"], "probability")
            if top_factors:
                contrib = b.predict(x, pred_contrib=True)[:, :-1]
        elif status == "baseline_only":
            score = _platt(rule_raw(obj, kind), t["rule_platt"], "count")
        for i, ref in enumerate(refs):
            reason = None
            if status == "insufficient_labels":
                reason = "INSUFFICIENT_LABELS"
            elif covered is not None and ref not in covered:
                reason = "OBJECT_NOT_COVERED"
            elif (ref, kind) in ongoing:
                reason = "ONGOING_INCIDENT"
            s = None if reason or np.isnan(score[i]) else float(score[i])
            factors = []
            if s is not None and contrib is not None:
                order = np.argsort(-contrib[i])[:top_factors]
                factors = [{"feature": humanize(feats[j]), "direction": "up"} for j in order if contrib[i, j] > 0]
            elif s is not None and status == "baseline_only":
                factors = [{"feature": humanize(c), "direction": "up"} for c in RULE_COLS[kind]]
            out.append({"request_id": request_id, object_col: ref, "as_of_date": as_of_date.isoformat(),
                        "incident_type": TYPE_RU[kind], "window_start": win_s.isoformat(),
                        "window_end_exclusive": win_e.isoformat(), "score": s,
                        "score_kind": "calibrated_probability" if s is not None else None,
                        "evidence_level": spec["evidence_level"], "label_source": spec["label_source"],
                        "decision_status": status, "operational_ready": False, "abstain_reason": reason,
                        "top_factors": factors, "model_version": spec["model_version"],
                        "feature_contract_version": spec["feature_contract_version"]})
    return out
