"""Shared, standalone runtime for Kaggle notebooks 07--12.

The module deliberately distinguishes observed proxies, anomalies and synthetic
scenario matches from confirmed incidents.  Notebook generation embeds this
file verbatim, so Kaggle does not need the repository as an input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
from typing import Any, Iterable, Sequence

import numpy as np


SOURCE_SCHEMA_VERSION = "2.0"
DERIVED_SCHEMA_VERSION = "missing-targets-1.1"
DROPOUT_SELECTION_CONTRACT_VERSION = "dropout-selection-3.0"
ACCESS_TARGET = "target_access_corroboration_24_48h_proxy"
FIRE_TARGET = "target_fire_corroboration_24_48h_proxy"
DROPOUT_TARGET = "target_channel_dropout_24_48h_proxy"
GENERIC_ALARM_TARGET = "target_any_alarm_observed_Dplus2_proxy"

ACCESS_TYPES = {
    "КД Дверь",
    "КД АВ",
    "КД Люк",
    "9-секционный люк",
    "Датчик движения",
    "Состояние охраны",
    "Стекло",
}
FIRE_TYPES = {
    "Датчик дыма",
    "Газовый датчик",
    "Датчик температуры",
    "Тепловой датчик",
    "Ручной извещатель",
}
VENTILATION_TYPES = {"Состояние вентилятора"}
FLOOD_TYPES = {"Датчик затопления"}
PUMP_TYPES = {"Состояние насоса"}
POWER_TYPES = {"Состояние фазы", "ИБП"}

SOURCE_REQUIRED_COLUMNS = {
    "d_channel_key",
    "d_object_key",
    "d_cutoff_date",
    "d_target_start_date",
    "d_target_end_date_exclusive",
    "d_year",
    "тип_датчика",
    "тип_инж_системы",
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
    "d_catalogue_match",
}

LEAKAGE_COLUMNS = {
    "d_future_failure_event_date",
    "d_future_alarm_event_date",
    "target_failure_state_onset_24h",
    "target_alarm_onset_24h",
}

OBJECT_FEATURES = [
    "d_channel_count",
    "d_sensor_type_count",
    "d_event_count_sum_24h",
    "d_alarm_count_sum_24h",
    "d_alarm_share_mean_24h",
    "d_failure_state_count_sum_24h",
    "d_numeric_mean_mean_24h",
    "d_numeric_min_24h",
    "d_numeric_max_24h",
    "d_numeric_std_mean_24h",
    "d_state_n_unique_max_24h",
    "d_gap_days_mean",
    "d_access_channel_count",
    "d_access_alarm_type_count",
    "d_fire_channel_count",
    "d_fire_alarm_type_count",
    "d_ventilation_alarm_count_24h",
    "d_flood_channel_count",
    "d_flood_alarm_count_24h",
    "d_pump_channel_count",
    "d_pump_alarm_count_24h",
    "d_power_alarm_count_24h",
    "d_flood_numeric_mean_24h",
    "d_pump_numeric_mean_24h",
    "d_days_since_access_corroboration",
    "d_days_since_fire_corroboration",
]

ELEMENT_NUMERIC_FEATURES = [
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
    "d_catalogue_match",
]

TARGET_REGISTRY = {
    ACCESS_TARGET: {
        "evidence_level": "E2",
        "score_kind": "calibrated_corroboration_proxy_probability",
        "entity": "object-day",
        "meaning_ru": (
            "В сутки D+2 на объекте наблюдались тревожные сигналы не менее чем "
            "от двух разных типов access-каналов. Это не факт несанкционированного доступа."
        ),
    },
    FIRE_TARGET: {
        "evidence_level": "E2",
        "score_kind": "calibrated_corroboration_proxy_probability",
        "entity": "object-day",
        "meaning_ru": (
            "В сутки D+2 на объекте наблюдались тревожные сигналы не менее чем "
            "от двух разных типов fire-каналов. Это не подтверждённый пожар."
        ),
    },
    DROPOUT_TARGET: {
        "evidence_level": "E1",
        "score_kind": "channel_availability_proxy_probability",
        "entity": "channel-day",
    "meaning_ru": (
            "На конец D наблюдаем канал и хотя бы один peer-канал. Положительная proxy-метка: "
            "канал наблюдался в D+1, затем не наблюдался D+2…D+4 при активных peer-каналах "
            "и снова появился не позже D+31. Неразрешённые исходы цензурируются. "
            "Это proxy доступности, а не физический отказ."
        ),
    },
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (date, Path)):
        return str(value)
    raise TypeError(f"Cannot serialise {type(value)!r}")


def write_json(path: str | Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return path


def environment_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import polars as pl
        import sklearn

        info["polars"] = pl.__version__
        info["sklearn"] = sklearn.__version__
    except Exception as exc:  # pragma: no cover - diagnostic only
        info["library_error"] = repr(exc)
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["device"] = (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        )
    except Exception:
        info["torch"] = None
        info["cuda_available"] = False
        info["device"] = "CPU"
    return info


def _discover_one(name: str, explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        root = Path(explicit)
        candidates.extend([root / name, *root.rglob(name)])
    env_root = os.environ.get("LDT_KAGGLE_DATA_DIR")
    if env_root:
        root = Path(env_root)
        candidates.extend([root / name, *root.rglob(name)])
    kaggle_root = Path("/kaggle/input")
    if kaggle_root.exists():
        candidates.extend(kaggle_root.rglob(name))
    unique = sorted({path.resolve() for path in candidates if path.is_file()})
    if len(unique) != 1:
        raise RuntimeError(
            f"Ожидался ровно один {name}; найдено: {len(unique)}. "
            "Прикрепите только нужный private Kaggle Dataset."
        )
    return unique[0]


def load_source_panel(explicit: str | Path | None = None) -> tuple[Any, dict, Path]:
    import polars as pl

    manifest_path = _discover_one("panel_manifest_v2.json", explicit)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("panel_schema_version") != SOURCE_SCHEMA_VERSION:
        raise RuntimeError("Несовместимая версия исходной панели")
    if manifest.get("raw_identifiers_included") is not False:
        raise RuntimeError("Пакет не подтверждает de-identification")
    if manifest.get("contains_2026_rows") is not False:
        raise RuntimeError("2026 запрещён в development-панели")
    data_path = manifest_path.parent / manifest["data_file"]
    if not data_path.is_file():
        raise RuntimeError(f"Не найден файл панели: {data_path.name}")
    if sha256_file(data_path) != manifest.get("data_sha256"):
        raise RuntimeError("Не совпала SHA-256 исходной панели")
    panel = pl.read_parquet(data_path)
    missing = sorted(SOURCE_REQUIRED_COLUMNS - set(panel.columns))
    if missing:
        raise RuntimeError(f"Отсутствуют поля: {missing}")
    if panel.height != int(manifest.get("rows", -1)):
        raise RuntimeError("Число строк не совпало с manifest")
    if panel.select(pl.col("d_year").max()).item() > 2025:
        raise RuntimeError("В панели найдены строки после 2025")
    if {"ид_канала_данных", "ид_объект"} & set(panel.columns):
        raise RuntimeError("Найдены сырые идентификаторы")
    return panel, manifest, manifest_path


def _safe_mean(column: str, alias: str) -> Any:
    import polars as pl

    return pl.col(column).cast(pl.Float64, strict=False).mean().alias(alias)


def _build_object_day(panel: Any) -> Any:
    import polars as pl

    frame = panel.filter(pl.col("d_object_key").is_not_null()).with_columns(
        pl.col("тип_датчика").fill_null("__MISSING__"),
        pl.col("тип_датчика").is_in(sorted(ACCESS_TYPES)).alias("_access"),
        pl.col("тип_датчика").is_in(sorted(FIRE_TYPES)).alias("_fire"),
        pl.col("тип_датчика").is_in(sorted(VENTILATION_TYPES)).alias("_vent"),
        pl.col("тип_датчика").is_in(sorted(FLOOD_TYPES)).alias("_flood"),
        pl.col("тип_датчика").is_in(sorted(PUMP_TYPES)).alias("_pump"),
        pl.col("тип_датчика").is_in(sorted(POWER_TYPES)).alias("_power"),
        (pl.col("d_alarm_count_24h").fill_null(0) > 0).alias("_alarm"),
    )
    grouped = (
        frame.group_by(["d_object_key", "d_cutoff_date"])
        .agg(
            pl.col("d_channel_key").n_unique().alias("d_channel_count"),
            pl.col("тип_датчика").n_unique().alias("d_sensor_type_count"),
            pl.col("d_event_count_24h").sum().alias("d_event_count_sum_24h"),
            pl.col("d_alarm_count_24h").sum().alias("d_alarm_count_sum_24h"),
            _safe_mean("d_alarm_share_24h", "d_alarm_share_mean_24h"),
            pl.col("d_failure_state_event_count_24h").sum().alias(
                "d_failure_state_count_sum_24h"
            ),
            _safe_mean("d_value_numeric_mean_24h", "d_numeric_mean_mean_24h"),
            pl.col("d_value_numeric_min_24h").min().alias("d_numeric_min_24h"),
            pl.col("d_value_numeric_max_24h").max().alias("d_numeric_max_24h"),
            _safe_mean("d_value_numeric_std_24h", "d_numeric_std_mean_24h"),
            pl.col("d_state_n_unique_24h").max().alias("d_state_n_unique_max_24h"),
            _safe_mean("d_gap_days_since_previous", "d_gap_days_mean"),
            pl.col("_access").sum().alias("d_access_channel_count"),
            pl.col("тип_датчика")
            .filter(pl.col("_access") & pl.col("_alarm"))
            .n_unique()
            .alias("d_access_alarm_type_count"),
            pl.col("_fire").sum().alias("d_fire_channel_count"),
            pl.col("тип_датчика")
            .filter(pl.col("_fire") & pl.col("_alarm"))
            .n_unique()
            .alias("d_fire_alarm_type_count"),
            pl.col("d_alarm_count_24h").filter(pl.col("_vent")).sum().alias(
                "d_ventilation_alarm_count_24h"
            ),
            pl.col("_flood").sum().alias("d_flood_channel_count"),
            pl.col("d_alarm_count_24h").filter(pl.col("_flood")).sum().alias(
                "d_flood_alarm_count_24h"
            ),
            pl.col("_pump").sum().alias("d_pump_channel_count"),
            pl.col("d_alarm_count_24h").filter(pl.col("_pump")).sum().alias(
                "d_pump_alarm_count_24h"
            ),
            pl.col("d_alarm_count_24h").filter(pl.col("_power")).sum().alias(
                "d_power_alarm_count_24h"
            ),
            pl.col("d_value_numeric_mean_24h").filter(pl.col("_flood")).mean().alias(
                "d_flood_numeric_mean_24h"
            ),
            pl.col("d_value_numeric_mean_24h").filter(pl.col("_pump")).mean().alias(
                "d_pump_numeric_mean_24h"
            ),
            pl.col("d_catalogue_match").cast(pl.Int8).mean().alias(
                "d_catalogue_match_share"
            ),
        )
        .sort(["d_object_key", "d_cutoff_date"])
        .with_columns(
            (pl.col("d_access_alarm_type_count") >= 2).alias(
                "d_access_corroboration_event"
            ),
            (pl.col("d_fire_alarm_type_count") >= 2).alias(
                "d_fire_corroboration_event"
            ),
            (pl.col("d_alarm_count_sum_24h") > 0).alias("d_any_alarm_event"),
        )
    )
    for event, output in [
        ("d_access_corroboration_event", "d_days_since_access_corroboration"),
        ("d_fire_corroboration_event", "d_days_since_fire_corroboration"),
    ]:
        last = f"_{event}_previous_date"
        grouped = grouped.with_columns(
            pl.when(pl.col(event))
            .then(pl.col("d_cutoff_date"))
            .otherwise(None)
            .shift(1)
            .forward_fill()
            .over("d_object_key")
            .alias(last)
        ).with_columns(
            (pl.col("d_cutoff_date") - pl.col(last)).dt.total_days().alias(output)
        ).drop(last)
    future = grouped.select(
        "d_object_key",
        (pl.col("d_cutoff_date") - pl.duration(days=2)).alias("d_cutoff_date"),
        pl.when(pl.col("d_access_channel_count") > 0)
        .then(pl.col("d_access_corroboration_event").cast(pl.Int8))
        .otherwise(None)
        .alias(ACCESS_TARGET),
        pl.when(pl.col("d_fire_channel_count") > 0)
        .then(pl.col("d_fire_corroboration_event").cast(pl.Int8))
        .otherwise(None)
        .alias(FIRE_TARGET),
        pl.col("d_any_alarm_event").cast(pl.Int8).alias(GENERIC_ALARM_TARGET),
        (pl.col("d_cutoff_date") - pl.duration(days=2)).alias("_score_date"),
    )
    return (
        grouped.join(future, on=["d_object_key", "d_cutoff_date"], how="left")
        .with_columns(
            (pl.col("d_cutoff_date") + pl.duration(days=2)).alias(
                "d_target_start_date"
            ),
            (pl.col("d_cutoff_date") + pl.duration(days=3)).alias(
                "d_target_end_date_exclusive"
            ),
            pl.col("d_cutoff_date").dt.year().alias("d_year"),
        )
        .drop("_score_date")
    )


def _add_dropout_target(panel: Any) -> Any:
    import polars as pl

    keys = ["d_channel_key", "d_object_key", "d_cutoff_date"]
    ordered = panel.select(keys).unique().sort(["d_channel_key", "d_cutoff_date"])
    ordered = ordered.with_columns(
        pl.col("d_cutoff_date").shift(-1).over("d_channel_key").alias("_next1"),
        pl.col("d_cutoff_date").shift(-2).over("d_channel_key").alias("_next2"),
    )
    object_counts = ordered.group_by(["d_object_key", "d_cutoff_date"]).agg(
        pl.col("d_channel_key").n_unique().alias("_object_channels")
    )
    base = ordered.join(object_counts, on=["d_object_key", "d_cutoff_date"], how="left")
    for offset in (2, 3, 4):
        self_future = ordered.select(
            "d_channel_key",
            (pl.col("d_cutoff_date") - pl.duration(days=offset)).alias(
                "d_cutoff_date"
            ),
            pl.lit(1).alias(f"_self_{offset}"),
        )
        object_future = object_counts.select(
            "d_object_key",
            (pl.col("d_cutoff_date") - pl.duration(days=offset)).alias(
                "d_cutoff_date"
            ),
            pl.col("_object_channels").alias(f"_object_channels_{offset}"),
        )
        base = base.join(
            self_future, on=["d_channel_key", "d_cutoff_date"], how="left"
        ).join(object_future, on=["d_object_key", "d_cutoff_date"], how="left")
    next1_days = (pl.col("_next1") - pl.col("d_cutoff_date")).dt.total_days()
    next2_days = (pl.col("_next2") - pl.col("d_cutoff_date")).dt.total_days()
    peer_active = pl.all_horizontal(
        [
            (
                pl.col(f"_object_channels_{offset}").fill_null(0)
                - pl.col(f"_self_{offset}").fill_null(0)
            )
            >= 1
            for offset in (2, 3, 4)
        ]
    )
    silent_three_days = pl.all_horizontal(
        [pl.col(f"_self_{offset}").is_null() for offset in (2, 3, 4)]
    )
    observed_in_window = pl.any_horizontal(
        [pl.col(f"_self_{offset}").is_not_null() for offset in (2, 3, 4)]
    )
    asof_eligible = pl.col("_object_channels") >= 2
    label_resolvable = (
        asof_eligible & (next1_days == 1)
        & peer_active
        & pl.col("_next2").is_not_null()
        & (next2_days <= 31)
    )
    labels = base.select(
        *keys,
        asof_eligible.alias("d_dropout_asof_eligible"),
        pl.when(~label_resolvable)
        .then(None)
        .when(silent_three_days & (next2_days >= 5))
        .then(pl.lit(1))
        .when(observed_in_window)
        .then(pl.lit(0))
        .otherwise(None)
        .cast(pl.Int8)
        .alias(DROPOUT_TARGET),
        peer_active.alias("d_dropout_peer_evidence_complete"),
        next2_days.alias("d_days_to_second_future_observation"),
        (pl.col("d_cutoff_date") + pl.duration(days=2)).alias(
            "d_dropout_target_start_date"
        ),
        (pl.col("d_cutoff_date") + pl.duration(days=5)).alias(
            "d_dropout_target_end_date_exclusive"
        ),
    )
    return panel.join(labels, on=keys, how="left")


def build_missing_target_panels(panel: Any) -> tuple[Any, Any]:
    """Return object-day and channel-element panels using only D-time features."""
    import polars as pl

    object_day = _build_object_day(panel)
    clean_columns = [column for column in panel.columns if column not in LEAKAGE_COLUMNS]
    channel = _add_dropout_target(panel.select(clean_columns))
    labels = object_day.select(
        "d_object_key",
        "d_cutoff_date",
        ACCESS_TARGET,
        FIRE_TARGET,
        GENERIC_ALARM_TARGET,
        "d_access_corroboration_event",
        "d_fire_corroboration_event",
        "d_days_since_access_corroboration",
        "d_days_since_fire_corroboration",
    )
    channel = channel.join(labels, on=["d_object_key", "d_cutoff_date"], how="left")
    assert not (LEAKAGE_COLUMNS & set(channel.columns))
    assert panel.height == channel.height
    return object_day, channel


def export_missing_target_bundle(
    panel: Any,
    source_manifest: dict,
    output_dir: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    import polars as pl

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if config.get("run_mode") == "smoke":
        maximum = panel["d_cutoff_date"].max()
        panel = panel.filter(
            pl.col("d_cutoff_date") >= pl.lit(maximum) - pl.duration(days=180)
        )
    object_day, channel = build_missing_target_panels(panel)
    if config.get("run_mode") == "smoke":
        dates = object_day.select("d_cutoff_date").unique().sort("d_cutoff_date")
        keep_dates = dates.tail(min(120, dates.height))["d_cutoff_date"]
        object_day = object_day.filter(pl.col("d_cutoff_date").is_in(keep_dates))
        channel = channel.filter(pl.col("d_cutoff_date").is_in(keep_dates))
    object_path = output_dir / "object_day_panel_v1.parquet"
    channel_path = output_dir / "object_channel_day_panel_v1.parquet"
    registry_path = output_dir / "missing_target_registry_v1.json"
    object_day.write_parquet(object_path, compression="zstd")
    channel.write_parquet(channel_path, compression="zstd")
    registry = {
        "schema_version": DERIVED_SCHEMA_VERSION,
        "lead_time": "D+1",
        "outcome_day": "D+2",
        "targets": TARGET_REGISTRY,
        "unavailable_confirmed_targets": [
            "confirmed_physical_failure",
            "confirmed_unauthorized_access",
            "confirmed_fire",
            "confirmed_flooding",
            "false_alarm",
            "maintenance_requirement",
        ],
    }
    write_json(registry_path, registry)
    manifest = {
        "schema_version": DERIVED_SCHEMA_VERSION,
        "source_panel_schema_version": source_manifest["panel_schema_version"],
        "source_data_sha256": source_manifest["data_sha256"],
        "run_mode": config.get("run_mode", "full"),
        "contains_2026_rows": False,
        "raw_identifiers_included": False,
        "files": {
            "object_day": object_path.name,
            "channel_element": channel_path.name,
            "registry": registry_path.name,
        },
        "sha256": {
            "object_day": sha256_file(object_path),
            "channel_element": sha256_file(channel_path),
            "registry": sha256_file(registry_path),
        },
        "rows": {"object_day": object_day.height, "channel_element": channel.height},
        "date_min": str(object_day["d_cutoff_date"].min()),
        "date_max": str(object_day["d_cutoff_date"].max()),
        "target_positive_counts": {
            target: int(object_day.select(pl.col(target).sum()).item() or 0)
            for target in (ACCESS_TARGET, FIRE_TARGET)
        }
        | {
            DROPOUT_TARGET: int(channel.select(pl.col(DROPOUT_TARGET).sum()).item() or 0)
        },
        "environment": environment_info(),
    }
    manifest_path = output_dir / "missing_targets_manifest_v1.json"
    write_json(manifest_path, manifest)
    checksum_path = output_dir / "SHA256SUMS.txt"
    checksum_path.write_text(
        "\n".join(
            [
                f"{manifest['sha256']['object_day']}  {object_path.name}",
                f"{manifest['sha256']['channel_element']}  {channel_path.name}",
                f"{manifest['sha256']['registry']}  {registry_path.name}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    audit_path = output_dir / "missing_targets_audit_ru.md"
    audit_path.write_text(_audit_markdown(manifest), encoding="utf-8")
    return manifest


def _audit_markdown(manifest: dict[str, Any]) -> str:
    counts = manifest["target_positive_counts"]
    return f"""# Аудит weak-label целей

Статус: панель собрана, режим `{manifest['run_mode']}`.

- Object-day строк: {manifest['rows']['object_day']:,}
- Channel-element строк: {manifest['rows']['channel_element']:,}
- Период: {manifest['date_min']} — {manifest['date_max']}
- Access corroboration positives: {counts[ACCESS_TARGET]:,}
- Fire corroboration positives: {counts[FIRE_TARGET]:,}
- Temporary dropout positives: {counts[DROPOUT_TARGET]:,}

Все цели — proxy. Они не подтверждают пожар, затопление, несанкционированный доступ или
физический отказ. Пропущенные дни не превращались в отрицательные метки.
"""


def load_missing_target_bundle(
    explicit: str | Path | None = None,
) -> tuple[Any, Any, dict[str, Any], Path]:
    import polars as pl

    manifest_path = _discover_one("missing_targets_manifest_v1.json", explicit)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != DERIVED_SCHEMA_VERSION:
        raise RuntimeError("Несовместимая версия missing-target panel")
    if manifest.get("raw_identifiers_included") is not False:
        raise RuntimeError("Нарушен de-identification contract")
    paths = {
        key: manifest_path.parent / filename for key, filename in manifest["files"].items()
    }
    for key in ("object_day", "channel_element", "registry"):
        if sha256_file(paths[key]) != manifest["sha256"][key]:
            raise RuntimeError(f"Не совпала SHA-256: {key}")
    object_day = pl.read_parquet(paths["object_day"])
    channel = pl.read_parquet(paths["channel_element"])
    if object_day.height != manifest["rows"]["object_day"]:
        raise RuntimeError("Не совпало число object-day строк")
    if channel.height != manifest["rows"]["channel_element"]:
        raise RuntimeError("Не совпало число channel-element строк")
    return object_day, channel, manifest, manifest_path


@dataclass(frozen=True)
class RollingFold:
    name: str
    train_end: date
    calibration_start: date
    calibration_end: date
    validation_start: date
    validation_end: date


ROLLING_FOLDS = [
    RollingFold(
        "fold_2023",
        date(2023, 1, 1),
        date(2023, 1, 1),
        date(2023, 7, 1),
        date(2023, 7, 1),
        date(2024, 1, 1),
    ),
    RollingFold(
        "fold_2024",
        date(2024, 1, 1),
        date(2024, 1, 1),
        date(2024, 7, 1),
        date(2024, 7, 1),
        date(2025, 1, 1),
    ),
]


def rolling_split(
    frame: Any,
    target: str,
    fold: RollingFold,
    start_column: str = "d_target_start_date",
    end_column: str = "d_target_end_date_exclusive",
) -> dict[str, Any]:
    """Split by fully observed target windows; 2021 is never training data."""
    import polars as pl

    labelled = frame.filter(pl.col(target).is_not_null())
    start = pl.col(start_column)
    end = pl.col(end_column)
    cutoff_year = pl.col("d_cutoff_date").dt.year()
    train = labelled.filter((end <= fold.train_end) & (cutoff_year != 2021))
    calibration = labelled.filter(
        (start >= fold.calibration_start) & (end <= fold.calibration_end)
    )
    validation = labelled.filter(
        (start >= fold.validation_start) & (end <= fold.validation_end)
    )
    if min(train.height, calibration.height, validation.height) == 0:
        raise RuntimeError(f"Пустой temporal split: {fold.name}")
    return {"train": train, "calibration": calibration, "validation": validation}


def sample_training_rows(
    frame: Any, target: str, ratio: int, seed: int
) -> tuple[Any, np.ndarray]:
    import polars as pl

    positives = frame.filter(pl.col(target) == 1)
    negatives = frame.filter(pl.col(target) == 0)
    if positives.height == 0:
        raise RuntimeError("В train нет positives")
    keep = min(negatives.height, max(positives.height * ratio, 1))
    sampled_negatives = negatives.sample(n=keep, seed=seed, shuffle=True)
    sampled = pl.concat([positives, sampled_negatives]).sample(
        fraction=1.0, seed=seed, shuffle=True
    )
    negative_probability = keep / max(negatives.height, 1)
    y = sampled[target].to_numpy()
    weights = np.where(y == 1, 1.0, 1.0 / max(negative_probability, 1e-12))
    return sampled, weights.astype(np.float64)


def _finite_probability(values: Sequence[float]) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    return np.clip(np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0), 0, 1)


def fit_platt(raw_probability: Sequence[float], y: Sequence[int]) -> Any:
    from sklearn.linear_model import LogisticRegression

    p = np.clip(np.asarray(raw_probability, dtype=np.float64), 1e-6, 1 - 1e-6)
    labels = np.asarray(y, dtype=np.int8)
    if np.unique(labels).size < 2:
        return {"kind": "identity"}
    logits = np.log(p / (1 - p)).reshape(-1, 1)
    model = LogisticRegression(random_state=0, max_iter=500)
    model.fit(logits, labels)
    return {"kind": "platt", "model": model}


def apply_platt(spec: Any, raw_probability: Sequence[float]) -> np.ndarray:
    p = np.clip(np.asarray(raw_probability, dtype=np.float64), 1e-6, 1 - 1e-6)
    if spec["kind"] == "identity":
        return p
    logits = np.log(p / (1 - p)).reshape(-1, 1)
    return _finite_probability(spec["model"].predict_proba(logits)[:, 1])


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = len(y)
    error = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (p >= left) & (p < right if right < 1 else p <= right)
        if mask.any():
            error += mask.mean() * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(error)


def threshold_for_precision(y: np.ndarray, p: np.ndarray, minimum: float) -> float:
    from sklearn.metrics import precision_recall_curve

    if np.unique(y).size < 2:
        return 1.0
    precision, recall, thresholds = precision_recall_curve(y, p)
    candidates = [
        (float(recall[index]), float(thresholds[index]))
        for index in range(len(thresholds))
        if precision[index] >= minimum
    ]
    return max(candidates, default=(0.0, 1.0))[1]


def _top_budget_mask(dates: np.ndarray, probability: np.ndarray, budget: int) -> np.ndarray:
    mask = np.zeros(len(probability), dtype=bool)
    for current in np.unique(dates):
        indices = np.flatnonzero(dates == current)
        selected = indices[np.argsort(-probability[indices], kind="stable")[:budget]]
        mask[selected] = True
    return mask


def episode_metrics(
    frame: Any,
    target: str,
    probability: Sequence[float],
    budget: int,
    cooldown_hours: int,
    threshold: float | None = None,
    entity_column: str = "d_object_key",
) -> dict[str, Any]:
    import pandas as pd

    columns = [entity_column, "d_cutoff_date", "d_target_start_date", target]
    data = pd.DataFrame(frame.select(columns).to_dict(as_series=False))
    data["probability"] = _finite_probability(probability)
    data["d_cutoff_date"] = pd.to_datetime(data["d_cutoff_date"])
    data["d_target_start_date"] = pd.to_datetime(data["d_target_start_date"])
    top = _top_budget_mask(
        data["d_cutoff_date"].dt.date.to_numpy(), data["probability"].to_numpy(), budget
    )
    if threshold is not None:
        top &= data["probability"].to_numpy() >= threshold
    alerts = data.loc[top].sort_values(["d_cutoff_date", "probability"], ascending=[True, False])
    cooldown = timedelta(hours=int(cooldown_hours))
    accepted: list[int] = []
    last: dict[str, Any] = {}
    for index, row in alerts.iterrows():
        entity = row[entity_column]
        if entity not in last or row["d_cutoff_date"] - last[entity] >= cooldown:
            accepted.append(index)
            last[entity] = row["d_cutoff_date"]
    accepted_frame = data.loc[accepted]
    unresolved_alerts = int(accepted_frame[target].isna().sum())
    events = data.loc[data[target] == 1, [entity_column, "d_target_start_date"]].drop_duplicates()
    event_set = set(map(tuple, events.to_numpy()))
    matched: set[tuple[Any, Any]] = set()
    for _, row in accepted_frame.iterrows():
        key = (row[entity_column], row["d_target_start_date"])
        if key in event_set:
            matched.add(key)
    n_alerts = len(accepted_frame)
    n_events = len(event_set)
    return {
        "alert_episodes": n_alerts,
        "proxy_episodes": n_events,
        "matched_episodes": len(matched),
        "unresolved_alert_episodes": unresolved_alerts,
        "known_negative_alert_episodes": n_alerts - len(matched) - unresolved_alerts,
        "precision": float(len(matched) / n_alerts) if n_alerts else 0.0,
        "recall": float(len(matched) / n_events) if n_events else 0.0,
        "alert_budget_per_day": budget,
        "cooldown_hours": cooldown_hours,
    }


def score_predictions(
    frame: Any,
    target: str,
    probability: Sequence[float],
    threshold: float,
    config: dict[str, Any],
    entity_column: str = "d_object_key",
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss

    y = frame[target].to_numpy().astype(np.int8)
    p = _finite_probability(probability)
    pred = p >= threshold
    positives = int(y.sum())
    pr_auc = (
        float(average_precision_score(y, p))
        if positives >= int(config.get("min_positives_for_pr_auc", 20))
        else None
    )
    tp = int(((y == 1) & pred).sum())
    fp = int(((y == 0) & pred).sum())
    episodes = episode_metrics(
        frame,
        target,
        p,
        int(config.get("alert_budget_per_day", 50)),
        int(config.get("cooldown_hours", 72)),
        None,
        entity_column,
    )
    operational_false_alerts = episodes["alert_episodes"] - episodes["matched_episodes"]
    return {
        "rows": len(y),
        "positives": positives,
        "prevalence": float(y.mean()) if len(y) else None,
        "pr_auc": pr_auc,
        "pr_auc_status": "reported" if pr_auc is not None else "not_evaluable_lt_20_positives",
        "brier_score": float(brier_score_loss(y, p)),
        "ece_10_bins": expected_calibration_error(y, p),
        "threshold": float(threshold),
        "precision": float(tp / max(tp + fp, 1)),
        "recall": float(tp / max(positives, 1)),
        "false_alerts_per_1000_eligible_days": float(1000 * fp / max(len(y), 1)),
        "operational_false_alerts_per_1000_eligible_days": float(
            1000 * operational_false_alerts / max(len(y), 1)
        ),
        "episodes": episodes,
    }


def date_block_bootstrap_difference(
    frame: Any,
    target: str,
    candidate: Sequence[float],
    reference: Sequence[float],
    repeats: int,
    seed: int,
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score

    y = frame[target].to_numpy().astype(np.int8)
    dates = frame["d_cutoff_date"].to_numpy()
    candidate = _finite_probability(candidate)
    reference = _finite_probability(reference)
    unique_dates = np.unique(dates)
    blocks = [unique_dates[index : index + 7] for index in range(0, len(unique_dates), 7)]
    indices_by_block = [np.flatnonzero(np.isin(dates, block)) for block in blocks]
    rng = np.random.default_rng(seed)
    differences: list[float] = []
    for _ in range(repeats):
        selected = rng.integers(0, len(indices_by_block), len(indices_by_block))
        indices = np.concatenate([indices_by_block[index] for index in selected])
        if np.unique(y[indices]).size < 2:
            continue
        differences.append(
            float(average_precision_score(y[indices], candidate[indices]))
            - float(average_precision_score(y[indices], reference[indices]))
        )
    if not differences:
        return {"status": "not_evaluable", "reason": "bootstrap_has_one_class"}
    values = np.asarray(differences)
    return {
        "status": "ok",
        "mean_difference": float(values.mean()),
        "ci95_low": float(np.quantile(values, 0.025)),
        "ci95_high": float(np.quantile(values, 0.975)),
        "repeats_finite": len(values),
        "method": "paired seven-day date blocks",
    }


def date_block_bootstrap_episode_difference(
    frame: Any,
    target: str,
    candidate: Sequence[float],
    reference: Sequence[float],
    repeats: int,
    seed: int,
    budget: int,
    cooldown_hours: int,
    entity_column: str,
) -> dict[str, Any]:
    """Paired block bootstrap of the actual operational episode policy.

    Metrics are first recomputed independently inside seven-day blocks. This
    deliberately censors cooldown and episode matching at block boundaries;
    both candidates receive the same boundaries and sampled blocks.
    """
    dates = frame["d_cutoff_date"].to_numpy()
    unique_dates = np.unique(dates)
    blocks = [unique_dates[index : index + 7] for index in range(0, len(unique_dates), 7)]
    candidate = _finite_probability(candidate)
    reference = _finite_probability(reference)
    contributions: list[dict[str, tuple[int, int, int]]] = []
    for block in blocks:
        indices = np.flatnonzero(np.isin(dates, block))
        block_frame = frame[indices.tolist()]
        item: dict[str, tuple[int, int, int]] = {}
        for name, probability in (("candidate", candidate), ("reference", reference)):
            metric = episode_metrics(
                block_frame,
                target,
                probability[indices],
                budget,
                cooldown_hours,
                None,
                entity_column,
            )
            item[name] = (
                int(metric["matched_episodes"]),
                int(metric["proxy_episodes"]),
                int(metric["alert_episodes"]),
            )
        contributions.append(item)
    rng = np.random.default_rng(seed)
    recall_difference: list[float] = []
    precision_difference: list[float] = []
    for _ in range(repeats):
        selected = rng.integers(0, len(contributions), len(contributions))
        values: dict[str, tuple[float, float]] = {}
        for name in ("candidate", "reference"):
            matched = sum(contributions[index][name][0] for index in selected)
            events = sum(contributions[index][name][1] for index in selected)
            alerts = sum(contributions[index][name][2] for index in selected)
            values[name] = (
                matched / events if events else float("nan"),
                matched / alerts if alerts else float("nan"),
            )
        if np.isfinite(values["candidate"][0]) and np.isfinite(values["reference"][0]):
            recall_difference.append(values["candidate"][0] - values["reference"][0])
        if np.isfinite(values["candidate"][1]) and np.isfinite(values["reference"][1]):
            precision_difference.append(values["candidate"][1] - values["reference"][1])

    def interval(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"status": "not_evaluable", "reason": "bootstrap_has_no_events"}
        array = np.asarray(values)
        return {
            "status": "ok",
            "mean_difference": float(array.mean()),
            "ci95_low": float(np.quantile(array, 0.025)),
            "ci95_high": float(np.quantile(array, 0.975)),
            "repeats_finite": len(array),
        }

    return {
        "episode_recall": interval(recall_difference),
        "episode_precision": interval(precision_difference),
        "method": "paired bootstrap of seven-day blocks; block boundaries censored",
    }


FLOOD_FEATURES = [
    "d_flood_channel_count",
    "d_flood_alarm_count_24h",
    "d_flood_numeric_mean_24h",
    "d_pump_channel_count",
    "d_pump_alarm_count_24h",
    "d_pump_numeric_mean_24h",
    "d_power_alarm_count_24h",
    "d_event_count_sum_24h",
    "d_alarm_count_sum_24h",
    "d_alarm_share_mean_24h",
    "d_gap_days_mean",
]


def _unlabelled_split(frame: Any, fold: RollingFold) -> dict[str, Any]:
    import polars as pl

    start = pl.col("d_target_start_date")
    end = pl.col("d_target_end_date_exclusive")
    year = pl.col("d_cutoff_date").dt.year()
    return {
        "train": frame.filter((end <= fold.train_end) & (year != 2021)),
        "calibration": frame.filter(
            (start >= fold.calibration_start) & (end <= fold.calibration_end)
        ),
        "validation": frame.filter(
            (start >= fold.validation_start) & (end <= fold.validation_end)
        ),
    }


def _robust_fit(frame: Any, features: Sequence[str]) -> dict[str, np.ndarray]:
    values = frame.select(features).to_numpy().astype(np.float64)
    median = np.zeros(values.shape[1], dtype=np.float64)
    scale = np.ones(values.shape[1], dtype=np.float64)
    for index in range(values.shape[1]):
        finite = values[np.isfinite(values[:, index]), index]
        if len(finite):
            median[index] = float(np.median(finite))
            spread = float(np.quantile(finite, 0.75) - np.quantile(finite, 0.25))
            scale[index] = spread if spread >= 1e-6 else 1.0
    return {"median": median, "scale": scale}


def _robust_apply(frame: Any, features: Sequence[str], spec: dict[str, np.ndarray]) -> np.ndarray:
    values = frame.select(features).to_numpy().astype(np.float64)
    values = np.where(np.isfinite(values), values, spec["median"])
    return np.clip((values - spec["median"]) / spec["scale"], -20, 20).astype(
        np.float32
    )


def _flood_rule_score(x: np.ndarray, features: Sequence[str]) -> np.ndarray:
    index = {name: position for position, name in enumerate(features)}
    flood_alarm = np.maximum(x[:, index["d_flood_alarm_count_24h"]], 0)
    pump_alarm = np.maximum(x[:, index["d_pump_alarm_count_24h"]], 0)
    power_alarm = np.maximum(x[:, index["d_power_alarm_count_24h"]], 0)
    flood_value = np.abs(x[:, index["d_flood_numeric_mean_24h"]])
    pump_value = np.abs(x[:, index["d_pump_numeric_mean_24h"]])
    cadence = np.maximum(x[:, index["d_gap_days_mean"]], 0)
    raw = np.maximum.reduce(
        [
            flood_alarm + 0.5 * np.maximum(pump_alarm, pump_value),
            flood_value + 0.5 * np.maximum(-pump_alarm, 0),
            0.7 * np.abs(flood_value - pump_value) + 0.3 * (power_alarm + cadence),
        ]
    )
    return 1.0 / (1.0 + np.exp(-np.clip(raw, -20, 20)))


def _fit_autoencoder(
    train_x: np.ndarray, config: dict[str, Any]
) -> tuple[Any, str]:
    """Fit a denoising autoencoder in full mode; PCA is smoke-only."""
    if config.get("run_mode") == "smoke":
        from sklearn.decomposition import PCA

        components = max(1, min(train_x.shape[1] // 2, train_x.shape[0] - 1))
        model = PCA(n_components=components, random_state=config.get("random_seed", 0))
        model.fit(train_x)
        return model, "smoke_pca_contract_surrogate"
    import torch
    from torch import nn

    if not torch.cuda.is_available():
        raise RuntimeError("FULL notebook 10 требует Kaggle NVIDIA GPU")
    device = torch.device("cuda")
    torch.manual_seed(int(config.get("random_seed", 0)))

    class Autoencoder(nn.Module):
        def __init__(self, width: int) -> None:
            super().__init__()
            hidden = max(8, width * 2)
            latent = max(3, width // 2)
            self.encoder = nn.Sequential(nn.Linear(width, hidden), nn.ReLU(), nn.Linear(hidden, latent))
            self.decoder = nn.Sequential(nn.Linear(latent, hidden), nn.ReLU(), nn.Linear(hidden, width))

        def forward(self, values: Any) -> Any:
            return self.decoder(self.encoder(values))

    model = Autoencoder(train_x.shape[1]).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    values = torch.tensor(train_x, dtype=torch.float32)
    dataset = torch.utils.data.TensorDataset(values)
    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=int(config.get("batch_size", 2048)),
        shuffle=True,
        drop_last=False,
    )
    model.train()
    for _ in range(int(config.get("epochs", 12))):
        for (batch,) in loader:
            batch = batch.to(device)
            noisy = batch + 0.03 * torch.randn_like(batch)
            loss = ((model(noisy) - batch) ** 2).mean()
            optimiser.zero_grad(set_to_none=True)
            loss.backward()
            optimiser.step()
    model.eval()
    return model, "type_conditioned_denoising_autoencoder"


def _autoencoder_score(model: Any, kind: str, x: np.ndarray) -> np.ndarray:
    if kind == "smoke_pca_contract_surrogate":
        reconstructed = model.inverse_transform(model.transform(x))
        return np.mean((x - reconstructed) ** 2, axis=1)
    import torch

    device = next(model.parameters()).device
    scores: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(x), 8192):
            batch = torch.tensor(x[start : start + 8192], dtype=torch.float32, device=device)
            scores.append(((model(batch) - batch) ** 2).mean(dim=1).cpu().numpy())
    return np.concatenate(scores)


def _budget_threshold(dates: np.ndarray, score: np.ndarray, budget: int) -> float:
    selected = _top_budget_mask(dates, score, budget)
    return float(np.min(score[selected])) if selected.any() else math.inf


def _synthetic_flood_challenge(
    validation: Any,
    x: np.ndarray,
    features: Sequence[str],
    count_per_family: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Inject only relative feature changes into copies of real validation rows."""
    rng = np.random.default_rng(seed)
    index = {name: position for position, name in enumerate(features)}
    eligible = np.flatnonzero(validation["d_flood_channel_count"].to_numpy() > 0)
    if len(eligible) < 10:
        return (
            np.empty((0, x.shape[1]), dtype=np.float32),
            np.array([], dtype=object),
            np.array([]),
            np.array([], dtype=object),
        )
    rows: list[np.ndarray] = []
    families: list[str] = []
    severities: list[float] = []
    challenge_dates: list[Any] = []
    validation_dates = validation["d_cutoff_date"].to_numpy()
    for family in range(3):
        chosen = rng.choice(eligible, size=count_per_family, replace=True)
        copies = x[chosen].copy()
        severity = rng.uniform(1.0, 5.0, size=count_per_family).astype(np.float32)
        noise = rng.normal(0, 0.15, size=copies.shape).astype(np.float32)
        copies += noise
        if family == 0:
            copies[:, index["d_flood_alarm_count_24h"]] += severity
            copies[:, index["d_pump_alarm_count_24h"]] += 0.7 * severity
        elif family == 1:
            copies[:, index["d_flood_numeric_mean_24h"]] += severity
            copies[:, index["d_pump_alarm_count_24h"]] -= 0.5 * severity
        else:
            copies[:, index["d_flood_numeric_mean_24h"]] += severity
            copies[:, index["d_pump_numeric_mean_24h"]] -= severity
            copies[:, index["d_gap_days_mean"]] += 0.5 * severity
            copies[:, index["d_power_alarm_count_24h"]] += 0.3 * severity
        missing = rng.random(copies.shape) < rng.uniform(0.0, 0.08, size=(len(copies), 1))
        copies[missing] = 0.0
        rows.append(copies)
        families.extend([f"scenario_{family + 1}"] * count_per_family)
        severities.extend(severity.tolist())
        challenge_dates.extend(validation_dates[chosen].tolist())
    return (
        np.vstack(rows),
        np.asarray(families),
        np.asarray(severities),
        np.asarray(challenge_dates),
    )


def run_flood_synthetic_challenge(
    object_day: Any,
    manifest: dict[str, Any],
    config: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    import polars as pl

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "status": "completed",
        "run_mode": config.get("run_mode", "full"),
        "comparability": "non_comparable_smoke" if config.get("run_mode") == "smoke" else "comparable_within_target",
        "target_code": "flood_synthetic_scenario",
        "score_kind": "synthetic_scenario_match",
        "evidence_level": "E4",
        "real_flood_probability_reported": False,
        "real_pr_auc_reported": False,
        "source_manifest_sha256": manifest["sha256"],
        "environment": environment_info(),
        "folds": {},
    }
    prediction_parts: list[Any] = []
    for fold_index, fold in enumerate(ROLLING_FOLDS):
        split = _unlabelled_split(object_day, fold)
        if config.get("run_mode") == "smoke":
            split = {key: value.tail(min(value.height, 4000)) for key, value in split.items()}
        background = split["train"].filter(
            (pl.col("d_flood_alarm_count_24h").fill_null(0) == 0)
            & (pl.col("d_pump_alarm_count_24h").fill_null(0) == 0)
        )
        if background.height < 20:
            background = split["train"]
        robust = _robust_fit(background, FLOOD_FEATURES)
        train_x = _robust_apply(background, FLOOD_FEATURES, robust)
        cal_x = _robust_apply(split["calibration"], FLOOD_FEATURES, robust)
        val_x = _robust_apply(split["validation"], FLOOD_FEATURES, robust)
        model, model_kind = _fit_autoencoder(train_x, config)
        scores = {
            "robust_rule": {
                "calibration": _flood_rule_score(cal_x, FLOOD_FEATURES),
                "validation": _flood_rule_score(val_x, FLOOD_FEATURES),
            },
            "autoencoder": {
                "calibration": _autoencoder_score(model, model_kind, cal_x),
                "validation": _autoencoder_score(model, model_kind, val_x),
            },
        }
        synthetic_x, families, severity, synthetic_dates = _synthetic_flood_challenge(
            split["validation"],
            val_x,
            FLOOD_FEATURES,
            int(config.get("synthetic_count_per_family", 500)),
            int(config.get("random_seed", 0)) + fold_index,
        )
        fold_result: dict[str, Any] = {
            "rows": {key: value.height for key, value in split.items()},
            "synthetic_rows": len(synthetic_x),
            "synthetic_support_status": "ok" if len(synthetic_x) else "not_evaluable_no_flood_sensor_support",
            "models": {},
        }
        cal_dates = split["calibration"]["d_cutoff_date"].to_numpy()
        val_dates = split["validation"]["d_cutoff_date"].to_numpy()
        for name, values in scores.items():
            threshold = _budget_threshold(
                cal_dates,
                values["calibration"],
                int(config.get("alert_budget_per_day", 50)),
            )
            real_alert = values["validation"] >= threshold
            model_result: dict[str, Any] = {
                "model_kind": model_kind if name == "autoencoder" else "deterministic_relative_rule",
                "threshold_from_real_calibration": threshold,
                "real_validation_rows": len(real_alert),
                "real_false_alerts": int(real_alert.sum()),
                "real_false_alerts_per_1000_object_days": float(1000 * real_alert.mean()),
                "real_alerts_per_day": float(
                    real_alert.sum() / max(len(np.unique(val_dates)), 1)
                ),
                "real_pr_auc": None,
            }
            if len(synthetic_x):
                synthetic_score = (
                    _flood_rule_score(synthetic_x, FLOOD_FEATURES)
                    if name == "robust_rule"
                    else _autoencoder_score(model, model_kind, synthetic_x)
                )
                model_result["synthetic_sensitivity"] = float((synthetic_score >= threshold).mean())
                combined_dates = np.concatenate([val_dates, synthetic_dates])
                combined_score = np.concatenate([values["validation"], synthetic_score])
                selected_at_budget = _top_budget_mask(
                    combined_dates,
                    combined_score,
                    int(config.get("alert_budget_per_day", 50)),
                )
                model_result["synthetic_recall_at_50_per_day"] = float(
                    selected_at_budget[len(val_dates) :].mean()
                )
                model_result["synthetic_sensitivity_by_family"] = {
                    family: float((synthetic_score[families == family] >= threshold).mean())
                    for family in sorted(set(families))
                }
                model_result["synthetic_sensitivity_by_severity"] = {
                    "low_1_2": float((synthetic_score[severity < 2] >= threshold).mean()) if (severity < 2).any() else None,
                    "medium_2_4": float((synthetic_score[(severity >= 2) & (severity < 4)] >= threshold).mean()) if ((severity >= 2) & (severity < 4)).any() else None,
                    "high_4_5": float((synthetic_score[severity >= 4] >= threshold).mean()) if (severity >= 4).any() else None,
                }
            fold_result["models"][name] = model_result
        # Prefer lower real alert burden, then higher synthetic sensitivity; this is not incident-model selection.
        budget = int(config.get("alert_budget_per_day", 50))
        supported_models = [
            (name, values)
            for name, values in fold_result["models"].items()
            if values.get("synthetic_sensitivity") is not None
        ]
        eligible_models = [
            item
            for item in supported_models
            if item[1]["real_alerts_per_day"] <= budget * 1.2
        ]
        selected = (
            max(
                eligible_models,
                key=lambda item: (
                    item[1]["synthetic_recall_at_50_per_day"],
                    item[1]["synthetic_sensitivity"],
                    -item[1]["real_false_alerts_per_1000_object_days"],
                    item[0] == "robust_rule",
                ),
            )[0]
            if eligible_models
            else (
                min(
                    supported_models,
                    key=lambda item: item[1]["real_alerts_per_day"],
                )[0]
                if supported_models
                else "none"
            )
        )
        fold_result["selection_gate"] = {
            "real_alerts_per_day_max": budget * 1.2,
            "status": (
                "passed"
                if eligible_models
                else ("failed_alert_budget" if supported_models else "not_evaluable")
            ),
        }
        fold_result["selected_detector"] = selected
        results["folds"][fold.name] = fold_result
        if selected != "none":
            score = scores[selected]["validation"]
            selected_threshold = fold_result["models"][selected]["threshold_from_real_calibration"]
            prediction_parts.append(
                split["validation"].select(
                    "d_object_key", "d_cutoff_date", "d_target_start_date", "d_target_end_date_exclusive"
                ).with_columns(
                    pl.Series("selected_score", score),
                    pl.lit(fold.name).alias("fold"),
                    pl.lit(selected).alias("selected_model"),
                    pl.lit("synthetic_scenario_match").alias("score_kind"),
                    pl.lit("E4").alias("evidence_level"),
                    pl.Series("decision_status", np.where(score >= selected_threshold, "scenario_match", "background_like")),
                )
            )
    results["selection"] = {
        "status": "synthetic_detector_only",
        "backend_incident_model_allowed": False,
        "reason_codes": ["NO_REAL_FLOOD_LABEL", "E4_SYNTHETIC_CHALLENGE_ONLY"],
    }
    result_path = write_json(output_dir / "results_flood_missing_target.json", results)
    if prediction_parts:
        pl.concat(prediction_parts, how="vertical_relaxed").write_parquet(
            output_dir / "predictions_flood_missing_target.parquet", compression="zstd"
        )
    (output_dir / "summary_flood_missing_target_ru.md").write_text(
        _flood_summary(results), encoding="utf-8"
    )
    return results


def _flood_summary(results: dict[str, Any]) -> str:
    lines = [
        "# Синтетический flooding challenge",
        "",
        "Это E4 scenario-match, а не вероятность затопления. Real PR-AUC не рассчитывался.",
        "",
    ]
    for fold, payload in results["folds"].items():
        lines.append(f"## {fold}")
        lines.append("")
        lines.append(f"Synthetic rows: {payload['synthetic_rows']}; selected: `{payload['selected_detector']}`.")
        for name, metric in payload["models"].items():
            lines.append(
                f"- {name}: real false alerts/1000 = {metric['real_false_alerts_per_1000_object_days']:.2f}; "
                f"synthetic sensitivity = {metric.get('synthetic_sensitivity', 'not_evaluable')}; "
                f"synthetic Recall@50/day = {metric.get('synthetic_recall_at_50_per_day', 'not_evaluable')}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


SCENARIO_GENERATOR_VERSION = "scenario-temporal-1.0"
SCENARIO_SPECS = {
    "access": {
        "direction": "access",
        "support": "d_access_channel_count",
        "features": ["d_access_alarm_type_count", "d_alarm_count_sum_24h", "d_state_n_unique_max_24h", "d_gap_days_mean"],
        "families": [
            ("d_access_alarm_type_count", "d_alarm_count_sum_24h"),
            ("d_state_n_unique_max_24h", "d_access_alarm_type_count"),
            ("d_gap_days_mean", "d_alarm_count_sum_24h"),
        ],
    },
    "fire": {
        "direction": "fire",
        "support": "d_fire_channel_count",
        "features": ["d_fire_alarm_type_count", "d_alarm_count_sum_24h", "d_ventilation_alarm_count_24h", "d_numeric_max_24h", "d_gap_days_mean"],
        "families": [
            ("d_fire_alarm_type_count", "d_alarm_count_sum_24h"),
            ("d_numeric_max_24h", "d_ventilation_alarm_count_24h"),
            ("d_gap_days_mean", "d_fire_alarm_type_count", "d_numeric_max_24h"),
        ],
    },
    "flood": {
        "support": "d_flood_channel_count",
        "features": ["d_flood_alarm_count_24h", "d_flood_numeric_mean_24h", "d_pump_alarm_count_24h", "d_pump_numeric_mean_24h", "d_power_alarm_count_24h", "d_gap_days_mean"],
        "families": [
            ("d_flood_alarm_count_24h", "d_pump_alarm_count_24h"),
            ("d_flood_numeric_mean_24h", "d_pump_numeric_mean_24h"),
            ("d_gap_days_mean", "d_power_alarm_count_24h", "d_flood_numeric_mean_24h"),
        ],
    },
}


def _scenario_history(frame: Any, features: Sequence[str]) -> Any:
    """Attach only the preceding two observed calendar days to each D row."""
    import polars as pl

    result = frame.with_columns([pl.col(name).alias(f"lag0_{name}") for name in features])
    for lag in (1, 2):
        past = frame.select(
            "d_object_key",
            (pl.col("d_cutoff_date") + pl.duration(days=lag)).alias("d_cutoff_date"),
            *[pl.col(name).alias(f"lag{lag}_{name}") for name in features],
            pl.lit(True).alias(f"lag{lag}_observed"),
        )
        result = result.join(past, on=["d_object_key", "d_cutoff_date"], how="left")
    return result


def _scenario_inject(
    x: np.ndarray, available: np.ndarray, eligible: np.ndarray, features: Sequence[str],
    families: Sequence[Sequence[str]], family_indices: Sequence[int], count: int, seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Perturb causal three-day feature histories; never assign incident labels."""
    rng = np.random.default_rng(seed)
    if len(eligible) == 0 or count <= 0:
        return (
            np.empty((0, x.shape[1]), dtype=np.float32), np.array([], dtype=np.int8),
            np.array([]), np.array([], dtype=np.int64),
        )
    output: list[np.ndarray] = []
    labels: list[int] = []
    severities: list[float] = []
    source_indices: list[np.ndarray] = []
    index = {name: position for position, name in enumerate(features)}
    for family in family_indices:
        chosen = rng.choice(eligible, size=count, replace=True)
        source_indices.append(chosen)
        copies = x[chosen].copy()
        severity = rng.uniform(0.7, 4.0, size=count)
        for row in range(count):
            observed_lags = np.flatnonzero(available[chosen[row]])
            duration = int(rng.integers(1, len(observed_lags) + 1))
            first = int(rng.integers(0, len(observed_lags) - duration + 1))
            for lag in observed_lags[first : first + duration]:
                for signal in families[family]:
                    column = index[f"lag{lag}_{signal}"]
                    direction = -1 if signal == "d_pump_numeric_mean_24h" else 1
                    copies[row, column] += direction * severity[row] * rng.uniform(0.5, 1.1)
        copies += rng.normal(0, 0.12, size=copies.shape)
        missing = rng.random(copies.shape) < rng.uniform(0, 0.06, size=(count, 1))
        copies[missing] = 0
        output.append(copies.astype(np.float32))
        labels.extend([family] * count)
        severities.extend(severity.tolist())
    return (
        np.vstack(output), np.asarray(labels, dtype=np.int8),
        np.asarray(severities), np.concatenate(source_indices),
    )


def _scenario_rule(x: np.ndarray, feature_names: Sequence[str], families: Sequence[Sequence[str]]) -> np.ndarray:
    index = {name: position for position, name in enumerate(feature_names)}
    signals = sorted({name for family in families for name in family})
    current = np.stack([np.maximum(x[:, index[f"lag0_{name}"]], 0) for name in signals], axis=1)
    ranked = np.sort(current, axis=1)
    return _finite_probability(1 - np.exp(-np.maximum(ranked[:, -1] + ranked[:, -2], 0) / 5))


def _scenario_anomaly(x: np.ndarray) -> np.ndarray:
    return _finite_probability(1 - np.exp(-np.linalg.norm(np.clip(x, -10, 10), axis=1) / max(x.shape[1], 1)))


def run_multitarget_synthetic_challenge(
    object_day: Any, manifest: dict[str, Any], config: dict[str, Any], output_dir: str | Path,
) -> dict[str, Any]:
    """Train on generated patterns, test unseen families and real alert burden."""
    import polars as pl
    from sklearn.linear_model import LogisticRegression

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    count = int(config.get("synthetic_count_per_family", 500))
    budget = int(config.get("alert_budget_per_day", 5))
    if budget <= 0 or budget >= 25:
        raise ValueError("Synthetic challenge requires a non-saturated budget in 1..24")
    for task, spec in SCENARIO_SPECS.items():
        features = [f"lag{lag}_{name}" for lag in (0, 1, 2) for name in spec["features"]]
        history = _scenario_history(object_day, spec["features"]).filter(
            pl.col(spec["support"]).fill_null(0) > 0
        )
        payload: dict[str, Any] = {
            "status": "completed", "run_mode": config.get("run_mode", "full"),
            "comparability": "non_comparable_smoke" if config.get("run_mode") == "smoke" else "comparable_within_target",
            "target_code": f"{task}_synthetic_scenario",
            "score_kind": "synthetic_scenario_match", "evidence_level": "E4",
            "generator_version": SCENARIO_GENERATOR_VERSION,
            "source_manifest_sha256": manifest["sha256"],
            "config": {
                "alert_budget_per_day_max": budget,
                "synthetic_count_per_family": count,
                "random_seed": int(config.get("random_seed", 0)),
            },
            "real_incident_probability_reported": False, "real_pr_auc_reported": False,
            "folds": {},
        }
        predictions: list[Any] = []
        last_artifact: dict[str, Any] | None = None
        for fold_index, fold in enumerate(ROLLING_FOLDS):
            split = _unlabelled_split(history, fold)
            all_validation_rows = _unlabelled_split(object_day, fold)["validation"].height
            if config.get("run_mode") == "smoke":
                split = {key: value.tail(min(value.height, 1500)) for key, value in split.items()}
            if min(value.height for value in split.values()) == 0:
                raise RuntimeError(f"{task}: пустой temporal split для поддерживаемых объектов")
            daily_counts = split["calibration"].group_by("d_cutoff_date").len()["len"].to_numpy()
            effective_budget = min(budget, max(1, int(np.floor(0.1 * np.median(daily_counts)))))
            budget_saturation = float(effective_budget / max(np.median(daily_counts), 1))
            robust = _robust_fit(split["train"], features)
            arrays = {key: _robust_apply(value, features, robust) for key, value in split.items()}
            availability = {
                key: np.column_stack([
                    np.ones(value.height, dtype=bool),
                    value["lag1_observed"].fill_null(False).to_numpy(),
                    value["lag2_observed"].fill_null(False).to_numpy(),
                ])
                for key, value in split.items()
            }
            train_eligible = np.arange(split["train"].height)
            val_eligible = np.arange(split["validation"].height)
            synthetic_train, _, _, _ = _scenario_inject(
                arrays["train"], availability["train"], train_eligible, features, spec["families"], (0, 1),
                count, int(config.get("random_seed", 0)) + fold_index,
            )
            challenge, family, severity, challenge_source_indices = _scenario_inject(
                arrays["validation"], availability["validation"], val_eligible, features, spec["families"], (0, 1, 2),
                count, int(config.get("random_seed", 0)) + 100 + fold_index,
            )
            real_sample = arrays["train"][np.random.default_rng(fold_index).choice(
                len(arrays["train"]), size=len(synthetic_train), replace=True,
            )] if len(synthetic_train) else np.empty((0, len(features)))
            learned = None
            if len(synthetic_train) and len(challenge):
                learned = LogisticRegression(max_iter=500, C=0.2, class_weight="balanced")
                learned.fit(
                    np.vstack([real_sample, synthetic_train]),
                    np.r_[np.zeros(len(real_sample)), np.ones(len(synthetic_train))],
                )
            model_scores: dict[str, dict[str, np.ndarray]] = {}
            for name in ("rule", "robust_anomaly", "learned_logistic"):
                if name == "learned_logistic" and learned is None:
                    continue
                scorer = (
                    (lambda values: _scenario_rule(values, features, spec["families"])) if name == "rule"
                    else (_scenario_anomaly if name == "robust_anomaly" else
                          (lambda values: _finite_probability(learned.predict_proba(values)[:, 1])))
                )
                model_scores[name] = {key: scorer(arrays[key]) for key in ("calibration", "validation")}
                model_scores[name]["challenge"] = scorer(challenge) if len(challenge) else np.array([])
            fold_metrics: dict[str, Any] = {}
            cal_dates = split["calibration"]["d_cutoff_date"].to_numpy()
            val_dates = split["validation"]["d_cutoff_date"].to_numpy()
            challenge_dates = val_dates[challenge_source_indices]
            for name, scores in model_scores.items():
                threshold = float(np.quantile(scores["calibration"], 0.90))
                real_mask = _top_budget_mask(val_dates, scores["validation"], effective_budget) & (scores["validation"] > threshold)
                synthetic_mask = np.zeros(len(challenge), dtype=bool)
                if len(challenge):
                    combined_dates = np.r_[val_dates, challenge_dates]
                    combined = np.r_[scores["validation"], scores["challenge"]]
                    synthetic_mask = (_top_budget_mask(combined_dates, combined, effective_budget) & (combined > threshold))[len(val_dates):]
                holdout = family == 2
                fold_metrics[name] = {
                    "threshold_from_real_calibration": threshold,
                    "real_background_alerts_per_1000": float(1000 * real_mask.mean()),
                    "real_alerts_per_day": float(real_mask.sum() / max(len(np.unique(val_dates)), 1)),
                    "synthetic_sensitivity_by_family": {
                        str(i): float(synthetic_mask[family == i].mean()) if (family == i).any() else None
                        for i in range(3)
                    },
                    "heldout_family_recall_at_budget": float(synthetic_mask[holdout].mean()) if holdout.any() else None,
                    "synthetic_sensitivity_by_severity": {
                        "low": float(synthetic_mask[severity < 1.5].mean()) if (severity < 1.5).any() else None,
                        "medium": float(synthetic_mask[(severity >= 1.5) & (severity < 3)].mean()) if ((severity >= 1.5) & (severity < 3)).any() else None,
                        "high": float(synthetic_mask[severity >= 3].mean()) if (severity >= 3).any() else None,
                    },
                    "real_pr_auc": None,
                }
            simple = max(("rule", "robust_anomaly"), key=lambda name: (
                fold_metrics[name]["heldout_family_recall_at_budget"] or -1,
                -fold_metrics[name]["real_background_alerts_per_1000"],
            ))
            learned_ok = (
                "learned_logistic" in fold_metrics
                and fold_metrics["learned_logistic"]["heldout_family_recall_at_budget"] is not None
                and fold_metrics["learned_logistic"]["heldout_family_recall_at_budget"]
                >= (fold_metrics[simple]["heldout_family_recall_at_budget"] or 0) + 0.02
                and fold_metrics["learned_logistic"]["real_background_alerts_per_1000"]
                <= fold_metrics[simple]["real_background_alerts_per_1000"] + 1.0
            )
            selected = "learned_logistic" if learned_ok else simple
            last_artifact = {
                "selected": selected, "model": learned if selected == "learned_logistic" else None,
                "robust": robust, "features": features,
                "threshold": fold_metrics[selected]["threshold_from_real_calibration"],
            }
            payload["folds"][fold.name] = {
                "rows": {key: value.height for key, value in split.items()},
                "supported_validation_coverage": split["validation"].height / max(all_validation_rows, 1),
                "synthetic_rows": len(challenge), "training_families": ["0", "1"],
                "heldout_family": "2",
                "alert_budget_per_day_effective": effective_budget,
                "budget_saturation": budget_saturation,
                "models": fold_metrics, "selected_detector": selected,
                "selection_reason": "LEARNED_BEATS_HELDOUT_BASELINE" if learned_ok else "PREFER_SIMPLE_BASELINE",
            }
            values = model_scores[selected]["validation"]
            threshold = fold_metrics[selected]["threshold_from_real_calibration"]
            alert = _top_budget_mask(val_dates, values, effective_budget) & (values > threshold)
            predictions.append(split["validation"].select(
                "d_object_key", "d_cutoff_date", "d_target_start_date", "d_target_end_date_exclusive"
            ).with_columns(
                pl.Series("selected_score", values), pl.lit(fold.name).alias("fold"),
                pl.lit("synthetic_scenario_match").alias("score_kind"),
                pl.lit("E4").alias("evidence_level"),
                pl.Series("decision_status", np.where(alert, "scenario_match", "background_like")),
            ))
        payload["selection"] = {
            "status": "synthetic_detector_only", "backend_incident_model_allowed": False,
            "backend_scenario_score_allowed": all(
                fold_result["budget_saturation"] < 0.8 for fold_result in payload["folds"].values()
            ),
            "reason_codes": ["E4_SYNTHETIC_CHALLENGE_ONLY", "NO_CONFIRMED_INCIDENT_LABEL"]
            + (["BUDGET_SATURATED"] if any(
                fold_result["budget_saturation"] >= 0.8 for fold_result in payload["folds"].values()
            ) else []),
        }
        if last_artifact is not None:
            model_path = output_dir / f"model_{task}_synthetic_selected.joblib"
            import joblib

            joblib.dump(last_artifact["model"], model_path)
            scenario_contract = {
                "contract_version": "scenario-inference-1.0",
                "generator_version": SCENARIO_GENERATOR_VERSION,
                "source_bundle_sha256": manifest["sha256"],
                "trained_for_fold": list(payload["folds"])[-1],
                "target_code": f"{task}_synthetic_scenario",
                "score_kind": "synthetic_scenario_match", "evidence_level": "E4",
                "selected_model": last_artifact["selected"],
                "base_features": spec["features"], "feature_names": features,
                "support_column": spec["support"],
                "robust_median": last_artifact["robust"]["median"].tolist(),
                "robust_scale": last_artifact["robust"]["scale"].tolist(),
                "threshold": float(last_artifact["threshold"]),
                "alert_budget_per_day_max": budget,
                "model_file": model_path.name, "model_sha256": sha256_file(model_path),
                "warning_ru": "E4: сценарный скор, не вероятность реального инцидента.",
            }
            contract_path = output_dir / f"model_{task}_synthetic_contract.json"
            write_json(contract_path, scenario_contract)
            payload["selection"]["artifact"] = {
                "model_file": model_path.name, "model_sha256": scenario_contract["model_sha256"],
                "contract_file": contract_path.name, "contract_sha256": sha256_file(contract_path),
            }
        result_name = f"results_{task}_synthetic_scenario.json"
        prediction_name = f"predictions_{task}_synthetic_scenario.parquet"
        write_json(output_dir / result_name, payload)
        if predictions:
            pl.concat(predictions, how="vertical_relaxed").write_parquet(output_dir / prediction_name, compression="zstd")
        (output_dir / f"summary_{task}_synthetic_scenario_ru.md").write_text(
            f"# {task}: синтетические сценарии\n\n"
            "E4: сценарное совпадение, не вероятность реального инцидента. "
            "Порог выбран только на реальном background; семейство 2 не использовалось при обучении.\n\n"
            + "\n".join(
                f"- {name}: выбран {fold_result['selected_detector']}; "
                f"background alerts/day = {fold_result['models'][fold_result['selected_detector']]['real_alerts_per_day']:.2f}; "
                f"held-out recall@{fold_result['alert_budget_per_day_effective']}/day = {fold_result['models'][fold_result['selected_detector']]['heldout_family_recall_at_budget']}"
                for name, fold_result in payload["folds"].items()
            ) + "\n", encoding="utf-8"
        )
        results[task] = payload
    return results


def predict_scenario_bundle(history: Any, frame: Any, bundle_dir: str | Path, task: str) -> Any:
    """Replay a notebook-10 E4 detector on canonical object-day history."""
    import joblib
    import polars as pl

    if task not in SCENARIO_SPECS:
        raise ValueError("Unknown scenario task")
    bundle_dir = Path(bundle_dir)
    contract = json.loads((bundle_dir / f"model_{task}_synthetic_contract.json").read_text(encoding="utf-8"))
    if contract.get("contract_version") != "scenario-inference-1.0" or contract.get("generator_version") != SCENARIO_GENERATOR_VERSION:
        raise RuntimeError("Устаревший synthetic contract")
    model_path = bundle_dir / contract["model_file"]
    if sha256_file(model_path) != contract["model_sha256"]:
        raise RuntimeError("SHA-256 synthetic model не совпал")
    required = {"d_object_key", "d_cutoff_date", *contract["base_features"], contract["support_column"]}
    missing = sorted(required - set(history.columns))
    if missing:
        raise RuntimeError(f"Отсутствуют object-day признаки: {missing}")
    if frame.height == 0:
        return frame.select("d_object_key", "d_cutoff_date").with_columns(pl.lit(None, dtype=pl.Float64).alias("score"))
    if frame.select("d_object_key", "d_cutoff_date").unique().height != frame.height:
        raise RuntimeError("Duplicate object-day input")
    expanded = _scenario_history(history, contract["base_features"])
    selected = frame.select("d_object_key", "d_cutoff_date").with_row_index("_prediction_row").join(
        expanded, on=["d_object_key", "d_cutoff_date"], how="left"
    ).sort("_prediction_row")
    if selected.height != frame.height:
        raise RuntimeError("Incomplete or duplicated object-day history")
    robust = {
        "median": np.asarray(contract["robust_median"], dtype=np.float64),
        "scale": np.asarray(contract["robust_scale"], dtype=np.float64),
    }
    x = _robust_apply(selected, contract["feature_names"], robust)
    name = contract["selected_model"]
    if name == "rule":
        score = _scenario_rule(x, contract["feature_names"], SCENARIO_SPECS[task]["families"])
    elif name == "robust_anomaly":
        score = _scenario_anomaly(x)
    elif name == "learned_logistic":
        score = _finite_probability(joblib.load(model_path).predict_proba(x)[:, 1])
    else:
        raise RuntimeError("Unknown scenario detector")
    supported = selected[contract["support_column"]].fill_null(0).to_numpy() > 0
    return selected.select("d_object_key", "d_cutoff_date").with_columns(
        pl.Series("score", np.where(supported, score, np.nan)).fill_nan(None),
        pl.lit(contract["target_code"]).alias("target_code"),
        pl.lit("synthetic_scenario_match").alias("score_kind"),
        pl.lit("E4").alias("evidence_level"),
        (pl.col("d_cutoff_date") + pl.duration(days=2)).alias("window_start"),
        (pl.col("d_cutoff_date") + pl.duration(days=3)).alias("window_end_exclusive"),
        pl.Series("decision_status", np.where(supported, "experimental_shadow", "abstain")),
        pl.Series("reason_codes", np.where(supported, "[]", '["NO_SUPPORTED_SENSOR"]')),
    )


DROPOUT_NUMERIC_FEATURES = [
    "d_event_count_24h",
    "d_alarm_count_24h",
    "d_alarm_share_24h",
    "d_failure_state_event_count_24h",
    "d_value_numeric_mean_24h",
    "d_value_numeric_std_24h",
    "d_state_n_unique_24h",
    "d_gap_days_since_previous",
    "d_event_count_previous_24h",
    "d_alarm_count_previous_24h",
    "d_alarm_share_previous_24h",
    "d_catalogue_match",
]
DROPOUT_CATEGORICAL_FEATURES = ["тип_датчика", "тип_инж_системы"]


def _to_model_pandas(frame: Any, columns: Sequence[str]) -> Any:
    import pandas as pd

    data = pd.DataFrame(frame.select(columns).to_dict(as_series=False))
    for column in columns:
        if column in DROPOUT_CATEGORICAL_FEATURES:
            data[column] = data[column].fillna("__MISSING__").astype(str)
        else:
            data[column] = data[column].astype(float)
    return data


def _dropout_rule_probability(frame: Any) -> np.ndarray:
    gap = np.nan_to_num(frame["d_gap_days_since_previous"].to_numpy(), nan=0.0)
    current = np.nan_to_num(frame["d_event_count_24h"].to_numpy(), nan=0.0)
    previous = np.nan_to_num(frame["d_event_count_previous_24h"].to_numpy(), nan=0.0)
    cadence_change = np.maximum(previous - current, 0) / (1 + np.maximum(previous, 0))
    raw = 0.9 * np.log1p(np.maximum(gap, 0)) + 1.4 * cadence_change - 1.8
    return 1.0 / (1.0 + np.exp(-np.clip(raw, -20, 20)))


def _fit_dropout_logistic(train: Any, weights: np.ndarray, target: str) -> Any:
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric = Pipeline(
        [("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
    )
    categorical = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("one_hot", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]
    )
    transformer = ColumnTransformer(
        [("numeric", numeric, DROPOUT_NUMERIC_FEATURES), ("categorical", categorical, DROPOUT_CATEGORICAL_FEATURES)]
    )
    model = Pipeline(
        [
            ("features", transformer),
            (
                "classifier",
                LogisticRegression(
                    C=0.5,
                    max_iter=600,
                    solver="liblinear",
                    random_state=0,
                ),
            ),
        ]
    )
    x = _to_model_pandas(train, DROPOUT_NUMERIC_FEATURES + DROPOUT_CATEGORICAL_FEATURES)
    model.fit(x, train[target].to_numpy().astype(np.int8), classifier__sample_weight=weights)
    return model


def _predict_dropout_logistic(model: Any, frame: Any) -> np.ndarray:
    x = _to_model_pandas(frame, DROPOUT_NUMERIC_FEATURES + DROPOUT_CATEGORICAL_FEATURES)
    return _finite_probability(model.predict_proba(x)[:, 1])


def _build_channel_sequences(
    history: Any,
    selected: Any,
    features: Sequence[str],
    length: int,
    robust: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Create causal sequences of observed rows; gaps remain explicit features."""
    hist = history.select(["d_channel_key", "d_cutoff_date", *features]).sort(
        ["d_channel_key", "d_cutoff_date"]
    )
    hist_x = _robust_apply(hist, features, robust)
    channels = hist["d_channel_key"].to_numpy()
    dates = hist["d_cutoff_date"].to_numpy()
    groups: dict[str, np.ndarray] = {}
    if len(channels):
        boundaries = np.r_[0, np.flatnonzero(channels[1:] != channels[:-1]) + 1, len(channels)]
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            groups[str(channels[start])] = np.arange(start, end)
    selected_channels = selected["d_channel_key"].to_numpy()
    selected_dates = selected["d_cutoff_date"].to_numpy()
    values = np.zeros((selected.height, length, len(features)), dtype=np.float32)
    mask = np.zeros((selected.height, length), dtype=np.float32)
    for row, (channel, cutoff) in enumerate(zip(selected_channels, selected_dates)):
        indices = groups.get(str(channel))
        if indices is None:
            continue
        local_dates = dates[indices]
        stop = int(np.searchsorted(local_dates, cutoff, side="right"))
        chosen = indices[max(0, stop - length) : stop]
        size = len(chosen)
        if size:
            values[row, -size:] = hist_x[chosen]
            mask[row, -size:] = 1.0
    return values, mask


def _make_masked_tcn(width: int, hidden: int) -> Any:
    import torch
    from torch import nn

    class MaskedTCN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.network = nn.Sequential(
                nn.Conv1d(width, hidden, kernel_size=3, padding=2, dilation=1),
                nn.ReLU(),
                nn.Conv1d(hidden, hidden, kernel_size=3, padding=4, dilation=2),
                nn.ReLU(),
            )
            self.head = nn.Linear(hidden * 2, 1)

        def forward(self, values: Any, valid: Any) -> Any:
            encoded = self.network(values.transpose(1, 2))[:, :, : values.shape[1]]
            valid_expanded = valid.unsqueeze(1)
            mean = (encoded * valid_expanded).sum(dim=2) / valid_expanded.sum(dim=2).clamp_min(1)
            masked = encoded.masked_fill(valid_expanded == 0, -1e9)
            maximum = masked.max(dim=2).values
            maximum = torch.where(torch.isfinite(maximum), maximum, torch.zeros_like(maximum))
            return self.head(torch.cat([mean, maximum], dim=1)).squeeze(1)

    return MaskedTCN()


def _fit_masked_tcn(
    history: Any,
    train: Any,
    weights: np.ndarray,
    target: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    if config.get("run_mode") == "smoke":
        return {"kind": "smoke_logistic_surrogate", "model": _fit_dropout_logistic(train, weights, target)}
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("FULL notebook 11 требует Kaggle NVIDIA GPU")
    seed = int(config.get("random_seed", 0))
    torch.manual_seed(seed)
    max_rows = int(config.get("max_tcn_train_rows", 200_000))
    original_negative_count = int((train[target].to_numpy() == 0).sum())
    if train.height > max_rows:
        # This bounded sample is independent of validation and retains all positives where possible.
        import polars as pl

        positives = train.filter(pl.col(target) == 1)
        negative_count = max(0, max_rows - positives.height)
        negatives = train.filter(pl.col(target) == 0).sample(
            n=min(negative_count, train.filter(pl.col(target) == 0).height),
            seed=seed,
            shuffle=True,
        )
        train = pl.concat([positives, negatives]).sample(fraction=1.0, seed=seed, shuffle=True)
        y_train = train[target].to_numpy().astype(np.int8)
        # Sampling weights must depend only on the current training fold.
        negative_probability = len(negatives) / max(original_negative_count, 1)
        weights = np.where(y_train == 1, 1.0, 1.0 / max(negative_probability, 1e-12))
    robust = _robust_fit(train, DROPOUT_NUMERIC_FEATURES)
    sequence_length = int(config.get("sequence_length", 14))
    x, mask = _build_channel_sequences(
        history, train, DROPOUT_NUMERIC_FEATURES, sequence_length, robust
    )
    y = train[target].to_numpy().astype(np.float32)

    device = torch.device("cuda")
    model = _make_masked_tcn(x.shape[2], int(config.get("tcn_hidden", 48))).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    tensors = torch.utils.data.TensorDataset(
        torch.tensor(x),
        torch.tensor(mask),
        torch.tensor(y),
        torch.tensor(weights.astype(np.float32)),
    )
    loader = torch.utils.data.DataLoader(
        tensors,
        batch_size=int(config.get("batch_size", 1024)),
        shuffle=True,
    )
    model.train()
    for _ in range(int(config.get("epochs", 10))):
        for batch_x, batch_mask, batch_y, batch_weight in loader:
            batch_x, batch_mask = batch_x.to(device), batch_mask.to(device)
            batch_y, batch_weight = batch_y.to(device), batch_weight.to(device)
            logits = model(batch_x, batch_mask)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                logits, batch_y, weight=batch_weight
            )
            optimiser.zero_grad(set_to_none=True)
            loss.backward()
            optimiser.step()
    model.eval()
    return {
        "kind": "masked_tcn",
        "model": model,
        "robust": robust,
        "sequence_length": sequence_length,
    }


def _predict_masked_tcn(spec: dict[str, Any], history: Any, frame: Any) -> np.ndarray:
    if spec["kind"] == "smoke_logistic_surrogate":
        return _predict_dropout_logistic(spec["model"], frame)
    import torch

    x, mask = _build_channel_sequences(
        history,
        frame,
        DROPOUT_NUMERIC_FEATURES,
        spec["sequence_length"],
        spec["robust"],
    )
    model = spec["model"]
    device = next(model.parameters()).device
    outputs: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(x), 4096):
            batch_x = torch.tensor(x[start : start + 4096], device=device)
            batch_mask = torch.tensor(mask[start : start + 4096], device=device)
            outputs.append(torch.sigmoid(model(batch_x, batch_mask)).cpu().numpy())
    return _finite_probability(np.concatenate(outputs))


def _fit_calibrate_score_models(
    history: Any,
    split: dict[str, Any],
    validation_all: Any,
    target: str,
    config: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, np.ndarray], dict[str, np.ndarray], dict[str, dict[str, Any]]]:
    sampled, weights = sample_training_rows(
        split["train"],
        target,
        int(config.get("negative_to_positive_ratio", 20)),
        int(config.get("random_seed", 0)),
    )
    logistic = _fit_dropout_logistic(sampled, weights, target)
    tcn = _fit_masked_tcn(history, sampled, weights, target, config)
    known_indices = np.flatnonzero(validation_all[target].is_not_null().to_numpy())
    keys = ["d_channel_key", "d_cutoff_date"]
    aligned = (
        len(known_indices) == split["validation"].height
        and validation_all[known_indices.tolist()].select(keys).equals(
            split["validation"].select(keys)
        )
    )

    def labelled(all_values: np.ndarray, predictor: Any) -> np.ndarray:
        return all_values[known_indices] if aligned else predictor(split["validation"])

    rule_all = _dropout_rule_probability(validation_all)
    logistic_all = _predict_dropout_logistic(logistic, validation_all)
    tcn_all = _predict_masked_tcn(tcn, history, validation_all)
    raw = {
        "cadence_rule": {
            "calibration": _dropout_rule_probability(split["calibration"]),
            "validation": labelled(rule_all, _dropout_rule_probability),
            "validation_all": rule_all,
        },
        "logistic_hazard": {
            "calibration": _predict_dropout_logistic(logistic, split["calibration"]),
            "validation": labelled(logistic_all, lambda frame: _predict_dropout_logistic(logistic, frame)),
            "validation_all": logistic_all,
        },
        "masked_tcn": {
            "calibration": _predict_masked_tcn(tcn, history, split["calibration"]),
            "validation": labelled(tcn_all, lambda frame: _predict_masked_tcn(tcn, history, frame)),
            "validation_all": tcn_all,
        },
    }
    metrics: dict[str, dict[str, Any]] = {}
    probability: dict[str, np.ndarray] = {}
    probability_all: dict[str, np.ndarray] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    cal_y = split["calibration"][target].to_numpy().astype(np.int8)
    for name, values in raw.items():
        calibrator = fit_platt(values["calibration"], cal_y)
        cal_probability = apply_platt(calibrator, values["calibration"])
        validation_probability = apply_platt(calibrator, values["validation"])
        all_probability = apply_platt(calibrator, values["validation_all"])
        threshold = threshold_for_precision(
            cal_y, cal_probability, float(config.get("minimum_precision", 0.2))
        )
        metrics[name] = score_predictions(
            split["validation"],
            target,
            validation_probability,
            threshold,
            config,
            entity_column="d_channel_key",
        )
        metrics[name]["implementation"] = (
            tcn["kind"] if name == "masked_tcn" else name
        )
        asof_episodes = episode_metrics(
            validation_all, target, all_probability,
            int(config.get("alert_budget_per_day", 50)),
            int(config.get("cooldown_hours", 72)), None, "d_channel_key",
        )
        metrics[name]["asof_operational"] = {
            **asof_episodes,
            "cohort_rows": validation_all.height,
            "labelled_rows": split["validation"].height,
            "label_coverage": split["validation"].height / max(validation_all.height, 1),
            "known_negative_alerts_per_1000_cohort_days": (
                1000 * asof_episodes["known_negative_alert_episodes"] / max(validation_all.height, 1)
            ),
            "unresolved_alert_share": (
                asof_episodes["unresolved_alert_episodes"] / max(asof_episodes["alert_episodes"], 1)
            ),
            "precision_is_lower_bound": True,
        }
        probability[name] = validation_probability
        probability_all[name] = all_probability
        artifacts[name] = {
            "model": None if name == "cadence_rule" else logistic if name == "logistic_hazard" else tcn,
            "calibrator": calibrator,
            "threshold": float(threshold),
        }
    return metrics, probability, probability_all, artifacts


def _mean_metric(folds: dict[str, Any], model: str, path: Sequence[str]) -> float | None:
    values: list[float] = []
    for payload in folds.values():
        current: Any = payload["models"][model]
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if current is not None and np.isfinite(current):
            values.append(float(current))
    return float(np.mean(values)) if values else None


def _calibrator_contract(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("kind") != "platt":
        return {"kind": "identity"}
    model = spec["model"]
    return {
        "kind": "platt_logit",
        "coef": model.coef_.ravel().tolist(),
        "intercept": model.intercept_.ravel().tolist(),
        "classes": model.classes_.tolist(),
    }


def _save_dropout_artifact(
    selected: str,
    artifact: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any],
    source_bundle_sha256: Any,
) -> dict[str, Any]:
    contract = {
        "contract_version": DROPOUT_SELECTION_CONTRACT_VERSION,
        "target_code": DROPOUT_TARGET,
        "score_kind": "channel_availability_proxy_probability",
        "evidence_level": "E1",
        "model": selected,
        "trained_for_fold": "fold_2024",
        "source_bundle_sha256": source_bundle_sha256,
        "numeric_features": DROPOUT_NUMERIC_FEATURES,
        "categorical_features": DROPOUT_CATEGORICAL_FEATURES,
        "sequence_length": int(config.get("sequence_length", 14)),
        "threshold": float(artifact["threshold"]),
        "alert_budget_per_day": int(config.get("alert_budget_per_day", 50)),
        "cooldown_hours": int(config.get("cooldown_hours", 72)),
        "asof_eligibility": "channel and at least one peer observed at end of D",
        "calibration": _calibrator_contract(artifact["calibrator"]),
        "preprocessing_ru": (
            "Исторические channel-day признаки строятся до вызова модели. "
            "Импутация/масштабирование сохранены в model-файле; "
            "калибровка и политика тревог — в contract JSON."
        ),
        "warning_ru": "Это proxy наблюдаемости канала, а не вероятность физического отказа.",
    }
    if selected == "cadence_rule":
        model_path = output_dir / "model_dropout_selected.json"
        write_json(
            model_path,
            {
                "kind": "cadence_rule",
                "formula": "sigmoid(0.9*log1p(max(gap,0)) + 1.4*max(previous-current,0)/(1+max(previous,0)) - 1.8)",
            },
        )
    elif selected == "logistic_hazard":
        import joblib

        model_path = output_dir / "model_dropout_selected.joblib"
        joblib.dump(artifact["model"], model_path)
    else:
        spec = artifact["model"]
        if spec["kind"] == "smoke_logistic_surrogate":
            import joblib

            model_path = output_dir / "model_dropout_selected.joblib"
            joblib.dump(spec["model"], model_path)
        else:
            import torch

            model_path = output_dir / "model_dropout_selected.pt"
            torch.save(
                {
                    "state_dict": {key: value.detach().cpu() for key, value in spec["model"].state_dict().items()},
                    "robust_median": spec["robust"]["median"].tolist(),
                    "robust_scale": spec["robust"]["scale"].tolist(),
                    "sequence_length": int(spec["sequence_length"]),
                    "numeric_features": DROPOUT_NUMERIC_FEATURES,
                    "tcn_hidden": int(config.get("tcn_hidden", 48)),
                },
                model_path,
            )
    contract["model_file"] = model_path.name
    contract["model_sha256"] = sha256_file(model_path)
    contract_path = output_dir / "model_dropout_contract.json"
    write_json(contract_path, contract)
    return {
        "model_file": model_path.name,
        "model_sha256": contract["model_sha256"],
        "contract_file": contract_path.name,
        "contract_sha256": sha256_file(contract_path),
    }


def predict_dropout_bundle(history: Any, frame: Any, bundle_dir: str | Path) -> Any:
    """Score canonical channel-day features; never claim confirmed failure risk.

    `history` must contain all peer channels through each requested day D. It is
    not a raw-event feature builder. Top-K and cooldown remain backend policy.
    """
    import polars as pl

    bundle_dir = Path(bundle_dir)
    contract = json.loads((bundle_dir / "model_dropout_contract.json").read_text(encoding="utf-8"))
    if contract.get("contract_version") != DROPOUT_SELECTION_CONTRACT_VERSION:
        raise RuntimeError("Устаревший dropout contract")
    model_path = bundle_dir / contract["model_file"]
    if sha256_file(model_path) != contract["model_sha256"]:
        raise RuntimeError("SHA-256 dropout model не совпал")
    required = {"d_channel_key", "d_object_key", "d_cutoff_date", *DROPOUT_NUMERIC_FEATURES}
    if contract["model"] != "cadence_rule":
        required.update(DROPOUT_CATEGORICAL_FEATURES)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Отсутствуют day-D признаки: {missing}")
    history_missing = sorted({"d_channel_key", "d_object_key", "d_cutoff_date", *DROPOUT_NUMERIC_FEATURES} - set(history.columns))
    if history_missing:
        raise RuntimeError(f"Отсутствуют исторические признаки: {history_missing}")
    if frame.height == 0:
        return frame.select("d_channel_key", "d_object_key", "d_cutoff_date").with_columns(
            pl.lit(None, dtype=pl.Float64).alias("score")
        )
    peer_counts = history.group_by(["d_object_key", "d_cutoff_date"]).agg(
        pl.col("d_channel_key").n_unique().alias("_asof_channel_count")
    )
    indexed = frame.with_row_index("_prediction_row").join(
        peer_counts, on=["d_object_key", "d_cutoff_date"], how="left"
    ).sort("_prediction_row")
    if contract["model"] == "cadence_rule":
        raw = _dropout_rule_probability(indexed)
    elif model_path.suffix == ".joblib":
        import joblib

        raw = _predict_dropout_logistic(joblib.load(model_path), indexed)
    elif model_path.suffix == ".pt" and contract["model"] == "masked_tcn":
        import torch

        saved = torch.load(model_path, map_location="cpu", weights_only=True)
        if saved["numeric_features"] != DROPOUT_NUMERIC_FEATURES:
            raise RuntimeError("TCN feature contract не совпал")
        model = _make_masked_tcn(len(DROPOUT_NUMERIC_FEATURES), int(saved["tcn_hidden"]))
        model.load_state_dict(saved["state_dict"])
        model.eval()
        spec = {
            "kind": "masked_tcn", "model": model,
            "robust": {
                "median": np.asarray(saved["robust_median"]),
                "scale": np.asarray(saved["robust_scale"]),
            },
            "sequence_length": int(saved["sequence_length"]),
        }
        raw = _predict_masked_tcn(spec, history, indexed)
    else:
        raise RuntimeError("Неизвестный формат dropout model")
    calibration = contract["calibration"]
    probability = np.clip(raw, 1e-6, 1 - 1e-6)
    if calibration["kind"] == "platt_logit":
        logit = np.log(probability / (1 - probability))
        z = float(calibration["coef"][0]) * logit + float(calibration["intercept"][0])
        probability = 1 / (1 + np.exp(-np.clip(z, -50, 50)))
    elif calibration["kind"] != "identity":
        raise RuntimeError("Неизвестный calibrator")
    eligible = indexed["_asof_channel_count"].fill_null(0).to_numpy() >= 2
    return indexed.select("d_channel_key", "d_object_key", "d_cutoff_date").with_columns(
        pl.Series("score", np.where(eligible, probability, np.nan)).fill_nan(None),
        pl.lit(DROPOUT_TARGET).alias("target_code"),
        pl.lit("channel_availability_proxy_probability").alias("score_kind"),
        pl.lit("E1").alias("evidence_level"),
        (pl.col("d_cutoff_date") + pl.duration(days=2)).alias("window_start"),
        (pl.col("d_cutoff_date") + pl.duration(days=5)).alias("window_end_exclusive"),
        pl.Series("decision_status", np.where(eligible, "experimental_shadow", "abstain")),
        pl.Series("reason_codes", np.where(eligible, "[]", '["NO_DAY_D_PEER"]')),
    )


def run_dropout_experiment(
    channel: Any,
    manifest: dict[str, Any],
    config: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    import polars as pl

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # The attached 07 bundle can contain a legacy target. Rebuild labels from
    # its immutable day-D feature rows without trusting future-defined eligibility.
    old_label_columns = [
        DROPOUT_TARGET, "d_dropout_asof_eligible", "d_dropout_peer_evidence_complete",
        "d_days_to_second_future_observation", "d_dropout_target_start_date",
        "d_dropout_target_end_date_exclusive",
    ]
    channel = _add_dropout_target(
        channel.drop([name for name in old_label_columns if name in channel.columns])
    ).filter(pl.col("d_dropout_asof_eligible"))
    results: dict[str, Any] = {
        "status": "completed",
        "run_mode": config.get("run_mode", "full"),
        "comparability": "non_comparable_smoke" if config.get("run_mode") == "smoke" else "comparable_within_target",
        "target_code": DROPOUT_TARGET,
        "target_semantics": TARGET_REGISTRY[DROPOUT_TARGET],
        "score_kind": "channel_availability_proxy_probability",
        "evidence_level": "E1",
        "physical_failure_probability_reported": False,
        "selection_contract_version": DROPOUT_SELECTION_CONTRACT_VERSION,
        "source_bundle_sha256": manifest.get("sha256"),
        "environment": environment_info(),
        "folds": {},
    }
    prediction_parts: list[Any] = []
    fold_store: dict[str, dict[str, Any]] = {}
    fold_artifacts: dict[str, dict[str, dict[str, Any]]] = {}
    for fold_index, fold in enumerate(ROLLING_FOLDS):
        split = rolling_split(
            channel,
            DROPOUT_TARGET,
            fold,
            "d_dropout_target_start_date",
            "d_dropout_target_end_date_exclusive",
        )
        validation_all = channel.filter(
            (pl.col("d_dropout_target_start_date") >= fold.validation_start)
            & (pl.col("d_dropout_target_end_date_exclusive") <= fold.validation_end)
        )
        if config.get("run_mode") == "smoke":
            split = {key: value.tail(min(value.height, 5000)) for key, value in split.items()}
            validation_all = validation_all.tail(min(validation_all.height, 5000))
        fold_config = dict(config)
        fold_config["random_seed"] = int(config.get("random_seed", 0)) + fold_index
        metrics, probability, probability_all, artifacts = _fit_calibrate_score_models(
            channel, split, validation_all, DROPOUT_TARGET, fold_config
        )
        comparisons = {
            model: date_block_bootstrap_difference(
                split["validation"],
                DROPOUT_TARGET,
                probability[model],
                probability["logistic_hazard"],
                int(config.get("bootstrap_repeats", 200)),
                int(config.get("random_seed", 0)) + fold_index,
            )
            for model in ("cadence_rule", "masked_tcn")
        }
        results["folds"][fold.name] = {
            "rows": {key: value.height for key, value in split.items()},
            "asof_validation_rows": validation_all.height,
            "label_coverage": split["validation"].height / max(validation_all.height, 1),
            "positives": {
                key: int(value.select(pl.col(DROPOUT_TARGET).sum()).item() or 0)
                for key, value in split.items()
            },
            "models": metrics,
            "paired_pr_auc_vs_logistic": comparisons,
        }
        fold_store[fold.name] = {
            "validation": split["validation"], "validation_all": validation_all,
            "probability": probability, "probability_all": probability_all,
        }
        fold_artifacts[fold.name] = artifacts
        # Final selection is decided across folds below; retain all scores temporarily.
        for model, values in probability.items():
            prediction_parts.append(
                validation_all.select(
                    "d_channel_key",
                    "d_cutoff_date",
                    pl.col("d_dropout_target_start_date").alias("d_target_start_date"),
                    pl.col("d_dropout_target_end_date_exclusive").alias("d_target_end_date_exclusive"),
                    DROPOUT_TARGET,
                ).with_columns(
                    pl.Series("score", probability_all[model]),
                    pl.lit(fold.name).alias("fold"),
                    pl.lit(model).alias("model"),
                )
            )
    summary = {
        model: {
            "episode_recall": _mean_metric(results["folds"], model, ["asof_operational", "recall"]),
            "episode_precision": _mean_metric(results["folds"], model, ["asof_operational", "precision"]),
            "false_alerts_per_1000": _mean_metric(results["folds"], model, ["false_alerts_per_1000_eligible_days"]),
            "operational_false_alerts_per_1000": _mean_metric(
                results["folds"], model, ["asof_operational", "known_negative_alerts_per_1000_cohort_days"]
            ),
            "unresolved_alert_share": _mean_metric(
                results["folds"], model, ["asof_operational", "unresolved_alert_share"]
            ),
            "pr_auc": _mean_metric(results["folds"], model, ["pr_auc"]),
        }
        for model in ("cadence_rule", "logistic_hazard", "masked_tcn")
    }
    best_simple = max(
        ("cadence_rule", "logistic_hazard"),
        key=lambda name: summary[name]["episode_recall"] or -math.inf,
    )
    neural = summary["masked_tcn"]
    simple = summary[best_simple]
    support_ok = all(
        payload["positives"]["validation"] >= int(config.get("min_positives_for_pr_auc", 20))
        for payload in results["folds"].values()
    )
    paired_operational: dict[str, Any] = {}
    episode_bootstrap_passes: list[bool] = []
    for fold_index, (fold_name, stored) in enumerate(fold_store.items()):
        comparison = date_block_bootstrap_episode_difference(
            stored["validation_all"],
            DROPOUT_TARGET,
            stored["probability_all"]["masked_tcn"],
            stored["probability_all"][best_simple],
            int(config.get("bootstrap_repeats", 200)),
            int(config.get("random_seed", 0)) + 100 + fold_index,
            int(config.get("alert_budget_per_day", 50)),
            int(config.get("cooldown_hours", 72)),
            "d_channel_key",
        )
        comparison["pr_auc"] = date_block_bootstrap_difference(
            stored["validation"],
            DROPOUT_TARGET,
            stored["probability"]["masked_tcn"],
            stored["probability"][best_simple],
            int(config.get("bootstrap_repeats", 200)),
            int(config.get("random_seed", 0)) + 200 + fold_index,
        )
        paired_operational[fold_name] = comparison
        recall_ci = comparison["episode_recall"]
        episode_bootstrap_passes.append(
            recall_ci.get("status") == "ok" and recall_ci.get("ci95_low", -math.inf) > 0
        )
    false_alert_limit = max(
        1.0, 0.05 * float(simple["operational_false_alerts_per_1000"] or 0.0)
    )
    coverage_ok = all(
        payload["label_coverage"] >= float(config.get("minimum_label_coverage", 0.8))
        for payload in results["folds"].values()
    )
    unresolved_ok = all(
        payload["models"]["masked_tcn"]["asof_operational"]["unresolved_alert_share"]
        <= float(config.get("maximum_unresolved_alert_share", 0.2))
        for payload in results["folds"].values()
    )
    full_run = config.get("run_mode", "full") == "full"
    neural_passes = (
        full_run
        and support_ok
        and coverage_ok
        and unresolved_ok
        and all(episode_bootstrap_passes)
        and neural["episode_precision"] is not None
        and simple["episode_precision"] is not None
        and neural["episode_precision"] >= simple["episode_precision"] - 0.01
        and neural["operational_false_alerts_per_1000"]
        <= simple["operational_false_alerts_per_1000"] + false_alert_limit
    )
    selected = "masked_tcn" if neural_passes else best_simple
    results["model_summary"] = summary
    results["paired_operational_vs_best_simple"] = {
        "candidate": "masked_tcn",
        "reference": best_simple,
        "folds": paired_operational,
    }
    results["selection"] = {
        "selected_model": selected,
        "decision_status": (
            "selected_proxy_model" if full_run and support_ok and coverage_ok and unresolved_ok
            else "experimental_censored_cohort"
        ),
        "backend_candidate": bool(full_run and support_ok and coverage_ok and unresolved_ok),
        "neural_passed_symmetric_gates": neural_passes,
        "best_simple_model": best_simple,
        "operational_false_alert_limit_per_1000": false_alert_limit,
        "reason_codes": (
            ["TCN_SIGNIFICANT_AND_OPERATIONALLY_NONINFERIOR"]
            if neural_passes
            else ["PREFER_SIMPLE_BASELINE", "TCN_DID_NOT_PASS_ALL_GATES"]
            + ([] if coverage_ok else ["LOW_LABEL_COVERAGE"])
            + ([] if unresolved_ok else ["HIGH_UNRESOLVED_ALERT_SHARE"])
            + ([] if full_run else ["SMOKE_NOT_COMPARABLE"])
        ),
    }
    selected_predictions = pl.concat(
        [part.filter(pl.col("model") == selected) for part in prediction_parts],
        how="vertical_relaxed",
    ).drop("model").with_columns(
        pl.lit("channel_availability_proxy_probability").alias("score_kind"),
        pl.lit("E1").alias("evidence_level"),
        pl.lit(results["selection"]["decision_status"]).alias("decision_status"),
    )
    selected_predictions.write_parquet(
        output_dir / "predictions_dropout_missing_target.parquet", compression="zstd"
    )
    all_predictions = pl.concat(prediction_parts, how="vertical_relaxed").with_columns(
        pl.lit("channel_availability_proxy_probability").alias("score_kind"),
        pl.lit("E1").alias("evidence_level"),
    )
    all_predictions.write_parquet(
        output_dir / "predictions_dropout_candidates.parquet", compression="zstd"
    )
    last_fold = list(fold_artifacts)[-1]
    results["selection"]["artifact"] = _save_dropout_artifact(
        selected, fold_artifacts[last_fold][selected], output_dir, config,
        manifest.get("sha256"),
    )
    write_json(output_dir / "results_dropout_missing_target.json", results)
    (output_dir / "summary_dropout_missing_target_ru.md").write_text(
        _dropout_summary(results), encoding="utf-8"
    )
    return results


def _dropout_summary(results: dict[str, Any]) -> str:
    lines = [
        "# Proxy временной потери наблюдаемости канала",
        "",
        "Это E1 proxy доступности, а не вероятность физического отказа.",
        "Операционные эпизоды рассчитаны на когорте, определённой в D. "
        "Precision и число известных отрицательных тревог — нижние оценки: "
        "исход части тревог цензурирован.",
        "",
        f"Выбрано: `{results['selection']['selected_model']}`; статус: `{results['selection']['decision_status']}`.",
        "",
        "| модель | known-positive episode recall | precision lower bound | known-negative alerts / 1000 D-cohort | PR-AUC on resolved labels |",
        "|---|---:|---:|---:|---:|",
    ]
    for model, metric in results["model_summary"].items():
        lines.append(
            f"| {model} | {metric['episode_recall']!s} | {metric['episode_precision']!s} | "
            f"{metric['operational_false_alerts_per_1000']!s} | {metric['pr_auc']!s} |"
        )
    lines.extend(["", "| фолд | D-когорта | разрешённые метки | coverage |", "|---|---:|---:|---:|"])
    for fold, payload in results["folds"].items():
        lines.append(
            f"| {fold} | {payload['asof_validation_rows']} | {payload['rows']['validation']} | "
            f"{payload['label_coverage']:.3f} |"
        )
    return "\n".join(lines) + "\n"


SCORECARD_INPUTS = {
    "access": {
        "direction": "access",
        "result": "results_access_missing_target.json",
        "predictions": "predictions_access_missing_target.parquet",
        "target_code": ACCESS_TARGET,
        "score_kind": "calibrated_corroboration_proxy_probability",
        "evidence_level": "E2",
        "entity_column": "d_object_key",
    },
    "fire": {
        "direction": "fire",
        "result": "results_fire_missing_target.json",
        "predictions": "predictions_fire_missing_target.parquet",
        "target_code": FIRE_TARGET,
        "score_kind": "calibrated_corroboration_proxy_probability",
        "evidence_level": "E2",
        "entity_column": "d_object_key",
    },
    "access_synthetic": {
        "direction": "access",
        "result": "results_access_synthetic_scenario.json",
        "predictions": "predictions_access_synthetic_scenario.parquet",
        "target_code": "access_synthetic_scenario",
        "score_kind": "synthetic_scenario_match",
        "evidence_level": "E4",
        "entity_column": "d_object_key",
        "optional": True,
    },
    "fire_synthetic": {
        "direction": "fire",
        "result": "results_fire_synthetic_scenario.json",
        "predictions": "predictions_fire_synthetic_scenario.parquet",
        "target_code": "fire_synthetic_scenario",
        "score_kind": "synthetic_scenario_match",
        "evidence_level": "E4",
        "entity_column": "d_object_key",
        "optional": True,
    },
    "flood": {
        "direction": "flooding",
        "result": "results_flood_synthetic_scenario.json",
        "predictions": "predictions_flood_synthetic_scenario.parquet",
        "target_code": "flood_synthetic_scenario",
        "score_kind": "synthetic_scenario_match",
        "evidence_level": "E4",
        "entity_column": "d_object_key",
        "optional": True,
    },
    "availability": {
        "direction": "failure_availability",
        "result": "results_dropout_missing_target.json",
        "predictions": "predictions_dropout_missing_target.parquet",
        "target_code": DROPOUT_TARGET,
        "score_kind": "channel_availability_proxy_probability",
        "evidence_level": "E1",
        "entity_column": "d_channel_key",
    },
}


def _discover_unique_outputs(filename: str, explicit: str | Path | None = None, optional: bool = False) -> Path | None:
    roots: list[Path] = []
    if explicit:
        roots.append(Path(explicit))
    env_root = os.environ.get("LDT_KAGGLE_RESULTS_DIR")
    if env_root:
        roots.append(Path(env_root))
    if Path("/kaggle/input").exists():
        roots.append(Path("/kaggle/input"))
    candidates = sorted(
        {
            path.resolve()
            for root in roots
            for path in ([root / filename] + list(root.rglob(filename)))
            if path.is_file()
        }
    )
    if optional and not candidates:
        return None
    if len(candidates) != 1:
        raise RuntimeError(
            f"Для {filename} ожидался один input, найдено {len(candidates)}"
        )
    return candidates[0]


def _decision_from_result(module: str, payload: dict[str, Any]) -> tuple[str, list[str], bool, str]:
    selection = payload.get("selection", {})
    if module in ("access_synthetic", "fire_synthetic", "flood"):
        source_status = str(selection.get("status") or "not_evaluable")
        gate_name = "backend_scenario_score_allowed"
    else:
        source_status = str(selection.get("decision_status") or selection.get("status") or "not_evaluable")
        gate_name = "backend_candidate"
    allowed = selection.get(gate_name) is True
    reasons = [str(reason) for reason in (selection.get("reason_codes") or ["NO_EXPLICIT_REASON"])]
    if not allowed:
        gate_reason = "BACKEND_GATE_FALSE" if selection.get(gate_name) is False else "BACKEND_GATE_MISSING"
        if gate_reason not in reasons:
            reasons.append(gate_reason)
    return (source_status if allowed else "abstain", reasons, allowed, source_status)


def build_missing_targets_scorecard(
    input_dir: str | Path | None,
    output_dir: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    import polars as pl

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    modules: dict[str, Any] = {}
    combined: list[Any] = []
    source_fingerprints: dict[str, str] = {}
    for module, contract in SCORECARD_INPUTS.items():
        optional = bool(contract.get("optional", False))
        result_path = _discover_unique_outputs(contract["result"], input_dir, optional)
        prediction_path = _discover_unique_outputs(contract["predictions"], input_dir, optional)
        if result_path is None and prediction_path is None:
            modules[module] = {
                "direction": contract["direction"],
                "target_code": contract["target_code"],
                "score_kind": contract["score_kind"],
                "evidence_level": contract["evidence_level"],
                "decision_status": "not_evaluated",
                "reason_codes": ["MISSING_SYNTHETIC_RUN"],
                "score_exposure_allowed": False,
                "prediction_rows": 0,
            }
            continue
        if result_path is None or prediction_path is None:
            raise RuntimeError(f"{module}: неполный result/prediction bundle")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if config.get("run_mode", "full") == "full" and result.get("run_mode") != "full":
            raise RuntimeError(f"{module}: smoke/non-comparable result запрещён для итогового scorecard")
        if result.get("status") not in (None, "completed"):
            raise RuntimeError(f"{module}: незавершённый result: {result.get('status')}")
        if module == "availability" and result.get("selection_contract_version") != DROPOUT_SELECTION_CONTRACT_VERSION:
            raise RuntimeError(
                "availability: устаревший selection contract; notebook 11 нужно перезапустить после исправления"
            )
        if optional and result.get("generator_version") != SCENARIO_GENERATOR_VERSION:
            raise RuntimeError(f"{module}: устаревший synthetic generator")
        if result.get("target_code") != contract["target_code"]:
            raise RuntimeError(f"{module}: target_code не совпал")
        if result.get("score_kind") != contract["score_kind"]:
            raise RuntimeError(f"{module}: score_kind не совпал")
        if result.get("evidence_level") != contract["evidence_level"]:
            raise RuntimeError(f"{module}: evidence_level не совпал")
        status, reasons, score_exposure_allowed, source_status = _decision_from_result(module, result)
        predictions = pl.read_parquet(prediction_path)
        entity = contract["entity_column"]
        score_column = "score" if "score" in predictions.columns else "selected_score"
        required = {
            entity,
            "d_target_start_date",
            "d_target_end_date_exclusive",
            score_column,
            "score_kind",
            "evidence_level",
        }
        missing = sorted(required - set(predictions.columns))
        if missing:
            raise RuntimeError(f"{module}: в predictions нет {missing}")
        score_kinds = predictions["score_kind"].unique().to_list()
        evidence = predictions["evidence_level"].unique().to_list()
        if score_kinds != [contract["score_kind"]] or evidence != [contract["evidence_level"]]:
            raise RuntimeError(f"{module}: predictions нарушают typed-score contract")
        raw_identifiers = {"ид_канала_данных", "ид_объект", "ид_события"} & set(predictions.columns)
        if raw_identifiers:
            raise RuntimeError(f"{module}: найдены сырые идентификаторы {sorted(raw_identifiers)}")
        invalid_scores = predictions.filter(
            pl.col(score_column).is_null()
            | pl.col(score_column).is_nan()
            | pl.col(score_column).is_infinite()
            | (pl.col(score_column) < 0)
            | (pl.col(score_column) > 1)
        ).height
        if invalid_scores:
            raise RuntimeError(f"{module}: {invalid_scores} некорректных score")
        duplicate_rows = predictions.height - predictions.select(
            entity, "d_target_start_date"
        ).unique().height
        if duplicate_rows:
            raise RuntimeError(f"{module}: duplicate entity/window rows: {duplicate_rows}")
        source = (
            result.get("source_bundle_sha256")
            or result.get("source_manifest_sha256")
            or result.get("input_contract", {}).get("source_manifest_sha256")
        )
        if config.get("run_mode", "full") == "full" and source is None:
            raise RuntimeError(f"{module}: отсутствует SHA-256 исходного бандла")
        if source is not None:
            source_fingerprints[module] = json.dumps(source, sort_keys=True, ensure_ascii=False)
        modules[module] = {
            "direction": contract["direction"],
            "target_code": contract["target_code"],
            "score_kind": contract["score_kind"],
            "evidence_level": contract["evidence_level"],
            "decision_status": status,
            "source_decision_status": source_status,
            "reason_codes": reasons,
            "score_exposure_allowed": score_exposure_allowed,
            "result_sha256": sha256_file(result_path),
            "predictions_sha256": sha256_file(prediction_path),
            "prediction_rows": predictions.height,
            "selection_contract_version": result.get("selection_contract_version"),
            "generator_version": result.get("generator_version"),
            "model_artifact": result.get("selection", {}).get("artifact"),
        }
        combined.append(
            predictions.select(
                pl.col(entity).alias("entity_key"),
                pl.lit("object" if entity == "d_object_key" else "channel").alias("entity_kind"),
                pl.lit(contract["target_code"]).alias("target_code"),
                pl.lit(contract["direction"]).alias("direction"),
                (pl.col(score_column).cast(pl.Float64) if score_exposure_allowed else pl.lit(None, dtype=pl.Float64)).alias("score"),
                pl.col(score_column).cast(pl.Float64).alias("research_score"),
                pl.lit(score_exposure_allowed).alias("score_exposure_allowed"),
                pl.lit(contract["score_kind"]).alias("score_kind"),
                pl.lit(contract["evidence_level"]).alias("evidence_level"),
                pl.col("d_target_start_date").alias("window_start"),
                pl.col("d_target_end_date_exclusive").alias("window_end_exclusive"),
                (pl.col("decision_status") if "decision_status" in predictions.columns and score_exposure_allowed else pl.lit(status)).alias("decision_status"),
                pl.lit(json.dumps(reasons, ensure_ascii=False)).alias("reason_codes"),
            )
        )
    scores = pl.concat(combined, how="vertical_relaxed")
    if len(set(source_fingerprints.values())) > 1:
        raise RuntimeError(
            f"Модули построены по разным source bundles: {sorted(source_fingerprints)}"
        )
    # Explicit invariant: a row describes exactly one target and is never averaged with another target.
    unique_rows = scores.select(
        pl.struct(["entity_key", "window_start", "target_code"]).n_unique()
    ).item()
    if unique_rows != scores.height:
        raise RuntimeError("В scorecard найдены duplicate entity/window/target rows")
    score_path = output_dir / "missing_targets_scores.parquet"
    scores.write_parquet(score_path, compression="zstd")
    scorecard = {
        "status": "completed",
        "run_mode": config.get("run_mode", "full"),
        "cross_target_averaging": False,
        "confirmed_incident_probability_available": False,
        "development_results_only": True,
        "router_contract_version": "missing-target-router-3.0",
        "modules": modules,
        "score_rows": scores.height,
        "scores_sha256": sha256_file(score_path),
        "environment": environment_info(),
    }
    write_json(output_dir / "missing_targets_scorecard.json", scorecard)
    router_contract = {
        "contract_version": scorecard["router_contract_version"],
        "cross_target_averaging": False,
        "confirmed_incident_probability_available": False,
        "result_fields": [
            "entity_key",
            "entity_kind",
            "target_code",
            "direction",
            "score",
            "research_score",
            "score_exposure_allowed",
            "score_kind",
            "evidence_level",
            "window_start",
            "window_end_exclusive",
            "decision_status",
            "reason_codes",
        ],
        "targets": modules,
        "warning_ru": (
            "Скоры разных целей нельзя усреднять. E1/E2 являются proxy, E4 — synthetic scenario match."
        ),
    }
    write_json(output_dir / "missing_targets_router_contract.json", router_contract)
    (output_dir / "missing_targets_scorecard_ru.md").write_text(
        _scorecard_summary(scorecard), encoding="utf-8"
    )
    return scorecard


def _scorecard_summary(scorecard: dict[str, Any]) -> str:
    lines = [
        "# Типизированный missing-target scorecard",
        "",
        "Scores разных целей не усредняются. Подтверждённая вероятность incident недоступна.",
        "",
        "| модуль | target_code | score_kind | evidence | status | rows |",
        "|---|---|---|---|---|---:|",
    ]
    for module, payload in scorecard["modules"].items():
        lines.append(
            f"| {module} | `{payload['target_code']}` | `{payload['score_kind']}` | "
            f"{payload['evidence_level']} | `{payload['decision_status']}` | {payload['prediction_rows']} |"
        )
    return "\n".join(lines) + "\n"
