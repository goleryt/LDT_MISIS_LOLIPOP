from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.sql import func

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
    ObjectCatalogue,
)
from app.db.session import SessionLocal
from app.core.read_cache import cached_snapshot


router = APIRouter(
    prefix="/alarms",
    tags=["alarms"],
)


@router.get("")
@cached_snapshot
def get_active_alarms(
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
) -> dict[str, object]:
    with SessionLocal() as session:
        ranked_events = (
            select(
                EventsJournal.id.label(
                    "event_row_id"
                ),
                EventsJournal.ид_события.label(
                    "event_id"
                ),
                EventsJournal.ид_канала_данных.label(
                    "channel_id"
                ),
                EventsJournal.d_event_time.label(
                    "event_time"
                ),
                EventsJournal.d_alarm.label(
                    "alarm"
                ),
                EventsJournal.значение_датчика.label(
                    "raw_value"
                ),
                EventsJournal.d_value_numeric.label(
                    "numeric_value"
                ),
                EventsJournal.d_value_state.label(
                    "state_value"
                ),
                func.row_number()
                .over(
                    partition_by=(
                        EventsJournal
                        .ид_канала_данных
                    ),
                    order_by=(
                        EventsJournal
                        .d_event_time
                        .desc()
                        .nullslast(),
                        EventsJournal.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .subquery()
        )

        statement = (
            select(
                ranked_events.c.event_row_id,
                ranked_events.c.event_id,
                ranked_events.c.channel_id,
                ranked_events.c.event_time,
                ranked_events.c.alarm,
                ranked_events.c.raw_value,
                ranked_events.c.numeric_value,
                ranked_events.c.state_value,

                ChannelCatalogue
                .название_датчика
                .label("sensor_name"),

                ChannelCatalogue
                .тип_датчика
                .label("sensor_type"),

                ChannelCatalogue
                .тип_инж_системы
                .label("system_type"),

                ChannelCatalogue
                .тег_инженерной_системы
                .label("tag"),

                ChannelCatalogue
                .ид_объект
                .label("object_id"),

                ObjectCatalogue
                .диспетчерское_название_объекта
                .label("object_name"),

                ObjectCatalogue
                .вид_объекта
                .label("object_type"),
            )
            .join(
                ChannelCatalogue,
                ChannelCatalogue
                .ид_канала_данных
                == ranked_events.c.channel_id,
            )
            .outerjoin(
                ObjectCatalogue,
                ObjectCatalogue.ид_объект
                == ChannelCatalogue.ид_объект,
            )
            .where(
                ranked_events.c.row_number == 1,
                ranked_events.c.alarm.is_(True),
            )
            .order_by(
                ranked_events.c.event_time
                .desc()
                .nullslast(),
                ranked_events.c.event_row_id.desc(),
            )
            .limit(limit)
        )

        rows = session.execute(
            statement
        ).mappings().all()

        alarms: list[dict[str, object]] = []

        for row in rows:
            event_time = row[
                "event_time"
            ]

            alarms.append(
                {
                    "event_row_id": int(
                        row["event_row_id"]
                    ),
                    "event_id": int(
                        row["event_id"]
                    ),
                    "channel_id": int(
                        row["channel_id"]
                    ),
                    "object_id": (
                        int(row["object_id"])
                        if row["object_id"]
                        is not None
                        else None
                    ),
                    "object_name": row[
                        "object_name"
                    ],
                    "object_type": row[
                        "object_type"
                    ],
                    "sensor_name": row[
                        "sensor_name"
                    ],
                    "sensor_type": row[
                        "sensor_type"
                    ],
                    "system_type": row[
                        "system_type"
                    ],
                    "tag": row["tag"],
                    "event_time": (
                        event_time.isoformat()
                        if event_time is not None
                        else None
                    ),
                    "alarm": bool(
                        row["alarm"]
                    ),
                    "raw_value": row[
                        "raw_value"
                    ],
                    "numeric_value": row[
                        "numeric_value"
                    ],
                    "state_value": row[
                        "state_value"
                    ],
                }
            )

        return {
            "count": len(alarms),
            "alarms": alarms,
        }
