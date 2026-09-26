"""Synthetic contracts for notebook 19; no project records are used."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE))

import gas_fingerprint_v4 as gf  # noqa: E402
import generate_gas_fingerprint_notebook as gen  # noqa: E402


def _seconds() -> pl.DataFrame:
    t0 = datetime(2024, 1, 2, 12, 0)
    return pl.DataFrame({
        "d_channel_key": ["c1"] * 4 + ["c2"] * 2,
        "d_object_key": ["o1"] * 6,
        "t": [t0, t0 + timedelta(minutes=1), t0 + timedelta(minutes=10), t0 + timedelta(minutes=20),
              t0, t0 + timedelta(minutes=1)],
        "mn": [0.4, 1.2, 1.8, 0.8, 0.4, 0.5],
        "mx": [0.4, 1.2, 1.8, 0.8, 0.4, 1.3],
    })


def test_strict_crossing_peak_duration_rise_and_same_second() -> None:
    events = gf.strict_crossing_features(pl, _seconds())
    assert events.height == 1  # c2 second {0.5, 1.3} is ambiguous, never strict
    row = events.row(0, named=True)
    assert row["peak_60m"] == 1.8
    assert row["minutes_ge_1"] == 19.0
    assert row["rise_minutes"] == 1.0
    assert row["duration_censored"] is False


def test_silence_context_is_bounded_and_future_run_cannot_change_age() -> None:
    base = datetime(2024, 1, 1, 8)
    sec = pl.DataFrame({
        "d_channel_key": ["c"] * 4, "d_object_key": ["o"] * 4,
        "t": [base, base + timedelta(days=6), base + timedelta(days=7), base + timedelta(days=20)],
        "mn": [0.2] * 4, "mx": [0.2] * 4,
    })
    runs = gf.bounded_silence_runs(pl, sec, 4)
    assert runs.select("length").to_series().to_list() == [5, 12]
    crossing = pl.DataFrame({
        "d_channel_key": ["c"], "d_object_key": ["o"], "cross_t": [base + timedelta(days=7)],
        "day": [(base + timedelta(days=7)).date()], "peak_60m": [1.2], "minutes_ge_1": [2.0],
        "duration_censored": [False], "rise_minutes": [1.0], "hour": [8], "is_weekend": [False],
    })
    a = gf.add_maintenance_context(pl, crossing, runs.head(1))["days_since_silence_end"][0]
    b = gf.add_maintenance_context(pl, crossing, runs)["days_since_silence_end"][0]
    assert a == b == 2


def test_fingerprint_uses_only_pre2025_and_has_deterministic_tie_break() -> None:
    rows = []
    for i, peak in enumerate([2.01, 2.02, 2.21, 2.22]):  # two modal bins tie; lower wins
        rows.append({"day": date(2024, 1, 1) + timedelta(days=i), "in_posthoc_window": True,
                     "peak_60m": peak, "minutes_ge_1": 10.0, "duration_censored": False})
    early = pl.DataFrame(rows)
    first = gf.fit_fingerprint(early)
    late = pl.concat([early, pl.DataFrame([{"day": date(2026, 1, 1), "in_posthoc_window": True,
                                           "peak_60m": 4.9, "minutes_ge_1": 1440.0,
                                           "duration_censored": True}])], how="vertical")
    assert gf.fit_fingerprint(late) == first
    assert first["modal_bin_low"] == 2.0


def test_panel_preflight_rejects_foreign_manifest(tmp_path: Path) -> None:
    pdir = tmp_path / "event_panel_v3"
    pdir.mkdir()
    part = pdir / "part.parquet"
    pl.DataFrame({"x": [1]}).write_parquet(part)
    manifest = {"schema_version": "3.0", "rows": 1,
                "parts": [{"file": part.name, "sha256": gf._sha256(part)}]}
    (pdir / "panel_manifest_v3.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(gf.PanelMismatch):
        gf.discover_panel(tmp_path, expected_prefix="8cb6e0e2584f")
    parts, loaded, _ = gf.discover_panel(tmp_path, expected_prefix=None)
    assert parts == [part] and loaded["rows"] == 1


def test_aggregate_output_has_no_identifier_fields() -> None:
    result = {"status": "ok", "counts": {"events": 3}}
    assert "d_object_key" not in gf._safe_result_text(result)
    with pytest.raises(AssertionError):
        gf._safe_result_text({"d_object_key": "secret"})


def test_stage19_small_end_to_end_writes_aggregates_only(tmp_path: Path) -> None:
    raw = tmp_path / "input"
    raw.mkdir()
    catalogue = pl.DataFrame({
        "ид_канала_данных": ["raw-channel-1"],
        "тип_инж_системы": ["Газоснабжение"],
        "тип_датчика": ["Газовый датчик"],
        "ид_объект": ["raw-object-1"],
    })
    catalogue.write_csv(raw / "справочник_каналов_датчиков.csv")
    event_times = [
        datetime(2023, 7, 1, 12), datetime(2023, 7, 7, 11, 59),
        datetime(2023, 7, 7, 12), datetime(2023, 7, 7, 12, 10),
        datetime(2023, 7, 7, 12, 20),
    ]
    values = ["0.2", "0.4", "1.2", "1.8", "0.8"]
    journal = pl.DataFrame({
        "ид_события": [str(i) for i in range(len(values))],
        "ид_канала_данных": ["raw-channel-1"] * len(values),
        "дата": [t.strftime("%Y-%m-%d") for t in event_times],
        "время": [t.strftime("%H:%M:%S") for t in event_times],
        "тревожное": ["false"] * len(values),
        "значение_датчика": values,
    })
    journal.write_parquet(raw / "ext-journal-2023.parquet")

    panel_dir = raw / "event_panel_v3"
    panel_dir.mkdir()
    part = panel_dir / "event_panel_v3_part00.parquet"
    pl.DataFrame({
        "d_channel_key": [gf.ep.pseudo_key("raw-channel-1")],
        "d_object_key": [gf.ep.pseudo_key("raw-object-1")],
        "d_cutoff_date": [date(2023, 7, 5)],
        gf.TARGET: [1],
    }).write_parquet(part)
    manifest = {"schema_version": "3.0", "rows": 1,
                "parts": [{"file": part.name, "sha256": gf._sha256(part)}]}
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(manifest), encoding="utf-8")

    out = tmp_path / "out"
    cfg = gf.make_config_19("FULL", {
        "input_dir": str(raw), "output_dir": str(out), "stage_dir": str(tmp_path / "stage"),
        "taxonomy_path": str(MODULE / "config" / "state_taxonomy_v3.json"),
        "expected_manifest_prefix": None,
    })
    result = gf.run_stage19(cfg, log=lambda *_: None)
    assert result["status"] == "completed" and result["crossings_total"] == 1
    power = result["power"]["periods"]["2023H2"]
    assert power["t_raw_positives"] == 1
    assert power["positives_in_window_excluded_from_clean_target"] == 1
    assert power["positives_outside_window"] == 0
    for name in ("results_19_gas_fingerprint.json", "summary_19_gas_fingerprint_ru.md"):
        text = (out / name).read_text(encoding="utf-8")
        assert "raw-channel-1" not in text and "raw-object-1" not in text


def test_generated_notebook_embeds_current_code_and_compiles() -> None:
    notebook = gen.build_notebook()
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert "results_19_gas_fingerprint.json" in source
    embed_cell = next("".join(cell["source"]) for cell in notebook["cells"]
                      if cell["cell_type"] == "code" and "SOURCES =" in "".join(cell["source"]))
    namespace: dict[str, object] = {}
    exec(embed_cell, namespace)
    assert namespace["SOURCES"]["gas_fingerprint_v4.py"] == (MODULE / "gas_fingerprint_v4.py").read_text(encoding="utf-8")
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "19_gas_fingerprint_diagnostics_cpu.ipynb", "exec")
