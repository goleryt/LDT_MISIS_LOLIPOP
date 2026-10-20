"""A demo preparation command is read-only unless the operator opts into writes."""
from datetime import datetime, timedelta
import pytest
from app.core.config import get_settings
from app.scenario_job import ScenarioError, TZ
from scripts import prepare_final_demo as final
from scripts import publish_synthetic_scenario_demo as demo
from scripts.final_demo_inputs import export_gas_inputs


def test_inventory_target_refuses_unknown_database_or_environment(monkeypatch):
    with pytest.raises(RuntimeError,match='IDENTITY'): final.verify_target('unidentified_database')
    monkeypatch.setenv('ENVIRONMENT','development')
    with pytest.raises(RuntimeError,match='IDENTIFIED'): final.verify_target('ldt_test')
    monkeypatch.setenv('ENVIRONMENT','production')
    monkeypatch.delenv('RAILWAY_PROJECT_ID',raising=False)
    with pytest.raises(RuntimeError,match='UNKNOWN_PUBLIC'): final.verify_target('ldt_test')


def test_empty_inventory_has_no_invented_forecasts_or_deletions():
    final.verify_target('ldt_test')
    result=final.inventory()
    assert result['gas']==[] and result['scenarios']==[]
    assert not result['new_inference_performed'] and not result['deletion_performed']
    assert not result['operational_events_written']
    assert result['dataset_version']=='final-demo-2026-10-v1'


def test_gas_publication_requires_separate_explicit_opt_in(monkeypatch):
    monkeypatch.delenv('PUBLISH_FINAL_GAS_DEMO',raising=False)
    with pytest.raises(RuntimeError,match='EXPLICIT_GAS'):final.publish_gas()


def test_fixed_snapshot_never_accepts_an_unclosed_day(monkeypatch):
    for k,v in {'PUBLISH_SYNTHETIC_SCENARIO_DEMO':'synthetic-input-only',
            'RAILWAY_PROJECT_ID':demo.PROJECT,'RAILWAY_ENVIRONMENT_ID':demo.ENVIRONMENT}.items():monkeypatch.setenv(k,v)
    settings=get_settings().model_copy(update={'scenario_enabled':True})
    with pytest.raises(ScenarioError,match='CLOSED_DAY'):
        demo.publish(settings=settings,as_of_date=datetime.now(TZ).date()+timedelta(days=1))


def test_original_gas_inputs_are_fixed_idempotent_and_never_overwrite_unknown_files(tmp_path):
    import csv
    first=export_gas_inputs(tmp_path)
    assert first==export_gas_inputs(tmp_path)
    assert first['rows']==3870 and first['observed_days']==430
    with (tmp_path/'synthetic-demo-journal-20260928.csv').open(encoding='utf8',newline='') as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==3870 and len({r['дата'] for r in rows})==430
    assert set(r['ид_канала_данных'] for r in rows)=={'900000001','900000002','900000003'}
    assert max(r['дата'] for r in rows)=='2026-09-28'
    assert not first['scores_generated'] and not first['new_inference_performed']
    (tmp_path/'synthetic-demo-catalogue.csv').write_text('Unknown user data',encoding='utf8')
    with pytest.raises(RuntimeError,match='COLLISION'):export_gas_inputs(tmp_path)
