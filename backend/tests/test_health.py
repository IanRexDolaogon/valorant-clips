import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app

client = TestClient(app)


class OkDB:
    def execute(self, *_):
        return 1


class BrokenDB:
    def execute(self, *_):
        raise RuntimeError("down")


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_db_ok():
    app.dependency_overrides[get_db] = lambda: OkDB()
    assert client.get("/health/db").status_code == 200


def test_health_db_unavailable_returns_503():
    app.dependency_overrides[get_db] = lambda: BrokenDB()
    r = client.get("/health/db")
    assert r.status_code == 503
    assert r.json()["detail"] == "database unavailable"