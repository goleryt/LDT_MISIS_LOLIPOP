"""Contracts for notebook 15: models on event-panel v3 targets, typed-score contract, chain 14 → 15."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import re
import sys

import numpy as np
import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))
sys.path.insert(0, str(Path(__file__).parent))

import event_panel_v3 as ep  # noqa: E402
import target_models_v3_runtime as tm  # noqa: E402
from test_event_panel_v3 import _catalogue, _events  # noqa: E402

TAX = MODULE_DIR / "config" / "state_taxonomy_v3.json"


def test_self_tests_pass(tmp_path) -> None:
    assert all(tm.run_targets_self_tests(tmp_path).values())


def test_features_exclude_future_and_identifiers() -> None:
    manifest = {"feature_columns": ["f_a", "link_state", "d_weekday"]}
    assert tm.safe_features(manifest, ["f_a", "link_state", "d_weekday", "target_x", "тип_датчика"]) == ["f_a", "link_state", "d_weekday", "тип_датчика"]
    for bad in ("reason_t2a_link_onset", "competing_link_onset_d1", "d_label_decision_end", "d_channel_key",
                "target_t4_gas_cross", "d_target_start_date"):
        with pytest.raises(ValueError):
            tm.safe_features({"feature_columns": [bad]}, [bad])


def test_folds_never_touch_2021_or_2025(tmp_path) -> None:
    root = tm.synthetic_panel_v3(tmp_path / "in", n_channels=20).parent
    parts, manifest = tm.discover_panel(root, verify=True)
    cfg = tm.make_config_targets("FULL")
    frame = tm.load_target(pl, parts, "target_t2a_link_onset", tm.safe_features(manifest, pl.scan_parquet(parts).collect_schema().names()), cfg)
    years = set(frame["d_cutoff_date"].dt.year().unique().to_list())
    assert 2021 not in years and 2025 not in years
    assert frame["d_cutoff_date"].filter(frame["d_cutoff_date"].dt.year() == 2022).min() >= tm.EXCLUDED[1]
    assert frame["d_label_decision_end"].max() <= tm.LOAD_END
    for fold in tm.FOLDS:
        tr, ca, va = tm.split_fold(pl, frame, fold)
        assert tr["d_label_decision_end"].max() <= fold["calibration"][0]
        assert ca["d_label_decision_end"].max() <= fold["validation"][0]


def test_sha_mismatch_stops(tmp_path) -> None:
    panel_dir = tm.synthetic_panel_v3(tmp_path / "in", n_channels=10)
    m = json.loads((panel_dir / "panel_manifest_v3.json").read_text())
    m["parts"][0]["sha256"] = "0" * 64
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(m))
    with pytest.raises(ValueError):
        tm.discover_panel(tmp_path / "in", verify=True)


def test_gates_insufficient_and_baseline_only() -> None:
    cfg = tm.make_config_targets("FULL")
    def fold(pos, g1_low, l1_low, g1=0.3, g2=0.3, l1=0.2):
        models = {m: {"pr_auc": v} for m, v in (("P0_type_prior", 0.05), ("R1_rule", 0.2), ("L1_logistic", l1),
                                                 ("G1_lightgbm", g1), ("G2_no_calendar", g2), ("G3_no_catalogue", g1))}
        return {"rows": {"validation_pos": pos}, "models": models, "best_simple_baseline": "R1_rule",
                "by_sensor_type_pr_auc": {m: {} for m in models}, "unknown_share_selectable": 0.2,
                "bootstrap_G1_lightgbm_vs_R1_rule": {"ci95_low": g1_low},
                "bootstrap_G2_no_calendar_vs_R1_rule": {"ci95_low": g1_low},
                "bootstrap_L1_logistic_vs_R1_rule": {"ci95_low": l1_low}}
    d = tm.decide({"folds": {"a": fold(5, 0.1, 0.1), "b": fold(100, 0.1, 0.1)}}, cfg)
    assert d["evidence_level"] == "insufficient_events" and d["selected"] is None
    d = tm.decide({"folds": {"a": fold(100, -0.01, -0.02), "b": fold(100, 0.1, 0.1)}}, cfg)
    assert d["evidence_level"] == "baseline_only" and d["selected"] == "R1_rule"
    d = tm.decide({"folds": {"a": fold(100, 0.05, -0.01), "b": fold(100, 0.05, 0.02)}}, cfg)
    assert d["selected"] == "G1_lightgbm" and d["evidence_level"] == "validated_proxy_model"
    # календарный shortcut: без календаря сильно хуже, но всё ещё лучше baseline → G2
    d = tm.decide({"folds": {"a": fold(100, 0.05, -0.01, g2=0.22), "b": fold(100, 0.05, -0.01, g2=0.22)}}, cfg)
    assert d["selected"] == "G2_no_calendar" and not d["gates"]["g3_no_calendar_shortcut"]


def test_score_kind_rules() -> None:
    cfg = tm.make_config_targets("FULL")
    folds = {"a": {"models": {"G1_lightgbm": {"ece10": 0.01}}, "unknown_share_selectable": 0.05},
             "b": {"models": {"G1_lightgbm": {"ece10": 0.015}}, "unknown_share_selectable": 0.08}}
    ok = {"evidence_level": "validated_proxy_model", "selected": "G1_lightgbm"}
    assert tm.score_kind(tm.TARGET_SPECS["target_t2a_link_onset"], ok, folds, cfg) == "probability_calibrated"
    assert tm.score_kind(tm.TARGET_SPECS["target_t2b_link_sustained"], ok, folds, cfg) == "conditional_proxy_score"
    folds["b"]["unknown_share_selectable"] = 0.4  # ECE хорошая, но много неизвестных исходов → не обещаем вероятность
    assert tm.score_kind(tm.TARGET_SPECS["target_t2a_link_onset"], ok, folds, cfg) == "proxy_score"
    folds["b"]["unknown_share_selectable"] = 0.05
    folds["b"]["models"]["G1_lightgbm"]["ece10"] = 0.05
    assert tm.score_kind(tm.TARGET_SPECS["target_t2a_link_onset"], ok, folds, cfg) == "proxy_score"
    assert tm.score_kind(tm.TARGET_SPECS["target_t4_gas_cross"], {"evidence_level": "insufficient_events", "selected": None},
                         folds, cfg) == "abstain"


def test_chain_notebook14_output_feeds_notebook15(tmp_path) -> None:
    """Панель, собранная runtime ноутбука 14 из синтетического журнала, читается и считается runtime 15."""
    rnd = random.Random(5)
    t0 = datetime(2022, 6, 1)
    rows = []
    for c in range(16):
        for d in range(0, 940, 1):
            t = t0 + timedelta(days=d, hours=rnd.randint(0, 23))
            rows.append((f"C{c:02d}", t, "Норма"))
            if rnd.random() < 0.06:
                rows.append((f"C{c:02d}", t + timedelta(minutes=1), rnd.choice(["Неисправен", "Обесточен"])))
                rows.append((f"C{c:02d}", t + timedelta(minutes=rnd.choice([1, 30])), "Норма"))
    j, c = tmp_path / "j.csv", tmp_path / "c.csv"
    _events(rows).write_csv(j)
    _catalogue({f"C{i:02d}": "Состояние насоса" for i in range(16)}).write_csv(c)
    panel_dir = tmp_path / "in" / "event_panel_v3"
    panel_dir.mkdir(parents=True)
    _, audit = ep.build_event_panel(pl, [j], c, TAX, out_dir=panel_dir, log=lambda *a: None)
    manifest = {"schema_version": ep.SCHEMA_VERSION, "rows": audit["rows"], "taxonomy_sha256": audit["taxonomy_sha256"],
                "panel_config": audit["config"], "feature_columns": audit["feature_columns"],
                "target_columns": audit["target_columns"],
                "parts": [{"file": p, "sha256": tm.file_sha256(panel_dir / p)} for p in audit["part_files"]]}
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(manifest), encoding="utf-8")
    cfg = tm.make_config_targets("SMOKE", {"input_dir": str(tmp_path / "in"), "output_dir": str(tmp_path / "out"),
                                           "smoke_channel_share": 1, "min_val_positives": 5,
                                           "targets": ["target_t2a_link_onset", "target_t2c_power_onset"]})
    res = tm.run_targets_v3(cfg, log=lambda *a: None)
    assert res["status"] == "completed_smoke_non_comparable"
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == ["backend_typed_scores_v3.json", "results_targets_v3.json",
                                                     "summary_targets_v3_ru.md"]
    contract = json.loads((out / "backend_typed_scores_v3.json").read_text(encoding="utf-8"))
    for t in contract["targets"]:
        assert t["evidence_level"] in ("validated_proxy_model", "baseline_only", "insufficient_events")
        assert t["score_kind"] in ("probability_calibrated", "proxy_score", "conditional_proxy_score", "abstain")
        assert t["not_a_confirmed_failure"] is True
    assert contract["data_quality_flags"][0]["score_kind"] == "data_quality_flag"
    results = json.loads((out / "results_targets_v3.json").read_text(encoding="utf-8"))
    for t, r in results["targets"].items():
        for f in r["folds"].values():
            assert f["rows"]["validation_selectable"] >= f["rows"]["validation"]
            for m in f.get("models", {}).values():
                b = m["budget"]["25"]
                assert b["precision"] <= b["precision_upper"]
                assert b["recall_low"] <= b["recall"] + 1e-12 and b["recall_low_cooldown"] <= b["recall_up_cooldown"] + 1e-12
            if f.get("models") and t in ("target_t2a_link_onset", "target_t2c_power_onset"):
                assert "competing_d1" in f and set(f["competing_d1"]["pr_auc_first_onset"]) == set(tm.MODELS)
    keys = set(pl.read_parquet(sorted(panel_dir.glob("*.parquet")))["d_channel_key"].unique().to_list())
    for name in ("backend_typed_scores_v3.json", "results_targets_v3.json", "summary_targets_v3_ru.md"):
        tokens = set(re.findall(r"[0-9a-f]{16}", (out / name).read_text(encoding="utf-8")))
        assert not tokens & keys, name


def test_generated_notebook_embeds_runtime_and_compiles() -> None:
    path = ROOT / "notebooks" / "kaggle" / "15_targets_v3_models_cpu.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert (MODULE_DIR / "target_models_v3_runtime.py").read_text(encoding="utf-8").strip() in source, "regenerate notebook"
    for cell in notebook["cells"]:
        assert "id" in cell
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), str(path), "exec")


def test_manifest_row_count_mismatch_stops(tmp_path) -> None:
    panel_dir = tm.synthetic_panel_v3(tmp_path / "in", n_channels=10)
    m = json.loads((panel_dir / "panel_manifest_v3.json").read_text())
    m["rows"] += 1
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(m))
    with pytest.raises(ValueError):
        tm.discover_panel(tmp_path / "in", verify=True)


def test_2021_is_stress_only(tmp_path) -> None:
    """2021 не попадает в обучение/выбор, но оценивается отдельным stress-срезом моделями fold_2024 (GPT 20)."""
    tm.synthetic_panel_v3(tmp_path / "in", n_channels=60)
    cfg = tm.make_config_targets("SMOKE", {"input_dir": str(tmp_path / "in"), "output_dir": str(tmp_path / "out"),
                                           "smoke_channel_share": 1, "targets": ["target_t2a_link_onset"],
                                           "bootstrap_reps": 5})
    tm.run_targets_v3(cfg, log=lambda *a: None)
    res = json.loads((tmp_path / "out" / "results_targets_v3.json").read_text(encoding="utf-8"))
    st = res["targets"]["target_t2a_link_onset"]["stress_2021"]
    assert st["rows"] > 0 and set(st["pr_auc"]) == set(tm.MODELS)
    assert "Stress 2021" in (tmp_path / "out" / "summary_targets_v3_ru.md").read_text(encoding="utf-8")
