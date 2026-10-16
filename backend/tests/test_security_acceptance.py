from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import select, update
from app.db.platform import AuditEntry, LoginSession
from app.db.session import SessionLocal
from app.operations import heartbeat, backup_status
from app.core.config import get_settings

@pytest.mark.parametrize('role', ['manager','analyst','technician','dispatcher','admin'])
def test_backend_role_matrix(login, role):
    c = login(role)
    for path in ('events','notifications','requests','predictions','reports/observations?date_from=2026-09-01&date_to=2026-09-01'):
        assert c.get('/api/v1/'+path).status_code == 200
    for path in ('audit','operations/status','integrations/status'):
        assert c.get('/api/v1/'+path).status_code == (200 if role == 'admin' else 403)
    expected = 200 if role in {'admin','dispatcher','technician'} else 403
    assert c.post('/api/v1/requests',json={'object_id':1,'title':'Matrix'}).status_code == expected
    c.headers.pop('X-CSRF-Token')
    assert c.post('/api/v1/auth/logout').status_code == 403
    # An arbitrary Authorization header must never bypass cookie CSRF validation.
    assert c.post('/api/v1/auth/logout',headers={'Authorization':'invalid'}).status_code == 401

def test_expired_session_and_logout(login):
    c = login()
    with SessionLocal.begin() as db:
        db.execute(update(LoginSession).values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    assert c.get('/api/v1/auth/me').status_code == 401
    c = login()
    assert c.post('/api/v1/auth/logout').status_code == 200
    assert c.get('/api/v1/auth/me').status_code == 401

def test_failed_login_and_attributed_actions_are_audited(client, login):
    assert client.post('/api/v1/auth/login',json={'username':'dispatcher','password':'not-the-password'}).status_code == 401
    c = login('admin')
    rid = c.post('/api/v1/requests',json={'object_id':1,'title':'Audit test'}).json()['id']
    assert c.patch(f'/api/v1/requests/{rid}',json={'status':'in_progress'}).status_code == 200
    assert c.post('/api/v1/auth/logout').status_code == 200
    with SessionLocal() as db:
        entries = db.scalars(select(AuditEntry).order_by(AuditEntry.id)).all()
        assert entries[0].actor == 'dispatcher' and entries[0].outcome == 401
        assert entries[1].role == 'admin' and entries[1].entity_type == 'user'
        created = next(x for x in entries if x.target == '/api/v1/requests' and x.action == 'POST')
        assert created.entity_id == str(rid) and created.role == 'admin'
        assert all(x.created_at and x.outcome is not None for x in entries)
        assert 'not-the-password' not in str([x.__dict__ for x in entries])

def test_operational_status_never_fabricates_success(login, tmp_path):
    c = login('admin')
    initial = c.get('/api/v1/operations/status').json()
    assert initial['workers']['ml_scheduler']['state'] == 'not_observed'
    assert initial['last_prediction_job'] is None
    heartbeat('integrations','idle',success=True)
    heartbeat('integrations','error',error_code='SOURCE_FAILURE')
    result = c.get('/api/v1/operations/status').json()
    assert result['workers']['integrations']['last_success']
    assert result['workers']['integrations']['error_code'] == 'SOURCE_FAILURE'
    assert 'password' not in json.dumps(result).lower()
    settings = get_settings()
    previous = settings.backup_status_dir
    try:
        settings.backup_status_dir = str(tmp_path)
        assert backup_status()['state'] == 'not_observed'
        (tmp_path/'last-success').write_text('2026-10-16T12:00:00Z')
        (tmp_path/'status.json').write_text('{"state":"failed"}')
        assert backup_status()['state'] == 'failed' and backup_status()['last_success']
    finally:
        settings.backup_status_dir = previous
