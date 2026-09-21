from datetime import date

from sqlalchemy import text

from app.db.session import SessionLocal


BUILD_CHANNEL_DAILY_FEATURES_SQL = """
WITH daily AS (
    SELECT
        "ид_канала_данных" AS channel_id,
        d_event_time::date AS event_date,
        COUNT(*) AS event_count,
        COUNT(*) FILTER (WHERE d_alarm) AS alarm_count,
        COUNT(*) FILTER (
            WHERE d_value_state IN ('Неисправен', 'Обесточен')
        ) AS failure_state_event_count,
        AVG(d_value_numeric) AS value_numeric_mean,
        MIN(d_value_numeric) AS value_numeric_min,
        MAX(d_value_numeric) AS value_numeric_max,
        STDDEV_POP(d_value_numeric) AS value_numeric_std,
        COUNT(DISTINCT d_value_state) AS state_n_unique
    FROM events_journal
    WHERE d_event_time IS NOT NULL
        AND (CAST(:start_date AS date) IS NULL OR d_event_time::date >= :start_date)
        AND (CAST(:end_date AS date) IS NULL OR d_event_time::date <= :end_date)
    GROUP BY "ид_канала_данных", d_event_time::date
),
last_numeric AS (
    SELECT DISTINCT ON ("ид_канала_данных", d_event_time::date)
        "ид_канала_данных" AS channel_id,
        d_event_time::date AS event_date,
        d_value_numeric AS value_numeric_last
    FROM events_journal
    WHERE d_value_numeric IS NOT NULL
    ORDER BY "ид_канала_данных", d_event_time::date, d_event_time DESC
),
last_state AS (
    SELECT DISTINCT ON ("ид_канала_данных", d_event_time::date)
        "ид_канала_данных" AS channel_id,
        d_event_time::date AS event_date,
        d_value_state AS last_state
    FROM events_journal
    WHERE d_value_state IS NOT NULL
    ORDER BY "ид_канала_данных", d_event_time::date, d_event_time DESC
),
enriched AS (
    SELECT
        d.channel_id,
        d.event_date,
        d.event_count,
        d.alarm_count,
        d.failure_state_event_count,
        d.value_numeric_mean,
        d.value_numeric_min,
        d.value_numeric_max,
        d.value_numeric_std,
        d.state_n_unique,
        ln.value_numeric_last,
        COALESCE(ls.last_state IN ('Неисправен', 'Обесточен'), FALSE) AS current_failure_state,
        ROW_NUMBER() OVER (
            PARTITION BY d.channel_id ORDER BY d.event_date
        ) AS observed_days_so_far,
        LAG(d.event_date) OVER (
            PARTITION BY d.channel_id ORDER BY d.event_date
        ) AS previous_event_date,
        LAG(d.event_count) OVER (
            PARTITION BY d.channel_id ORDER BY d.event_date
        ) AS event_count_previous,
        LAG(d.alarm_count) OVER (
            PARTITION BY d.channel_id ORDER BY d.event_date
        ) AS alarm_count_previous,
        LAG(ln.value_numeric_last) OVER (
            PARTITION BY d.channel_id ORDER BY d.event_date
        ) AS value_numeric_previous,
        MAX(d.event_date) FILTER (WHERE d.failure_state_event_count > 0) OVER (
            PARTITION BY d.channel_id ORDER BY d.event_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS last_failure_date_before_today
    FROM daily d
    LEFT JOIN last_numeric ln
        ON ln.channel_id = d.channel_id AND ln.event_date = d.event_date
    LEFT JOIN last_state ls
        ON ls.channel_id = d.channel_id AND ls.event_date = d.event_date
)
INSERT INTO channel_daily_features (
    "ид_канала_данных",
    as_of_date,
    d_observed_days_so_far,
    d_current_failure_state,
    d_event_count_24h,
    d_alarm_count_24h,
    d_alarm_share_24h,
    d_failure_state_event_count_24h,
    d_value_numeric_mean_24h,
    d_value_numeric_min_24h,
    d_value_numeric_max_24h,
    d_value_numeric_std_24h,
    d_value_numeric_last,
    d_state_n_unique_24h,
    d_gap_days_since_previous,
    d_event_count_previous_24h,
    d_alarm_count_previous_24h,
    d_alarm_share_previous_24h,
    d_value_numeric_previous,
    d_days_since_failure_state_event,
    d_weekday,
    d_month,
    d_catalogue_match,
    "тип_инж_системы",
    "тип_датчика"
)
SELECT
    e.channel_id,
    e.event_date,
    e.observed_days_so_far,
    e.current_failure_state,
    e.event_count,
    e.alarm_count,
    CASE WHEN e.event_count > 0 THEN e.alarm_count::float / e.event_count ELSE NULL END,
    e.failure_state_event_count,
    e.value_numeric_mean,
    e.value_numeric_min,
    e.value_numeric_max,
    e.value_numeric_std,
    e.value_numeric_last,
    e.state_n_unique,
    CASE WHEN e.previous_event_date IS NOT NULL
        THEN (e.event_date - e.previous_event_date)
        ELSE NULL END,
    e.event_count_previous,
    e.alarm_count_previous,
    CASE WHEN e.event_count_previous > 0
        THEN e.alarm_count_previous::float / e.event_count_previous
        ELSE NULL END,
    e.value_numeric_previous,
    CASE WHEN e.last_failure_date_before_today IS NOT NULL
        THEN (e.event_date - e.last_failure_date_before_today)
        ELSE NULL END,
    EXTRACT(ISODOW FROM e.event_date)::int,
    EXTRACT(MONTH FROM e.event_date)::int,
    (cc."ид_канала_данных" IS NOT NULL),
    cc."тип_инж_системы",
    cc."тип_датчика"
FROM enriched e
LEFT JOIN channel_catalogue cc ON cc."ид_канала_данных" = e.channel_id
ON CONFLICT ("ид_канала_данных", as_of_date) DO UPDATE SET
    d_observed_days_so_far = EXCLUDED.d_observed_days_so_far,
    d_current_failure_state = EXCLUDED.d_current_failure_state,
    d_event_count_24h = EXCLUDED.d_event_count_24h,
    d_alarm_count_24h = EXCLUDED.d_alarm_count_24h,
    d_alarm_share_24h = EXCLUDED.d_alarm_share_24h,
    d_failure_state_event_count_24h = EXCLUDED.d_failure_state_event_count_24h,
    d_value_numeric_mean_24h = EXCLUDED.d_value_numeric_mean_24h,
    d_value_numeric_min_24h = EXCLUDED.d_value_numeric_min_24h,
    d_value_numeric_max_24h = EXCLUDED.d_value_numeric_max_24h,
    d_value_numeric_std_24h = EXCLUDED.d_value_numeric_std_24h,
    d_value_numeric_last = EXCLUDED.d_value_numeric_last,
    d_state_n_unique_24h = EXCLUDED.d_state_n_unique_24h,
    d_gap_days_since_previous = EXCLUDED.d_gap_days_since_previous,
    d_event_count_previous_24h = EXCLUDED.d_event_count_previous_24h,
    d_alarm_count_previous_24h = EXCLUDED.d_alarm_count_previous_24h,
    d_alarm_share_previous_24h = EXCLUDED.d_alarm_share_previous_24h,
    d_value_numeric_previous = EXCLUDED.d_value_numeric_previous,
    d_days_since_failure_state_event = EXCLUDED.d_days_since_failure_state_event,
    d_weekday = EXCLUDED.d_weekday,
    d_month = EXCLUDED.d_month,
    d_catalogue_match = EXCLUDED.d_catalogue_match,
    "тип_инж_системы" = EXCLUDED."тип_инж_системы",
    "тип_датчика" = EXCLUDED."тип_датчика"
"""


def build_channel_daily_features(
    start_date: date | None = None,
    end_date: date | None = None,
) -> int:
    """Пересчитывает channel_daily_features из events_journal + channel_catalogue.

    Причинно: previous-day и failure-state-history считаются оконными функциями
    по наблюдаемым channel-дням, без обращения к будущим датам.
    """
    with SessionLocal() as session:
        try:
            result = session.execute(
                text(BUILD_CHANNEL_DAILY_FEATURES_SQL),
                {"start_date": start_date, "end_date": end_date},
            )
            session.commit()
            return result.rowcount
        except Exception:
            session.rollback()
            raise
