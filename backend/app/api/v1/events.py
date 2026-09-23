from fastapi import APIRouter, Query
from sqlalchemy import select

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
    ObjectCatalogue,
)
from app.db.session import SessionLocal


router = APIRouter(
    prefix="/events",
    tags=["events"],
)


@router.get("")
def get_events(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    alarm: bool | None = Query(
        default=None,
    ),
    object_id: int | None = Query(
        default=None,
        ge=1,
    ),
    channel_id: int | None = Query(
        default=None,
        ge=1,
    ),
) -> dict[str, object]:
    statement = (
        select(
            EventsJournal.id.label(
                "row_id"
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
            ChannelCatalogue.название_датчика.label(
                "sensor_name"
            ),
            ChannelCatalogue.тип_датчика.label(
                "sensor_type"
            ),
            ChannelCatalogue.тип_инж_системы.label(
                "system_type"
            ),
            ChannelCatalogue.ид_объект.label(
                "object_id"
            ),
            ObjectCatalogue.диспетчерское_название_объекта.label(
                "object_name"
            ),
        )
        .outerjoin(
            ChannelCatalogue,
            ChannelCatalogue.ид_канала_данных
            == EventsJournal.ид_канала_данных,
        )
        .outerjoin(
            ObjectCatalogue,
            ObjectCatalogue.ид_объект
            == ChannelCatalogue.ид_объект,
        )
    )

    if alarm is not None:
        statement = statement.where(
            EventsJournal.d_alarm.is_(alarm)
        )

    if object_id is not None:
        statement = statement.where(
            ChannelCatalogue.ид_объект
            == object_id
        )

    if channel_id is not None:
        statement = statement.where(
            EventsJournal.ид_канала_данных
            == channel_id
        )

    statement = (
        statement
        .order_by(
            EventsJournal.d_event_time
            .desc()
            .nullslast(),
            EventsJournal.id.desc(),
        )
        .offset(offset)
        .limit(limit + 1)
    )

    with SessionLocal() as session:
        rows = session.execute(
            statement
        ).mappings().all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    events: list[dict[str, object]] = []

    for row in rows:
        event_time = row["event_time"]

        events.append(
            {
                "row_id": int(
                    row["row_id"]
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
                "sensor_name": row[
                    "sensor_name"
                ],
                "sensor_type": row[
                    "sensor_type"
                ],
                "system_type": row[
                    "system_type"
                ],
                "event_time": (
                    event_time.isoformat()
                    if event_time is not None
                    else None
                ),
                "alarm": row["alarm"],
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
        "limit": limit,
        "offset": offset,
        "returned": len(events),
        "has_more": has_more,
        "events": events,
    }
