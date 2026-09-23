"""Contracts for the de-identified Kaggle package and standalone notebooks."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

from kaggle_runtime import (  # noqa: E402
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    PANEL_SCHEMA_VERSION,
    REQUIRED_PANEL_COLUMNS,
    feature_columns,
    load_panel,
    sha256_file,
)
from prepare_kaggle_package import deidentify_panel  # noqa: E402
from train_baseline import _split  # noqa: E402


def _panel_row(year: int) -> dict:
    cutoff = date(year, 8, 1)
    row = {
        "ид_канала_данных": f"raw-channel-{year}",
        "ид_объект": f"raw-object-{year}",
        "d_cutoff_date": cutoff,
        "d_target_start_date": date(year, 8, 3),
        "d_target_end_date_exclusive": date(year, 8, 4),
        "d_future_failure_event_date": None,
        "d_future_alarm_event_date": None,
        "d_year": year,
        "target_failure_state_onset_24h": 0,
        "target_alarm_onset_24h": 0,
    }
    row.update({name: 0.0 for name in NUMERIC_FEATURES})
    row.update({name: "type" for name in CATEGORICAL_FEATURES})
    return row


def test_split_rejects_panel_without_boundary_contract() -> None:
    import polars as pl

    frame = pl.DataFrame(
        {"d_year": [2024], "target_failure_state_onset_24h": [0]}
    )
    with pytest.raises(ValueError, match="rebuild"):
        _split(frame, "target_failure_state_onset_24h", include_2021=False)


def test_default_features_exclude_raw_and_pseudonymous_object_identity() -> None:
    _, _, features = feature_columns("safe_recurrence")
    assert "ид_объект" not in features
    assert "d_object_key" not in features
    _, ablation_categories, _ = feature_columns("with_object_key_ablation")
    assert "d_object_key" in ablation_categories


def test_deidentification_removes_raw_ids_and_2026() -> None:
    import polars as pl

    raw = pl.DataFrame([_panel_row(2025), _panel_row(2026)])
    exported = deidentify_panel(raw, b"fixed-test-secret")
    assert exported.height == 1
    assert "ид_канала_данных" not in exported.columns
    assert "ид_объект" not in exported.columns
    assert exported["d_channel_key"].item().startswith("ch_")
    assert exported["d_object_key"].item().startswith("obj_")
    assert exported["d_year"].max() == 2025


def test_manifest_loader_rejects_tampered_data(tmp_path: Path) -> None:
    import polars as pl

    row = _panel_row(2025)
    row["d_channel_key"] = "ch_test"
    row["d_object_key"] = "obj_test"
    class SafePopDict(dict):
        def pop(self, key, *args):  # pragma: no cover - encoding-safe test helper
            return super().pop(key, None)

    row = SafePopDict(row)
    row.pop("ид_кана_данных")
    row.pop("ид_объект")
    frame = pl.DataFrame([row]).select(sorted(REQUIRED_PANEL_COLUMNS))
    data_path = tmp_path / "panel.parquet"
    frame.write_parquet(data_path)
    manifest = {
        "panel_schema_version": PANEL_SCHEMA_VERSION,
        "contains_2026_rows": False,
        "raw_identifiers_included": False,
        "data_file": data_path.name,
        "data_sha256": sha256_file(data_path),
        "rows": 1,
    }
    (tmp_path / "panel_manifest_v2.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    loaded, _, _ = load_panel(tmp_path)
    assert loaded.height == 1
    data_path.write_bytes(data_path.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="сумма"):
        load_panel(tmp_path)


def test_generated_notebooks_are_standalone_and_have_expected_devices() -> None:
    directory = ROOT / "notebooks" / "kaggle"
    expected = {
        "01_rule_cpu_for_colleague.ipynb": "none",
        "02_lightgbm_cpu_for_colleague.ipynb": "none",
        "03_logistic_cpu_for_mi.ipynb": "none",
        "04_catboost_gpu_for_mi.ipynb": "gpu",
    }
    for name, accelerator in expected.items():
        notebook = json.loads((directory / name).read_text(encoding="utf-8"))
        source = "".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        assert "panel_manifest_v2.json" in source
        assert "run_model" in source
        assert "/kaggle/input" in source
        assert "Mi/hackatons" not in source
        assert notebook["metadata"]["kaggle"]["accelerator"] == accelerator


def test_all_notebooks_execute_on_synthetic_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    rows = []
    for year, month in [
        (2019, 1),
        (2020, 1),
        (2021, 1),
        (2022, 1),
        (2023, 1),
        (2024, 1),
        (2025, 1),
        (2025, 8),
    ]:
        for day in range(1, 21):
            cutoff = date(year, month, day)
            positive = int(day % 5 == 0)
            row = {
                "d_channel_key": f"ch_{day % 7}",
                "d_object_key": f"obj_{day % 4}",
                "d_cutoff_date": cutoff,
                "d_target_start_date": date.fromordinal(cutoff.toordinal() + 2),
                "d_target_end_date_exclusive": date.fromordinal(cutoff.toordinal() + 3),
                "d_future_failure_event_date": (
                    date.fromordinal(cutoff.toordinal() + 2) if positive else None
                ),
                "d_future_alarm_event_date": (
                    date.fromordinal(cutoff.toordinal() + 2) if positive else None
                ),
                "d_year": year,
                "target_failure_state_onset_24h": positive,
                "target_alarm_onset_24h": positive,
            }
            for index, name in enumerate(NUMERIC_FEATURES):
                row[name] = (
                    True
                    if name == "d_catalogue_match"
                    else float((day + index + positive) % 13)
                )
            row.update({name: f"type_{day % 3}" for name in CATEGORICAL_FEATURES})
            rows.append(row)
    panel = pl.DataFrame(rows)
    data_path = tmp_path / "panel.parquet"
    panel.write_parquet(data_path)
    manifest = {
        "panel_schema_version": PANEL_SCHEMA_VERSION,
        "contains_2026_rows": False,
        "raw_identifiers_included": False,
        "data_file": data_path.name,
        "data_sha256": sha256_file(data_path),
        "rows": panel.height,
        "date_min": str(panel["d_cutoff_date"].min()),
        "date_max": str(panel["d_cutoff_date"].max()),
    }
    (tmp_path / "panel_manifest_v2.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    monkeypatch.setenv("LDT_KAGGLE_DATA_DIR", str(tmp_path))

    for notebook_path in sorted((ROOT / "notebooks" / "kaggle").glob("*.ipynb")):
        if not notebook_path.name[:2] in {"01", "02", "03", "04"}:
            # Specialized notebooks 06+ have separate contract tests.
            continue
        payload = json.loads(notebook_path.read_text(encoding="utf-8"))
        code = [
            "".join(cell["source"])
            for cell in payload["cells"]
            if cell["cell_type"] == "code"
        ]
        for source in code:
            compile(source, notebook_path.name, "exec")
        model = notebook_path.stem.split("_")[1]
        namespace = {
            "CONFIG": {
                "run_mode": "smoke",
                "target": "target_failure_state_onset_24h",
                "feature_variant": "safe_recurrence",
                "negative_to_positive_ratio": 20,
                "minimum_precision": 0.20,
                "alert_budget_per_day": 50,
                "cooldown_hours": 72,
                "random_seed": 17,
                "iterations": 30,
                "catboost_task_type": "CPU",
            },
            "MODEL_NAME": model,
            "OUTPUT_DIR": str(tmp_path / model),
        }
        runtime = next(source for source in code if "PANEL_SCHEMA_VERSION" in source)
        run = next(source for source in code if "result = run_model(panel" in source)
        finish = next(source for source in code if "save_validation_charts" in source and "Path(OUTPUT_DIR)" in source)
        exec(runtime, namespace)
        exec(run, namespace)
        exec(finish, namespace)
        assert (tmp_path / model / f"results_{model}.json").exists()
        assert (tmp_path / model / f"charts_{model}_2025_h2.png").exists()
