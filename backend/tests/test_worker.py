import httpx
from datetime import datetime, timezone
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.platform import IntegrationCursor, IntegrationRecord
from app.integration_worker import Source, poll_source

def test_worker_get_cursor_and_retry():
    source=Source(name="equipment-test",kind="equipment",url="https://example.test/export")
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={"records":[{"external_id":"1","observed_at":"2026-01-01T00:00:00Z",
            "object_id":2,"channel_id":2,"name":"Fixture equipment"}],"next_cursor":"next"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert poll_source(source,client)["inserted"]==1
        assert poll_source(source,client)["duplicates"]==1
    assert all(request.method=="GET" for request in requests)
    assert requests[1].url.params["cursor"]=="next"
    with SessionLocal() as db:
        assert db.get(IntegrationCursor,source.name).cursor=="next"

def test_failed_batch_does_not_advance_cursor():
    import pytest
    source=Source(name="bad-source",kind="telemetry",url="https://example.test/export")
    def handler(request):
        return httpx.Response(200,json={"records":[{"external_id":"1","observed_at":"2026-01-01T00:00:00Z",
            "channel_id":999,"event_id":1,"alarm":True}],"next_cursor":"must-not-save"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            poll_source(source,client)
    with SessionLocal() as db:
        assert db.get(IntegrationCursor,source.name) is None
        assert db.scalar(select(IntegrationRecord)) is None
