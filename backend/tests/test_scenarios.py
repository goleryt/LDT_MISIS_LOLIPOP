"""Transport/storage regressions using recorded REAL inference on synthetic inputs.

The fixture is produced by ml_combined/acceptance.py, never a hand-written score.
Mutations below are deliberately invalid contract inputs, not demonstration data.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import pytest
from sqlalchemy import func, select
from app.core.config import get_settings, Settings
from app.db.models import ChannelCatalogue, PreventiveRequest
from app.db.platform import AuditEntry, Notification, Prediction, MlScore, ScenarioForecast, ScenarioRun
from app.db.session import SessionLocal
from app import scenario_job as job

ACTUAL=json.loads(Path(__file__).with_name('fixtures').joinpath('combined_actual_numeric.json').read_text(encoding='utf8'))


def save_actual(db, *, version='original', day=date(2025,8,15)):
    run=ScenarioRun(as_of_date=day,revision=1,fingerprint=job.digest(version),snapshot_version=version,
        snapshot={'gas':None},versions={'enabled':{'sensor_failure':True,'fire':True}},state='running')
    db.add(ChannelCatalogue(ид_канала_данных=2,ид_объект=1,тип_датчика='Дымовой'))
    db.add(run);db.flush();job.store_validated(db,run,deepcopy(ACTUAL));db.flush()
    return run.id


def test_real_outputs_are_separate_and_never_create_alarms_requests_or_gas():
    with SessionLocal.begin() as db:
        run_id=save_actual(db)
        rows=db.scalars(select(ScenarioForecast)).all()
        assert len(rows)==3
        assert {r.worker for r in rows}=={'sensor_failure','fire'}
        assert all(r.payload['score_kind']=='scenario_score' for r in rows)
        assert db.get(ScenarioRun,run_id).output==ACTUAL
        for table in (PreventiveRequest,Notification,Prediction,MlScore):
            assert db.scalar(select(func.count()).select_from(table))==0


@pytest.mark.parametrize('change', ['version','date','score','nan','threshold','window','auto','duplicate','gas'])
def test_reject_invalid_combined_before_commit(change):
    output=deepcopy(ACTUAL);row=output['evidence_context']['forecasts'][0]
    if change=='version':row['model_version']='unregistered'
    if change=='date':row['cutoff']='2025-08-14'
    if change=='score':row['score']=1.1
    if change=='nan':row['score']=float('nan')
    if change=='threshold':row['threshold']=0.1
    if change=='window':row['window_start']='2025-08-17T00:00:00+03:00'
    if change=='auto':output['evidence_context']['automated_action_allowed']=True
    if change=='duplicate':output['evidence_context']['forecasts'].append(deepcopy(row))
    if change=='gas':output['gas']=[{'unexpected':'replacement'}]
    with pytest.raises((ValueError,job.ScenarioError)):
        with SessionLocal.begin() as db:
            run=ScenarioRun(as_of_date=date(2025,8,15),revision=1,fingerprint='f'*64,snapshot_version='invalid',
                snapshot={'gas':None},versions={'enabled':{'fire':True,'sensor_failure':True}},state='running')
            db.add(run);db.flush();job.store_validated(db,run,output)
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(ScenarioForecast))==0


def test_binding_failure_is_abstain_never_zero():
    with SessionLocal.begin() as db:
        run=ScenarioRun(as_of_date=date(2025,8,15),revision=1,fingerprint='f'*64,snapshot_version='unbound',
            snapshot={'gas':None},versions={'enabled':{'fire':True,'sensor_failure':True}},state='running')
        db.add(run);db.flush();out=deepcopy(ACTUAL)
        for row in out['evidence_context']['forecasts']:row['object']='unknown'
        job.store_validated(db,run,out);db.flush()
        assert all(not r.payload['eligible'] and r.payload['score'] is None and not r.attention
            for r in db.scalars(select(ScenarioForecast)))


@pytest.mark.parametrize('role,allowed',[('manager',False),('technician',False),('dispatcher',True),('analyst',True),('admin',True)])
def test_scenario_rbac_review_draft_idempotence_history_and_audit(client,login,role,allowed):
    with SessionLocal.begin() as db:run_id=save_actual(db)
    assert client.get('/api/v1/predictions/scenarios').status_code==401
    login(role)
    data=client.get('/api/v1/predictions/scenarios').json();assert data['run']['id']==run_id
    row=data['forecasts'][0];base=f"/api/v1/predictions/scenarios/{row['id']}"
    response=client.patch(base+'/decision',json={'revision':1,'decision':'reviewed','notes':'Ручная проверка'})
    assert response.status_code==(200 if allowed else 403)
    if not allowed:return
    assert response.json()['decisions'][0]['actor']==role
    assert client.patch(base+'/decision',json={'revision':1,'decision':'monitoring','notes':'stale'}).status_code==409
    created=client.post(base+'/request');assert created.status_code==200
    assert client.post(base+'/request').json()==created.json()
    request_id=created.json()['request_id']
    request=next(r for r in client.get('/api/v1/requests').json() if r['id']==request_id)
    assert request['status']=='draft'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PreventiveRequest))==1
        audit=db.scalar(select(AuditEntry).where(AuditEntry.entity_type=='scenario_forecast',AuditEntry.outcome==200))
        assert audit.actor==role and audit.role==role
    # Draft confirmation remains separately enforced by the existing request API.
    if role=='analyst':assert client.patch(f'/api/v1/requests/{request_id}',json={'status':'new'}).status_code==403


def test_scenario_flags_csrf_and_production_gate(client,login):
    login('dispatcher');client.headers.pop('X-CSRF-Token')
    assert client.post('/api/v1/predictions/scenarios/1/request').status_code==403
    assert not job.configuration()['enabled']
    with pytest.raises(ValueError):
        Settings(environment='production',secure_cookies=True,postgres_password='test-database-password',scenario_enabled=True)


def test_ready_marker_requires_cutoff_binding_and_no_future_time(tmp_path):
    marker={'as_of_date':'2025-08-15','loaded_at':'2025-08-16T04:00:00+03:00',
        'complete':True,'catalogue_valid_as_of':'2025-08-15','snapshot_version':'verified-v1',
        'coverage':{'start':'2025-07-14','end_exclusive':'2025-08-16'}}
    path=tmp_path/'marker.json';path.write_text(json.dumps(marker))
    now=datetime.fromisoformat('2025-08-16T06:00:00+03:00')
    assert job.read_marker(path,now)==marker
    marker['loaded_at']='2025-08-17T06:00:00+03:00';path.write_text(json.dumps(marker))
    with pytest.raises(job.ScenarioError):job.read_marker(path,now)


def test_same_snapshot_reused_corrected_snapshot_revision_failure_recovery(tmp_path,monkeypatch):
    s=get_settings().model_copy(update={'scenario_enabled':True})
    marker={'as_of_date':'2025-08-15','loaded_at':'2025-08-16T04:00:00+03:00','complete':True,
        'catalogue_valid_as_of':'2025-08-15','snapshot_version':'v1',
        'coverage':{'start':'2025-07-14','end_exclusive':'2025-08-16'}}
    path=tmp_path/'marker.json';path.write_text(json.dumps(marker))
    monkeypatch.setattr(job,'invoke_runtime',lambda *a:deepcopy(ACTUAL))
    with SessionLocal.begin() as db:db.add(ChannelCatalogue(ид_канала_данных=2,ид_объект=1))
    now=datetime.fromisoformat('2025-08-16T06:00:00+03:00')
    first=job.run_scenarios(path,settings=s,now=now)
    second=job.run_scenarios(path,settings=s,now=now)
    assert first['id']==second['id'] and second['reused']
    marker['snapshot_version']='v2';path.write_text(json.dumps(marker))
    monkeypatch.setattr(job,'invoke_runtime',lambda *a:(_ for _ in ()).throw(job.ScenarioError('SCENARIO_RUNTIME_TIMEOUT')))
    with pytest.raises(job.ScenarioError):job.run_scenarios(path,settings=s,now=now)
    assert job.run_scenarios(path,settings=s,now=now)['state']=='failed' # no endless retry
    monkeypatch.setattr(job,'invoke_runtime',lambda *a:deepcopy(ACTUAL))
    recovered=job.run_scenarios(path,settings=s,now=now,retry=True)
    assert recovered['id']!=first['id'] and recovered['state']=='completed'
    with SessionLocal() as db:
        assert len(db.scalars(select(ScenarioRun)).all())==2
        assert len(db.scalars(select(ScenarioForecast)).all())==6
        assert [a['state'] for a in db.get(ScenarioRun,recovered['id']).output['backend_attempt_history']]==['failed','completed']
    with SessionLocal.begin() as db:db.get(ChannelCatalogue,1).название_датчика='Исправленный справочник'
    with pytest.raises(job.ScenarioError,match='SNAPSHOT_CHANGED_REQUIRES_NEW_VERSION'):
        job.run_scenarios(path,settings=s,now=now)


def test_worker_child_environment_excludes_credentials(tmp_path,monkeypatch):
    script=tmp_path/'worker.py';script.write_text('# transport fixture')
    s=get_settings().model_copy(update={'scenario_compute_script':str(script)})
    monkeypatch.setenv('LDAP_BIND_PASSWORD','sentinel-not-a-real-secret')
    def check(cmd,**kwargs):
        assert 'POSTGRES_PASSWORD' not in kwargs['env'] and 'LDAP_BIND_PASSWORD' not in kwargs['env']
        assert kwargs['timeout']==180
        Path(cmd[cmd.index('--output')+1]).write_text('{}')
    monkeypatch.setattr(subprocess,'run',check)
    assert job.invoke_runtime({},datetime.now(timezone.utc).isoformat(),s)=={}
