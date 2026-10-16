"""Bounded operational metadata only; never source payloads, URLs, or credentials."""
import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.db.models import DataImport
from app.db.platform import IntegrationCursor, MlRun, WorkerHeartbeat
from app.db.session import SessionLocal, engine

def heartbeat(name, state, *, success=False, error_code=None):
    now = datetime.now(timezone.utc)
    values = dict(name=name, state=state, last_seen=now, error_code=error_code)
    if success:
        values['last_success'] = now
    with SessionLocal.begin() as db:
        db.execute(insert(WorkerHeartbeat).values(**values).on_conflict_do_update(
            index_elements=['name'], set_={k:v for k,v in values.items() if k != 'name'}))

def backup_status():
    directory = get_settings().backup_status_dir
    if not directory:
        return {'state':'not_configured', 'last_success':None}
    try:
        root = Path(directory)
        last = (root/'last-success').read_text().strip()
        success = datetime.fromisoformat(last.replace('Z','+00:00')).isoformat()
    except (OSError, ValueError):
        success = None
    try:
        path = root/'status.json'
        if path.stat().st_size > 4096: raise ValueError('Oversized status')
        raw = json.loads(path.read_text())
        state = raw.get('state')
        if state not in {'completed','failed','running'}: raise ValueError('Invalid state')
    except (OSError, ValueError):
        state = 'not_observed'
    return {'state':state, 'last_success':success}

def operational_status():
    with SessionLocal() as db:
        workers = {w.name:{'state':w.state,'last_seen':w.last_seen,'last_success':w.last_success,'error_code':w.error_code}
                   for w in db.scalars(select(WorkerHeartbeat))}
        last_import = db.scalar(select(DataImport).order_by(DataImport.id.desc()).limit(1))
        last_job = db.scalar(select(MlRun).order_by(MlRun.id.desc()).limit(1))
        sources = [{'source':s.source,'last_success':s.last_success,'error_code':s.last_error}
                   for s in db.scalars(select(IntegrationCursor).order_by(IntegrationCursor.source))]
        pool = engine.pool
        return {'api':'ok', 'database':'connected', 'workers':{name:workers.get(name,{'state':'not_observed'}) for name in ('integrations','ml_scheduler')},
                'last_import':None if not last_import else {'id':last_import.id,'status':last_import.status,'completed_at':last_import.completed_at},
                'last_prediction_job':None if not last_job else {'id':last_job.id,'state':last_job.state,'finished_at':last_job.finished_at,'error_code':last_job.error_code},
                'integration_sources':sources, 'integration_failures':sum(bool(s['error_code']) for s in sources),
                'backup':backup_status(), 'pool':{'size':pool.size(),'checked_out':pool.checkedout(),'overflow':pool.overflow()}}
