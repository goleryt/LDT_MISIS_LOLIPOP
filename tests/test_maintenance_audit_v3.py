"""Ноутбук 17: read-only audit газового bundle по окнам сервисных работ (синтетика, без реальных данных)."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "ml" / "sensor_failure"))

import gas_bundle_v3 as gb  # noqa: E402
import maintenance_audit_v3 as ma  # noqa: E402
import target_models_v3_runtime as rt  # noqa: E402

D0 = date(2025, 3, 1)


def _activity(pattern: str, obj: str = "o1") -> pl.DataFrame:
    """pattern: строка из 1/0 по дням (1 — были газовые показания)."""
    return pl.DataFrame({"d_object_key": [obj] * len(pattern),
                         "day": [D0 + timedelta(days=i) for i in range(len(pattern))],
                         "reading": [c == "1" for c in pattern]})


def test_silence_runs_and_windows() -> None:
    act = _activity("1111100000011111111111" + "1" * 30)   # молчание 6 суток: дни 5..10
    runs = ma.silence_runs(pl, act, 4)
    assert runs.height == 1 and runs["length"][0] == 6 and runs["returned"][0]
    ph = ma.posthoc_days(pl, runs, before=3, after=21)
    days = set(ph["day"].to_list())
    assert D0 + timedelta(days=2) in days and D0 + timedelta(days=31) in days and D0 + timedelta(days=32) not in days
    shifted = set(ma.posthoc_days(pl, runs, 3, 21, shift=30)["day"].to_list())
    assert min(shifted) == D0 + timedelta(days=32)


def test_trailing_flag_is_causal() -> None:
    """Флаг на D только после возврата и не позже lookback суток после конца молчания; внутри молчания — нет."""
    act = _activity("1111100000011111111111" + "1" * 30)
    runs = ma.silence_runs(pl, act, 4)
    tr = set(ma.trailing_days(pl, runs, 21)["day"].to_list())
    assert D0 + timedelta(days=11) in tr                      # первый день после молчания
    assert D0 + timedelta(days=8) not in tr                   # внутри молчания — ещё нельзя знать
    assert D0 + timedelta(days=31) in tr and D0 + timedelta(days=32) not in tr


def test_short_silence_and_unbounded_edges_are_ignored() -> None:
    """3 суток — короче порога; молчание до первого и после последнего показания — не отрезки (v2)."""
    act = _activity("000000" + "11110001111" + "1111" + "0000000")
    runs = ma.silence_runs(pl, act, 4)
    assert runs.height == 0
    assert ma.trailing_days(pl, runs, 21).height == 0


def test_mark_aligns_by_row_index_not_join_order() -> None:
    frame = pl.DataFrame({"d_object_key": ["o2", "o1", "o2", "o1"],
                          "d_cutoff_date": [D0, D0, D0 + timedelta(days=1), D0 + timedelta(days=1)]})
    days = pl.DataFrame({"d_object_key": ["o1", "o1", "o2"],
                         "day": [D0 + timedelta(days=3), D0 + timedelta(days=3), D0 + timedelta(days=2)]})
    assert ma.mark(pl, frame, days, "w", 2)["w"].to_list() == [True, False, False, True]


def test_panel_mismatch_is_rejected(tmp_path) -> None:
    mpath = tmp_path / "panel_manifest_v3.json"
    mpath.write_text("{}", encoding="utf-8")
    manifest = {"schema_version": "3.0", "rows": 10, "parts": [{"sha256": "a"}]}
    spec = {"panel": {"manifest_sha256": ma._sha256(mpath), "schema_version": "3.0", "rows": 10, "parts_sha256": ["a"]}}
    assert ma.check_panel_matches_bundle(manifest, mpath, spec)["panel_matches_bundle"]
    with pytest.raises(ma.PanelMismatch):
        ma.check_panel_matches_bundle({**manifest, "rows": 11}, mpath, spec)
    with pytest.raises(ma.PanelMismatch):
        ma.check_panel_matches_bundle(manifest, mpath, {"panel": {**spec["panel"], "parts_sha256": ["b"]}})


def test_mark_uses_outcome_day() -> None:
    days = pl.DataFrame({"d_object_key": ["o1"], "day": [D0 + timedelta(days=10)]})
    frame = pl.DataFrame({"d_object_key": ["o1", "o1", "o2"], "d_cutoff_date": [D0 + timedelta(days=8), D0 + timedelta(days=10), D0 + timedelta(days=8)]})
    m = ma.mark(pl, frame, days, "w", 2)["w"].to_list()
    assert m == [True, False, False]


def test_common_top_k_policy_with_cooldown() -> None:
    days = np.array([0, 0, 0, 1, 1, 1])
    ch = np.array(["a", "b", "c", "a", "b", "c"])
    s = np.array([0.9, 0.8, 0.1, 0.9, 0.2, 0.3])
    picked = ma.select_alerts(days, ch, s, k=2, cooldown=3)
    assert picked.tolist() == [True, True, False, False, False, True]


@pytest.fixture(scope="module")
def audit_run(tmp_path_factory):
    work = tmp_path_factory.mktemp("a17")
    root = work / "in"
    rt.synthetic_panel_v3(root, n_channels=96, end=date(2026, 7, 10), gas_features=True)
    cfg16 = gb.make_config_export("SMOKE", "refit_2025h1", {"input_dir": str(root), "output_dir": str(work / "o16"),
                                                           "smoke_channel_share": 1, "latency_rows": 500,
                                                           "min_calibration_positives": 5, "min_train_positives": 5})
    gb.run_export_v3(cfg16, log=lambda *a: None)
    ds = root / "bundle_dataset"
    ds.mkdir()
    for name in ("gas_cross_v3_bundle.zip", "gas_cross_v3_bundle.zip.sha256"):
        shutil.copy(work / "o16" / name, ds / name)
    cfg = ma.make_config_17("SMOKE", {"input_dir": str(root), "output_dir": str(work / "o17"), "smoke_channel_share": 1})
    return work, ma.run_audit_17(cfg, log=lambda *a: None), cfg


def test_audit_end_to_end(audit_run) -> None:
    work, res, _ = audit_run
    assert res["status"] == "completed_smoke_non_comparable"
    assert res["bundle"]["zip_sha256_verified"] is True and res["silence_runs"]["runs"] > 0
    p = res["periods"]["2025H2"]
    st = p["strata"]
    assert st["all"]["selectable"] == st["posthoc_after21:in"]["selectable"] + st["posthoc_after21:out"]["selectable"]
    assert st["all"]["selectable"] == st["trailing_flag_at_D:true"]["selectable"] + st["trailing_flag_at_D:false"]["selectable"]
    a = st["all"]["top_k_alerts"]["alerts"]
    assert a == st["posthoc_after21:in"]["top_k_alerts"]["alerts"] + st["posthoc_after21:out"]["top_k_alerts"]["alerts"]
    assert "pr_auc_G2" in st["all"] and "lift_G2" in st["all"]
    assert (work / "o17" / "summary_17_maintenance_audit_ru.md").exists()


def test_audit_uses_unchanged_bundle_and_no_keys_in_outputs(audit_run) -> None:
    work, res, _ = audit_run
    spec = json.loads(next((work / "o16" / "gas_cross_v3_bundle").glob("bundle.json")).read_text(encoding="utf-8"))
    assert res["bundle"]["model_sha256"] == spec["model_sha256"]
    part = pl.read_parquet(work / "in" / "event_panel_v3" / "event_panel_v3_part00.parquet")
    keys = set(part["d_channel_key"].unique().to_list()) | set(part["d_object_key"].unique().to_list())
    for name in ("results_17_maintenance_audit.json", "summary_17_maintenance_audit_ru.md"):
        text = (work / "o17" / name).read_text(encoding="utf-8")
        assert not any(k in text for k in keys), name


def test_controls_exclude_main_window_and_alerts_use_eligible_cohort(audit_run) -> None:
    _, res, _ = audit_run
    st = res["periods"]["2025H2"]["strata"]
    assert res["panel"]["panel_matches_bundle"] and res["audit_version"] == "17-v2"
    for s in ("control_shift30", "control_shift60"):
        assert st[f"{s}:in"]["selectable"] + st[f"{s}:out"]["selectable"] == st["all"]["selectable"]
    assert st["all"]["top_k_alerts_R1_policy"]["alerts"] > 0


def test_other_panel_is_rejected(audit_run, tmp_path) -> None:
    work, _, cfg = audit_run
    root = tmp_path / "in"
    shutil.copytree(work / "in", root)
    mp = next(root.rglob("panel_manifest_v3.json"))
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["panel_config"] = {**m.get("panel_config", {}), "note": "rebuilt"}
    mp.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ma.PanelMismatch):
        ma.run_audit_17({**cfg, "input_dir": str(root), "output_dir": str(tmp_path / "o")}, log=lambda *a: None)


def test_tampered_zip_is_rejected(audit_run, tmp_path) -> None:
    work, _, cfg = audit_run
    root = tmp_path / "in"
    shutil.copytree(work / "in", root)
    (root / "bundle_dataset" / "gas_cross_v3_bundle.zip.sha256").write_text("0" * 64 + "  gas_cross_v3_bundle.zip\n")
    with pytest.raises(ValueError):
        ma.run_audit_17({**cfg, "input_dir": str(root), "output_dir": str(tmp_path / "o")}, log=lambda *a: None)
