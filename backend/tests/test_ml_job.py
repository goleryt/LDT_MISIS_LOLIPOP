"""Daily ML batch storage and API read-back, with a fake runtime output (no ML libraries needed)."""
from datetime import date, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ChannelCatalogue
from app.db.platform import MlScore, Prediction
from app.db.session import SessionLocal
from app.ml_job import store_output

D = date(2026, 6, 20)


def gas(channel, score, status="experimental_shadow", reasons=None, day=D, maintenance="unknown"):
    return {
        "bundle": "gas_cross_v3_bundle", "is_primary": True, "model_version": "gas-test-v3",
        "target_code": "gas_threshold_cross_1pct_d2_proxy_v3", "incident_type": "gas_threshold_cross",
        "score": score, "score_kind": "proxy_score", "evidence_level": "E1", "decision_status": status,
        "reason_codes": reasons or [], "window_start": (day + timedelta(days=2)).isoformat(),
        "window_end_exclusive": (day + timedelta(days=3)).isoformat(),
        "ид_канала_данных": str(channel), "ид_объект": "1", "maintenance_context": maintenance,
    }


def output(records, day=D, incidents=()):
    return {"as_of_date": day.isoformat(), "request_id": f"daily-{day}", "primary_gas": "gas_cross_v3_bundle",
            "gas": list(records), "incidents": list(incidents), "maintenance_context": []}


def settings(top_k=2, cooldown=3):
    return get_settings().model_copy(update={"ml_top_k_per_day": top_k, "ml_cooldown_days": cooldown})


def add_channels():
    with SessionLocal.begin() as db:
        db.add_all([ChannelCatalogue(ид_канала_данных=i, ид_объект=1, название_датчика=f"Газ {i}") for i in (2, 3, 4, 5)])


def run(records, day=D, **kw):
    with SessionLocal.begin() as db:
        return store_output(db, output(records, day), settings(**kw))


def test_top_k_selection_and_predictions():
    add_channels()
    summary = run([gas(1, 0.10), gas(2, 0.50), gas(3, 0.30), gas(4, 0.01),
                   gas(5, None, "abstain", ["ABOVE_THRESHOLD_AT_D"]),
                   gas(9, None, "abstain", ["NOT_GAS_STREAM"])])
    assert summary["gas_rows"] == 5  # NOT_GAS_STREAM is dropped, other abstentions are kept
    assert summary["alerts_selected"] == 2 and summary["predictions_created"] == 2
    with SessionLocal() as db:
        selected = db.scalars(select(MlScore).where(MlScore.selected.is_(True)).order_by(MlScore.rank)).all()
        assert [(r.channel_id, r.rank) for r in selected] == [(2, 1), (3, 2)]
        abstain = db.scalar(select(MlScore).where(MlScore.channel_id == 5))
        assert abstain.score is None and abstain.reason_codes == ["ABOVE_THRESHOLD_AT_D"] and not abstain.selected
        predictions = db.scalars(select(Prediction).order_by(Prediction.id)).all()
        assert [p.channel_id for p in predictions] == [2, 3]
        first = predictions[0]
        assert first.incident_type == "gas_threshold_cross" and first.horizon_hours == 24
        assert first.predicted_for == first.calculated_at + timedelta(hours=24)
        assert first.recommendation is None and first.status == "new"


def test_rerun_replaces_the_day_without_duplicates():
    add_channels()
    run([gas(1, 0.4), gas(2, 0.2)])
    run([gas(1, 0.4), gas(2, 0.2)])
    with SessionLocal() as db:
        assert len(db.scalars(select(MlScore)).all()) == 2
        assert len(db.scalars(select(Prediction)).all()) == 2


def test_cooldown_skips_recently_alerted_channels():
    add_channels()
    run([gas(1, 0.9), gas(2, 0.1)], day=D, top_k=1)
    run([gas(1, 0.9, day=D + timedelta(days=1)), gas(2, 0.1, day=D + timedelta(days=1))],
        day=D + timedelta(days=1), top_k=1)
    with SessionLocal() as db:
        chosen = db.scalars(select(MlScore).where(MlScore.selected.is_(True)).order_by(MlScore.as_of_date)).all()
        assert [(r.as_of_date, r.channel_id) for r in chosen] == [(D, 1), (D + timedelta(days=1), 2)]


def test_sensors_endpoint_reads_the_stored_result(login):
    run([gas(1, 0.42, maintenance="possible_recent_silence")])
    client = login("dispatcher")
    sensor = client.get("/api/v1/objects/1/sensors").json()["sensors"][0]
    assert sensor["risk_score"] == 0.42 and sensor["risk_is_alert_candidate"] is True
    assert sensor["risk_decision_status"] == "experimental_shadow"
    assert sensor["risk_maintenance_context"] == "possible_recent_silence"
    assert sensor["risk_window_start"] == "2026-06-22" and sensor["risk_as_of_date"] == "2026-06-20"


def test_sensor_without_result_has_no_risk(login):
    sensor = login("dispatcher").get("/api/v1/objects/1/sensors").json()["sensors"][0]
    assert sensor["risk_score"] is None and sensor["risk_reason_codes"] == []


def test_prediction_status_reflects_the_last_run(login):
    client = login("dispatcher")
    assert client.get("/api/v1/predictions/status").json()["available"] is False
    run([gas(1, 0.2)])
    body = client.get("/api/v1/predictions/status").json()
    assert body["available"] is True and body["as_of_date"] == "2026-06-20" and body["model_version"] == "gas-test-v3"
