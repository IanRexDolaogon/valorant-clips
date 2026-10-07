from hashlib import sha256

from fastapi import HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

redis = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
COUNTER = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""


def limit(request: Request, category: str, maximum: int) -> None:
    address = request.client.host if request.client else "unknown"
    key = "rate:" + category + ":" + sha256(address.encode()).hexdigest()
    try:
        count = redis.eval(COUNTER, 1, key)
    except RedisError:
        raise HTTPException(503, "Rate limiter unavailable") from None
    if count > maximum:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": "60"})


def auth_limit(request: Request) -> None:
    limit(request, "auth", settings.auth_requests_per_minute)


def upload_limit(request: Request) -> None:
    limit(request, "upload", settings.upload_requests_per_minute)


def share_limit(request: Request) -> None:
    limit(request, "share", settings.share_requests_per_minute)
