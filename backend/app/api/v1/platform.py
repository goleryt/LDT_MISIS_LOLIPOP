from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from app.db.platform import AuditEntry, Notification, NotificationRead
from app.db.session import SessionLocal

router = APIRouter(tags=["operations"])

def serialize(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}

@router.get("/audit")
def audit(after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        return [serialize(x) for x in db.scalars(select(AuditEntry).where(AuditEntry.id > after_id).order_by(AuditEntry.id).limit(limit))]

@router.get("/notifications")
def notifications(request: Request, limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        read = exists().where(NotificationRead.notification_id == Notification.id,
                              NotificationRead.username == request.state.principal.username)
        return [serialize(x) for x in db.scalars(select(Notification).where(~read).order_by(Notification.id.desc()).limit(limit))]

@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, request: Request):
    with SessionLocal.begin() as db:
        if not db.get(Notification, notification_id):
            raise HTTPException(404, "Notification not found")
        db.execute(insert(NotificationRead).values(notification_id=notification_id,
                   username=request.state.principal.username).on_conflict_do_nothing())
    return {"status": "read"}
