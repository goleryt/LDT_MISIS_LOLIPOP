"""Canonical, read-only source integration. Receiving data never calls an equipment control API."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.db.models import ChannelCatalogue, EventsJournal, ObjectCatalogue, PreventiveRequest
from app.db.platform import IntegrationRecord, Notification, ObjectLocation
from app.ingestion.csv_loader import parse_event_row

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    external_id: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    object_id: int | None = Field(None, ge=1)
    channel_id: int | None = Field(None, ge=1)
    event_id: int | None = Field(None, ge=1)
    alarm: bool | None = None
    value: str | None = Field(None, max_length=2000)
    name: str | None = Field(None, max_length=200)
    sensor_type: str | None = Field(None, max_length=100)
    system_type: str | None = Field(None, max_length=100)
    tag: str | None = Field(None, max_length=200)
    longitude: float | None = Field(None, ge=-180, le=180)
    latitude: float | None = Field(None, ge=-90, le=90)
    description: str | None = Field(None, max_length=4000)
    request_id: int | None = Field(None, ge=1)
    status: Literal["new", "in_progress", "completed", "cancelled"] | None = None
    temperature: float | None = None
    humidity: float | None = Field(None, ge=0, le=100)
    precipitation: float | None = Field(None, ge=0)
    pressure: float | None = Field(None, gt=0)
    mock: bool = False

    @model_validator(mode="after")
    def valid_time(self):
        if self.observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Source timestamp is more than 5 minutes in the future")
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("Both coordinates are required")
        return self

KINDS = {"telemetry", "equipment", "ods", "work_status", "weather"}

def ingest(db, kind: str, source: str, records: list[Record]):
    if kind not in KINDS:
        raise ValueError("Unknown integration kind")
    inserted = 0
    maximum_lag = 0.0
    for item in records:
        if item.mock and not get_settings().allow_mock_ingestion:
            raise ValueError("Mock ingestion is disabled")
        payload = item.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        # A source message is immutable. Conflicting retries are rejected, never silently overwritten.
        statement = insert(IntegrationRecord).values(source=source, kind=kind, external_id=item.external_id,
                    payload_hash=digest, payload=payload, observed_at=item.observed_at).on_conflict_do_nothing().returning(IntegrationRecord.id)
        record_id = db.scalar(statement)
        if record_id is None:
            old = db.scalar(select(IntegrationRecord).where(IntegrationRecord.source == source,
                            IntegrationRecord.kind == kind, IntegrationRecord.external_id == item.external_id))
            if old.payload_hash != digest:
                raise ValueError("External ID already exists with a different payload")
            continue
        if kind == "equipment":
            if item.object_id is None or not item.name:
                raise ValueError("Equipment requires object_id and name")
            db.execute(insert(ObjectCatalogue).values(ид_объект=item.object_id,
                       диспетчерское_название_объекта=item.name).on_conflict_do_update(
                       index_elements=["ид_объект"], set_={"диспетчерское_название_объекта": item.name}))
            if item.channel_id:
                existing = db.get(ChannelCatalogue, item.channel_id)
                if existing and existing.ид_объект != item.object_id:
                    raise ValueError("Reassigning a channel requires a reviewed data migration")
                data = {"ид_канала_данных": item.channel_id, "ид_объект": item.object_id,
                        "название_датчика": item.name, "тип_датчика": item.sensor_type,
                        "тип_инж_системы": item.system_type, "тег_инженерной_системы": item.tag}
                db.execute(insert(ChannelCatalogue).values(**data).on_conflict_do_update(
                           index_elements=["ид_канала_данных"], set_=data))
            if item.longitude is not None:
                db.execute(insert(ObjectLocation).values(object_id=item.object_id, longitude=item.longitude,
                           latitude=item.latitude).on_conflict_do_update(index_elements=["object_id"],
                           set_={"longitude": item.longitude, "latitude": item.latitude}))
        elif kind == "telemetry":
            channel = db.get(ChannelCatalogue, item.channel_id) if item.channel_id else None
            if not channel or item.event_id is None or item.alarm is None:
                raise ValueError("Telemetry requires a known channel_id, event_id and alarm")
            if item.object_id and channel.ид_объект != item.object_id:
                raise ValueError("Channel does not belong to object")
            local = item.observed_at.astimezone(ZoneInfo(get_settings().source_timezone)).replace(tzinfo=None)
            event = parse_event_row({"ид_события": str(item.event_id), "ид_канала_данных": str(item.channel_id),
                    "дата": local.date().isoformat(), "время": local.time().isoformat(),
                    "тревожное": str(item.alarm).lower(), "значение_датчика": item.value}, row_number=1)
            event_row = db.scalar(insert(EventsJournal).values(**event).on_conflict_do_nothing(
                                  index_elements=["d_row_hash"]).returning(EventsJournal.id))
            if event_row and item.alarm:
                db.add(Notification(kind="observed_alarm", object_id=channel.ид_объект, reference_id=event_row,
                                    message=f"{'Тестовый поток: ' if item.mock else ''}Тревога датчика {item.channel_id}"))
        elif kind == "work_status":
            target = db.scalar(select(PreventiveRequest).where(PreventiveRequest.id == item.request_id).with_for_update())
            if not target or item.status is None:
                raise ValueError("Work status requires known request_id and status")
            if target.status in {"completed", "cancelled"} and target.status != item.status:
                raise ValueError("A closed request cannot be reopened by an integration")
            target.status = item.status
            target.updated_at = datetime.now(timezone.utc)
            if item.status == "completed" and target.completed_at is None:
                target.completed_at = datetime.now(timezone.utc)
        elif kind == "ods":
            if not item.description:
                raise ValueError("ODS record requires description")
        elif kind == "weather":
            if item.longitude is None or all(v is None for v in (item.temperature, item.humidity, item.precipitation, item.pressure)):
                raise ValueError("Weather requires location and at least one measurement")
        inserted += 1
        maximum_lag = max(maximum_lag, (datetime.now(timezone.utc) - item.observed_at).total_seconds())
    return {"inserted": inserted, "duplicates": len(records) - inserted,
            "max_source_lag_seconds": round(maximum_lag, 3), "within_300_seconds": maximum_lag <= 300}
