"""Inference helpers for the experimental cold-start risk model.

Delivered as-is by the ML workstream alongside
``experimental_cold_start_model.joblib`` and ``model_contract.json``.
Do not edit the scoring logic here without updating the model bundle;
this file must stay in lockstep with how the bundle was trained.

The score is a calibrated probability of an *observable* proxy state
(``failure_state_presence_24_48h_proxy_v1``), not a confirmed physical
failure. See ``model_contract.json`` and ``decision_status`` in the
output ("experimental_shadow").
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

TARGET_CODE = "failure_state_presence_24_48h_proxy_v1"


def load_bundle(path: str | Path):
    return joblib.load(path)


def _calibrate(spec, raw):
    raw = np.clip(np.asarray(raw, dtype=float), 1e-6, 1 - 1e-6)
    if spec["kind"] == "identity":
        return raw
    logits = np.log(raw / (1 - raw))
    z = float(spec["coef"]) * logits + float(spec["intercept"])
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def _robust_score(data, bundle):
    result = np.zeros(len(data), dtype=float)
    sensor = data["тип_датчика"].fillna("__MISSING__").astype(str)
    for sensor_type in sensor.unique():
        mask = sensor == sensor_type
        spec = bundle["robust_stats"].get(sensor_type, bundle["robust_stats"]["__GLOBAL__"])
        cols = []
        for name in bundle["robust_numeric"]:
            center, scale = spec["center"].get(name), spec["scale"].get(name)
            if center is None or scale is None:
                continue
            values = pd.to_numeric(data.loc[mask, name], errors="coerce").to_numpy(float)
            cols.append(np.minimum(np.abs((values - center) / scale), 20.0))
        if cols:
            with np.errstate(invalid="ignore"):
                score = np.nanmean(np.column_stack(cols), axis=1)
            result[np.flatnonzero(mask.to_numpy())] = np.nan_to_num(score, nan=0.0)
    return result


def _frame(records, bundle, features, cold=False):
    data = pd.DataFrame(records)
    missing = sorted(set(bundle["required_input_fields"]) - set(data.columns))
    if missing:
        raise ValueError(f"Missing model fields: {missing}")
    category_names = set(bundle["category_levels"])
    for name in features:
        if name not in category_names:
            data[name] = pd.to_numeric(data[name], errors="coerce")
    if cold:
        data["d_missing_feature_count"] = data[bundle["cold_base_numeric"]].isna().sum(axis=1)
        data["d_type_robust_deviation"] = _robust_score(data, bundle)
    for name, levels in bundle["category_levels"].items():
        values = data[name].fillna("__MISSING__").astype(str)
        data[name] = values.astype(pd.CategoricalDtype(categories=levels))
    return data[features]


def predict(records, bundle):
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty list")
    base_raw = bundle["base_model"].predict_proba(
        _frame(records, bundle, bundle["warm_features"])
    )[:, 1]
    base = _calibrate(bundle["base_calibration"], base_raw)
    if bundle["selected_policy"] == "cold_start_router":
        cold_raw = bundle["cold_model"].predict_proba(
            _frame(records, bundle, bundle["cold_features"], cold=True)
        )[:, 1]
        warm_raw = bundle["warm_model"].predict_proba(
            _frame(records, bundle, bundle["warm_features"])
        )[:, 1]
        cold = _calibrate(bundle["cold_calibration"], cold_raw)
        warm = _calibrate(bundle["warm_calibration"], warm_raw)
        cold_mask = np.asarray([
            int(row["d_observed_days_so_far"]) <= bundle["cold_days"] for row in records
        ])
        score = np.where(cold_mask, cold, warm)
        route = np.where(cold_mask, "cold_start", "mature_history")
        threshold = float(bundle["router_threshold"])
    else:
        score = base
        route = np.asarray(["base_lightgbm"] * len(records))
        threshold = float(bundle["base_threshold"])
    output = []
    for index, (row, value, selected_route) in enumerate(zip(records, score, route)):
        as_of = date.fromisoformat(str(row["as_of_date"]))
        eligible = not bool(row["d_current_failure_state"])
        output.append({
            "request_index": index,
            "target_code": TARGET_CODE,
            "as_of_date": as_of.isoformat(),
            "window_start": (as_of + timedelta(days=2)).isoformat(),
            "window_end_exclusive": (as_of + timedelta(days=3)).isoformat(),
            "score": float(value) if eligible else None,
            "score_kind": "calibrated_observable_state_proxy_probability",
            "route": str(selected_route),
            "threshold": threshold,
            "is_alert_candidate": bool(eligible and value >= threshold),
            "eligibility_status": "eligible" if eligible else "already_in_proxy_state",
            "decision_status": "experimental_shadow",
            "model_version": bundle["model_version"],
        })
    return output
