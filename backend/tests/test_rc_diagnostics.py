import json
import pytest
from app.core.config import get_settings


@pytest.mark.parametrize('payload',[[],None,12,"broken",{},{"state":"unrecognised"}])
def test_corrupt_backup_metadata_does_not_break_operations(login,tmp_path,monkeypatch,payload):
    monkeypatch.setattr(get_settings(),'backup_status_dir',str(tmp_path))
    (tmp_path/'status.json').write_text(json.dumps(payload))
    (tmp_path/'last-success').write_text('2026-10-16T12:00:00')  # Missing timezone is not a success.
    c=login('admin')
    response=c.get('/api/v1/operations/status')
    assert response.status_code==200
    result=response.json()
    assert result['backup']=={'state':'not_observed','last_success':None}
    assert result['application']['version']
    assert result['application']['commit']=='unknown'


def test_commit_identifier_is_bounded_and_cannot_contain_credentials():
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(app_commit='https://user:secret@example.test/repo',_env_file=None,postgres_password='fixture-only-password')
