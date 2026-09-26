"""Ноутбук 16: финальный газовый bundle v3 — экспорт, parity predictor, причинность build_features (синтетика)."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

import event_panel_v3 as ep  # noqa: E402
import gas_bundle_v3 as gb  # noqa: E402
import gas_predictor_v3 as gp  # noqa: E402
import target_models_v3_runtime as rt  # noqa: E402

TAX = MODULE_DIR / "config" / "state_taxonomy_v3.json"
T0 = datetime(2024, 3, 1)


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    work = tmp_path_factory.mktemp("export16")
    root = work / "in"
    rt.synthetic_panel_v3(root, n_channels=80, end=date(2026, 1, 10), gas_features=True)
    cfg = gb.make_config_export("SMOKE", "refit_2025h1", {"input_dir": str(root), "output_dir": str(work / "out"),
                                                         "smoke_channel_share": 1, "latency_rows": 2000,
                                                         "min_calibration_positives": 5, "min_train_positives": 5})
    res = gb.run_export_v3(cfg, log=lambda *a: None)
    return work, res, cfg


def test_export_completes_and_acceptance_passes(exported) -> None:
    work, res, _ = exported
    assert res["status"] == "completed_smoke_non_comparable"
    acc = res["acceptance"]
    assert acc["passed"] and acc["parity_ok"] and acc["example_ok"]
    assert acc["missing_feature_rejected"] and acc["unknown_field_rejected"]
    assert acc["unknown_category_scored"] and acc["null_features_scored"]
    assert (work / "out" / f"{gb.BUNDLE_DIR_NAME}.zip").exists()


def test_refit_split_uses_2025_and_purges(exported) -> None:
    _, res, _ = exported
    a = res["audit"]
    assert a["rows_selectable"] > 0 and res["counts"]["calibration"] > 0
    # всё selectable в audit проходит runtime eligibility: она не зависит от будущего
    assert a["runtime_eligible_share_of_selectable"] == 1.0


def test_features_are_g2_list_without_calendar_and_match_booster(exported) -> None:
    work, res, _ = exported
    spec = json.loads((work / "out" / gb.BUNDLE_DIR_NAME / "bundle.json").read_text(encoding="utf-8"))
    names = [f["name"] for f in spec["features"]]
    assert not set(names) & set(rt.CALENDAR)
    assert "тип_датчика" in names and spec["n_features"] == len(names) == res["n_features"]
    bundle = gp.load_bundle(work / "out" / gb.BUNDLE_DIR_NAME)
    assert bundle["booster"].feature_name() == names
    assert spec["operational_ready"] is False and spec["score_kind"] == "proxy_score"
    assert spec["evidence_scope"] == "known_outcome_subset"


def test_bundle_has_no_pickle_and_checksums_match(exported) -> None:
    work, _, _ = exported
    bdir = work / "out" / gb.BUNDLE_DIR_NAME
    files = {str(p.relative_to(bdir)) for p in bdir.rglob("*") if p.is_file()}
    assert not any(f.endswith((".pkl", ".joblib", ".pickle")) for f in files)
    sums = json.loads((bdir / "SHA256SUMS.json").read_text(encoding="utf-8"))
    for name, sha in sums.items():
        assert rt.file_sha256(bdir / name) == sha


def test_tampered_model_is_rejected(exported, tmp_path) -> None:
    work, _, _ = exported
    bdir = tmp_path / "b"
    shutil.copytree(work / "out" / gb.BUNDLE_DIR_NAME, bdir)
    with open(bdir / "model.txt", "a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(gp.ContractError):
        gp.load_bundle(bdir)


def test_outputs_contain_no_channel_keys(exported) -> None:
    work, _, _ = exported
    keys = pl.read_parquet(work / "in" / "event_panel_v3" / "event_panel_v3_part00.parquet")["d_channel_key"].unique().to_list()
    for name in ("results_export_16_v3.json", "summary_export_16_v3_ru.md", f"{gb.BUNDLE_DIR_NAME}/audit.json",
                 f"{gb.BUNDLE_DIR_NAME}/bundle.json"):
        text = (work / "out" / name).read_text(encoding="utf-8")
        assert not any(k in text for k in keys), name


def test_fold_2024_exact_reproduces_notebook_15_g2(tmp_path) -> None:
    """Рецепт fold_2024_exact = G2 fold_2024 из 15: те же строки, признаки и модель → тот же PR-AUC на валидации."""
    root = tmp_path / "in"
    rt.synthetic_panel_v3(root, n_channels=60, gas_features=True)
    c15 = rt.make_config_targets("SMOKE", {"input_dir": str(root), "output_dir": str(tmp_path / "o15"),
                                           "smoke_channel_share": 1, "targets": [gb.TARGET], "bootstrap_reps": 5})
    r15 = rt.run_targets_v3(c15, log=lambda *a: None)
    res15 = json.loads((tmp_path / "o15" / "results_targets_v3.json").read_text(encoding="utf-8"))
    pr15 = res15["targets"][gb.TARGET]["folds"]["fold_2024"]["models"][gb.MODEL_NAME]["pr_auc"]
    c16 = gb.make_config_export("SMOKE", "fold_2024_exact", {"input_dir": str(root), "output_dir": str(tmp_path / "o16"),
                                                             "smoke_channel_share": 1, "latency_rows": 1000,
                                                             "min_calibration_positives": 5, "min_train_positives": 5})
    r16 = gb.run_export_v3(c16, log=lambda *a: None)
    assert r15["status"].startswith("completed")
    assert r16["audit"]["models"][gb.MODEL_NAME]["pr_auc"] == pytest.approx(pr15, abs=1e-12)


def test_recipe_stop_before_training(tmp_path) -> None:
    root = tmp_path / "in"
    rt.synthetic_panel_v3(root, n_channels=30, end=date(2026, 1, 10), gas_features=True)
    cfg = gb.make_config_export("SMOKE", "refit_2025h1", {"input_dir": str(root), "output_dir": str(tmp_path / "o"),
                                                         "smoke_channel_share": 1, "min_calibration_positives": 10**9})
    with pytest.raises(gb.RecipeStop):
        gb.run_export_v3(cfg, log=lambda *a: None)
    assert not (tmp_path / "o" / gb.BUNDLE_DIR_NAME).exists()


def test_predict_eligibility_reasons(exported) -> None:
    work, _, _ = exported
    bundle = gp.load_bundle(work / "out" / gb.BUNDLE_DIR_NAME)
    ex = json.loads((work / "out" / gb.BUNDLE_DIR_NAME / "example_request.json").read_text(encoding="utf-8"))
    no_reading = {**ex[0], "f_gas_last": None}
    out = gp.predict(ex + [no_reading], bundle)
    assert [o["reason_codes"] for o in out] == [[], ["ABOVE_THRESHOLD_AT_D"], ["NOT_GAS_STREAM"], ["NO_GAS_READING_AT_D"]]
    assert out[0]["window_start"] == "2026-01-17" and out[0]["window_end_exclusive"] == "2026-01-18"
    assert out[0]["ид_канала_данных"] == "EXAMPLE-CHANNEL-1" and 0 < out[0]["score"] < 1
    assert all(o["score"] is None and o["decision_status"] == "abstain" for o in out[1:])


def test_self_tests_pass(tmp_path) -> None:
    rep = gb.run_export_self_tests(tmp_path)
    assert all(rep.values()), rep


# ---------------------------------------------------------------------------
# build_features: тот же код 14, события после D не участвуют, достаточная история → те же признаки
# ---------------------------------------------------------------------------
def _journal(rows) -> pl.DataFrame:
    return pl.DataFrame({
        "ид_события": [str(i) for i in range(len(rows))], "ид_канала_данных": [r[0] for r in rows],
        "дата": [r[1].strftime("%Y-%m-%d") for r in rows], "время": [r[1].strftime("%H:%M:%S") for r in rows],
        "тревожное": ["f"] * len(rows), "значение_датчика": [r[2] for r in rows]})


def _rows(seed: int = 5, channels: int = 10, days: int = 70) -> list:
    import random

    rnd = random.Random(seed)
    values = ["Норма", "Неисправен", "Обесточен", "Есть питание", "Неопределен", "-127", "0,05", "0,40", "1,3"]
    rows = []
    for c in range(channels):
        for d in range(days):
            for _ in range(rnd.randint(1, 6)):
                rows.append((f"C{c:03d}", T0 + timedelta(days=d, seconds=rnd.randint(0, 86399)), rnd.choice(values)))
    return rows


def _fake_bundle(tmp_path: Path, feature_names: list[str]) -> dict:
    d = tmp_path / "bundle"
    (d / "features_v3").mkdir(parents=True)
    shutil.copy(MODULE_DIR / "event_panel_v3.py", d / "features_v3" / "event_panel_v3.py")
    shutil.copy(TAX, d / "features_v3" / "state_taxonomy_v3.json")
    return {"dir": d, "spec": {"panel_config": {}, "features": [{"name": n} for n in feature_names]}}


def test_build_features_equals_training_panel_row_and_ignores_future(tmp_path) -> None:
    rows = _rows()
    types = {f"C{c:03d}": ("Газовый датчик" if c % 2 == 0 else "Состояние насоса") for c in range(10)}
    j, c = tmp_path / "j.csv", tmp_path / "c.csv"
    _journal(rows).write_csv(j)
    pl.DataFrame({"ид_канала_данных": list(types), "тип_инж_системы": ["x"] * 10, "тип_датчика": list(types.values()),
                  "ид_объект": ["1"] * 10}).write_csv(c)
    full, audit = ep.build_event_panel(pl, [j], c, TAX, log=lambda *a: None)
    names = [n for n in audit["feature_columns"] if n not in rt.CALENDAR] + ["тип_датчика", "тип_инж_системы"]
    bundle = _fake_bundle(tmp_path, names)
    as_of = (T0 + timedelta(days=50)).date()
    got = gp.build_features([j], c, as_of.isoformat(), bundle).sort_values("ид_канала_данных").reset_index(drop=True)
    ref = (full.filter(pl.col("d_cutoff_date") == as_of)
           .with_columns(pl.col("d_channel_key").replace_strict({ep.pseudo_key(k): k for k in types}).alias("ид_канала_данных"))
           .sort("ид_канала_данных").select(["ид_канала_данных"] + names).to_pandas())
    assert list(got["ид_канала_данных"]) == list(ref["ид_канала_данных"]) and len(got) == 10
    for n in names:
        a, b = got[n].to_numpy(), ref[n].to_numpy()
        if a.dtype.kind in "fi" and b.dtype.kind in "fi":
            assert np.allclose(a.astype(float), b.astype(float), equal_nan=True), n
        else:
            assert list(a) == list(b), n


def test_build_features_with_truncated_history_bounded_windows_equal(tmp_path) -> None:
    rows = _rows(seed=9)
    types = {f"C{c:03d}": ("Газовый датчик" if c % 2 == 0 else "Состояние насоса") for c in range(10)}
    as_of = (T0 + timedelta(days=65)).date()
    cut = T0 + timedelta(days=65 - 40)            # история 40 суток ≥ 37 (окно 30 + активность 7)
    j_full, j_cut, c = tmp_path / "f.csv", tmp_path / "t.csv", tmp_path / "c.csv"
    _journal(rows).write_csv(j_full)
    _journal([r for r in rows if r[1] >= cut]).write_csv(j_cut)
    pl.DataFrame({"ид_канала_данных": list(types), "тип_инж_системы": ["x"] * 10, "тип_датчика": list(types.values()),
                  "ид_объект": ["1"] * 10}).write_csv(c)
    _, audit = ep.build_event_panel(pl, [j_full], c, TAX, log=lambda *a: None)
    bounded = [n for n in audit["feature_columns"] if n.endswith(("_7d", "_30d")) and "gas_cross" not in n
               and "completed" not in n]
    bundle = _fake_bundle(tmp_path, bounded)
    a = gp.build_features([j_full], c, as_of, bundle).sort_values("ид_канала_данных").reset_index(drop=True)
    b = gp.build_features([j_cut], c, as_of, bundle).sort_values("ид_канала_данных").reset_index(drop=True)
    for n in bounded:
        assert np.allclose(a[n].to_numpy(float), b[n].to_numpy(float), equal_nan=True), n


def test_refit_reproduction_check_matches_fold_2024(tmp_path) -> None:
    """Сверка с 15 внутри refit-прогона: отдельное обучение fold_2024 тем же кодом даёт тот же PR-AUC."""
    root = tmp_path / "in"
    rt.synthetic_panel_v3(root, n_channels=60, end=date(2026, 1, 10), gas_features=True)
    common = {"input_dir": str(root), "smoke_channel_share": 1, "latency_rows": 1000,
              "min_calibration_positives": 5, "min_train_positives": 5}
    exact = gb.run_export_v3(gb.make_config_export("SMOKE", "fold_2024_exact", {**common, "output_dir": str(tmp_path / "a")}),
                             log=lambda *a: None)
    expected = exact["audit"]["models"][gb.MODEL_NAME]["pr_auc"]
    refit = gb.run_export_v3(gb.make_config_export("SMOKE", "refit_2025h1", {
        **common, "output_dir": str(tmp_path / "b"), "expected_15_fold_2024_pr_auc": expected}), log=lambda *a: None)
    assert refit["reproduction_15"]["status"] == "reproduced"
    with pytest.raises(gb.ReleaseBlocked):     # fail-closed (GPT 29): при расхождении bundle не создаётся
        gb.run_export_v3(gb.make_config_export("SMOKE", "refit_2025h1", {
            **common, "output_dir": str(tmp_path / "c"), "expected_15_fold_2024_pr_auc": expected + 0.1}), log=lambda *a: None)
    res = json.loads((tmp_path / "c" / "results_export_16_v3.json").read_text(encoding="utf-8"))
    assert res["status"] == "reproduction_mismatch" and res["reproduction_15"]["status"] == "MISMATCH"
    assert not (tmp_path / "c" / f"{gb.BUNDLE_DIR_NAME}.zip").exists()
    assert not (tmp_path / "c" / gb.BUNDLE_DIR_NAME).exists()
    assert (tmp_path / "b" / f"{gb.BUNDLE_DIR_NAME}.zip.sha256").read_text().split()[0] == \
        rt.file_sha256(tmp_path / "b" / f"{gb.BUNDLE_DIR_NAME}.zip")


def test_release_gates_in_acceptance(exported) -> None:
    _, res, _ = exported
    acc = res["acceptance"]
    assert acc["missing_as_of_rejected"] and acc["bad_as_of_rejected"] and acc["tampered_file_rejected"]
    assert acc["typed_fields_present"]


def test_predict_requires_valid_as_of_date(exported) -> None:
    work, _, _ = exported
    bundle = gp.load_bundle(work / "out" / gb.BUNDLE_DIR_NAME)
    ex = json.loads((work / "out" / gb.BUNDLE_DIR_NAME / "example_request.json").read_text(encoding="utf-8"))
    for bad in (None, "", "2026-13-01", "2026-01-15junk", "15.01.2026"):
        with pytest.raises(gp.ContractError):
            gp.predict([{**ex[0], "as_of_date": bad}], bundle)
    with pytest.raises(gp.ContractError):
        gp.predict([{k: v for k, v in ex[0].items() if k != "as_of_date"}], bundle)
    o = gp.predict([{**ex[0], "as_of_date": date(2026, 1, 15)}], bundle)[0]
    assert o["observation_cutoff_date"] == "2026-01-15" and o["evidence_level"] == "E1"
    assert o["model_version"].startswith("gas-cross-g2-v3-refit_2025h1-")
    assert o["feature_contract_version"].startswith("event-panel-v3.0+tax-")


def test_build_features_rejects_insufficient_history(tmp_path) -> None:
    rows = _rows(seed=11, days=30)
    types = {f"C{c:03d}": "Газовый датчик" for c in range(10)}
    j, c = tmp_path / "j.csv", tmp_path / "c.csv"
    _journal(rows).write_csv(j)
    pl.DataFrame({"ид_канала_данных": list(types), "тип_инж_системы": ["x"] * 10, "тип_датчика": list(types.values()),
                  "ид_объект": ["1"] * 10}).write_csv(c)
    bundle = _fake_bundle(tmp_path, ["f_gas_n_7d"])
    bundle["spec"]["history_days_required"] = 400
    with pytest.raises(gp.ContractError, match="INSUFFICIENT_HISTORY"):
        gp.build_features([j], c, (T0 + timedelta(days=25)).date(), bundle)
    assert len(gp.build_features([j], c, (T0 + timedelta(days=25)).date(), bundle, min_history_days=20)) == 10


def test_repack_first16_bundle_without_retraining(exported, tmp_path) -> None:
    """Bundle первой версии 16 (predictor без release gates, без typed-полей) переупаковывается без обучения."""
    work, _, _ = exported
    v1 = tmp_path / "v1"
    shutil.copytree(work / "out" / gb.BUNDLE_DIR_NAME, v1)
    spec = json.loads((v1 / "bundle.json").read_text(encoding="utf-8"))
    for k in ("evidence_level", "evidence_level_meaning", "model_version", "feature_contract_version"):
        spec.pop(k)
    (v1 / "bundle.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    shutil.copy(ROOT / "tests" / "fixtures" / "gas_predictor_v3_first16.py", v1 / "predictor.py")
    sums = {str(p.relative_to(v1)): rt.file_sha256(p) for p in sorted(v1.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.json"}
    (v1 / "SHA256SUMS.json").write_text(json.dumps(sums), encoding="utf-8")
    new = gb.repack_bundle(v1, tmp_path / "out")
    rep = gb.verify_repack(new, v1, n=2000)
    assert rep["passed"] and rep["scores_identical"] and rep["same_model_sha"], rep
    assert (tmp_path / "out" / f"{gb.BUNDLE_DIR_NAME}.zip.sha256").exists()
    spec2 = json.loads((new / "bundle.json").read_text(encoding="utf-8"))
    assert spec2["repack"]["model_retrained"] is False and spec2["model_sha256"] == spec["model_sha256"]
