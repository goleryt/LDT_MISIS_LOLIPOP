"""Notebook 19: aggregate diagnostics of gas crossings around suspected maintenance.

This module does not train or score a model.  It reuses the event-panel-v3
classification contract, detects strict upward crossings at second resolution,
describes their observable shape, and evaluates whether there is enough support
outside post-hoc suspected-maintenance windows to justify a separate stage 20.

Only aggregate results may leave the runtime.  Channel/object keys are used
internally and are never serialized.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

import event_panel_v3 as ep
import event_panel_v3_kaggle as kag

TARGET = "target_t4_gas_cross"
EXPECTED_PANEL_MANIFEST_PREFIX = "8cb6e0e2584f"
PERIODS = (
    ("le2022", None, date(2023, 1, 1)),
    ("2023H1", date(2023, 1, 1), date(2023, 7, 1)),
    ("2023H2", date(2023, 7, 1), date(2024, 1, 1)),
    ("2024H1", date(2024, 1, 1), date(2024, 7, 1)),
    ("2024H2", date(2024, 7, 1), date(2025, 1, 1)),
    ("2025H1", date(2025, 1, 1), date(2025, 7, 1)),
    ("2025H2", date(2025, 7, 1), date(2026, 1, 1)),
    ("2026H1", date(2026, 1, 1), date(2026, 7, 1)),
)
DEV_PERIODS = ("2023H2", "2024H1", "2024H2")
# Audit 17 v2 (same frozen panel): positives in / outside the post-hoc window. Windows there were built from panel
# gas_max, here from raw gas seconds; 17 also required d_label_decision_end <= period end. Small drift is expected.
REFERENCE_17 = {"2025H2": {"in_window": 531, "outside_window": 33}, "2026H1": {"in_window": 226, "outside_window": 117}}
SANITY_TOLERANCE = 0.10


class PanelMismatch(ValueError):
    """The supplied panel is not the frozen notebook-14 output expected by v3."""


def make_config_19(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode not in ("FULL", "SMOKE"):
        raise ValueError("MODE must be FULL or SMOKE")
    cfg: dict[str, Any] = {
        "mode": mode,
        "input_dir": os.environ.get("LDT_KAGGLE_INPUT_DIR", "/kaggle/input"),
        "output_dir": os.environ.get("LDT_OUTPUT_DIR", "/kaggle/working"),
        "stage_dir": os.environ.get("LDT_STAGE_DIR", "/tmp/ldt_gas_fingerprint_19"),
        "taxonomy_path": None,
        "threshold": 1.0,
        "rise_threshold": 0.5,
        "peak_window_minutes": 60,
        "duration_cap_minutes": 1440,
        "min_silence_days": 4,
        "before_days": 3,
        "after_days": 21,
        "expected_manifest_prefix": EXPECTED_PANEL_MANIFEST_PREFIX,
        "verify_sha256": True,
        "smoke_years": [2023, 2024],
        "smoke_channel_share": 20,
        # Bound peak RAM: every bucket contains complete cross-year histories for its channels.
        "channel_buckets": 64,
        "keep_stage": False,
    }
    cfg.update(overrides or {})
    return cfg


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 22):
            h.update(block)
    return h.hexdigest()


def discover_panel(input_dir: Path, verify: bool = True,
                   expected_prefix: str | None = EXPECTED_PANEL_MANIFEST_PREFIX) -> tuple[list[Path], dict[str, Any], Path]:
    manifests = sorted(Path(input_dir).rglob("panel_manifest_v3.json"))
    if not manifests:
        raise FileNotFoundError("panel_manifest_v3.json not found: attach the frozen notebook-14 output")
    path = manifests[0]
    digest = _sha256(path)
    if expected_prefix and not digest.startswith(expected_prefix):
        raise PanelMismatch(
            f"panel manifest {digest} is not the frozen v3 panel (expected prefix {expected_prefix}); do not bypass preflight"
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != ep.SCHEMA_VERSION:
        raise PanelMismatch(f"panel schema {manifest.get('schema_version')} != {ep.SCHEMA_VERSION}")
    parts: list[Path] = []
    for item in manifest.get("parts", []):
        part = path.parent / item["file"]
        if not part.is_file():
            raise PanelMismatch(f"missing panel part: {item['file']}")
        if verify and _sha256(part) != item.get("sha256"):
            raise PanelMismatch(f"SHA-256 mismatch for panel part: {item['file']}")
        parts.append(part)
    if not parts:
        raise PanelMismatch("panel manifest contains no parts")
    return parts, manifest, path


def preflight_sources(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = kag.discover_sources(Path(cfg["input_dir"]))
    if not raw["journals"] or raw["catalogue"] is None:
        raise FileNotFoundError("raw ext-journal-YYYY inputs and the sensor-channel catalogue are required")
    parts, manifest, path = discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"],
                                            cfg.get("expected_manifest_prefix"))
    return {
        "journal_years": list(raw["journals"]),
        "catalogue_found": True,
        "panel_manifest_sha256": _sha256(path),
        "panel_rows": int(manifest["rows"]),
        "panel_parts": len(parts),
    }


def gas_seconds_from_raw(pl: Any, raw: Any, catalogue: Any, taxonomy: dict[str, Any]) -> Any:
    """Return one unordered-value-set row per gas channel/second."""
    gas_type = taxonomy["numeric"]["gas_sensor_type"]
    gas_ids = (catalogue.filter(pl.col("тип_датчика") == gas_type)
               .select("ид_канала_данных").drop_nulls().unique())
    if gas_ids.is_empty():
        return pl.DataFrame(schema={"d_channel_key": pl.String, "d_object_key": pl.String,
                                    "t": pl.Datetime("us"), "mn": pl.Float64, "mx": pl.Float64})
    subset = raw.join(gas_ids, on="ид_канала_данных", how="semi")
    ev = ep.classify_events(pl, subset, taxonomy, catalogue).filter(
        (pl.col("cls") == "numeric") & pl.col("is_gas") & pl.col("ид_объект").is_not_null()
    )
    # Pseudonyms are computed once per unique id (as in event_panel_v3), not per row: tens of millions of rows.
    ev = ev.with_columns(pl.col("ch").cast(pl.String), pl.col("ид_объект").cast(pl.String))
    ch_map = ep.key_map(pl, ev["ch"].unique().to_list(), "d_channel_key").rename({"raw": "ch"})
    obj_map = ep.key_map(pl, ev["ид_объект"].unique().to_list(), "d_object_key").rename({"raw": "ид_объект"})
    ev = ev.join(ch_map, on="ch", how="left").join(obj_map, on="ид_объект", how="left")
    return (ev.group_by("d_channel_key", "d_object_key", "t").agg(
        pl.col("num").min().alias("mn"), pl.col("num").max().alias("mx")
    ))


def strict_crossing_features(pl: Any, seconds: Any, threshold: float = 1.0, rise_threshold: float = 0.5,
                             peak_window_minutes: int = 60, duration_cap_minutes: int = 1440) -> Any:
    """Detect strict crossings and calculate shape features from second-level value sets.

    A second containing values on both sides of the threshold is never strict.
    The previous second must be unambiguously below the threshold.  Durations are
    capped at 24h and explicitly marked as censored.
    """
    schema = {"d_channel_key": pl.String, "d_object_key": pl.String, "cross_t": pl.Datetime("us"),
              "day": pl.Date, "peak_60m": pl.Float64, "minutes_ge_1": pl.Float64,
              "duration_censored": pl.Boolean, "rise_minutes": pl.Float64, "hour": pl.Int8,
              "is_weekend": pl.Boolean}
    if seconds.is_empty():
        return pl.DataFrame(schema=schema)
    rows: list[dict[str, Any]] = []
    peak_s = peak_window_minutes * 60
    cap_s = duration_cap_minutes * 60
    for group in seconds.sort("d_channel_key", "t").partition_by("d_channel_key", maintain_order=True):
        times = group["t"].to_numpy().astype("datetime64[us]").astype(np.int64)
        mn = group["mn"].to_numpy()
        mx = group["mx"].to_numpy()
        objects = group["d_object_key"].to_list()
        channels = group["d_channel_key"].to_list()
        strict = np.flatnonzero((mn[1:] >= threshold) & (mx[:-1] < threshold)) + 1
        low_idx = np.flatnonzero(mx < rise_threshold)
        for i in strict:
            t0 = int(times[i])
            peak_end = int(np.searchsorted(times, t0 + peak_s * 1_000_000, side="right"))
            peak = float(np.nanmax(mx[i:peak_end]))
            duration_end = int(np.searchsorted(times, t0 + cap_s * 1_000_000, side="right"))
            drop_rel = np.flatnonzero(mn[i + 1:duration_end] < threshold)
            if len(drop_rel):
                j = i + 1 + int(drop_rel[0])
                duration = (int(times[j]) - t0) / 60_000_000
                censored = False
            else:
                duration = float(duration_cap_minutes)
                censored = True
            k = int(np.searchsorted(low_idx, i)) - 1        # last reading < rise_threshold before i (low_idx sorted)
            rise = None if k < 0 else (t0 - int(times[int(low_idx[k])])) / 60_000_000
            dt = group["t"][int(i)]
            rows.append({
                "d_channel_key": channels[i], "d_object_key": objects[i], "cross_t": dt,
                "day": dt.date(), "peak_60m": peak, "minutes_ge_1": float(duration),
                "duration_censored": censored, "rise_minutes": None if rise is None else float(rise),
                "hour": dt.hour, "is_weekend": dt.weekday() >= 5,
            })
    return pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)


def bounded_silence_runs_from_activity(pl: Any, observed: Any, min_silence_days: int = 4) -> Any:
    """Bounded gaps between observed object-days; no leading/trailing invented gaps."""
    schema = {"d_object_key": pl.String, "start": pl.Date, "end": pl.Date, "length": pl.Int32}
    if observed.is_empty():
        return pl.DataFrame(schema=schema)
    observed = observed.unique().sort("d_object_key", "day")
    rows: list[dict[str, Any]] = []
    for group in observed.partition_by("d_object_key", maintain_order=True):
        days = group["day"].to_list()
        obj = group["d_object_key"][0]
        for left, right in zip(days, days[1:]):
            length = (right - left).days - 1
            if length >= min_silence_days:
                rows.append({"d_object_key": obj, "start": left + timedelta(days=1),
                             "end": right - timedelta(days=1), "length": length})
    return pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)


def bounded_silence_runs(pl: Any, seconds: Any, min_silence_days: int = 4) -> Any:
    """Bounded gaps between real object gas-reading days; no leading/trailing invented gaps."""
    if seconds.is_empty():
        observed = pl.DataFrame(schema={"d_object_key": pl.String, "day": pl.Date})
    else:
        observed = seconds.select("d_object_key", pl.col("t").dt.date().alias("day")).unique()
    return bounded_silence_runs_from_activity(pl, observed, min_silence_days)


def process_seconds_buckets(pl: Any, paths: list[Path], cfg: dict[str, Any], log: Any = print) -> tuple[Any, Any]:
    """Process complete channel histories in bounded-RAM hash buckets."""
    n_buckets = int(cfg["channel_buckets"])
    if not 1 <= n_buckets <= 65_535:
        raise ValueError("channel_buckets must be between 1 and 65535")
    crossing_frames = []
    activity_frames = []
    scans = [pl.scan_parquet(path) for path in paths]
    for bucket in range(n_buckets):
        seconds = (pl.concat(scans, how="vertical_relaxed")
                   .filter(pl.col("_channel_bucket") == bucket)
                   .collect()
                   .sort("d_channel_key", "t"))
        if seconds.is_empty():
            continue
        crossing_frames.append(strict_crossing_features(
            pl, seconds, cfg["threshold"], cfg["rise_threshold"],
            cfg["peak_window_minutes"], cfg["duration_cap_minutes"],
        ))
        activity_frames.append(
            seconds.select("d_object_key", pl.col("t").dt.date().alias("day")).unique()
        )
        log(f"channel bucket {bucket + 1}/{n_buckets}: {seconds.height:,} gas seconds")
        del seconds
        gc.collect()
    empty_seconds = pl.DataFrame(schema={"d_channel_key": pl.String, "d_object_key": pl.String,
                                         "t": pl.Datetime("us"), "mn": pl.Float64, "mx": pl.Float64})
    crossings = (pl.concat(crossing_frames, how="vertical_relaxed") if crossing_frames
                 else strict_crossing_features(pl, empty_seconds))
    activity = (pl.concat(activity_frames, how="vertical_relaxed").unique()
                if activity_frames else
                pl.DataFrame(schema={"d_object_key": pl.String, "day": pl.Date}))
    return crossings, activity


def add_maintenance_context(pl: Any, crossings: Any, runs: Any, before_days: int = 3,
                            after_days: int = 21) -> Any:
    """Attach post-hoc strata and causal time-since-return at the crossing instant."""
    if crossings.is_empty():
        return crossings.with_columns(pl.lit(False).alias("in_posthoc_window"),
                                      pl.lit(None, dtype=pl.Int32).alias("days_since_silence_end"),
                                      pl.lit(False).alias("silence_ongoing_at_event"))
    by_object = {g["d_object_key"][0]: g.sort("start") for g in runs.partition_by("d_object_key")}
    flags: list[bool] = []
    ages: list[int | None] = []
    for obj, day in crossings.select("d_object_key", "day").iter_rows():
        group = by_object.get(obj)
        if group is None:
            flags.append(False)
            ages.append(None)
            continue
        in_window = False
        latest_end: date | None = None
        for start, end in group.select("start", "end").iter_rows():
            if start - timedelta(days=before_days) <= day <= end + timedelta(days=after_days):
                in_window = True
            # The crossing itself is a real reading, so a run ending before its day is known by the event time.
            if end < day and (latest_end is None or end > latest_end):
                latest_end = end
        flags.append(in_window)
        ages.append(None if latest_end is None else (day - latest_end).days)
    return crossings.with_columns(
        pl.Series("in_posthoc_window", flags),
        pl.Series("days_since_silence_end", ages, dtype=pl.Int32),
        # Always False by construction: the crossing itself is a real gas reading, so the object is not silent at
        # the event instant. Kept as an explicit column for the stage-20 feature contract (003 A3).
        pl.lit(False).alias("silence_ongoing_at_event"),
    )


def add_same_object_count(pl: Any, crossings: Any) -> Any:
    if crossings.is_empty():
        return crossings.with_columns(pl.lit(0, dtype=pl.Int32).alias("same_object_same_day"))
    counts = (crossings.group_by("d_object_key", "day")
              .agg(pl.col("d_channel_key").n_unique().cast(pl.Int32).alias("same_object_same_day")))
    return crossings.join(counts, on=["d_object_key", "day"], how="left")


def period_name(day: date) -> str | None:
    for name, start, end in PERIODS:
        if (start is None or day >= start) and day < end:
            return name
    return None


def _hist(values: list[float | int | None], edges: list[float], labels: list[str]) -> dict[str, int]:
    out = {label: 0 for label in labels}
    for value in values:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            out.setdefault("missing", 0)
            out["missing"] += 1
            continue
        idx = int(np.searchsorted(np.asarray(edges), float(value), side="right"))
        out[labels[min(idx, len(labels) - 1)]] += 1
    return out


def _quartiles(values: list[float | int | None]) -> dict[str, float | None]:
    a = np.asarray([float(v) for v in values if v is not None and not math.isnan(float(v))], dtype=float)
    if not len(a):
        return {"q1": None, "median": None, "q3": None}
    q = np.quantile(a, [0.25, 0.5, 0.75])
    return {"q1": round(float(q[0]), 6), "median": round(float(q[1]), 6), "q3": round(float(q[2]), 6)}


def stratum_summary(frame: Any) -> dict[str, Any]:
    peak = frame["peak_60m"].to_list()
    duration = frame["minutes_ge_1"].to_list()
    rise = frame["rise_minutes"].to_list()
    same = frame["same_object_same_day"].to_list()
    silence_age = frame["days_since_silence_end"].to_list()
    censored = frame["duration_censored"].to_list()
    duration_hist = {"le5": 0, "gt5_le15": 0, "gt15_le60": 0, "gt60": 0, "censored": 0}
    for value, is_censored in zip(duration, censored):
        if is_censored:
            duration_hist["censored"] += 1
        elif value <= 5:
            duration_hist["le5"] += 1
        elif value <= 15:
            duration_hist["gt5_le15"] += 1
        elif value <= 60:
            duration_hist["gt15_le60"] += 1
        else:
            duration_hist["gt60"] += 1
    return {
        "events": frame.height,
        "peak_60m_hist": _hist(peak, [1.5, 1.9, 2.6, 3.8, 4.6],
                                ["1.0_1.5", "1.5_1.9", "1.9_2.6", "2.6_3.8", "3.8_4.6", "gt4.6"]),
        "minutes_ge_1_hist": duration_hist,
        "rise_minutes_hist": _hist(rise, [1, 5, 15, 60, 1440],
                                   ["le1", "gt1_le5", "gt5_le15", "gt15_le60", "gt60_le1440", "gt1440"]),
        "days_since_silence_end_hist": _hist(
            silence_age, [1, 7, 21, 60], ["le1", "gt1_le7", "gt7_le21", "gt21_le60", "gt60"]
        ),
        "hour_hist": {str(h): int(frame.filter(frame["hour"] == h).height) for h in range(24)},
        "weekday": int(frame.filter(~frame["is_weekend"]).height),
        "weekend": int(frame.filter(frame["is_weekend"]).height),
        "same_object_same_day_hist": _hist(same, [1.5, 2.5, 3.5], ["1", "2", "3", "ge4"]),
        "quartiles": {"peak_60m": _quartiles(peak), "minutes_ge_1": _quartiles(duration),
                      "rise_minutes": _quartiles(rise), "days_since_silence_end": _quartiles(silence_age),
                      "same_object_same_day": _quartiles(same)},
    }


def fit_fingerprint(events: Any) -> dict[str, Any]:
    train = events.filter((events["day"] < date(2025, 1, 1)) & events["in_posthoc_window"]
                          & (events["peak_60m"] >= 1.5) & (events["peak_60m"] <= 5.0))
    if train.is_empty():
        return {"status": "insufficient_events", "n": 0}
    peaks = train["peak_60m"].to_numpy()
    bin_index = np.minimum(np.floor((peaks - 1.5) / 0.1).astype(int), 34)
    counts = np.bincount(bin_index, minlength=35)
    winner = int(np.flatnonzero(counts == counts.max())[0])
    center = 1.5 + (winner + 0.5) * 0.1
    q1, q3 = np.quantile(peaks, [0.25, 0.75])
    durations = np.sort(train["minutes_ge_1"].to_numpy())
    rank = max(1, int(math.ceil(0.95 * len(durations)))) - 1
    p95 = float(durations[rank])
    censored_share = float(train["duration_censored"].mean())
    return {
        "status": "locked", "n": train.height, "training_cutoff": "2025-01-01",
        "modal_bin_low": round(1.5 + winner * 0.1, 6), "modal_center": round(center, 6),
        "plateau_q1": round(float(q1), 6), "plateau_q3": round(float(q3), 6),
        "max_minutes_p95_nearest_rank": round(p95, 6), "censored_share": round(censored_share, 6),
        "duration_is_lower_bound": bool(p95 >= 1440 or censored_share >= 0.05),
    }


def apply_fingerprint(pl: Any, events: Any, fingerprint: dict[str, Any]) -> Any:
    if fingerprint.get("status") != "locked":
        return events.with_columns(pl.lit(False).alias("strict_fingerprint_match"))
    return events.with_columns(
        (pl.col("peak_60m").is_between(fingerprint["plateau_q1"], fingerprint["plateau_q3"], closed="both")
         & (pl.col("minutes_ge_1") <= fingerprint["max_minutes_p95_nearest_rank"]))
        .alias("strict_fingerprint_match")
    )


def aggregate_crossings(pl: Any, events: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, _, _ in PERIODS:
        p = events.filter(pl.col("period") == name)
        out[name] = {}
        for window, flag in (("in_window", True), ("out_window", False)):
            s = p.filter(pl.col("in_posthoc_window") == flag)
            summary = stratum_summary(s)
            if not flag:
                matches = int(s["strict_fingerprint_match"].sum()) if "strict_fingerprint_match" in s.columns else 0
                summary["strict_fingerprint_matches"] = matches
                summary["strict_fingerprint_share"] = matches / s.height if s.height else None
            out[name][window] = summary
    return out


def _posthoc_intervals(runs: Any, before: int, after: int) -> dict[str, list[tuple[date, date]]]:
    out: dict[str, list[tuple[date, date]]] = {}
    for obj, start, end in runs.select("d_object_key", "start", "end").iter_rows():
        out.setdefault(obj, []).append((start - timedelta(days=before), end + timedelta(days=after)))
    return out


def panel_power(pl: Any, parts: list[Path], runs: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    lf = pl.scan_parquet(parts).filter(pl.col(TARGET) == 1)
    if cfg["mode"] == "SMOKE":
        lf = lf.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
    positives = lf.select("d_object_key", "d_cutoff_date").collect()
    windows = _posthoc_intervals(runs, cfg["before_days"], cfg["after_days"])
    rows: list[dict[str, Any]] = []
    for obj, cutoff in positives.iter_rows():
        outcome_day = cutoff + timedelta(days=2)
        period = period_name(cutoff)
        if period not in (*DEV_PERIODS, "2025H2", "2026H1"):
            continue
        inside = any(a <= outcome_day <= b for a, b in windows.get(obj, []))
        rows.append({"d_object_key": obj, "period": period, "in_posthoc_window": inside})
    result: dict[str, Any] = {}
    for period in (*DEV_PERIODS, "2025H2", "2026H1"):
        period_rows = [r for r in rows if r["period"] == period]
        group = [r["d_object_key"] for r in period_rows if not r["in_posthoc_window"]]
        counts = sorted((group.count(obj) for obj in set(group)), reverse=True)
        n = len(group)
        result[period] = {
            "t_raw_positives": len(period_rows),
            "positives_in_window_excluded_from_clean_target": sum(r["in_posthoc_window"] for r in period_rows),
            "positives_outside_window": n,
            "objects_with_positive": len(counts),
            "top1_object_share": counts[0] / n if n else None,
            "top3_object_share": sum(counts[:3]) / n if n else None,
        }
    dev_objects = [r["d_object_key"] for r in rows if r["period"] in DEV_PERIODS and not r["in_posthoc_window"]]
    dev_counts = sorted((dev_objects.count(obj) for obj in set(dev_objects)), reverse=True)
    total = len(dev_objects)
    top1 = dev_counts[0] / total if total else None
    gate = {
        "dev_positives": total,
        "dev_top1_object_share": top1,
        "each_dev_at_least_10": all(result[p]["positives_outside_window"] >= 10 for p in DEV_PERIODS),
        "sum_at_least_60": total >= 60,
        "top1_at_most_50pct": top1 is not None and top1 <= 0.5,
    }
    gate["proceed_to_stage20"] = bool(gate["each_dev_at_least_10"] and gate["sum_at_least_60"]
                                      and gate["top1_at_most_50pct"])
    gate["decision"] = "eligible_for_stage20_spec" if gate["proceed_to_stage20"] else "insufficient_labels_keep_v3"
    return {"periods": result, "gate_19_to_20": gate, "sanity_vs_17": sanity_vs_17(result, cfg)}


def sanity_vs_17(periods: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Compare window assignment with audit 17 v2; a large drift means the windows are built differently."""
    out: dict[str, Any] = {"tolerance": SANITY_TOLERANCE, "comparable": cfg["mode"] == "FULL", "periods": {}}
    for period, ref in REFERENCE_17.items():
        got = {"in_window": periods[period]["positives_in_window_excluded_from_clean_target"],
               "outside_window": periods[period]["positives_outside_window"]}
        rel = {k: (abs(got[k] - v) / v if v else None) for k, v in ref.items()}
        out["periods"][period] = {"stage19": got, "audit17": ref, "relative_diff": rel,
                                  "within_tolerance": all(r is not None and r <= SANITY_TOLERANCE for r in rel.values())}
    out["all_within_tolerance"] = all(p["within_tolerance"] for p in out["periods"].values())
    return out


def _safe_result_text(result: dict[str, Any]) -> str:
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    forbidden = ("d_channel_key", "d_object_key", "ид_канала", "ид_объект")
    if any(key in text for key in forbidden):
        raise AssertionError("identifier field leaked into aggregate output")
    return text


def summary_markdown(result: dict[str, Any]) -> str:
    gate = result["power"]["gate_19_to_20"]
    lines = ["# Notebook 19 — диагностика газовых пересечений", "",
             "Это диагностика наблюдаемых пересечений 1 % CH4, а не подтверждённых утечек или инцидентов.",
             "Окна обозначают **подозреваемое обслуживание**; связь с поверкой не доказана.", "",
             f"Статус: **{result['status']}**. Строгих пересечений: **{result['crossings_total']:,}**; "
             f"ограниченных пауз всех газовых каналов объекта: **{result['silence_runs']:,}**.", "",
             "## Gate 19 → 20", "",
             "| период | T_raw = 1 | внутри окна (исключаются) | вне окна | объектов | top-1 | top-3 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for period, s in result["power"]["periods"].items():
        lines.append(f"| {period} | {s['t_raw_positives']} | {s['positives_in_window_excluded_from_clean_target']} | "
                     f"{s['positives_outside_window']} | {s['objects_with_positive']} | "
                     f"{s['top1_object_share'] if s['top1_object_share'] is not None else '—'} | "
                     f"{s['top3_object_share'] if s['top3_object_share'] is not None else '—'} |")
    sv = result["power"].get("sanity_vs_17")
    if sv:
        lines += ["", "Сверка с аудитом 17 v2 (положительные в окне / вне окна): " + "; ".join(
            f"{p}: {v['stage19']['in_window']} / {v['stage19']['outside_window']} "
            f"(17 v2: {v['audit17']['in_window']} / {v['audit17']['outside_window']})"
            for p, v in sv["periods"].items())
            + (". Расхождение в пределах 10 %." if sv["all_within_tolerance"] else
               ". **ВНИМАНИЕ: расхождение > 10 % — окна построены иначе, чем в 17; решение по gate отложить до разбора.**")
            + ("" if sv["comparable"] else " (SMOKE — не сравнимо.)")]
    lines += ["", f"Решение: **{gate['decision']}** (Σ dev = {gate['dev_positives']}, "
              f"top-1 = {gate['dev_top1_object_share'] if gate['dev_top1_object_share'] is not None else '—'}).", "",
              "Stage 20 не запускается автоматически: даже пройденный gate означает только достаточность для отдельной спецификации.", "",
              "## Строгий отпечаток (зафиксирован только на ≤ 2024, внутри окон)", "",
              "```json", json.dumps(result["fingerprint_pre2025"], ensure_ascii=False, indent=2), "```", "",
              "Полные агрегатные гистограммы и квартили находятся в `results_19_gas_fingerprint.json`. "
              "T_raw и все исключаемые события сохраняются в агрегатных счётчиках; совпадение с отпечатком не исключает реальный инцидент.", ""]
    return "\n".join(lines)


def run_stage19(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    started = time.time()
    out = Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    stage = Path(cfg["stage_dir"])
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    raw_sources = kag.discover_sources(Path(cfg["input_dir"]))
    if not raw_sources["journals"] or raw_sources["catalogue"] is None:
        raise FileNotFoundError("raw journals or sensor catalogue not found")
    parts, manifest, manifest_path = discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"],
                                                     cfg.get("expected_manifest_prefix"))
    years = cfg["smoke_years"] if cfg["mode"] == "SMOKE" else None
    year_files, stage_audit = kag.stage_journals(pl, raw_sources["journals"], stage, years, log)
    taxonomy = ep.load_taxonomy(Path(cfg["taxonomy_path"]))
    catalogue = pl.read_csv(raw_sources["catalogue"], infer_schema_length=0, encoding="utf8-lossy")
    gas_type = taxonomy["numeric"]["gas_sensor_type"]
    gas_ids = (catalogue.filter(pl.col("тип_датчика") == gas_type)
               .select("ид_канала_данных").drop_nulls().unique().to_series().to_list())
    if not gas_ids:
        raise ValueError("the catalogue contains no gas channels")
    seconds_dir = stage / "gas_seconds"
    seconds_dir.mkdir()
    second_paths: list[Path] = []
    gas_seconds_total = 0
    for path in year_files:
        # Scan the complete journal but collect only gas-channel rows; the full 313M-row archive never enters RAM.
        raw = (pl.scan_parquet(path).select(ep.EVENT_COLUMNS)
               .filter(pl.col("ид_канала_данных").is_in(gas_ids)).collect())
        seconds = gas_seconds_from_raw(pl, raw, catalogue, taxonomy)
        if cfg["mode"] == "SMOKE" and not seconds.is_empty():
            seconds = seconds.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
        del raw
        gc.collect()
        # Sorting by the materialized bucket lets Parquet skip unrelated row groups on every bucket pass.
        seconds = seconds.with_columns(
            (pl.col("d_channel_key").hash(seed=19) % cfg["channel_buckets"])
            .cast(pl.UInt16).alias("_channel_bucket")
        ).sort("_channel_bucket", "d_channel_key", "t")
        seconds_path = seconds_dir / f"{path.stem}_gas_seconds.parquet"
        seconds.write_parquet(seconds_path, compression="zstd", row_group_size=250_000)
        second_paths.append(seconds_path)
        gas_seconds_total += seconds.height
        log(f"{path.name}: gas seconds {seconds.height:,}")
        # The staged raw year is no longer needed; release both disk and memory before the next year.
        path.unlink(missing_ok=True)
        del seconds
        gc.collect()
    crossings, activity = process_seconds_buckets(pl, second_paths, cfg, log)
    crossings = add_same_object_count(pl, crossings)
    runs = bounded_silence_runs_from_activity(pl, activity, cfg["min_silence_days"])
    crossings = add_maintenance_context(pl, crossings, runs, cfg["before_days"], cfg["after_days"])
    crossings = crossings.with_columns(
        pl.col("day").map_elements(period_name, return_dtype=pl.String).alias("period")
    ).filter(pl.col("period").is_not_null())

    fingerprint = fit_fingerprint(crossings)
    partial = {
        "status": "fingerprint_locked", "analysis_version": "19-v1",
        "panel": {"manifest_sha256": _sha256(manifest_path), "rows": int(manifest["rows"]),
                  "parts": len(parts), "schema_version": manifest["schema_version"]},
        "fingerprint_pre2025": fingerprint,
    }
    result_path = out / "results_19_gas_fingerprint.json"
    result_path.write_text(_safe_result_text(partial) + "\n", encoding="utf-8")
    # Apply exactly the parameters already written above; late periods cannot refit them.
    locked = json.loads(result_path.read_text(encoding="utf-8"))["fingerprint_pre2025"]
    crossings = apply_fingerprint(pl, crossings, locked)
    power = panel_power(pl, parts, runs, cfg)
    result = {
        "status": "completed_smoke_non_comparable" if cfg["mode"] == "SMOKE" else "completed",
        "analysis_version": "19-v1", "mode": cfg["mode"],
        "runtime_s": round(time.time() - started, 1),
        "panel": partial["panel"],
        "raw": {"journal_years": sorted(int(y) for y in stage_audit.get("years", {})),
                "gas_seconds": gas_seconds_total},
        "crossings_total": crossings.height, "silence_runs": runs.height,
        "fingerprint_pre2025": locked,
        "crossing_strata": aggregate_crossings(pl, crossings),
        "power": power,
        "claims": {"event": "observable crossing of 1% CH4", "window": "suspected maintenance, not confirmed calibration",
                   "incident_probability": False, "training_performed": False},
    }
    result_path.write_text(_safe_result_text(result) + "\n", encoding="utf-8")
    (out / "summary_19_gas_fingerprint_ru.md").write_text(summary_markdown(result), encoding="utf-8")
    if not cfg["keep_stage"]:
        shutil.rmtree(stage, ignore_errors=True)
    return result
