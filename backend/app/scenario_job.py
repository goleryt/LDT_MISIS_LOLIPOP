"""Independent, opt-in scenario batch. The API never imports ML dependencies."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.models import ChannelCatalogue, EventsJournal, ObjectCatalogue
from app.db.platform import MlRun, MlScore, ScenarioForecast, ScenarioRun
from app.db.session import SessionLocal, engine
from app.ml_job import CATALOGUE_COLUMNS, JOURNAL_COLUMNS
from app.operations import heartbeat

REGISTRY = json.loads(Path(__file__).with_name('scenario_registry.json').read_text())
PACKAGE_SHA = '1afb9615c2526b21f7aa5e9dd0147b82a74777c86b7c5064b6134dcd0366573b'
TZ = ZoneInfo('Europe/Moscow')


class ScenarioError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def configuration(settings=None):
    s = settings or get_settings()
    return {'enabled':s.scenario_enabled,
        'sensor_failure':s.scenario_enabled and s.scenario_sensor_enabled,
        'fire':s.scenario_enabled and s.scenario_fire_enabled,
        'flood':False,'intrusion':False,'system_failure':False,
        'operational_ready':False,'automated_action_allowed':False}


def read_marker(path, now=None):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 16384:
        raise ScenarioError('SCENARIO_DATA_NOT_CERTIFIED')
    marker = json.loads(path.read_text(encoding='utf8'))
    d = date.fromisoformat(marker['as_of_date'])
    stamp = datetime.fromisoformat(marker['loaded_at'])
    current = now or datetime.now(TZ)
    if (stamp.tzinfo is None or stamp > current or stamp < datetime.combine(d+timedelta(days=1),time(),TZ)
        or d >= current.astimezone(TZ).date() or marker.get('complete') is not True
        or marker.get('catalogue_valid_as_of') != d.isoformat()
        or not isinstance(marker.get('snapshot_version'),str) or not 1 <= len(marker['snapshot_version']) <= 120):
        raise ScenarioError('SCENARIO_DATA_NOT_CERTIFIED')
    start = date.fromisoformat(marker['coverage']['start'])
    end = date.fromisoformat(marker['coverage']['end_exclusive'])
    if start >= end or end != d+timedelta(days=1):
        raise ScenarioError('INVALID_COVERAGE')
    return marker


def snapshot_database(db, marker, max_rows):
    d = date.fromisoformat(marker['as_of_date'])
    start = datetime.combine(d-timedelta(days=32),time())
    end = datetime.combine(d+timedelta(days=1),time())
    events = db.execute(select(EventsJournal).where(EventsJournal.d_event_time >= start,
        EventsJournal.d_event_time < end).order_by(EventsJournal.d_event_time,EventsJournal.id).limit(max_rows+1)).scalars().all()
    if len(events) > max_rows:
        raise ScenarioError('SCENARIO_SNAPSHOT_ROW_LIMIT')
    journal = []
    for row in events:
        when = row.d_event_time
        journal.append(dict(zip(JOURNAL_COLUMNS,[str(row.ид_события),str(row.ид_канала_данных),
            when.date().isoformat(),when.time().strftime('%H:%M:%S'),
            '' if row.d_alarm is None else str(row.d_alarm).lower(),row.значение_датчика or ''])))
    catalogue = [{c:'' if getattr(row,c) is None else str(getattr(row,c)) for c in CATALOGUE_COLUMNS}
        for row in db.scalars(select(ChannelCatalogue).order_by(ChannelCatalogue.ид_канала_данных))]
    gas_run = db.scalar(select(MlRun).where(MlRun.as_of_date==d,MlRun.state=='completed')
        .order_by(MlRun.revision.desc()).limit(1))
    gas = None; gas_issued = None
    if gas_run and gas_run.finished_at:
        scores = db.scalars(select(MlScore).where(MlScore.as_of_date==d,MlScore.kind=='gas',
            MlScore.run_id.like(f'%:r{gas_run.revision}')).order_by(MlScore.id)).all()
        if scores:
            gas = {'as_of_date':str(d),'gas':[row.payload for row in scores]}
            gas_issued = gas_run.finished_at.isoformat()
    return {'as_of_date':str(d),'snapshot_version':marker['snapshot_version'],
        'coverage':marker['coverage'],'loaded_at':marker['loaded_at'],
        'catalogue_valid_as_of':marker['catalogue_valid_as_of'],'catalogue':catalogue,
        'journal':journal,'gas':gas,'gas_issued_at':gas_issued}


def invoke_runtime(snapshot, issued_at, settings):
    script = Path(settings.scenario_compute_script)
    if not script.is_file():
        raise ScenarioError('SCENARIO_RUNTIME_UNAVAILABLE')
    # The ML child has no database, LDAP, session, Railway or user credentials.
    safe_env = {k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','TMPDIR','LANG'}}
    safe_env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='2',POLARS_MAX_THREADS='2')
    with tempfile.TemporaryDirectory(prefix='scenario_batch_') as tmp:
        tmp = Path(tmp); source = tmp/'input.json'; target = tmp/'output.json'
        source.write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False),encoding='utf8')
        cmd = [sys.executable,str(script),'--input',str(source),'--output',str(target),'--issued-at',issued_at]
        if not settings.scenario_sensor_enabled: cmd.append('--no-sensor')
        if not settings.scenario_fire_enabled: cmd.append('--no-fire')
        try:
            subprocess.run(cmd, env=safe_env, cwd=tmp, timeout=settings.scenario_timeout_seconds,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.TimeoutExpired:
            raise ScenarioError('SCENARIO_RUNTIME_TIMEOUT') from None
        except (OSError,subprocess.CalledProcessError):
            raise ScenarioError('SCENARIO_RUNTIME_FAILED') from None
        if target.stat().st_size > 32*1024*1024:
            raise ScenarioError('SCENARIO_OUTPUT_TOO_LARGE')
        return json.loads(target.read_text(encoding='utf8'),parse_constant=lambda _: (_ for _ in ()).throw(ScenarioError('NONFINITE_OUTPUT')))


def store_validated(db, run, output):
    """Persist only supplied combine_evidence forecasts; raw outputs stay in the run."""
    json.dumps(output,allow_nan=False)
    context = output['evidence_context']
    if (context.get('implementation_version') != 'evidence-combination-v1.1'
        or context.get('automated_action_allowed') is not False
        or context.get('combined_incident_probability') is not None
        or context.get('as_of_date') not in {None,str(run.as_of_date)}
        or output.get('gas',[]) != (run.snapshot.get('gas') or {}).get('gas',[])):
        raise ScenarioError('INVALID_COMBINED_CONTRACT')
    refs = set()
    for source in context['forecasts']:
        if source['worker'] == 'gas': continue  # Existing gas storage/queue is untouched.
        row = dict(source); worker = row['worker']
        if worker not in {'sensor_failure','fire'} or not run.versions['enabled'][worker]:
            raise ScenarioError('UNSUPPORTED_SCENARIO_HEAD')
        if context['workers'].get(worker,{}).get('status')!='available':
            raise ScenarioError('FORECAST_FROM_UNAVAILABLE_WORKER')
        spec = REGISTRY['workers'][worker]
        if row['model_version'] not in spec['model_versions'] or row['cutoff'] != str(run.as_of_date):
            raise ScenarioError('UNSUPPORTED_SCENARIO_VERSION_OR_DATE')
        if row['ref'] in refs: raise ScenarioError('DUPLICATE_SCENARIO_REF')
        refs.add(row['ref'])
        issued = datetime.fromisoformat(row['issued_at'])
        start,end = (datetime.fromisoformat(row[k]) for k in ('window_start','window_end_exclusive'))
        if (issued.tzinfo is None or start != datetime.combine(run.as_of_date+timedelta(days=3),time(),TZ)
            or end != start+timedelta(days=1) or start-issued < timedelta(hours=24)):
            raise ScenarioError('INVALID_SCENARIO_TIME')
        if row['eligible']:
            score = row['score']; threshold = spec['thresholds'][row['model_version']]
            if (type(score) not in {int,float} or not 0<=score<=1 or row['threshold'] != threshold
                or row['warning'] != (score>=threshold) or row['evidence_level']!='E4'
                or row['score_kind']!='scenario_score' or row['label_source']!='synthetic_scenario'):
                raise ScenarioError('INVALID_SCENARIO_SCORE')
        elif row['score'] is not None or row['warning']:
            raise ScenarioError('ABSTAIN_WITH_SCORE')
        # Only confirmed integer catalogue bindings can link application entities.
        obj = db.get(ObjectCatalogue,int(row['object'])) if str(row.get('object','')).isdigit() else None
        ch = db.get(ChannelCatalogue,int(row['channel'])) if str(row.get('channel','')).isdigit() else None
        binding = obj is not None and (worker=='fire' or ch is not None and ch.ид_объект==obj.ид_объект)
        if not binding:
            row.update(eligible=False,score=None,warning=False,data_status='abstained',reason='BINDING_UNAVAILABLE')
        recent = db.scalar(select(ScenarioForecast.id).join(ScenarioRun).where(
            ScenarioForecast.worker==worker,ScenarioForecast.attention.is_(True),
            ScenarioForecast.object_id==(obj.ид_объект if obj else None),
            ScenarioForecast.channel_id==(ch.ид_канала_данных if ch and worker=='sensor_failure' else None),
            ScenarioRun.as_of_date<=run.as_of_date,
            ScenarioRun.as_of_date>=run.as_of_date-timedelta(days=2)).limit(1))
        db.add(ScenarioForecast(run_id=run.id,forecast_ref=row['ref'],worker=worker,
            object_id=obj.ид_объект if obj else None,
            channel_id=ch.ид_канала_данных if ch and worker=='sensor_failure' and binding else None,
            payload=row,attention=bool(row['warning'] and not recent),decisions=[]))
    run.output = output
    run.state = 'completed' if all(context['workers'][n]['status'] in {'available','empty'}
        for n in ('sensor_failure','fire') if run.versions['enabled'][n]) else 'partial'
    run.error_code = None
    run.finished_at = datetime.now(timezone.utc)


def run_scenarios(marker_path, *, settings=None, now=None, retry=False):
    settings = settings or get_settings()
    if not settings.scenario_enabled: raise ScenarioError('SCENARIOS_DISABLED')
    if now is not None and settings.environment != 'test':
        raise ScenarioError('HISTORICAL_REPLAY_REQUIRES_ISOLATED_TEST_ENVIRONMENT')
    marker = read_marker(marker_path,now)
    issued = (now or datetime.now(TZ)).isoformat()
    with engine.connect() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(90261019)')):
            raise ScenarioError('SCENARIO_JOB_ALREADY_RUNNING')
        lock.commit()
        try:
            with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
                with Session(bind=conn) as db:
                    snapshot = snapshot_database(db,marker,settings.scenario_max_rows)
            compute_script=Path(settings.scenario_compute_script)
            versions = {'package':PACKAGE_SHA,'registry':digest(REGISTRY),'adapter':'scenario-adapter-v1.1',
                'compute_sha256':hashlib.sha256(compute_script.read_bytes()).hexdigest() if compute_script.is_file() else 'unavailable',
                'enabled':configuration(settings)}
            fingerprint = digest({'snapshot':snapshot,'versions':versions})
            with SessionLocal.begin() as db:
                run = db.scalar(select(ScenarioRun).where(ScenarioRun.fingerprint==fingerprint))
                if run and (run.state!='failed' or not retry):
                    return {'id':run.id,'state':run.state,'reused':True}
                if not run:
                    previous=db.scalar(select(ScenarioRun).where(
                        ScenarioRun.as_of_date==date.fromisoformat(marker['as_of_date']),
                        ScenarioRun.snapshot_version==marker['snapshot_version']).order_by(ScenarioRun.id.desc()).limit(1))
                    source=lambda value:{k:v for k,v in value.items() if k not in {'gas','gas_issued_at'}}
                    if previous and digest(source(previous.snapshot))!=digest(source(snapshot)):
                        raise ScenarioError('SNAPSHOT_CHANGED_REQUIRES_NEW_VERSION')
                    revision = 1+(db.scalar(select(func.max(ScenarioRun.revision)).where(
                        ScenarioRun.as_of_date==date.fromisoformat(marker['as_of_date']))) or 0)
                    run = ScenarioRun(as_of_date=date.fromisoformat(marker['as_of_date']),revision=revision,
                        fingerprint=fingerprint,snapshot_version=marker['snapshot_version'],snapshot=snapshot,
                        versions=versions,state='running')
                    db.add(run);db.flush()
                run.state='running';run.error_code=None
                run_id=run.id
                attempts=(run.output or {}).get('backend_attempt_history',[])
            heartbeat('scenario_worker','running')
            try:
                output=invoke_runtime(snapshot,issued,settings)
                with SessionLocal.begin() as db:
                    run=db.get(ScenarioRun,run_id)
                    store_validated(db,run,output)
                    run.output={**run.output,'backend_attempt_history':[*attempts,
                        {'state':run.state,'finished_at':run.finished_at.isoformat(),'error_code':None}]}
                heartbeat('scenario_worker','completed',success=True)
            except Exception as exc:
                code=str(exc) if isinstance(exc,ScenarioError) else type(exc).__name__
                with SessionLocal.begin() as db:
                    run=db.get(ScenarioRun,run_id);run.state='failed';run.error_code=code[:100]
                    run.finished_at=datetime.now(timezone.utc)
                    run.output={'backend_attempt_history':[*attempts,
                        {'state':'failed','finished_at':run.finished_at.isoformat(),'error_code':code[:100]}]}
                heartbeat('scenario_worker','error',error_code=code[:100])
                raise ScenarioError(code) from None
            with SessionLocal() as db:
                return {'id':run_id,'state':db.get(ScenarioRun,run_id).state,'reused':False}
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(90261019)'));lock.commit()
