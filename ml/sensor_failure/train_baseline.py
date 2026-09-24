"""Train and evaluate rule, logistic, and CPU CatBoost proxy baselines."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from panel import PANEL_SCHEMA_VERSION, TARGET_COLUMNS, build_panel, source_file_manifest


NUMERIC_FEATURES = [
    "d_event_count_24h",
    "d_alarm_count_24h",
    "d_alarm_share_24h",
    "d_failure_state_event_count_24h",
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
    "d_days_since_failure_state_event",
    "d_weekday",
    "d_month",
    "d_catalogue_match",
]

CATEGORICAL_FEATURES = ["тип_инж_системы", "тип_датчика"]
MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
FEATURE_PRESETS = {
    "core": [
        name
        for name in NUMERIC_FEATURES
        if "previous" not in name
        and name not in {"d_gap_days_since_previous", "d_days_since_failure_state_event"}
    ],
    "recurrence": [
        "d_gap_days_since_previous",
        "d_event_count_previous_24h",
        "d_alarm_count_previous_24h",
        "d_alarm_share_previous_24h",
        "d_value_numeric_previous",
        "d_days_since_failure_state_event",
    ],
    "all_safe": NUMERIC_FEATURES,
    "safe_recurrence": NUMERIC_FEATURES,
    "no_same_day_failure": [
        name
        for name in NUMERIC_FEATURES
        if name not in {"d_failure_state_event_count_24h", "d_days_since_failure_state_event"}
    ],
}
FORBIDDEN_PREFIXES = ("target_", "d_future_")
FORBIDDEN_EXACT = {
    "ид_события",
    "ид_канала_данных",
    "дата",
    "время",
    "тревожное",
    "значение_датчика",
    "d_event_time",
    "d_available_time",
    "d_last_available_time",
}


def assert_leakage_safe_features(features: list[str]) -> None:
    forbidden = [
        name
        for name in features
        if name in FORBIDDEN_EXACT or name.startswith(FORBIDDEN_PREFIXES)
    ]
    if forbidden:
        raise ValueError(f"forbidden/leaky model features: {forbidden}")
    if len(features) != len(set(features)):
        raise ValueError("duplicate feature names")


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--target",
        choices=TARGET_COLUMNS,
        default="target_failure_state_onset_24h",
    )
    parser.add_argument(
        "--failure-state-dictionary",
        type=Path,
        default=here / "config" / "failure_state_dictionary.json",
    )
    parser.add_argument(
        "--latency-minutes", type=int, nargs="+", default=[0, 5, 60, 360, 1440]
    )
    parser.add_argument("--include-2021", action="store_true")
    parser.add_argument("--minimum-precision", type=float, default=0.20)
    parser.add_argument("--bootstrap-repeats", type=int, default=50)
    parser.add_argument("--negative-to-positive-ratio", type=int, default=20)
    parser.add_argument("--random-seed", type=int, default=20260919)
    parser.add_argument("--catboost-iterations", type=int, default=500)
    parser.add_argument("--catboost-threads", type=int, default=-1)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=["rule", "logistic", "catboost", "lightgbm"],
        default=["rule", "logistic", "catboost"],
    )
    parser.add_argument("--catboost-task-type", choices=["CPU", "GPU"], default="CPU")
    parser.add_argument("--lightgbm-iterations", type=int, default=500)
    parser.add_argument("--lightgbm-threads", type=int, default=-1)
    parser.add_argument(
        "--lightgbm-device-type", choices=["cpu", "gpu", "cuda"], default="cpu"
    )
    parser.add_argument("--target-lead-hours", type=int, default=24)
    parser.add_argument("--target-window-hours", type=int, default=24)
    parser.add_argument("--clean-history-days", type=int, default=0)
    parser.add_argument("--alert-budget-per-day", type=int, default=50)
    parser.add_argument("--cooldown-hours", type=int, default=72)
    parser.add_argument(
        "--feature-preset", choices=sorted(FEATURE_PRESETS), default="all_safe"
    )
    parser.add_argument("--evaluate-test", action="store_true")
    return parser.parse_args()


def _to_pandas(frame: Any, columns: list[str]) -> Any:
    import pandas as pd

    return pd.DataFrame(frame.select(columns).to_dict(as_series=False))


def _split(frame: Any, target: str, include_2021: bool) -> dict[str, Any]:
    import polars as pl

    required = {
        "d_year",
        "d_cutoff_date",
        "d_target_start_date",
        "d_target_end_date_exclusive",
        target,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "panel lacks mandatory temporal-boundary columns; rebuild it: "
            f"{missing}"
        )
    labelled = frame.filter(pl.col(target).is_not_null())
    years = pl.col("d_year")
    train_years = [2019, 2020, 2022, 2023, 2024]
    if include_2021:
        train_years.append(2021)
    def before(boundary: date) -> Any:
        return pl.col("d_target_end_date_exclusive") <= pl.lit(boundary)

    def starts_on_or_after(boundary: date) -> Any:
        return pl.col("d_target_start_date") >= pl.lit(boundary)

    return {
        "train": labelled.filter(
            years.is_in(train_years) & before(date(2025, 1, 1))
        ),
        "stress_2021": labelled.filter(
            (years == 2021) & before(date(2022, 1, 1))
        ),
        "calibration_2025_h1": labelled.filter(
            (years == 2025) & before(date(2025, 7, 1))
        ),
        "validation_2025_h2": labelled.filter(
            (years == 2025)
            & starts_on_or_after(date(2025, 7, 1))
            & before(date(2026, 1, 1))
        ),
        "test_2026_h1": labelled.filter(
            (years == 2026)
            & starts_on_or_after(date(2026, 1, 1))
            & before(date(2026, 7, 1))
        ),
    }


def _sample_training(frame: Any, target: str, ratio: int, seed: int) -> Any:
    import polars as pl

    if ratio <= 0:
        raise ValueError("negative-to-positive ratio must be positive")
    positives = frame.filter(pl.col(target) == 1)
    negatives = frame.filter(pl.col(target) == 0)
    if positives.is_empty() or negatives.is_empty():
        raise ValueError("training split must contain both target classes")
    keep_negatives = min(negatives.height, max(positives.height * ratio, 1))
    negative_weight = 1.0
    if keep_negatives < negatives.height:
        negative_weight = negatives.height / keep_negatives
        negatives = negatives.sample(n=keep_negatives, seed=seed, shuffle=True)
    positives = positives.with_columns(pl.lit(1.0).alias("d_sample_weight"))
    negatives = negatives.with_columns(
        pl.lit(float(negative_weight)).alias("d_sample_weight")
    )
    return pl.concat([positives, negatives], how="vertical").sample(
        fraction=1.0, seed=seed, shuffle=True
    )


def _fit_probability_calibrator(probability: np.ndarray, y: np.ndarray) -> Any:
    from sklearn.linear_model import LogisticRegression

    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    calibrator = LogisticRegression(random_state=0, max_iter=500)
    calibrator.fit(logits, y)
    return calibrator


def _calibrate(calibrator: Any, probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    return calibrator.predict_proba(logits)[:, 1]


def _select_threshold(y: np.ndarray, p: np.ndarray, minimum_precision: float) -> float:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y, p)
    candidates = np.flatnonzero(precision[:-1] >= minimum_precision)
    if candidates.size:
        best = candidates[np.argmax(recall[candidates])]
        return float(thresholds[best])
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(
        precision[:-1] + recall[:-1], 1e-12
    )
    return float(thresholds[int(np.nanargmax(f1))])


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    result = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (p >= left) & (p < right if right < 1 else p <= right)
        if mask.any():
            result += mask.mean() * abs(float(y[mask].mean() - p[mask].mean()))
    return float(result)


def _point_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, float]:
    from sklearn.metrics import average_precision_score, brier_score_loss

    predicted = p >= threshold
    tp = int(((y == 1) & predicted).sum())
    fp = int(((y == 0) & predicted).sum())
    fn = int(((y == 1) & ~predicted).sum())
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(tp + fn, 1),
        "false_alerts_per_1000_eligible_channel_days": 1000 * fp / max(len(y), 1),
        "brier_score": float(brier_score_loss(y, p)),
        "expected_calibration_error_10_bins": _ece(y, p),
        "threshold": float(threshold),
        "eligible_rows": int(len(y)),
        "positive_rows": int(y.sum()),
    }


def _bootstrap_intervals(
    y: np.ndarray,
    p: np.ndarray,
    dates: np.ndarray,
    threshold: float,
    repeats: int,
    seed: int,
) -> dict[str, list[float]]:
    from sklearn.metrics import average_precision_score

    unique_dates, inverse = np.unique(dates, return_inverse=True)
    rng = np.random.default_rng(seed)
    sampled_metrics: dict[str, list[float]] = {
        "pr_auc": [],
        "precision": [],
        "recall": [],
        "false_alerts_per_1000_eligible_channel_days": [],
    }
    predicted = p >= threshold
    for _ in range(repeats):
        draws = rng.integers(0, len(unique_dates), size=len(unique_dates))
        multiplicity = np.bincount(draws, minlength=len(unique_dates))
        weights = multiplicity[inverse]
        if weights[y == 1].sum() == 0:
            continue
        tp = float(weights[(y == 1) & predicted].sum())
        fp = float(weights[(y == 0) & predicted].sum())
        fn = float(weights[(y == 1) & ~predicted].sum())
        sampled_metrics["pr_auc"].append(
            float(average_precision_score(y, p, sample_weight=weights))
        )
        sampled_metrics["precision"].append(tp / max(tp + fp, 1))
        sampled_metrics["recall"].append(tp / max(tp + fn, 1))
        sampled_metrics["false_alerts_per_1000_eligible_channel_days"].append(
            1000 * fp / max(float(weights.sum()), 1)
        )
    return {
        name: [float(x) for x in np.quantile(values, [0.025, 0.975])]
        for name, values in sampled_metrics.items()
        if values
    }


def _evaluate(
    frame: Any,
    target: str,
    probability: np.ndarray,
    threshold: float,
    repeats: int,
    seed: int,
) -> dict[str, Any]:
    y = frame[target].to_numpy().astype(np.int8)
    dates = frame["d_cutoff_date"].to_numpy().astype(str)
    result: dict[str, Any] = _point_metrics(y, probability, threshold)
    result["date_block_bootstrap_95pct"] = _bootstrap_intervals(
        y, probability, dates, threshold, repeats, seed
    )
    return result


def _rule_probability(frame: Any) -> np.ndarray:
    alarm = frame["d_alarm_share_24h"].fill_null(0).to_numpy()
    prior_alarm = frame["d_alarm_share_previous_24h"].fill_null(0).to_numpy()
    observed_failure = (
        frame["d_failure_state_event_count_24h"].fill_null(0).to_numpy() > 0
    ).astype(float)
    return np.clip(np.maximum.reduce([alarm, 0.5 * prior_alarm, 0.75 * observed_failure]), 0, 1)


def _train_models(splits: dict[str, Any], args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    import joblib
    from evaluation import evaluate_alert_episodes
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    requested = set(getattr(args, "models", ["rule", "logistic", "catboost"]))
    supported = {"rule", "logistic", "catboost", "lightgbm"}
    unknown = requested - supported
    if unknown:
        raise ValueError(f"unsupported models: {sorted(unknown)}")
    if not requested:
        raise ValueError("at least one model must be requested")
    feature_preset = getattr(args, "feature_preset", "all_safe")
    if feature_preset not in FEATURE_PRESETS:
        raise ValueError(f"unsupported feature preset: {feature_preset}")
    numeric_features = FEATURE_PRESETS[feature_preset]
    model_features = numeric_features + CATEGORICAL_FEATURES
    assert_leakage_safe_features(model_features)

    train = _sample_training(
        splits["train"], args.target, args.negative_to_positive_ratio, args.random_seed
    )
    train_x = _to_pandas(train, model_features)
    train_y = train[args.target].to_numpy().astype(np.int8)
    train_weight = train["d_sample_weight"].to_numpy()
    fitted: dict[str, Any] = {}
    category_levels: dict[str, list[str]] = {}

    if "logistic" in requested:
        numeric = Pipeline(
            [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
        )
        categorical = Pipeline(
            [
                ("impute", SimpleImputer(strategy="most_frequent")),
                (
                    "onehot",
                    OneHotEncoder(handle_unknown="ignore", min_frequency=20),
                ),
            ]
        )
        logistic = Pipeline(
            [
                (
                    "features",
                    ColumnTransformer(
                        [
                            ("numeric", numeric, numeric_features),
                            ("categorical", categorical, CATEGORICAL_FEATURES),
                        ]
                    ),
                ),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1000,
                        random_state=args.random_seed,
                        solver="liblinear",
                    ),
                ),
            ]
        )
        logistic.fit(train_x, train_y, model__sample_weight=train_weight)
        fitted["logistic"] = logistic

    def cat_frame(x: Any) -> Any:
        result = x.copy()
        for name in CATEGORICAL_FEATURES:
            result[name] = result[name].fillna("__MISSING__").astype(str)
        return result

    if "catboost" in requested:
        from catboost import CatBoostClassifier

        catboost = CatBoostClassifier(
            iterations=args.catboost_iterations,
            depth=7,
            learning_rate=0.08,
            loss_function="Logloss",
            eval_metric="PRAUC",
            random_seed=args.random_seed,
            task_type=getattr(args, "catboost_task_type", "CPU"),
            thread_count=args.catboost_threads,
            allow_writing_files=False,
            verbose=False,
        )
        catboost.fit(
            cat_frame(train_x),
            train_y,
            cat_features=CATEGORICAL_FEATURES,
            sample_weight=train_weight,
        )
        fitted["catboost"] = catboost

    def lightgbm_frame(x: Any, *, training: bool = False) -> Any:
        result = x.copy()
        for name in CATEGORICAL_FEATURES:
            values = result[name].fillna("__MISSING__").astype(str)
            if training:
                category_levels[name] = sorted(values.unique().tolist())
            result[name] = values.astype(
                __import__("pandas").CategoricalDtype(categories=category_levels[name])
            )
        return result

    if "lightgbm" in requested:
        from lightgbm import LGBMClassifier

        lightgbm = LGBMClassifier(
            objective="binary",
            n_estimators=getattr(args, "lightgbm_iterations", 500),
            learning_rate=0.05,
            num_leaves=63,
            max_bin=63,
            random_state=args.random_seed,
            n_jobs=getattr(args, "lightgbm_threads", -1),
            device_type=getattr(args, "lightgbm_device_type", "cpu"),
            verbosity=-1,
        )
        lightgbm.fit(
            lightgbm_frame(train_x, training=True),
            train_y,
            sample_weight=train_weight,
            categorical_feature=CATEGORICAL_FEATURES,
        )
        fitted["lightgbm"] = lightgbm

    calibration = splits["calibration_2025_h1"]
    val_x = _to_pandas(calibration, model_features)
    val_y = calibration[args.target].to_numpy().astype(np.int8)
    if np.unique(val_y).size != 2:
        raise ValueError("validation split must contain both target classes")

    def raw_predict(name: str, model: Any, x: Any) -> np.ndarray:
        if name == "catboost":
            x = cat_frame(x)
        elif name == "lightgbm":
            x = lightgbm_frame(x)
        return model.predict_proba(x)[:, 1]

    thresholds: dict[str, float] = {}
    calibrators: dict[str, Any] = {}
    validation_probabilities: dict[str, np.ndarray] = {}
    if "rule" in requested:
        thresholds["rule"] = 0.5
        validation_probabilities["rule"] = _rule_probability(calibration)
    for name, model in fitted.items():
        raw = raw_predict(name, model, val_x)
        calibrator = _fit_probability_calibrator(raw, val_y)
        calibrated = _calibrate(calibrator, raw)
        calibrators[name] = calibrator
        validation_probabilities[name] = calibrated
        thresholds[name] = _select_threshold(
            val_y, calibrated, args.minimum_precision
        )
    probabilities: dict[str, dict[str, np.ndarray]] = {
        "calibration_2025_h1": validation_probabilities
    }
    evaluation_splits = ["validation_2025_h2"]
    if not getattr(args, "include_2021", False):
        evaluation_splits.append("stress_2021")
    if getattr(args, "evaluate_test", True):
        evaluation_splits.append("test_2026_h1")
    for split_name in evaluation_splits:
        frame = splits[split_name]
        x = _to_pandas(frame, model_features)
        split_probabilities: dict[str, np.ndarray] = {}
        if "rule" in requested:
            split_probabilities["rule"] = _rule_probability(frame)
        for name, model in fitted.items():
            split_probabilities[name] = _calibrate(
                calibrators[name], raw_predict(name, model, x)
            )
        probabilities[split_name] = split_probabilities

    metrics: dict[str, Any] = {}
    for split_name, model_probabilities in probabilities.items():
        metrics[split_name] = {}
        for model_name, probability in model_probabilities.items():
            metrics[split_name][model_name] = _evaluate(
                splits[split_name],
                args.target,
                probability,
                thresholds[model_name],
                args.bootstrap_repeats,
                args.random_seed,
            )
            event_column = (
                "d_future_failure_event_date"
                if args.target == "target_failure_state_onset_24h"
                else "d_future_alarm_event_date"
            )
            episode_columns = {
                "d_target_start_date",
                "d_target_end_date_exclusive",
                event_column,
                "тип_датчика",
            }
            if episode_columns.issubset(set(splits[split_name].columns)):
                metrics[split_name][model_name]["alert_episode_evaluation"] = (
                    evaluate_alert_episodes(
                        splits[split_name],
                        probability,
                        target=args.target,
                        threshold=thresholds[model_name],
                        budget_per_day=getattr(args, "alert_budget_per_day", 50),
                        cooldown_hours=getattr(args, "cooldown_hours", 72),
                    )
                )

    run_dir.mkdir(parents=True, exist_ok=True)
    if "logistic" in fitted:
        joblib.dump(fitted["logistic"], run_dir / "logistic.joblib")
    if "catboost" in fitted:
        fitted["catboost"].save_model(run_dir / "catboost.cbm")
    if "lightgbm" in fitted:
        fitted["lightgbm"].booster_.save_model(str(run_dir / "lightgbm.txt"))
    for name, calibrator in calibrators.items():
        joblib.dump(calibrator, run_dir / f"{name}_calibrator.joblib")
    return {
        "target_semantics": "observable proxy, not confirmed physical failure",
        "target": args.target,
        "feature_preset": feature_preset,
        "feature_columns": model_features,
        "models": sorted(requested),
        "train_years": sorted(splits["train"]["d_year"].unique().to_list()),
        "training_rows_after_negative_sampling": train.height,
        "negative_sampling_uses_inverse_probability_weights": True,
        "stress_2021_evaluation": (
            "omitted because 2021 was included in training"
            if getattr(args, "include_2021", False)
            else "migration-regime stress slice; not a prospective headline test"
        ),
        "threshold_selection": {
            "period": "2025 H1",
            "minimum_precision": args.minimum_precision,
            "thresholds": thresholds,
        },
        "metrics": metrics,
    }


def main() -> None:
    import polars as pl

    args = parse_args()
    assert_leakage_safe_features(MODEL_FEATURES)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "target": args.target,
        "target_semantics": "observable proxy, not confirmed physical failure",
        "runs": {},
    }
    for latency in args.latency_minutes:
        panel_key = (
            f"lead_{args.target_lead_hours:04d}h_"
            f"window_{args.target_window_hours:04d}h_"
            f"clean_{args.clean_history_days:03d}d_"
            f"latency_{latency:04d}m"
        )
        run_dir = args.output_dir / panel_key
        panel_path = run_dir / "channel_panel.parquet"
        audit_path = run_dir / "panel_audit.json"
        run_dir.mkdir(parents=True, exist_ok=True)
        if panel_path.exists() and audit_path.exists():
            panel_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            expected = {
                "panel_schema_version": PANEL_SCHEMA_VERSION,
                "latency_minutes": latency,
                "target_lead_hours": args.target_lead_hours,
                "target_window_hours": args.target_window_hours,
                "clean_history_days": args.clean_history_days,
            }
            mismatch = {
                key: (panel_audit.get(key), value)
                for key, value in expected.items()
                if panel_audit.get(key) != value
            }
            if mismatch:
                raise RuntimeError(f"cached panel configuration mismatch: {mismatch}")
            if panel_audit.get("source_files") != source_file_manifest(args.data_dir):
                raise RuntimeError("cached panel source checksums differ; rebuild required")
            panel = pl.read_parquet(panel_path)
        else:
            panel, panel_audit = build_panel(
                args.data_dir,
                args.failure_state_dictionary,
                latency,
                target_lead_hours=args.target_lead_hours,
                target_window_hours=args.target_window_hours,
                clean_history_days=args.clean_history_days,
            )
            panel.write_parquet(panel_path, compression="zstd")
            audit_path.write_text(
                json.dumps(panel_audit, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if panel_audit["leakage_audit"]["feature_rows_after_cutoff"] != 0:
            raise RuntimeError("leakage audit failed: feature event after cutoff")
        splits = _split(panel, args.target, args.include_2021)
        empty = [name for name, frame in splits.items() if frame.is_empty()]
        if empty:
            raise RuntimeError(f"empty temporal splits: {empty}")
        result = _train_models(splits, args, run_dir)
        result["panel_audit"] = panel_audit
        (run_dir / "metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary["runs"][str(latency)] = result
        del panel

    (args.output_dir / "latency_robustness_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
