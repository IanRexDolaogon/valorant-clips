from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.security import password_hasher

ACCOUNT = {"email": "Player@example.com", "password": "long-test-password", "display_name": "Player"}


def test_register_login_and_me_never_return_password_hash(api_client, db_connection):
    response = api_client.post("/auth/register", json=ACCOUNT)
    assert response.status_code == 201
    token = response.json()["access_token"]
    me = api_client.get("/auth/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200
    assert me.json()["email"] == "player@example.com"
    assert set(me.json()) == {"id", "email", "display_name"}
    hashed = db_connection.scalar(text("SELECT password_hash FROM users WHERE email='player@example.com'"))
    assert hashed != ACCOUNT["password"]
    assert password_hasher.verify(hashed, ACCOUNT["password"])
    assert api_client.post("/auth/login", json=ACCOUNT).status_code == 200


def test_register_rejects_duplicate_email(api_client):
    assert api_client.post("/auth/register", json=ACCOUNT).status_code == 201
    assert api_client.post("/auth/register", json={**ACCOUNT, "email": "PLAYER@example.com"}).status_code == 409


@pytest.mark.parametrize("changes", [{"email": "invalid"}, {"password": "short"}, {"display_name": "   "}])
def test_register_rejects_invalid_input(api_client, changes):
    assert api_client.post("/auth/register", json={**ACCOUNT, **changes}).status_code == 422


def test_login_rejects_wrong_password_and_unknown_user(api_client):
    api_client.post("/auth/register", json=ACCOUNT)
    wrong = api_client.post("/auth/login", json={**ACCOUNT, "password": "wrong-test-password"})
    missing = api_client.post("/auth/login", json={**ACCOUNT, "email": "missing@example.com"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()


@pytest.mark.parametrize("token", [None, "garbage", "expired", "other-secret", "deleted-user"])
def test_me_rejects_invalid_tokens(api_client, token):
    if token in {"expired", "other-secret", "deleted-user"}:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"sub": "999999", "iat": now - timedelta(hours=2), "exp": now + timedelta(minutes=-1 if token == "expired" else 5)},
            "another-secret-at-least-32-characters" if token == "other-secret" else settings.jwt_secret,
            algorithm="HS256",
        )
    headers = {"Authorization": "Bearer " + token} if token else {}
    assert api_client.get("/auth/me", headers=headers).status_code == 401
