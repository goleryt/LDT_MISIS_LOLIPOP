from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.alarms import router as alarms_router
from app.api.v1.events import router as events_router
from app.api.v1.imports import router as imports_router
from app.api.v1.map import router as map_router
from app.api.v1.objects import router as objects_router
from app.api.v1.requests import router as requests_router
from app.api.v1.sensors import router as sensors_router
from app.core.config import get_settings


settings = get_settings()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        settings.cors_origin_list
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    map_router,
    prefix="/api/v1",
)
app.include_router(
    objects_router,
    prefix="/api/v1",
)
app.include_router(
    sensors_router,
    prefix="/api/v1",
)
app.include_router(
    alarms_router,
    prefix="/api/v1",
)
app.include_router(
    events_router,
    prefix="/api/v1",
)
app.include_router(
    requests_router,
    prefix="/api/v1",
)
app.include_router(
    imports_router,
    prefix="/api/v1",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
