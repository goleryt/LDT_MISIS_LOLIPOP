"""Audit intent before execution and outcome after; never record bodies or tokens."""
import logging
import uuid
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from sqlalchemy import update
from app.core.security import authorize
from app.db.platform import AuditEntry
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

def begin_audit(request, request_id):
    with SessionLocal.begin() as db:
        record = AuditEntry(request_id=request_id, actor=getattr(request.state, "actor", None),
                            action=request.method, target=request.url.path[:500], outcome=None)
        db.add(record)
        db.flush()
        return record.id

def end_audit(record_id, request, status):
    with SessionLocal.begin() as db:
        db.execute(update(AuditEntry).where(AuditEntry.id == record_id).values(
            actor=getattr(request.state, "actor", None), outcome=status))

class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())
        if request.url.path in {"/health", "/ready"} or request.method == "OPTIONS":
            return await call_next(request)
        audit_id = None
        try:
            # Authentication failures are audited too.
            failure = None
            try:
                if request.url.path != "/api/v1/auth/login":
                    await run_in_threadpool(authorize, request)
            except HTTPException as exc:
                failure = exc
            audit_id = await run_in_threadpool(begin_audit, request, request_id)
            if failure:
                response = JSONResponse({"detail": failure.detail}, status_code=failure.status_code)
            else:
                response = await call_next(request)
            await run_in_threadpool(end_audit, audit_id, request, response.status_code)
        except Exception:
            logger.exception("Request failed request_id=%s audit_id=%s", request_id, audit_id)
            if audit_id is not None:
                try:
                    await run_in_threadpool(end_audit, audit_id, request, 500)
                except Exception:
                    logger.error("Audit outcome unavailable request_id=%s", request_id)
            response = JSONResponse({"detail": "Service unavailable", "request_id": request_id}, status_code=503)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
