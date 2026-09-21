from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
)
from app.db.session import SessionLocal


router = APIRouter(
    prefix="/sensors",
    tags=["sensors"],
)


@router.get("/{channel_id}/history")
def get_sensor_history(
    channel_id: int,
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
) -> dict[str, object]:
    with SessionLocal() as session:
        sensor = session.get(
            ChannelCatalogue,
            channel_id,
        )

        if sensor is None:
            raise HTTPException(
                status_code=404,
                detail="Sensor not found",
            )

        statement = (
            select(
                EventsJournal.id,
                EventsJournal.ид_события,
                EventsJournal.d_event_time,
                EventsJournal.d_alarm,
                EventsJournal.значение_датчика,
                EventsJournal.d_value_numeric,
                EventsJournal.d_value_state,
            )
            .where(
                EventsJournal.ид_канала_данных
                == channel_id
            )
            .order_by(
                EventsJournal.d_event_time
                .desc()
                .nullslast(),
                EventsJournal.id.desc(),
            )
            .limit(limit)
        )

        rows = session.execute(
            statement
        ).mappings().all()

        events: list[dict[str, object]] = []

        # SQL возвращает последние события сначала,
        # а графику удобнее хронологический порядок.
        for row in reversed(rows):
            event_time = row[
                "d_event_time"
            ]

            events.append(
                {
                    "id": int(
                        row["id"]
                    ),
                    "event_id": int(
                        row["ид_события"]
                    ),
                    "event_time": (
                        event_time.isoformat()
                        if event_time is not None
                        else None
                    ),
                    "alarm": row[
                        "d_alarm"
                    ],
                    "raw_value": row[
                        "значение_датчика"
                    ],
                    "numeric_value": row[
                        "d_value_numeric"
                    ],
                    "state_value": row[
                        "d_value_state"
                    ],
                }
            )

        numeric_event_count = sum(
            1
            for event in events
            if event["numeric_value"]
            is not None
        )

        alarm_event_count = sum(
            1
            for event in events
            if event["alarm"] is True
        )

        return {
            "channel_id": int(
                sensor.ид_канала_данных
            ),
            "name": sensor.название_датчика,
            "sensor_type": sensor.тип_датчика,
            "system_type": (
                sensor.тип_инж_системы
            ),
            "object_id": sensor.ид_объект,
            "returned_events": len(events),
            "numeric_event_count": (
                numeric_event_count
            ),
            "alarm_event_count": (
                alarm_event_count
            ),
            "events": events,
        }