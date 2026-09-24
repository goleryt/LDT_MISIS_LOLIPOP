import hashlib

from fastapi import APIRouter
from sqlalchemy import case, func, select

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
    ObjectCatalogue,
)
from app.db.session import SessionLocal
from app.db.platform import ObjectLocation
from app.core.read_cache import cached_snapshot


router = APIRouter(
    prefix="/map",
    tags=["map"],
)


SYNTHETIC_MIN_LON = 37.35
SYNTHETIC_MAX_LON = 37.85
SYNTHETIC_MIN_LAT = 55.55
SYNTHETIC_MAX_LAT = 55.95


def synthetic_point_for_object(
    object_id: int,
) -> tuple[float, float]:
    """
    Создаёт стабильную демонстрационную координату объекта.

    Координата не является реальным местоположением объекта.
    Для одного object_id результат всегда одинаковый.
    """
    digest = hashlib.sha256(
        str(object_id).encode("utf-8")
    ).digest()

    lon_ratio = (
        int.from_bytes(digest[0:8], "big")
        / ((1 << 64) - 1)
    )

    lat_ratio = (
        int.from_bytes(digest[8:16], "big")
        / ((1 << 64) - 1)
    )

    longitude = (
        SYNTHETIC_MIN_LON
        + lon_ratio
        * (
            SYNTHETIC_MAX_LON
            - SYNTHETIC_MIN_LON
        )
    )

    latitude = (
        SYNTHETIC_MIN_LAT
        + lat_ratio
        * (
            SYNTHETIC_MAX_LAT
            - SYNTHETIC_MIN_LAT
        )
    )

    return (
        round(longitude, 6),
        round(latitude, 6),
    )


@router.get("/objects")
@cached_snapshot
def get_map_objects() -> list[dict[str, object]]:
    ranked_events = (
        select(
            EventsJournal.ид_канала_данных.label(
                "channel_id"
            ),
            EventsJournal.d_alarm.label(
                "alarm"
            ),
            EventsJournal.d_event_time.label(
                "event_time"
            ),
            func.row_number()
            .over(
                partition_by=(
                    EventsJournal.ид_канала_данных
                ),
                order_by=(
                    EventsJournal.d_event_time
                    .desc()
                    .nullslast(),
                    EventsJournal.id.desc(),
                ),
            )
            .label("row_number"),
        )
        .cte("ranked_events")
    )

    latest_events = (
        select(
            ranked_events.c.channel_id,
            ranked_events.c.alarm,
            ranked_events.c.event_time,
        )
        .where(
            ranked_events.c.row_number == 1
        )
        .subquery()
    )

    statement = (
        select(
            ObjectCatalogue.ид_объект.label(
                "object_id"
            ),
            ObjectCatalogue
            .диспетчерское_название_объекта
            .label("object_name"),
            ObjectCatalogue.вид_объекта.label(
                "object_type"
            ),
            func.count(
                ChannelCatalogue
                .ид_канала_данных
            ).label("sensor_count"),
            func.count(
                latest_events.c.channel_id
            ).label("sensors_with_data"),
            func.sum(
                case(
                    (
                        latest_events.c.alarm
                        .is_(True),
                        1,
                    ),
                    else_=0,
                )
            ).label("alarm_sensor_count"),
            func.max(
                latest_events.c.event_time
            ).label("last_event_time"),
        )
        .join(
            ChannelCatalogue,
            ChannelCatalogue.ид_объект
            == ObjectCatalogue.ид_объект,
        )
        .outerjoin(
            latest_events,
            latest_events.c.channel_id
            == ChannelCatalogue
            .ид_канала_данных,
        )
        .group_by(
            ObjectCatalogue.ид_объект,
            ObjectCatalogue
            .диспетчерское_название_объекта,
            ObjectCatalogue.вид_объекта,
        )
        .order_by(
            ObjectCatalogue.ид_объект
        )
    )

    with SessionLocal() as session:
        rows = session.execute(
            statement
        ).mappings().all()

    with SessionLocal() as session:
        locations = {row.object_id: (row.longitude, row.latitude) for row in session.scalars(select(ObjectLocation))}
    result: list[dict[str, object]] = []

    for row in rows:
        object_id = int(
            row["object_id"]
        )

        sensor_count = int(
            row["sensor_count"] or 0
        )

        sensors_with_data = int(
            row["sensors_with_data"] or 0
        )

        alarm_sensor_count = int(
            row["alarm_sensor_count"] or 0
        )

        if alarm_sensor_count > 0:
            status = "alarm"

        elif sensors_with_data > 0:
            status = "normal"

        else:
            status = "unknown"

        longitude, latitude = (
            synthetic_point_for_object(
                object_id
            )
        )

        if object_id in locations:
            longitude, latitude = locations[object_id]
        last_event_time = row[
            "last_event_time"
        ]

        result.append(
            {
                "object_id": object_id,
                "name": row[
                    "object_name"
                ],
                "object_type": row[
                    "object_type"
                ],
                "status": status,
                "sensor_count": sensor_count,
                "sensors_with_data": (
                    sensors_with_data
                ),
                "alarm_sensor_count": (
                    alarm_sensor_count
                ),
                "last_event_time": (
                    last_event_time.isoformat()
                    if last_event_time is not None
                    else None
                ),
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        longitude,
                        latitude,
                    ],
                },
                "geometry_is_synthetic": object_id not in locations,
            }
        )

    return result
