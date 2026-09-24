"""Short process-local cache for expensive shared monitoring snapshots, never auth or writes."""
import threading
import time
from functools import wraps
from app.core.config import get_settings

def cached_snapshot(function):
    lock = threading.Lock()
    values = {}
    @wraps(function)
    def wrapped(*args, **kwargs):
        ttl = get_settings().read_cache_seconds
        if ttl == 0:
            return function(*args, **kwargs)
        key = (args, tuple(sorted(kwargs.items())))
        with lock:
            now = time.monotonic()
            entry = values.get(key)
            if entry is not None and now < entry[0]:
                return entry[1]
            value = function(*args, **kwargs)
            # Bound memory even if clients vary pagination parameters.
            if len(values) >= 256:
                values.clear()
            values[key] = (time.monotonic() + ttl, value)
            return value
    return wrapped
