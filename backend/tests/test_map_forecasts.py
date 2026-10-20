"""Map projection is read-only; recorded real inference values stay unmodified."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from sqlalchemy import func, select
from app.core.config import get_settings
from app.db.models import ChannelCatalogue, EventsJournal, PreventiveRequest
from app.db.platform import MlScore, ScenarioRun, ScenarioForecast, Prediction
from app.db.session import SessionLocal
from app.scenario_job import store_validated

ACTUAL = json.loads(Path(__file__).with_name('fixtures').joinpath('combined_actual_numeric.json').read_text(encoding='utf8'))


def scenario():
    with SessionLocal.begin() as db:
        db.add(ChannelCatalogue(ид_канала_данных=2, ид_объект=1, тип_датчика='Дымовой'))
        run = ScenarioRun(as_of_date=date(2025,8,15), revision=1, fingerprint='a'*64,
            snapshot_version='recorded-supplier-inference', snapshot={'gas':None},
            versions={'enabled':{'sensor_failure':True,'fire':True}}, state='running')
        db.add(run); db.flush(); store_validated(db, run, deepcopy(ACTUAL)); db.flush()
        return run.id


def test_map_forecasts_requires_auth_and_empty_is_not_zero(client, login):
    assert client.get('/api/v1/map/forecasts').status_code == 401
    login('manager')
    result = client.get('/api/v1/map/forecasts').json()
    assert result['forecasts'] == []
    assert result['automated_action_allowed'] is False


def test_all_saved_scenario_scores_visible_without_threshold_selection(client, login, monkeypatch):
    monkeypatch.setattr(get_settings(), 'scenario_enabled', True)
    monkeypatch.setattr(get_settings(), 'scenario_sensor_enabled', True)
    monkeypatch.setattr(get_settings(), 'scenario_fire_enabled', True)
    scenario(); login('manager')
    data = client.get('/api/v1/map/forecasts').json()
    rows = data['forecasts']
    assert len(rows) == 3 and all(r['bound'] and r['available'] for r in rows)
    assert {r['worker'] for r in rows} == {'sensor_failure','fire'}
    assert sorted(r['score'] for r in rows) == sorted(r['score'] for r in ACTUAL['evidence_context']['forecasts'])
    assert all('scenarioRun=' in r['detail_url'] and 'scenarioId=' in r['detail_url'] for r in rows)
    with SessionLocal() as db:
        for table in (Prediction, EventsJournal, PreventiveRequest):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_unbound_and_disabled_never_leak_a_numeric_score(client, login, monkeypatch):
    monkeypatch.setattr(get_settings(), 'scenario_enabled', False)
    scenario(); login()
    rows = client.get('/api/v1/map/forecasts').json()['forecasts']
    assert all(not r['available'] and r['score'] is None for r in rows)
    assert all(r['availability_reason']=='MODULE_DISABLED' for r in rows)
    monkeypatch.setattr(get_settings(), 'scenario_enabled', True)
    with SessionLocal.begin() as db:
        row = db.scalar(select(ScenarioForecast).limit(1)); row.object_id = None
    unbound = next(r for r in client.get('/api/v1/map/forecasts').json()['forecasts'] if not r['bound'])
    assert not unbound['available'] and unbound['score'] is None
    assert unbound['availability_reason']=='UNBOUND_CHANNEL'


def test_latest_failed_snapshot_does_not_show_previous_success(client, login):
    scenario()
    with SessionLocal.begin() as db:
        db.add(ScenarioRun(as_of_date=date(2025,8,16), revision=1, fingerprint='b'*64,
            snapshot_version='failed-new-source', snapshot={}, versions={}, state='failed'))
    login()
    data = client.get('/api/v1/map/forecasts').json()
    assert data['scenario_run']['state'] == 'failed'
    assert data['forecasts'] == []


def test_nonselected_gas_and_abstain_visible_latest_revision_only(client, login):
    # A recorded public gas output, not a newly fabricated demonstration result.
    score = 0.00830046623911187
    with SessionLocal.begin() as db:
        for d, value, status in [(date(2026,9,27),score,'experimental_shadow'),
                (date(2026,9,28),score,'experimental_shadow')]:
            db.add(MlScore(as_of_date=d,run_id=f'{d}',kind='gas',bundle='gas_cross_v3',
                object_id=1,channel_id=1,score=value,score_kind='proxy_score',decision_status=status,
                selected=False,payload={},window_start=date(2026,9,30),window_end_exclusive=date(2026,10,1)))
        db.add(MlScore(as_of_date=date(2026,9,28),run_id='abstain',kind='gas',bundle='gas_cross_v3',
            object_id=1,channel_id=None,score=None,decision_status='abstain',reason_codes=['INSUFFICIENT_HISTORY'],payload={}))
    login()
    rows = client.get('/api/v1/map/forecasts').json()['forecasts']
    assert len(rows) == 2
    available = next(r for r in rows if r['available'])
    assert available['score'] == score and available['queue_selected'] is False
    missing = next(r for r in rows if not r['available'])
    assert missing['score'] is None and missing['reason'] == ['INSUFFICIENT_HISTORY']
