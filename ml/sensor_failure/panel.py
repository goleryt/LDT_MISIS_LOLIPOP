"""Build a leakage-safe channel/day panel from immutable source CSV files."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


EVENT_COLUMNS = [
    "ид_события",
    "ид_канала_данных",
    "дата",
    "время",
    "тревожное",
    "значение_датчика",
]

CATALOGUE_COLUMNS = [
    "ид_канала_данных",
    "тип_инж_системы",
    "тип_датчика",
    "тег_инженерной_системы",
    "название_датчика",
    "ид_объект",
]

TARGET_COLUMNS = ["target_failure_state_onset_24h", "target_alarm_onset_24h"]
PANEL_SCHEMA_VERSION = "2.0"


def file_sha256(path: Path) -> str:
    """Return a streaming SHA-256 without loading a source file into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_failure_state_dictionary(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("default"), list):
        raise ValueError("failure-state dictionary must contain a list named 'default'")
    if not isinstance(config.get("by_тип_датчика", {}), dict):
        raise ValueError("'by_тип_датчика' must be an object")
    return config


def _failure_expression(pl: Any, config: dict[str, Any]) -> Any:
    state = pl.col("значение_датчика")
    result = state.is_in(config["default"])
    for sensor_type, values in config.get("by_тип_датчика", {}).items():
        result = pl.when(pl.col("тип_датчика") == sensor_type).then(
            state.is_in(values)
        ).otherwise(result)
    return result.fill_null(False)


def _event_paths(data_dir: Path) -> list[Path]:
    paths = [data_dir / f"ext-journal-{year}.csv" for year in range(2019, 2027)]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing historical journals: {missing}")
    return paths


def source_file_manifest(data_dir: Path) -> list[dict[str, Any]]:
    """Hash immutable event journals and the channel catalogue for cache checks."""
    catalogue = data_dir / "справочник_каналов_датчиков.csv"
    paths = [*_event_paths(data_dir), catalogue]
    if not catalogue.exists():
        raise FileNotFoundError(catalogue)
    return [
        {"name": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for path in paths
    ]


def _scan_events(pl: Any, path: Path) -> Any:
    schema = {column: pl.String for column in EVENT_COLUMNS}
    return pl.scan_csv(
        path,
        has_header=True,
        schema_overrides=schema,
        infer_schema_length=0,
        encoding="utf8-lossy",
        low_memory=True,
    ).filter(pl.col("ид_события") != "ид_события")


def _scan_catalogue(pl: Any, data_dir: Path) -> Any:
    path = data_dir / "справочник_каналов_датчиков.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    schema = {column: pl.String for column in CATALOGUE_COLUMNS}
    return pl.scan_csv(
        path,
        has_header=True,
        schema_overrides=schema,
        infer_schema_length=0,
        encoding="utf8-lossy",
    ).select(CATALOGUE_COLUMNS)


def build_panel(
    data_dir: Path,
    failure_dictionary_path: Path,
    latency_minutes: int = 0,
    target_lead_hours: int = 24,
    target_window_hours: int = 24,
    clean_history_days: int = 0,
) -> tuple[Any, dict[str, Any]]:
    """Return a Polars DataFrame and a compact, aggregate-only audit manifest.

    The row cutoff is the end of ``d_cutoff_date``. Feature events use an
    artificial availability time equal to registration time plus the requested
    latency. The daily panel supports whole-day lead and outcome windows. With
    the defaults, events on D+2 are predicted at the end of D, providing a
    formal lead of at least 24 hours.
    """
    import polars as pl

    if latency_minutes < 0:
        raise ValueError("latency_minutes must be non-negative")
    if target_lead_hours < 0 or target_lead_hours % 24:
        raise ValueError("target_lead_hours must be a non-negative multiple of 24")
    if target_window_hours <= 0 or target_window_hours % 24:
        raise ValueError("target_window_hours must be a positive multiple of 24")
    if clean_history_days < 0:
        raise ValueError("clean_history_days must be non-negative")

    lead_days = target_lead_hours // 24
    window_days = target_window_hours // 24

    dictionary = load_failure_state_dictionary(failure_dictionary_path)
    catalogue = _scan_catalogue(pl, data_dir).collect()
    actual_parts = []
    available_parts = []
    order = ["d_available_time", "d_event_time", "ид_события", "значение_датчика"]

    # Aggregate one source year at a time. This is the key memory boundary:
    # no operation ever sorts or groups all 313M raw events together.
    for path in _event_paths(data_dir):
        typed = (
            _scan_events(pl, path)
            .join(catalogue.lazy(), on="ид_канала_данных", how="left")
            .with_columns(
                pl.concat_str(["дата", "время"], separator=" ")
                .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
                .alias("d_event_time"),
                pl.col("тревожное")
                .str.to_lowercase()
                .is_in(["t", "true"])
                .alias("d_alarm"),
                pl.col("значение_датчика")
                .str.replace(",", ".", literal=True)
                .cast(pl.Float64, strict=False)
                .alias("d_value_numeric"),
                pl.col("тип_датчика").is_not_null().alias("d_catalogue_match"),
            )
            .filter(pl.col("d_event_time").is_not_null())
            .with_columns(
                pl.when(pl.col("d_value_numeric").is_null())
                .then(pl.col("значение_датчика"))
                .otherwise(None)
                .alias("d_value_state"),
                _failure_expression(pl, dictionary).alias("d_failure_state_event"),
            )
        )

        actual_parts.append(
            typed.with_columns(
                pl.col("d_event_time").dt.date().alias("d_actual_date")
            )
            .group_by(["ид_канала_данных", "d_actual_date"])
            .agg(
                pl.len().alias("d_future_event_count"),
                pl.col("d_failure_state_event").any().alias(
                    "d_future_failure_state"
                ),
                pl.col("d_alarm").any().alias("d_future_alarm"),
            )
            .collect(engine="streaming")
        )

        available = typed.with_columns(
            (pl.col("d_event_time") + pl.duration(minutes=latency_minutes)).alias(
                "d_available_time"
            )
        ).with_columns(pl.col("d_available_time").dt.date().alias("d_cutoff_date"))
        available_parts.append(
            available.group_by(["ид_канала_данных", "d_cutoff_date"])
            .agg(
                pl.len().alias("d_event_count_24h"),
                pl.col("d_alarm").sum().alias("d_alarm_count_24h"),
                pl.col("d_failure_state_event").sum().alias(
                    "d_failure_state_event_count_24h"
                ),
                pl.col("d_failure_state_event")
                .sort_by(order)
                .last()
                .alias("d_current_failure_state"),
                pl.col("d_alarm").sort_by(order).last().alias("d_current_alarm"),
                pl.col("d_value_numeric").sum().alias("d_value_numeric_sum_24h"),
                (pl.col("d_value_numeric") ** 2)
                .sum()
                .alias("d_value_numeric_sum_squares_24h"),
                pl.col("d_value_numeric").count().alias("d_value_numeric_count_24h"),
                pl.col("d_value_numeric").min().alias("d_value_numeric_min_24h"),
                pl.col("d_value_numeric").max().alias("d_value_numeric_max_24h"),
                pl.col("d_value_numeric")
                .sort_by(order)
                .last()
                .alias("d_value_numeric_last"),
                pl.col("d_value_state").n_unique().alias("d_state_n_unique_24h"),
                pl.col("d_catalogue_match")
                .sort_by(order)
                .last()
                .alias("d_catalogue_match"),
                pl.col("d_available_time").max().alias("d_last_available_time"),
                pl.col("тип_инж_системы")
                .sort_by(order)
                .last()
                .alias("тип_инж_системы"),
                pl.col("тип_датчика").sort_by(order).last().alias("тип_датчика"),
                pl.col("ид_объект").sort_by(order).last().alias("ид_объект"),
            )
            .collect(engine="streaming")
        )

    actual_daily = (
        pl.concat(actual_parts, how="vertical")
        .group_by(["ид_канала_данных", "d_actual_date"])
        .agg(
            pl.col("d_future_event_count").sum(),
            pl.col("d_future_failure_state").any(),
            pl.col("d_future_alarm").any(),
        )
    )

    daily = (
        pl.concat(available_parts, how="vertical")
        .group_by(["ид_канала_данных", "d_cutoff_date"])
        .agg(
            pl.col("d_event_count_24h").sum(),
            pl.col("d_alarm_count_24h").sum(),
            pl.col("d_failure_state_event_count_24h").sum(),
            pl.col("d_current_failure_state")
            .sort_by("d_last_available_time")
            .last(),
            pl.col("d_current_alarm").sort_by("d_last_available_time").last(),
            pl.col("d_value_numeric_sum_24h").sum(),
            pl.col("d_value_numeric_sum_squares_24h").sum(),
            pl.col("d_value_numeric_count_24h").sum(),
            pl.col("d_value_numeric_min_24h").min(),
            pl.col("d_value_numeric_max_24h").max(),
            pl.col("d_value_numeric_last")
            .sort_by("d_last_available_time")
            .last(),
            pl.col("d_state_n_unique_24h").sum(),
            pl.col("d_catalogue_match").sort_by("d_last_available_time").last(),
            pl.col("d_last_available_time").max(),
            pl.col("тип_инж_системы").sort_by("d_last_available_time").last(),
            pl.col("тип_датчика").sort_by("d_last_available_time").last(),
            pl.col("ид_объект").sort_by("d_last_available_time").last(),
        )
        .with_columns(
            (
                pl.col("d_value_numeric_sum_24h")
                / pl.col("d_value_numeric_count_24h")
            ).alias("d_value_numeric_mean_24h"),
            pl.when(pl.col("d_value_numeric_count_24h") > 1)
            .then(
                (
                    (
                        pl.col("d_value_numeric_sum_squares_24h")
                        - pl.col("d_value_numeric_sum_24h") ** 2
                        / pl.col("d_value_numeric_count_24h")
                    )
                    / (pl.col("d_value_numeric_count_24h") - 1)
                )
                .clip(lower_bound=0)
                .sqrt()
            )
            .otherwise(None)
            .alias("d_value_numeric_std_24h"),
        )
        .drop(
            "d_value_numeric_sum_24h",
            "d_value_numeric_sum_squares_24h",
            "d_value_numeric_count_24h",
        )
        .sort(["ид_канала_данных", "d_cutoff_date"])
        .with_columns(
            pl.col("d_cutoff_date")
            .shift(1)
            .over("ид_канала_данных")
            .alias("d_previous_observed_date")
        )
        .with_columns(
            (pl.col("d_cutoff_date") - pl.col("d_previous_observed_date"))
            .dt.total_days()
            .alias("d_gap_days_since_previous"),
            (
                pl.col("d_alarm_count_24h") / pl.col("d_event_count_24h")
            ).alias("d_alarm_share_24h"),
            pl.col("d_cutoff_date").dt.weekday().alias("d_weekday"),
            pl.col("d_cutoff_date").dt.month().alias("d_month"),
            pl.col("d_cutoff_date").dt.year().alias("d_year"),
        )
        .with_columns(
            pl.when(pl.col("d_failure_state_event_count_24h") > 0)
            .then(pl.col("d_cutoff_date"))
            .otherwise(None)
            .forward_fill()
            .over("ид_канала_данных")
            .alias("d_last_failure_state_event_date")
        )
        .with_columns(
            (
                pl.col("d_cutoff_date")
                - pl.col("d_last_failure_state_event_date")
            )
            .dt.total_days()
            .alias("d_days_since_failure_state_event")
        )
    )

    previous = daily.select(
        "ид_канала_данных",
        (pl.col("d_cutoff_date") + pl.duration(days=1)).alias("d_cutoff_date"),
        pl.col("d_event_count_24h").alias("d_event_count_previous_24h"),
        pl.col("d_alarm_count_24h").alias("d_alarm_count_previous_24h"),
        pl.col("d_alarm_share_24h").alias("d_alarm_share_previous_24h"),
        pl.col("d_value_numeric_last").alias("d_value_numeric_previous"),
    )

    future = None
    future_columns: list[tuple[str, str, str]] = []
    for offset in range(1 + lead_days, 1 + lead_days + window_days):
        count_col = f"d_future_event_count_day_{offset}"
        failure_col = f"d_future_failure_state_day_{offset}"
        alarm_col = f"d_future_alarm_day_{offset}"
        shifted = actual_daily.select(
            "ид_канала_данных",
            (pl.col("d_actual_date") - pl.duration(days=offset)).alias(
                "d_cutoff_date"
            ),
            pl.col("d_future_event_count").alias(count_col),
            pl.col("d_future_failure_state").alias(failure_col),
            pl.col("d_future_alarm").alias(alarm_col),
        )
        future_columns.append((count_col, failure_col, alarm_col))
        future = shifted if future is None else future.join(
            shifted,
            on=["ид_канала_данных", "d_cutoff_date"],
            how="outer_coalesce",
        )

    count_columns = [names[0] for names in future_columns]
    failure_columns = [names[1] for names in future_columns]
    alarm_columns = [names[2] for names in future_columns]
    offsets = list(range(1 + lead_days, 1 + lead_days + window_days))
    clean_history = (
        pl.col("d_days_since_failure_state_event").is_null()
        | (pl.col("d_days_since_failure_state_event") >= clean_history_days)
    )
    failure_eligible = ~pl.col("d_current_failure_state")
    if clean_history_days:
        failure_eligible = failure_eligible & clean_history

    panel = (
        daily.join(
            previous,
            on=["ид_канала_данных", "d_cutoff_date"],
            how="left",
        )
        .join(future, on=["ид_канала_данных", "d_cutoff_date"], how="left")
        .with_columns(
            pl.all_horizontal([pl.col(name).is_not_null() for name in count_columns])
            .alias("d_future_observed"),
            pl.any_horizontal([pl.col(name).fill_null(False) for name in failure_columns])
            .alias("d_future_failure_state"),
            pl.any_horizontal([pl.col(name).fill_null(False) for name in alarm_columns])
            .alias("d_future_alarm"),
            pl.min_horizontal(
                [
                    pl.when(pl.col(name).fill_null(False))
                    .then(pl.col("d_cutoff_date") + pl.duration(days=offset))
                    .otherwise(None)
                    for name, offset in zip(failure_columns, offsets)
                ]
            ).alias("d_future_failure_event_date"),
            pl.min_horizontal(
                [
                    pl.when(pl.col(name).fill_null(False))
                    .then(pl.col("d_cutoff_date") + pl.duration(days=offset))
                    .otherwise(None)
                    for name, offset in zip(alarm_columns, offsets)
                ]
            ).alias("d_future_alarm_event_date"),
            (pl.col("d_cutoff_date") + pl.duration(days=1 + lead_days)).alias(
                "d_target_start_date"
            ),
            (
                pl.col("d_cutoff_date")
                + pl.duration(days=1 + lead_days + window_days)
            ).alias("d_target_end_date_exclusive"),
        )
        .with_columns(
            pl.when(~failure_eligible)
            .then(None)
            .when(~pl.col("d_future_observed"))
            .then(None)
            .otherwise(pl.col("d_future_failure_state").cast(pl.Int8))
            .alias("target_failure_state_onset_24h"),
            pl.when(pl.col("d_current_alarm"))
            .then(None)
            .when(~pl.col("d_future_observed"))
            .then(None)
            .otherwise(pl.col("d_future_alarm").cast(pl.Int8))
            .alias("target_alarm_onset_24h"),
            pl.lit(latency_minutes).cast(pl.Int32).alias("d_latency_minutes"),
        )
        .drop(count_columns + failure_columns + alarm_columns)
    )

    audit = {
        "panel_schema_version": PANEL_SCHEMA_VERSION,
        "target_semantics": "observable proxy, not confirmed physical failure",
        "failure_state_dictionary": dictionary,
        "latency_minutes": latency_minutes,
        "target_lead_hours": target_lead_hours,
        "target_window_hours": target_window_hours,
        "clean_history_days": clean_history_days,
        "rows": panel.height,
        "channels": panel["ид_канала_данных"].n_unique(),
        "date_min": str(panel["d_cutoff_date"].min()),
        "date_max": str(panel["d_cutoff_date"].max()),
        "catalogue_unmatched_rows": int((~panel["d_catalogue_match"]).sum()),
        "panel_columns": panel.columns,
        "source_files": source_file_manifest(data_dir),
        "leakage_audit": {
            "feature_rows_after_cutoff": int(
                (
                    panel["d_last_available_time"].dt.date()
                    > panel["d_cutoff_date"]
                ).sum()
            ),
            "forbidden_model_columns": [
                "ид_события",
                "дата",
                "время",
                "тревожное",
                "значение_датчика",
                "d_event_time",
                "d_last_available_time",
                "d_future_event_count",
                "d_future_failure_state",
                "d_future_alarm",
                "d_future_failure_event_date",
                "d_future_alarm_event_date",
                "d_future_observed",
                *TARGET_COLUMNS,
            ],
        },
        "target_failure_state_onset_24h": _target_audit(
            panel, "target_failure_state_onset_24h"
        ),
        "target_alarm_onset_24h": _target_audit(
            panel, "target_alarm_onset_24h"
        ),
    }
    return panel, audit


def _target_audit(panel: Any, target: str) -> dict[str, int]:
    series = panel[target]
    return {
        "positive": int((series == 1).sum()),
        "negative": int((series == 0).sum()),
        "null": int(series.null_count()),
    }
