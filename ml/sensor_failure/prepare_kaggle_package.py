"""Build and export the private, de-identified Kaggle development panel."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from kaggle_runtime import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    PANEL_SCHEMA_VERSION,
    REQUIRED_PANEL_COLUMNS,
    TARGETS,
    sha256_file,
    temporal_splits,
)
from panel import build_panel


PACKAGE_COLUMNS = [
    "d_channel_key",
    "d_object_key",
    "d_cutoff_date",
    "d_target_start_date",
    "d_target_end_date_exclusive",
    "d_future_failure_event_date",
    "d_future_alarm_event_date",
    "d_year",
    *NUMERIC_FEATURES,
    *CATEGORICAL_FEATURES,
    *TARGETS,
]


def _pseudonym(secret: bytes, prefix: str, value: str) -> str:
    digest = hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    return f"{prefix}_{digest}"


def deidentify_panel(panel: Any, secret: bytes) -> Any:
    import polars as pl

    channel_column = "ид_канала_данных"
    object_column = "ид_объект"
    channels = panel.select(channel_column).unique().with_columns(
        pl.col(channel_column)
        .map_elements(
            lambda value: _pseudonym(secret, "ch", str(value)),
            return_dtype=pl.String,
        )
        .alias("d_channel_key")
    )
    objects = (
        panel.select(object_column)
        .unique()
        .with_columns(
            pl.col(object_column)
            .fill_null("__MISSING__")
            .map_elements(
                lambda value: _pseudonym(secret, "obj", str(value)),
                return_dtype=pl.String,
            )
            .alias("d_object_key")
        )
    )
    development = (
        panel.filter(
            (pl.col("d_year") <= 2025)
            & (pl.col("d_target_end_date_exclusive") <= pl.lit(date(2026, 1, 1)))
        )
        .join(channels, on=channel_column, how="left")
        .join(objects, on=object_column, how="left", nulls_equal=True)
        .select(PACKAGE_COLUMNS)
    )
    missing = sorted(REQUIRED_PANEL_COLUMNS - set(development.columns))
    if missing:
        raise RuntimeError(f"export is missing required columns: {missing}")
    forbidden = {
        "ид_события",
        "ид_канала_данных",
        "ид_объект",
        "тег_инженерной_системы",
        "название_датчика",
    }
    leaked = sorted(forbidden & set(development.columns))
    if leaked:
        raise RuntimeError(f"raw identifiers remain in export: {leaked}")
    return development


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Refresh code hashes/support files without rebuilding an unchanged panel.",
    )
    parser.add_argument(
        "--failure-state-dictionary",
        type=Path,
        default=Path(__file__).resolve().parent / "config" / "failure_state_dictionary.json",
    )
    return parser.parse_args()


def _builder_paths() -> list[Path]:
    return [
        Path(__file__).resolve(),
        Path(__file__).resolve().parent / "panel.py",
        Path(__file__).resolve().parent / "kaggle_runtime.py",
    ]


def _write_support_files(output_dir: Path, dictionary_source: Path) -> None:
    dictionary_target = output_dir / "failure_state_dictionary.json"
    dictionary_target.write_bytes(dictionary_source.read_bytes())
    card_source = Path(__file__).resolve().parents[2] / "docs" / "KAGGLE_DATASET_CARD_RU.md"
    card_target = output_dir / "README_RU.md"
    card_target.write_bytes(card_source.read_bytes())
    manifest_path = output_dir / "panel_manifest_v2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data_path = output_dir / manifest["data_file"]
    if sha256_file(data_path) != manifest["data_sha256"]:
        raise RuntimeError("existing package data checksum mismatch")
    checksum = output_dir / "SHA256SUMS.txt"
    checksum.write_text(
        f"{manifest['data_sha256']}  {data_path.name}\n"
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n"
        f"{sha256_file(dictionary_target)}  {dictionary_target.name}\n"
        f"{sha256_file(card_target)}  {card_target.name}\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.refresh_existing:
        manifest_path = args.output_dir / "panel_manifest_v2.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["builder_files"] = [
            {"name": path.name, "sha256": sha256_file(path)}
            for path in _builder_paths()
        ]
        manifest["manifest_refreshed_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_support_files(args.output_dir, args.failure_state_dictionary)
        print(json.dumps({"refreshed": True, "rows": manifest["rows"]}))
        return
    panel, audit = build_panel(
        args.data_dir,
        args.failure_state_dictionary,
        latency_minutes=0,
        target_lead_hours=24,
        target_window_hours=24,
        clean_history_days=0,
    )
    if audit.get("panel_schema_version") != PANEL_SCHEMA_VERSION:
        raise RuntimeError("panel builder schema version mismatch")
    development = deidentify_panel(panel, secrets.token_bytes(32))
    splits = temporal_splits(development, "target_failure_state_onset_24h")
    data_path = args.output_dir / "channel_panel_deidentified_v2.parquet"
    development.write_parquet(data_path, compression="zstd")
    manifest = {
        "panel_schema_version": PANEL_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_file": data_path.name,
        "data_sha256": sha256_file(data_path),
        "rows": development.height,
        "columns": development.columns,
        "date_min": str(development["d_cutoff_date"].min()),
        "date_max": str(development["d_cutoff_date"].max()),
        "contains_2026_rows": False,
        "raw_identifiers_included": False,
        "pseudonymization": "HMAC-SHA256 with an ephemeral, discarded key",
        "target": {
            "primary": "target_failure_state_onset_24h",
            "semantics": "observable proxy, not confirmed physical failure",
            "lead_hours": 24,
            "window_hours": 24,
            "clean_history_days": 0,
        },
        "split_counts": {
            name: {
                "rows": frame.height,
                "positives": int(
                    (frame["target_failure_state_onset_24h"] == 1).sum()
                ),
            }
            for name, frame in splits.items()
        },
        "source_files": audit["source_files"],
        "builder_files": [
            {"name": path.name, "sha256": sha256_file(path)} for path in _builder_paths()
        ],
    }
    manifest_path = args.output_dir / "panel_manifest_v2.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_support_files(args.output_dir, args.failure_state_dictionary)
    print(
        json.dumps(
            {
                "rows": development.height,
                "data_mb": round(data_path.stat().st_size / 1024**2, 2),
                "date_min": manifest["date_min"],
                "date_max": manifest["date_max"],
                "split_counts": manifest["split_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
