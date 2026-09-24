import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
# Never allow destructive fixtures against a working database.
if os.environ.get("ENVIRONMENT") != "test" or os.environ.get("POSTGRES_DB") != "ldt_test":
    raise RuntimeError("Tests require ENVIRONMENT=test and a dedicated POSTGRES_DB=ldt_test")
from app.main import app
from app.db.session import SessionLocal, engine
from app.db.models import ChannelCatalogue, ObjectCatalogue
from app.db.platform import User
from app.core.security import password_hash
from app.core.config import get_settings
get_settings().read_cache_seconds = 0

PASSWORD = "test-only-password-012345"
HASH = password_hash(PASSWORD)

@pytest.fixture(autouse=True)
def data():
    with engine.begin() as db:
        tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")).scalars().all()
        db.execute(text("TRUNCATE " + ", ".join('"' + name + '"' for name in tables) + " RESTART IDENTITY CASCADE"))
    with SessionLocal.begin() as db:
        db.add_all([User(username=role, role=role, password_hash=HASH, provider="local", active=True)
                    for role in ("admin", "dispatcher", "technician", "manager", "analyst", "integrator")])
        db.add(ObjectCatalogue(ид_объект=1, диспетчерское_название_объекта="Тестовый объект"))
        db.flush()
        db.add(ChannelCatalogue(ид_канала_данных=1, ид_объект=1, название_датчика="Тестовый датчик"))

@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

@pytest.fixture
def login(client):
    def enter(role="dispatcher"):
        response = client.post("/api/v1/auth/login", json={"username": role, "password": PASSWORD})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client
    return enter
