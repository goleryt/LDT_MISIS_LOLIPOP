from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import (
    ChannelCatalogue,
    ObjectCatalogue,
    PreventiveRequest,
)
from app.db.session import SessionLocal
from app.db.platform import RequestChange


router = APIRouter(
    prefix="/requests",
    tags=["requests"],
)


RequestPriority = Literal[
    "low",
    "medium",
    "high",
    "critical",
]

RequestStatus = Literal[
    "draft",
    "new",
    "in_progress",
    "completed",
    "cancelled",
]

TRANSITIONS = {"draft": {"new", "cancelled"}, "new": {"in_progress", "cancelled"},
               "in_progress": {"completed", "cancelled"}, "completed": set(), "cancelled": set()}

def record_change(db, row, principal, previous, fields):
    db.add(RequestChange(request_id=row.id, actor=principal.username, role=principal.role,
                         from_status=previous, to_status=row.status, changed_fields=sorted(fields)))


class PreventiveRequestCreate(BaseModel):
    object_id: int = Field(ge=1)
    channel_id: int | None = Field(
        default=None,
        ge=1,
    )
    title: str = Field(
        min_length=1,
        max_length=200,
    )
    description: str | None = Field(
        default=None,
        max_length=4000,
    )
    priority: RequestPriority = "medium"


class PreventiveRequestUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    description: str | None = Field(
        default=None,
        max_length=4000,
    )
    priority: RequestPriority | None = None
    status: RequestStatus | None = None


def validate_target(
    session,
    *,
    object_id: int,
    channel_id: int | None,
) -> tuple[ObjectCatalogue, ChannelCatalogue | None]:
    object_item = session.get(
        ObjectCatalogue,
        object_id,
    )

    if object_item is None:
        raise HTTPException(
            status_code=404,
            detail="Object not found",
        )

    if channel_id is None:
        return object_item, None

    sensor = session.get(
        ChannelCatalogue,
        channel_id,
    )

    if sensor is None:
        raise HTTPException(
            status_code=404,
            detail="Sensor not found",
        )

    if sensor.ид_объект != object_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Sensor does not belong to "
                "the selected object"
            ),
        )

    return object_item, sensor


def serialize_request(
    request: PreventiveRequest,
    *,
    object_name: str | None,
    sensor_name: str | None,
) -> dict[str, object]:
    return {
        "id": int(request.id),
        "object_id": int(
            request.object_id
        ),
        "object_name": object_name,
        "channel_id": (
            int(request.channel_id)
            if request.channel_id
            is not None
            else None
        ),
        "sensor_name": sensor_name,
        "title": request.title,
        "description": request.description,
        "priority": request.priority,
        "status": request.status,
        "created_at": (
            request.created_at.isoformat()
            if request.created_at
            is not None
            else None
        ),
        "updated_at": (
            request.updated_at.isoformat()
            if request.updated_at
            is not None
            else None
        ),
        "completed_at": (
            request.completed_at.isoformat()
            if request.completed_at
            is not None
            else None
        ),
    }


def get_request_with_names(
    session,
    request_id: int,
):
    return session.execute(
        select(
            PreventiveRequest,
            ObjectCatalogue.диспетчерское_название_объекта.label(
                "object_name"
            ),
            ChannelCatalogue.название_датчика.label(
                "sensor_name"
            ),
        )
        .join(
            ObjectCatalogue,
            ObjectCatalogue.ид_объект
            == PreventiveRequest.object_id,
        )
        .outerjoin(
            ChannelCatalogue,
            ChannelCatalogue.ид_канала_данных
            == PreventiveRequest.channel_id,
        )
        .where(
            PreventiveRequest.id
            == request_id
        )
    ).first()


@router.get("")
def get_requests(
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
) -> list[dict[str, object]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(
                PreventiveRequest,
                ObjectCatalogue.диспетчерское_название_объекта.label(
                    "object_name"
                ),
                ChannelCatalogue.название_датчика.label(
                    "sensor_name"
                ),
            )
            .join(
                ObjectCatalogue,
                ObjectCatalogue.ид_объект
                == PreventiveRequest.object_id,
            )
            .outerjoin(
                ChannelCatalogue,
                ChannelCatalogue.ид_канала_данных
                == PreventiveRequest.channel_id,
            )
            .order_by(
                PreventiveRequest.id.desc()
            )
            .limit(limit)
        ).all()

        return [
            serialize_request(
                row[0],
                object_name=row.object_name,
                sensor_name=row.sensor_name,
            )
            for row in rows
        ]


@router.post("")
def create_request(
    payload: PreventiveRequestCreate,
    http_request: Request,
) -> dict[str, object]:
    title = payload.title.strip()

    if not title:
        raise HTTPException(
            status_code=422,
            detail="Title must not be blank",
        )

    with SessionLocal() as session:
        validate_target(
            session,
            object_id=payload.object_id,
            channel_id=payload.channel_id,
        )

        request = PreventiveRequest(
            object_id=payload.object_id,
            channel_id=payload.channel_id,
            title=title,
            description=(
                payload.description.strip()
                if payload.description
                else None
            ),
            priority=payload.priority,
            status="new",
        )

        session.add(request)
        session.flush()
        record_change(session, request, http_request.state.principal, None, ["created"])
        session.commit()
        session.refresh(request)

        row = get_request_with_names(
            session,
            request.id,
        )

        if row is None:
            raise HTTPException(
                status_code=500,
                detail="Request serialization failed",
            )

        return serialize_request(
            row[0],
            object_name=row.object_name,
            sensor_name=row.sensor_name,
        )


@router.patch("/{request_id}")
def update_request(
    request_id: int,
    payload: PreventiveRequestUpdate,
    http_request: Request,
) -> dict[str, object]:
    with SessionLocal() as session:
        request = session.get(
            PreventiveRequest,
            request_id,
            with_for_update=True,
        )

        if request is None:
            raise HTTPException(
                status_code=404,
                detail="Request not found",
            )

        changes = payload.model_dump(
            exclude_unset=True
        )
        previous = request.status
        if not changes:
            raise HTTPException(422, "Specify at least one change")
        if previous in {"completed", "cancelled"}:
            raise HTTPException(409, "A closed request cannot be edited")
        if previous == "draft" and http_request.state.principal.role not in {"admin", "dispatcher"}:
            raise HTTPException(403, "Only a dispatcher can review a draft")
        if changes.get("status") is not None and changes["status"] != previous and changes["status"] not in TRANSITIONS.get(previous, set()):
            raise HTTPException(409, "Invalid request status transition")

        for required in ("title", "priority", "status"):
            if required in changes and changes[required] is None:
                raise HTTPException(422, f"{required} cannot be null")
        if request.status in {"completed", "cancelled"} and changes.get("status", request.status) != request.status:
            raise HTTPException(409, "A closed request cannot be reopened")
        if "title" in changes:
            title = changes["title"].strip()

            if not title:
                raise HTTPException(
                    status_code=422,
                    detail="Title must not be blank",
                )

            request.title = title

        if "description" in changes:
            description = changes[
                "description"
            ]
            request.description = (
                description.strip()
                if description
                else None
            )

        if "priority" in changes:
            request.priority = changes[
                "priority"
            ]

        if "status" in changes:
            request.status = changes[
                "status"
            ]

            if request.status == "completed" and request.completed_at is None:
                request.completed_at = (
                    datetime.now(
                        timezone.utc
                    )
                )
            elif request.status != "completed":
                request.completed_at = None

        request.updated_at = datetime.now(
            timezone.utc
        )

        record_change(session, request, http_request.state.principal, previous, changes.keys())

        session.commit()

        row = get_request_with_names(
            session,
            request.id,
        )

        if row is None:
            raise HTTPException(
                status_code=500,
                detail="Request serialization failed",
            )

        return serialize_request(
            row[0],
            object_name=row.object_name,
            sensor_name=row.sensor_name,
        )


@router.get("/{request_id}/history")
def request_history(request_id: int):
    with SessionLocal() as db:
        if db.get(PreventiveRequest, request_id) is None:
            raise HTTPException(404, "Request not found")
        return [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in db.scalars(select(RequestChange).where(RequestChange.request_id == request_id)
                                      .order_by(RequestChange.id))]
