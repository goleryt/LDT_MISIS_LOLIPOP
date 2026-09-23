"""Cold-start LightGBM research and experimental backend bundle.

The implementation uses only the de-identified daily panel. Channel/object
keys are grouping aids and never model inputs or exported backend fields.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any
import zipfile

import numpy as np

try:
    from kaggle_runtime import (
        CATEGORICAL_FEATURES,
        NUMERIC_FEATURES,
        _fit_calibrator,
        _sample_training,
        _select_threshold,
        _smoke_frame,
        _to_pandas,
        episode_metrics,
        point_metrics,
    )
except ImportError:  # Standalone notebook executes kaggle_runtime first.
    pass


TARGET = "target_failure_state_onset_24h"
MODEL_VERSION = "cold-start-router-proxy-v1"
TARGET_CODE = "failure_state_presence_24_48h_proxy_v1"

COLD_BASE_NUMERIC = [
    "d_event_count_24h",
    "d_alarm_count_24h",
    "d_alarm_share_24h",
    "d_value_numeric_mean_24h",
    "d_value_numeric_min_24h",
    "d_value_numeric_max_24h",
    "d_value_numeric_std_24h",
    "d_value_numeric_last",
    "d_state_n_unique_24h",
    "d_gap_days_since_previous",
    "d_event_count_previous_24h",
    "d_alarm_count_previous_24h",
    "d_alarm_share_previous_24h",
    "d_value_numeric_previous",
    "d_catalogue_match",
]
COLD_DERIVED_NUMERIC = [
    "d_observed_days_so_far",
    "d_missing_feature_count",
    "d_type_robust_deviation",
]
ROBUST_NUMERIC = [
    name for name in COLD_BASE_NUMERIC if name != "d_catalogue_match"
]
COLD_FEATURES = COLD_BASE_NUMERIC + COLD_DERIVED_NUMERIC + list(CATEGORICAL_FEATURES)
WARM_FEATURES = list(NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)


def add_causal_maturity(panel: Any, cold_days: int) -> Any:
    """Add history length using current and past rows only."""
    import polars as pl

    if cold_days < 1:
        raise ValueError("cold_days must be positive")
    return (
        panel.sort(["d_channel_key", "d_cutoff_date"])
        .with_columns(
            pl.col("d_cutoff_date")
            .cum_count()
            .over("d_channel_key")
            .cast(pl.Int32)
            .alias("d_observed_days_so_far")
        )
        .with_columns(
            (pl.col("d_observed_days_so_far") <= cold_days).alias("d_is_cold_start")
        )
    )


def rolling_fold(panel: Any, validation_year: int, target: str = TARGET) -> dict[str, Any]:
    """Return leakage-purged train, H1 calibration and H2 validation."""
    import polars as pl

    if validation_year not in {2023, 2024}:
        raise ValueError("Only the pre-2025 folds 2023 and 2024 are allowed")
    labelled = panel.filter(pl.col(target).is_not_null())
    train_years = [year for year in range(2019, validation_year) if year != 2021]
    year_start = date(validation_year, 1, 1)
    h2_start = date(validation_year, 7, 1)
    next_year = date(validation_year + 1, 1, 1)
    end = pl.col("d_target_end_date_exclusive")
    start = pl.col("d_target_start_date")
    splits = {
        "train": labelled.filter(
            pl.col("d_year").is_in(train_years) & (end <= pl.lit(year_start))
        ),
        "calibration": labelled.filter(
            (pl.col("d_year") == validation_year) & (end <= pl.lit(h2_start))
        ),
        "validation": labelled.filter(
            (pl.col("d_year") == validation_year)
            & (start >= pl.lit(h2_start))
            & (end <= pl.lit(next_year))
        ),
    }
    empty = [name for name, frame in splits.items() if frame.is_empty()]
    if empty:
        raise RuntimeError(f"Пустые части fold {validation_year}: {empty}")
    return splits


def final_training_split(panel: Any, target: str = TARGET) -> dict[str, Any]:
    """Train through 2024 and calibrate on 2025 H1; never use 2025 H2."""
    import polars as pl

    labelled = panel.filter(pl.col(target).is_not_null())
    end = pl.col("d_target_end_date_exclusive")
    splits = {
        "train": labelled.filter(
            pl.col("d_year").is_in([2019, 2020, 2022, 2023, 2024])
            & (end <= pl.lit(date(2025, 1, 1)))
        ),
        "calibration": labelled.filter(
            (pl.col("d_year") == 2025) & (end <= pl.lit(date(2025, 7, 1)))
        ),
    }
    if any(frame.is_empty() for frame in splits.values()):
        raise RuntimeError("Недостаточно данных для финального train/calibration")
    return splits


def _smoke_routed_frame(frame: Any, seed: int, per_group: int = 750) -> Any:
    """Keep both classes in both router branches when they exist."""
    import polars as pl

    pieces = []
    for cold in (False, True):
        for target_value in (0, 1):
            part = frame.filter(
                (pl.col("d_is_cold_start") == cold)
                & (pl.col(TARGET) == target_value)
            )
            if not part.is_empty():
                pieces.append(
                    part.sample(
                        n=min(per_group, part.height),
                        seed=seed + int(cold) * 10 + target_value,
                        shuffle=True,
                    )
                )
    if not pieces:
        raise RuntimeError("Smoke sample is empty")
    return pl.concat(pieces, how="vertical").sort("d_cutoff_date")


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def fit_robust_stats(frame: Any, max_rows: int, seed: int) -> dict[str, Any]:
    """Fit type-relative medians and IQRs without labels or future rows."""
    import pandas as pd

    if frame.height > max_rows:
        frame = frame.sample(n=max_rows, seed=seed, shuffle=True)
    data = _to_pandas(frame, ROBUST_NUMERIC + ["тип_датчика"])
    for column in ROBUST_NUMERIC:
        data[column] = pd.to_numeric(data[column], errors="coerce").astype(float)

    def summarize(group: Any) -> dict[str, dict[str, float | None]]:
        centers: dict[str, float | None] = {}
        scales: dict[str, float | None] = {}
        for column in ROBUST_NUMERIC:
            series = group[column].dropna()
            if series.empty:
                centers[column], scales[column] = None, None
                continue
            center = _finite_or_none(series.median())
            iqr = _finite_or_none(series.quantile(0.75) - series.quantile(0.25))
            centers[column] = center
            scales[column] = iqr if iqr is not None and iqr > 1e-9 else 1.0
        return {"center": centers, "scale": scales}

    stats: dict[str, Any] = {"__GLOBAL__": summarize(data)}
    sensor = data["тип_датчика"].fillna("__MISSING__").astype(str)
    for sensor_type, group in data.assign(__sensor=sensor).groupby("__sensor"):
        if len(group) >= 1000:
            stats[str(sensor_type)] = summarize(group)
    return stats


def _robust_deviation(data: Any, stats: dict[str, Any]) -> np.ndarray:
    import pandas as pd

    result = np.zeros(len(data), dtype=float)
    sensor_values = data["тип_датчика"].fillna("__MISSING__").astype(str)
    for sensor_type in sensor_values.unique():
        mask = sensor_values == sensor_type
        spec = stats.get(sensor_type, stats["__GLOBAL__"])
        columns = []
        for name in ROBUST_NUMERIC:
            center, scale = spec["center"].get(name), spec["scale"].get(name)
            if center is None or scale is None:
                continue
            values = pd.to_numeric(data.loc[mask, name], errors="coerce").to_numpy(float)
            columns.append(np.minimum(np.abs((values - center) / scale), 20.0))
        if columns:
            with np.errstate(invalid="ignore"):
                score = np.nanmean(np.column_stack(columns), axis=1)
            result[np.flatnonzero(mask.to_numpy())] = np.nan_to_num(score, nan=0.0)
    return result


def _category_levels(data: Any) -> dict[str, list[str]]:
    return {
        name: sorted(data[name].fillna("__MISSING__").astype(str).unique().tolist())
        for name in CATEGORICAL_FEATURES
    }


def prepare_features(
    frame: Any,
    features: list[str],
    category_levels: dict[str, list[str]],
    robust_stats: dict[str, Any] | None = None,
) -> Any:
    import pandas as pd

    base = sorted(set(WARM_FEATURES + ["d_observed_days_so_far"]))
    data = _to_pandas(frame, base)
    if robust_stats is not None:
        data["d_missing_feature_count"] = data[COLD_BASE_NUMERIC].isna().sum(axis=1)
        data["d_type_robust_deviation"] = _robust_deviation(data, robust_stats)
    for name in CATEGORICAL_FEATURES:
        values = data[name].fillna("__MISSING__").astype(str)
        data[name] = values.astype(pd.CategoricalDtype(categories=category_levels[name]))
    return data[features]


def _fit_lgbm(
    train: Any,
    features: list[str],
    category_levels: dict[str, list[str]],
    robust_stats: dict[str, Any] | None,
    config: dict[str, Any],
    seed_offset: int,
) -> Any:
    from lightgbm import LGBMClassifier

    sampled = _sample_training(
        train,
        TARGET,
        int(config["negative_to_positive_ratio"]),
        int(config["random_seed"]) + seed_offset,
    )
    x = prepare_features(sampled, features, category_levels, robust_stats)
    y = sampled[TARGET].to_numpy().astype(np.int8)
    model = LGBMClassifier(
        objective="binary",
        n_estimators=(40 if config["run_mode"] == "smoke" else int(config["iterations"])),
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=40,
        max_bin=63,
        colsample_bytree=0.9,
        subsample=0.9,
        random_state=int(config["random_seed"]) + seed_offset,
        n_jobs=-1,
        device_type="cpu",
        verbosity=-1,
    )
    model.fit(
        x,
        y,
        sample_weight=sampled["d_sample_weight"].to_numpy(),
        categorical_feature=list(CATEGORICAL_FEATURES),
    )
    return model


def _fit_platt_or_identity(raw: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    if np.unique(y).size < 2:
        return {"kind": "identity", "warning": "calibration subset has one class"}
    model = _fit_calibrator(raw, y)
    return {
        "kind": "platt",
        "coef": float(model.coef_[0, 0]),
        "intercept": float(model.intercept_[0]),
    }


def apply_calibration(spec: dict[str, Any], raw: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(raw, dtype=float), 1e-6, 1 - 1e-6)
    if spec["kind"] == "identity":
        return clipped
    logits = np.log(clipped / (1 - clipped))
    z = float(spec["coef"]) * logits + float(spec["intercept"])
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def _predict_model(
    model: Any,
    frame: Any,
    features: list[str],
    levels: dict[str, list[str]],
    stats: dict[str, Any] | None,
    calibration: dict[str, Any],
) -> np.ndarray:
    raw = model.predict_proba(prepare_features(frame, features, levels, stats))[:, 1]
    return apply_calibration(calibration, raw)


def fit_system(train: Any, calibration: Any, config: dict[str, Any]) -> dict[str, Any]:
    import polars as pl

    levels = _category_levels(_to_pandas(train, list(CATEGORICAL_FEATURES)))
    robust_stats = fit_robust_stats(
        train, int(config["robust_stats_max_rows"]), int(config["random_seed"])
    )
    cold_train = train.filter(pl.col("d_is_cold_start"))
    warm_train = train.filter(~pl.col("d_is_cold_start"))
    if cold_train[TARGET].n_unique() < 2 or warm_train[TARGET].n_unique() < 2:
        raise RuntimeError("Cold/warm train subset must contain both target classes")

    base = _fit_lgbm(train, WARM_FEATURES, levels, None, config, 0)
    cold = _fit_lgbm(cold_train, COLD_FEATURES, levels, robust_stats, config, 100)
    warm = _fit_lgbm(warm_train, WARM_FEATURES, levels, None, config, 200)

    cal_y = calibration[TARGET].to_numpy().astype(np.int8)
    base_raw = base.predict_proba(
        prepare_features(calibration, WARM_FEATURES, levels, None)
    )[:, 1]
    base_calibration = _fit_platt_or_identity(base_raw, cal_y)
    base_probability = apply_calibration(base_calibration, base_raw)

    cold_mask = calibration["d_is_cold_start"].to_numpy()
    cold_raw = cold.predict_proba(
        prepare_features(calibration, COLD_FEATURES, levels, robust_stats)
    )[:, 1]
    warm_raw = warm.predict_proba(
        prepare_features(calibration, WARM_FEATURES, levels, None)
    )[:, 1]
    cold_calibration = _fit_platt_or_identity(cold_raw[cold_mask], cal_y[cold_mask])
    warm_calibration = _fit_platt_or_identity(warm_raw[~cold_mask], cal_y[~cold_mask])
    router_probability = np.where(
        cold_mask,
        apply_calibration(cold_calibration, cold_raw),
        apply_calibration(warm_calibration, warm_raw),
    )
    return {
        "base_model": base,
        "cold_model": cold,
        "warm_model": warm,
        "category_levels": levels,
        "robust_stats": robust_stats,
        "base_calibration": base_calibration,
        "cold_calibration": cold_calibration,
        "warm_calibration": warm_calibration,
        "base_threshold": _select_threshold(
            cal_y, base_probability, float(config["minimum_precision"])
        ),
        "router_threshold": _select_threshold(
            cal_y, router_probability, float(config["minimum_precision"])
        ),
    }


def predict_system(system: dict[str, Any], frame: Any) -> tuple[np.ndarray, np.ndarray]:
    base = _predict_model(
        system["base_model"], frame, WARM_FEATURES, system["category_levels"],
        None, system["base_calibration"],
    )
    cold_raw = system["cold_model"].predict_proba(
        prepare_features(
            frame, COLD_FEATURES, system["category_levels"], system["robust_stats"]
        )
    )[:, 1]
    warm_raw = system["warm_model"].predict_proba(
        prepare_features(frame, WARM_FEATURES, system["category_levels"], None)
    )[:, 1]
    cold = apply_calibration(system["cold_calibration"], cold_raw)
    warm = apply_calibration(system["warm_calibration"], warm_raw)
    router = np.where(frame["d_is_cold_start"].to_numpy(), cold, warm)
    return base, router


def _slice_metrics(frame: Any, probability: np.ndarray, threshold: float) -> dict[str, Any]:
    y = frame[TARGET].to_numpy().astype(np.int8)
    if len(y) == 0:
        return {"eligible_rows": 0, "positive_rows": 0, "pr_auc": None}
    if np.unique(y).size < 2:
        return {
            "eligible_rows": int(len(y)),
            "positive_rows": int(y.sum()),
            "prevalence": float(y.mean()),
            "pr_auc": None,
        }
    output = point_metrics(y, probability, threshold)
    output["prevalence"] = float(y.mean())
    output["pr_auc_lift_over_prevalence"] = output["pr_auc"] / max(float(y.mean()), 1e-12)
    return output


def _paired_weekly_ci(
    frame: Any,
    left: np.ndarray,
    right: np.ndarray,
    repeats: int,
    seed: int,
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score
    import pandas as pd

    y = frame[TARGET].to_numpy().astype(np.int8)
    dates = pd.to_datetime(frame["d_cutoff_date"].to_list())
    blocks = np.asarray([
        f"{value.isocalendar().year}-{value.isocalendar().week}" for value in dates
    ])
    unique = np.unique(blocks)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(repeats):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(blocks == block) for block in sampled])
        if np.unique(y[indices]).size < 2:
            continue
        deltas.append(
            average_precision_score(y[indices], right[indices])
            - average_precision_score(y[indices], left[indices])
        )
    if not deltas:
        return {"estimate": None, "low": None, "high": None, "repeats": 0}
    return {
        "estimate": float(np.mean(deltas)),
        "low": float(np.quantile(deltas, 0.025)),
        "high": float(np.quantile(deltas, 0.975)),
        "repeats": len(deltas),
    }


def evaluate_fold(
    splits: dict[str, Any], config: dict[str, Any], validation_year: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config["run_mode"] == "smoke":
        splits = {
            name: _smoke_routed_frame(
                frame, int(config["random_seed"]) + validation_year + index
            )
            for index, (name, frame) in enumerate(splits.items())
        }
    system = fit_system(splits["train"], splits["calibration"], config)
    validation = splits["validation"]
    base_probability, router_probability = predict_system(system, validation)

    known_channels = set(splits["train"]["d_channel_key"].to_list())
    known_channels.update(splits["calibration"]["d_channel_key"].to_list())
    unseen_mask = ~validation["d_channel_key"].is_in(list(known_channels))
    cold_mask = validation["d_is_cold_start"]

    def subset(mask: Any, probability: np.ndarray) -> tuple[Any, np.ndarray]:
        indices = np.flatnonzero(mask.to_numpy())
        return validation.filter(mask), probability[indices]

    unseen_frame, unseen_base = subset(unseen_mask, base_probability)
    _, unseen_router = subset(unseen_mask, router_probability)
    cold_frame, cold_base = subset(cold_mask, base_probability)
    _, cold_router = subset(cold_mask, router_probability)

    base_episode = episode_metrics(
        validation, base_probability, TARGET, system["base_threshold"],
        int(config["alert_budget_per_day"]), int(config["cooldown_hours"]),
    )
    router_episode = episode_metrics(
        validation, router_probability, TARGET, system["router_threshold"],
        int(config["alert_budget_per_day"]), int(config["cooldown_hours"]),
    )
    report = {
        "validation_year": validation_year,
        "base": _slice_metrics(validation, base_probability, system["base_threshold"]),
        "router": _slice_metrics(validation, router_probability, system["router_threshold"]),
        "unseen_channel": {
            "rows": int(unseen_frame.height),
            "base": _slice_metrics(unseen_frame, unseen_base, system["base_threshold"]),
            "router": _slice_metrics(unseen_frame, unseen_router, system["router_threshold"]),
            "paired_pr_auc_delta_ci95": (
                _paired_weekly_ci(
                    unseen_frame, unseen_base, unseen_router,
                    int(config["bootstrap_repeats"]),
                    int(config["random_seed"]) + validation_year,
                )
                if unseen_frame.height
                else None
            ),
        },
        "cold_start_rows": {
            "rows": int(cold_frame.height),
            "base": _slice_metrics(cold_frame, cold_base, system["base_threshold"]),
            "router": _slice_metrics(cold_frame, cold_router, system["router_threshold"]),
        },
        "episode_50_day_72h": {"base": base_episode, "router": router_episode},
        "paired_pr_auc_delta_ci95": _paired_weekly_ci(
            validation, base_probability, router_probability,
            int(config["bootstrap_repeats"]),
            int(config["random_seed"]) + validation_year,
        ),
    }
    return report, system


def select_router(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Conservative selection; failed gates keep the ordinary LightGBM."""
    reasons: list[str] = []
    for fold in folds:
        ci = fold["unseen_channel"]["paired_pr_auc_delta_ci95"]
        if not ci or ci["low"] is None or ci["low"] <= 0:
            reasons.append(
                f"{fold['validation_year']}: unseen-channel PR-AUC CI is not positive"
            )
        base_episode = fold["episode_50_day_72h"]["base"]
        router_episode = fold["episode_50_day_72h"]["router"]
        if router_episode["precision"] < base_episode["precision"] - 0.01:
            reasons.append(
                f"{fold['validation_year']}: episode precision fell by more than 0.01"
            )
        base_false = fold["base"]["false_alerts_per_1000_eligible_channel_days"]
        router_false = fold["router"]["false_alerts_per_1000_eligible_channel_days"]
        if router_false > base_false + max(1.0, 0.05 * base_false):
            reasons.append(
                f"{fold['validation_year']}: false-alert burden increased materially"
            )
    return {
        "selected_policy": "cold_start_router" if not reasons else "base_lightgbm",
        "router_passed": not reasons,
        "reasons": reasons or ["all pre-2025 cold-start gates passed"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backend_predictor_source() -> str:
    """Return the portable scorer included in the backend ZIP."""
    return '''from __future__ import annotations
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
'''


def export_backend_bundle(
    system: dict[str, Any],
    selection: dict[str, Any],
    manifest: dict[str, Any],
    config: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    import joblib

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    required = sorted(
        set(
            WARM_FEATURES
            + ["d_observed_days_so_far", "d_current_failure_state", "as_of_date"]
        )
    )
    bundle = {
        **system,
        "selected_policy": selection["selected_policy"],
        "model_version": MODEL_VERSION,
        "target_code": TARGET_CODE,
        "target_column": TARGET,
        "target_semantics": "observable state proxy; not confirmed physical failure",
        "cold_days": int(config["cold_days"]),
        "warm_features": WARM_FEATURES,
        "cold_features": COLD_FEATURES,
        "cold_base_numeric": COLD_BASE_NUMERIC,
        "robust_numeric": ROBUST_NUMERIC,
        "required_input_fields": required,
        "panel_data_sha256": manifest["data_sha256"],
    }
    model_path = output / "experimental_cold_start_model.joblib"
    joblib.dump(bundle, model_path)
    predictor_path = output / "predictor.py"
    predictor_path.write_text(backend_predictor_source(), encoding="utf-8")
    requirements_path = output / "backend_model_requirements.txt"
    requirements_path.write_text(
        "joblib>=1.3,<2\n"
        "lightgbm>=4.4,<5\n"
        "numpy>=1.26,<3\n"
        "pandas>=2.1,<3\n"
        "scikit-learn==1.6.1\n",
        encoding="utf-8",
    )
    contract = {
        "model_version": MODEL_VERSION,
        "format": "joblib dictionary + predictor.py",
        "call": "bundle = load_bundle(path); predict([record], bundle)",
        "selected_policy": selection["selected_policy"],
        "input_fields": {
            name: (
                "string ISO date YYYY-MM-DD"
                if name == "as_of_date"
                else "boolean"
                if name == "d_current_failure_state"
                else "nullable string"
                if name in CATEGORICAL_FEATURES
                else "integer >= 1"
                if name == "d_observed_days_so_far"
                else "nullable number"
            )
            for name in required
        },
        "output_score": (
            "calibrated probability of the observable proxy state in [D+2,D+3); "
            "not probability of confirmed physical failure"
        ),
        "preprocessing": {
            "inside_bundle": [
                "missing-value handling by LightGBM",
                "category mapping with unknown categories mapped to missing",
                "type-relative robust deviation",
                "cold/warm routing",
                "Platt calibration",
            ],
            "backend_required": [
                "construct daily aggregate fields from events available by end of D",
                "maintain causal d_observed_days_so_far",
                "apply top-K/cooldown policy outside the model",
            ],
        },
        "decision_status": "experimental_shadow",
    }
    contract_path = output / "model_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    example = {name: None for name in required}
    example.update(
        {
            "as_of_date": "2026-09-21",
            "d_observed_days_so_far": 3,
            "d_current_failure_state": False,
            "тип_датчика": "Датчик температуры",
            "тип_инж_системы": "Система мониторинга",
            "d_event_count_24h": 12,
            "d_alarm_count_24h": 1,
            "d_alarm_share_24h": 1 / 12,
            "d_catalogue_match": 1,
        }
    )
    example_path = output / "example_input.json"
    example_path.write_text(
        json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    readme_path = output / "README_BACKEND_RU.md"
    readme_path.write_text(
        "# Экспериментальная ML-модель\n\n"
        "Модель предназначена только для shadow-режима. Она оценивает вероятность "
        "наблюдаемого proxy-состояния, а не подтверждённой физической поломки.\n\n"
        "Вызов: bundle = load_bundle('experimental_cold_start_model.joblib'), "
        "затем predict([record], bundle). Сырые события должны быть заранее "
        "агрегированы backend/data-контуром в поля из model_contract.json.\n",
        encoding="utf-8",
    )
    zip_path = output / "backend_experimental_model.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in [
            model_path, predictor_path, requirements_path,
            contract_path, example_path, readme_path,
        ]:
            archive.write(path, arcname=path.name)
    return {
        "bundle_zip": zip_path.name,
        "bundle_sha256": _sha256(zip_path),
        "model_sha256": _sha256(model_path),
        "contract": contract,
    }


def run_cold_start_research(
    panel: Any,
    manifest: dict[str, Any],
    config: dict[str, Any],
    output_dir: str | Path = "/kaggle/working",
) -> dict[str, Any]:
    """Evaluate pre-2025 folds, select safely and fit the handoff bundle."""
    started = time.perf_counter()
    if config["run_mode"] not in {"smoke", "full"}:
        raise ValueError("run_mode must be smoke or full")
    enriched = add_causal_maturity(panel, int(config["cold_days"]))
    fold_reports = []
    for year in ([2024] if config["run_mode"] == "smoke" else [2023, 2024]):
        report, _ = evaluate_fold(rolling_fold(enriched, year), config, year)
        fold_reports.append(report)
    selection = select_router(fold_reports)

    final_splits = final_training_split(enriched)
    if config["run_mode"] == "smoke":
        final_splits = {
            name: _smoke_routed_frame(
                frame, int(config["random_seed"]) + 500 + index
            )
            for index, (name, frame) in enumerate(final_splits.items())
        }
    final_system = fit_system(
        final_splits["train"], final_splits["calibration"], config
    )
    bundle_info = export_backend_bundle(
        final_system, selection, manifest, config, output_dir
    )
    result = {
        "status": "ok",
        "comparable": config["run_mode"] == "full",
        "target": TARGET,
        "target_code": TARGET_CODE,
        "target_semantics": (
            "Failure-state presence proxy on D+2 after features through D; "
            "not proven physical failure and not strict onset through D+1"
        ),
        "uses_2025_h2_for_selection_or_training": False,
        "uses_2026": False,
        "folds": fold_reports,
        "selection": selection,
        "backend_bundle": bundle_info,
        "configuration": config,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "runtime_seconds": time.perf_counter() - started,
    }
    output = Path(output_dir)
    (output / "results_cold_start_router.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
