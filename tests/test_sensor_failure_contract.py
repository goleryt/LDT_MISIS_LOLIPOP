"""Tests that do not require access to sensitive project data."""

from pathlib import Path
from datetime import date, timedelta
import sys

import pytest


MODULE_DIR = Path(__file__).parents[1] / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

from panel import load_failure_state_dictionary  # noqa: E402
from panel import build_panel  # noqa: E402
from train_baseline import (  # noqa: E402
    CATEGORICAL_FEATURES,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    _split,
    _train_models,
    assert_leakage_safe_features,
)
from evaluation import build_alert_episodes, evaluate_alert_episodes  # noqa: E402


def test_default_failure_dictionary_is_explicit_proxy_configuration() -> None:
    config = load_failure_state_dictionary(
        MODULE_DIR / "config" / "failure_state_dictionary.json"
    )
    assert config["default"] == ["Неисправен", "Обесточен"]
    assert "not confirmed physical failures" in config["description"]


def test_declared_model_features_pass_leakage_guard() -> None:
    assert_leakage_safe_features(MODEL_FEATURES)


@pytest.mark.parametrize(
    "column",
    [
        "target_failure_state_onset_24h",
        "target_alarm_onset_24h",
        "d_future_alarm",
        "d_event_time",
        "ид_канала_данных",
        "значение_датчика",
    ],
)
def test_leakage_guard_rejects_forbidden_columns(column: str) -> None:
    with pytest.raises(ValueError):
        assert_leakage_safe_features([column])


def test_panel_keeps_censored_horizons_null(tmp_path: Path) -> None:
    import polars as pl

    header = (
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
    )
    for year in range(2019, 2027):
        rows = [f"{year}00,c_other,{year}-02-01,08:00:00,f,Норма"]
        if year == 2024:
            rows.extend(
                [
                    "2401,c_positive,2024-03-01,08:00:00,f,Норма",
                    "2402,c_positive,2024-03-02,08:00:00,f,Норма",
                    "2403,c_positive,2024-03-03,08:00:00,t,Неисправен",
                    "2404,c_positive,2024-03-04,08:00:00,f,Норма",
                    "2411,c_censored,2024-03-01,08:00:00,f,Норма",
                ]
            )
        (tmp_path / f"ext-journal-{year}.csv").write_text(
            header + "\n".join(rows) + "\n", encoding="utf-8-sig"
        )

    catalogue = (
        "ид_канала_данных,тип_инж_системы,тип_датчика,"
        "тег_инженерной_системы,название_датчика,ид_объект\n"
        "c_other,system,sensor,tag_1,name_1,object_1\n"
        "c_positive,system,sensor,tag_2,name_2,object_1\n"
        "c_censored,system,sensor,tag_3,name_3,object_1\n"
    )
    (tmp_path / "справочник_каналов_датчиков.csv").write_text(
        catalogue, encoding="utf-8-sig"
    )
    panel, audit = build_panel(
        tmp_path,
        MODULE_DIR / "config" / "failure_state_dictionary.json",
        latency_minutes=0,
    )

    positive = panel.filter(
        (pl.col("ид_канала_данных") == "c_positive")
        & (pl.col("d_cutoff_date") == pl.date(2024, 3, 1))
    )
    assert positive["target_failure_state_onset_24h"].item() == 1

    already_failed = panel.filter(
        (pl.col("ид_канала_данных") == "c_positive")
        & (pl.col("d_cutoff_date") == pl.date(2024, 3, 3))
    )
    assert already_failed["target_failure_state_onset_24h"].item() is None

    censored = panel.filter(
        (pl.col("ид_канала_данных") == "c_censored")
        & (pl.col("d_cutoff_date") == pl.date(2024, 3, 1))
    )
    assert censored["target_failure_state_onset_24h"].item() is None
    assert audit["leakage_audit"]["feature_rows_after_cutoff"] == 0
    assert audit["target_lead_hours"] == 24
    assert positive["d_target_start_date"].item() == date(2024, 3, 3)


def test_three_baselines_run_on_synthetic_temporal_splits(tmp_path: Path) -> None:
    from types import SimpleNamespace

    import polars as pl

    rows = []
    for year in [2019, 2021, 2022, 2025, 2026]:
        cutoffs = [date(year, 1, day) for day in range(1, 31)]
        if year == 2025:
            cutoffs += [date(year, 8, day) for day in range(1, 31)]
        for day, cutoff in enumerate(cutoffs, start=1):
            target = int(day % 5 == 0)
            row = {
                "ид_канала_данных": f"channel_{day % 4}",
                "d_cutoff_date": cutoff,
                "d_target_start_date": cutoff + timedelta(days=2),
                "d_target_end_date_exclusive": cutoff + timedelta(days=3),
                "d_year": year,
                "target_failure_state_onset_24h": target,
                "target_alarm_onset_24h": int(day % 7 == 0),
            }
            for index, name in enumerate(NUMERIC_FEATURES):
                row[name] = float((day + index + target) % 11)
            row.update(
                {
                    CATEGORICAL_FEATURES[0]: f"system_{day % 2}",
                    CATEGORICAL_FEATURES[1]: f"sensor_{day % 3}",
                }
            )
            rows.append(row)
    frame = pl.DataFrame(rows).with_columns(
        pl.col("d_cutoff_date").cast(pl.Date)
    )
    splits = _split(frame, "target_failure_state_onset_24h", include_2021=False)
    args = SimpleNamespace(
        target="target_failure_state_onset_24h",
        negative_to_positive_ratio=20,
        random_seed=17,
        catboost_iterations=5,
        catboost_threads=1,
        minimum_precision=0.10,
        bootstrap_repeats=2,
    )
    result = _train_models(splits, args, tmp_path)
    assert set(result["metrics"]["validation_2025_h2"]) == {
        "rule",
        "logistic",
        "catboost",
    }
    assert (tmp_path / "catboost.cbm").exists()
    assert (tmp_path / "logistic.joblib").exists()


def test_split_purges_targets_crossing_period_boundary() -> None:
    import polars as pl

    rows = []
    for cutoff, target_end in [
        (date(2024, 12, 28), date(2024, 12, 31)),
        (date(2024, 12, 31), date(2025, 1, 3)),
        (date(2025, 12, 31), date(2026, 1, 3)),
        (date(2026, 6, 28), date(2026, 7, 1)),
    ]:
        rows.append(
            {
                "d_year": cutoff.year,
                "d_cutoff_date": cutoff,
                "d_target_start_date": cutoff + timedelta(days=2),
                "d_target_end_date_exclusive": target_end,
                "target_failure_state_onset_24h": 0,
            }
        )
    frame = pl.DataFrame(rows)
    splits = _split(frame, "target_failure_state_onset_24h", include_2021=False)
    assert splits["train"].height == 1
    assert splits["calibration_2025_h1"].height == 0
    assert splits["validation_2025_h2"].height == 0
    assert splits["test_2026_h1"].height == 1


def test_alerts_are_budgeted_and_deduplicated_as_episodes() -> None:
    import pandas as pd

    frame = pd.DataFrame(
        {
            "ид_канала_данных": ["c1", "c1", "c1", "c2"],
            "d_cutoff_date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-05", "2025-01-01"]
            ),
            "d_target_start_date": pd.to_datetime(
                ["2025-01-03", "2025-01-04", "2025-01-07", "2025-01-03"]
            ),
            "d_target_end_date_exclusive": pd.to_datetime(
                ["2025-01-04", "2025-01-05", "2025-01-08", "2025-01-04"]
            ),
            "target_failure_state_onset_24h": [1, 0, 0, 0],
            "d_future_failure_event_date": pd.to_datetime(
                ["2025-01-03", None, None, None]
            ),
            "тип_датчика": ["sensor", "sensor", "sensor", "sensor"],
        }
    )
    probability = [0.9, 0.8, 0.7, 0.6]
    alerts = build_alert_episodes(
        frame,
        probability,
        threshold=0.0,
        budget_per_day=2,
        cooldown_hours=72,
    )
    assert len(alerts) == 3
    metrics = evaluate_alert_episodes(
        frame,
        probability,
        target="target_failure_state_onset_24h",
        threshold=0.0,
        budget_per_day=2,
        cooldown_hours=72,
    )
    assert metrics["overall"]["proxy_events"] == 1
    assert metrics["overall"]["matched_alerts"] == 1
    assert metrics["overall"]["recall"] == 1.0
