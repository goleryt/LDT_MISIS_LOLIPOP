"""Storage contract fixtures only, never production inference or reported model quality."""
from copy import deepcopy
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from app.db.platform import MlRun, MlScore, Prediction, Notification
from app.db.session import SessionLocal
from app.ml_job import MlJobError, store_output, run_daily
from test_ml_job import gas, output, settings, D

def test_changed_output_requires_new_revision_and_preserves_history():
    first = output([gas(1, 0.2)])
    with SessionLocal.begin() as db: store_output(db, first, settings())
    changed = deepcopy(first)
    changed['gas'][0]['maintenance_context'] = 'possible_recent_silence'
    with pytest.raises(MlJobError, match='DAY_ALREADY_EXISTS'):
        with SessionLocal.begin() as db: store_output(db, changed, settings())
    with SessionLocal.begin() as db: store_output(db, changed, settings(), revision=2)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MlRun)) == 2
        assert db.scalar(select(func.count()).select_from(MlScore)) == 2
        assert db.scalar(select(func.count()).select_from(Prediction)) == 2
        assert db.scalar(select(func.count()).select_from(Notification)) == 0

def test_window_and_manual_advisory_come_from_runtime():
    row = gas(1, 0.2)
    row.update(window_start=str(D + timedelta(days=4)), window_end_exclusive=str(D + timedelta(days=5)),
               recommendation={'text_ru':'Check telemetry manually', 'automated_action_allowed':False})
    with SessionLocal.begin() as db: store_output(db, output([row]), settings())
    with SessionLocal() as db:
        forecast = db.scalar(select(Prediction))
        assert forecast.horizon_hours == 72
        assert forecast.recommendation == 'Check telemetry manually'
        assert forecast.ml_metadata['window_start'] == str(D + timedelta(days=4))

@pytest.mark.parametrize('field,value', [('score',1.1),('ид_объект','999'),('window_start',str(D)),('label_source','stub')])
def test_bad_contract_never_persists(field,value):
    record = gas(1, 0.2)
    record[field] = value
    with pytest.raises(MlJobError):
        with SessionLocal.begin() as db: store_output(db, output([record]), settings())
    with SessionLocal() as db: assert db.scalar(select(func.count()).select_from(Prediction)) == 0

def test_run_requires_completed_etl_marker():
    with pytest.raises(MlJobError, match='DAY_NOT_CERTIFIED_READY'):
        run_daily(D, settings=settings())

def test_duplicate_channel_rejected():
    with pytest.raises(MlJobError, match='DUPLICATE_GAS_CHANNEL'):
        with SessionLocal.begin() as db: store_output(db, output([gas(1,0.2),gas(1,0.2)]), settings())

def test_runs_endpoint_exposes_summary_not_raw_inputs(login):
    with SessionLocal.begin() as db: store_output(db, output([gas(1,0.2)]), settings())
    body = login('manager').get('/api/v1/predictions/runs').json()
    assert body[0]['state'] == 'completed'
    assert body[0]['summary']['predictions_created'] == 1
