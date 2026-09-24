from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

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
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    alarm_state: Literal["all", "alarm", "normal", "unknown"] = "all",
    object_query: str | None = Query(default=None, max_length=100),
    sensor_query: str | None = Query(default=None, max_length=100),
    event_query: str | None = Query(default=None, max_length=100),
    sort_by: Literal["time", "object", "sensor", "event", "status"] = "time",
    sort_desc: bool = True,
) -> dict[str, object]:
    if (time_from and time_from.tzinfo) or (time_to and time_to.tzinfo):
        raise HTTPException(
            status_code=422,
            detail="Time range must use local datetimes without timezone offsets",
        )

    if time_from and time_to and time_from > time_to:
        raise HTTPException(
            status_code=422,
            detail="time_from must not be later than time_to",
        )

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

    if alarm_state == "alarm":
        statement = statement.where(EventsJournal.d_alarm.is_(True))
    elif alarm_state == "normal":
        statement = statement.where(EventsJournal.d_alarm.is_(False))
    elif alarm_state == "unknown":
        statement = statement.where(EventsJournal.d_alarm.is_(None))
    elif alarm is not None:
        statement = statement.where(
            EventsJournal.d_alarm.is_(alarm)
        )

    if time_from is not None:
        statement = statement.where(EventsJournal.d_event_time >= time_from)

    if time_to is not None:
        statement = statement.where(EventsJournal.d_event_time <= time_to)

    if object_query:
        query = object_query.strip()
        if query:
            predicate = ObjectCatalogue.диспетчерское_название_объекта.ilike(
                f"%{query}%"
            )
            if query.isdecimal() and len(query) <= 18:
                predicate = or_(predicate, ChannelCatalogue.ид_объект == int(query))
            statement = statement.where(predicate)

    if sensor_query:
        query = sensor_query.strip()
        if query:
            predicate = ChannelCatalogue.название_датчика.ilike(f"%{query}%")
            if query.isdecimal() and len(query) <= 18:
                predicate = or_(predicate, EventsJournal.ид_канала_данных == int(query))
            statement = statement.where(predicate)

    if event_query:
        query = event_query.strip()
        if query:
            predicate = or_(
                EventsJournal.значение_датчика.ilike(f"%{query}%"),
                EventsJournal.d_value_state.ilike(f"%{query}%"),
            )
            if query.isdecimal() and len(query) <= 18:
                predicate = or_(predicate, EventsJournal.ид_события == int(query))
            statement = statement.where(predicate)

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

    sort_columns = {
        "time": EventsJournal.d_event_time,
        "object": ObjectCatalogue.диспетчерское_название_объекта,
        "sensor": ChannelCatalogue.название_датчика,
        "event": EventsJournal.ид_события,
        "status": EventsJournal.d_alarm,
    }
    sort_column = sort_columns[sort_by]
    sort_order = sort_column.desc() if sort_desc else sort_column.asc()
    row_order = EventsJournal.id.desc() if sort_desc else EventsJournal.id.asc()

    statement = (
        statement
        .order_by(sort_order.nullslast(), row_order)
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
