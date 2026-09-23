"""Run one versioned, configuration-driven sensor-risk experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from panel import PANEL_SCHEMA_VERSION, TARGET_COLUMNS, build_panel, source_file_manifest
from train_baseline import FEATURE_PRESETS, _split, _train_models


SUPPORTED_MODELS = {"rule", "logistic", "catboost", "lightgbm"}


def load_experiment_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("experiment config must be a YAML object")
    target = config.get("target", {})
    if target.get("column") not in TARGET_COLUMNS:
        raise ValueError(f"target.column must be one of {TARGET_COLUMNS}")
    for name in ("lead_hours", "window_hours"):
        value = target.get(name)
        if not isinstance(value, int) or value < 0 or value % 24:
            raise ValueError(f"target.{name} must be a non-negative multiple of 24")
    if target["window_hours"] == 0:
        raise ValueError("target.window_hours must be positive")
    if target["window_hours"] != 24:
        raise ValueError(
            "the declared *_24h targets require target.window_hours: 24"
        )

    panel = config.get("panel", {})
    latencies = panel.get("latency_minutes", [])
    if not latencies or any(
        not isinstance(value, int) or value < 0 for value in latencies
    ):
        raise ValueError("panel.latency_minutes must contain non-negative integers")
    clean_history_days = target.get("clean_history_days", 0)
    if not isinstance(clean_history_days, int) or clean_history_days < 0:
        raise ValueError("target.clean_history_days must be a non-negative integer")

    preset = config.get("features", {}).get("preset")
    if preset not in FEATURE_PRESETS:
        raise ValueError(f"features.preset must be one of {sorted(FEATURE_PRESETS)}")
    models = config.get("models", {}).get("enabled", [])
    if not models or set(models) - SUPPORTED_MODELS:
        raise ValueError(
            f"models.enabled must contain only {sorted(SUPPORTED_MODELS)}"
        )
    category = config.get("category_selection", {})
    if category.get("mode") not in {"evidence", "fixed", "all"}:
        raise ValueError("category_selection.mode must be evidence, fixed, or all")
    evaluation = config.get("evaluation", {})
    if evaluation.get("alert_budget_per_day", 0) <= 0:
        raise ValueError("evaluation.alert_budget_per_day must be positive")
    training = config.get("training", {})
    if training.get("negative_to_positive_ratio", 0) <= 0:
        raise ValueError("training.negative_to_positive_ratio must be positive")
    return config


def select_categories(
    splits: dict[str, Any], target: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    import polars as pl

    column = policy.get("column", "тип_датчика")
    mode = policy["mode"]
    if mode == "fixed":
        selected = sorted(set(policy.get("fixed_values", [])))
    elif mode == "all":
        selected = sorted(
            splits["train"].select(column).drop_nulls().unique()[column].to_list()
        )
    else:
        train_counts = (
            splits["train"]
            .filter(pl.col(target) == 1)
            .group_by(column)
            .len()
            .rename({"len": "train_events"})
        )
        eligible = train_counts.filter(
            pl.col("train_events") >= policy.get("minimum_train_events", 100)
        )
        selected = sorted(eligible[column].drop_nulls().to_list())
    if not selected:
        raise RuntimeError("category policy selected no categories")

    before = {
        name: {"rows": frame.height, "positive": int((frame[target] == 1).sum())}
        for name, frame in splits.items()
    }
    filtered = {
        name: frame.filter(pl.col(column).is_in(selected))
        for name, frame in splits.items()
    }
    after = {
        name: {"rows": frame.height, "positive": int((frame[target] == 1).sum())}
        for name, frame in filtered.items()
    }
    return filtered, {
        "selection_period": "training only",
        "column": column,
        "selected_values": selected,
        "coverage_before": before,
        "coverage_after": after,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--unlock-test",
        action="store_true",
        help="Allow the one-time 2026 H1 evaluation when config also enables it.",
    )
    return parser.parse_args()


def main() -> None:
    import polars as pl

    cli = parse_args()
    config = load_experiment_config(cli.config)
    evaluation = config["evaluation"]
    evaluate_test = bool(evaluation.get("evaluate_test", False))
    if evaluate_test and not cli.unlock_test:
        raise RuntimeError(
            "2026 H1 is locked; pass --unlock-test only after configuration freeze"
        )

    target = config["target"]
    panel_config = config["panel"]
    model_config = config["models"]
    training = config["training"]
    dictionary_path = Path(panel_config["failure_state_dictionary"])
    if not dictionary_path.is_absolute():
        dictionary_path = cli.config.parent / dictionary_path

    experiment_dir = cli.output_dir / config["name"]
    experiment_dir.mkdir(parents=True, exist_ok=True)
    (experiment_dir / "resolved_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary: dict[str, Any] = {
        "target_semantics": "observable proxy, not confirmed physical failure",
        "test_locked": not evaluate_test,
        "runs": {},
    }
    for latency in panel_config.get("latency_minutes", [0]):
        run_dir = experiment_dir / f"latency_{int(latency):04d}m"
        run_dir.mkdir(parents=True, exist_ok=True)
        panel_path = run_dir / "channel_panel.parquet"
        audit_path = run_dir / "panel_audit.json"
        if panel_path.exists() and audit_path.exists():
            panel = pl.read_parquet(panel_path)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            expected = {
                "panel_schema_version": PANEL_SCHEMA_VERSION,
                "latency_minutes": int(latency),
                "target_lead_hours": target["lead_hours"],
                "target_window_hours": target["window_hours"],
                "clean_history_days": target.get("clean_history_days", 0),
            }
            mismatch = {
                key: (audit.get(key), value)
                for key, value in expected.items()
                if audit.get(key) != value
            }
            if mismatch:
                raise RuntimeError(f"cached panel configuration mismatch: {mismatch}")
            if audit.get("source_files") != source_file_manifest(cli.data_dir):
                raise RuntimeError("cached panel source checksums differ; rebuild required")
        else:
            panel, audit = build_panel(
                cli.data_dir,
                dictionary_path,
                latency_minutes=int(latency),
                target_lead_hours=target["lead_hours"],
                target_window_hours=target["window_hours"],
                clean_history_days=target.get("clean_history_days", 0),
            )
            panel.write_parquet(panel_path, compression="zstd")
            audit_path.write_text(
                json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        splits = _split(panel, target["column"], training.get("include_2021", False))
        splits, category_manifest = select_categories(
            splits, target["column"], config["category_selection"]
        )
        required = [
            "train",
            "calibration_2025_h1",
            "validation_2025_h2",
            "stress_2021",
        ]
        if evaluate_test:
            required.append("test_2026_h1")
        empty = [name for name in required if splits[name].is_empty()]
        if empty:
            raise RuntimeError(f"empty temporal splits after category selection: {empty}")

        catboost_config = model_config.get("catboost", {})
        lightgbm_config = model_config.get("lightgbm", {})
        run_args = SimpleNamespace(
            target=target["column"],
            models=model_config["enabled"],
            feature_preset=config["features"]["preset"],
            negative_to_positive_ratio=training.get("negative_to_positive_ratio", 20),
            random_seed=training.get("random_seed", 20260919),
            catboost_iterations=catboost_config.get("iterations", 500),
            catboost_threads=catboost_config.get("threads", -1),
            catboost_task_type=catboost_config.get("task_type", "CPU"),
            lightgbm_iterations=lightgbm_config.get("iterations", 500),
            lightgbm_threads=lightgbm_config.get("threads", -1),
            lightgbm_device_type=lightgbm_config.get("device_type", "cpu"),
            minimum_precision=evaluation.get("minimum_precision", 0.20),
            bootstrap_repeats=evaluation.get("bootstrap_repeats", 50),
            alert_budget_per_day=evaluation.get("alert_budget_per_day", 50),
            cooldown_hours=evaluation.get("cooldown_hours", 72),
            evaluate_test=evaluate_test,
            include_2021=training.get("include_2021", False),
        )
        result = _train_models(splits, run_args, run_dir)
        result["panel_audit"] = audit
        result["category_selection"] = category_manifest
        result["test_locked"] = not evaluate_test
        (run_dir / "metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary["runs"][str(latency)] = result

    (experiment_dir / "experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
