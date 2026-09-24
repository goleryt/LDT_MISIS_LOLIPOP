"""Wires the experimental cold-start model into backend API responses.

Scope and limits (read before trusting the numbers):

- The bundle scores a *proxy* target (`failure_state_presence_24_48h_proxy_v1`),
  not a confirmed physical failure or unauthorized-access event.
- `тревожное` in the source journal is not a validated failure label; this
  service does not treat it as one.
- There is no validated "failure state" definition in this database, so
  `d_current_failure_state`, `d_days_since_failure_state_event` and
  `d_failure_state_event_count_24h` cannot be computed here. They are sent
  as `False` / `None`, which the model tolerates (LightGBM missing-value
  handling), but this means the recurrence signal the model was trained
  with is unavailable at serving time for this dataset. Treat scores as
  experimental/shadow, exactly as `decision_status` says.
- "24h" windows are approximated as calendar-day buckets of `d_event_time`
  ending on each channel's own most recent event date, not a rolling
  wall-clock 24h window synced to a shared "today".
"""

from __future__ import annotations

import statistics
import logging
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import EventsJournal

logger = logging.getLogger(__name__)

BUNDLE_PATH = Path(__file__).parent / "experimental_cold_start_model.joblib"
MAX_EVENTS_PER_CHANNEL = 500


@lru_cache
def get_bundle():
    # Импорт ленивый: ML-зависимости (requirements-ml.txt) и сам файл
    # модели необязательны — в Git модели не хранятся (см. models/README.md).
    from app.ml import predictor

    return predictor.load_bundle(BUNDLE_PATH)


@lru_cache
def model_available() -> bool:
    try:
        get_bundle()
    except (ImportError, OSError) as exc:
        logger.warning(
            "ML model unavailable, risk scores disabled: %s",
            exc,
        )
        return False

    return True


def _fetch_recent_events(
    session: Session,
    channel_ids: list[int],
) -> dict[int, list[dict]]:
    if not channel_ids:
        return {}

    ranked = (
        select(
            EventsJournal.ид_канала_данных.label("channel_id"),
            EventsJournal.d_event_time.label("event_time"),
            EventsJournal.d_alarm.label("alarm"),
            EventsJournal.d_value_numeric.label("value_numeric"),
            EventsJournal.d_value_state.label("value_state"),
            func.row_number()
            .over(
                partition_by=EventsJournal.ид_канала_данных,
                order_by=EventsJournal.d_event_time.desc().nullslast(),
            )
            .label("rn"),
        )
        .where(EventsJournal.ид_канала_данных.in_(channel_ids))
        .cte("ranked_recent_events_for_scoring")
    )

    statement = (
        select(
            ranked.c.channel_id,
            ranked.c.event_time,
            ranked.c.alarm,
            ranked.c.value_numeric,
            ranked.c.value_state,
        )
        .where(ranked.c.rn <= MAX_EVENTS_PER_CHANNEL)
        .order_by(ranked.c.channel_id, ranked.c.event_time.desc())
    )

    by_channel: dict[int, list[dict]] = {}
    for row in session.execute(statement).mappings().all():
        if row["event_time"] is None:
            continue
        by_channel.setdefault(int(row["channel_id"]), []).append(dict(row))

    return by_channel


def _build_record(
    channel_id: int,
    sensor_type: str | None,
    system_type: str | None,
    events: list[dict],
) -> dict | None:
    if not events:
        return None

    as_of_date: date = events[0]["event_time"].date()
    distinct_dates = sorted({e["event_time"].date() for e in events}, reverse=True)
    previous_date = distinct_dates[1] if len(distinct_dates) > 1 else None

    day_events = [e for e in events if e["event_time"].date() == as_of_date]
    previous_day_events = (
        [e for e in events if e["event_time"].date() == previous_date]
        if previous_date
        else []
    )

    numeric_values_all = [e["value_numeric"] for e in events if e["value_numeric"] is not None]
    numeric_values_day = [e["value_numeric"] for e in day_events if e["value_numeric"] is not None]
    state_values_day = {e["value_state"] for e in day_events if e["value_state"] is not None}

    alarm_count_24h = sum(1 for e in day_events if e["alarm"] is True)
    alarm_count_previous_24h = (
        sum(1 for e in previous_day_events if e["alarm"] is True) if previous_date else None
    )

    return {
        "as_of_date": as_of_date.isoformat(),
        "d_alarm_count_24h": alarm_count_24h,
        "d_alarm_count_previous_24h": alarm_count_previous_24h,
        "d_alarm_share_24h": (
            alarm_count_24h / len(day_events) if day_events else None
        ),
        "d_alarm_share_previous_24h": (
            alarm_count_previous_24h / len(previous_day_events)
            if previous_date and previous_day_events
            else None
        ),
        "d_catalogue_match": 1,
        "d_current_failure_state": False,
        "d_days_since_failure_state_event": None,
        "d_event_count_24h": len(day_events),
        "d_event_count_previous_24h": len(previous_day_events) if previous_date else None,
        "d_failure_state_event_count_24h": None,
        "d_gap_days_since_previous": (
            (as_of_date - previous_date).days if previous_date else None
        ),
        "d_month": as_of_date.month,
        "d_observed_days_so_far": len(distinct_dates),
        "d_state_n_unique_24h": len(state_values_day) if state_values_day else None,
        "d_value_numeric_last": numeric_values_all[0] if numeric_values_all else None,
        "d_value_numeric_max_24h": max(numeric_values_day) if numeric_values_day else None,
        "d_value_numeric_mean_24h": (
            statistics.fmean(numeric_values_day) if numeric_values_day else None
        ),
        "d_value_numeric_min_24h": min(numeric_values_day) if numeric_values_day else None,
        "d_value_numeric_previous": (
            numeric_values_all[1] if len(numeric_values_all) > 1 else None
        ),
        "d_value_numeric_std_24h": (
            statistics.stdev(numeric_values_day) if len(numeric_values_day) > 1 else None
        ),
        "d_weekday": as_of_date.weekday(),
        "тип_датчика": sensor_type,
        "тип_инж_системы": system_type,
        "channel_id": channel_id,
    }


def score_channels(
    session: Session,
    channels: list[tuple[int, str | None, str | None]],
) -> dict[int, dict | None]:
    """
    channels: list of (channel_id, тип_датчика, тип_инж_системы).

    Returns channel_id -> risk dict, or None when there is no data to score
    (channel has no events yet).
    """
    if not model_available():
        return {channel_id: None for channel_id, _, _ in channels}

    channel_ids = [channel_id for channel_id, _, _ in channels]
    events_by_channel = _fetch_recent_events(session, channel_ids)

    records = []
    order: list[int] = []
    for channel_id, sensor_type, system_type in channels:
        record = _build_record(
            channel_id,
            sensor_type,
            system_type,
            events_by_channel.get(channel_id, []),
        )
        if record is not None:
            records.append(record)
            order.append(channel_id)

    if not records:
        return {channel_id: None for channel_id, _, _ in channels}

    from app.ml import predictor

    predictions = predictor.predict(records, get_bundle())

    result: dict[int, dict | None] = {channel_id: None for channel_id, _, _ in channels}
    for channel_id, prediction in zip(order, predictions):
        result[channel_id] = {
            "risk_score": prediction["score"],
            "risk_score_kind": prediction["score_kind"],
            "risk_window_start": prediction["window_start"],
            "risk_window_end_exclusive": prediction["window_end_exclusive"],
            "risk_route": prediction["route"],
            "risk_is_alert_candidate": prediction["is_alert_candidate"],
            "risk_eligibility_status": prediction["eligibility_status"],
            "risk_decision_status": prediction["decision_status"],
            "risk_model_version": prediction["model_version"],
        }

    return result
