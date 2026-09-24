from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from app.api.v1 import alarms, events, imports, map, objects, requests, sensors, auth, platform, integrations, predictions, geo
from app.core.config import get_settings
from app.core.middleware import SecurityMiddleware
from app.db.session import engine
from app.api.v1 import reports

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
for module in (map, objects, sensors, alarms, events, requests, imports, auth, platform, integrations, predictions, geo):
    app.include_router(module.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.add_middleware(SecurityMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "PUT", "OPTIONS"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts.split(","))

@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}

@app.get("/ready", tags=["system"])
def readiness():
    try:
        with engine.connect() as db:
            if db.scalar(text("SELECT version_num FROM alembic_version")) != "5e192ace0042":
                raise ValueError("Schema migration required")
    except Exception:
        raise HTTPException(503, "Database not ready") from None
    return {"status": "ready"}
