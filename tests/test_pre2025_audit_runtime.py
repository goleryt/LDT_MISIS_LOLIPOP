"""Contracts for notebook 05: pre-2025 baseline/leakage/propensity audit."""

from __future__ import annotations

from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

import pre2025_audit_runtime as audit  # noqa: E402


def _write_fixture(root: Path, panel: pl.DataFrame, bad_hash: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data = root / "panel_v2.parquet"
    panel.write_parquet(data, compression="zstd")
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    manifest = {
        "panel_schema_version": "2.0", "data_file": data.name,
        "data_sha256": "0" * 64 if bad_hash else digest, "rows": panel.height,
        "contains_2026_rows": False, "raw_identifiers_included": False,
        "date_min": str(panel["d_cutoff_date"].min()), "date_max": str(panel["d_cutoff_date"].max()),
    }
    (root / "panel_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def base_panel() -> pl.DataFrame:
    return audit.synthetic_panel(n_channels=160, seed=7)


def _run(monkeypatch, data_dir: Path, out_dir: Path, **overrides):
    monkeypatch.setenv("LDT_KAGGLE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(out_dir))
    config = audit.make_config("SMOKE", {"smoke_channel_share": 3, "bootstrap_reps": 20, **overrides})
    return audit.run_research(config)


def _strip(result: dict) -> dict:
    result = json.loads(json.dumps(result))
    for key in ("runtime", "environment", "panel"):
        result.pop(key, None)
    return result


def test_self_tests_pass() -> None:
    assert all(audit.run_self_tests().values())


def test_smoke_end_to_end_writes_only_aggregates(tmp_path, monkeypatch, base_panel) -> None:
    data = _write_fixture(tmp_path / "data", base_panel)
    result = _run(monkeypatch, data, tmp_path / "out")
    assert result["status"] == "completed_smoke_non_comparable"
    assert result["comparability"] == "non_comparable"
    keys = {str(k) for k in base_panel["d_channel_key"].unique()} | {str(k) for k in base_panel["d_object_key"].unique()}
    for name in ("research_results_pre2025.json", "research_summary_ru.md"):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert not (set(re.findall(r"[A-Za-z0-9_\-]+", text)) & keys), name
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["research_results_pre2025.json", "research_summary_ru.md"]
    # Все модели прямого сравнения оценены на одних и тех же validation-строках.
    for fold in result["folds"].values():
        prints = {json.dumps(m["validation_row_fingerprint"], sort_keys=True) for m in fold["models"].values()}
        assert len(prints) == 1
        assert set(fold["clean_history"]) == {"native", "common_k30"}
        assert len({v["rows"] for v in fold["clean_history"]["common_k30"].values()}) == 1


def test_rows_after_2024_do_not_affect_results(tmp_path, monkeypatch, base_panel) -> None:
    changed = base_panel.with_columns(
        pl.when(pl.col("d_cutoff_date") >= pl.date(2025, 1, 1))
        .then(1 - pl.col(audit.TARGET)).otherwise(pl.col(audit.TARGET)).cast(pl.Int8).alias(audit.TARGET)
    )
    a = _run(monkeypatch, _write_fixture(tmp_path / "a", base_panel), tmp_path / "oa")
    b = _run(monkeypatch, _write_fixture(tmp_path / "b", changed), tmp_path / "ob")
    assert _strip(a) == _strip(b)


def test_validation_labels_do_not_drive_thresholds_calibration_or_m(tmp_path, monkeypatch, base_panel) -> None:
    flipped = base_panel.with_columns(
        pl.when(pl.col("d_cutoff_date") >= pl.date(2024, 7, 1))
        .then(1 - pl.col(audit.TARGET)).otherwise(pl.col(audit.TARGET)).cast(pl.Int8).alias(audit.TARGET)
    )
    a = _run(monkeypatch, _write_fixture(tmp_path / "a", base_panel), tmp_path / "oa")["folds"]["fold_2024"]
    b = _run(monkeypatch, _write_fixture(tmp_path / "b", flipped), tmp_path / "ob")["folds"]["fold_2024"]
    for model in a["models"]:
        assert a["models"][model]["point"]["threshold"] == b["models"][model]["point"]["threshold"], model
    assert a["propensity"]["m_selection_on_calibration_h1"] == b["propensity"]["m_selection_on_calibration_h1"]
    assert a["b0_prevalence_pre_validation"] == b["b0_prevalence_pre_validation"]
    assert a["coverage"]["supported_types"] == b["coverage"]["supported_types"]


def test_hash_mismatch_stops_with_diagnostics(tmp_path, monkeypatch, base_panel) -> None:
    result = _run(monkeypatch, _write_fixture(tmp_path / "d", base_panel.head(5000), bad_hash=True), tmp_path / "o")
    assert result["status"] == "contract_failed" and "SHA-256" in result["stop_reason"]
    assert (tmp_path / "o" / "research_summary_ru.md").exists()


def test_m0_failure_stops_all_experiments(tmp_path, monkeypatch, base_panel) -> None:
    import numpy as np

    monkeypatch.setattr(audit.LightGBMModel, "raw", lambda self, frame: np.full(frame.height, np.nan))
    result = _run(monkeypatch, _write_fixture(tmp_path / "d", base_panel), tmp_path / "o")
    assert result["status"] == "m0_reproduction_failed"
    assert "selection" not in result and "hypotheses" not in result


def test_generated_notebook_is_standalone_cpu_and_compiles() -> None:
    path = ROOT / "notebooks" / "kaggle" / "05_lightgbm_propensity_research_cpu.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    runtime = (MODULE_DIR / "pre2025_audit_runtime.py").read_text(encoding="utf-8")
    assert runtime.strip() in source, "notebook must embed the runtime verbatim; regenerate it"
    assert "from pre2025_audit_runtime" not in source and "/home/" not in source
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), str(path), "exec")
