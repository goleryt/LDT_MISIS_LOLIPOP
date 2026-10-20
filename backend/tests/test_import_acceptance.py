"""Import failure/retry matrix against a disposable PostgreSQL database."""
import pytest
from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.db.models import EventsJournal, DataImport
from app.ingestion import import_registry
from app.core.config import get_settings
from test_workflows import file_content, row

@pytest.mark.parametrize('failure', [RuntimeError, KeyboardInterrupt])
def test_registry_and_data_commit_atomically_then_retry(tmp_path, monkeypatch, failure):
    path = tmp_path/'atomic.json'; path.write_bytes(file_content('json'))
    original = import_registry.complete_file_import
    def interrupt(*args, **kwargs): raise failure('simulated interruption before commit')
    monkeypatch.setattr(import_registry, 'complete_file_import', interrupt)
    with pytest.raises(failure): import_registry.import_events_file(path)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(EventsJournal)) == 0
        assert db.scalar(select(DataImport)).status in {'failed','processing'}
    monkeypatch.setattr(import_registry, 'complete_file_import', original)
    assert import_registry.import_events_file(path)['inserted_rows'] == 1
    assert import_registry.import_events_file(path)['already_imported']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(EventsJournal)) == 1

@pytest.mark.parametrize('format', ['csv','xlsx','json','xml'])
def test_invalid_schema_is_registered_failed(login, format, tmp_path):
    from app.ingestion.formats import normalize_to_csv
    c = login()
    # A syntactically valid event file interpreted as an object catalogue must fail atomically.
    r = c.post('/api/v1/imports/events?kind=objects',files={'file':('wrong.'+format,file_content(format))})
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.scalar(select(DataImport)).status == 'failed'
        assert db.scalar(select(func.count()).select_from(EventsJournal)) == 0

def test_oversized_file_rejected_before_import(login, monkeypatch):
    c=login()
    monkeypatch.setattr(get_settings(),'max_upload_bytes',1024)
    assert c.post('/api/v1/imports/events',files={'file':('large.csv',b'x'*1025)}).status_code == 413
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DataImport)) == 0

def test_duplicate_rows_and_partial_bad_data(login):
    import json
    c=login()
    repeated=json.dumps([row(),row()]).encode()
    response=c.post('/api/v1/imports/events',files={'file':('duplicate.json',repeated)})
    assert response.json()['inserted_rows'] == 1 and response.json()['skipped_duplicates'] == 1
    invalid=json.dumps([row(2),{**row(3),'дата':'bad'}]).encode()
    assert c.post('/api/v1/imports/events',files={'file':('partial.json',invalid)}).status_code == 400
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(EventsJournal)) == 1
