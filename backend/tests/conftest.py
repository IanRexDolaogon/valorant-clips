import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

test_url = os.environ.get("TEST_DATABASE_URL")
if test_url:
    if not (make_url(test_url).database or "").endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must use a separate database ending in _test")
    os.environ["DATABASE_URL"] = test_url

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://vclips:change_me@localhost:5432/vclips"
)
os.environ["JWT_SECRET"] = "test-secret-at-least-32-characters-long"


@pytest.fixture
def db_connection():
    if not test_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    engine = create_engine(test_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


@pytest.fixture
def api_client(db_connection, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from app.core.db import get_db
    from app.core.config import settings
    from app.core.rate_limit import auth_limit, upload_limit, share_limit
    from app.main import app

    # TestClient serves the API directly, without the production /api reverse proxy.
    monkeypatch.setattr(settings, "public_api_url", "http://testserver")

    with Session(bind=db_connection, join_transaction_mode="create_savepoint") as session:
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[auth_limit] = lambda: None
        app.dependency_overrides[upload_limit] = lambda: None
        app.dependency_overrides[share_limit] = lambda: None
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
