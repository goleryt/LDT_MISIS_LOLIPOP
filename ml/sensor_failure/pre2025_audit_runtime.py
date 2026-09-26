"""Pre-2025 аудит основной proxy-цели: baseline-лестница, shortcut-ablations,
clean-history sensitivity, channel propensity, gates и stress 2021 (ноутбук 05).

Модуль самодостаточен: генератор встраивает его в notebook дословно.
Работает только с обезличенной panel v2; строки 2025 H2 и 2026 в память не загружаются.
"""

from __future__ import annotations


import gc
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Контракт панели (скопирован из общего runtime четырёх исходных notebook)
# ---------------------------------------------------------------------------
PANEL_SCHEMA_VERSION = "2.0"
TARGET = "target_failure_state_onset_24h"
EVENT_COLUMN = "d_future_failure_event_date"
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
FORBIDDEN_FEATURE_PREFIXES = ("target_", "d_future_", "d_hist_prior")
FORBIDDEN_FEATURES = {
    "d_channel_key",
    "d_object_key",
    "ид_события",
    "ид_канала_данных",
    "ид_объект",
    "дата",
    "время",
    "тревожное",
    "значение_датчика",
    "d_last_available_time",
    "d_cutoff_date",
    "d_target_start_date",
    "d_target_end_date_exclusive",
    "d_year",
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
DATE_COLUMNS = [
    "d_cutoff_date",
    "d_target_start_date",
    "d_target_end_date_exclusive",
    EVENT_COLUMN,
]

# Наборы признаков -----------------------------------------------------------
RECURRENCE = ["d_failure_state_event_count_24h", "d_days_since_failure_state_event"]
CALENDAR = ["d_month", "d_weekday"]
CATALOGUE_NUMERIC = ["d_catalogue_match"]
# Имена из задания -> точные имена колонок панели. В задании у четырёх
# показателей пропущен суффикс `_24h`; в панели таких колонок без суффикса нет.
CONDITION_ONLY_REQUESTED = [
    "d_alarm_count_24h",
    "d_alarm_share_24h",
    "d_value_numeric_mean",
    "d_value_numeric_min",
    "d_value_numeric_max",
    "d_value_numeric_std",
    "d_value_numeric_last",
    "d_state_n_unique_24h",
    "d_gap_days_since_previous",
    "d_event_count_previous_24h",
    "d_alarm_count_previous_24h",
    "d_alarm_share_previous_24h",
    "d_value_numeric_previous",
]
HIST_FEATURES = [
    "d_hist_eligible_days_90d",
    "d_hist_positive_days_90d",
    "d_hist_failure_rate_90d",
    "d_hist_eligible_days_365d",
    "d_hist_positive_days_365d",
    "d_hist_failure_rate_365d",
    "d_hist_eligible_days_all",
    "d_hist_positive_days_all",
    "d_hist_failure_rate_eb",
]

FOLDS = [
    {
        "name": "fold_2023",
        "train_years": [2019, 2020, 2022],
        "train_end": date(2023, 1, 1),
        "calibration": (date(2023, 1, 1), date(2023, 7, 1)),
        "validation": (date(2023, 7, 1), date(2024, 1, 1)),
    },
    {
        "name": "fold_2024",
        "train_years": [2019, 2020, 2022, 2023],
        "train_end": date(2024, 1, 1),
        "calibration": (date(2024, 1, 1), date(2024, 7, 1)),
        "validation": (date(2024, 7, 1), date(2025, 1, 1)),
    },
]
LOAD_END_EXCLUSIVE = date(2025, 1, 1)  # ничего с окном цели позже в память не попадает
STRESS_YEAR = 2021

BASELINES = ["B0_constant", "B1_type_prevalence", "B2_recurrence", "B3_rule", "B4_logistic"]
M0 = "M0_lightgbm"


class ContractError(RuntimeError):
    """Нарушение контракта данных: дальнейшие расчёты запрещены."""


class ReproductionError(RuntimeError):
    """M0 не воспроизводится: дальнейшие эксперименты запрещены."""


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def log(*parts: Any) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


def _clean(value: Any) -> Any:
    """Рекурсивно заменяет NaN/inf на None, чтобы JSON был валидным."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def environment_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    }
    try:
        with open("/proc/meminfo", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("MemTotal"):
                    info["ram_total_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        info["ram_total_gb"] = None
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True, timeout=20,
        )
        info["gpu"] = completed.stdout.strip() or "GPU_NOT_AVAILABLE"
    except Exception:
        info["gpu"] = "GPU_NOT_AVAILABLE"
    info["accelerator_none"] = info["gpu"] == "GPU_NOT_AVAILABLE"
    versions = {}
    for name in ("numpy", "pandas", "polars", "pyarrow", "sklearn", "lightgbm", "scipy"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:
            versions[name] = "not_installed"
    info["libraries"] = versions
    return info


# ---------------------------------------------------------------------------
# 1. Preflight и загрузка
# ---------------------------------------------------------------------------
def discover_manifest() -> tuple[Path, dict[str, Any]]:
    override = os.environ.get("LDT_KAGGLE_DATA_DIR")
    roots = [Path(override)] if override else [Path("/kaggle/input")]
    matches: list[Path] = []
    for root in roots:
        if root.exists():
            matches.extend(root.rglob("panel_manifest_v2.json"))
    matches = sorted({path.resolve() for path in matches})
    if len(matches) != 1:
        raise ContractError(
            f"Ожидался ровно один panel_manifest_v2.json, найдено: {len(matches)}. "
            "Проверьте Add Input: должен быть подключён ровно один приватный dataset панели."
        )
    manifest = json.loads(matches[0].read_text(encoding="utf-8"))
    return matches[0], manifest


def _as_date_expr(pl: Any, name: str, dtype: Any) -> Any:
    column = pl.col(name)
    if dtype == pl.Date:
        return column
    if isinstance(dtype, pl.Datetime) or dtype == pl.Datetime:
        return column.dt.date()
    if dtype in (pl.String, pl.Utf8):
        return column.str.slice(0, 10).str.to_date("%Y-%m-%d", strict=False)
    return column.cast(pl.Date, strict=False)


def preflight(mode: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Проверка контракта. Любое несовпадение -> ContractError."""
    import polars as pl

    manifest_path, manifest = discover_manifest()
    checks: dict[str, Any] = {"manifest_found": True}
    if manifest.get("panel_schema_version") != PANEL_SCHEMA_VERSION:
        raise ContractError(
            f"Версия схемы {manifest.get('panel_schema_version')!r}, ожидалась {PANEL_SCHEMA_VERSION!r}"
        )
    checks["schema_version"] = PANEL_SCHEMA_VERSION
    if manifest.get("contains_2026_rows") is not False:
        raise ContractError("Манифест не подтверждает отсутствие строк 2026 года")
    if manifest.get("raw_identifiers_included") not in (False, None):
        raise ContractError("Манифест сообщает о сырых идентификаторах в панели")
    checks["raw_identifiers_included"] = bool(manifest.get("raw_identifiers_included", False))
    data_path = manifest_path.parent / str(manifest.get("data_file", ""))
    if not data_path.is_file():
        raise ContractError("Файл панели из манифеста не найден рядом с манифестом")
    expected_hash = manifest.get("data_sha256")
    if not expected_hash:
        raise ContractError("В манифесте нет data_sha256")
    started = time.perf_counter()
    actual_hash = sha256_file(data_path)
    checks["sha256_seconds"] = round(time.perf_counter() - started, 1)
    if actual_hash != expected_hash:
        raise ContractError("SHA-256 файла панели не совпал с манифестом")
    checks["sha256_match"] = True

    lazy = pl.scan_parquet(data_path)
    schema = lazy.collect_schema()
    missing = sorted(REQUIRED_PANEL_COLUMNS - set(schema.names()))
    if missing:
        raise ContractError(f"В панели нет обязательных полей: {missing}")
    for boundary in ("d_target_start_date", "d_target_end_date_exclusive"):
        if boundary not in schema.names():
            raise ContractError(f"Нет точного поля границы таргета: {boundary}")
    checks["required_columns_present"] = True
    cutoff = _as_date_expr(pl, "d_cutoff_date", schema["d_cutoff_date"])
    # Только агрегаты по всему файлу: число строк, min/max даты, max года.
    agg = lazy.select(
        pl.len().alias("rows"),
        cutoff.min().alias("date_min"),
        cutoff.max().alias("date_max"),
        pl.col("d_year").max().alias("year_max"),
    ).collect()
    rows = int(agg["rows"][0])
    if manifest.get("rows") is not None and rows != int(manifest["rows"]):
        raise ContractError("Число строк не совпало с манифестом")
    checks["rows_total_file"] = rows
    if int(agg["year_max"][0]) >= 2026:
        raise ContractError("В панели есть строки 2026 года")
    checks["year_max"] = int(agg["year_max"][0])
    date_min, date_max = agg["date_min"][0], agg["date_max"][0]
    for key, value in (("date_min", date_min), ("date_max", date_max)):
        declared = manifest.get(key)
        if declared is None:
            checks[f"{key}_declared"] = "not_in_manifest"
        elif str(declared)[:10] != str(value)[:10]:
            raise ContractError(f"{key}: в манифесте {declared}, в файле {value}")
        else:
            checks[f"{key}_declared"] = "match"
    checks["date_min"] = str(date_min)
    checks["date_max"] = str(date_max)
    checks["mode"] = mode
    return data_path, manifest, checks


def load_pre2025(data_path: Path, mode: str, smoke_share: int) -> Any:
    """Загружает только размеченные строки с окном цели, закрытым до 2025-01-01."""
    import polars as pl

    lazy = pl.scan_parquet(data_path)
    schema = lazy.collect_schema()
    columns = sorted(
        REQUIRED_PANEL_COLUMNS - {"target_alarm_onset_24h", "d_future_alarm_event_date"}
    )
    exprs = []
    for name in columns:
        if name in DATE_COLUMNS:
            exprs.append(_as_date_expr(pl, name, schema[name]).alias(name))
        else:
            exprs.append(pl.col(name))
    frame = (
        lazy.select(exprs)
        .filter(
            pl.col(TARGET).is_not_null()
            & (pl.col("d_year") <= 2024)
            & (pl.col("d_target_end_date_exclusive") <= pl.lit(LOAD_END_EXCLUSIVE))
        )
    )
    if mode == "SMOKE":
        # Детерминированная выборка ~1/smoke_share каналов; порядок во времени сохраняется.
        frame = frame.filter(pl.col("d_channel_key").hash(seed=20260921) % smoke_share == 0)
    frame = frame.collect()
    frame = frame.with_columns(pl.col(TARGET).cast(pl.Int8))
    for name in CATEGORICAL_FEATURES:
        frame = frame.with_columns(pl.col(name).cast(pl.String))
    frame = frame.sort(["d_cutoff_date", "d_channel_key"])
    if frame.is_empty():
        raise ContractError("После фильтра до 2025 года не осталось размеченных строк")
    if frame["d_target_end_date_exclusive"].max() > LOAD_END_EXCLUSIVE:
        raise ContractError("В память попали строки с окном цели после 2025-01-01")
    return frame


# ---------------------------------------------------------------------------
# 2. Channel propensity (causal, as-of по концу окна цели)
# ---------------------------------------------------------------------------
def build_propensity(frame: Any, m_grid: list[int], type_prior_min_rows: int = 100) -> Any:
    """Добавляет исторические признаки канала.

    Историческая строка учитывается для текущей строки, только если её
    d_target_end_date_exclusive <= d_cutoff_date + 1 день (конец суток D).
    Считаются только существующие размеченные строки: пропущенные
    channel-days не становятся отрицательными. 2021 год в историю не входит.
    Сдвиги по номеру строки не используются.
    """
    import polars as pl

    key = (pl.col("d_cutoff_date") + pl.duration(days=1)).alias("_key")
    left = frame.select(
        pl.int_range(0, pl.len()).alias("_row"),
        "d_channel_key", "тип_датчика", key,
    )
    history = frame.filter(pl.col("d_year") != STRESS_YEAR).select(
        "d_channel_key", "тип_датчика",
        pl.col("d_target_end_date_exclusive").alias("_end"),
        pl.col(TARGET).cast(pl.Int64).alias("_y"),
    )

    def cumulative(by: list[str]) -> Any:
        grouped = (
            history.group_by(by + ["_end"])
            .agg(pl.len().alias("_n"), pl.col("_y").sum().alias("_p"))
            .sort(by + ["_end"])
        )
        if by:
            grouped = grouped.with_columns(
                pl.col("_n").cum_sum().over(by).alias("_cn"),
                pl.col("_p").cum_sum().over(by).alias("_cp"),
            )
        else:
            grouped = grouped.with_columns(
                pl.col("_n").cum_sum().alias("_cn"), pl.col("_p").cum_sum().alias("_cp")
            )
        return grouped.select(by + ["_end", "_cn", "_cp"]).sort("_end")

    def asof(base: Any, table: Any, by: list[str], shift_days: int, suffix: str) -> Any:
        probe = base.with_columns((pl.col("_key") - pl.duration(days=shift_days)).alias("_probe"))
        probe = probe.sort("_probe")
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # сортировка обеспечена выше; проверено самотестом
            joined = probe.join_asof(
                table, left_on="_probe", right_on="_end", by=by or None, strategy="backward"
            )
        return joined.select(
            "_row",
            pl.col("_cn").fill_null(0).alias(f"_cn{suffix}"),
            pl.col("_cp").fill_null(0).alias(f"_cp{suffix}"),
        )

    channel_table = cumulative(["d_channel_key"])
    type_table = cumulative(["тип_датчика"])
    global_table = cumulative([])
    base = left.sort("_key")
    parts = [
        asof(base, channel_table, ["d_channel_key"], 0, "_all"),
        asof(base, channel_table, ["d_channel_key"], 90, "_m90"),
        asof(base, channel_table, ["d_channel_key"], 365, "_m365"),
        asof(base.filter(pl.col("тип_датчика").is_not_null()), type_table, ["тип_датчика"], 0, "_type"),
        asof(base, global_table, [], 0, "_global"),
    ]
    result = left.select("_row")
    for part in parts:
        result = result.join(part, on="_row", how="left")
    result = result.sort("_row").with_columns(
        pl.col("_cn_type").fill_null(0), pl.col("_cp_type").fill_null(0)
    )
    n90 = pl.col("_cn_all") - pl.col("_cn_m90")
    p90 = pl.col("_cp_all") - pl.col("_cp_m90")
    n365 = pl.col("_cn_all") - pl.col("_cn_m365")
    p365 = pl.col("_cp_all") - pl.col("_cp_m365")
    prior = (
        pl.when(pl.col("_cn_type") >= type_prior_min_rows)
        .then(pl.col("_cp_type") / pl.col("_cn_type"))
        .when(pl.col("_cn_global") > 0)
        .then(pl.col("_cp_global") / pl.col("_cn_global"))
        .otherwise(None)
    )
    result = result.with_columns(
        n90.cast(pl.Float32).alias("d_hist_eligible_days_90d"),
        p90.cast(pl.Float32).alias("d_hist_positive_days_90d"),
        pl.when(n90 > 0).then(p90 / n90).otherwise(None).cast(pl.Float32).alias("d_hist_failure_rate_90d"),
        n365.cast(pl.Float32).alias("d_hist_eligible_days_365d"),
        p365.cast(pl.Float32).alias("d_hist_positive_days_365d"),
        pl.when(n365 > 0).then(p365 / n365).otherwise(None).cast(pl.Float32).alias("d_hist_failure_rate_365d"),
        pl.col("_cn_all").cast(pl.Float32).alias("d_hist_eligible_days_all"),
        pl.col("_cp_all").cast(pl.Float32).alias("d_hist_positive_days_all"),
        prior.cast(pl.Float64).alias("d_hist_prior_rate"),
        pl.when(pl.col("_cn_type") >= type_prior_min_rows).then(pl.lit("type"))
        .when(pl.col("_cn_global") > 0).then(pl.lit("global")).otherwise(pl.lit("none"))
        .alias("d_hist_prior_source"),
    )
    eb = [
        ((pl.col("d_hist_positive_days_all") + m * pl.col("d_hist_prior_rate"))
         / (pl.col("d_hist_eligible_days_all") + m)).cast(pl.Float32).alias(f"d_hist_failure_rate_eb_m{m}")
        for m in m_grid
    ]
    result = result.with_columns(eb)
    keep = [c for c in result.columns if c.startswith("d_hist_")]
    return frame.hstack(result.select(keep))


# ---------------------------------------------------------------------------
# 3. Функции модели (логика повторяет общий runtime исходных notebook)
# ---------------------------------------------------------------------------
def assert_safe_features(features: list[str]) -> None:
    bad = [f for f in features if f in FORBIDDEN_FEATURES or f.startswith(FORBIDDEN_FEATURE_PREFIXES)]
    if bad:
        raise ValueError(f"Запрещённые/утекающие признаки: {bad}")
    if len(features) != len(set(features)):
        raise ValueError("Признаки дублируются")


def sample_training(frame: Any, ratio: int, seed: int) -> Any:
    import polars as pl

    positives = frame.filter(pl.col(TARGET) == 1)
    negatives = frame.filter(pl.col(TARGET) == 0)
    if positives.is_empty() or negatives.is_empty():
        raise ReproductionError("В train нужны оба класса")
    keep = min(negatives.height, positives.height * ratio)
    weight = negatives.height / max(keep, 1)
    sampled = negatives.sample(n=keep, seed=seed, shuffle=True)
    return pl.concat(
        [
            positives.with_columns(pl.lit(1.0).alias("d_sample_weight")),
            sampled.with_columns(pl.lit(float(weight)).alias("d_sample_weight")),
        ],
        how="vertical",
    ).sample(fraction=1.0, seed=seed, shuffle=True)


def to_pandas(frame: Any, columns: list[str]) -> Any:
    try:
        return frame.select(columns).to_pandas()
    except Exception:
        import pandas as pd

        return pd.DataFrame(frame.select(columns).to_dict(as_series=False))


def fit_platt(probability: np.ndarray, y: np.ndarray) -> Any:
    from sklearn.linear_model import LogisticRegression

    if np.unique(y).size < 2:
        return None  # один класс в H1: калибровка невозможна, скор остаётся как есть

    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    model = LogisticRegression(random_state=0, max_iter=500)
    model.fit(logits, y)
    return model


def apply_platt(model: Any, probability: np.ndarray) -> np.ndarray:
    if model is None:
        return np.asarray(probability, dtype=float)
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    return model.predict_proba(logits)[:, 1]


def select_threshold(y: np.ndarray, p: np.ndarray, minimum_precision: float) -> float:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y, p)
    candidates = np.flatnonzero(precision[:-1] >= minimum_precision)
    if candidates.size:
        return float(thresholds[candidates[np.argmax(recall[candidates])]])
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.nanargmax(f1))])


def ece_10(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    result = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (p >= left) & (p < right if right < 1 else p <= right)
        if mask.any():
            result += mask.mean() * abs(float(y[mask].mean() - p[mask].mean()))
    return float(result)


def rule_score(frame: Any) -> np.ndarray:
    alarm = frame["d_alarm_share_24h"].fill_null(0).to_numpy().astype(float)
    previous = frame["d_alarm_share_previous_24h"].fill_null(0).to_numpy().astype(float)
    failure = (frame["d_failure_state_event_count_24h"].fill_null(0).to_numpy() > 0).astype(float)
    return np.clip(np.maximum.reduce([alarm, 0.5 * previous, 0.75 * failure]), 0, 1)


def recurrence_score(frame: Any) -> np.ndarray:
    days = frame["d_days_since_failure_state_event"].to_numpy().astype(float)
    score = np.zeros_like(days)
    present = np.isfinite(days)
    score[present] = 1.0 / (1.0 + np.maximum(days[present], 0.0))
    return score


class LightGBMModel:
    """CPU LightGBM с параметрами исходного notebook; категории фиксируются по train."""

    def __init__(self, numeric: list[str], categorical: list[str], config: dict[str, Any]):
        self.numeric = list(numeric)
        self.categorical = list(categorical)
        self.features = self.numeric + self.categorical
        assert_safe_features(self.features)
        self.config = config
        self.levels: dict[str, list[str]] = {}
        self.model: Any = None

    def _frame(self, frame: Any, training: bool = False) -> Any:
        import pandas as pd

        x = to_pandas(frame, self.features)
        for name in self.categorical:
            values = x[name].fillna("__MISSING__").astype(str)
            if training:
                self.levels[name] = sorted(values.unique().tolist())
            x[name] = values.astype(pd.CategoricalDtype(categories=self.levels[name]))
        return x

    def fit(self, train: Any) -> "LightGBMModel":
        from lightgbm import LGBMClassifier

        self.model = LGBMClassifier(
            objective="binary",
            n_estimators=int(self.config["lgbm_iterations"]),
            learning_rate=0.05,
            num_leaves=63,
            max_bin=63,
            random_state=int(self.config["random_seed"]),
            n_jobs=-1,
            device_type="cpu",
            verbosity=-1,
        )
        self.model.fit(
            self._frame(train, training=True),
            train[TARGET].to_numpy().astype(np.int8),
            sample_weight=train["d_sample_weight"].to_numpy(),
            categorical_feature=(self.categorical if self.categorical else "auto"),
        )
        return self

    def raw(self, frame: Any) -> np.ndarray:
        return self.model.predict_proba(self._frame(frame))[:, 1]

    def importance(self) -> dict[str, float]:
        gain = self.model.booster_.feature_importance("gain")
        total = float(gain.sum()) or 1.0
        return {f: float(g / total) for f, g in zip(self.features, gain)}


class LogisticModel:
    """Регуляризованная логистическая регрессия исходного pipeline (B4)."""

    def __init__(self, numeric: list[str], categorical: list[str], config: dict[str, Any]):
        self.numeric, self.categorical = list(numeric), list(categorical)
        self.features = self.numeric + self.categorical
        assert_safe_features(self.features)
        self.config = config

    def fit(self, train: Any) -> "LogisticModel":
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler

        min_frequency = 2 if self.config["mode"] == "SMOKE" else 20
        self.model = Pipeline([
            ("features", ColumnTransformer([
                ("numeric", Pipeline([
                    ("impute", SimpleImputer(strategy="median")),
                    ("scale", StandardScaler()),
                ]), self.numeric),
                ("categorical", Pipeline([
                    ("impute", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=min_frequency)),
                ]), self.categorical),
            ])),
            ("model", LogisticRegression(max_iter=1000, random_state=int(self.config["random_seed"]),
                                         solver="liblinear")),
        ])
        x = to_pandas(train, self.features)
        for name in self.categorical:
            x[name] = x[name].astype(object).where(x[name].notna(), np.nan)
        self.model.fit(x, train[TARGET].to_numpy().astype(np.int8),
                       model__sample_weight=train["d_sample_weight"].to_numpy())
        return self

    def raw(self, frame: Any) -> np.ndarray:
        x = to_pandas(frame, self.features)
        for name in self.categorical:
            x[name] = x[name].astype(object).where(x[name].notna(), np.nan)
        return self.model.predict_proba(x)[:, 1]


# ---------------------------------------------------------------------------
# 4. Метрики
# ---------------------------------------------------------------------------
def point_metrics(y: np.ndarray, p: np.ndarray, threshold: float, b0_prevalence: float) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss

    predicted = p >= threshold
    tp = int(((y == 1) & predicted).sum())
    fp = int(((y == 0) & predicted).sum())
    fn = int(((y == 1) & ~predicted).sum())
    has_both = np.unique(y).size == 2
    pr_auc = float(average_precision_score(y, p)) if has_both else None
    return {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()) if len(y) else None,
        "pr_auc": pr_auc,
        # PR-AUC константы B0 на тех же строках равен их prevalence.
        "lift_over_b0": (pr_auc / float(y.mean())) if (pr_auc is not None and y.mean() > 0) else None,
        "b0_constant_value_pre_validation": float(b0_prevalence),
        "brier_score": float(brier_score_loss(y, p)) if len(y) else None,
        "ece_10_bins": ece_10(y, p) if len(y) else None,
        "threshold": float(threshold),
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(tp + fn, 1),
        "false_alerts_per_1000_eligible_channel_days": 1000 * fp / max(len(y), 1),
    }


class EvalFrame:
    """Numpy-представление validation-строк фолда для быстрых эпизодных метрик."""

    def __init__(self, frame: Any, period_start: date):
        keys = frame["d_channel_key"].to_numpy()
        unique, codes = np.unique(keys.astype(str), return_inverse=True)
        # Порядок кодов совпадает со строковым порядком ключей (как tie-break в исходном коде).
        self.n_channels = len(unique)
        self.channel = codes.astype(np.int64)
        del unique, keys
        to_days = lambda name: frame[name].cast(__import__("polars").Int32).to_numpy()  # noqa: E731
        self.cutoff = to_days("d_cutoff_date").astype(np.int64)
        self.start = to_days("d_target_start_date").astype(np.int64)
        self.end = to_days("d_target_end_date_exclusive").astype(np.int64)
        event = frame[EVENT_COLUMN].cast(__import__("polars").Int32).to_numpy()
        self.event = np.where(np.isnan(event.astype(float)), -(10 ** 9), event).astype(np.int64)
        self.y = frame[TARGET].to_numpy().astype(np.int8)
        origin = (period_start - date(1970, 1, 1)).days
        self.week = np.maximum((self.cutoff - origin) // 7, 0).astype(np.int64)
        self.n_weeks = int(self.week.max()) + 1 if len(self.week) else 1
        self.origin = origin
        self.month = frame["d_cutoff_date"].dt.strftime("%Y-%m").to_numpy()
        self.sensor = frame["тип_датчика"].fill_null("__MISSING__").to_numpy()
        # События: уникальные (канал, дата события) среди положительных строк.
        mask = (self.y == 1) & (self.event > -(10 ** 9))
        pairs = np.unique(np.stack([self.channel[mask], self.event[mask]], axis=1), axis=0) if mask.any() \
            else np.zeros((0, 2), dtype=np.int64)
        self.ev_channel = pairs[:, 0]
        self.ev_date = pairs[:, 1]
        self.ev_week = np.clip((self.ev_date - origin) // 7, 0, self.n_weeks - 1)

    def subset_rows(self, mask: np.ndarray) -> np.ndarray:
        return mask


def episodes(ev: EvalFrame, p: np.ndarray, threshold: float | None, budget: int,
             cooldown_hours: int, row_mask: np.ndarray | None = None) -> dict[str, Any]:
    """One-to-one эпизодная оценка (эквивалент episode_metrics исходного runtime).

    threshold=None -> только бюджет (без порога), используется при подборе m на H1.
    row_mask ограничивает строки (например, common cohort); события берутся из тех же строк.
    """
    n = len(p)
    rows = np.arange(n)
    allowed = np.isfinite(p)
    if threshold is not None:
        allowed &= p >= threshold
    if row_mask is not None:
        allowed &= row_mask
    cand = rows[allowed]
    # Сортировка: день ↑, вероятность ↓, ключ канала ↑; затем top-budget в каждом дне.
    order = np.lexsort((ev.channel[cand], -p[cand], ev.cutoff[cand]))
    cand = cand[order]
    day = ev.cutoff[cand]
    if len(cand):
        new_day = np.r_[True, day[1:] != day[:-1]]
        group_start = np.maximum.accumulate(np.where(new_day, np.arange(len(cand)), 0))
        rank = np.arange(len(cand)) - group_start
        cand = cand[rank < budget]
    # Cooldown по времени тревоги (cutoff + 1 сутки); порядок: время, ключ.
    alert_time_h = (ev.cutoff[cand] + 1) * 24
    order = np.lexsort((ev.channel[cand], alert_time_h))
    cand, alert_time_h = cand[order], alert_time_h[order]
    kept = []
    last: dict[int, int] = {}
    for idx, t in zip(cand.tolist(), alert_time_h.tolist()):
        ch = int(ev.channel[idx])
        prev = last.get(ch)
        if prev is None or t - prev >= cooldown_hours:
            kept.append(idx)
            last[ch] = t
    alerts = np.array(kept, dtype=np.int64)
    # События в пределах тех же строк.
    if row_mask is None:
        ev_ch, ev_dt, ev_wk = ev.ev_channel, ev.ev_date, ev.ev_week
    else:
        m = row_mask & (ev.y == 1) & (ev.event > -(10 ** 9))
        pairs = np.unique(np.stack([ev.channel[m], ev.event[m]], axis=1), axis=0) if m.any() \
            else np.zeros((0, 2), dtype=np.int64)
        ev_ch, ev_dt = pairs[:, 0], pairs[:, 1]
        ev_wk = np.clip((ev_dt - ev.origin) // 7, 0, ev.n_weeks - 1)
    by_channel: dict[int, list[int]] = {}
    for i in np.lexsort((ev_dt, ev_ch)).tolist():
        by_channel.setdefault(int(ev_ch[i]), []).append(i)
    matched_event = np.zeros(len(ev_ch), dtype=bool)
    alert_hit = np.zeros(len(alerts), dtype=bool)
    order = np.argsort((ev.cutoff[alerts] + 1), kind="mergesort")
    for position in order.tolist():
        idx = int(alerts[position])
        for event_index in by_channel.get(int(ev.channel[idx]), ()):
            if matched_event[event_index]:
                continue
            when = ev_dt[event_index]
            if ev.start[idx] <= when < ev.end[idx]:
                matched_event[event_index] = True
                alert_hit[position] = True
                break
    n_alerts, n_events = len(alerts), len(ev_ch)
    return {
        "alert_budget_per_day": budget,
        "cooldown_hours": cooldown_hours,
        "threshold_applied": threshold is not None,
        "alert_episodes": int(n_alerts),
        "proxy_events": int(n_events),
        "matched_alerts": int(alert_hit.sum()),
        "precision": float(alert_hit.sum() / max(n_alerts, 1)),
        "recall": float(matched_event.sum() / max(n_events, 1)),
        # служебное, в JSON не выводится
        "_alert_week": ev.week[alerts] if n_alerts else np.zeros(0, dtype=np.int64),
        "_alert_hit": alert_hit,
        "_alert_channel": ev.channel[alerts] if n_alerts else np.zeros(0, dtype=np.int64),
        "_event_week": ev_wk,
        "_event_hit": matched_event,
        "_event_channel": ev_ch,
    }


def public(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if not k.startswith("_")}


class APPrep:
    """Предсортировка для быстрого взвешенного PR-AUC (совпадает с sklearn AP)."""

    def __init__(self, y: np.ndarray, p: np.ndarray):
        self.order = np.argsort(-p, kind="mergesort")
        sorted_p = p[self.order]
        self.y = y[self.order].astype(float)
        self.ends = np.r_[np.flatnonzero(np.diff(sorted_p) != 0), len(sorted_p) - 1]

    def ap(self, weights: np.ndarray) -> float:
        w = weights[self.order]
        tp = np.cumsum(w * self.y)[self.ends]
        fp = np.cumsum(w * (1 - self.y))[self.ends]
        total = tp[-1]
        if total <= 0:
            return float("nan")
        precision = np.where(tp + fp > 0, tp / np.maximum(tp + fp, 1e-12), 0.0)
        recall = tp / total
        return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def topk_daily(ev: EvalFrame, p: np.ndarray, k: int, mask: np.ndarray) -> tuple[int, int, int]:
    rows = np.flatnonzero(mask)
    if not len(rows):
        return 0, 0, 0
    order = np.lexsort((ev.channel[rows], -p[rows], ev.cutoff[rows]))
    rows = rows[order]
    day = ev.cutoff[rows]
    new_day = np.r_[True, day[1:] != day[:-1]]
    group_start = np.maximum.accumulate(np.where(new_day, np.arange(len(rows)), 0))
    top = rows[(np.arange(len(rows)) - group_start) < k]
    return int(ev.y[top].sum()), int(len(top)), int(ev.y[rows].sum())


def monthly_metrics(ev: EvalFrame, p: np.ndarray, min_pos: int) -> list[dict[str, Any]]:
    from sklearn.metrics import average_precision_score

    output = []
    for month in sorted(set(ev.month.tolist())):
        mask = ev.month == month
        y = ev.y[mask]
        hits, alerts, positives = topk_daily(ev, p, 50, mask)
        output.append({
            "month": month,
            "rows": int(mask.sum()),
            "positives": int(y.sum()),
            "prevalence": float(y.mean()),
            "pr_auc": float(average_precision_score(y, p[mask])) if y.sum() >= min_pos and y.sum() < len(y) else None,
            "precision_at_50_per_day": hits / max(alerts, 1),
            "recall_at_50_per_day": hits / max(positives, 1),
        })
    return output


def sensor_metrics(ev: EvalFrame, p: np.ndarray, min_pos: int) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score

    output = {}
    for sensor in sorted(set(ev.sensor.tolist())):
        mask = ev.sensor == sensor
        y = ev.y[mask]
        output[str(sensor)] = {
            "rows": int(mask.sum()),
            "positives": int(y.sum()),
            "prevalence": float(y.mean()),
            "pr_auc": float(average_precision_score(y, p[mask])) if y.sum() >= min_pos and y.sum() < len(y) else None,
        }
    return output


# ---------------------------------------------------------------------------
# 5. Оценка модели на фолде
# ---------------------------------------------------------------------------
def evaluate_scores(name: str, ev: EvalFrame, p_val: np.ndarray, threshold: float,
                    b0: float, config: dict[str, Any], full: bool = True) -> dict[str, Any]:
    result = {"model": name, "point": point_metrics(ev.y, p_val, threshold, b0)}
    grid = {}
    raw_primary = None
    for budget in config["budgets"]:
        for cooldown in config["cooldowns"]:
            if not full and not (budget == 50 and cooldown == 72):
                continue
            item = episodes(ev, p_val, threshold, budget, cooldown)
            if budget == 50 and cooldown == 72:
                raw_primary = item
            grid[f"budget_{budget}_cooldown_{cooldown}h"] = public(item)
    result["episodes"] = grid
    result["_primary"] = raw_primary
    result["episodes_budget_only_50_72h"] = public(episodes(ev, p_val, None, 50, 72))
    if full:
        result["monthly"] = monthly_metrics(ev, p_val, config["min_positives_for_pr_auc"])
        result["by_sensor_type"] = sensor_metrics(ev, p_val, config["min_positives_for_pr_auc"])
    return result


def calibrate_and_threshold(raw_cal: np.ndarray, y_cal: np.ndarray, config: dict[str, Any],
                            calibrate: bool = True) -> tuple[Any, float]:
    calibrator = fit_platt(raw_cal, y_cal) if calibrate else None
    p_cal = apply_platt(calibrator, raw_cal) if calibrate else raw_cal
    threshold = select_threshold(y_cal, p_cal, config["minimum_precision"])
    return calibrator, threshold


# ---------------------------------------------------------------------------
# 6. Бутстрэп блоками календарных недель
# ---------------------------------------------------------------------------
class Bootstrap:
    """Одинаковые блоки недель для всех моделей: парные сравнения."""

    def __init__(self, week_counts: dict[str, int], reps: int, seed: int):
        rng = np.random.default_rng(seed)
        self.reps = reps
        self.draws: dict[str, np.ndarray] = {}
        for fold in sorted(week_counts):
            n = week_counts[fold]
            self.draws[fold] = np.stack([
                np.bincount(rng.integers(0, n, size=n), minlength=n).astype(float) for _ in range(reps)
            ])

    def pr_auc(self, fold: str, ev: EvalFrame, prep: APPrep, mask: np.ndarray | None = None) -> np.ndarray:
        out = np.empty(self.reps)
        base_mask = np.ones(len(ev.y)) if mask is None else mask.astype(float)
        for r in range(self.reps):
            out[r] = prep.ap(self.draws[fold][r][ev.week] * base_mask)
        return out

    def episode(self, fold: str, item: dict[str, Any], channel_mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        aw, ah, ec = item["_alert_week"], item["_alert_hit"].astype(float), item["_event_channel"]
        ew, eh = item["_event_week"], item["_event_hit"].astype(float)
        a_keep = np.ones(len(aw)) if channel_mask is None else channel_mask[item["_alert_channel"]].astype(float)
        e_keep = np.ones(len(ew)) if channel_mask is None else channel_mask[ec].astype(float)
        draws = self.draws[fold]
        wa = draws[:, aw] * a_keep if len(aw) else np.zeros((self.reps, 0))
        we = draws[:, ew] * e_keep if len(ew) else np.zeros((self.reps, 0))
        precision = (wa * ah).sum(1) / np.maximum(wa.sum(1), 1e-12)
        recall = (we * eh).sum(1) / np.maximum(we.sum(1), 1e-12)
        return precision, recall


def ci(values: np.ndarray) -> dict[str, Any]:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"mean_difference": None, "ci95_low": None, "ci95_high": None, "reps_finite": 0}
    return {
        "mean_difference": float(finite.mean()),
        "ci95_low": float(np.percentile(finite, 2.5)),
        "ci95_high": float(np.percentile(finite, 97.5)),
        "reps_finite": int(len(finite)),
    }


# ===========================================================================
# Оркестрация
# ===========================================================================



import gc
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np


def _frame_between(frame: Any, start: date, end: date) -> Any:
    import polars as pl

    return frame.filter(
        (pl.col("d_target_start_date") >= pl.lit(start))
        & (pl.col("d_target_end_date_exclusive") <= pl.lit(end))
        & (pl.col("d_year") != STRESS_YEAR)
    )


def _eligible_mask(frame: Any, k: int) -> np.ndarray:
    days = frame["d_days_since_failure_state_event"].to_numpy().astype(float)
    if k <= 0:
        return np.ones(len(days), dtype=bool)
    return ~np.isfinite(days) | (days >= k)


def _eligible_filter(frame: Any, k: int) -> Any:
    import polars as pl

    if k <= 0:
        return frame
    column = pl.col("d_days_since_failure_state_event").cast(pl.Float64)
    return frame.filter(column.is_null() | column.is_nan() | (column >= k))


def _with_eb(frame: Any, m: int) -> Any:
    import polars as pl

    return frame.with_columns(pl.col(f"d_hist_failure_rate_eb_m{m}").alias("d_hist_failure_rate_eb"))


def _resolve_condition_only(columns: list[str]) -> tuple[list[str], dict[str, str]]:
    resolved, mapping = [], {}
    for name in CONDITION_ONLY_REQUESTED:
        if name in columns:
            resolved.append(name)
            mapping[name] = name
        elif f"{name}_24h" in columns:
            resolved.append(f"{name}_24h")
            mapping[name] = f"{name}_24h"
        else:
            raise ContractError(f"Для condition_only не найден признак {name}")
    return resolved, mapping


def _pr_auc_on(y: np.ndarray, p: np.ndarray, mask: np.ndarray, min_pos: int) -> float | None:
    from sklearn.metrics import average_precision_score

    yy = y[mask]
    if yy.sum() < min_pos or yy.sum() == len(yy):
        return None
    return float(average_precision_score(yy, p[mask]))


def _decide(ci_dict: dict[str, Any], positive_is_good: bool = True) -> tuple[str, str]:
    low, high = ci_dict.get("ci95_low"), ci_dict.get("ci95_high")
    if low is None:
        return "inconclusive", "no_finite_bootstrap"
    if positive_is_good:
        if low > 0:
            return "confirmed", "ci95_above_zero"
        if high < 0:
            return "rejected", "ci95_below_zero"
    return "inconclusive", "ci95_includes_zero"


def _decide_removable(pr: dict[str, Any], rec: dict[str, Any], tol: float = 0.01) -> tuple[str, str]:
    """Гипотеза «признаки можно убрать без потерь»."""
    if pr["ci95_low"] is None or rec["ci95_low"] is None:
        return "inconclusive", "no_finite_bootstrap"
    if pr["ci95_high"] < 0 or rec["ci95_high"] < 0:
        return "rejected", "significant_loss_ci95_below_zero"
    if pr["ci95_low"] > -tol and rec["ci95_low"] > -tol:
        return "confirmed", "loss_bounded_by_0.01_at_ci95"
    return "inconclusive", "ci95_allows_loss_above_0.01"


def run_research(config: dict[str, Any]) -> dict[str, Any]:
    """Точка входа. ReproductionError в любом месте -> диагностический результат."""
    ctx: dict[str, Any] = {"keys": set()}
    try:
        return _run_research(config, ctx)
    except ReproductionError as error:
        result = ctx["result"]
        for key in ("folds", "pooled_mean_over_folds", "paired_bootstrap", "selection", "hypotheses"):
            result.pop(key, None)
        result.update(status="m0_reproduction_failed", stop_reason=str(error))
        return _finish(result, ctx["output_dir"], ctx["timings"], ctx["started"], ctx["keys"])


def _run_research(config: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    import polars as pl

    started = time.perf_counter()
    mode = config["mode"]
    output_dir = Path(os.environ.get("LDT_OUTPUT_DIR", config["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": None,
        "mode": mode,
        "comparability": "non_comparable" if mode == "SMOKE" else "comparable_within_this_run",
        "target": TARGET,
        "target_semantics": "observable proxy: onset of Неисправен/Обесточен on D+2; not a confirmed physical failure",
        "evaluation_scope": "pre-2025 rolling folds (development validation, not a final test)",
        "config": {k: v for k, v in config.items() if k != "output_dir"},
        "environment": environment_info(),
    }
    timings: dict[str, float] = {}
    ctx.update(result=result, output_dir=output_dir, timings=timings, started=started)

    def tick(label: str, since: float) -> float:
        timings[label] = round(time.perf_counter() - since, 1)
        log(f"{label}: {timings[label]} с")
        return time.perf_counter()

    # ---- 1. Контракт и загрузка -------------------------------------------------
    t = time.perf_counter()
    try:
        data_path, manifest, checks = preflight(mode)
    except ContractError as error:
        result.update(status="contract_failed", stop_reason=str(error))
        return _finish(result, output_dir, timings, started, keys=set())
    result["panel"] = {
        "schema_version": manifest.get("panel_schema_version"),
        "data_sha256": manifest.get("data_sha256"),
        "manifest_rows": manifest.get("rows"),
        "contract_checks": checks,
    }
    t = tick("preflight", t)
    try:
        frame = load_pre2025(data_path, mode, int(config["smoke_channel_share"]))
    except ContractError as error:
        result.update(status="contract_failed", stop_reason=str(error))
        return _finish(result, output_dir, timings, started, keys=set())
    keys = set(frame["d_channel_key"].unique().cast(pl.String).to_list()) | set(
        frame["d_object_key"].unique().cast(pl.String).to_list()
    )
    ctx["keys"] = keys
    duplicates = frame.height - frame.select(["d_channel_key", "d_cutoff_date"]).unique().height
    result["panel"]["loaded"] = {
        "rows_labelled_pre2025": frame.height,
        "max_target_end_exclusive": frame["d_target_end_date_exclusive"].max(),
        "rows_with_target_end_after_2025_01_01": 0,
        "duplicate_channel_day_rows": int(duplicates),
        "years": sorted(frame["d_year"].unique().to_list()),
        "note_ru": "Строки 2025 H2 и 2026 в память не загружались; они участвовали только в агрегатных проверках контракта.",
    }
    condition_only, condition_mapping = _resolve_condition_only(frame.columns)
    result["feature_name_resolution"] = {
        "condition_only_requested_to_panel": condition_mapping,
        "note_ru": "В задании у d_value_numeric_mean/min/max/std нет суффикса _24h; в панели эти показатели называются с суффиксом.",
    }
    t = tick("load", t)

    frame = build_propensity(frame, list(config["m_grid"]))
    t = tick("propensity_features", t)

    numeric_m0 = list(NUMERIC_FEATURES)
    categorical_m0 = list(CATEGORICAL_FEATURES)
    variants = {
        "no_recurrence": ([f for f in numeric_m0 if f not in RECURRENCE], categorical_m0),
        "no_calendar": ([f for f in numeric_m0 if f not in CALENDAR], categorical_m0),
        "no_current_catalogue": ([f for f in numeric_m0 if f not in CATALOGUE_NUMERIC], []),
        "condition_only": (condition_only, []),
    }
    for numeric, categorical in variants.values():
        assert_safe_features(numeric + categorical)

    folds_out: dict[str, Any] = {}
    store: dict[str, dict[str, Any]] = {}  # fold -> служебные массивы для бутстрэпа
    stress_predictors: dict[str, Any] = {}
    ratio, seed = int(config["negative_to_positive_ratio"]), int(config["random_seed"])

    for fold in FOLDS:
        name = fold["name"]
        log(f"=== {name} ===")
        train_all = frame.filter(
            pl.col("d_year").is_in(fold["train_years"])
            & (pl.col("d_target_end_date_exclusive") <= pl.lit(fold["train_end"]))
        )
        cal = _frame_between(frame, *fold["calibration"])
        val = _frame_between(frame, *fold["validation"])
        if train_all.is_empty() or cal.is_empty() or val.is_empty():
            result.update(status="contract_failed", stop_reason=f"{name}: пустая выборка train/calibration/validation")
            return _finish(result, output_dir, timings, started, keys)
        y_cal = cal[TARGET].to_numpy().astype(np.int8)
        pre = pl.concat([train_all, cal], how="vertical")
        b0 = float(pre[TARGET].mean())
        ev = EvalFrame(val, fold["validation"][0])
        ev_cal = EvalFrame(cal, fold["calibration"][0])
        val_fp = {"rows": val.height, "cutoff_day_sum": int(ev.cutoff.sum())}
        fold_out: dict[str, Any] = {
            "periods": {
                "train_years": fold["train_years"],
                "train_target_end_exclusive_max": fold["train_end"],
                "calibration": list(fold["calibration"]),
                "validation": list(fold["validation"]),
            },
            "rows": {"train_before_sampling": train_all.height, "calibration": cal.height, "validation": val.height},
            "positives": {
                "train": int(train_all[TARGET].sum()), "calibration": int(y_cal.sum()), "validation": int(ev.y.sum()),
            },
            "b0_prevalence_pre_validation": b0,
            "validation_row_fingerprint": val_fp,
            "models": {},
        }
        preds: dict[str, np.ndarray] = {}
        primaries: dict[str, dict[str, Any]] = {}
        thresholds: dict[str, float] = {}
        importances: dict[str, Any] = {}

        def register(model_name: str, p_val: np.ndarray, threshold: float, full: bool = True) -> None:
            assert len(p_val) == val.height, "валидационные строки должны совпадать"
            evaluation = evaluate_scores(model_name, ev, p_val, threshold, b0, config, full=full)
            primaries[model_name] = evaluation.pop("_primary")
            preds[model_name] = p_val
            thresholds[model_name] = threshold
            evaluation["validation_row_fingerprint"] = val_fp
            fold_out["models"][model_name] = evaluation

        # --- baseline-лестница ---
        p_b0 = np.full(val.height, b0)
        _, thr = calibrate_and_threshold(np.full(cal.height, b0), y_cal, config, calibrate=False)
        register("B0_constant", p_b0, thr)

        type_stats = pre.group_by("тип_датчика").agg(pl.len().alias("n"), pl.col(TARGET).mean().alias("rate"))
        type_rate = {
            row["тип_датчика"]: row["rate"]
            for row in type_stats.iter_rows(named=True)
            if row["n"] >= config["b1_min_type_rows"] and row["тип_датчика"] is not None
        }

        def b1(frame_: Any) -> np.ndarray:
            return np.array([type_rate.get(v, b0) for v in frame_["тип_датчика"].to_list()], dtype=float)

        _, thr = calibrate_and_threshold(b1(cal), y_cal, config, calibrate=False)
        register("B1_type_prevalence", b1(val), thr)

        for model_name, scorer in (("B2_recurrence", recurrence_score), ("B3_rule", rule_score)):
            platt, thr = calibrate_and_threshold(scorer(cal), y_cal, config)
            register(model_name, apply_platt(platt, scorer(val)), thr)

        train_sampled = sample_training(train_all, ratio, seed)
        fold_out["rows"]["train_after_sampling"] = train_sampled.height
        logistic = LogisticModel(numeric_m0, categorical_m0, config).fit(train_sampled)
        platt, thr = calibrate_and_threshold(logistic.raw(cal), y_cal, config)
        register("B4_logistic", apply_platt(platt, logistic.raw(val)), thr)
        del logistic
        t = tick(f"{name}: baselines B0-B4", t)

        # --- M0 ---
        try:
            m0 = LightGBMModel(numeric_m0, categorical_m0, config).fit(train_sampled)
            raw_cal = m0.raw(cal)
            if not np.isfinite(raw_cal).all():
                raise ValueError("M0 выдал нечисловые скоры на calibration")
            platt_m0, thr_m0 = calibrate_and_threshold(raw_cal, y_cal, config)
            p_m0 = apply_platt(platt_m0, m0.raw(val))
        except ReproductionError:
            raise
        except Exception as error:  # любая ошибка обучения/калибровки M0 = стоп
            raise ReproductionError(f"{name}: M0 не воспроизведён: {type(error).__name__}: {error}") from error
        repro = {
            "feature_columns": m0.features,
            "feature_count": len(m0.features),
            "matches_safe_recurrence_21": m0.features == NUMERIC_FEATURES + CATEGORICAL_FEATURES,
            "predictions_finite": bool(np.isfinite(p_m0).all()),
            "calibration_pr_auc": _pr_auc_on(y_cal, apply_platt(platt_m0, raw_cal), np.ones(len(y_cal), bool), 1),
            "calibration_prevalence": float(y_cal.mean()),
            "category_levels_from_train_only": True,
        }
        fold_out["m0_reproduction"] = repro
        if not (repro["matches_safe_recurrence_21"] and repro["predictions_finite"]
                and repro["calibration_pr_auc"] is not None
                and repro["calibration_pr_auc"] > repro["calibration_prevalence"]):
            result["m0_reproduction_diagnostics"] = {name: repro}
            raise ReproductionError(f"{name}: M0 не воспроизведён (см. m0_reproduction_diagnostics)")
        register(M0, p_m0, thr_m0)
        importances[M0] = m0.importance()
        if name == FOLDS[-1]["name"]:
            stress_predictors[M0] = (m0, platt_m0, thr_m0, None)
        else:
            del m0
        t = tick(f"{name}: M0", t)

        # --- ablations ---
        ablation_models: dict[str, Any] = {}
        for variant, (numeric, categorical) in variants.items():
            model = LightGBMModel(numeric, categorical, config).fit(train_sampled)
            platt, thr = calibrate_and_threshold(model.raw(cal), y_cal, config)
            register(variant, apply_platt(platt, model.raw(val)), thr)
            importances[variant] = model.importance()
            if name == FOLDS[-1]["name"]:
                stress_predictors[variant] = (model, platt, thr, None)
            ablation_models[variant] = model
        del ablation_models
        t = tick(f"{name}: ablations", t)

        # --- clean-history sensitivity ---
        clean: dict[str, Any] = {"native": {}, "common_k30": {}}
        common_mask = _eligible_mask(val, 30)
        clean_preds: dict[int, np.ndarray] = {}
        for k in config["clean_history_days"]:
            if k == 0:
                p_k, thr_k = p_m0, thr_m0
            else:
                train_k = sample_training(_eligible_filter(train_all, k), ratio, seed)
                cal_k = _eligible_filter(cal, k)
                model = LightGBMModel(numeric_m0, categorical_m0, config).fit(train_k)
                platt, thr_k = calibrate_and_threshold(model.raw(cal_k), cal_k[TARGET].to_numpy().astype(np.int8), config)
                p_k = apply_platt(platt, model.raw(val))
                del model, train_k
            clean_preds[k] = p_k
            for cohort, mask in (("native", _eligible_mask(val, k)), ("common_k30", common_mask)):
                y_sub = ev.y[mask]
                item = episodes(ev, p_k, thr_k, 50, 72, row_mask=mask)
                clean[cohort][f"k_{k}"] = {
                    "rows": int(mask.sum()),
                    "positives": int(y_sub.sum()),
                    "prevalence": float(y_sub.mean()) if mask.any() else None,
                    "pr_auc": _pr_auc_on(ev.y, p_k, mask, 1),
                    "episodes_budget_50_cooldown_72h": public(item),
                    "_item": item,
                }
        fold_out["clean_history"] = {
            cohort: {k: {kk: vv for kk, vv in v.items() if kk != "_item"} for k, v in tables.items()}
            for cohort, tables in clean.items()
        }
        t = tick(f"{name}: clean-history", t)

        # --- propensity ---
        propensity: dict[str, Any] = {"m_selection_on_calibration_h1": {}}
        # H1 делится по времени: первая половина — подбор m, вторая — Platt и порог
        # (та же схема, что в 08/09: одна выборка не используется дважды).
        h1_start, h1_end = fold["calibration"]
        h1_mid = h1_start + (h1_end - h1_start) / 2
        cal_sel = cal.filter(pl.col("d_cutoff_date") < pl.lit(h1_mid))
        cal_fit = cal.filter(pl.col("d_cutoff_date") >= pl.lit(h1_mid))
        ev_cal_sel = EvalFrame(cal_sel, h1_start)
        y_cal_sel = cal_sel[TARGET].to_numpy().astype(np.int8)
        y_cal_fit = cal_fit[TARGET].to_numpy().astype(np.int8)
        propensity["h1_split"] = {"selection_rows": cal_sel.height, "calibration_rows": cal_fit.height,
                                  "split_date": h1_mid}
        prop_variants = {
            "propensity_only": None,
            "baseline_plus_propensity": (numeric_m0 + HIST_FEATURES, categorical_m0),
            "no_recurrence_plus_propensity": (variants["no_recurrence"][0] + HIST_FEATURES, categorical_m0),
        }
        for variant, spec in prop_variants.items():
            candidates = []
            fitted: dict[int, Any] = {}
            for m in config["m_grid"]:
                cal_m = _with_eb(cal_sel, m)
                if spec is None:
                    raw_c = cal_m["d_hist_failure_rate_eb"].fill_null(b0).fill_nan(b0).to_numpy().astype(float)
                    fitted[m] = None
                else:
                    model = LightGBMModel(spec[0], spec[1], config).fit(
                        sample_training(_with_eb(train_all, m), ratio, seed))
                    raw_c = model.raw(cal_m)
                    fitted[m] = model
                item = episodes(ev_cal_sel, raw_c, None, 50, 72)
                candidates.append({
                    "m": m,
                    "calibration_episode_recall_budget_only": item["recall"],
                    "calibration_episode_precision_budget_only": item["precision"],
                    "calibration_pr_auc": _pr_auc_on(y_cal_sel, raw_c, np.ones(len(y_cal_sel), bool), 1) or 0.0,
                })
            best_recall = max(c["calibration_episode_recall_budget_only"] for c in candidates)
            close = [c for c in candidates if best_recall - c["calibration_episode_recall_budget_only"] < 0.01]
            chosen = sorted(close, key=lambda c: (
                -c["calibration_episode_precision_budget_only"], -c["calibration_pr_auc"], -c["m"]))[0]
            m = chosen["m"]
            propensity["m_selection_on_calibration_h1"][variant] = {
                "chosen_m": m,
                "grid": [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates],
                "rule": "max episode recall (budget 50/day, cooldown 72h, без порога) на первой половине H1; "
                        "при разнице <0.01 — выше episode precision, затем PR-AUC, затем больший m",
            }
            fit_m = _with_eb(cal_fit, m)
            raw_fit = (fit_m["d_hist_failure_rate_eb"].fill_null(b0).fill_nan(b0).to_numpy().astype(float)
                       if spec is None else fitted[m].raw(fit_m))
            platt, thr = calibrate_and_threshold(raw_fit, y_cal_fit, config)
            val_m = _with_eb(val, m)
            if spec is None:
                raw_v = val_m["d_hist_failure_rate_eb"].fill_null(b0).fill_nan(b0).to_numpy().astype(float)
            else:
                raw_v = fitted[m].raw(val_m)
                importances[variant] = fitted[m].importance()
            register(variant, apply_platt(platt, raw_v), thr)
            if name == FOLDS[-1]["name"]:
                stress_predictors[variant] = (fitted[m], platt, thr, m)
            del fitted
            gc.collect()
        fold_out["propensity"] = propensity
        t = tick(f"{name}: propensity", t)

        # --- support и generalization ---
        seen_channels = set(pre["d_channel_key"].unique().to_list())
        seen_objects = set(pre["d_object_key"].unique().to_list())
        support = pre.group_by("тип_датчика").agg(pl.len().alias("n"), pl.col(TARGET).sum().alias("p"))
        supported_types = {
            row["тип_датчика"] for row in support.iter_rows(named=True)
            if row["n"] >= config["support_min_rows"] and row["p"] >= config["support_min_positives"]
        }
        val_channels = val["d_channel_key"].to_numpy()
        seen_row = np.array([c in seen_channels for c in val_channels.tolist()])
        seen_obj_row = np.array([o in seen_objects for o in val["d_object_key"].to_list()])
        supported_row = np.array([s in supported_types for s in val["тип_датчика"].to_list()])
        unique_keys = np.unique(val_channels.astype(str))
        groups = {
            "seen_channel": seen_row, "unseen_channel": ~seen_row,
            "seen_object": seen_obj_row, "unseen_object": ~seen_obj_row,
            "supported_type": supported_row, "unsupported_type": ~supported_row,
        }
        coverage = {
            "validation_rows": val.height,
            "validation_positive_rows": int(ev.y.sum()),
            "validation_dates_covered": int(np.unique(ev.cutoff).size),
            "validation_date_min": str(val["d_cutoff_date"].min()),
            "validation_date_max": str(val["d_cutoff_date"].max()),
            "validation_channels_observed": int(len(unique_keys)),
            "validation_objects_observed": int(val["d_object_key"].n_unique()),
            "supported_type_rule": f">= {config['support_min_rows']} labelled rows and >= {config['support_min_positives']} positives in train+calibration",
            "supported_types": sorted(str(s) for s in supported_types),
            "groups": {},
        }
        for group, mask in groups.items():
            coverage["groups"][group] = {
                "rows": int(mask.sum()),
                "row_share": float(mask.mean()),
                "positives": int(ev.y[mask].sum()),
                "channels": int(np.unique(val_channels[mask]).size) if mask.any() else 0,
                "objects": int(val.filter(pl.Series(mask))["d_object_key"].n_unique()) if mask.any() else 0,
            }
        fold_out["coverage"] = coverage
        code_masks = {}
        for group, mask in groups.items():
            code_mask = np.zeros(ev.n_channels, dtype=bool)
            code_mask[ev.channel[mask]] = True
            code_masks[group] = code_mask
        subset_metrics: dict[str, Any] = {}
        for model_name, p in preds.items():
            entry = {}
            for group, mask in groups.items():
                item = episodes(ev, p, thresholds[model_name], 50, 72, row_mask=mask)
                entry[group] = {
                    "rows": int(mask.sum()),
                    "positives": int(ev.y[mask].sum()),
                    "pr_auc": _pr_auc_on(ev.y, p, mask, config["min_positives_for_pr_auc"]),
                    "episode_precision_50_72h": item["precision"],
                    "episode_recall_50_72h": item["recall"],
                    "proxy_events": item["proxy_events"],
                }
            subset_metrics[model_name] = entry
        fold_out["support_generalization"] = subset_metrics
        fold_out["feature_importance_gain_share"] = {
            "interpretation_ru": "Доля gain — только predictive association, не причинность.",
            "models": importances,
        }
        folds_out[name] = fold_out
        store[name] = {
            "ev": ev, "preds": preds, "primaries": primaries, "groups": groups,
            "code_masks": code_masks, "clean": clean, "clean_preds": clean_preds, "common_mask": common_mask,
        }
        del train_all, cal, val, pre, train_sampled
        gc.collect()
        t = tick(f"{name}: support", t)

    result["folds"] = folds_out

    # ---- пулированные таблицы по фолдам ------------------------------------------
    model_names = list(folds_out[FOLDS[0]["name"]]["models"])
    pooled = {}
    for model_name in model_names:
        per = [folds_out[f["name"]]["models"][model_name] for f in FOLDS]
        prim = [p["episodes"]["budget_50_cooldown_72h"] for p in per]
        pooled[model_name] = {
            "mean_pr_auc": float(np.mean([p["point"]["pr_auc"] or np.nan for p in per])),
            "mean_lift_over_b0": float(np.mean([p["point"]["lift_over_b0"] or np.nan for p in per])),
            "mean_brier": float(np.mean([p["point"]["brier_score"] for p in per])),
            "mean_ece": float(np.mean([p["point"]["ece_10_bins"] for p in per])),
            "mean_false_alerts_per_1000": float(np.mean([p["point"]["false_alerts_per_1000_eligible_channel_days"] for p in per])),
            "mean_episode_recall_50_72h": float(np.mean([p["recall"] for p in prim])),
            "mean_episode_precision_50_72h": float(np.mean([p["precision"] for p in prim])),
        }
    result["pooled_mean_over_folds"] = pooled

    # ---- бутстрэп ---------------------------------------------------------------------
    t = time.perf_counter()
    boot = Bootstrap({f: store[f]["ev"].n_weeks for f in store}, int(config["bootstrap_reps"]), int(config["bootstrap_seed"]))
    preps: dict[tuple[str, str], APPrep] = {}

    def prep(fold: str, model_name: str) -> APPrep:
        if (fold, model_name) not in preps:
            preps[(fold, model_name)] = APPrep(store[fold]["ev"].y, store[fold]["preds"][model_name])
        return preps[(fold, model_name)]

    def paired(candidate: str, reference: str, row_group: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"candidate": candidate, "reference": reference, "difference": "candidate - reference"}
        diffs = {"pr_auc": [], "episode_recall_50_72h": [], "episode_precision_50_72h": []}
        for fold in store:
            s = store[fold]
            mask = None if row_group is None else s["groups"][row_group]
            a = boot.pr_auc(fold, s["ev"], prep(fold, candidate), mask)
            b = boot.pr_auc(fold, s["ev"], prep(fold, reference), mask)
            cmask = None if row_group is None else s["code_masks"][row_group]
            pa, ra = boot.episode(fold, s["primaries"][candidate], cmask)
            pb, rb = boot.episode(fold, s["primaries"][reference], cmask)
            per = {"pr_auc": a - b, "episode_recall_50_72h": ra - rb, "episode_precision_50_72h": pa - pb}
            out[fold] = {k: ci(v) for k, v in per.items()}
            for k, v in per.items():
                diffs[k].append(v)
        out["mean_over_folds"] = {k: ci(np.mean(np.stack(v), axis=0)) for k, v in diffs.items()}
        return out

    def paired_masked(fold_preds: dict[str, tuple[np.ndarray, np.ndarray]], mask_key: str) -> dict[str, Any]:
        """PR-AUC разница на подвыборке строк (common cohort)."""
        out: dict[str, Any] = {}
        per_fold = []
        for fold in store:
            s = store[fold]
            mask = s[mask_key]
            pa, pb = fold_preds[fold]
            a = boot.pr_auc(fold, s["ev"], APPrep(s["ev"].y, pa), mask)
            b = boot.pr_auc(fold, s["ev"], APPrep(s["ev"].y, pb), mask)
            out[fold] = ci(a - b)
            per_fold.append(a - b)
        out["mean_over_folds"] = ci(np.mean(np.stack(per_fold), axis=0))
        return out

    comparisons: dict[str, Any] = {}
    for baseline in ("B2_recurrence", "B3_rule", "B4_logistic"):
        comparisons[f"{baseline}_vs_M0"] = paired(baseline, M0)
    candidates = list(variants) + ["propensity_only", "baseline_plus_propensity", "no_recurrence_plus_propensity"]
    for candidate in candidates:
        comparisons[f"{candidate}_vs_M0"] = paired(candidate, M0)
    strongest = max(("B2_recurrence", "B3_rule", "B4_logistic"), key=lambda b: pooled[b]["mean_pr_auc"])
    for candidate in candidates + [M0]:
        comparisons[f"{candidate}_vs_strongest_baseline"] = paired(candidate, strongest)
    comparisons["condition_only_vs_B2_recurrence"] = paired("condition_only", "B2_recurrence")
    comparisons["no_recurrence_plus_propensity_vs_no_recurrence"] = paired("no_recurrence_plus_propensity", "no_recurrence")
    comparisons["M0_vs_B1_on_unseen_channels"] = paired(M0, "B1_type_prevalence", row_group="unseen_channel")
    comparisons["M0_vs_B1_on_unsupported_types"] = paired(M0, "B1_type_prevalence", row_group="unsupported_type")
    comparisons["clean_history_k30_vs_k0_on_common_cohort"] = paired_masked(
        {f: (store[f]["clean_preds"][30], store[f]["clean_preds"][0]) for f in store}, "common_mask")
    comparisons["M0_vs_B2_on_common_cohort_k30"] = paired_masked(
        {f: (store[f]["preds"][M0], store[f]["preds"]["B2_recurrence"]) for f in store}, "common_mask")
    result["paired_bootstrap"] = {
        "method": "парный бутстрэп блоками календарных недель validation-периода; одинаковые блоки для всех моделей",
        "reps": int(config["bootstrap_reps"]),
        "seed": int(config["bootstrap_seed"]),
        "strongest_baseline_by_mean_pr_auc": strongest,
        "comparisons": comparisons,
    }
    t = tick("bootstrap", t)

    # ---- gates и выбор ------------------------------------------------------------
    min_pos = config["min_positives_for_pr_auc"]

    def mean_subset(model_name: str, group: str, key: str) -> float | None:
        values = [folds_out[f]["support_generalization"][model_name][group][key] for f in folds_out]
        values = [v for v in values if v is not None]
        return float(np.mean(values)) if values else None

    def subset_events(group: str) -> int:
        return int(sum(folds_out[f]["support_generalization"][M0][group]["proxy_events"] for f in folds_out))

    selection: dict[str, Any] = {"primary_metric": "mean over folds of episode recall at 50 alerts/day, cooldown 72h",
                                 "candidates": {}}
    m0_pool = pooled[M0]
    for candidate in candidates:
        c_pool = pooled[candidate]
        comp = comparisons[f"{candidate}_vs_M0"]["mean_over_folds"]
        vs_base = comparisons[f"{candidate}_vs_strongest_baseline"]["mean_over_folds"]["pr_auc"]
        gates: dict[str, Any] = {}
        rec_ci = comp["episode_recall_50_72h"]
        gates["g1_recall_ci_excludes_zero"] = bool(rec_ci["ci95_low"] is not None and rec_ci["ci95_low"] > 0)
        gates["g2_episode_precision_not_below_m0_by_0.01"] = (
            c_pool["mean_episode_precision_50_72h"] >= m0_pool["mean_episode_precision_50_72h"] - 0.01)
        fa_limit = max(1.0, 0.05 * m0_pool["mean_false_alerts_per_1000"])
        gates["g3_false_alerts_within_limit"] = (
            c_pool["mean_false_alerts_per_1000"] <= m0_pool["mean_false_alerts_per_1000"] + fa_limit)
        unseen_pr_c, unseen_pr_m = mean_subset(candidate, "unseen_channel", "pr_auc"), mean_subset(M0, "unseen_channel", "pr_auc")
        unseen_rec_c = mean_subset(candidate, "unseen_channel", "episode_recall_50_72h")
        unseen_rec_m = mean_subset(M0, "unseen_channel", "episode_recall_50_72h")
        if subset_events("unseen_channel") < min_pos or unseen_pr_c is None or unseen_pr_m is None:
            gates["g4_unseen_not_worse_by_0.01"] = "insufficient_support"
        else:
            gates["g4_unseen_not_worse_by_0.01"] = bool(
                unseen_pr_c >= unseen_pr_m - 0.01 and unseen_rec_c >= unseen_rec_m - 0.01)
        g5 = []
        for seen_g, unseen_g in (("seen_channel", "unseen_channel"), ("supported_type", "unsupported_type")):
            if subset_events(unseen_g) < min_pos:
                g5.append("insufficient_support")
                continue
            d_seen = mean_subset(candidate, seen_g, "episode_recall_50_72h") - mean_subset(M0, seen_g, "episode_recall_50_72h")
            d_unseen = mean_subset(candidate, unseen_g, "episode_recall_50_72h") - mean_subset(M0, unseen_g, "episode_recall_50_72h")
            g5.append(not (d_seen > 0 and d_unseen <= 0))
        gates["g5_improvement_not_only_seen_or_supported"] = (
            "insufficient_support" if all(v == "insufficient_support" for v in g5)
            else all(v is True or v == "insufficient_support" for v in g5))
        gates["g6_beats_strongest_baseline_pr_auc"] = bool(vs_base["ci95_low"] is not None and vs_base["ci95_low"] > 0)
        passed = all(v is True or v == "insufficient_support" for v in gates.values())
        failed = [k for k, v in gates.items() if v is False]
        selection["candidates"][candidate] = {
            "mean_episode_recall_50_72h": c_pool["mean_episode_recall_50_72h"],
            "mean_episode_precision_50_72h": c_pool["mean_episode_precision_50_72h"],
            "mean_pr_auc": c_pool["mean_pr_auc"],
            "gates": gates, "passed": passed, "failed_gates": failed,
        }
    passed = [c for c, v in selection["candidates"].items() if v["passed"]]
    if passed:
        best = max(pooled[c]["mean_episode_recall_50_72h"] for c in passed)
        close = [c for c in passed if best - pooled[c]["mean_episode_recall_50_72h"] < 0.01]
        simplicity = {c: i for i, c in enumerate(["condition_only", "no_current_catalogue", "no_calendar",
                                                   "no_recurrence", "propensity_only",
                                                   "no_recurrence_plus_propensity", "baseline_plus_propensity"])}
        chosen = sorted(close, key=lambda c: (-pooled[c]["mean_episode_precision_50_72h"],
                                              -pooled[c]["mean_pr_auc"], simplicity.get(c, 99)))[0]
        selection.update(selected=chosen, reason="passed_all_gates_max_episode_recall")
    else:
        selection.update(selected=M0, reason="no_candidate_passed_gates_keep_m0_without_improvement_claim")
    result["selection"] = selection

    # ---- stress 2021 (однократно, после выбора) -------------------------------------
    t = time.perf_counter()
    stress = frame.filter((pl.col("d_year") == STRESS_YEAR)
                          & (pl.col("d_target_end_date_exclusive") <= pl.lit(date(2022, 1, 1))))
    stress_out: dict[str, Any] = {"used_once_after_selection": True, "models_from": FOLDS[-1]["name"]}
    if stress.is_empty():
        stress_out["status"] = "no_rows"
    else:
        ev_s = EvalFrame(stress, date(2021, 1, 1))
        b0_last = folds_out[FOLDS[-1]["name"]]["b0_prevalence_pre_validation"]
        for model_name in dict.fromkeys([M0, selection["selected"]]):
            model, platt, thr, m = stress_predictors[model_name]
            source = _with_eb(stress, m) if m is not None else stress
            if model is None:
                raw = source["d_hist_failure_rate_eb"].fill_null(b0_last).fill_nan(b0_last).to_numpy().astype(float)
            else:
                raw = model.raw(source)
            ev_eval = evaluate_scores(model_name, ev_s, apply_platt(platt, raw), thr, b0_last, config, full=False)
            ev_eval.pop("_primary")
            stress_out[model_name] = ev_eval
        stress_out["B2_recurrence_pr_auc"] = _pr_auc_on(ev_s.y, recurrence_score(stress), np.ones(len(ev_s.y), bool), 1)
        stress_out["prevalence"] = float(ev_s.y.mean())
        stress_out["rows"] = int(len(ev_s.y))
    result["stress_2021"] = stress_out
    t = tick("stress_2021", t)

    # ---- гипотезы -----------------------------------------------------------------
    hyp: dict[str, Any] = {}
    c = comparisons
    status, reason = _decide(c[f"{M0}_vs_strongest_baseline"]["mean_over_folds"]["pr_auc"])
    hyp["H1_m0_beats_strongest_baseline_pr_auc"] = {"decision": status, "reason": reason, "baseline": strongest}
    for variant, key in (("no_recurrence", "H2_recurrence_removable_without_loss"),
                         ("no_calendar", "H3_calendar_removable_without_loss"),
                         ("no_current_catalogue", "H4_current_catalogue_removable_without_loss")):
        mo = c[f"{variant}_vs_M0"]["mean_over_folds"]
        status, reason = _decide_removable(mo["pr_auc"], mo["episode_recall_50_72h"])
        hyp[key] = {"decision": status, "reason": reason}
    status, reason = _decide(c["condition_only_vs_B2_recurrence"]["mean_over_folds"]["pr_auc"])
    hyp["H5_condition_features_beat_recurrence_score"] = {"decision": status, "reason": reason}
    status, reason = _decide(c["M0_vs_B2_on_common_cohort_k30"]["mean_over_folds"])
    hyp["H6_m0_beats_recurrence_score_on_clean_history_cohort"] = {"decision": status, "reason": reason}
    status, reason = _decide(c["clean_history_k30_vs_k0_on_common_cohort"]["mean_over_folds"])
    hyp["H7_clean_history_training_improves_common_cohort"] = {
        "decision": status, "reason": reason,
        "note": "sensitivity-анализ eligibility, не утверждение новой цели"}
    for key, comp, group in (("H8_m0_generalizes_to_unseen_channels", "M0_vs_B1_on_unseen_channels", "unseen_channel"),
                             ("H9_m0_generalizes_to_unsupported_types", "M0_vs_B1_on_unsupported_types", "unsupported_type")):
        if subset_events(group) < min_pos:
            hyp[key] = {"decision": "inconclusive", "reason": "insufficient_support_lt_min_positives"}
        else:
            status, reason = _decide(c[comp]["mean_over_folds"]["pr_auc"])
            hyp[key] = {"decision": status, "reason": reason, "reference": "B1_type_prevalence"}
    prop = selection["candidates"]["baseline_plus_propensity"]
    no_rec = c["no_recurrence_plus_propensity_vs_no_recurrence"]["mean_over_folds"]["pr_auc"]
    rec_ci = c["baseline_plus_propensity_vs_M0"]["mean_over_folds"]["episode_recall_50_72h"]
    unseen_gate = prop["gates"]["g4_unseen_not_worse_by_0.01"]
    if prop["passed"] and no_rec["ci95_low"] is not None and no_rec["ci95_low"] > 0 and unseen_gate is not False:
        hyp["H10_channel_propensity_improves_m0"] = {"decision": "confirmed", "reason": "passed_gates_and_survives_without_recurrence"}
    elif (rec_ci["ci95_high"] is not None and rec_ci["ci95_high"] <= 0) or \
            (no_rec["ci95_high"] is not None and no_rec["ci95_high"] <= 0) or unseen_gate is False:
        why = ("episode_recall_ci95_not_above_zero" if rec_ci["ci95_high"] is not None and rec_ci["ci95_high"] <= 0
               else "improvement_vanishes_without_recurrence" if no_rec["ci95_high"] is not None and no_rec["ci95_high"] <= 0
               else "worse_on_unseen_channels")
        hyp["H10_channel_propensity_improves_m0"] = {"decision": "rejected", "reason": why}
    else:
        hyp["H10_channel_propensity_improves_m0"] = {
            "decision": "inconclusive", "reason": "failed_gates:" + ",".join(prop["failed_gates"]) if prop["failed_gates"] else "ci95_includes_zero"}
    hyp["H10_channel_propensity_improves_m0"]["label"] = "identity-like historical feature, not physical/causal"
    result["hypotheses"] = hyp
    result["status"] = "completed" if mode == "FULL" else "completed_smoke_non_comparable"
    return _finish(result, output_dir, timings, started, keys)


# ---------------------------------------------------------------------------
# Запись результатов
# ---------------------------------------------------------------------------
def _finish(result: dict[str, Any], output_dir: Path, timings: dict[str, float],
            started: float, keys: set[str]) -> dict[str, Any]:
    result["runtime"] = {"seconds_total": round(time.perf_counter() - started, 1), "steps_seconds": timings}
    result = _clean(result)
    text = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    long_keys = {k for k in keys if len(k) >= 8}
    tokens = set(re.findall(r"[A-Za-z0-9_\-]+", text))
    leaked = long_keys & tokens
    if leaked:
        raise RuntimeError(f"В результатах обнаружены идентификаторы ({len(leaked)} шт.) — запись остановлена")
    result["privacy_check"] = {"identifiers_in_output": 0, "row_level_predictions_saved": False}
    text = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    (output_dir / "research_results_pre2025.json").write_text(text, encoding="utf-8")
    (output_dir / "research_summary_ru.md").write_text(render_summary(result), encoding="utf-8")
    log("Записано:", output_dir / "research_results_pre2025.json", "и research_summary_ru.md")
    return result


# ---------------------------------------------------------------------------
# Русская сводка для команды (генерируется из JSON)
# ---------------------------------------------------------------------------
def _f(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}".replace(",", " ")
    return f"{float(value):.{digits}f}"


def _ci_text(entry: dict[str, Any] | None) -> str:
    if not entry or entry.get("mean_difference") is None:
        return "—"
    return f"{entry['mean_difference']:+.4f} [{entry['ci95_low']:+.4f}; {entry['ci95_high']:+.4f}]"


MODEL_TITLES_RU = {
    "B0_constant": "B0 константа",
    "B1_type_prevalence": "B1 доля по типу датчика",
    "B2_recurrence": "B2 recurrence-скор",
    "B3_rule": "B3 правило",
    "B4_logistic": "B4 логистическая регрессия",
    "M0_lightgbm": "M0 LightGBM (safe_recurrence)",
    "no_recurrence": "без recurrence",
    "no_calendar": "без календаря",
    "no_current_catalogue": "без каталога",
    "condition_only": "только condition-признаки",
    "propensity_only": "только propensity",
    "baseline_plus_propensity": "M0 + propensity",
    "no_recurrence_plus_propensity": "без recurrence + propensity",
}
DECISION_RU = {"confirmed": "подтверждено", "rejected": "отклонено", "inconclusive": "не определено"}


def render_summary(r: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Аудит baseline, shortcut-признаков и channel propensity (pre-2025)")
    add("")
    add(f"Статус: **{r.get('status')}** · режим: **{r.get('mode')}** · сравнимость: `{r.get('comparability')}`")
    add("")
    if r.get("mode") == "SMOKE":
        add("> **SMOKE-прогон.** Выборка каналов и число деревьев урезаны; числа ниже нельзя "
            "сравнивать ни между собой, ни с FULL.")
        add("")
    add("Цель — `target_failure_state_onset_24h`: наблюдаемый proxy начала состояния "
        "`Неисправен`/`Обесточен` в сутки D+2. Это **не подтверждённая физическая поломка**. "
        "Оценка — на двух rolling-фолдах до 2025 года (development validation), это **не финальный тест**.")
    add("")
    if r.get("status") in ("contract_failed", "m0_reproduction_failed"):
        add("## Остановка")
        add("")
        add(f"Причина: {r.get('stop_reason')}")
        add("")
        add("Дальнейшие эксперименты не выполнялись; заявлений об улучшении нет.")
        return "\n".join(lines) + "\n"

    folds = r["folds"]
    fold_names = list(folds)
    add("## Выборки")
    add("")
    add("| фолд | train (до / после прореживания) | calibration H1 | validation H2 | positives validation | prevalence B0 (pre-validation) |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name in fold_names:
        f = folds[name]
        add(f"| {name} | {_f(f['rows']['train_before_sampling'])} / {_f(f['rows'].get('train_after_sampling'))} "
            f"| {_f(f['rows']['calibration'])} | {_f(f['rows']['validation'])} | {_f(f['positives']['validation'])} "
            f"| {_f(f['b0_prevalence_pre_validation'])} |")
    add("")

    pooled = r["pooled_mean_over_folds"]
    add("## 1. Baseline-лестница")
    add("")
    add("Среднее по двум фолдам. Эпизоды: 50 тревог/сутки, cooldown 72 ч, порог выбран на H1.")
    add("")
    add("| модель | PR-AUC | lift над B0 | эпизоды recall | эпизоды precision | ложных / 1000 | Brier | ECE |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for model in BASELINES + [M0]:
        p = pooled[model]
        add(f"| {MODEL_TITLES_RU[model]} | {_f(p['mean_pr_auc'])} | {_f(p['mean_lift_over_b0'], 2)} "
            f"| {_f(p['mean_episode_recall_50_72h'])} | {_f(p['mean_episode_precision_50_72h'])} "
            f"| {_f(p['mean_false_alerts_per_1000'], 1)} | {_f(p['mean_brier'])} | {_f(p['mean_ece'])} |")
    add("")
    add("По фолдам:")
    add("")
    add("| модель | " + " | ".join(f"{n}: PR-AUC | {n}: эпизоды recall" for n in fold_names) + " |")
    add("| --- | " + " | ".join("---: | ---:" for _ in fold_names) + " |")
    for model in BASELINES + [M0]:
        cells = []
        for n in fold_names:
            m = folds[n]["models"][model]
            cells += [_f(m["point"]["pr_auc"]), _f(m["episodes"]["budget_50_cooldown_72h"]["recall"])]
        add(f"| {MODEL_TITLES_RU[model]} | " + " | ".join(cells) + " |")
    add("")
    add("Эпизодные метрики B0 и B1 (константа/доля по типу) определяются в основном порядком разрешения "
        "равных скоров (по ключу канала), поэтому для них информативен PR-AUC, а не эпизоды.")
    add("")
    comps = r["paired_bootstrap"]["comparisons"]
    add("Парные 95% CI (бутстрэп блоками недель), разность **baseline − M0**, среднее по фолдам:")
    add("")
    add("| сравнение | PR-AUC | эпизоды recall | эпизоды precision |")
    add("| --- | ---: | ---: | ---: |")
    for baseline in ("B2_recurrence", "B3_rule", "B4_logistic"):
        c = comps[f"{baseline}_vs_M0"]["mean_over_folds"]
        add(f"| {MODEL_TITLES_RU[baseline]} − M0 | {_ci_text(c['pr_auc'])} | {_ci_text(c['episode_recall_50_72h'])} "
            f"| {_ci_text(c['episode_precision_50_72h'])} |")
    add("")

    add("## 2. Ablation shortcut-признаков")
    add("")
    add("Разность **вариант − M0**, среднее по фолдам, 95% CI. Важность признаков в JSON — только "
        "predictive association, не причинность.")
    add("")
    add("| вариант | PR-AUC | Δ PR-AUC | Δ эпизоды recall | Δ эпизоды precision |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for variant in ("no_recurrence", "no_calendar", "no_current_catalogue", "condition_only"):
        c = comps[f"{variant}_vs_M0"]["mean_over_folds"]
        add(f"| {MODEL_TITLES_RU[variant]} | {_f(pooled[variant]['mean_pr_auc'])} | {_ci_text(c['pr_auc'])} "
            f"| {_ci_text(c['episode_recall_50_72h'])} | {_ci_text(c['episode_precision_50_72h'])} |")
    add("")

    add("## 3. Clean-history sensitivity")
    add("")
    add("`eligible(k)`: `d_days_since_failure_state_event` отсутствует или ≥ k. Изменение prevalence — "
        "свойство выборки, а не улучшение модели. Это диагностика, не новая подтверждённая цель.")
    add("")
    for cohort, title in (("native", "Native cohort — каждая версия на своей eligibility-выборке"),
                          ("common_k30", "Common cohort — все версии на validation-строках, подходящих для k=30")):
        add(f"**{title}**")
        add("")
        add("| фолд | k | строк | positives | prevalence | PR-AUC | эпизоды recall | эпизоды precision |")
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for name in fold_names:
            for key, v in folds[name]["clean_history"][cohort].items():
                e = v["episodes_budget_50_cooldown_72h"]
                add(f"| {name} | {key.split('_')[1]} | {_f(v['rows'])} | {_f(v['positives'])} | {_f(v['prevalence'])} "
                    f"| {_f(v['pr_auc'])} | {_f(e['recall'])} | {_f(e['precision'])} |")
        add("")
    add(f"k=30 против k=0 на common cohort, Δ PR-AUC: "
        f"{_ci_text(comps['clean_history_k30_vs_k0_on_common_cohort']['mean_over_folds'])}; "
        f"M0 против B2 на common cohort: {_ci_text(comps['M0_vs_B2_on_common_cohort_k30']['mean_over_folds'])}.")
    add("")

    add("## 4. Channel propensity (вторичный эксперимент)")
    add("")
    add("Propensity — **identity-like историческая характеристика канала**, не физический и не причинный "
        "признак. История учитывается только по строкам, чьё окно цели закрыто к концу суток D; "
        "пропущенные channel-days не считаются отрицательными; 2021 в историю не входит.")
    add("")
    add("| вариант | m (fold_2023 / fold_2024) | PR-AUC | Δ PR-AUC к M0 | Δ эпизоды recall к M0 |")
    add("| --- | --- | ---: | ---: | ---: |")
    for variant in ("propensity_only", "baseline_plus_propensity", "no_recurrence_plus_propensity"):
        ms = " / ".join(str(folds[n]["propensity"]["m_selection_on_calibration_h1"][variant]["chosen_m"]) for n in fold_names)
        c = comps[f"{variant}_vs_M0"]["mean_over_folds"]
        add(f"| {MODEL_TITLES_RU[variant]} | {ms} | {_f(pooled[variant]['mean_pr_auc'])} | {_ci_text(c['pr_auc'])} "
            f"| {_ci_text(c['episode_recall_50_72h'])} |")
    add("")
    add(f"Без recurrence: (без recurrence + propensity) − (без recurrence), Δ PR-AUC: "
        f"{_ci_text(comps['no_recurrence_plus_propensity_vs_no_recurrence']['mean_over_folds']['pr_auc'])}.")
    add("")

    add("## 5. Unseen / support и coverage")
    add("")
    add("Группы определены только по train + calibration каждого фолда. PR-AUC не показывается при < 20 positives.")
    add("")
    add("| фолд | группа | строк | доля строк | positives | каналов | объектов | M0 PR-AUC | M0 эпизоды recall |")
    add("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name in fold_names:
        cov = folds[name]["coverage"]
        for group, g in cov["groups"].items():
            s = folds[name]["support_generalization"][M0][group]
            add(f"| {name} | {group} | {_f(g['rows'])} | {_f(g['row_share'], 3)} | {_f(g['positives'])} "
                f"| {_f(g['channels'])} | {_f(g['objects'])} | {_f(s['pr_auc'])} | {_f(s['episode_recall_50_72h'])} |")
    add("")
    for name in fold_names:
        cov = folds[name]["coverage"]
        add(f"- {name}: validation {cov['validation_date_min']} — {cov['validation_date_max']}, "
            f"дат с данными {cov['validation_dates_covered']}, наблюдаемых каналов {cov['validation_channels_observed']}, "
            f"объектов {cov['validation_objects_observed']}.")
    add("")
    add("Coverage описывает только наблюдаемую sparse event-panel. Выводов о полном operational coverage "
        "парка отсюда сделать нельзя: для этого нужны raw target dictionary, жизненный цикл каналов и аудит тихих суток.")
    add("")

    add("## 6. Гипотезы")
    add("")
    add("| гипотеза | решение | причина |")
    add("| --- | --- | --- |")
    for key, h in r["hypotheses"].items():
        add(f"| `{key}` | **{DECISION_RU.get(h['decision'], h['decision'])}** | `{h['reason']}` |")
    add("")

    add("## 7. Отбор кандидата")
    add("")
    add("| кандидат | эпизоды recall | эпизоды precision | PR-AUC | прошёл gates | не пройдены |")
    add("| --- | ---: | ---: | ---: | --- | --- |")
    for candidate, v in r["selection"]["candidates"].items():
        add(f"| {MODEL_TITLES_RU.get(candidate, candidate)} | {_f(v['mean_episode_recall_50_72h'])} "
            f"| {_f(v['mean_episode_precision_50_72h'])} | {_f(v['mean_pr_auc'])} | {'да' if v['passed'] else 'нет'} "
            f"| {', '.join(v['failed_gates']) or '—'} |")
    add("")
    sel = r["selection"]
    add(f"**Текущий кандидат: `{sel['selected']}`** (`{sel['reason']}`).")
    if sel["selected"] == M0:
        add("")
        add("M0 зафиксирован как текущий кандидат **без заявления об улучшении**.")
    add("")
    stress = r.get("stress_2021", {})
    if stress and stress.get("status") != "no_rows":
        add("## 8. Stress 2021 (однократно, после выбора)")
        add("")
        add(f"Модели фолда {stress.get('models_from')}; строк {_f(stress.get('rows'))}, prevalence {_f(stress.get('prevalence'))}, "
            f"B2 PR-AUC {_f(stress.get('B2_recurrence_pr_auc'))}.")
        add("")
        for model in dict.fromkeys((M0, sel["selected"])):  # без повтора, если выбран M0
            if model in stress:
                point = stress[model]["point"]
                ep = stress[model]["episodes"].get("budget_50_cooldown_72h", {})
                add(f"- {MODEL_TITLES_RU.get(model, model)}: PR-AUC {_f(point['pr_auc'])}, "
                    f"эпизоды recall {_f(ep.get('recall'))}, precision {_f(ep.get('precision'))}.")
        add("")
    add("## Ограничения")
    add("")
    add("- Proxy-цель по журналу, не подтверждённые физические отказы.")
    add("- Два pre-2025 фолда — development validation, не финальный тест; 2025 H2 и 2026 не использовались.")
    add("- Панель содержит только суточные строки с событиями; тихие сутки не достраивались и не считались отрицательными.")
    add("- Episode-target окончательно можно установить только сборкой из raw events.")
    add("- Бутстрэп блоками недель не учитывает зависимость между фолдами; CI по среднему — приближённые.")
    add("")
    runtime = r.get("runtime", {})
    add(f"Время прогона: {runtime.get('seconds_total')} с. Окружение: {r['environment'].get('cpu_count')} CPU, "
        f"{r['environment'].get('ram_total_gb')} ГБ RAM, GPU: {r['environment'].get('gpu')}.")
    return "\n".join(lines) + "\n"


def make_config(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode not in ("SMOKE", "FULL"):
        raise ValueError("MODE должен быть 'SMOKE' или 'FULL'")
    config = {
        "mode": mode,
        "output_dir": "/kaggle/working",
        "random_seed": 20260919,
        "negative_to_positive_ratio": 20,
        "minimum_precision": 0.20,
        "lgbm_iterations": 500 if mode == "FULL" else 30,
        "bootstrap_reps": 500 if mode == "FULL" else 50,
        "bootstrap_seed": 42,
        "budgets": [10, 25, 50, 100],
        "cooldowns": [24, 72, 168],
        "clean_history_days": [0, 7, 14, 30],
        "m_grid": [5, 15, 50, 100],
        "min_positives_for_pr_auc": 20,
        "b1_min_type_rows": 100,
        "support_min_rows": 1000,
        "support_min_positives": 100,
        "smoke_channel_share": 20,
    }
    config.update(overrides or {})
    return config


# ===========================================================================
# Самопроверки на синтетике
# ===========================================================================



from datetime import date, timedelta
from typing import Any

import numpy as np


def synthetic_panel(n_channels: int = 60, start: date = date(2019, 1, 1), end: date = date(2025, 12, 29),
                    seed: int = 7, active_scale: float = 1.0) -> Any:
    """Синтетическая панель в точной схеме v2 (без реальных данных)."""
    import polars as pl

    rng = np.random.default_rng(seed)
    days = (end - start).days + 1
    types = ["Состояние вентилятора", "Состояние насоса", "Состояние фазы", "Датчик дыма",
             "Газовый датчик", "Датчик температуры", "КД Дверь", "ИБП"]
    systems = {"Состояние вентилятора": "Вентиляция", "Состояние насоса": "Водоотведение",
               "Состояние фазы": "Электроснабжение", "Датчик дыма": "Пожарная сигнализация",
               "Газовый датчик": "Газоанализ", "Датчик температуры": "Климат",
               "КД Дверь": "СКУД", "ИБП": "Электроснабжение"}
    type_rate = dict(zip(types, [0.030, 0.050, 0.120, 0.006, 0.002, 0.002, 0.0005, 0.02]))
    frames = []
    for c in range(n_channels):
        sensor = types[c % len(types)] if rng.random() > 0.02 else None
        rate = type_rate.get(sensor, 0.01) * float(rng.lognormal(0, 0.9))
        season = 1 + 0.4 * np.sin(2 * np.pi * np.arange(days) / 365.25)
        fail = rng.random(days) < np.clip(rate * season, 0, 0.6)
        born = int(rng.integers(0, days // 2)) if rng.random() < 0.25 else 0
        fail[:born] = False
        active = (rng.random(days) < min(0.95, active_scale * float(rng.uniform(0.15, 0.7)))) | fail
        active[:born] = False
        idx = np.flatnonzero(active)
        idx = idx[idx + 2 < days]
        if not len(idx):
            continue
        onset = fail[idx + 2] & ~fail[idx + 1]
        last_fail = np.full(days, -1)
        pos = -1
        for d in range(days):
            if fail[d]:
                pos = d
            last_fail[d] = pos
        since = np.where(last_fail[idx] >= 0, idx - last_fail[idx], np.nan)
        gap = np.r_[np.nan, np.diff(idx)].astype(float)
        cutoff = np.array([start + timedelta(days=int(d)) for d in idx])
        n = len(idx)
        events = rng.poisson(3 + 10 * fail[idx], n) + 1
        alarms = rng.binomial(events, 0.1 + 0.3 * onset)
        label = onset.astype(float)
        label[rng.random(n) < 0.03] = np.nan  # часть строк без метки
        frames.append(pl.DataFrame({
            "d_channel_key": [f"ch_{c:04d}{rng.integers(1 << 30):08x}"] * n,
            "d_object_key": [f"obj_{c // 6:04d}{(c // 6) * 7919 % 99991:06d}"] * n,
            "d_cutoff_date": list(cutoff),
            "d_target_start_date": [d + timedelta(days=2) for d in cutoff],
            "d_target_end_date_exclusive": [d + timedelta(days=3) for d in cutoff],
            "d_future_failure_event_date": [d + timedelta(days=2) if o else None for d, o in zip(cutoff, onset)],
            "d_future_alarm_event_date": [None] * n,
            "d_year": [d.year for d in cutoff],
            "target_failure_state_onset_24h": [None if np.isnan(v) else int(v) for v in label],
            "target_alarm_onset_24h": (rng.random(n) < 0.05).astype(int),
            "d_event_count_24h": events.astype(float),
            "d_alarm_count_24h": alarms.astype(float),
            "d_alarm_share_24h": alarms / events,
            "d_failure_state_event_count_24h": fail[idx].astype(float) * rng.integers(1, 4, n),
            "d_value_numeric_mean_24h": rng.normal(20, 5, n),
            "d_value_numeric_min_24h": rng.normal(15, 5, n),
            "d_value_numeric_max_24h": rng.normal(25, 5, n),
            "d_value_numeric_std_24h": rng.gamma(2, 1, n),
            "d_value_numeric_last": rng.normal(20, 5, n),
            "d_state_n_unique_24h": rng.integers(1, 4, n).astype(float),
            "d_gap_days_since_previous": gap,
            "d_event_count_previous_24h": np.r_[np.nan, events[:-1]].astype(float),
            "d_alarm_count_previous_24h": np.r_[np.nan, alarms[:-1]].astype(float),
            "d_alarm_share_previous_24h": np.r_[np.nan, (alarms / events)[:-1]],
            "d_value_numeric_previous": rng.normal(20, 5, n),
            "d_days_since_failure_state_event": since,
            "d_weekday": np.array([d.weekday() for d in cutoff], dtype=float),
            "d_month": np.array([d.month for d in cutoff], dtype=float),
            "d_catalogue_match": (rng.random(n) < 0.97).astype(float),
            "тип_инж_системы": [systems.get(sensor) if sensor else None] * n,
            "тип_датчика": [sensor] * n,
        }, schema_overrides={"d_cutoff_date": pl.Date, "d_target_start_date": pl.Date,
                             "d_target_end_date_exclusive": pl.Date, "d_future_failure_event_date": pl.Date, "d_future_alarm_event_date": pl.Date,
                             "тип_инж_системы": pl.String, "тип_датчика": pl.String}))
    panel = pl.concat(frames, how="vertical").sort(["d_cutoff_date", "d_channel_key"])
    return panel.with_columns(
        pl.col("target_failure_state_onset_24h").cast(pl.Int8),
        pl.col("target_alarm_onset_24h").cast(pl.Int8),
        pl.col("d_year").cast(pl.Int32),
    )


# Эталон: episode_metrics из общего runtime исходных notebook (без изменений логики).
def _reference_episode_metrics(frame: Any, probability: np.ndarray, threshold: float,
                               budget_per_day: int, cooldown_hours: int) -> dict[str, Any]:
    import pandas as pd

    event_column = EVENT_COLUMN
    columns = ["d_channel_key", "d_cutoff_date", "d_target_start_date", "d_target_end_date_exclusive",
               event_column, TARGET, "тип_датчика"]
    data = pd.DataFrame(frame.select(columns).to_dict(as_series=False))
    data["probability"] = probability
    for column in ["d_cutoff_date", "d_target_start_date", "d_target_end_date_exclusive", event_column]:
        data[column] = pd.to_datetime(data[column])
    alerts = data[np.isfinite(probability) & (probability >= threshold)].copy()
    alerts = alerts.sort_values(["d_cutoff_date", "probability", "d_channel_key"],
                                ascending=[True, False, True], kind="mergesort"
                                ).groupby("d_cutoff_date", sort=False).head(budget_per_day)
    alerts["d_alert_time"] = alerts["d_cutoff_date"] + pd.to_timedelta(1, unit="D")
    keep, last = [], {}
    cooldown = pd.to_timedelta(cooldown_hours, unit="h")
    for index, row in alerts.sort_values(["d_alert_time", "d_channel_key"]).iterrows():
        previous = last.get(row["d_channel_key"])
        if previous is None or row["d_alert_time"] - previous >= cooldown:
            keep.append(index)
            last[row["d_channel_key"]] = row["d_alert_time"]
    alerts = alerts.loc[keep]
    events = data.loc[data[TARGET] == 1, ["d_channel_key", event_column]].dropna()
    events = events.drop_duplicates(["d_channel_key", event_column]).reset_index(drop=True)
    matched_events: set[int] = set()
    matched_alerts = 0
    for _, alert in alerts.sort_values("d_alert_time").iterrows():
        candidates = events[(events["d_channel_key"] == alert["d_channel_key"])
                            & (events[event_column] >= alert["d_target_start_date"])
                            & (events[event_column] < alert["d_target_end_date_exclusive"])
                            & (~events.index.isin(matched_events))]
        if not candidates.empty:
            matched_events.add(int(candidates.sort_values(event_column).index[0]))
            matched_alerts += 1
    return {"alert_episodes": int(len(alerts)), "proxy_events": int(len(events)),
            "matched_alerts": matched_alerts,
            "precision": matched_alerts / max(len(alerts), 1),
            "recall": len(matched_events) / max(len(events), 1)}


def run_self_tests() -> dict[str, Any]:
    import polars as pl
    from sklearn.metrics import average_precision_score

    report: dict[str, Any] = {}
    panel = synthetic_panel(n_channels=40, start=date(2022, 1, 1), end=date(2024, 12, 31), active_scale=1.3)
    labelled = panel.filter(pl.col(TARGET).is_not_null())
    rng = np.random.default_rng(0)

    # 1. Быстрый взвешенный PR-AUC совпадает со sklearn (включая равные скоры).
    y = labelled[TARGET].to_numpy().astype(np.int8)
    p = np.round(rng.random(len(y)) * 0.3 + 0.5 * y * rng.random(len(y)), 3)
    w = rng.integers(0, 4, len(y)).astype(float)
    fast = APPrep(y, p).ap(w)
    reference = average_precision_score(y, p, sample_weight=w)
    assert abs(fast - reference) < 1e-9, (fast, reference)
    report["weighted_pr_auc_matches_sklearn"] = True

    # 2. Быстрые эпизоды совпадают с эталоном исходного runtime.
    val = labelled.filter(pl.col("d_cutoff_date") >= date(2024, 7, 1))
    ev = EvalFrame(val, date(2024, 7, 1))
    p = rng.random(val.height) * 0.5 + 0.5 * ev.y * rng.random(val.height)
    for budget, cooldown, thr in ((3, 72, 0.2), (1, 24, 0.0), (5, 168, 0.4), (50, 72, 0.3)):
        mine = episodes(ev, p, thr, budget, cooldown)
        ref = _reference_episode_metrics(val, p, thr, budget, cooldown)
        for key in ("alert_episodes", "proxy_events", "matched_alerts"):
            assert mine[key] == ref[key], (budget, cooldown, key, mine[key], ref[key])
    report["episode_metrics_match_reference_runtime"] = True

    # 3. Изменение будущих меток не меняет более ранний propensity.
    grid = [5, 15]
    base = build_propensity(labelled, grid)
    cut = date(2023, 6, 1)
    flipped = labelled.with_columns(
        pl.when(pl.col("d_cutoff_date") >= pl.lit(cut)).then(1 - pl.col(TARGET)).otherwise(pl.col(TARGET))
        .cast(pl.Int8).alias(TARGET))
    changed = build_propensity(flipped, grid)
    # Строки, у которых вся используемая история закончилась до cut: cutoff + 1 < cut.
    early = (base["d_cutoff_date"] + timedelta(days=1)) < cut
    early = early.to_numpy()
    for column in HIST_FEATURES[:-1] + [f"d_hist_failure_rate_eb_m{m}" for m in grid]:
        a = base[column].to_numpy()[early].astype(float)
        b = changed[column].to_numpy()[early].astype(float)
        assert np.allclose(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1)), column
    report["future_labels_do_not_change_earlier_propensity"] = True

    # 4. Строка учитывается в истории только после закрытия окна цели.
    one = base.filter(pl.col("d_channel_key") == base["d_channel_key"][0]).sort("d_cutoff_date")
    ends = labelled.filter(pl.col("d_channel_key") == one["d_channel_key"][0])["d_target_end_date_exclusive"].to_numpy()
    for row in one.head(200).iter_rows(named=True):
        key = np.datetime64(row["d_cutoff_date"] + timedelta(days=1))
        expected = int((ends <= key).sum())
        assert int(row["d_hist_eligible_days_all"]) == expected, (row["d_cutoff_date"], expected)
    report["history_uses_only_closed_target_windows"] = True

    # 5. Пропущенные channel-days не становятся отрицательными: удаление строк
    #    уменьшает eligible-счётчики ровно на число удалённых закрытых строк.
    channel = base["d_channel_key"][0]
    sub = labelled.filter(pl.col("d_channel_key") == channel).sort("d_cutoff_date")
    removed = sub.filter(pl.col(TARGET) == 0).head(10)
    thinned = labelled.join(removed.select("d_channel_key", "d_cutoff_date"),
                            on=["d_channel_key", "d_cutoff_date"], how="anti")
    after = build_propensity(thinned, grid).filter(pl.col("d_channel_key") == channel).sort("d_cutoff_date")
    last_row = after.tail(1).row(0, named=True)
    before_row = base.filter((pl.col("d_channel_key") == channel)
                             & (pl.col("d_cutoff_date") == last_row["d_cutoff_date"])).row(0, named=True)
    assert before_row["d_hist_eligible_days_all"] - last_row["d_hist_eligible_days_all"] == removed.height
    assert before_row["d_hist_positive_days_all"] == last_row["d_hist_positive_days_all"]
    report["missing_channel_days_are_not_implicit_negatives"] = True

    # 6. Никаких сдвигов по номеру строки: перестановка строк не меняет признаки.
    shuffled = labelled.sample(fraction=1.0, shuffle=True, seed=3)
    again = build_propensity(shuffled, grid).sort(["d_channel_key", "d_cutoff_date"])
    ref_sorted = base.sort(["d_channel_key", "d_cutoff_date"])
    for column in ("d_hist_eligible_days_all", "d_hist_positive_days_365d", "d_hist_failure_rate_eb_m15"):
        assert np.allclose(np.nan_to_num(again[column].to_numpy().astype(float), nan=-1),
                           np.nan_to_num(ref_sorted[column].to_numpy().astype(float), nan=-1)), column
    report["propensity_invariant_to_row_order"] = True
    return report
