from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from app.core.config import get_settings
from app.db.platform import IntegrationCursor, IntegrationRecord
from app.db.session import SessionLocal
from app.ingestion.formats import decode_records
from app.ingestion.integrations import Record, ingest
from app.api.v1.platform import serialize

router = APIRouter(prefix="/integrations", tags=["integrations"])
Kind = Literal["telemetry", "equipment", "ods", "work_status", "weather"]

@router.post("/{kind}")
async def receive(kind: Kind, request: Request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > get_settings().max_upload_bytes:
            raise HTTPException(413, "Payload too large")
    media = request.headers.get("content-type", "").split(";")[0]
    if media not in {"application/json", "application/xml", "text/xml"}:
        raise HTTPException(415, "Use application/json or application/xml")
    try:
        records = [Record.model_validate(x) for x in decode_records(bytes(data), "json" if media == "application/json" else "xml")]
        if len(records) > 2000:
            raise ValueError("Maximum API batch is 2000 records")
        # Source identity comes from the authenticated account, never from request data.
        from starlette.concurrency import run_in_threadpool
        def save():
            with SessionLocal.begin() as db:
                return ingest(db, kind, request.state.principal.username, records)
        return await run_in_threadpool(save)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from None

@router.get("/records/{kind}")
def records(kind: Kind, after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        return [serialize(x) for x in db.scalars(select(IntegrationRecord).where(
            IntegrationRecord.kind == kind, IntegrationRecord.id > after_id).order_by(IntegrationRecord.id).limit(limit))]

@router.get("/status")
def status():
    with SessionLocal() as db:
        return [serialize(x) for x in db.scalars(select(IntegrationCursor).order_by(IntegrationCursor.source))]
