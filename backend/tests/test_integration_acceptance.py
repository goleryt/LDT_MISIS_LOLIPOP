from datetime import datetime, timezone
import httpx
import pytest
from sqlalchemy import select, func
from app.core.config import get_settings
from app.integration_worker import Source, poll_source
from app.db.platform import IntegrationRecord, Notification, Prediction
from app.db.models import PreventiveRequest
from app.db.session import SessionLocal

@pytest.mark.parametrize('kind,extra',[
    ('equipment',{'object_id':2,'channel_id':2,'name':'TEST equipment'}),
    ('telemetry',{'channel_id':1,'event_id':101,'alarm':True,'value':'20'}),
    ('ods',{'description':'TEST ODS'}),
    ('weather',{'longitude':37.6,'latitude':55.7,'temperature':12}),
    ('work_status',{'request_id':1,'status':'in_progress'}),
])
def test_all_source_kinds_retry_timeout_cursor_and_idempotency(kind, extra):
    if kind == 'work_status':
        with SessionLocal.begin() as db:
            db.add(PreventiveRequest(id=1,object_id=1,title='TEST work',status='new',priority='medium'))
    source=Source(name='acceptance-'+kind,kind=kind,url='https://example.test/export')
    payload={'external_id':'1','observed_at':datetime.now(timezone.utc).isoformat(),**extra}
    failures=[500,'timeout',200,200]
    seen=[]
    def handler(request):
        seen.append(request)
        result=failures.pop(0)
        if result == 'timeout': raise httpx.ReadTimeout('simulated', request=request)
        return httpx.Response(result,json={'records':[payload],'next_cursor':'after-1'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError): poll_source(source,client)
        with pytest.raises(httpx.ReadTimeout): poll_source(source,client)
        assert poll_source(source,client)['inserted'] == 1
        assert poll_source(source,client)['duplicates'] == 1
    assert all(r.method == 'GET' for r in seen)
    assert seen[-1].url.params['cursor'] == 'after-1'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(IntegrationRecord)) == 1
        assert db.scalar(select(func.count()).select_from(Prediction)) == 0

def test_notification_visibility_is_per_user_and_targets_exact_sensor(login):
    from app.ingestion.integrations import Record, ingest
    with SessionLocal.begin() as db:
        ingest(db,'telemetry','smvu',[Record(external_id='alarm',observed_at=datetime.now(timezone.utc),channel_id=1,event_id=200,alarm=True)])
    c=login('dispatcher')
    notice=c.get('/api/v1/notifications').json()[0]
    assert notice['kind'] == 'observed_alarm' and notice['channel_id'] == 1 and notice['object_id'] == 1
    assert c.post(f"/api/v1/notifications/{notice['id']}/read").status_code == 200
    assert c.post(f"/api/v1/notifications/{notice['id']}/read").status_code == 200
    assert c.get('/api/v1/notifications').json() == []
    c=login('manager')
    assert len(c.get('/api/v1/notifications').json()) == 1
