"""Contracts for experiment 05W: Moscow weather features in notebook 05."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

import pre2025_audit_runtime as audit  # noqa: E402
import weather_data  # noqa: E402
import weather_runtime as wr  # noqa: E402
from test_pre2025_audit_runtime import _write_fixture  # noqa: E402


@pytest.fixture(scope="module")
def panel() -> pl.DataFrame:
    return audit.synthetic_panel(n_channels=120, seed=5)


def test_self_tests_pass() -> None:
    assert all(wr.run_weather_self_tests().values())


def test_weather_blob_integrity_and_tamper_detection(monkeypatch) -> None:
    assert len(weather_data.weather_csv_bytes()) == 115620
    monkeypatch.setattr(weather_data, "WEATHER_CSV_SHA256", "0" * 64)
    with pytest.raises(ValueError):
        weather_data.weather_csv_bytes()


def test_join_covers_all_pre2025_dates(panel) -> None:
    feats = wr.weather_features(wr.load_weather())
    labelled = panel.filter(pl.col(audit.TARGET).is_not_null() & (pl.col("d_year") <= 2024))
    out, report = wr.attach_weather(labelled, feats)
    assert out.height == labelled.height
    assert report["null_share"]["w_t_mean_d0"] == 0 and report["null_share"]["wp_t_mean_d0"] == 0


def test_smoke_end_to_end_aggregates_only(tmp_path, monkeypatch, panel) -> None:
    monkeypatch.setenv("LDT_KAGGLE_DATA_DIR", str(_write_fixture(tmp_path / "data", panel)))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    result = wr.run_weather(wr.make_config_weather("SMOKE", {"smoke_channel_share": 2, "bootstrap_reps": 20}))
    assert result["status"] == "completed_smoke_non_comparable", result.get("stop_reason")
    assert set(result["hypotheses"]) >= {"W1_real_weather_beats_placebo_pr_auc", "W2_oracle_forecast_adds_over_obs_pr_auc",
                                         "W3_weather_replaces_calendar_not_worse_than_M0"}
    assert "W2_obs_fcst_oracle" not in result["selection"]["candidates"]
    for c in result["selection"]["candidates"].values():
        assert "g6_beats_own_placebo_pr_auc" in c["gates"]
    keys = {str(k) for k in panel["d_channel_key"].unique()} | {str(k) for k in panel["d_object_key"].unique()}
    for name in ("results_weather_pre2025.json", "summary_weather_ru.md"):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert not (set(re.findall(r"[A-Za-z0-9_\-]+", text)) & keys)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["results_weather_pre2025.json", "summary_weather_ru.md"]


def test_generated_notebook_embeds_runtimes_and_compiles() -> None:
    path = ROOT / "notebooks" / "kaggle" / "05_lightgbm_propensity_research_cpu.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    import generate_pre2025_audit_notebook as gen

    for module in ("pre2025_audit_runtime.py", "weather_data.py"):
        assert (MODULE_DIR / module).read_text(encoding="utf-8").strip() in source, f"regenerate: {module}"
    assert gen.embeddable((MODULE_DIR / "weather_runtime.py").read_text(encoding="utf-8")).strip() in source
    assert "from pre2025_audit_runtime" not in source and "from weather_data" not in source
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), str(path), "exec")
