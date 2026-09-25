"""Contract tests for notebooks 07--12 and their shared weak-label runtime."""

from __future__ import annotations

from datetime import date, timedelta
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

from missing_targets_runtime import (  # noqa: E402
    ACCESS_TARGET,
    DERIVED_SCHEMA_VERSION,
    DROPOUT_SELECTION_CONTRACT_VERSION,
    DROPOUT_TARGET,
    ELEMENT_NUMERIC_FEATURES,
    FIRE_TARGET,
    GENERIC_ALARM_TARGET,
    OBJECT_FEATURES,
    SCORECARD_INPUTS,
    build_missing_target_panels,
    build_missing_targets_scorecard,
    export_missing_target_bundle,
    load_missing_target_bundle,
    predict_dropout_bundle,
    predict_scenario_bundle,
    run_dropout_experiment,
    run_flood_synthetic_challenge,
)


def _source_row(
    channel: str,
    object_key: str,
    cutoff: date,
    sensor_type: str,
    alarm: int = 0,
) -> dict:
    row = {
        "d_channel_key": channel,
        "d_object_key": object_key,
        "d_cutoff_date": cutoff,
        "d_target_start_date": cutoff + timedelta(days=2),
        "d_target_end_date_exclusive": cutoff + timedelta(days=3),
        "d_future_failure_event_date": None,
        "d_future_alarm_event_date": None,
        "d_year": cutoff.year,
        "target_failure_state_onset_24h": 0,
        "target_alarm_onset_24h": 0,
        "тип_датчика": sensor_type,
        "тип_инж_системы": "тест",
        "d_event_count_24h": 1.0,
        "d_alarm_count_24h": float(alarm),
        "d_alarm_share_24h": float(alarm),
        "d_failure_state_event_count_24h": 0.0,
        "d_value_numeric_mean_24h": 1.0,
        "d_value_numeric_min_24h": 1.0,
        "d_value_numeric_max_24h": 1.0,
        "d_value_numeric_std_24h": 0.0,
        "d_value_numeric_last": 1.0,
        "d_state_n_unique_24h": 1.0,
        "d_gap_days_since_previous": 1.0,
        "d_event_count_previous_24h": 1.0,
        "d_alarm_count_previous_24h": 0.0,
        "d_alarm_share_previous_24h": 0.0,
        "d_value_numeric_previous": 1.0,
        "d_days_since_failure_state_event": None,
        "d_weekday": cutoff.weekday(),
        "d_month": cutoff.month,
        "d_catalogue_match": True,
    }
    return row


def _fixture_panel() -> object:
    import polars as pl

    start = date(2024, 1, 1)
    rows: list[dict] = []
    # Peer is observed every day. Target channel is silent D+2..D+4 and returns D+5.
    for offset in range(8):
        current = start + timedelta(days=offset)
        rows.append(_source_row("peer", "obj", current, "Датчик движения"))
        rows.append(_source_row("unrelated", "obj-unrelated", current, "Переключатель"))
        if offset not in {2, 3, 4}:
            rows.append(_source_row("drop", "obj", current, "КД Дверь"))
    # Two access types alarm on D+2 relative to the first day.
    rows.append(_source_row("access-2", "obj", start + timedelta(days=2), "Стекло", 1))
    rows.append(_source_row("access-3", "obj", start + timedelta(days=2), "КД АВ", 1))
    # Two fire types alarm on the same target day.
    rows.append(_source_row("fire-1", "obj", start + timedelta(days=2), "Датчик дыма", 1))
    rows.append(_source_row("fire-2", "obj", start + timedelta(days=2), "Тепловой датчик", 1))
    return pl.DataFrame(rows)


def test_future_proxy_labels_and_dropout_censoring_are_causal() -> None:
    import polars as pl

    panel = _fixture_panel()
    object_day, channel = build_missing_target_panels(panel)
    first = object_day.filter(pl.col("d_cutoff_date") == date(2024, 1, 1)).row(0, named=True)
    assert first[ACCESS_TARGET] == 1
    assert first[FIRE_TARGET] == 1
    assert first[GENERIC_ALARM_TARGET] == 1
    dropout = channel.filter(
        (pl.col("d_channel_key") == "drop")
        & (pl.col("d_cutoff_date") == date(2024, 1, 1))
    ).row(0, named=True)
    assert dropout[DROPOUT_TARGET] == 1
    assert dropout["d_dropout_peer_evidence_complete"] is True
    tail = object_day.filter(pl.col("d_cutoff_date") == date(2024, 1, 8)).row(0, named=True)
    assert tail[ACCESS_TARGET] is None
    unrelated = object_day.filter(
        (pl.col("d_object_key") == "obj-unrelated")
        & (pl.col("d_cutoff_date") == date(2024, 1, 1))
    ).row(0, named=True)
    assert unrelated[ACCESS_TARGET] is None
    assert unrelated[FIRE_TARGET] is None
    assert not {"d_future_failure_event_date", "target_failure_state_onset_24h"} & set(channel.columns)


def test_future_records_cannot_change_earlier_features() -> None:
    import polars as pl

    panel = _fixture_panel()
    baseline, _ = build_missing_target_panels(panel)
    changed = panel.with_columns(
        pl.when(pl.col("d_cutoff_date") == date(2024, 1, 3))
        .then(pl.lit(9999.0))
        .otherwise(pl.col("d_event_count_24h"))
        .alias("d_event_count_24h")
    )
    rebuilt, _ = build_missing_target_panels(changed)
    selector = (pl.col("d_object_key") == "obj") & (
        pl.col("d_cutoff_date") == date(2024, 1, 1)
    )
    before = baseline.filter(selector).select(OBJECT_FEATURES).row(0)
    after = rebuilt.filter(selector).select(OBJECT_FEATURES).row(0)
    assert before == after


def test_dropout_asof_cohort_does_not_use_future_peer_activity() -> None:
    import polars as pl

    panel = _fixture_panel()
    _, original = build_missing_target_panels(panel)
    changed = panel.filter(
        ~((pl.col("d_cutoff_date") > date(2024, 1, 1)) & (pl.col("d_channel_key") == "peer"))
    )
    _, revised = build_missing_target_panels(changed)
    predicate = (pl.col("d_channel_key") == "drop") & (pl.col("d_cutoff_date") == date(2024, 1, 1))
    assert original.filter(predicate)["d_dropout_asof_eligible"].item() is True
    assert revised.filter(predicate)["d_dropout_asof_eligible"].item() is True
    assert original.filter(predicate)[DROPOUT_TARGET].item() != revised.filter(predicate)[DROPOUT_TARGET].item()


def test_fast_sequence_builder_matches_causal_history() -> None:
    import polars as pl
    from missing_targets_runtime import _build_channel_sequences

    history = pl.DataFrame({
        "d_channel_key": ["a", "b", "a", "a", "b"],
        "d_cutoff_date": [date(2024, 1, 1), date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 3)],
        "d_event_count_24h": [1.0, 10.0, 2.0, 4.0, 30.0],
    })
    selected = pl.DataFrame({
        "d_channel_key": ["a", "b"],
        "d_cutoff_date": [date(2024, 1, 3), date(2024, 1, 3)],
    })
    values, mask = _build_channel_sequences(
        history, selected, ["d_event_count_24h"], 3,
        {"median": np.array([0.0]), "scale": np.array([1.0])},
    )
    np.testing.assert_array_equal(values[:, :, 0], [[0, 1, 2], [0, 10, 20]])
    np.testing.assert_array_equal(mask, [[0, 1, 1], [0, 1, 1]])


def test_bundle_manifest_detects_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    panel = _fixture_panel()
    source_manifest = {
        "panel_schema_version": "2.0",
        "data_sha256": "source-test-hash",
    }
    manifest = export_missing_target_bundle(panel, source_manifest, tmp_path, {"run_mode": "full"})
    assert manifest["schema_version"] == DERIVED_SCHEMA_VERSION
    assert manifest["raw_identifiers_included"] is False
    monkeypatch.setenv("LDT_KAGGLE_DATA_DIR", str(tmp_path))
    object_day, channel, loaded, _ = load_missing_target_bundle(tmp_path)
    assert object_day.height == manifest["rows"]["object_day"]
    assert channel.height == manifest["rows"]["channel_element"]
    assert loaded["sha256"] == manifest["sha256"]
    path = tmp_path / "object_day_panel_v1.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="SHA-256"):
        load_missing_target_bundle(tmp_path)


def test_codex_owned_notebooks_are_standalone_and_device_correct() -> None:
    expected = {
        "07_missing_targets_panel_audit_cpu.ipynb": "none",
        "10_flood_synthetic_anomaly_gpu.ipynb": "none",
        "11_channel_dropout_sequence_gpu.ipynb": "gpu",
        "12_missing_targets_scorecard_cpu.ipynb": "none",
    }
    for name, accelerator in expected.items():
        path = ROOT / "notebooks" / "kaggle" / name
        notebook = json.loads(path.read_text(encoding="utf-8"))
        assert notebook["metadata"]["kaggle"]["accelerator"] == accelerator
        sources = ["".join(cell.get("source", [])) for cell in notebook["cells"]]
        for cell, source in zip(notebook["cells"], sources):
            if source and cell["cell_type"] == "code":
                compile(source, name, "exec")
        joined = "\n".join(sources)
        assert "/kaggle/input" in joined
        assert "Mi/hackatons" not in joined
        assert "ЕДИНСТВЕННАЯ ЯЧЕЙКА" in joined
        assert "confirmed incident" in joined or "physical" in joined or "подтвержд" in joined


@pytest.mark.parametrize(
    ("name", "task"),
    [
        ("08_access_deepsets_gpu.ipynb", "access"),
        ("09_fire_transfer_deepsets_gpu.ipynb", "fire"),
    ],
)
def test_delegated_notebook_can_save_selected_baseline_and_calibration(
    name: str, task: str, tmp_path: Path
) -> None:
    notebook = json.loads((ROOT / "notebooks" / "kaggle" / name).read_text(encoding="utf-8"))
    namespace: dict = {}
    for index in (5, 6):
        exec("".join(notebook["cells"][index]["source"]), namespace)
    artifact = namespace["save_artifact"](
        task,
        "rule",
        {"days_since_feature": "d_days_since_access_corroboration"},
        {"fold_2024": {"thresholds": {"rule": 0.2}, "calibrators": {"rule": {"kind": "identity"}}}},
        tmp_path,
        {"config": {}},
    )
    assert (tmp_path / artifact["file"]).exists()
    calibration = json.loads((tmp_path / artifact["calibration_file"]).read_text(encoding="utf-8"))
    assert calibration["calibrator"]["kind"] == "identity"
    assert calibration["threshold"] == 0.2


def _write_dummy_module(root: Path, module: str, rows: int = 3) -> None:
    import polars as pl

    contract = SCORECARD_INPUTS[module]
    result = {
        "status": "completed",
        "run_mode": "full",
        "source_bundle_sha256": {"object_day": "same-source", "channel_element": "same-source"},
        "target_code": contract["target_code"],
        "score_kind": contract["score_kind"],
        "evidence_level": contract["evidence_level"],
        "selection": {
            "decision_status": "selected_proxy_model",
            "reason_codes": ["TEST"],
            "backend_candidate": True,
            "backend_scenario_score_allowed": True,
        },
    }
    if module == "availability":
        result["selection_contract_version"] = DROPOUT_SELECTION_CONTRACT_VERSION
    if contract.get("optional"):
        result["generator_version"] = "scenario-temporal-1.0"
    (root / contract["result"]).write_text(json.dumps(result), encoding="utf-8")
    entity = contract["entity_column"]
    frame = pl.DataFrame(
        {
            entity: [f"pseudo-{module}-{index}" for index in range(rows)],
            "d_target_start_date": [date(2024, 7, index + 1) for index in range(rows)],
            "d_target_end_date_exclusive": [date(2024, 7, index + 2) for index in range(rows)],
            "score": np.linspace(0.1, 0.9, rows),
            "score_kind": [contract["score_kind"]] * rows,
            "evidence_level": [contract["evidence_level"]] * rows,
        }
    )
    frame.write_parquet(root / contract["predictions"])


def test_scorecard_keeps_targets_separate(tmp_path: Path) -> None:
    import polars as pl

    for module in SCORECARD_INPUTS:
        _write_dummy_module(tmp_path, module)
    output = tmp_path / "output"
    scorecard = build_missing_targets_scorecard(tmp_path, output, {"run_mode": "smoke"})
    assert scorecard["cross_target_averaging"] is False
    assert scorecard["confirmed_incident_probability_available"] is False
    assert scorecard["development_results_only"] is True
    scores = pl.read_parquet(output / "missing_targets_scores.parquet")
    assert scores["target_code"].n_unique() == 6
    assert set(scores["evidence_level"].unique()) == {"E1", "E2", "E4"}
    assert scores["score_exposure_allowed"].all()
    assert scores["score"].null_count() == 0
    assert (output / "missing_targets_router_contract.json").exists()


def test_scorecard_abstains_when_backend_gates_fail(tmp_path: Path) -> None:
    import polars as pl

    for module in SCORECARD_INPUTS:
        _write_dummy_module(tmp_path, module)
    for module, gate in (("flood", "backend_scenario_score_allowed"), ("availability", "backend_candidate")):
        path = tmp_path / SCORECARD_INPUTS[module]["result"]
        result = json.loads(path.read_text(encoding="utf-8"))
        result["selection"][gate] = False
        result["selection"]["reason_codes"] = ["BUDGET_SATURATED" if module == "flood" else "LOW_LABEL_COVERAGE"]
        path.write_text(json.dumps(result), encoding="utf-8")
    output = tmp_path / "output"
    scorecard = build_missing_targets_scorecard(tmp_path, output, {"run_mode": "full"})
    scores = pl.read_parquet(output / "missing_targets_scores.parquet")
    for module in ("flood", "availability"):
        target = SCORECARD_INPUTS[module]["target_code"]
        assert scorecard["modules"][module]["decision_status"] == "abstain"
        assert scorecard["modules"][module]["score_exposure_allowed"] is False
        assert "BACKEND_GATE_FALSE" in scorecard["modules"][module]["reason_codes"]
        blocked = scores.filter(pl.col("target_code") == target)
        assert blocked["score"].null_count() == blocked.height
        assert blocked["research_score"].null_count() == 0
        assert blocked["decision_status"].unique().to_list() == ["abstain"]
        assert blocked["score_exposure_allowed"].unique().to_list() == [False]


def test_scorecard_missing_backend_gate_fails_closed(tmp_path: Path) -> None:
    for module in SCORECARD_INPUTS:
        _write_dummy_module(tmp_path, module)
    path = tmp_path / SCORECARD_INPUTS["access"]["result"]
    result = json.loads(path.read_text(encoding="utf-8"))
    result["selection"].pop("backend_candidate")
    path.write_text(json.dumps(result), encoding="utf-8")
    scorecard = build_missing_targets_scorecard(tmp_path, tmp_path / "output", {"run_mode": "full"})
    assert scorecard["modules"]["access"]["decision_status"] == "abstain"
    assert "BACKEND_GATE_MISSING" in scorecard["modules"]["access"]["reason_codes"]


def test_scorecard_rejects_legacy_dropout_selection(tmp_path: Path) -> None:
    for module in SCORECARD_INPUTS:
        _write_dummy_module(tmp_path, module)
    availability = SCORECARD_INPUTS["availability"]
    path = tmp_path / availability["result"]
    result = json.loads(path.read_text(encoding="utf-8"))
    result.pop("selection_contract_version")
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(RuntimeError, match="устаревший selection contract"):
        build_missing_targets_scorecard(tmp_path, tmp_path / "output", {"run_mode": "full"})


def test_scorecard_rejects_mixed_source_bundles(tmp_path: Path) -> None:
    for module in SCORECARD_INPUTS:
        _write_dummy_module(tmp_path, module)
    fire = SCORECARD_INPUTS["fire"]
    path = tmp_path / fire["result"]
    result = json.loads(path.read_text(encoding="utf-8"))
    result["source_bundle_sha256"]["object_day"] = "other-source"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(RuntimeError, match="разным source bundles"):
        build_missing_targets_scorecard(tmp_path, tmp_path / "output", {"run_mode": "full"})


def test_scorecard_accepts_claude_prediction_and_manifest_shape(tmp_path: Path) -> None:
    import polars as pl

    for module in SCORECARD_INPUTS:
        _write_dummy_module(tmp_path, module)
    for module in ("access", "fire"):
        contract = SCORECARD_INPUTS[module]
        result_path = tmp_path / contract["result"]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["input_contract"] = {
            "source_manifest_sha256": result.pop("source_bundle_sha256")
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")
        prediction_path = tmp_path / contract["predictions"]
        pl.read_parquet(prediction_path).rename({"score": "selected_score"}).write_parquet(
            prediction_path
        )
    scorecard = build_missing_targets_scorecard(
        tmp_path, tmp_path / "output", {"run_mode": "full"}
    )
    assert scorecard["score_rows"] == 18


def test_scorecard_marks_missing_synthetic_as_not_evaluated(tmp_path: Path) -> None:
    for module, contract in SCORECARD_INPUTS.items():
        if not contract.get("optional"):
            _write_dummy_module(tmp_path, module)
    scorecard = build_missing_targets_scorecard(tmp_path, tmp_path / "output", {"run_mode": "full"})
    assert scorecard["modules"]["flood"]["decision_status"] == "not_evaluated"
    assert scorecard["modules"]["access_synthetic"]["prediction_rows"] == 0


def test_delegation_contract_freezes_claude_outputs() -> None:
    text = (ROOT / "docs" / "CLAUDE_DELEGATION_NOTEBOOKS_08_09_RU.md").read_text(
        encoding="utf-8"
    )
    assert "08_access_deepsets_gpu.ipynb" in text
    assert "09_fire_transfer_deepsets_gpu.ipynb" in text
    assert DERIVED_SCHEMA_VERSION in text
    assert "< 20 positives" in text
    assert "not_evaluable" in text


def _object_day_smoke_fixture() -> object:
    import polars as pl

    rows: list[dict] = []
    for year in (2019, 2020, 2022, 2023, 2024):
        for day_index in range(1, 361, 3):
            cutoff = date(year, 1, 1) + timedelta(days=day_index - 1)
            for object_index in range(2):
                row = {
                    "d_object_key": f"obj-{object_index}",
                    "d_cutoff_date": cutoff,
                    "d_target_start_date": cutoff + timedelta(days=2),
                    "d_target_end_date_exclusive": cutoff + timedelta(days=3),
                    "d_year": year,
                }
                for feature_index, feature in enumerate(
                    [
                        "d_access_channel_count",
                        "d_access_alarm_type_count",
                        "d_fire_channel_count",
                        "d_fire_alarm_type_count",
                        "d_ventilation_alarm_count_24h",
                        "d_numeric_max_24h",
                        "d_state_n_unique_max_24h",
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
                ):
                    row[feature] = float((day_index + object_index + feature_index) % 7)
                row["d_flood_channel_count"] = 1.0
                row["d_access_channel_count"] = 1.0
                row["d_fire_channel_count"] = 1.0
                row["d_flood_alarm_count_24h"] = 0.0
                row["d_pump_alarm_count_24h"] = 0.0
                rows.append(row)
    return pl.DataFrame(rows)


def test_flood_smoke_is_e4_and_never_reports_real_pr_auc(tmp_path: Path) -> None:
    result = run_flood_synthetic_challenge(
        _object_day_smoke_fixture(),
        {"sha256": {"object_day": "test"}},
        {
            "run_mode": "smoke",
            "alert_budget_per_day": 1,
            "synthetic_count_per_family": 10,
            "random_seed": 7,
        },
        tmp_path,
    )
    assert result["evidence_level"] == "E4"
    assert result["real_pr_auc_reported"] is False
    assert result["selection"]["backend_incident_model_allowed"] is False
    assert (tmp_path / "results_flood_missing_target.json").exists()
    assert (tmp_path / "predictions_flood_missing_target.parquet").exists()


def test_multitarget_synthetic_challenge_is_e4_and_uses_heldout_family(tmp_path: Path) -> None:
    from missing_targets_runtime import run_multitarget_synthetic_challenge
    import polars as pl

    history = _object_day_smoke_fixture()
    results = run_multitarget_synthetic_challenge(
        history, {"sha256": {"object_day": "test"}},
        {"run_mode": "smoke", "alert_budget_per_day": 1, "synthetic_count_per_family": 10, "random_seed": 7},
        tmp_path,
    )
    assert set(results) == {"access", "fire", "flood"}
    for task, result in results.items():
        assert result["evidence_level"] == "E4"
        assert result["real_pr_auc_reported"] is False
        assert all(fold["heldout_family"] == "2" for fold in result["folds"].values())
        assert all(fold["training_families"] == ["0", "1"] for fold in result["folds"].values())
        assert (tmp_path / f"results_{task}_synthetic_scenario.json").exists()
        assert (tmp_path / f"model_{task}_synthetic_contract.json").exists()
        saved = pl.read_parquet(tmp_path / f"predictions_{task}_synthetic_scenario.parquet").filter(
            pl.col("fold") == "fold_2024"
        )
        frame = history.join(
            saved.select("d_object_key", "d_cutoff_date"),
            on=["d_object_key", "d_cutoff_date"], how="inner",
        )
        replay = predict_scenario_bundle(history, frame, tmp_path, task)
        # GPT 26: сценарий внедрён в историю D−2…D → детекция на D, окно паттерна [D−2; D+1), не D+2
        assert (replay["horizon"] == "detection_at_D").all()
        assert (replay["window_start"] == replay["d_cutoff_date"] - timedelta(days=2)).all()
        assert (replay["window_end_exclusive"] == replay["d_cutoff_date"] + timedelta(days=1)).all()
        comparison = replay.join(
            saved.select("d_object_key", "d_cutoff_date", "selected_score"),
            on=["d_object_key", "d_cutoff_date"],
        )
        np.testing.assert_allclose(
            comparison["score"].to_numpy(), comparison["selected_score"].to_numpy(), atol=1e-6
        )
        if task == "flood":
            contract = json.loads((tmp_path / "model_flood_synthetic_contract.json").read_text(encoding="utf-8"))
            model_path = tmp_path / contract["model_file"]
            model_path.write_bytes(model_path.read_bytes() + b"tampered")
            with pytest.raises(RuntimeError, match="SHA-256"):
                predict_scenario_bundle(history, frame, tmp_path, task)


def _dropout_smoke_fixture() -> object:
    import polars as pl

    rows: list[dict] = []
    for year in (2019, 2020, 2022, 2023, 2024):
        for day_index in range(360):
            cutoff = date(year, 1, 1) + timedelta(days=day_index)
            for channel_index in range(2):
                if channel_index == 0 and day_index % 20 in (2, 3, 4):
                    continue
                positive = int(channel_index == 0 and day_index % 20 == 0)
                row = {
                    "d_channel_key": f"ch-{channel_index}",
                    "d_object_key": "obj",
                    "d_cutoff_date": cutoff,
                    "d_target_start_date": cutoff + timedelta(days=2),
                    "d_target_end_date_exclusive": cutoff + timedelta(days=3),
                    "d_dropout_target_start_date": cutoff + timedelta(days=2),
                    "d_dropout_target_end_date_exclusive": cutoff + timedelta(days=5),
                    "d_year": year,
                    DROPOUT_TARGET: 0,  # legacy label must be rebuilt, never trusted
                    "тип_датчика": f"type-{channel_index}",
                    "тип_инж_системы": "system",
                }
                for index, feature in enumerate(ELEMENT_NUMERIC_FEATURES):
                    row[feature] = (
                        True
                        if feature == "d_catalogue_match"
                        else float((day_index + index + 3 * positive) % 17)
                    )
                rows.append(row)
    return pl.DataFrame(rows)


def test_full_tcn_loss_uses_imported_torch_namespace() -> None:
    from missing_targets_runtime import _fit_masked_tcn

    source = inspect.getsource(_fit_masked_tcn)
    assert "import torch" in source
    assert "torch.nn.functional.binary_cross_entropy_with_logits" in source


def test_dropout_smoke_runs_and_marks_tcn_surrogate(tmp_path: Path) -> None:
    import polars as pl

    history = _dropout_smoke_fixture()
    result = run_dropout_experiment(
        history,
        {"sha256": {"channel_element": "test"}},
        {
            "run_mode": "smoke",
            "negative_to_positive_ratio": 20,
            "minimum_precision": 0.1,
            "alert_budget_per_day": 1,
            "cooldown_hours": 72,
            "bootstrap_repeats": 10,
            "min_positives_for_pr_auc": 1,
            "random_seed": 7,
        },
        tmp_path,
    )
    assert result["evidence_level"] == "E1"
    assert result["physical_failure_probability_reported"] is False
    assert result["selection_contract_version"] == DROPOUT_SELECTION_CONTRACT_VERSION
    for fold in result["folds"].values():
        assert fold["models"]["masked_tcn"]["implementation"] == "smoke_logistic_surrogate"
        assert fold["asof_validation_rows"] >= fold["rows"]["validation"]
        assert fold["models"]["masked_tcn"]["asof_operational"]["precision_is_lower_bound"] is True
    assert (tmp_path / "results_dropout_missing_target.json").exists()
    assert (tmp_path / "predictions_dropout_missing_target.parquet").exists()
    assert (tmp_path / "predictions_dropout_candidates.parquet").exists()
    saved = pl.read_parquet(tmp_path / "predictions_dropout_missing_target.parquet").filter(
        pl.col("fold") == "fold_2024"
    )
    frame = history.join(
        saved.select("d_channel_key", "d_cutoff_date"),
        on=["d_channel_key", "d_cutoff_date"], how="inner",
    )
    replay = predict_dropout_bundle(history, frame, tmp_path)
    comparison = replay.join(
        saved.select("d_channel_key", "d_cutoff_date", "score"),
        on=["d_channel_key", "d_cutoff_date"], suffix="_saved",
    )
    np.testing.assert_allclose(comparison["score"].to_numpy(), comparison["score_saved"].to_numpy(), atol=1e-6)
    contract = json.loads((tmp_path / "model_dropout_contract.json").read_text(encoding="utf-8"))
    model_path = tmp_path / contract["model_file"]
    model_path.write_bytes(model_path.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="SHA-256"):
        predict_dropout_bundle(history, frame, tmp_path)
    assert (tmp_path / "model_dropout_contract.json").exists()
    for metric in result["model_summary"].values():
        assert metric["operational_false_alerts_per_1000"] is not None
