from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
    ObjectCatalogue,
)
from app.db.session import SessionLocal
from app.ml.service import score_channels


router = APIRouter(
    prefix="/objects",
    tags=["objects"],
)


@router.get("/{object_id}/sensors")
def get_object_sensors(
    object_id: int,
) -> dict[str, object]:
    with SessionLocal() as session:
        object_item = session.get(
            ObjectCatalogue,
            object_id,
        )

        if object_item is None:
            raise HTTPException(
                status_code=404,
                detail="Object not found",
            )

        object_channel_ids = (
            select(
                ChannelCatalogue
                .ид_канала_данных
            )
            .where(
                ChannelCatalogue.ид_объект
                == object_id
            )
        )

        ranked_events = (
            select(
                EventsJournal
                .ид_канала_данных
                .label("channel_id"),
                EventsJournal
                .d_event_time
                .label("event_time"),
                EventsJournal
                .d_alarm
                .label("alarm"),
                EventsJournal
                .значение_датчика
                .label("raw_value"),
                EventsJournal
                .d_value_numeric
                .label("numeric_value"),
                EventsJournal
                .d_value_state
                .label("state_value"),
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
                        EventsJournal
                        .id
                        .desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(
                EventsJournal
                .ид_канала_данных
                .in_(object_channel_ids)
            )
            .cte(
                "ranked_object_events"
            )
        )

        latest_events = (
            select(
                ranked_events.c.channel_id,
                ranked_events.c.event_time,
                ranked_events.c.alarm,
                ranked_events.c.raw_value,
                ranked_events.c.numeric_value,
                ranked_events.c.state_value,
            )
            .where(
                ranked_events.c.row_number
                == 1
            )
            .subquery()
        )

        statement = (
            select(
                ChannelCatalogue
                .ид_канала_данных
                .label("channel_id"),
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
                .d_site
                .label("site"),
                ChannelCatalogue
                .d_pk
                .label("picket"),
                latest_events.c.channel_id
                .label("event_channel_id"),
                latest_events.c.event_time,
                latest_events.c.alarm,
                latest_events.c.raw_value,
                latest_events.c.numeric_value,
                latest_events.c.state_value,
            )
            .outerjoin(
                latest_events,
                latest_events.c.channel_id
                == ChannelCatalogue
                .ид_канала_данных,
            )
            .where(
                ChannelCatalogue.ид_объект
                == object_id
            )
            .order_by(
                ChannelCatalogue
                .название_датчика,
                ChannelCatalogue
                .ид_канала_данных,
            )
        )

        rows = session.execute(
            statement
        ).mappings().all()

        risk_by_channel = score_channels(
            session,
            [
                (
                    int(row["channel_id"]),
                    row["sensor_type"],
                    row["system_type"],
                )
                for row in rows
            ],
        )

        sensors: list[
            dict[str, object]
        ] = []

        for row in rows:
            has_data = (
                row["event_channel_id"]
                is not None
            )

            if not has_data:
                status = "unknown"

            elif row["alarm"] is True:
                status = "alarm"

            else:
                status = "normal"

            event_time = row[
                "event_time"
            ]

            channel_id = int(
                row["channel_id"]
            )

            # Experimental shadow-model risk (see app/ml/service.py).
            # None when the channel has no events to score yet.
            risk = risk_by_channel.get(
                channel_id
            )

            sensors.append(
                {
                    "channel_id": channel_id,
                    "name": row[
                        "sensor_name"
                    ],
                    "sensor_type": row[
                        "sensor_type"
                    ],
                    "system_type": row[
                        "system_type"
                    ],
                    "tag": row["tag"],
                    "site": row["site"],
                    "picket": row[
                        "picket"
                    ],
                    "status": status,
                    "has_data": has_data,
                    "alarm": (
                        row["alarm"]
                        if has_data
                        else None
                    ),
                    "last_event_time": (
                        event_time.isoformat()
                        if event_time
                        is not None
                        else None
                    ),
                    "latest_value_raw": row[
                        "raw_value"
                    ],
                    "latest_value_numeric": row[
                        "numeric_value"
                    ],
                    "latest_value_state": row[
                        "state_value"
                    ],
                    "risk_score": (
                        risk["risk_score"]
                        if risk
                        else None
                    ),
                    "risk_is_alert_candidate": (
                        risk["risk_is_alert_candidate"]
                        if risk
                        else None
                    ),
                    "risk_window_start": (
                        risk["risk_window_start"]
                        if risk
                        else None
                    ),
                    "risk_window_end_exclusive": (
                        risk["risk_window_end_exclusive"]
                        if risk
                        else None
                    ),
                    "risk_decision_status": (
                        risk["risk_decision_status"]
                        if risk
                        else None
                    ),
                    "risk_model_version": (
                        risk["risk_model_version"]
                        if risk
                        else None
                    ),
                }
            )

        # Stable multi-key sort applied lowest-priority first:
        # 1. активная тревога; 2. ML-риск по убыванию (эксперимент,
        # см. app/ml/service.py); 3. время последнего события по убыванию;
        # 4. channel_id как стабильный tie-breaker.
        sensors.sort(key=lambda sensor: sensor["channel_id"])
        sensors.sort(
            key=lambda sensor: sensor["last_event_time"] or "",
            reverse=True,
        )
        sensors.sort(
            key=lambda sensor: (
                sensor["risk_score"]
                if sensor["risk_score"] is not None
                else -1.0
            ),
            reverse=True,
        )
        sensors.sort(
            key=lambda sensor: 0 if sensor["alarm"] is True else 1
        )

        return {
            "object_id": int(
                object_item.ид_объект
            ),
            "name": (
                object_item
                .диспетчерское_название_объекта
            ),
            "object_type": (
                object_item.вид_объекта
            ),
            "sensor_count": len(
                sensors
            ),
            "sensors": sensors,
        }