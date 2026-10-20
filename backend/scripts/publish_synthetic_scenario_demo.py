"""Explicit one-shot publication of frozen inference on supplier synthetic inputs.

This is an operator deployment tool, not a source of operational observations.
The raw fixture remains in the scenario snapshot: it NEVER enters events_journal.
Only reserved, visibly synthetic catalogue entities and validated forecasts are added.
"""
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text
from app.core.config import get_settings
from app.db.models import ChannelCatalogue, ObjectCatalogue
from app.db.platform import AuditEntry, ScenarioRun
from app.db.session import SessionLocal, engine
from app.operations import heartbeat
from app.scenario_job import (PACKAGE_SHA, REGISTRY, TZ, ScenarioError,
    configuration, digest, invoke_runtime, store_validated)

OBJECT_ID = 91000000001
CHANNEL_BASE = 91000000100
LABEL = 'ДЕМО — синтетическая проверка моделей, не реальный объект'
PROJECT = 'd4c500cc-fab0-4f7f-ad7e-a52db7a5585c'
ENVIRONMENT = '1dd4e231-b7ab-48b3-879e-b17389d1e911'


def require_opt_in(settings):
    if (os.environ.get('PUBLISH_SYNTHETIC_SCENARIO_DEMO') != 'synthetic-input-only'
        or os.environ.get('RAILWAY_PROJECT_ID') != PROJECT
        or os.environ.get('RAILWAY_ENVIRONMENT_ID') != ENVIRONMENT
        or not settings.scenario_enabled
        or (settings.environment == 'production' and not settings.scenario_allow_production)):
        raise ScenarioError('EXPLICIT_PUBLIC_DEMO_ACCEPTANCE_REQUIRED')


def build_snapshot(root, day):
    """Translate all supplied dates equally; never fill absent observations."""
    catalogue = list(csv.DictReader((root/'catalogue.csv').open(encoding='utf8')))
    journal = list(csv.DictReader((root/'journal.csv').open(encoding='utf8')))
    delta = day-date(2025,8,15)
    mapping = {row['ид_канала_данных']:str(CHANNEL_BASE+i) for i,row in enumerate(catalogue)}
    for row in catalogue:
        row['ид_канала_данных'] = mapping[row['ид_канала_данных']]
        row['ид_объект'] = str(OBJECT_ID)
    for row in journal:
        row['ид_канала_данных'] = mapping[row['ид_канала_данных']]
        row['дата'] = (date.fromisoformat(row['дата'])+delta).isoformat()
    coverage = json.loads((root/'coverage.json').read_text())
    coverage = {k:(date.fromisoformat(v)+delta).isoformat() for k,v in coverage.items()}
    fixture_sha = hashlib.sha256(b''.join((root/name).read_bytes()
        for name in ('catalogue.csv','journal.csv','coverage.json'))).hexdigest()
    return {'as_of_date':str(day),'snapshot_version':f'public-synthetic-v1-{fixture_sha[:16]}',
        'coverage':coverage,'catalogue_valid_as_of':str(day),'catalogue':catalogue,
        'journal':journal,'gas':None,'gas_issued_at':None,
        'provenance':{'kind':'supplier_synthetic_demo','package_sha256':PACKAGE_SHA,
            'fixture_sha256':fixture_sha,'date_translation_days':delta.days,
            'operational_observations_written':False,'actual_gas_queue_changed':False}}


def ensure_catalogue(db, snapshot):
    obj = db.get(ObjectCatalogue,OBJECT_ID)
    if obj and obj.диспетчерское_название_объекта != LABEL:
        raise ScenarioError('DEMO_CATALOGUE_ID_COLLISION')
    if not obj:
        db.add(ObjectCatalogue(ид_объект=OBJECT_ID,диспетчерское_название_объекта=LABEL,
            вид_объекта='Синтетическая демонстрация'))
    for source in snapshot['catalogue']:
        cid = int(source['ид_канала_данных'])
        name = 'ДЕМО — '+(source.get('название_датчика') or source.get('тип_датчика') or 'сценарный канал')
        old = db.get(ChannelCatalogue,cid)
        if old and (old.ид_объект != OBJECT_ID or old.название_датчика != name):
            raise ScenarioError('DEMO_CATALOGUE_ID_COLLISION')
        if not old:
            record = {k:v for k,v in source.items() if k in ChannelCatalogue.__table__.columns}
            record.update(ид_канала_данных=cid,ид_объект=OBJECT_ID,название_датчика=name)
            db.add(ChannelCatalogue(**record))
    db.flush()


def publish(*, root=Path('/opt/combined/vendor/examples'), settings=None, as_of_date=None):
    settings = settings or get_settings()
    require_opt_in(settings)
    issued = datetime.now(TZ)
    day = as_of_date or issued.date()-timedelta(days=1)
    if not isinstance(day, date) or day >= issued.date():
        raise ScenarioError('DEMO_REQUIRES_CLOSED_DAY')
    snapshot = build_snapshot(root,day)
    script = Path(settings.scenario_compute_script)
    versions = {'package':PACKAGE_SHA,'registry':digest(REGISTRY),'adapter':'public-synthetic-demo-v1',
        'compute_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
        'enabled':configuration(settings)}
    fingerprint = digest({'snapshot':snapshot,'versions':versions})
    with engine.connect() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(90261019)')):
            raise ScenarioError('SCENARIO_JOB_ALREADY_RUNNING')
        lock.commit()
        try:
            with SessionLocal() as db:
                previous = db.scalar(select(ScenarioRun).where(ScenarioRun.fingerprint==fingerprint))
                if previous:
                    return {'id':previous.id,'state':previous.state,'reused':True}
            heartbeat('scenario_worker','running')
            # Inference happens before any new catalogue/forecast writes. The child
            # receives no DB/Railway credentials (same sanitized runtime boundary).
            output = invoke_runtime(snapshot,issued.isoformat(),settings)
            with SessionLocal.begin() as db:
                ensure_catalogue(db,snapshot)
                revision = 1+(db.scalar(select(func.max(ScenarioRun.revision))
                    .where(ScenarioRun.as_of_date==day)) or 0)
                run = ScenarioRun(as_of_date=day,revision=revision,fingerprint=fingerprint,
                    snapshot_version=snapshot['snapshot_version'],snapshot=snapshot,
                    versions=versions,state='running')
                db.add(run);db.flush()
                store_validated(db,run,output)
                run_id,state = run.id,run.state
                db.add(AuditEntry(request_id=str(uuid4()),actor='system:synthetic-demo',role='system',
                    action='CREATE',target='operator:publish_synthetic_scenario_demo',
                    entity_type='scenario_run',entity_id=str(run_id),outcome=200))
            heartbeat('scenario_worker','completed',success=True)
            return {'id':run_id,'state':state,'reused':False,
                'source':'supplier synthetic raw fixture; no operational events written'}
        except Exception as exc:
            heartbeat('scenario_worker','error',error_code=type(exc).__name__)
            raise
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(90261019)'));lock.commit()


if __name__ == '__main__':
    try:
        print(json.dumps(publish(),ensure_ascii=False))
    except Exception as exc:
        # No payload, database connection details or credentials in job logs.
        raise SystemExit('Synthetic demo batch failed: '+type(exc).__name__) from None
