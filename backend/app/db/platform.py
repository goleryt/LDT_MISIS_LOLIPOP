"""Operational tables; forecast rows are written only by a real provider."""
from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(120), primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[str] = mapped_column(String(20), default="local")

class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(ForeignKey("users.username", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class AuditEntry(Base):
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[str | None] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(500))
    outcome: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class ObjectLocation(Base):
    __tablename__ = "object_locations"
    __table_args__ = (CheckConstraint("longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90"),)
    object_id: Mapped[int] = mapped_column(ForeignKey("object_catalogue.ид_объект"), primary_key=True)
    longitude: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)

class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (CheckConstraint("probability >= 0 AND probability <= 1"), CheckConstraint("horizon_hours >= 24"), UniqueConstraint("model_version", "provider_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(200))
    object_id: Mapped[int] = mapped_column(ForeignKey("object_catalogue.ид_объект"), index=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channel_catalogue.ид_канала_данных"))
    incident_type: Mapped[str] = mapped_column(String(50))
    probability: Mapped[float] = mapped_column(Float)
    horizon_hours: Mapped[int] = mapped_column(Integer)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_version: Mapped[str] = mapped_column(String(100))
    recommendation: Mapped[str | None] = mapped_column(Text)
    ml_metadata: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="new")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    actual_outcome: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("preventive_requests.id"))

class PredictionDecision(Base):
    __tablename__ = "prediction_decisions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    actual_outcome: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[int | None] = mapped_column(BigInteger)
    reference_id: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class NotificationRead(Base):
    __tablename__ = "notification_reads"
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"), primary_key=True)
    username: Mapped[str] = mapped_column(ForeignKey("users.username"), primary_key=True)

class IntegrationRecord(Base):
    __tablename__ = "integration_records"
    __table_args__ = (UniqueConstraint("source", "kind", "external_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class IntegrationCursor(Base):
    __tablename__ = "integration_cursors"
    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))


class MlScore(Base):
    """One runtime record of the daily ML batch (LCT_ML_backend_v1), stored as delivered.

    `score` is a proxy score, not the probability of a fire or a confirmed incident;
    the meaning is carried by `target_code`, `score_kind`, `evidence_level` and
    `decision_status` from the bundle itself. Results are immutable per day/revision; prior decisions are retained.
    """
    __tablename__ = "ml_scores"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    run_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # gas | incident
    bundle: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(200))
    target_code: Mapped[str | None] = mapped_column(String(100))
    object_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    incident_type: Mapped[str | None] = mapped_column(String(50))
    score: Mapped[float | None] = mapped_column(Float)
    score_kind: Mapped[str | None] = mapped_column(String(50))
    evidence_level: Mapped[str | None] = mapped_column(String(10))
    decision_status: Mapped[str | None] = mapped_column(String(40))
    reason_codes: Mapped[list | None] = mapped_column(JSON)
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end_exclusive: Mapped[date | None] = mapped_column(Date)
    maintenance_context: Mapped[str | None] = mapped_column(String(40))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)  # top-K/day after cooldown
    rank: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MlRun(Base):
    __tablename__ = "ml_runs"
    __table_args__ = (UniqueConstraint("as_of_date", "revision"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20))
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
