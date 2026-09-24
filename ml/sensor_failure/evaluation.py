"""User-visible alert episode construction and evaluation.

Internal scores may be recalculated frequently. These helpers count only new
dispatcher-visible alerts after a deterministic daily budget and cooldown.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


def build_alert_episodes(
    frame: Any,
    probability: Iterable[float],
    *,
    threshold: float = 0.0,
    budget_per_day: int = 50,
    cooldown_hours: int = 72,
) -> pd.DataFrame:
    """Return deterministic, budgeted, cooldown-deduplicated alert episodes."""
    if budget_per_day <= 0:
        raise ValueError("budget_per_day must be positive")
    if cooldown_hours < 0:
        raise ValueError("cooldown_hours must be non-negative")

    columns = [
        "ид_канала_данных",
        "d_cutoff_date",
        "d_target_start_date",
        "d_target_end_date_exclusive",
    ]
    if hasattr(frame, "select"):
        data = pd.DataFrame(frame.select(columns).to_dict(as_series=False))
    else:
        data = pd.DataFrame(frame)[columns].copy()
    scores = np.asarray(list(probability), dtype=float)
    if len(scores) != len(data):
        raise ValueError("probability length must match frame rows")
    data["probability"] = scores
    data = data[np.isfinite(scores) & (scores >= threshold)].copy()
    if data.empty:
        return data.assign(d_alert_time=pd.Series(dtype="datetime64[ns]"))

    data["d_cutoff_date"] = pd.to_datetime(data["d_cutoff_date"])
    data["d_alert_time"] = data["d_cutoff_date"] + pd.to_timedelta(1, unit="D")
    data["__channel_sort"] = data["ид_канала_данных"].astype(str)
    data = data.sort_values(
        ["d_cutoff_date", "probability", "__channel_sort"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    data = data.groupby("d_cutoff_date", sort=False).head(budget_per_day)

    keep: list[int] = []
    last_alert: dict[str, pd.Timestamp] = {}
    cooldown = pd.to_timedelta(cooldown_hours, unit="h")
    for index, row in data.sort_values(
        ["d_alert_time", "__channel_sort"], kind="mergesort"
    ).iterrows():
        channel = str(row["ид_канала_данных"])
        timestamp = row["d_alert_time"]
        previous = last_alert.get(channel)
        if previous is not None and timestamp - previous < cooldown:
            continue
        keep.append(index)
        last_alert[channel] = timestamp
    return data.loc[keep].drop(columns="__channel_sort").reset_index(drop=True)


def evaluate_alert_episodes(
    frame: Any,
    probability: Iterable[float],
    *,
    target: str,
    threshold: float = 0.0,
    budget_per_day: int = 50,
    cooldown_hours: int = 72,
    category_column: str = "тип_датчика",
) -> dict[str, Any]:
    """Evaluate one-to-one alert/event matches overall and by category."""
    event_column = {
        "target_failure_state_onset_24h": "d_future_failure_event_date",
        "target_alarm_onset_24h": "d_future_alarm_event_date",
    }.get(target)
    if event_column is None:
        raise ValueError(f"unsupported episode target: {target}")

    base_columns = [
        "ид_канала_данных",
        target,
        event_column,
        category_column,
    ]
    if hasattr(frame, "select"):
        base = pd.DataFrame(frame.select(base_columns).to_dict(as_series=False))
    else:
        base = pd.DataFrame(frame)[base_columns].copy()
    alerts = build_alert_episodes(
        frame,
        probability,
        threshold=threshold,
        budget_per_day=budget_per_day,
        cooldown_hours=cooldown_hours,
    )
    if hasattr(frame, "select"):
        categories = pd.DataFrame(
            frame.select(["ид_канала_данных", category_column]).to_dict(
                as_series=False
            )
        )
    else:
        categories = pd.DataFrame(frame)[
            ["ид_канала_данных", category_column]
        ].copy()
    categories = categories.drop_duplicates("ид_канала_данных", keep="last")
    alerts = alerts.merge(categories, on="ид_канала_данных", how="left")

    events = base.loc[base[target] == 1, [
        "ид_канала_данных",
        event_column,
        category_column,
    ]].dropna(subset=[event_column])
    events[event_column] = pd.to_datetime(events[event_column])
    events = events.drop_duplicates(
        ["ид_канала_данных", event_column], keep="first"
    ).reset_index(drop=True)
    alerts["d_target_start_date"] = pd.to_datetime(alerts["d_target_start_date"])
    alerts["d_target_end_date_exclusive"] = pd.to_datetime(
        alerts["d_target_end_date_exclusive"]
    )

    matched_events: set[int] = set()
    matched_alerts: set[int] = set()
    for alert_index, alert in alerts.sort_values("d_alert_time").iterrows():
        candidates = events[
            (events["ид_канала_данных"] == alert["ид_канала_данных"])
            & (events[event_column] >= alert["d_target_start_date"])
            & (events[event_column] < alert["d_target_end_date_exclusive"])
            & (~events.index.isin(matched_events))
        ]
        if not candidates.empty:
            event_index = int(candidates.sort_values(event_column).index[0])
            matched_events.add(event_index)
            matched_alerts.add(int(alert_index))

    alerts = alerts.assign(d_matched=alerts.index.isin(matched_alerts))
    events = events.assign(d_matched=events.index.isin(matched_events))

    def summarize(alert_mask: pd.Series, event_mask: pd.Series) -> dict[str, float | int]:
        selected_alerts = alerts.loc[alert_mask]
        selected_events = events.loc[event_mask]
        true_alerts = int(selected_alerts["d_matched"].sum())
        matched_event_count = int(selected_events["d_matched"].sum())
        return {
            "alert_episodes": int(len(selected_alerts)),
            "proxy_events": int(len(selected_events)),
            "matched_alerts": true_alerts,
            "precision": true_alerts / max(len(selected_alerts), 1),
            "recall": matched_event_count / max(len(selected_events), 1),
        }

    overall = summarize(
        pd.Series(True, index=alerts.index), pd.Series(True, index=events.index)
    )
    categories_present = sorted(
        set(alerts[category_column].dropna().astype(str))
        | set(events[category_column].dropna().astype(str))
    )
    per_category = {
        category: summarize(
            alerts[category_column].astype(str) == category,
            events[category_column].astype(str) == category,
        )
        for category in categories_present
    }
    return {
        "unit": "user_visible_alert_episode",
        "budget_per_day": budget_per_day,
        "cooldown_hours": cooldown_hours,
        "overall": overall,
        "per_category": per_category,
    }
