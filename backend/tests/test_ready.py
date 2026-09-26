"""Readiness must follow the Alembic head, not a hardcoded revision."""
from sqlalchemy import text

from app.db.session import engine
from app.main import expected_schema_revision


def test_ready_matches_alembic_head(client):
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == expected_schema_revision()
    assert client.get("/ready").json() == {"status": "ready"}
