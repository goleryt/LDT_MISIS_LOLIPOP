"""predictor.py — исполняемый скоринг газового proxy v3 для backend (shadow-режим).

Что считает: score будущего наблюдаемого строгого пересечения газового порога (1 %) снизу вверх
в окне [D+2; D+3) по признакам, доступным к концу суток D. Это НЕ вероятность пожара и НЕ подтверждённый
инцидент: метка — наблюдаемое событие журнала; Platt-калибровка сделана на строках с известным исходом.

Зависимости: numpy, pandas, lightgbm (скоринг); polars — только для build_features.
Модель хранится текстом LightGBM (model.txt), калибровка и контракт — в bundle.json. Pickle не используется.

    from predictor import load_bundle, build_features, predict
    bundle = load_bundle("gas_cross_v3_bundle")
    records = build_features(["journal_extract.csv"], "catalogue.csv", "2026-09-24", bundle)
    results = predict(records, bundle)

Backend применяет суточный бюджет (top-k) и cooldown поверх score; автоматические заявки по score выключены.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np

PASSTHROUGH = ("as_of_date", "ид_канала_данных", "request_id")
NA_LEVEL = "__NA__"


class ContractError(ValueError):
    """Вход не соответствует feature_contract.json."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Загружает bundle.json и model.txt; сверяет SHA-256 всех файлов из SHA256SUMS.json и признаки модели с контрактом.
    SHA-256 самого ZIP лежит отдельно (gas_cross_v3_bundle.zip.sha256) и проверяется при получении архива."""
    import lightgbm as lgb

    d = Path(bundle_dir)
    sums_path = d / "SHA256SUMS.json"
    if not sums_path.exists():
        raise ContractError("нет SHA256SUMS.json — bundle неполный")
    sums = json.loads(sums_path.read_text(encoding="utf-8"))
    bad = [name for name, sha in sums.items()
           if not (d / name).is_file() or _sha256_bytes((d / name).read_bytes()) != sha]
    if bad:
        raise ContractError(f"SHA-256 не совпадает или файла нет: {bad}")
    spec = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
    model_bytes = (d / "model.txt").read_bytes()
    if _sha256_bytes(model_bytes) != spec["model_sha256"]:
        raise ContractError("SHA-256 model.txt не совпадает с bundle.json")
    booster = lgb.Booster(model_str=model_bytes.decode("utf-8"))
    names = [f["name"] for f in spec["features"]]
    if booster.num_feature() != len(names) or booster.feature_name() != names:
        raise ContractError("признаки модели не совпадают с контрактом bundle.json")
    return {"spec": spec, "booster": booster, "dir": d}


# ---------------------------------------------------------------------------
# Признаки: тот же причинный код, что строил обучающую панель (ноутбук 14)
# ---------------------------------------------------------------------------
def _panel_module(bundle: dict[str, Any]) -> Any:
    path = bundle["dir"] / "features_v3" / "event_panel_v3.py"
    spec = importlib.util.spec_from_file_location("gas_bundle_event_panel_v3", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_features(journal_files: list[str | Path], catalogue_file: str | Path, as_of_date: str | date,
                   bundle: dict[str, Any], channels: list[str] | None = None,
                   min_history_days: int | None = None) -> Any:
    """Причинные v3-признаки на конец суток as_of_date (D) для каналов из выгрузки журнала.

    journal_files — CSV/parquet с колонками журнала (ид_события, ид_канала_данных, дата, время, тревожное,
    значение_датчика); catalogue_file — справочник каналов. События позже D отбрасываются до сборки.
    История: ≥ bundle.json → history_days_required суток до D (иначе «неограниченные» признаки — давность
    последней смены состояния/последнего onset, последнее значение — могут стать null и разойтись с train).
    Если самая ранняя дата в переданной выгрузке позже D − history_days_required — ContractError
    (INSUFFICIENT_HISTORY): score не выдаётся. Рекомендуется передавать всю доступную историю газовых каналов:
    только тогда давность последней смены состояния/onset и последнее значение совпадают с обучающей панелью.
    Возвращает pandas.DataFrame: as_of_date, ид_канала_данных и признаки контракта (по одной строке на канал,
    у которого были события в [D−6; D]).
    """
    import polars as pl

    spec = bundle["spec"]
    ep = _panel_module(bundle)
    d = as_of_date if isinstance(as_of_date, date) else date.fromisoformat(str(as_of_date))
    flt = pl.col("дата") <= d.isoformat()
    if channels is not None:
        flt = flt & pl.col("ид_канала_данных").is_in([str(c) for c in channels])
    files = [Path(p) for p in journal_files]
    need = int(spec.get("history_days_required", 0) if min_history_days is None else min_history_days)
    first = min((ep._scan_source(pl, f).filter(flt).select(pl.col("дата").min()).collect().item() for f in files),
                key=lambda x: x or "9999-12-31")
    if first is None:
        raise ContractError("INSUFFICIENT_HISTORY: в выгрузке нет событий до D")
    if date.fromisoformat(str(first)[:10]) > d - timedelta(days=need):
        raise ContractError(f"INSUFFICIENT_HISTORY: история с {str(first)[:10]}, нужно не позже "
                            f"{(d - timedelta(days=need)).isoformat()} ({need} суток до D)")
    panel, _ = ep.build_event_panel(pl, files, Path(catalogue_file), bundle["dir"] / "features_v3" / "state_taxonomy_v3.json",
                                    config=spec["panel_config"], log=lambda *a: None, channel_filter=flt,
                                    data_end=datetime.combine(d, time(23, 59, 59)))
    rows = panel.filter(pl.col("d_cutoff_date") == d)
    raw_ids = set()
    for f in files:
        raw_ids.update(ep._scan_source(pl, f).filter(flt).select("ид_канала_данных").unique().collect()
                       ["ид_канала_данных"].to_list())
    keys = ep.key_map(pl, raw_ids, "d_channel_key")
    rows = rows.join(keys, on="d_channel_key", how="left").rename({"raw": "ид_канала_данных"})
    names = [f["name"] for f in spec["features"]]
    out = rows.select([pl.lit(d.isoformat()).alias("as_of_date"), "ид_канала_данных"] + names)
    return out.to_pandas()


# ---------------------------------------------------------------------------
# Скоринг
# ---------------------------------------------------------------------------
def _frame(records: Any, spec: dict[str, Any]) -> tuple[Any, Any]:
    import pandas as pd

    df = records if isinstance(records, pd.DataFrame) else pd.DataFrame(list(records))
    df = df.reset_index(drop=True)
    if "as_of_date" not in df.columns:
        raise ContractError("нет обязательного поля as_of_date (YYYY-MM-DD, конец суток D)")
    for i, v in enumerate(df["as_of_date"].tolist()):
        text = v.isoformat()[:10] if isinstance(v, (date, datetime)) else str(v)
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                raise ValueError
            date.fromisoformat(text)
        except ValueError as exc:
            raise ContractError(f"as_of_date в строке {i}: ожидается дата YYYY-MM-DD, получено {v!r}") from exc
    df["as_of_date"] = [v.isoformat()[:10] if isinstance(v, (date, datetime)) else str(v) for v in df["as_of_date"]]
    names = [f["name"] for f in spec["features"]]
    missing = [n for n in names if n not in df.columns]
    if missing:
        raise ContractError(f"нет обязательных признаков: {missing[:10]}{' …' if len(missing) > 10 else ''}")
    extra = [c for c in df.columns if c not in names and c not in PASSTHROUGH]
    if extra:
        raise ContractError(f"лишние поля (не из контракта): {extra[:10]}")
    x = pd.DataFrame(index=df.index)
    for f in spec["features"]:
        col = df[f["name"]]
        if f["kind"] == "categorical":
            v = col.astype(object).where(col.notna(), NA_LEVEL).astype(str)
            v = v.where(v.isin(f["levels"]), None)                  # неизвестный уровень → пропуск (как в train)
            x[f["name"]] = pd.Categorical(v, categories=f["levels"])
        else:
            try:
                x[f["name"]] = pd.to_numeric(col, errors="raise").astype("float32")
            except (TypeError, ValueError) as exc:
                raise ContractError(f"признак {f['name']}: ожидается число или null") from exc
    return df, x


def _calibrate(raw: np.ndarray, platt: dict[str, float]) -> np.ndarray:
    p = np.clip(raw, 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    return 1.0 / (1.0 + np.exp(-(platt["coef"] * z + platt["intercept"])))


def eligibility(df: Any, spec: dict[str, Any]) -> tuple[np.ndarray, list[list[str]]]:
    """Runtime eligibility на конец D (как gas_elig в панели 14): газовый поток в [D−6; D] и последнее показание < порога."""
    import pandas as pd

    thr = float(spec["eligibility"]["gas_threshold_percent"])
    n7 = pd.to_numeric(df["f_gas_n_7d"], errors="coerce").to_numpy(dtype=float)
    last = pd.to_numeric(df["f_gas_last"], errors="coerce").to_numpy(dtype=float)
    ok = np.zeros(len(df), dtype=bool)
    reasons: list[list[str]] = []
    for i in range(len(df)):
        if not (n7[i] > 0):
            reasons.append(["NOT_GAS_STREAM"])
        elif math.isnan(last[i]):
            reasons.append(["NO_GAS_READING_AT_D"])
        elif last[i] >= thr:
            reasons.append(["ABOVE_THRESHOLD_AT_D"])
        else:
            ok[i] = True
            reasons.append([])
    return ok, reasons


def predict(records: Any, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """records: список dict или pandas.DataFrame с признаками контракта (+ as_of_date, ид_канала_данных, request_id).
    Для неподходящих строк score = null и decision_status = abstain с причиной."""
    spec = bundle["spec"]
    df, x = _frame(records, spec)
    ok, reasons = eligibility(df, spec)
    raw = np.full(len(df), np.nan)
    if ok.any():
        raw[ok] = bundle["booster"].predict(x[ok])
    cal = np.where(ok, _calibrate(np.nan_to_num(raw, nan=0.5), spec["platt"]), np.nan)
    w = spec["window"]
    out = []
    for i in range(len(df)):
        d = date.fromisoformat(str(df["as_of_date"].iloc[i])[:10])
        item = {
            "request_index": i,
            "as_of_date": d.isoformat(),
            "observation_cutoff_date": d.isoformat(),      # признаки — по событиям до конца этих суток
            "target_code": spec["target_code"],
            "model_version": spec["model_version"],
            "feature_contract_version": spec["feature_contract_version"],
            "evidence_level": spec["evidence_level"],
            "incident_type": spec["incident_type"],
            "score": float(cal[i]) if ok[i] else None,
            "raw_score": float(raw[i]) if ok[i] else None,
            "score_kind": spec["score_kind"],
            "decision_status": spec["decision_status"] if ok[i] else "abstain",
            "reason_codes": reasons[i],
            "window_start": (d + timedelta(days=w["start_offset_days"])).isoformat(),
            "window_end_exclusive": (d + timedelta(days=w["end_offset_days_exclusive"])).isoformat(),
            "evidence_scope": spec["evidence_scope"],
            "operational_ready": spec["operational_ready"],
            "not_a_confirmed_incident": True,
            "not_fire_probability": True,
        }
        for k in ("ид_канала_данных", "request_id"):
            if k in df.columns:
                item[k] = None if df[k].isna().iloc[i] else str(df[k].iloc[i])
        out.append(item)
    return out
