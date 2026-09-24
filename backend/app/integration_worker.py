"""Poll configured source APIs using GET only; commit records and cursor atomically."""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from app.core.config import get_settings
from app.db.platform import IntegrationCursor
from app.db.session import SessionLocal, engine
from app.ingestion.integrations import KINDS, Record, ingest

log = logging.getLogger(__name__)

class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: str
    url: str
    token_env: str | None = None
    ca_file: str | None = None

def poll_source(source: Source, client: httpx.Client):
    if source.kind not in KINDS:
        raise ValueError("Unsupported source kind")
    parsed = urlparse(source.url)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Credentials and fragments must not appear in source URLs")
    if parsed.scheme != "https" and not (get_settings().environment != "production" and parsed.hostname in {"127.0.0.1", "localhost", "mock-source"}):
        raise ValueError("Sources require HTTPS; local HTTP mocks are development-only")
    with SessionLocal() as db:
        current = db.get(IntegrationCursor, source.name)
        cursor = current.cursor if current else None
    headers = {}
    if source.token_env:
        token = os.environ.get(source.token_env)
        if not token:
            raise ValueError("Source token environment variable is missing")
        headers["Authorization"] = f"Bearer {token}"
    with client.stream("GET", source.url, params={"cursor": cursor} if cursor else None, headers=headers) as response:
        response.raise_for_status()
        body = bytearray()
        started = time.monotonic()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > get_settings().max_upload_bytes or time.monotonic() - started > 30:
                raise ValueError("Source response exceeds size or time budget")
    payload = json.loads(body)
    if not isinstance(payload.get("records"), list) or len(payload["records"]) > 2000:
        raise ValueError("Source must return at most 2000 records and next_cursor")
    next_cursor = payload.get("next_cursor")
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 4096):
        raise ValueError("Invalid source cursor")
    records = [Record.model_validate(row) for row in payload["records"]]
    with SessionLocal.begin() as db:
        result = ingest(db, source.kind, source.name, records)
        state = db.get(IntegrationCursor, source.name)
        if not state:
            state = IntegrationCursor(source=source.name)
            db.add(state)
        state.cursor, state.last_success, state.last_error = next_cursor, datetime.now(timezone.utc), None
    return result

def main():
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.integration_sources_file:
        raise SystemExit("INTEGRATION_SOURCES_FILE must point to a JSON source configuration")
    sources = [Source.model_validate(row) for row in json.loads(Path(settings.integration_sources_file).read_text())]
    if len({s.name for s in sources}) != len(sources):
        raise SystemExit("Source names must be unique")
    if len(sources) > 5:
        raise SystemExit("At most five sources per worker; configure additional independent deployments if needed")
    # One elected worker avoids cursor races when the container is accidentally scaled.
    with engine.connect() as leader:
        if not leader.scalar(text("SELECT pg_try_advisory_lock(82519783)")):
            raise SystemExit("Another integration worker is active")
        while True:
            for source in sources:
                try:
                    import ssl
                    context = ssl.create_default_context(cafile=source.ca_file)
                    with httpx.Client(timeout=20, verify=context, follow_redirects=False, trust_env=False) as client:
                        result = poll_source(source, client)
                    log.info("source=%s result=%s", source.name, result)
                except Exception as exc:
                    # Do not log URLs, auth headers, source bodies or credentials.
                    log.error("source=%s failure=%s", source.name, type(exc).__name__)
                    with SessionLocal.begin() as db:
                        state = db.get(IntegrationCursor, source.name)
                        if not state:
                            state = IntegrationCursor(source=source.name)
                            db.add(state)
                        state.last_error = type(exc).__name__
            time.sleep(settings.integration_poll_seconds)

if __name__ == "__main__":
    main()
