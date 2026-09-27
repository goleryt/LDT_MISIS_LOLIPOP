"""Модуль 18: прогноз инцидентов по реестру (синтетика, без реальных данных)."""

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

import event_panel_v3 as ep  # noqa: E402
import incident_head_v1 as ih  # noqa: E402
import incident_predictor_v1 as ip  # noqa: E402

D0 = date(2024, 3, 1)


def test_groups_and_object_aggregation() -> None:
    ch = pl.DataFrame({"d_object_key": ["a", "a", "a", "b"], "d_cutoff_date": [D0] * 4,
                       "тип_датчика": ["Датчик дыма", "Состояние насоса", "КД Дверь", "Счётчик"],
                       "n_alarm": [2.0, 3.0, 5.0, 7.0], "f_n_alarm_7d": [1.0, 1.0, 1.0, 1.0],
                       "link_state": ["O", "F", "O", "O"], "gas_max": [None, None, None, None]})
    out = ip.aggregate_objects(pl, ch).sort("object_ref")
    a = out.row(0, named=True)
    assert a["grp_fire__n_alarm"] == 2 and a["grp_flood__n_alarm"] == 3 and a["grp_access__n_alarm"] == 5
    assert a["obj__n_alarm"] == 10 and a["obj__n_channels"] == 3 and abs(a["obj__share_link_not_ok"] - 1 / 3) < 1e-9
    assert a["_fp_fire"] == 2 and a["_fp_flood"] == 3 and a["_fp_access"] == 5
    assert out.row(1, named=True)["grp_other__n_alarm"] == 7
    assert not any(c.startswith("_") for c in ip.feature_columns(out.columns))
    assert ip.humanize("grp_flood__f_n_alarm_7d") == "датчики воды и насосы: тревоги за 7 сут"


def _obj(n_days: int = 20) -> pl.DataFrame:
    return pl.DataFrame({"object_ref": ["a"] * n_days, "d_cutoff_date": [D0 + timedelta(days=i) for i in range(n_days)]})


def test_targets_positive_ongoing_and_coverage() -> None:
    ev = pl.DataFrame({"object_ref": ["a"], "day": [D0 + timedelta(days=10)], "kind": ["flood"]})
    cov = {"period_start": D0.isoformat(), "period_end_exclusive": (D0 + timedelta(days=15)).isoformat(),
           "objects": "all", "label_source": "stub"}
    fr = ih.build_targets(pl, _obj(), ev, cov)
    y = fr["target_flood"].to_list()
    assert y[8] == 1                                   # D+2 = день инцидента
    assert all(y[i] is None for i in range(10, 17))   # начался в [D−6; D] → идёт, не прогноз
    assert y[17] is None and y[12] is None             # вне покрытия (D+2 ≥ 15) / идёт
    assert y[7] == 0 and y[9] is None and fr["reason_flood"][9] == "competing_event_d1"   # начало в D+1
    assert fr["target_fire"].drop_nulls().sum() == 0
    assert fr["reason_flood"][10] == "ongoing_incident" and fr["reason_flood"][13] == "outside_coverage"


def test_stub_register_is_seeded_and_rate_is_respected() -> None:
    days = [date(2022, 2, 1) + timedelta(days=i) for i in range(1000)]
    obj = pl.DataFrame({"object_ref": [f"o{i % 50}" for i in range(50 * 1000)],
                        "d_cutoff_date": [d for d in days for _ in range(50)],
                        "_fp_fire": np.random.default_rng(0).poisson(1, 50000).astype(float),
                        "_fp_flood": np.zeros(50000), "_fp_access": np.ones(50000)})
    cfg = ih.make_config_18("SMOKE", {"rate_per_object_year": 2.0})
    r1, cov = ih.make_stub_register(pl, obj, cfg, 2.0, 7)
    r2, _ = ih.make_stub_register(pl, obj, cfg, 2.0, 7)
    assert r1.equals(r2) and cov["label_source"] == "stub" and cov["stub"]["beta"] == 2.0
    expected = 2.0 / 365 * 50000
    for t in ip.INCIDENT_TYPES:
        n = int((r1["тип_инцидента"] == t).sum())
        assert 0.7 * expected < n < 1.3 * expected, (t, n, expected)
    assert set(ih.REGISTER_COLUMNS) <= set(r1.columns)


def test_load_register_maps_raw_ids_and_filters() -> None:
    reg = pl.DataFrame({"ид_инцидента": ["1", "2", "3", "4"], "ид_объект": ["77", "77", "78", "79"],
                        "тип_инцидента": ["пожар", "подтопление", "прочее", "нсд"],
                        "начало": ["2024-03-05T10:00:00", "2024-03-06T01:00:00", "2024-03-06", "2024-03-07"],
                        "подтверждён": [True, False, True, True]})
    ev, stats = ih.load_register(pl, reg, {"period_start": "2024-01-01", "period_end_exclusive": "2025-01-01",
                                           "objects": "all", "label_source": "register"})
    assert stats["confirmed_in_scope"] == 2 and stats["by_type"] == {"fire": 1, "flood": 0, "access": 1}
    assert set(ev["object_ref"].to_list()) == {ep.pseudo_key("77"), ep.pseudo_key("79")}
    with pytest.raises(ValueError):
        ih.load_register(pl, reg, {"period_start": "2024-01-01", "objects": "all", "label_source": "register"})
    with pytest.raises(ValueError):
        ih.load_register(pl, reg.drop("подтверждён"), {"period_start": "2024-01-01", "period_end_exclusive": "2025-01-01",
                                                       "objects": "all", "label_source": "register"})


@pytest.fixture(scope="module")
def run18(tmp_path_factory):
    work = tmp_path_factory.mktemp("i18")
    ih.synthetic_incident_panel(work / "in", n_objects=60)
    cfg = ih.make_config_18("SMOKE", {"input_dir": str(work / "in"), "output_dir": str(work / "out"),
                                      "smoke_object_share": 1, "rate_per_object_year": 2.0,
                                      "scenarios": {"control": 0.0, "medium": 2.0}, "main_scenario": "medium"})
    return work, ih.run_incident_head(cfg, log=lambda *a: None), cfg


def test_end_to_end_stub(run18) -> None:
    work, res, _ = run18
    out = work / "out"
    assert res["status"] == "completed_smoke_non_comparable"
    for name in ("incident_head_bundle.zip", "incident_head_bundle.zip.sha256", "incident_register_stub.csv",
                 "incident_register_coverage_stub.json", "results_18_incident_head.json", "summary_18_incident_head_ru.md"):
        assert (out / name).exists(), name
    assert (out / "incident_head_bundle.zip.sha256").read_text().split()[0] == ih._sha256_file(out / "incident_head_bundle.zip")
    spec = json.loads((out / "incident_head_bundle" / "bundle.json").read_text(encoding="utf-8"))
    assert spec["label_source"] == "stub" and spec["evidence_level"] == "E4" and spec["operational_ready"] is False
    ctrl = res["scenarios"]["control"]["types"]
    assert all(r["decision_status"] != "demo_stub" for r in ctrl.values())   # контроль не должен «пройти»
    assert res["scenarios"]["medium"]["types"]["fire"].get("learning_curve")
    assert res["acceptance"]["bad_date_rejected"] and res["acceptance"]["records"] > 0
    acc = res["acceptance"]
    if any(v != "abstain" for v in acc["parity_paths"].values()):      # путь правила тоже сверяется
        assert acc["parity_max_abs_diff"] is not None and acc["parity_max_abs_diff"] < 1e-9


def test_outputs_have_no_raw_panel_keys_in_summary(run18) -> None:
    work, _, _ = run18
    part = pl.read_parquet(work / "in" / "event_panel_v3" / "event_panel_v3_part00.parquet")
    keys = set(part["d_object_key"].unique().to_list()) | set(part["d_channel_key"].unique().to_list())
    for name in ("results_18_incident_head.json", "summary_18_incident_head_ru.md"):
        text = (work / "out" / name).read_text(encoding="utf-8")
        assert not any(k in text for k in keys), name


def test_bundle_parity_when_model_passes(run18, tmp_path) -> None:
    """Если модель допущена, predictor из bundle даёт те же score, что модель в памяти (канальные строки → объект)."""
    work, _, cfg = run18
    parts, manifest = ih.rt.discover_panel(work / "in", True)
    obj = ih.build_object_panel(pl, parts, cfg)
    feats = ip.feature_columns(obj.columns)
    reg, cov = ih.make_stub_register(pl, obj, cfg, 2.0, 18)
    ev, _ = ih.load_register(pl, reg, cov)
    tr, ca, te = ih.split(pl, ih.build_targets(pl, obj, ev, cov), cfg)
    fits = {k: ih.fit_type(pl, tr, ca, te, k, feats, cfg) for k in ip.GROUPS}
    for f in fits.values():
        f["gate"] = "passed"                          # форсируем только для проверки parity
    mp = next((work / "in").rglob("panel_manifest_v3.json"))
    bdir = ih.export_bundle(tmp_path, fits, feats, cov, "x", manifest, mp, cfg)
    acc = ih.acceptance(pl, bdir, parts, obj, fits, feats, cfg)
    assert acc["parity_max_abs_diff"] is not None and acc["parity_max_abs_diff"] < 1e-9
    assert acc["has_top_factors"]


def test_predictor_contract_and_tamper(run18, tmp_path) -> None:
    work, _, _ = run18
    bdir = tmp_path / "b"
    shutil.copytree(work / "out" / "incident_head_bundle", bdir)
    pred = ih._import_predictor(bdir)
    b = pred.load_bundle(bdir)
    day = date(2025, 8, 1)
    ch = pl.read_parquet(work / "in" / "event_panel_v3" / "event_panel_v3_part00.parquet").filter(pl.col("d_cutoff_date") == day)
    ch = ch.rename({"d_object_key": "ид_объект"})
    one = ch["ид_объект"][0]
    out = pred.predict(ch, b, day.isoformat(), request_id="r",
                       recent_incidents=[{"ид_объект": one, "тип_инцидента": "пожар", "начало": "2025-07-30"}])
    rec = [r for r in out if r["ид_объект"] == one and r["incident_type"] == "пожар"][0]
    assert rec["abstain_reason"] == "ONGOING_INCIDENT" and rec["score"] is None
    assert {r["window_start"] for r in out} == {"2025-08-03"}
    with pytest.raises(pred.ContractError):
        pred.predict(ch.drop("тип_датчика"), b, day.isoformat())
    (bdir / "bundle.json").write_text((bdir / "bundle.json").read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(pred.ContractError):
        pred.load_bundle(bdir)


def test_cli_with_real_register_format(run18, tmp_path) -> None:
    """Реальный реестр (тот же формат, label_source = register) → bundle с evidence E0."""
    work, _, _ = run18
    reg = pl.read_csv(work / "out" / "incident_register_stub.csv")
    reg.write_csv(tmp_path / "incident_register.csv")
    cov = json.loads((work / "out" / "incident_register_coverage_stub.json").read_text(encoding="utf-8"))
    cov = {k: v for k, v in cov.items() if k != "stub"} | {"label_source": "register"}
    (tmp_path / "coverage.json").write_text(json.dumps(cov), encoding="utf-8")
    code = ih.main(["train", "--panel", str(work / "in"), "--register", str(tmp_path / "incident_register.csv"),
                    "--coverage", str(tmp_path / "coverage.json"), "--out", str(tmp_path / "o"), "--mode", "SMOKE"])
    assert code == 0
    spec = json.loads((tmp_path / "o" / "incident_head_bundle" / "bundle.json").read_text(encoding="utf-8"))
    assert spec["label_source"] == "register" and spec["evidence_level"] == "E0"
    assert all(t["decision_status"] in ("experimental_shadow", "baseline_only", "insufficient_labels") for t in spec["types"].values())
