"""Future model boundary. No heuristic, random, zero-probability or demo inference fallback."""
from datetime import timedelta
from typing import Literal, Protocol
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

class PredictionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    provider_id: str = Field(min_length=1, max_length=200)
    object_id: int = Field(ge=1)
    channel_id: int | None = Field(None, ge=1)
    incident_type: Literal["fire", "intrusion", "flood", "sensor_failure", "system_failure", "gas_threshold_cross"]
    probability: float = Field(ge=0, le=1)
    horizon_hours: int = Field(ge=24)
    calculated_at: AwareDatetime
    predicted_for: AwareDatetime
    model_version: str = Field(min_length=1, max_length=100)
    recommendation: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def horizon_matches(self):
        if self.predicted_for != self.calculated_at + timedelta(hours=self.horizon_hours):
            raise ValueError("predicted_for must equal calculated_at + horizon_hours")
        return self

class ModelUnavailable(RuntimeError):
    pass

class PredictionProvider(Protocol):
    def predict(self, object_id: int) -> list[PredictionResult]: ...

class UnconfiguredProvider:
    def predict(self, object_id: int) -> list[PredictionResult]:
        raise ModelUnavailable("Расчёт по запросу не поддерживается: прогнозы считаются раз в сутки (scripts.run_ml_daily)")

def get_provider() -> PredictionProvider:
    # Replace this factory only when the real model and its input contract are available.
    return UnconfiguredProvider()
