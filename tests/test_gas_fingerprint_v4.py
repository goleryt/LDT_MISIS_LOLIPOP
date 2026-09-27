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


def test_disk_buckets_preserve_cross_year_channel_history(tmp_path: Path) -> None:
    t0 = datetime(2023, 12, 31, 23, 59)
    seconds = pl.DataFrame({
        "d_channel_key": ["c1", "c1", "c1", "c2"],
        "d_object_key": ["o1", "o1", "o1", "o2"],
        "t": [t0, t0 + timedelta(minutes=1), t0 + timedelta(minutes=2), t0],
        "mn": [0.2, 1.2, 0.7, 0.1],
        "mx": [0.2, 1.2, 0.7, 0.1],
    })
    paths = [tmp_path / "2023.parquet", tmp_path / "2024.parquet"]
    cfg = gf.make_config_19("FULL", {"channel_buckets": 3})
    staged = seconds.with_columns(
        (pl.col("d_channel_key").hash(seed=19) % cfg["channel_buckets"])
        .cast(pl.UInt16).alias("_channel_bucket")
    ).sort("_channel_bucket", "d_channel_key", "t")
    staged.filter(pl.col("t").dt.year() == 2023).write_parquet(paths[0])
    staged.filter(pl.col("t").dt.year() == 2024).write_parquet(paths[1])

    bucketed, activity = gf.process_seconds_buckets(pl, paths, cfg, log=lambda *_: None)
    expected = gf.strict_crossing_features(
        pl, seconds.sort("d_channel_key", "t"), cfg["threshold"], cfg["rise_threshold"],
        cfg["peak_window_minutes"], cfg["duration_cap_minutes"],
    )

    assert bucketed.sort("d_channel_key", "cross_t").to_dicts() == expected.to_dicts()
    assert activity.sort("d_object_key", "day").to_dicts() == [
        {"d_object_key": "o1", "day": date(2023, 12, 31)},
        {"d_object_key": "o1", "day": date(2024, 1, 1)},
        {"d_object_key": "o2", "day": date(2023, 12, 31)},
    ]


def test_rise_uses_last_low_reading_and_long_gaps_are_binned() -> None:
    """searchsorted rise == naive scan; a return after a multi-day gap falls into gt1440."""
    t0 = datetime(2024, 3, 1, 8)
    sec = pl.DataFrame({
        "d_channel_key": ["c"] * 6, "d_object_key": ["o"] * 6,
        "t": [t0, t0 + timedelta(minutes=5), t0 + timedelta(minutes=6), t0 + timedelta(minutes=30),
              t0 + timedelta(days=3), t0 + timedelta(days=3, minutes=1)],
        "mn": [0.3, 0.7, 1.4, 0.2, 2.2, 0.1],
        "mx": [0.3, 0.7, 1.4, 0.2, 2.2, 0.1],
    })
    ev = gf.strict_crossing_features(pl, sec).sort("cross_t")
    assert ev.height == 2
    assert ev["rise_minutes"].to_list() == [6.0, 3 * 1440 - 30.0]
    ev = ev.with_columns(pl.lit(1).alias("same_object_same_day"), pl.lit(None, dtype=pl.Int32).alias("days_since_silence_end"))
    hist = gf.stratum_summary(ev)["rise_minutes_hist"]
    assert hist["le1"] == 0 and hist["gt5_le15"] == 1 and hist["gt1440"] == 1


def test_gas_seconds_pseudonyms_match_pseudo_key() -> None:
    tax = gf.ep.load_taxonomy(MODULE / "config" / "state_taxonomy_v3.json")
    cat = pl.DataFrame({"ид_канала_данных": ["A", "B"], "тип_инж_системы": ["x", "x"],
                        "тип_датчика": ["Газовый датчик", "Газовый датчик"], "ид_объект": ["O1", "O2"]})
    raw = pl.DataFrame({"ид_события": ["1", "2", "3"], "ид_канала_данных": ["A", "B", "A"],
                        "дата": ["2024-01-01"] * 3, "время": ["10:00:00", "10:00:00", "10:00:01"],
                        "тревожное": ["f"] * 3, "значение_датчика": ["0,2", "0,3", "1,5"]})
    sec = gf.gas_seconds_from_raw(pl, raw, cat, tax)
    got = set(sec.select("d_channel_key", "d_object_key").unique().iter_rows())
    assert got == {(gf.ep.pseudo_key("A"), gf.ep.pseudo_key("O1")), (gf.ep.pseudo_key("B"), gf.ep.pseudo_key("O2"))}
    assert sec.height == 3


def test_sanity_vs_17_flags_large_drift() -> None:
    per = {"2025H2": {"positives_in_window_excluded_from_clean_target": 531, "positives_outside_window": 34},
           "2026H1": {"positives_in_window_excluded_from_clean_target": 150, "positives_outside_window": 117}}
    sv = gf.sanity_vs_17(per, {"mode": "FULL"})
    assert sv["periods"]["2025H2"]["within_tolerance"] and not sv["periods"]["2026H1"]["within_tolerance"]
    assert not sv["all_within_tolerance"]
