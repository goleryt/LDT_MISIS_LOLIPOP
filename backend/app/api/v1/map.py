import hashlib
import math

from fastapi import APIRouter
from sqlalchemy import case, func, select

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
    ObjectCatalogue,
)
from app.db.session import SessionLocal
from app.db.platform import ObjectLocation, MlScore, Prediction, ScenarioForecast, ScenarioRun
from app.scenario_job import configuration
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
    Создаёт стабильную условную координату объекта внутри Москвы.

    Координата не является реальным местоположением объекта.
    Для одного object_id результат всегда одинаковый; никакая
    географическая близость объектов из каталога не подразумевается.
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

    # The catalogue key groups channels under an object record. It does not
    # establish an address, equipment identity, or one channel per device.
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
                "data_is_synthetic": False,
            }
        )

    return result


@router.get("/forecasts")
def get_map_forecasts():
    """Read saved evidence only. Never run inference or derive an incident score.

    Gas includes non-selected/abstained rows from the latest day; Top-K remains
    the work queue policy, not a visibility threshold. Scenario rows belong to
    the latest snapshot, including failed/partial snapshots, never an older
    successful run silently substituted for a failed calculation.
    """
    rows = []
    limit = 500
    def finite(value):
        return isinstance(value, (int, float)) and math.isfinite(value)

    with SessionLocal() as db:
        objects = set(db.scalars(select(ObjectCatalogue.ид_объект).join(ChannelCatalogue,
            ChannelCatalogue.ид_объект == ObjectCatalogue.ид_объект).distinct()))
        bindings = dict(db.execute(select(ChannelCatalogue.ид_канала_данных, ChannelCatalogue.ид_объект)).all())
        def bound(oid, cid):
            return oid in objects and (cid is None or bindings.get(cid) == oid)

        day = db.scalar(select(func.max(MlScore.as_of_date)).where(MlScore.kind == 'gas'))
        gas = db.scalars(select(MlScore).where(MlScore.kind == 'gas', MlScore.as_of_date == day)
            .order_by(MlScore.id.desc()).limit(limit + 1)).all() if day else []
        # A journal link must refer to this saved score, never another model/day.
        linked = {(p.channel_id, (p.ml_metadata or {}).get('as_of_date'), p.model_version, p.probability): p for p in db.scalars(
            select(Prediction).where(Prediction.channel_id.in_([g.channel_id for g in gas if g.channel_id is not None]))
            .order_by(Prediction.id))}
        seen = set()
        for g in gas[:limit]:
            key = (g.object_id, g.channel_id)
            if key in seen:
                continue
            seen.add(key)
            binding = bound(g.object_id, g.channel_id)
            p = linked.get((g.channel_id, str(g.as_of_date), g.model_version, g.score))
            available = binding and finite(g.score) and g.decision_status == 'experimental_shadow'
            rows.append({'key': f'gas-{g.id}', 'worker': 'gas', 'object_id': g.object_id,
                'channel_id': g.channel_id, 'bound': binding, 'available': available,
                'score': g.score if available else None, 'score_kind': g.score_kind,
                'warning': None, 'queue_selected': g.selected, 'reason': g.reason_codes,
                'cutoff': str(g.as_of_date), 'issued_at': g.created_at,
                'window_start': g.window_start, 'window_end_exclusive': g.window_end_exclusive,
                'model_version': g.model_version, 'source': 'Сохранённый газовый shadow-расчёт; источник указан в снимке',
                'snapshot_version': g.run_id, 'detail_url': f'/predictions?predictionId={p.id}' if p else '/predictions',
                'recommendations': [(g.payload.get('recommendation') or {}).get('text_ru')] if (g.payload.get('recommendation') or {}).get('text_ru') else []})
        run = db.scalar(select(ScenarioRun).order_by(ScenarioRun.id.desc()).limit(1))
        scenarios = db.scalars(select(ScenarioForecast).where(ScenarioForecast.run_id == run.id)
            .order_by(ScenarioForecast.id).limit(limit + 1)).all() if run else []
        config = configuration()
        for s in scenarios[:limit]:
            p = s.payload
            binding = bound(s.object_id, s.channel_id)
            available = binding and p.get('eligible') is True and finite(p.get('score')) and config['enabled'] and config.get(s.worker, False)
            recommendations = (run.output or {}).get('evidence_context', {}).get('recommendations', [])
            rows.append({'key': f'{s.worker}-{s.id}', 'worker': s.worker, 'object_id': s.object_id,
                'channel_id': s.channel_id, 'bound': binding, 'available': available,
                'score': p.get('score') if available else None, 'score_kind': p.get('score_kind'),
                'warning': p.get('warning') if available else None, 'reason': p.get('reason'),
                'cutoff': p.get('cutoff'), 'issued_at': p.get('issued_at'), 'window_start': p.get('window_start'),
                'window_end_exclusive': p.get('window_end_exclusive'), 'model_version': p.get('model_version'),
                'source': 'Синтетический сценарий · экспериментальная модель', 'snapshot_version': run.snapshot_version,
                'detail_url': f'/predictions?scenarioRun={run.id}&scenarioId={s.id}&scenarioType={s.worker}',
                'recommendations': [r['text_ru'] for r in recommendations if s.forecast_ref in r.get('forecast_refs', [])]})
        return {'forecasts': rows, 'configuration': config,
            'scenario_run': {'id': run.id, 'state': run.state, 'error_code': run.error_code} if run else None,
            'gas_as_of_date': day, 'truncated': len(gas) > limit or len(scenarios) > limit,
            'operational_ready': False, 'automated_action_allowed': False}
