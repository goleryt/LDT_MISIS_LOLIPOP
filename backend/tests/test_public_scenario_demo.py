"""Operator-tool boundaries; real model execution is verified in isolated Docker."""
from datetime import date
import json
import pytest
from sqlalchemy import func, select
from app.core.config import get_settings
from app.db.models import ObjectCatalogue, EventsJournal, PreventiveRequest
from app.db.platform import ScenarioRun
from app.db.session import SessionLocal
from app.scenario_job import ScenarioError
from scripts import publish_synthetic_scenario_demo as demo


def fixture_root(tmp_path):
    (tmp_path/'catalogue.csv').write_text('ид_канала_данных,ид_объект,тип_датчика\na,o,Дым\n',encoding='utf8')
    (tmp_path/'journal.csv').write_text('ид_канала_данных,дата,время,тревожное\na,2025-08-15,12:00:00,true\n',encoding='utf8')
    (tmp_path/'coverage.json').write_text(json.dumps({'start':'2025-07-14','end_exclusive':'2025-08-16'}))
    return tmp_path


def opt_in(monkeypatch):
    for key,value in {'PUBLISH_SYNTHETIC_SCENARIO_DEMO':'synthetic-input-only',
        'RAILWAY_PROJECT_ID':demo.PROJECT,'RAILWAY_ENVIRONMENT_ID':demo.ENVIRONMENT}.items():
        monkeypatch.setenv(key,value)


@pytest.mark.parametrize('missing',['PUBLISH_SYNTHETIC_SCENARIO_DEMO','RAILWAY_PROJECT_ID','RAILWAY_ENVIRONMENT_ID'])
def test_operator_requires_explicit_target_and_acceptance(monkeypatch,missing):
    opt_in(monkeypatch);monkeypatch.delenv(missing)
    with pytest.raises(ScenarioError,match='EXPLICIT_PUBLIC_DEMO_ACCEPTANCE_REQUIRED'):
        demo.require_opt_in(get_settings().model_copy(update={'scenario_enabled':True}))


def test_operator_respects_master_and_production_guard(monkeypatch):
    opt_in(monkeypatch)
    for updates in [{'scenario_enabled':False},
        {'scenario_enabled':True,'environment':'production','scenario_allow_production':False}]:
        with pytest.raises(ScenarioError):demo.require_opt_in(get_settings().model_copy(update=updates))


def test_fixture_translation_preserves_observations_and_marks_provenance(tmp_path):
    snapshot=demo.build_snapshot(fixture_root(tmp_path),date(2026,10,18))
    assert len(snapshot['journal'])==1
    assert snapshot['journal'][0]['дата']=='2026-10-18'
    assert snapshot['journal'][0]['тревожное']=='true'
    assert snapshot['coverage']=={'start':'2026-09-16','end_exclusive':'2026-10-19'}
    assert snapshot['catalogue'][0]['ид_объект']==str(demo.OBJECT_ID)
    assert snapshot['provenance']['operational_observations_written'] is False
    assert snapshot['gas'] is None
    assert snapshot==demo.build_snapshot(tmp_path,date(2026,10,18))


def test_catalogue_creation_is_additive_and_rejects_existing_ids(tmp_path):
    snapshot=demo.build_snapshot(fixture_root(tmp_path),date(2026,10,18))
    with SessionLocal.begin() as db:
        db.add(ObjectCatalogue(ид_объект=demo.OBJECT_ID,диспетчерское_название_объекта='Existing user object'))
    with pytest.raises(ScenarioError,match='DEMO_CATALOGUE_ID_COLLISION'):
        with SessionLocal.begin() as db:demo.ensure_catalogue(db,snapshot)
    with SessionLocal() as db:
        assert db.get(ObjectCatalogue,demo.OBJECT_ID).диспетчерское_название_объекта=='Existing user object'
        assert db.scalar(select(func.count()).select_from(EventsJournal))==0


def test_runtime_failure_leaves_no_catalogue_forecasts_or_requests(monkeypatch,tmp_path):
    opt_in(monkeypatch);root=fixture_root(tmp_path);script=tmp_path/'runtime.py';script.write_text('# boundary fixture')
    settings=get_settings().model_copy(update={'scenario_enabled':True,'scenario_compute_script':str(script)})
    def fail(*args):raise ScenarioError('SCENARIO_RUNTIME_TIMEOUT')
    monkeypatch.setattr(demo,'invoke_runtime',fail)
    with pytest.raises(ScenarioError,match='TIMEOUT'):demo.publish(root=root,settings=settings)
    with SessionLocal() as db:
        assert db.get(ObjectCatalogue,demo.OBJECT_ID) is None
        for table in (ScenarioRun,EventsJournal,PreventiveRequest):
            assert db.scalar(select(func.count()).select_from(table))==0
