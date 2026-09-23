"""Contracts for the newcomer-aware experimental model."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

from cold_start_runtime import (  # noqa: E402
    TARGET,
    add_causal_maturity,
    backend_predictor_source,
    rolling_fold,
    run_cold_start_research,
)
from kaggle_runtime import (  # noqa: E402
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
)


def _row(channel: str, cutoff: date, target: int) -> dict:
    row = {
        "d_channel_key": channel,
        "d_object_key": "object",
        "d_cutoff_date": cutoff,
        "d_target_start_date": date(cutoff.year, cutoff.month, min(cutoff.day + 2, 28)),
        "d_target_end_date_exclusive": date(
            cutoff.year, cutoff.month, min(cutoff.day + 3, 28)
        ),
        "d_future_failure_event_date": None,
        "d_future_alarm_event_date": None,
        "d_year": cutoff.year,
        TARGET: target,
        "target_alarm_onset_24h": 0,
    }
    row.update(
        {
            name: (False if name == "d_catalogue_match" else 0.0)
            for name in NUMERIC_FEATURES
        }
    )
    row.update({name: "type" for name in CATEGORICAL_FEATURES})
    return row


def test_maturity_is_causal_and_channel_local() -> None:
    import polars as pl

    frame = pl.DataFrame(
        [
            _row("a", date(2022, 1, 2), 0),
            _row("b", date(2022, 1, 1), 0),
            _row("a", date(2022, 1, 1), 0),
            _row("a", date(2022, 1, 3), 1),
        ]
    )
    enriched = add_causal_maturity(frame, cold_days=2)
    assert enriched.filter(pl.col("d_channel_key") == "a")[
        "d_observed_days_so_far"
    ].to_list() == [1, 2, 3]
    assert enriched.filter(pl.col("d_channel_key") == "a")[
        "d_is_cold_start"
    ].to_list() == [True, True, False]
    assert enriched.filter(pl.col("d_channel_key") == "b")[
        "d_observed_days_so_far"
    ].to_list() == [1]


def test_future_target_change_does_not_change_maturity() -> None:
    import polars as pl

    rows = [
        _row("a", date(2022, 1, 1), 0),
        _row("a", date(2022, 1, 2), 0),
        _row("a", date(2022, 1, 3), 0),
    ]
    original = add_causal_maturity(pl.DataFrame(rows), cold_days=2)
    rows[-1][TARGET] = 1
    changed = add_causal_maturity(pl.DataFrame(rows), cold_days=2)
    assert original["d_observed_days_so_far"].to_list() == changed[
        "d_observed_days_so_far"
    ].to_list()
    assert original["d_is_cold_start"].to_list() == changed[
        "d_is_cold_start"
    ].to_list()


def test_rolling_fold_is_pre_2025_and_purged() -> None:
    import polars as pl

    rows = [
        _row("a", date(2022, 1, 1), 0),
        _row("a", date(2023, 3, 1), 0),
        _row("a", date(2023, 8, 1), 1),
        _row("a", date(2024, 3, 1), 0),
        _row("a", date(2024, 8, 1), 1),
        _row("a", date(2025, 8, 1), 1),
    ]
    frame = add_causal_maturity(pl.DataFrame(rows), cold_days=2)
    fold = rolling_fold(frame, 2024)
    assert fold["train"]["d_year"].max() == 2023
    assert fold["calibration"]["d_year"].unique().to_list() == [2024]
    assert fold["validation"]["d_year"].unique().to_list() == [2024]
    assert fold["validation"]["d_cutoff_date"].min() >= date(2024, 7, 1)
    assert all(part["d_year"].max() < 2025 for part in fold.values())


def test_backend_predictor_source_compiles() -> None:
    compile(backend_predictor_source(), "predictor.py", "exec")


def test_generated_notebook_is_standalone_cpu_and_compiles() -> None:
    path = ROOT / "notebooks" / "kaggle" / "06_cold_start_router_cpu_for_mi.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    assert len(notebook["cells"]) == 9
    source = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert "run_cold_start_research" in source
    assert "uses_2025_h2_for_selection_or_training" in source
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), str(path), "exec")


def test_smoke_end_to_end_exports_backend_bundle(tmp_path: Path) -> None:
    import polars as pl

    rows = []
    for year in [2022, 2023, 2024, 2025]:
        months = [2, 8] if year < 2025 else [2]
        for channel_index in range(8):
            channel = f"ch_{channel_index}"
            for month in months:
                for day in range(1, 11):
                    positive = int(day in {2, 9} and channel_index % 2 == 0)
                    row = _row(channel, date(year, month, day), positive)
                    row["d_future_failure_event_date"] = (
                        row["d_target_start_date"] if positive else None
                    )
                    for index, name in enumerate(NUMERIC_FEATURES):
                        row[name] = (
                            channel_index % 2 == 0
                            if name == "d_catalogue_match"
                            else float((channel_index + day + index) % 11)
                        )
                    rows.append(row)
    panel = pl.DataFrame(rows)
    config = {
        "run_mode": "smoke",
        "cold_days": 7,
        "negative_to_positive_ratio": 5,
        "minimum_precision": 0.20,
        "alert_budget_per_day": 5,
        "cooldown_hours": 72,
        "iterations": 10,
        "bootstrap_repeats": 10,
        "robust_stats_max_rows": 10_000,
        "random_seed": 42,
    }
    manifest = {"data_sha256": "synthetic"}
    result = run_cold_start_research(panel, manifest, config, tmp_path)
    assert result["uses_2025_h2_for_selection_or_training"] is False
    assert result["uses_2026"] is False
    assert (tmp_path / "backend_experimental_model.zip").exists()
    assert (tmp_path / "experimental_cold_start_model.joblib").exists()
    assert (tmp_path / "results_cold_start_router.json").exists()
    namespace: dict = {}
    exec((tmp_path / "predictor.py").read_text(encoding="utf-8"), namespace)
    bundle = namespace["load_bundle"](
        tmp_path / "experimental_cold_start_model.joblib"
    )
    record = {name: 1.0 for name in bundle["required_input_fields"]}
    record.update(
        {
            "as_of_date": "2026-09-21",
            "d_observed_days_so_far": 3,
            "d_current_failure_state": False,
            "тип_датчика": "type",
            "тип_инж_системы": "type",
        }
    )
    prediction = namespace["predict"]([record], bundle)[0]
    assert 0 <= prediction["score"] <= 1
    assert prediction["window_start"] == "2026-09-23"
    assert prediction["decision_status"] == "experimental_shadow"
    example = json.loads((tmp_path / "example_input.json").read_text(encoding="utf-8"))
    nullable_prediction = namespace["predict"]([example], bundle)[0]
    assert 0 <= nullable_prediction["score"] <= 1
    requirements = (tmp_path / "backend_model_requirements.txt").read_text(
        encoding="utf-8"
    )
    assert requirements.splitlines() == [
        "joblib>=1.3,<2",
        "lightgbm>=4.4,<5",
        "numpy>=1.26,<3",
        "pandas>=2.1,<3",
        "scikit-learn==1.6.1",
    ]
    record["d_current_failure_state"] = True
    ineligible = namespace["predict"]([record], bundle)[0]
    assert ineligible["score"] is None
    assert ineligible["is_alert_candidate"] is False
