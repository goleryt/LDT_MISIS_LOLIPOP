"""Standalone runtime embedded into the four Kaggle notebooks.

The module intentionally depends only on common Kaggle packages. It operates on
the de-identified development panel, never on the raw event archive.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np


PANEL_SCHEMA_VERSION = "2.0"
TARGETS = {
    "target_failure_state_onset_24h": "d_future_failure_event_date",
    "target_alarm_onset_24h": "d_future_alarm_event_date",
}
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
FEATURE_VARIANTS = {
    "safe_recurrence": NUMERIC_FEATURES,
    "core": [
        name
        for name in NUMERIC_FEATURES
        if "previous" not in name
        and name not in {"d_gap_days_since_previous", "d_days_since_failure_state_event"}
    ],
    "no_same_day_failure": [
        name
        for name in NUMERIC_FEATURES
        if name not in {"d_failure_state_event_count_24h", "d_days_since_failure_state_event"}
    ],
    "with_object_key_ablation": NUMERIC_FEATURES,
}
FORBIDDEN_FEATURE_PREFIXES = ("target_", "d_future_")
FORBIDDEN_FEATURES = {
    "d_channel_key",
    "ид_события",
    "ид_канала_данных",
    "ид_объект",
    "дата",
    "время",
    "тревожное",
    "значение_датчика",
    "d_last_available_time",
}
REQUIRED_PANEL_COLUMNS = {
    "d_channel_key",
    "d_object_key",
    "d_cutoff_date",
    "d_target_start_date",
    "d_target_end_date_exclusive",
    "d_future_failure_event_date",
    "d_future_alarm_event_date",
    "d_year",
    *TARGETS,
    *NUMERIC_FEATURES,
    *CATEGORICAL_FEATURES,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_package(root: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    if root:
        roots = [Path(root)]
    elif os.environ.get("LDT_KAGGLE_DATA_DIR"):
        roots = [Path(os.environ["LDT_KAGGLE_DATA_DIR"])]
    else:
        roots = [Path("/kaggle/input"), Path("data/kaggle_private_panel_v2")]
    matches: list[Path] = []
    for candidate in roots:
        if candidate.exists():
            matches.extend(candidate.rglob("panel_manifest_v2.json"))
    matches = sorted(set(path.resolve() for path in matches))
    if len(matches) != 1:
        raise RuntimeError(
            "Ожидался ровно один panel_manifest_v2.json; "
            f"найдено: {len(matches)}. Проверьте Add Input."
        )
    manifest_path = matches[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_path, manifest


def load_panel(root: str | Path | None = None) -> tuple[Any, dict[str, Any], Path]:
    import polars as pl

    manifest_path, manifest = discover_package(root)
    if manifest.get("panel_schema_version") != PANEL_SCHEMA_VERSION:
        raise RuntimeError(
            f"Несовместимая версия панели: {manifest.get('panel_schema_version')}"
        )
    if manifest.get("contains_2026_rows") is not False:
        raise RuntimeError("Пакет не прошёл блокировку 2026 года")
    data_path = manifest_path.parent / manifest["data_file"]
    if not data_path.exists():
        raise FileNotFoundError(data_path)
    if sha256_file(data_path) != manifest.get("data_sha256"):
        raise RuntimeError("Контрольная сумма Parquet не совпала")
    panel = pl.read_parquet(data_path)
    missing = sorted(REQUIRED_PANEL_COLUMNS - set(panel.columns))
    if missing:
        raise RuntimeError(f"В панели нет обязательных полей: {missing}")
    if panel.height != manifest.get("rows"):
        raise RuntimeError("Число строк не совпало с манифестом")
    if panel.select(pl.col("d_year").max()).item() >= 2026:
        raise RuntimeError("Обнаружены строки 2026 года")
    return panel, manifest, manifest_path


def assert_safe_features(features: list[str]) -> None:
    forbidden = [
        name
        for name in features
        if name in FORBIDDEN_FEATURES or name.startswith(FORBIDDEN_FEATURE_PREFIXES)
    ]
    if forbidden:
        raise ValueError(f"Запрещённые/утекающие признаки: {forbidden}")
    if len(features) != len(set(features)):
        raise ValueError("Признаки дублируются")


def feature_columns(variant: str) -> tuple[list[str], list[str], list[str]]:
    if variant not in FEATURE_VARIANTS:
        raise ValueError(f"Неизвестный набор признаков: {variant}")
    numeric = list(FEATURE_VARIANTS[variant])
    categorical = list(CATEGORICAL_FEATURES)
    if variant == "with_object_key_ablation":
        categorical.append("d_object_key")
    features = numeric + categorical
    assert_safe_features(features)
    return numeric, categorical, features


def temporal_splits(panel: Any, target: str) -> dict[str, Any]:
    import polars as pl

    if target not in TARGETS:
        raise ValueError(f"Неизвестная цель: {target}")
    labelled = panel.filter(pl.col(target).is_not_null())
    end = pl.col("d_target_end_date_exclusive")
    start = pl.col("d_target_start_date")
    year = pl.col("d_year")
    splits = {
        "train": labelled.filter(
            year.is_in([2019, 2020, 2022, 2023, 2024])
            & (end <= pl.lit(date(2025, 1, 1)))
        ),
        "calibration_2025_h1": labelled.filter(
            (year == 2025) & (end <= pl.lit(date(2025, 7, 1)))
        ),
        "validation_2025_h2": labelled.filter(
            (year == 2025)
            & (start >= pl.lit(date(2025, 7, 1)))
            & (end <= pl.lit(date(2026, 1, 1)))
        ),
        "stress_2021": labelled.filter(
            (year == 2021) & (end <= pl.lit(date(2022, 1, 1)))
        ),
    }
    empty = [name for name, frame in splits.items() if frame.is_empty()]
    if empty:
        raise RuntimeError(f"Пустые временные выборки: {empty}")
    return splits


def _smoke_frame(frame: Any, target: str, seed: int, per_class: int = 1500) -> Any:
    import polars as pl

    pieces = []
    for value in (0, 1):
        part = frame.filter(pl.col(target) == value)
        pieces.append(
            part.sample(n=min(per_class, part.height), seed=seed + value, shuffle=True)
        )
    return pl.concat(pieces, how="vertical").sort("d_cutoff_date")


def _sample_training(frame: Any, target: str, ratio: int, seed: int) -> Any:
    import polars as pl

    positives = frame.filter(pl.col(target) == 1)
    negatives = frame.filter(pl.col(target) == 0)
    if positives.is_empty() or negatives.is_empty():
        raise RuntimeError("В train нужны оба класса")
    keep = min(negatives.height, positives.height * ratio)
    weight = negatives.height / max(keep, 1)
    sampled_negative = negatives.sample(n=keep, seed=seed, shuffle=True)
    return pl.concat(
        [
            positives.with_columns(pl.lit(1.0).alias("d_sample_weight")),
            sampled_negative.with_columns(pl.lit(float(weight)).alias("d_sample_weight")),
        ],
        how="vertical",
    ).sample(fraction=1.0, seed=seed, shuffle=True)


def _to_pandas(frame: Any, columns: list[str]) -> Any:
    import pandas as pd

    return pd.DataFrame(frame.select(columns).to_dict(as_series=False))


def _fit_calibrator(probability: np.ndarray, y: np.ndarray) -> Any:
    from sklearn.linear_model import LogisticRegression

    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    model = LogisticRegression(random_state=0, max_iter=500)
    model.fit(logits, y)
    return model


def _calibrate(model: Any, probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    return model.predict_proba(logits)[:, 1]


def _select_threshold(y: np.ndarray, p: np.ndarray, minimum_precision: float) -> float:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y, p)
    candidates = np.flatnonzero(precision[:-1] >= minimum_precision)
    if candidates.size:
        return float(thresholds[candidates[np.argmax(recall[candidates])]])
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


def point_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, Any]:
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


def episode_metrics(
    frame: Any,
    probability: np.ndarray,
    target: str,
    threshold: float,
    budget_per_day: int,
    cooldown_hours: int,
) -> dict[str, Any]:
    import pandas as pd

    event_column = TARGETS[target]
    columns = [
        "d_channel_key",
        "d_cutoff_date",
        "d_target_start_date",
        "d_target_end_date_exclusive",
        event_column,
        target,
        "тип_датчика",
    ]
    data = _to_pandas(frame, columns)
    data["probability"] = probability
    for column in [
        "d_cutoff_date",
        "d_target_start_date",
        "d_target_end_date_exclusive",
        event_column,
    ]:
        data[column] = pd.to_datetime(data[column])
    alerts = data[np.isfinite(probability) & (probability >= threshold)].copy()
    alerts = alerts.sort_values(
        ["d_cutoff_date", "probability", "d_channel_key"],
        ascending=[True, False, True],
        kind="mergesort",
    ).groupby("d_cutoff_date", sort=False).head(budget_per_day)
    alerts["d_alert_time"] = alerts["d_cutoff_date"] + pd.to_timedelta(1, unit="D")
    keep: list[int] = []
    last: dict[str, Any] = {}
    cooldown = pd.to_timedelta(cooldown_hours, unit="h")
    for index, row in alerts.sort_values(["d_alert_time", "d_channel_key"]).iterrows():
        previous = last.get(row["d_channel_key"])
        if previous is None or row["d_alert_time"] - previous >= cooldown:
            keep.append(index)
            last[row["d_channel_key"]] = row["d_alert_time"]
    alerts = alerts.loc[keep]
    events = data.loc[data[target] == 1, ["d_channel_key", event_column]].dropna()
    events = events.drop_duplicates(["d_channel_key", event_column]).reset_index(drop=True)
    matched_events: set[int] = set()
    matched_alerts = 0
    for _, alert in alerts.sort_values("d_alert_time").iterrows():
        candidates = events[
            (events["d_channel_key"] == alert["d_channel_key"])
            & (events[event_column] >= alert["d_target_start_date"])
            & (events[event_column] < alert["d_target_end_date_exclusive"])
            & (~events.index.isin(matched_events))
        ]
        if not candidates.empty:
            matched_events.add(int(candidates.sort_values(event_column).index[0]))
            matched_alerts += 1
    return {
        "alert_budget_per_day": budget_per_day,
        "cooldown_hours": cooldown_hours,
        "alert_episodes": int(len(alerts)),
        "proxy_events": int(len(events)),
        "matched_alerts": matched_alerts,
        "precision": matched_alerts / max(len(alerts), 1),
        "recall": len(matched_events) / max(len(events), 1),
    }


def per_sensor_metrics(frame: Any, probability: np.ndarray, target: str) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score

    data = _to_pandas(frame, ["тип_датчика", target])
    data["probability"] = probability
    output: dict[str, Any] = {}
    for sensor, group in data.groupby("тип_датчика", dropna=False):
        y = group[target].to_numpy(dtype=np.int8)
        output[str(sensor)] = {
            "rows": int(len(group)),
            "positives": int(y.sum()),
            "pr_auc": (
                float(average_precision_score(y, group["probability"]))
                if np.unique(y).size == 2
                else None
            ),
        }
    return output


def _rule_probability(frame: Any) -> np.ndarray:
    alarm = frame["d_alarm_share_24h"].fill_null(0).to_numpy()
    previous = frame["d_alarm_share_previous_24h"].fill_null(0).to_numpy()
    failure = (
        frame["d_failure_state_event_count_24h"].fill_null(0).to_numpy() > 0
    ).astype(float)
    return np.clip(np.maximum.reduce([alarm, 0.5 * previous, 0.75 * failure]), 0, 1)


def gpu_description() -> str:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        return completed.stdout.strip()
    except Exception:
        return "GPU_NOT_AVAILABLE"


def run_model(
    panel: Any,
    manifest: dict[str, Any],
    model_name: str,
    config: dict[str, Any],
    output_dir: str | Path = "/kaggle/working",
) -> dict[str, Any]:
    import joblib
    import pandas as pd

    if model_name not in {"rule", "logistic", "lightgbm", "catboost"}:
        raise ValueError(model_name)
    target = config["target"]
    seed = int(config["random_seed"])
    numeric, categorical, features = feature_columns(config["feature_variant"])
    splits = temporal_splits(panel, target)
    if config["run_mode"] == "smoke":
        splits = {
            name: _smoke_frame(frame, target, seed + index)
            for index, (name, frame) in enumerate(splits.items())
        }
    elif config["run_mode"] != "full":
        raise ValueError("run_mode must be full or smoke")

    train = _sample_training(
        splits["train"], target, int(config["negative_to_positive_ratio"]), seed
    )
    train_x = _to_pandas(train, features)
    train_y = train[target].to_numpy().astype(np.int8)
    train_weight = train["d_sample_weight"].to_numpy()
    calibration = splits["calibration_2025_h1"]
    calibration_x = _to_pandas(calibration, features)
    calibration_y = calibration[target].to_numpy().astype(np.int8)
    model: Any = None
    category_levels: dict[str, list[str]] = {}

    def cat_frame(x: Any) -> Any:
        result = x.copy()
        for name in categorical:
            result[name] = result[name].fillna("__MISSING__").astype(str)
        return result

    def lightgbm_frame(x: Any, training: bool = False) -> Any:
        result = x.copy()
        for name in categorical:
            values = result[name].fillna("__MISSING__").astype(str)
            if training:
                category_levels[name] = sorted(values.unique().tolist())
            result[name] = values.astype(
                pd.CategoricalDtype(categories=category_levels[name])
            )
        return result

    started = time.perf_counter()
    if model_name == "rule":
        calibration_probability = _rule_probability(calibration)
        threshold = 0.5
        calibrator = None
    elif model_name == "logistic":
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler

        model = Pipeline(
            [
                (
                    "features",
                    ColumnTransformer(
                        [
                            (
                                "numeric",
                                Pipeline(
                                    [
                                        ("impute", SimpleImputer(strategy="median")),
                                        ("scale", StandardScaler()),
                                    ]
                                ),
                                numeric,
                            ),
                            (
                                "categorical",
                                Pipeline(
                                    [
                                        ("impute", SimpleImputer(strategy="most_frequent")),
                                        (
                                            "onehot",
                                            OneHotEncoder(
                                                handle_unknown="ignore",
                                                min_frequency=(2 if config["run_mode"] == "smoke" else 20),
                                            ),
                                        ),
                                    ]
                                ),
                                categorical,
                            ),
                        ]
                    ),
                ),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1000, random_state=seed, solver="liblinear"
                    ),
                ),
            ]
        )
        model.fit(train_x, train_y, model__sample_weight=train_weight)
        raw = model.predict_proba(calibration_x)[:, 1]
        calibrator = _fit_calibrator(raw, calibration_y)
        calibration_probability = _calibrate(calibrator, raw)
        threshold = _select_threshold(
            calibration_y, calibration_probability, config["minimum_precision"]
        )
    elif model_name == "lightgbm":
        from lightgbm import LGBMClassifier

        model = LGBMClassifier(
            objective="binary",
            n_estimators=(30 if config["run_mode"] == "smoke" else config["iterations"]),
            learning_rate=0.05,
            num_leaves=63,
            max_bin=63,
            random_state=seed,
            n_jobs=-1,
            device_type="cpu",
            verbosity=-1,
        )
        model.fit(
            lightgbm_frame(train_x, training=True),
            train_y,
            sample_weight=train_weight,
            categorical_feature=categorical,
        )
        raw = model.predict_proba(lightgbm_frame(calibration_x))[:, 1]
        calibrator = _fit_calibrator(raw, calibration_y)
        calibration_probability = _calibrate(calibrator, raw)
        threshold = _select_threshold(
            calibration_y, calibration_probability, config["minimum_precision"]
        )
    else:
        from catboost import CatBoostClassifier

        task_type = config.get("catboost_task_type", "GPU")
        if task_type == "GPU" and gpu_description() == "GPU_NOT_AVAILABLE":
            raise RuntimeError(
                "CatBoost настроен на GPU, но NVIDIA GPU не обнаружен. "
                "В Kaggle выберите Settings → Accelerator → GPU."
            )
        model = CatBoostClassifier(
            iterations=(30 if config["run_mode"] == "smoke" else config["iterations"]),
            depth=7,
            learning_rate=0.08,
            loss_function="Logloss",
            eval_metric="PRAUC",
            random_seed=seed,
            task_type=task_type,
            allow_writing_files=False,
            verbose=False,
        )
        model.fit(
            cat_frame(train_x),
            train_y,
            cat_features=categorical,
            sample_weight=train_weight,
        )
        raw = model.predict_proba(cat_frame(calibration_x))[:, 1]
        calibrator = _fit_calibrator(raw, calibration_y)
        calibration_probability = _calibrate(calibrator, raw)
        threshold = _select_threshold(
            calibration_y, calibration_probability, config["minimum_precision"]
        )

    def predict(frame: Any) -> np.ndarray:
        if model_name == "rule":
            return _rule_probability(frame)
        x = _to_pandas(frame, features)
        if model_name == "catboost":
            raw_probability = model.predict_proba(cat_frame(x))[:, 1]
        elif model_name == "lightgbm":
            raw_probability = model.predict_proba(lightgbm_frame(x))[:, 1]
        else:
            raw_probability = model.predict_proba(x)[:, 1]
        return _calibrate(calibrator, raw_probability)

    validation = splits["validation_2025_h2"]
    validation_probability = predict(validation)
    validation_y = validation[target].to_numpy().astype(np.int8)
    metrics = point_metrics(validation_y, validation_probability, threshold)
    metrics["alert_episode_evaluation"] = episode_metrics(
        validation,
        validation_probability,
        target,
        threshold,
        int(config["alert_budget_per_day"]),
        int(config["cooldown_hours"]),
    )
    metrics["per_sensor"] = per_sensor_metrics(
        validation, validation_probability, target
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions = _to_pandas(
        validation,
        ["d_channel_key", "d_cutoff_date", "тип_датчика", target],
    )
    predictions["probability"] = validation_probability
    predictions["prediction"] = (validation_probability >= threshold).astype(np.int8)
    import polars as pl

    pl.DataFrame(predictions.to_dict(orient="list")).write_parquet(
        output / f"predictions_{model_name}_2025_h2.parquet", compression="zstd"
    )
    if model_name == "logistic":
        joblib.dump(model, output / "model_logistic.joblib")
    elif model_name == "lightgbm":
        (output / "model_lightgbm.txt").write_text(
            model.booster_.model_to_string(), encoding="utf-8"
        )
    elif model_name == "catboost":
        model.save_model(output / "model_catboost.cbm")
    if calibrator is not None:
        joblib.dump(calibrator, output / f"calibrator_{model_name}.joblib")

    result = {
        "status": "SMOKE_NON_COMPARABLE" if config["run_mode"] == "smoke" else "FULL",
        "model": model_name,
        "device": (
            gpu_description()
            if model_name == "catboost" and config.get("catboost_task_type") == "GPU"
            else "CPU"
        ),
        "target": target,
        "target_semantics": "observable proxy, not confirmed physical failure",
        "feature_variant": config["feature_variant"],
        "feature_columns": features,
        "panel_data_sha256": manifest["data_sha256"],
        "threshold_selection_period": "2025 H1",
        "headline_evaluation_period": "2025 H2",
        "threshold": threshold,
        "minimum_precision_requested": config["minimum_precision"],
        "training_rows_after_negative_sampling": int(train.height),
        "negative_sampling_uses_inverse_probability_weights": True,
        "metrics_2025_h2": metrics,
        "runtime_seconds": time.perf_counter() - started,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "warning_ru": (
            "Это смоук-тест; его метрики нельзя сравнивать."
            if config["run_mode"] == "smoke"
            else "2025 H2 — независимая development-validation; это не физические отказы."
        ),
    }
    (output / f"results_{model_name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def save_validation_charts(model_name: str, output_dir: str | Path = "/kaggle/working") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import polars as pl
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import PrecisionRecallDisplay

    output = Path(output_dir)
    predictions = pd.DataFrame(
        pl.read_parquet(output / f"predictions_{model_name}_2025_h2.parquet").to_dict(
            as_series=False
        )
    )
    target = next(name for name in TARGETS if name in predictions.columns)
    y = predictions[target].to_numpy(dtype=np.int8)
    p = predictions["probability"].to_numpy()
    figure, axes = plt.subplots(1, 2, figsize=(12, 4))
    PrecisionRecallDisplay.from_predictions(y, p, ax=axes[0])
    axes[0].set_title("Кривая Precision–Recall, 2025 H2")
    observed, predicted = calibration_curve(y, p, n_bins=10, strategy="quantile")
    axes[1].plot(predicted, observed, marker="o", label="модель")
    axes[1].plot([0, 1], [0, 1], "--", label="идеал")
    axes[1].set(xlabel="Прогноз вероятности", ylabel="Фактическая доля", title="Калибровка")
    axes[1].legend()
    figure.tight_layout()
    chart_path = output / f"charts_{model_name}_2025_h2.png"
    figure.savefig(chart_path, dpi=150)
    plt.close(figure)
    try:
        from IPython.display import Image, display

        display(Image(filename=str(chart_path)))
    except ImportError:
        pass
