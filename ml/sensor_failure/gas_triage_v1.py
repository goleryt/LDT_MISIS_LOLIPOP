"""Research-only, causal-at-cutoff triage of observed CH4 crossings (spec 013+015).

The output of this module is an audit of hypotheses, not incident or maintenance
ground truth. No bundle, active model, or backend response is changed here.
"""

from __future__ import annotations

import bisect
import gc
import json
import os
import random
import shutil
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

import gas_fingerprint_v4 as gf

LIVE_MINUTES = 15
FAST_MINUTES = 5
RECENT_MINUTES = 10
PEAK_LIMIT = 2.6
NEIGHBOR_HOURS = 6
CONTEXT_DAYS = 90
ATTENTION = {"needs_attention", "short_isolated", "pending"}
PERIODS = ("le2022", "2023H1", "2023H2", "2024H1", "2024H2", "2025H1", "2025H2", "2026H1")
# Decision cohort for V1/N1 (spec 013 §7): all periods <= 2024 plus 2025; 2026H1 is an observation only.
COHORT_PERIODS = PERIODS[:-1]
COHORT_BLOCKS = {"le2024": ("le2022", "2023H1", "2023H2", "2024H1", "2024H2"), "2025": ("2025H1", "2025H2")}


def make_config_21(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = gf.make_config_19(mode)
    cfg.update({"stage_dir": os.environ.get("LDT_STAGE_DIR", "/tmp/ldt_gas_triage_21"),
                "keep_stage": False, "analysis_version": "21-v1"})
    cfg.update(overrides or {})
    return cfg


def preflight(cfg: dict[str, Any]) -> dict[str, Any]:
    source = gf.preflight_sources(cfg)
    stage_parent = Path(cfg["stage_dir"]).resolve().parent
    stage_parent.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(stage_parent)
    try:
        import psutil
        ram_gib = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except ImportError:
        ram_gib = None
    return {**source, "mode": cfg["mode"], "channel_buckets": cfg["channel_buckets"],
            "free_stage_gib": round(disk.free / (1024 ** 3), 1), "ram_gib": ram_gib,
            "staging_note": "FULL rereads raw yearly journals and writes temporary gas-second Parquet"}


def _event_shapes_for_bucket(pl: Any, seconds: Any) -> list[dict[str, Any]]:
    """Use Stage 19's strict detector; derive live shape only through t0+15m."""
    crossings = gf.strict_crossing_features(pl, seconds)
    if crossings.is_empty():
        return []
    events_by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in crossings.iter_rows(named=True):
        events_by_channel[event["d_channel_key"]].append(event)
    rows: list[dict[str, Any]] = []
    for group in seconds.partition_by("d_channel_key"):
        channel_events = events_by_channel.get(group["d_channel_key"][0], [])
        if not channel_events:
            continue
        times = group["t"].to_numpy().astype("datetime64[us]").astype(np.int64)
        mx = group["mx"].to_numpy()
        for event in channel_events:
            t0 = event["cross_t"]
            t0_us = np.datetime64(t0, "us").astype(np.int64)
            c_us = t0_us + LIVE_MINUTES * 60_000_000
            lo = int(np.searchsorted(times, t0_us, side="left"))
            hi = int(np.searchsorted(times, c_us, side="right"))
            fast_hi = int(np.searchsorted(times, t0_us + FAST_MINUTES * 60_000_000, side="right"))
            drop_candidates = np.flatnonzero(mx[lo + 1:fast_hi] < 1.0)
            drop_idx = lo + 1 + int(drop_candidates[0]) if len(drop_candidates) else None
            repeat = bool(drop_idx is not None and np.any(mx[drop_idx + 1:hi] >= 1.0))
            ended_fast = drop_idx is not None and not repeat
            peak = float(np.nanmax(mx[lo:hi]))
            valid = np.flatnonzero(np.isfinite(mx[lo:hi]))
            last_idx = lo + int(valid[-1])
            age_minutes = (c_us - int(times[last_idx])) / 60_000_000
            state = ("unknown" if drop_idx is None or repeat or not np.isfinite(peak) else
                     "observed_below" if age_minutes <= RECENT_MINUTES else "inferred_below")
            rows.append({"d_channel_key": event["d_channel_key"], "d_object_key": event["d_object_key"],
                         "cross_t": t0, "day": event["day"], "decision_t": t0 + timedelta(minutes=LIVE_MINUTES),
                         "ended_fast": ended_fast, "repeat_by_c": repeat, "peak_by_c": peak,
                         "last_reading_age_min": float(age_minutes), "state_at_c": state,
                         "drop_t": None if drop_idx is None else group["t"][drop_idx]})
    return rows


def _unique_other_count(events: list[dict[str, Any]], left: datetime, right: datetime,
                        channel: str) -> int:
    return len({e["d_channel_key"] for e in events
                if left <= e["cross_t"] <= right and e["d_channel_key"] != channel})


def _context(event: dict[str, Any], runs_by_object: dict[str, list[dict[str, Any]]],
             first_day: dict[str, date]) -> tuple[str, bool]:
    day = event["day"]
    obj = event["d_object_key"]
    first = first_day.get(obj)
    if first is None or (day - first).days < CONTEXT_DAYS:
        return "unknown", False
    runs = runs_by_object.get(obj, [])
    recent = any(1 <= (day - r["end"]).days <= 21 for r in runs)
    in_posthoc = any(r["start"] - timedelta(days=3) <= day <= r["end"] + timedelta(days=21)
                     for r in runs)
    return ("true" if recent else "false"), in_posthoc


def label_events(events: list[dict[str, Any]], activity: Any, runs: Any,
                 archive_end: datetime) -> list[dict[str, Any]]:
    """Label compact crossing rows; all neighbor counts use the full object timeline."""
    by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_object[event["d_object_key"]].append(event)
    for group in by_object.values():
        group.sort(key=lambda e: e["cross_t"])
    runs_by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs.iter_rows(named=True):
        runs_by_object[r["d_object_key"]].append(r)
    first_day: dict[str, date] = {}
    for obj, day in activity.select("d_object_key", "day").iter_rows():
        first_day[obj] = min(day, first_day.get(obj, day))

    for event in events:
        t0, c, day = event["cross_t"], event["decision_t"], event["day"]
        group = by_object[event["d_object_key"]]
        event["other_ch_by_live_cutoff"] = _unique_other_count(
            group, t0 - timedelta(hours=NEIGHBOR_HOURS), c, event["d_channel_key"])
        event["other_ch_day"] = _unique_other_count(
            group, datetime.combine(day, datetime.min.time()),
            datetime.combine(day + timedelta(days=1), datetime.min.time()) - timedelta(microseconds=1),
            event["d_channel_key"])
        event["after_silence"], event["in_posthoc_window"] = _context(event, runs_by_object, first_day)
        event["period"] = gf.period_name(day)
        event["is_weekend"] = t0.weekday() >= 5
        event["outside_07_19"] = not 7 <= t0.hour < 19
        bad_shape = (not event["ended_fast"] or not np.isfinite(event["peak_by_c"]) or
                     event["peak_by_c"] > PEAK_LIMIT or event["state_at_c"] == "unknown")
        event["shape_ok"] = not bad_shape
        if bad_shape:
            label = "needs_attention"
        elif event["after_silence"] == "true":
            label = "likely_after_maintenance"
        elif event["other_ch_by_live_cutoff"] >= 1:
            label = "likely_bump_test"
        else:
            label = "short_isolated"
        event["triage_live"] = label if c <= archive_end else None
        event["status_at_archive_end"] = "censored_right" if c > archive_end else "decided"
        event["status_at_day_end"] = "pending_at_day_end" if c.date() > day else "decided"
        day_end = datetime.combine(day + timedelta(days=1), datetime.min.time()) - timedelta(microseconds=1)
        event["triage_retro"] = ("censored_right" if day_end > archive_end else
                                 "censored_by_day" if c > day_end else
                                 "needs_attention" if bad_shape else
                                 "likely_after_maintenance" if event["after_silence"] == "true" else
                                 "likely_bump_test" if event["other_ch_day"] >= 2 else "short_isolated")
        event["triage_live_strict"] = (None if c > archive_end else
                                       "needs_attention" if label.startswith("likely_") and
                                       event["state_at_c"] != "observed_below" else label)
        event["series_only"] = bool(event["shape_ok"] and event["other_ch_by_live_cutoff"] >= 1)
        event["series_only_strict"] = bool(event["series_only"] and event["state_at_c"] == "observed_below")
        event["reason_codes"] = {"ended_fast": event["ended_fast"], "repeat_by_c": event["repeat_by_c"],
                                 "peak_by_c": event["peak_by_c"],
                                 "other_ch_by_live_cutoff": event["other_ch_by_live_cutoff"],
                                 "after_silence": event["after_silence"],
                                 "last_reading_age_min": event["last_reading_age_min"]}
    return events


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    return round(sum(bool(r[field]) for r in rows) / len(rows), 6) if rows else None


def _label_summary(events: list[dict[str, Any]], label_field: str) -> dict[str, Any]:
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_label[e[label_field] or "censored_right"].append(e)
    result = {}
    for label, rows in sorted(by_label.items()):
        object_counts = Counter(e["d_object_key"] for e in rows)
        ranked = sorted(object_counts.values(), reverse=True)
        result[label] = {"n": len(rows), "weekend_share": _rate(rows, "is_weekend"),
                         "outside_07_19_share": _rate(rows, "outside_07_19"),
                         "top1_object_share": round(ranked[0] / len(rows), 6),
                         "top3_object_share": round(sum(ranked[:3]) / len(rows), 6)}
    return result


def _bootstrap_calendar(events: list[dict[str, Any]], label_field: str,
                        repeats: int = 2000) -> dict[str, Any]:
    relevant = [e for e in events if e[label_field] == "likely_bump_test" or e[label_field] in ATTENTION]
    blocks: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for e in relevant:
        iso = e["day"].isocalendar()
        blocks[(e["d_object_key"], iso.year, iso.week)].append(e)
    rng = random.Random(21)
    groups = list(blocks.values())
    diffs: list[float] = []
    for _ in range(repeats):
        chosen = [row for _ in groups for row in groups[rng.randrange(len(groups))]] if groups else []
        bump = [e for e in chosen if e[label_field] == "likely_bump_test"]
        queue = [e for e in chosen if e[label_field] in ATTENTION]
        if bump and queue:
            diffs.append(sum(e["is_weekend"] for e in queue) / len(queue) -
                         sum(e["is_weekend"] for e in bump) / len(bump))
    return {"repeats": repeats, "valid_repeats": len(diffs),
            "weekend_queue_minus_bump_ci95": ([round(float(np.quantile(diffs, .025)), 6),
                                                 round(float(np.quantile(diffs, .975)), 6)] if diffs else None)}


def _n1_control(events: list[dict[str, Any]], archive_start: datetime,
                archive_end: datetime, strict: bool = False) -> dict[str, Any]:
    cohort = [e for e in events if e["period"] in COHORT_PERIODS]
    if not cohort:
        return {"n": 0, "passed": False, "reason": "empty_cohort"}
    # The observed and shifted fractions use exactly the same event cohort.
    by_obj_observed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in cohort:
        by_obj_observed[e["d_object_key"]].append(e)
    true_share = sum((e["shape_ok"] and (not strict or e["state_at_c"] == "observed_below") and
                      _unique_other_count(by_obj_observed[e["d_object_key"]],
                                          e["cross_t"] - timedelta(hours=NEIGHBOR_HOURS),
                                          e["decision_t"], e["d_channel_key"]) >= 1)
                     for e in cohort) / len(cohort)
    rng = random.Random(21)
    channels = sorted({e["d_channel_key"] for e in cohort})
    fractions: list[float] = []
    unshifted: list[int] = []
    right = archive_end - timedelta(days=1)
    for _ in range(20):
        offsets = {ch: rng.choice((-2, -1, 1, 2)) * timedelta(weeks=1) for ch in channels}
        by_channel = defaultdict(list)
        for e in cohort:
            by_channel[e["d_channel_key"]].append(e["cross_t"])
        for ch, original_times in by_channel.items():
            offset = offsets[ch]
            if any(not archive_start <= t + offset <= right for t in original_times):
                offsets[ch] = -offset
        shifted: list[dict[str, Any]] = []
        stationary = 0
        for e in cohort:
            t = e["cross_t"] + offsets[e["d_channel_key"]]
            if not archive_start <= t <= right:
                t = e["cross_t"]
                stationary += 1
            shifted.append({"d_object_key": e["d_object_key"], "d_channel_key": e["d_channel_key"],
                            "cross_t": t, "shape_ok": e["shape_ok"], "state_at_c": e["state_at_c"]})
        by_obj: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in shifted:
            by_obj[e["d_object_key"]].append(e)
        n_series = sum(e["shape_ok"] and (not strict or e["state_at_c"] == "observed_below") and
            _unique_other_count(
            by_obj[e["d_object_key"]], e["cross_t"] - timedelta(hours=NEIGHBOR_HOURS),
            e["cross_t"] + timedelta(minutes=LIVE_MINUTES), e["d_channel_key"]) >= 1
            for e in shifted)
        fractions.append(n_series / len(cohort))
        unshifted.append(stationary)
    return {"n": len(cohort), "seed": 21, "permutations": 20, "strict_observed_only": strict,
            "observed_share": round(true_share, 6),
            "permuted_median_share": round(float(np.median(fractions)), 6),
            "permuted_max_share": round(max(fractions), 6),
            "n1_unshifted_max": max(unshifted),
            "passed": true_share > max(fractions)}


def _v1_calendar(cohort: list[dict[str, Any]], label_field: str) -> dict[str, Any]:
    bump = [e for e in cohort if e[label_field] == "likely_bump_test"]
    attention = [e for e in cohort if e[label_field] in ATTENTION]
    bump_weekend, queue_weekend = _rate(bump, "is_weekend"), _rate(attention, "is_weekend")
    passed = bool(bump_weekend is not None and queue_weekend is not None and
                  bump_weekend <= .05 and bump_weekend * 2 <= queue_weekend)
    objects = {e["d_object_key"] for e in cohort}
    loo_passes = []
    for obj in objects:
        rows = [e for e in cohort if e["d_object_key"] != obj]
        b = [e for e in rows if e[label_field] == "likely_bump_test"]
        q = [e for e in rows if e[label_field] in ATTENTION]
        wb, wq = _rate(b, "is_weekend"), _rate(q, "is_weekend")
        loo_passes.append(bool(wb is not None and wq is not None and wb <= .05 and 2 * wb <= wq))
    blocks = {}
    for block, names in COHORT_BLOCKS.items():
        rows = [e for e in cohort if e["period"] in names]
        b = [e for e in rows if e[label_field] == "likely_bump_test"]
        q = [e for e in rows if e[label_field] in ATTENTION]
        blocks[block] = {"bump_n": len(b), "attention_n": len(q),
                         "bump_weekend_share": _rate(b, "is_weekend"),
                         "attention_weekend_share": _rate(q, "is_weekend")}
    return {"cohort": "le2022-2025H2", "bump_n": len(bump), "attention_n": len(attention),
            "degenerate_zero_weekend_queue": bool(queue_weekend == 0),
            "by_block_diagnostic": blocks,
            "bump_weekend_share": bump_weekend, "attention_weekend_share": queue_weekend,
            "bump_outside_07_19_share": _rate(bump, "outside_07_19"),
            "attention_outside_07_19_share": _rate(attention, "outside_07_19"),
            "bootstrap": _bootstrap_calendar(cohort, label_field),
            "leave_one_object_out": {"objects": len(objects), "passes": sum(loo_passes)},
            "passed": passed}


def _daily_burden(events: list[dict[str, Any]], period: str, archive_start: datetime,
                  archive_end: datetime) -> dict[str, Any]:
    period_def = next((start, end) for name, start, end in gf.PERIODS if name == period)
    start, end = period_def
    if start is None:
        # The archive's early-years start is an observed bound, not an invented 2019-01-01.
        start = min((e["day"] for e in events), default=end)
    start = max(start, archive_start.date())
    end = min(end, archive_end.date() + timedelta(days=1))
    days = max(1, (end - start).days)
    total = Counter(e["day"] for e in events)
    queue = Counter(e["day"] for e in events if
                    e["status_at_day_end"] == "pending_at_day_end" or
                    e["status_at_archive_end"] == "censored_right" or
                    e["triage_live"] in ATTENTION)
    arr_all = [total[start + timedelta(days=i)] for i in range(days)]
    arr_queue = [queue[start + timedelta(days=i)] for i in range(days)]
    return {"calendar_days": days, "all_mean_per_day": round(float(np.mean(arr_all)), 3),
            "all_p95_per_day": round(float(np.quantile(arr_all, .95)), 3),
            "attention_mean_per_day": round(float(np.mean(arr_queue)), 3),
            "attention_p95_per_day": round(float(np.quantile(arr_queue, .95)), 3)}


def aggregate_21(events: list[dict[str, Any]], runs_count: int, seconds_count: int,
                 archive_start: datetime, archive_end: datetime, cfg: dict[str, Any],
                 panel: dict[str, Any]) -> dict[str, Any]:
    by_period = {name: [e for e in events if e["period"] == name]
                 for name, _, _ in gf.PERIODS}
    cohort = [e for e in events if e["period"] in COHORT_PERIODS]
    v1 = _v1_calendar(cohort, "triage_live")
    v1_strict = _v1_calendar(cohort, "triage_live_strict")
    n1 = _n1_control(events, archive_start, archive_end)
    n1_strict = _n1_control(events, archive_start, archive_end, strict=True)
    bins = {"le1": 0, "gt1_le5": 0, "gt5_le10": 0,
            "gt10_le30": 0, "gt30_le120": 0, "gt120": 0}
    likely = [e for e in events if (e["triage_live"] or "").startswith("likely_")]
    for e in likely:
        age = e["last_reading_age_min"]
        key = ("le1" if age <= 1 else "gt1_le5" if age <= 5 else "gt5_le10" if age <= 10 else
               "gt10_le30" if age <= 30 else "gt30_le120" if age <= 120 else "gt120")
        bins[key] += 1
    periods = {}
    for name, rows in by_period.items():
        if not rows:
            continue
        in_window = [e for e in rows if e["in_posthoc_window"]]
        periods[name] = {"n": len(rows), "labels_live": _label_summary(rows, "triage_live"),
                         "labels_live_strict": _label_summary(rows, "triage_live_strict"),
                         "labels_retro": _label_summary(rows, "triage_retro"),
                         "pending_at_day_end": sum(e["status_at_day_end"] == "pending_at_day_end" for e in rows),
                         "censored_right": sum(e["status_at_archive_end"] == "censored_right" for e in rows),
                         "unresolved_or_incomplete": sum(not e["ended_fast"] for e in rows),
                         "context_unknown": sum(e["after_silence"] == "unknown" for e in rows),
                         "observed_below": sum(e["state_at_c"] == "observed_below" for e in rows),
                         "inferred_below": sum(e["state_at_c"] == "inferred_below" for e in rows),
                         "retro_disagreements": sum(e["triage_retro"] not in ("censored_by_day", "censored_right") and
                                                     e["triage_retro"] != e["triage_live"] for e in rows),
                         "v2_in_posthoc_window": {"n": len(in_window),
                             "hypothesis_share": round(sum((e["triage_live"] or "").startswith("likely_")
                                                        for e in in_window) / len(in_window), 6) if in_window else None,
                             "series_only_share": _rate(in_window, "series_only")},
                         "v6_daily_burden": _daily_burden(rows, name, archive_start, archive_end)}
    prior = [e for e in cohort if e["triage_live"] is not None]
    late = [e for e in by_period["2026H1"] if e["triage_live"] is not None]
    def attention_share(rows: list[dict[str, Any]]) -> float | None:
        return round(sum(e["triage_live"] in ATTENTION for e in rows) / len(rows), 6) if rows else None
    return {"status": "completed" if cfg["mode"] == "FULL" else "completed_smoke_non_comparable",
            "analysis_version": cfg["analysis_version"], "mode": cfg["mode"],
            "panel": panel, "gas_seconds": seconds_count,
            "crossings_total": len(events), "silence_runs": runs_count,
            "v1_calendar": v1, "v1_calendar_strict": v1_strict,
            "n1_synchrony_control": n1, "n1_synchrony_control_strict": n1_strict,
            "likely_last_reading_age_bins": bins,
            "v3_2026h1_observation": {"prior_2023_2025_attention_share": attention_share(prior),
                                      "2026h1_attention_share": attention_share(late),
                                      "exploratory_only": True},
            "periods": periods,
            "backend_gate": "research_only" if v1["passed"] and n1["passed"] else "stop_v1_or_n1",
            "claims": {"incident_labels": False, "verified_calibration": False,
                       "active_bundle_changed": False, "backend_deployed": False}}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f} %"


def summary_markdown(result: dict[str, Any]) -> str:
    lines = ["# Ноутбук 21 — исследовательский триаж газовых тревог", "",
             "Метки совместимы с гипотезой проверки датчиков, но не подтверждают поверку или инцидент.",
             "Тревоги не скрываются; решение о backend принимается отдельно.", "",
             f"Статус: **{result['status']}**; строгих пересечений: **{result['crossings_total']:,}**; "
             f"ограниченных пауз: **{result['silence_runs']:,}**.", "",
             "## Предзаданные проверки", "",
             f"- V1 календарь: **{'прошёл' if result['v1_calendar']['passed'] else 'не прошёл'}**; "
             f"выходные у likely_bump_test {_pct(result['v1_calendar']['bump_weekend_share'])}, "
             f"у очереди внимания {_pct(result['v1_calendar']['attention_weekend_share'])}; "
             f"CI95 разницы {result['v1_calendar']['bootstrap']['weekend_queue_minus_bump_ci95']}. "
             f"Строгий вариант: {'прошёл' if result['v1_calendar_strict']['passed'] else 'не прошёл'}.",
             f"- N1 синхронизация: **{'прошёл' if result['n1_synchrony_control']['passed'] else 'не прошёл'}**; "
             f"реальная доля серий {_pct(result['n1_synchrony_control'].get('observed_share'))}, "
             f"перестановки: медиана {_pct(result['n1_synchrony_control'].get('permuted_median_share'))}, "
             f"максимум {_pct(result['n1_synchrony_control'].get('permuted_max_share'))}. "
             f"Строгий вариант: {'прошёл' if result['n1_synchrony_control_strict']['passed'] else 'не прошёл'}.",
             f"- Stop-rule: **{result['backend_gate']}**. Прохождение не доказывает истинную причину тревог.", "",
             "## Метки по периодам", "",
             "| Период | Событий | Needs attention | Short isolated | After maintenance | Bump test | Pending D |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, p in result["periods"].items():
        labels = p["labels_live"]
        count = lambda label: labels.get(label, {}).get("n", 0)
        lines.append(f"| {name} | {p['n']} | {count('needs_attention')} | {count('short_isolated')} | "
                     f"{count('likely_after_maintenance')} | {count('likely_bump_test')} | {p['pending_at_day_end']} |")
    lines.extend(["", "Полные агрегаты V1–V6, строгий вариант, цензура и нагрузка — в JSON. "
                  "Идентификаторы объектов и каналов не публикуются."])
    return "\n".join(lines) + "\n"


def run_stage21(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    started = time.time()
    out = Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    parts, manifest, manifest_path = gf.discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"],
                                                       cfg.get("expected_manifest_prefix"))
    del parts
    paths, audit, _, seconds_count = _stage_seconds(pl, cfg, log)
    events, activity, archive_start, archive_end = _process_buckets(pl, paths, cfg, log)
    runs = gf.bounded_silence_runs_from_activity(pl, activity, cfg["min_silence_days"])
    events = label_events(events, activity, runs, archive_end)
    events = [e for e in events if e["period"] is not None]
    if cfg["mode"] == "FULL" and (len(events), runs.height) != (7_222, 93):
        by_period = Counter(e["period"] for e in events)
        (out / "results_21_identity_mismatch.json").write_text(gf._safe_result_text(
            {"status": "stopped_identity_mismatch", "crossings_total": len(events), "silence_runs": runs.height,
             "expected": {"crossings_total": 7_222, "silence_runs": 93}, "crossings_by_period": dict(by_period),
             "gas_seconds": seconds_count}) + "\n", encoding="utf-8")
        raise ValueError(f"Stage 19 identity mismatch: crossings={len(events)}, runs={runs.height}; expected 7222/93")
    result = aggregate_21(events, runs.height, seconds_count, archive_start, archive_end, cfg,
                          {"manifest_sha256": gf._sha256(manifest_path), "rows": int(manifest["rows"]),
                           "parts": len(manifest["parts"]), "schema_version": manifest["schema_version"],
                           "journal_years": sorted(int(y) for y in audit.get("years", {}))})
    result["runtime_s"] = round(time.time() - started, 1)
    (out / "results_21_gas_triage.json").write_text(gf._safe_result_text(result) + "\n", encoding="utf-8")
    (out / "summary_21_gas_triage_ru.md").write_text(summary_markdown(result), encoding="utf-8")
    if not cfg["keep_stage"]:
        shutil.rmtree(Path(cfg["stage_dir"]), ignore_errors=True)
    return result


def _stage_seconds(pl: Any, cfg: dict[str, Any], log: Any) -> tuple[list[Path], dict[str, Any], Any, int]:
    stage = Path(cfg["stage_dir"])
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    raw_sources = gf.kag.discover_sources(Path(cfg["input_dir"]))
    if not raw_sources["journals"] or raw_sources["catalogue"] is None:
        raise FileNotFoundError("raw journals or catalogue not found")
    years = cfg["smoke_years"] if cfg["mode"] == "SMOKE" else None
    year_files, audit = gf.kag.stage_journals(pl, raw_sources["journals"], stage, years, log)
    taxonomy = gf.ep.load_taxonomy(Path(cfg["taxonomy_path"]))
    catalogue = pl.read_csv(raw_sources["catalogue"], infer_schema_length=0, encoding="utf8-lossy")
    gas_type = taxonomy["numeric"]["gas_sensor_type"]
    gas_ids = (catalogue.filter(pl.col("тип_датчика") == gas_type)
               .select("ид_канала_данных").drop_nulls().unique().to_series().to_list())
    if not gas_ids:
        raise ValueError("the catalogue contains no gas channels")
    seconds_dir = stage / "gas_seconds"
    seconds_dir.mkdir()
    paths: list[Path] = []
    total = 0
    for path in year_files:
        raw = (pl.scan_parquet(path).select(gf.ep.EVENT_COLUMNS)
               .filter(pl.col("ид_канала_данных").is_in(gas_ids)).collect())
        sec = gf.gas_seconds_from_raw(pl, raw, catalogue, taxonomy)
        if cfg["mode"] == "SMOKE" and not sec.is_empty():
            sec = sec.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
        del raw
        gc.collect()
        sec = sec.with_columns((pl.col("d_channel_key").hash(seed=19) % cfg["channel_buckets"])
                               .cast(pl.UInt16).alias("_channel_bucket"))
        sec = sec.sort("_channel_bucket", "d_channel_key", "t")
        out = seconds_dir / f"{path.stem}_gas_seconds.parquet"
        sec.write_parquet(out, compression="zstd", row_group_size=250_000)
        paths.append(out)
        total += sec.height
        log(f"{path.name}: gas seconds {sec.height:,}")
        path.unlink(missing_ok=True)
        del sec
        gc.collect()
    return paths, audit, catalogue, total


def _process_buckets(pl: Any, paths: list[Path], cfg: dict[str, Any], log: Any
                     ) -> tuple[list[dict[str, Any]], Any, datetime, datetime]:
    scans = [pl.scan_parquet(path) for path in paths]
    events: list[dict[str, Any]] = []
    activity_frames = []
    archive_end: datetime | None = None
    archive_start: datetime | None = None
    for bucket in range(int(cfg["channel_buckets"])):
        sec = (pl.concat(scans, how="vertical_relaxed")
               .filter(pl.col("_channel_bucket") == bucket).collect()
               .sort("d_channel_key", "t"))
        if sec.is_empty():
            continue
        events.extend(_event_shapes_for_bucket(pl, sec))
        activity_frames.append(sec.select("d_object_key", pl.col("t").dt.date().alias("day")).unique())
        last = sec["t"].max()
        first = sec["t"].min()
        archive_end = max(last, archive_end) if archive_end is not None else last
        archive_start = min(first, archive_start) if archive_start is not None else first
        log(f"channel bucket {bucket + 1}/{cfg['channel_buckets']}: {sec.height:,} gas seconds")
        del sec
        gc.collect()
    activity = (pl.concat(activity_frames, how="vertical_relaxed").unique() if activity_frames else
                pl.DataFrame(schema={"d_object_key": pl.String, "day": pl.Date}))
    if archive_end is None:
        raise ValueError("no gas seconds in staged journals")
    assert archive_start is not None
    return events, activity, archive_start, archive_end
