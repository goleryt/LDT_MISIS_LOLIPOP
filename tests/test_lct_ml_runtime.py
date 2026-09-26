"""Единый runtime для backend: загрузка bundle'ов по папке, газ + контекст обслуживания + модуль инцидентов."""

from __future__ import annotations

import json
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "ml" / "sensor_failure"))

import gas_bundle_v3 as gb  # noqa: E402
import incident_head_v1 as ih  # noqa: E402
import lct_ml_runtime as lr  # noqa: E402
import target_models_v3_runtime as rt  # noqa: E402

T0 = datetime(2024, 1, 1)
DAYS = 430
AS_OF = (T0 + timedelta(days=DAYS - 1)).date()
TYPES = ["Газовый датчик", "Газовый датчик", "Датчик дыма", "Состояние насоса", "КД Дверь"]


def _journal_and_catalogue(tmp: Path) -> tuple[Path, Path]:
    rnd = random.Random(3)
    rows, cat = [], []
    for o in range(3):
        for k, typ in enumerate(TYPES):
            ch = f"C{o}{k}"
            cat.append((ch, "ВК", typ, f"OBJ{o}"))
            for d in range(DAYS):
                silent = o == 0 and typ == "Газовый датчик" and DAYS - 13 <= d <= DAYS - 7   # 7 суток, вернулся за 6 дней до D
                if silent:
                    continue
                for _ in range(rnd.randint(1, 4)):
                    t = T0 + timedelta(days=d, seconds=rnd.randint(0, 86399))
                    v = f"{rnd.uniform(0, 0.6):.2f}".replace(".", ",") if typ == "Газовый датчик" else rnd.choice(["Норма", "Тревога", "Норма"])
                    rows.append((ch, t, v))
    j, c = tmp / "journal.csv", tmp / "catalogue.csv"
    pl.DataFrame({"ид_события": [str(i) for i in range(len(rows))], "ид_канала_данных": [r[0] for r in rows],
                  "дата": [r[1].strftime("%Y-%m-%d") for r in rows], "время": [r[1].strftime("%H:%M:%S") for r in rows],
                  "тревожное": ["f"] * len(rows), "значение_датчика": [r[2] for r in rows]}).write_csv(j)
    pl.DataFrame({"ид_канала_данных": [x[0] for x in cat], "тип_инж_системы": [x[1] for x in cat],
                  "тип_датчика": [x[2] for x in cat], "ид_объект": [x[3] for x in cat]}).write_csv(c)
    return j, c


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    work = tmp_path_factory.mktemp("rt")
    g_in = work / "gin"
    rt.synthetic_panel_v3(g_in, n_channels=80, end=date(2026, 1, 10), gas_features=True)
    gb.run_export_v3(gb.make_config_export("SMOKE", "refit_2025h1", {
        "input_dir": str(g_in), "output_dir": str(work / "g16"), "smoke_channel_share": 1, "latency_rows": 500,
        "min_calibration_positives": 5, "min_train_positives": 5}), log=lambda *a: None)
    ih.synthetic_incident_panel(work / "iin", n_objects=40)
    ih.run_incident_head(ih.make_config_18("SMOKE", {"input_dir": str(work / "iin"), "output_dir": str(work / "i18"),
                                                     "smoke_object_share": 1, "rate_per_object_year": 2.0,
                                                     "scenarios": {"medium": 2.0}}), log=lambda *a: None)
    bdir = work / "bundles"
    bdir.mkdir()
    for src, name in ((work / "g16", "gas_cross_v3_bundle"), (work / "i18", "incident_head_bundle")):
        for suf in (".zip", ".zip.sha256"):
            shutil.copy(src / f"{name}{suf}", bdir / f"{name}{suf}")
    j, c = _journal_and_catalogue(work)
    return work, bdir, j, c


def test_runtime_scores_gas_incidents_and_context(setup) -> None:
    work, bdir, j, c = setup
    r = lr.MLRuntime(bdir, work / "rtwork")
    kinds = sorted(b["kind"] for b in r.info()["bundles"])
    assert kinds == ["gas", "incident"] and r.primary_gas == "gas_cross_v3_bundle"
    out = r.score_day([j], c, AS_OF.isoformat(), request_id="req-1")
    assert out["as_of_date"] == AS_OF.isoformat() and out["gas"] and out["incidents"]
    ctx = {m["ид_объект"]: m for m in out["maintenance_context"]}
    assert ctx["OBJ0"]["maintenance_context"] == "possible_recent_silence"
    assert ctx["OBJ0"]["silence_length_days"] == 7 and ctx["OBJ0"]["silence_ended_days_ago"] == 6
    assert "OBJ1" not in ctx
    g = [x for x in out["gas"] if x.get("ид_объект") == "OBJ0"]
    assert g and all(x["maintenance_context"] == "possible_recent_silence" for x in g)
    assert all(x["maintenance_context"] == "unknown" for x in out["gas"] if x.get("ид_объект") == "OBJ1")
    assert {x["ид_объект"] for x in out["incidents"]} == {"OBJ0", "OBJ1", "OBJ2"}
    assert all(x["request_id"] == "req-1" for x in out["gas"] + out["incidents"])
    assert all(not x["recommendation"]["automated_action_allowed"] for x in out["gas"] + out["incidents"])
    assert all(x["recommendation"]["version"] == "manual-advisory-v1" for x in out["gas"] + out["incidents"])
    assert all(x["recommendation"]["code"] in {"DEMO_ONLY", "NO_INCIDENT_FORECAST"}
               for x in out["incidents"])
    ppr = [{"ид_объект": "OBJ2", "start": (AS_OF - timedelta(days=1)).isoformat(), "end": (AS_OF + timedelta(days=3)).isoformat()}]
    out2 = r.score_day([j], c, AS_OF, ppr_windows=ppr)
    assert {m["ид_объект"]: m for m in out2["maintenance_context"]}["OBJ2"]["maintenance_context"] == "verified_schedule"


def test_runtime_is_drop_in_for_a_second_gas_bundle(setup, tmp_path) -> None:
    """Новая газовая модель = ещё один ZIP + ACTIVE.json; код backend не меняется."""
    work, bdir, j, c = setup
    b2 = tmp_path / "bundles"
    shutil.copytree(bdir, b2)
    for suf in (".zip", ".zip.sha256"):
        shutil.copy(bdir / f"gas_cross_v3_bundle{suf}", b2 / f"gas_cross_v4_bundle{suf}")
    (b2 / "gas_cross_v4_bundle.zip.sha256").write_text((bdir / "gas_cross_v3_bundle.zip.sha256").read_text())
    (b2 / "ACTIVE.json").write_text(json.dumps({"gas": "gas_cross_v4_bundle"}))
    r = lr.MLRuntime(b2, tmp_path / "w")
    out = r.score_day([j], c, AS_OF, all_gas_bundles=True)
    names = {x["bundle"] for x in out["gas"]}
    assert names == {"gas_cross_v3_bundle", "gas_cross_v4_bundle"}
    assert all(x["is_primary"] == (x["bundle"] == "gas_cross_v4_bundle") for x in out["gas"])
    (b2 / "ACTIVE.json").write_text(json.dumps({"gas": "nope"}))
    with pytest.raises(lr.RuntimeContractError):
        lr.MLRuntime(b2, tmp_path / "w2")


def test_runtime_rejects_tampered_or_unsigned_bundle(setup, tmp_path) -> None:
    _, bdir, _, _ = setup
    b = tmp_path / "b"
    shutil.copytree(bdir, b)
    (b / "incident_head_bundle.zip.sha256").write_text("0" * 64 + "  incident_head_bundle.zip\n")
    with pytest.raises(lr.RuntimeContractError):
        lr.MLRuntime(b, tmp_path / "w")
    (b / "incident_head_bundle.zip.sha256").unlink()
    with pytest.raises(lr.RuntimeContractError):
        lr.MLRuntime(b, tmp_path / "w3")
    r = lr.MLRuntime(bdir, tmp_path / "w4")
    with pytest.raises(lr.RuntimeContractError):
        r.score_day([], "x.csv", "25.09.2026")
