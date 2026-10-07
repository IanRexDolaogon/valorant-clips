import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import auth_limit
from app.core.security import token_for
from app.main import app
from app.services import riot_client


@pytest.mark.parametrize("cookie", [None, "a-different-browser-state"])
def test_riot_callback_rejects_missing_or_mismatched_browser_cookie(api_client, monkeypatch, cookie):
    def unexpected_exchange(*args):
        pytest.fail("Rejected callbacks must not exchange Riot authorization codes")
    monkeypatch.setattr(riot_client, "finish_link", unexpected_exchange)
    if cookie:
        api_client.cookies.set("rso_state", cookie)
    response = api_client.get("/riot/callback", params={"code": "test-code", "state": "a-test-state-at-least-twenty-characters"})
    assert response.status_code == 400


def test_riot_callback_links_verified_account_and_clears_cookie(api_client, db_connection, monkeypatch):
    token = api_client.post("/auth/register", json={"email": "link@example.com", "password": "link-long-password",
        "display_name": "Player"}).json()["access_token"]
    api_client.headers["Authorization"] = "Bearer " + token
    user_id = api_client.get("/auth/me").json()["id"]
    state = "a-test-state-at-least-twenty-characters"
    monkeypatch.setattr(riot_client, "link_url", lambda *args: "https://auth.riotgames.com/authorize?state=" + state)
    link = api_client.get("/riot/link?region=ap")
    assert link.status_code == 200
    assert "HttpOnly" in link.headers["set-cookie"]
    assert "SameSite=lax" in link.headers["set-cookie"]
    monkeypatch.setattr(riot_client, "finish_link", lambda *args: (user_id, "ap",
        riot_client.RiotAccount(puuid="verified-test-player", gameName="Player", tagLine="001")))
    callback = api_client.get("/riot/callback", params={"code": "test-code", "state": state}, follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == settings.frontend_url
    assert api_client.cookies.get("rso_state") is None
    assert db_connection.scalar(text("SELECT user_id FROM riot_accounts WHERE puuid='verified-test-player'")) == user_id


def test_validation_response_does_not_echo_password(api_client):
    response = api_client.post("/auth/register", json={"email": "invalid", "password": "secretvalue", "display_name": "Player"})
    assert response.status_code == 422
    assert "secretvalue" not in response.text
    assert all("input" not in error for error in response.json()["detail"])


def test_database_error_response_hides_internal_details():
    class BrokenDB:
        def scalar(self, *args):
            raise OperationalError("private-query", {}, RuntimeError("private-credentials"))
    app.dependency_overrides[get_db] = lambda: BrokenDB()
    app.dependency_overrides[auth_limit] = lambda: None
    try:
        response = TestClient(app).get("/auth/me", headers={"Authorization": "Bearer " + token_for(1)})
        assert response.status_code == 503
        assert response.json() == {"detail": "Database operation unavailable"}
        assert "private" not in response.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("changes", [
    {"jwt_secret": "short"}, {"frontend_url": "http://example.com"}, {"public_api_url": "http://example.com/api"},
])
def test_production_startup_rejects_weak_secret_or_non_https_urls(monkeypatch, changes):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "a-test-secret-at-least-32-characters")
    monkeypatch.setattr(settings, "frontend_url", "https://example.com")
    monkeypatch.setattr(settings, "public_api_url", "https://example.com/api")
    for key, value in changes.items():
        monkeypatch.setattr(settings, key, value)
    with pytest.raises(RuntimeError, match="Production requires"):
        with TestClient(app):
            pass


def test_production_startup_accepts_strong_secret_and_https_urls(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "a-test-secret-at-least-32-characters")
    monkeypatch.setattr(settings, "frontend_url", "https://example.com")
    monkeypatch.setattr(settings, "public_api_url", "https://example.com/api")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
