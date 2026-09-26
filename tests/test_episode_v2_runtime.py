"""Contracts for experiment 13: strict onset target v2 and causal cadence features."""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import re
import sys

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

import episode_v2_runtime as v2  # noqa: E402
import pre2025_audit_runtime as audit  # noqa: E402
from test_pre2025_audit_runtime import _write_fixture  # noqa: E402


@pytest.fixture(scope="module")
def presence_panel() -> pl.DataFrame:
    """Синтетика с семантикой v1 «наличие в D+2»: часть positives начинается уже в D+1."""
    panel = audit.synthetic_panel(n_channels=160, seed=11)
    nxt = panel.select(
        "d_channel_key", (pl.col("d_cutoff_date") - pl.duration(days=1)).alias("d_cutoff_date"),
        (pl.col("d_failure_state_event_count_24h") > 0).alias("_d1"),
    )
    return (
        panel.join(nxt, on=["d_channel_key", "d_cutoff_date"], how="left")
        .with_columns(
            pl.when(pl.col(audit.TARGET).is_not_null() & pl.col("_d1").fill_null(False))
            .then(pl.lit(1, pl.Int8)).otherwise(pl.col(audit.TARGET)).alias(audit.TARGET)
        )
        .drop("_d1")
    )


def test_self_tests_pass() -> None:
    assert all(v2.run_v2_self_tests().values())


def test_v2_excludes_every_dplus1_failure_and_keeps_others(presence_panel) -> None:
    out, report = v2.add_v2_target(presence_panel)
    assert report["excluded_dplus1_failure_v1_positives"] > 0
    nxt = presence_panel.select(
        "d_channel_key", (pl.col("d_cutoff_date") - pl.duration(days=1)).alias("d_cutoff_date"),
        (pl.col("d_failure_state_event_count_24h") > 0).alias("_d1"))
    joined = out.join(nxt, on=["d_channel_key", "d_cutoff_date"], how="left")
    assert joined.filter(pl.col("_d1").fill_null(False))["target_v2"].is_null().all()
    kept = joined.filter(~pl.col("_d1").fill_null(False) & pl.col(audit.TARGET).is_not_null())
    assert (kept["target_v2"] == kept[audit.TARGET]).all()


def test_cadence_features_are_causal(presence_panel) -> None:
    cut = presence_panel["d_cutoff_date"].min() + timedelta(days=900)
    base = v2.add_cadence_features(presence_panel)
    changed = v2.add_cadence_features(presence_panel.with_columns(
        pl.when(pl.col("d_cutoff_date") > cut).then(pl.lit(999.0))
        .otherwise(pl.col("d_event_count_24h")).alias("d_event_count_24h")))
    key = ["d_channel_key", "d_cutoff_date"]
    a = base.filter(pl.col("d_cutoff_date") <= cut).sort(key).select(v2.CADENCE_FEATURES)
    b = changed.filter(pl.col("d_cutoff_date") <= cut).sort(key).select(v2.CADENCE_FEATURES)
    assert a.equals(b)


def test_feature_sets_exclude_calendar_identity_and_targets() -> None:
    for name, feats in v2.FEATURE_SETS.items():
        assert not ({"d_month", "d_weekday"} & set(feats)), name
        audit.assert_safe_features(feats + list(audit.CATEGORICAL_FEATURES))
    assert not (set(audit.RECURRENCE) & set(v2.FEATURE_SETS["v2_cadence_no_recurrence"]))


def test_smoke_end_to_end_aggregates_only(tmp_path, monkeypatch, presence_panel) -> None:
    data = _write_fixture(tmp_path / "data", presence_panel)
    monkeypatch.setenv("LDT_KAGGLE_DATA_DIR", str(data))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    result = v2.run_episode_v2(v2.make_config_v2("SMOKE", {"smoke_channel_share": 3, "bootstrap_reps": 20}))
    assert result["status"] == "completed_smoke_non_comparable"
    assert result["target_audit"]["share_of_v1_positives_started_on_dplus1"] > 0
    assert set(result["hypotheses"]) >= {"E1_v2_target_has_support", "E2_cadence_improves_primary",
                                         "E3_cadence_replaces_recurrence"}
    assert result["selection"]["selected"]
    keys = {str(k) for k in presence_panel["d_channel_key"].unique()} | {str(k) for k in presence_panel["d_object_key"].unique()}
    for name in ("results_failure_onset_v2.json", "summary_failure_onset_v2_ru.md"):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert not (set(re.findall(r"[A-Za-z0-9_\-]+", text)) & keys)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["results_failure_onset_v2.json", "summary_failure_onset_v2_ru.md"]


def test_rows_after_2024_do_not_affect_results(tmp_path, monkeypatch, presence_panel) -> None:
    changed = presence_panel.with_columns(
        pl.when(pl.col("d_cutoff_date") >= pl.date(2025, 1, 1)).then(1 - pl.col(audit.TARGET))
        .otherwise(pl.col(audit.TARGET)).cast(pl.Int8).alias(audit.TARGET))
    results = []
    for name, panel in (("a", presence_panel), ("b", changed)):
        monkeypatch.setenv("LDT_KAGGLE_DATA_DIR", str(_write_fixture(tmp_path / name, panel)))
        monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / f"o{name}"))
        r = json.loads(json.dumps(v2.run_episode_v2(v2.make_config_v2("SMOKE", {"smoke_channel_share": 3, "bootstrap_reps": 20}))))
        for k in ("runtime_seconds", "environment", "panel"):
            r.pop(k, None)
        results.append(r)
    assert results[0] == results[1]


def test_generated_notebook_embeds_both_runtimes_and_compiles() -> None:
    path = ROOT / "notebooks" / "kaggle" / "13_failure_onset_v2_cadence_cpu.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    for module in ("pre2025_audit_runtime.py", "episode_v2_runtime.py"):
        assert (MODULE_DIR / module).read_text(encoding="utf-8").strip() in source, f"regenerate: {module}"
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), str(path), "exec")
