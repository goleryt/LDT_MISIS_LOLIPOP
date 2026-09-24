from app.core.config import get_settings
from app.core.read_cache import cached_snapshot

def test_snapshot_expires_and_can_be_disabled(monkeypatch):
    clock = [100.0]
    calls = []
    monkeypatch.setattr("app.core.read_cache.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(get_settings(), "read_cache_seconds", 2)
    @cached_snapshot
    def read(value):
        calls.append(value)
        return len(calls)
    assert read(1) == read(1) == 1
    clock[0] += 2.1
    assert read(1) == 2
    monkeypatch.setattr(get_settings(), "read_cache_seconds", 0)
    assert read(1) == 3
