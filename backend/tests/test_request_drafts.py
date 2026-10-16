"""Contract fixtures for workflow tests; never real model inference."""
import pytest
from sqlalchemy import select
from app.db.platform import Prediction
from app.db.session import SessionLocal
from app.ml_job import store_output
from test_ml_job import gas, output, settings

def recommendation():
    fixture = gas(1, 0.2)
    fixture['recommendation'] = {'text_ru': 'TEST FIXTURE: manually inspect telemetry'}
    with SessionLocal.begin() as db:
        store_output(db, output([fixture]), settings())
        db.flush()
        return db.scalar(select(Prediction.id))

def test_recommendation_creates_one_editable_draft_and_history(login):
    prediction = recommendation()
    c = login()
    response = c.post(f'/api/v1/predictions/{prediction}/request')
    assert response.status_code == 200
    rid = response.json()['request_id']
    path = f'/api/v1/requests/{rid}'
    assert c.get('/api/v1/requests').json()[0]['status'] == 'draft'
    assert c.post(f'/api/v1/predictions/{prediction}/request').json()['request_id'] == rid
    assert c.patch(path, json={'title': 'Reviewed title', 'description': 'Reviewed', 'priority': 'high'}).status_code == 200
    assert c.patch(path, json={'status': 'completed'}).status_code == 409
    for state in ('new', 'in_progress', 'completed'):
        row = c.patch(path, json={'status': state}).json()
        assert row['status'] == state
    assert row['completed_at'] is not None
    assert c.patch(path, json={'title': 'Closed edit'}).status_code == 409
    history = c.get(path + '/history').json()
    assert [h['to_status'] for h in history] == ['draft', 'draft', 'new', 'in_progress', 'completed']
    assert all(h['actor'] == 'dispatcher' and h['role'] == 'dispatcher' for h in history)
    assert c.get(f'/api/v1/predictions/{prediction}').json()['request_id'] == rid

@pytest.mark.parametrize('role,code', [('technician',403), ('manager',403), ('analyst',403), ('dispatcher',200), ('admin',200)])
def test_only_dispatcher_or_admin_reviews_drafts(login, role, code):
    prediction = recommendation()
    c = login('admin')
    rid = c.post(f'/api/v1/predictions/{prediction}/request').json()['request_id']
    c = login(role)
    assert c.patch(f'/api/v1/requests/{rid}', json={'status':'new'}).status_code == code

def test_new_request_cannot_skip_work_and_cancelled_cannot_reopen(login):
    c = login()
    rid = c.post('/api/v1/requests', json={'object_id':1,'title':'Test'}).json()['id']
    assert c.patch(f'/api/v1/requests/{rid}', json={'status':'completed'}).status_code == 409
    assert c.patch(f'/api/v1/requests/{rid}', json={'status':'cancelled'}).status_code == 200
    assert c.patch(f'/api/v1/requests/{rid}', json={'status':'new'}).status_code == 409
