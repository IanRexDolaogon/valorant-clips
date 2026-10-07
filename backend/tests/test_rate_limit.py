import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError
from starlette.requests import Request

from app.core import rate_limit


def test_rate_limit_rejects_excess_and_sets_retry_after(monkeypatch):
    calls = []
    monkeypatch.setattr(rate_limit.redis, "eval", lambda *args: calls.append(args) or len(calls))
    request = Request({"type": "http", "client": ("127.0.0.1", 1)})
    rate_limit.limit(request, "test", 1)
    with pytest.raises(HTTPException) as error:
        rate_limit.limit(request, "test", 1)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"
    assert calls[0][2] == calls[1][2]


def test_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch):
    def unavailable(*args):
        raise ConnectionError("private infrastructure details")
    monkeypatch.setattr(rate_limit.redis, "eval", unavailable)
    with pytest.raises(HTTPException) as error:
        rate_limit.limit(Request({"type": "http"}), "test", 1)
    assert error.value.status_code == 503
    assert "private" not in error.value.detail
