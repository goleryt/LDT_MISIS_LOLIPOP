"""Synthetic contracts for research notebook 21; no project records are used."""

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
import gas_triage_v1 as gt  # noqa: E402
import generate_gas_triage_notebook as gen  # noqa: E402


def _seconds(channel: str, obj: str, t0: datetime, peak: float = 1.4,
             drop_min: int = 4, extra: list[tuple[int, float]] | None = None) -> list[dict]:
    values = [(-1, .2), (0, peak), (drop_min, .4)] + (extra or [])
    return [{"d_channel_key": channel, "d_object_key": obj,
             "t": t0 + timedelta(minutes=m), "mn": value, "mx": value} for m, value in values]


def _label(seconds: pl.DataFrame, archive_end: datetime | None = None) -> list[dict]:
    shapes = gt._event_shapes_for_bucket(pl, seconds.sort("d_channel_key", "t"))
    activity = seconds.select("d_object_key", pl.col("t").dt.date().alias("day")).unique()
    runs = gf.bounded_silence_runs(pl, seconds)
    return gt.label_events(shapes, activity, runs, archive_end or seconds["t"].max())


def test_cutoffs_repeat_and_same_second_neighbor() -> None:
    t0 = datetime(2024, 6, 10, 12)
    rows = _seconds("a", "o", t0, extra=[(10, 1.1)])
    rows += _seconds("b", "o", t0)  # simultaneous other channel
    rows += _seconds("c", "o", t0 + timedelta(minutes=15))
    rows += _seconds("d", "o", t0 + timedelta(minutes=15, seconds=1))
    events = _label(pl.DataFrame(rows), t0 + timedelta(hours=1))
    first = next(e for e in events if e["d_channel_key"] == "a" and e["cross_t"] == t0)
    assert first["repeat_by_c"] and first["triage_live"] == "needs_attention"
    assert first["other_ch_by_live_cutoff"] == 2  # b, c; d is after cutoff
    assert first["reason_codes"]["other_ch_by_live_cutoff"] == 2


def test_six_hour_left_boundary_and_strict_variant() -> None:
    t0 = datetime(2024, 6, 10, 12)
    rows = _seconds("a", "o", t0, drop_min=4)
    rows += _seconds("b", "o", t0 - timedelta(hours=6))
    rows += _seconds("c", "o", t0 - timedelta(hours=6, seconds=1))
    event = next(e for e in _label(pl.DataFrame(rows), t0 + timedelta(hours=1))
                 if e["d_channel_key"] == "a")
    assert event["other_ch_by_live_cutoff"] == 1
    assert event["state_at_c"] == "inferred_below"
    assert event["triage_live"] == "likely_bump_test"
    assert event["triage_live_strict"] == "needs_attention"


def test_mixed_second_is_not_a_proven_drop() -> None:
    t0 = datetime(2024, 6, 10, 12)
    rows = _seconds("a", "o", t0)
    rows[-1]["mx"] = 1.2  # second contains a below and an above reading
    event = _label(pl.DataFrame(rows), t0 + timedelta(hours=1))[0]
    assert not event["ended_fast"]
    assert event["triage_live"] == "needs_attention"


def test_shape_peak_and_observed_vs_inferred_state() -> None:
    t0 = datetime(2024, 6, 10, 12)
    rows = _seconds("a", "o", t0, peak=2.6, drop_min=5)
    rows += _seconds("b", "o", t0 + timedelta(minutes=1), peak=2.61)
    rows += _seconds("c", "o", t0 + timedelta(minutes=2), drop_min=6)
    events = _label(pl.DataFrame(rows), t0 + timedelta(hours=1))
    by_channel = {e["d_channel_key"]: e for e in events}
    assert by_channel["a"]["shape_ok"] and by_channel["a"]["state_at_c"] == "observed_below"
    assert by_channel["a"]["triage_live"] == "likely_bump_test"
    assert by_channel["b"]["triage_live"] == "needs_attention"
    assert by_channel["c"]["triage_live"] == "needs_attention"


def test_year_boundary_retro_censored_by_day_and_live_matures() -> None:
    t0 = datetime(2023, 12, 31, 23, 55)
    rows = _seconds("a", "o", t0, drop_min=7)
    seconds = pl.DataFrame(rows)
    event = _label(seconds, datetime(2024, 1, 1, 1))[0]
    assert event["status_at_day_end"] == "pending_at_day_end"
    assert event["triage_retro"] == "censored_by_day"
    assert event["triage_live"] == "needs_attention"  # drop after minute 5


def test_silence_requires_both_bounds_and_ninety_days() -> None:
    t0 = datetime(2024, 6, 10, 12)
    event = gt._event_shapes_for_bucket(pl, pl.DataFrame(_seconds("a", "o", t0)))[0]
    activity = pl.DataFrame({"d_object_key": ["o", "o"],
                             "day": [date(2024, 2, 1), date(2024, 6, 10)]})
    runs = pl.DataFrame({"d_object_key": ["o"], "start": [date(2024, 6, 2)],
                         "end": [date(2024, 6, 9)], "length": [8]})
    labeled = gt.label_events([event], activity, runs, t0 + timedelta(hours=1))[0]
    assert labeled["after_silence"] == "true"
    short = pl.DataFrame({"d_object_key": ["o"], "day": [date(2024, 6, 1)]})
    event2 = gt._event_shapes_for_bucket(pl, pl.DataFrame(_seconds("a", "o", t0)))[0]
    assert gt.label_events([event2], short, runs, t0 + timedelta(hours=1))[0]["after_silence"] == "unknown"


def test_notebook_embeds_current_code_and_compiles() -> None:
    notebook = gen.build_notebook()
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    embed = next("".join(cell["source"]) for cell in notebook["cells"]
                 if cell["cell_type"] == "code" and "SOURCES =" in "".join(cell["source"]))
    namespace: dict[str, object] = {}
    exec(embed, namespace)
    assert namespace["SOURCES"]["gas_triage_v1.py"] == (MODULE / "gas_triage_v1.py").read_text(encoding="utf-8")
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "21_gas_triage_audit_cpu.ipynb", "exec")
    exec(gen.SELF_TEST, {"gt": gt, "pl": pl})


def test_synthetic_end_to_end_writes_aggregates_only(tmp_path: Path) -> None:
    raw = tmp_path / "input"
    raw.mkdir()
    pl.DataFrame({"ид_канала_данных": ["secret-channel"],
                  "тип_инж_системы": ["Газоснабжение"],
                  "тип_датчика": ["Газовый датчик"],
                  "ид_объект": ["secret-object"]}).write_csv(raw / "справочник_каналов_датчиков.csv")
    base = datetime(2023, 7, 7, 12)
    points = [(base - timedelta(minutes=1), "0.2"), (base, "1.4"),
              (base + timedelta(minutes=4), "0.4")]
    pl.DataFrame({"ид_события": [str(i) for i in range(len(points))],
                  "ид_канала_данных": ["secret-channel"] * len(points),
                  "дата": [t.strftime("%Y-%m-%d") for t, _ in points],
                  "время": [t.strftime("%H:%M:%S") for t, _ in points],
                  "тревожное": ["false"] * len(points),
                  "значение_датчика": [v for _, v in points]}).write_parquet(raw / "ext-journal-2023.parquet")
    panel_dir = raw / "event_panel_v3"
    panel_dir.mkdir()
    part = panel_dir / "part.parquet"
    pl.DataFrame({"x": [1]}).write_parquet(part)
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps({
        "schema_version": "3.0", "rows": 1, "parts": [{"file": part.name, "sha256": gf._sha256(part)}]
    }), encoding="utf-8")
    cfg = gt.make_config_21("SMOKE", {"input_dir": str(raw), "output_dir": str(tmp_path / "out"),
                                     "stage_dir": str(tmp_path / "stage"), "smoke_years": [2023],
                                     "smoke_channel_share": 1, "channel_buckets": 2,
                                     "taxonomy_path": str(MODULE / "config" / "state_taxonomy_v3.json"),
                                     "expected_manifest_prefix": None})
    result = gt.run_stage21(cfg, log=lambda *_: None)
    assert result["crossings_total"] == 1
    for name in ("results_21_gas_triage.json", "summary_21_gas_triage_ru.md"):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert "secret-channel" not in text and "secret-object" not in text


def test_live_label_ignores_everything_after_cutoff() -> None:
    """V5: appending any data after c must not change triage_live."""
    t0 = datetime(2024, 6, 10, 12)
    c = t0 + timedelta(minutes=gt.LIVE_MINUTES)
    base = _seconds("a", "o", t0) + _seconds("b", "o", t0 - timedelta(hours=1))
    future = (_seconds("c", "o", c + timedelta(seconds=1))           # neighbor after c
              + _seconds("a", "o", t0 + timedelta(minutes=40), peak=3.0))  # later high alarm on a
    archive_end = t0 + timedelta(hours=3)

    def live(rows: list[dict]) -> str:
        return next(e for e in _label(pl.DataFrame(rows), archive_end)
                    if e["d_channel_key"] == "a" and e["cross_t"] == t0)["triage_live"]

    assert live(base) == live(base + future) == "likely_bump_test"


def test_walk_of_five_sensors_live_vs_retro() -> None:
    t0 = datetime(2024, 6, 11, 9)
    rows: list[dict] = []
    for i, ch in enumerate("abcde"):
        rows += _seconds(ch, "o", t0 + timedelta(minutes=20 * i))
    events = sorted(_label(pl.DataFrame(rows), datetime(2024, 6, 12, 12)), key=lambda e: e["cross_t"])
    assert [e["triage_live"] for e in events] == ["short_isolated"] + ["likely_bump_test"] * 4
    assert {e["triage_retro"] for e in events} == {"likely_bump_test"}


def test_long_event_after_silence_and_in_series_needs_attention() -> None:
    t0 = datetime(2024, 6, 10, 12)
    rows = _seconds("a", "o", t0, drop_min=30) + _seconds("b", "o", t0)
    shapes = gt._event_shapes_for_bucket(pl, pl.DataFrame(rows).sort("d_channel_key", "t"))
    activity = pl.DataFrame({"d_object_key": ["o", "o"], "day": [date(2024, 2, 1), date(2024, 6, 10)]})
    runs = pl.DataFrame({"d_object_key": ["o"], "start": [date(2024, 6, 2)],
                         "end": [date(2024, 6, 9)], "length": [8]})
    by_channel = {e["d_channel_key"]: e for e in gt.label_events(shapes, activity, runs, t0 + timedelta(hours=1))}
    assert by_channel["a"]["after_silence"] == "true" and by_channel["a"]["other_ch_by_live_cutoff"] == 1
    assert by_channel["a"]["triage_live"] == "needs_attention"
    assert by_channel["b"]["triage_live"] == "likely_after_maintenance"


def test_decision_cohort_matches_spec() -> None:
    assert gt.COHORT_PERIODS[0] == "le2022" and "2026H1" not in gt.COHORT_PERIODS
    assert set(gt.COHORT_PERIODS) == {p for block in gt.COHORT_BLOCKS.values() for p in block}
