import json
from datetime import datetime,timezone
import httpx
import pytest
from sqlalchemy import select,func
from app.db.platform import IntegrationCursor,IntegrationRecord
from app.db.session import SessionLocal
from app.integration_worker import Source,poll_source


@pytest.mark.parametrize('body',[
    b'not-json',b'[]',b'null',b'{"records":[]}',b'{"records":{},"next_cursor":"bad"}',
    b'{"records":[],"next_cursor":42}',b'{"records":[{}],"next_cursor":"bad"}',
])
def test_malformed_or_disconnected_source_preserves_cursor_and_recovers(body):
    source=Source(name='rc-malformed',kind='equipment',url='https://example.test/export')
    with SessionLocal.begin() as db:db.add(IntegrationCursor(source=source.name,cursor='prior'))
    valid={'records':[{'external_id':'v1','observed_at':'2026-10-16T12:00:00Z','object_id':2,'channel_id':2,'name':'TEST RC equipment'}],'next_cursor':'after'}
    replies=[body,'disconnect',json.dumps(valid).encode(),json.dumps(valid).encode()]
    seen=[]
    def handler(request):
        seen.append(request)
        reply=replies.pop(0)
        if reply=='disconnect':raise httpx.ConnectError('Fixture disconnect',request=request)
        return httpx.Response(200,content=reply)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):poll_source(source,client)
        with pytest.raises(httpx.ConnectError):poll_source(source,client)
        with SessionLocal() as db:
            assert db.get(IntegrationCursor,source.name).cursor=='prior'
            assert db.scalar(select(func.count()).select_from(IntegrationRecord))==0
        assert poll_source(source,client)['inserted']==1
        assert poll_source(source,client)['duplicates']==1
    assert [str(r.url.params['cursor']) for r in seen]==['prior','prior','prior','after']
