import httpx
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services import riot_client


@pytest.mark.parametrize("status,expected", [(401, 503), (403, 503), (404, 404), (429, 429), (500, 502)])
def test_riot_errors_do_not_leak_upstream_details(monkeypatch, status, expected):
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def request(self, *args, **kwargs):
            return httpx.Response(status, json={"secret": "private"}, request=httpx.Request("GET", "https://example.com"))
    monkeypatch.setattr(riot_client.httpx, "Client", Client)
    with pytest.raises(HTTPException) as error:
        riot_client.request_json("GET", "https://example.com")
    assert error.value.status_code == expected
    assert "private" not in error.value.detail


def test_linking_requires_approved_rso_configuration(monkeypatch):
    monkeypatch.setattr(settings, "riot_client_id", "")
    with pytest.raises(HTTPException) as error:
        riot_client.link_url(1, "ap")
    assert error.value.status_code == 503


def test_riot_callback_state_is_one_time_and_bound_to_user(monkeypatch):
    states = {}
    monkeypatch.setattr(settings, "riot_client_id", "test")
    monkeypatch.setattr(settings, "riot_client_secret", "test")
    monkeypatch.setattr(settings, "riot_redirect_uri", "http://localhost/callback")
    monkeypatch.setattr(riot_client.redis, "set", lambda key, value, **kwargs: states.update({key: value}))
    monkeypatch.setattr(riot_client.redis, "getdel", lambda key: states.pop(key, None))
    from urllib.parse import parse_qs, urlparse
    state = parse_qs(urlparse(riot_client.link_url(42, "ap")).query)["state"][0]
    monkeypatch.setattr(riot_client, "request_json", lambda method, *args, **kwargs:
        {"access_token": "test-token"} if method == "POST" else {"puuid": "verified", "gameName": "Player", "tagLine": "001"})
    uid, region, account = riot_client.finish_link("code", state)
    assert (uid, region, account.puuid) == (42, "ap", "verified")
    with pytest.raises(HTTPException) as error:
        riot_client.finish_link("code", state)
    assert error.value.status_code == 400
