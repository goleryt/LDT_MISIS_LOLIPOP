from typing import Literal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.config import get_settings
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.api.v1.platform import serialize
from app.api.v1.requests import validate_target
from app.db.models import PreventiveRequest
from app.db.platform import MlRun, MlScore, Notification, Prediction, PredictionDecision
from app.db.session import SessionLocal
from app.predictions import ModelUnavailable, PredictionResult, get_provider

router = APIRouter(prefix="/predictions", tags=["predictions"])
REASONS = {"inspection": "Проверка на месте", "telemetry": "Показания датчиков",
           "planned_work": "Плановые работы", "equipment_fault": "Неисправность оборудования",
           "external_verification": "Внешняя проверка"}

class InferenceInput(BaseModel):
    object_id: int = Field(ge=1)

class DecisionInput(BaseModel):
    revision: int = Field(ge=1)
    decision: Literal["confirmed", "false_alarm", "monitoring", "dispatch", "closed"]
    reason: Literal["inspection", "telemetry", "planned_work", "equipment_fault", "external_verification"]
    notes: str | None = Field(None, max_length=4000)
    actual_outcome: str | None = Field(None, max_length=4000)

@router.get("/status")
def status():
    with SessionLocal() as db:
        last = db.scalar(select(func.max(MlScore.as_of_date)))
        model = db.scalar(select(MlScore.model_version).where(MlScore.kind == "gas").order_by(MlScore.as_of_date.desc()).limit(1))
    if last is None:
        return {"available": False, "state": "no_ml_run_yet",
                "message": "ML-пакет подключён, но суточный расчёт ещё не выполнялся (scripts.run_ml_daily)."}
    today = datetime.now(ZoneInfo(get_settings().source_timezone)).date()
    return {"available": True, "stale": last < today - timedelta(days=1), "state": "experimental_shadow", "as_of_date": last.isoformat(), "model_version": model,
            "message": "Экспериментальный shadow-режим: оценка наблюдаемого пересечения газом 1 % в окне прогноза. "
                       "Это не вероятность пожара и не подтверждённый инцидент."}

@router.get("/runs")
def runs(limit: int = Query(30, ge=1, le=100)):
    with SessionLocal() as db:
        return [serialize(row) for row in db.scalars(select(MlRun).order_by(MlRun.id.desc()).limit(limit))]

@router.get("/reasons")
def reasons():
    return REASONS

@router.get("")
def list_predictions(after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        return [serialize(x) for x in db.scalars(select(Prediction).where(Prediction.id > after_id).order_by(Prediction.id).limit(limit))]

@router.post("/inference")
def inference(payload: InferenceInput):
    with SessionLocal() as db:
        validate_target(db, object_id=payload.object_id, channel_id=None)
    try:
        results = get_provider().predict(payload.object_id)
    except ModelUnavailable as exc:
        raise HTTPException(503, {"code": "model_not_configured", "message": str(exc)}) from None
    # This path is unreachable until a real provider is connected. Validate before persisting.
    validated = [PredictionResult.model_validate(x) for x in results]
    with SessionLocal.begin() as db:
        saved = []
        for item in validated:
            if item.object_id != payload.object_id:
                raise HTTPException(502, "Provider returned another object's prediction")
            validate_target(db, object_id=item.object_id, channel_id=item.channel_id)
            existing = db.scalar(select(Prediction).where(Prediction.model_version == item.model_version,
                                                         Prediction.provider_id == item.provider_id))
            if existing:
                saved.append(serialize(existing))
                continue
            row = Prediction(**item.model_dump())
            db.add(row)
            db.flush()
            db.add(Notification(kind="prediction", object_id=row.object_id, reference_id=row.id,
                                message=f"Новый прогноз: {row.incident_type}, объект {row.object_id}"))
            saved.append(serialize(row))
        return saved

@router.get("/{prediction_id}")
def detail(prediction_id: int):
    with SessionLocal() as db:
        row = db.get(Prediction, prediction_id)
        if not row:
            raise HTTPException(404, "Prediction not found")
        return {**serialize(row), "decisions": [serialize(x) for x in db.scalars(
            select(PredictionDecision).where(PredictionDecision.prediction_id == prediction_id).order_by(PredictionDecision.id))]}

@router.patch("/{prediction_id}/decision")
def decision(prediction_id: int, payload: DecisionInput, request: Request):
    with SessionLocal.begin() as db:
        row = db.scalar(select(Prediction).where(Prediction.id == prediction_id).with_for_update())
        if not row:
            raise HTTPException(404, "Prediction not found")
        if row.revision != payload.revision or row.status == "closed":
            raise HTTPException(409, "Prediction changed or is already closed; reload it")
        if payload.decision == "closed" and not (payload.actual_outcome or "").strip():
            raise HTTPException(422, "Closing requires an actual outcome")
        row.status, row.revision = payload.decision, row.revision + 1
        if payload.actual_outcome is not None:
            row.actual_outcome = payload.actual_outcome
        db.add(PredictionDecision(prediction_id=row.id, actor=request.state.principal.username,
                                 **payload.model_dump(exclude={"revision"})))
        return serialize(row)

@router.post("/{prediction_id}/request")
def draft_request(prediction_id: int):
    with SessionLocal.begin() as db:
        row = db.scalar(select(Prediction).where(Prediction.id == prediction_id).with_for_update())
        if not row:
            raise HTTPException(404, "Prediction not found")
        if row.request_id:
            return {"request_id": row.request_id}
        if row.status in {"closed", "false_alarm"}:
            raise HTTPException(409, "Prediction is closed or marked false")
        if not row.recommendation:
            raise HTTPException(409, "The real model supplied no recommendation")
        target = PreventiveRequest(object_id=row.object_id, channel_id=row.channel_id,
                title=f"Проверка прогноза №{row.id}", description=row.recommendation, priority="medium", status="new")
        db.add(target)
        db.flush()
        row.request_id = target.id
        row.revision += 1
        return {"request_id": target.id}
