from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.imports import router as imports_router
from app.api.v1.map import router as map_router
from app.core.config import get_settings


settings = get_settings()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.include_router(
    map_router,
    prefix="/api/v1",
)

app.include_router(
    imports_router,
    prefix="/api/v1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}