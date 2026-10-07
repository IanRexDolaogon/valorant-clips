"""Riot VAL-MATCH-V1 and approved RSO client; tests replace the HTTP transport."""
import json
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.rate_limit import redis

REGIONS = {"na", "eu", "ap", "kr", "br", "latam"}


def request_json(method: str, url: str, **kwargs) -> dict:
    try:
        with httpx.Client(timeout=15) as client:
            response = client.request(method, url, **kwargs)
        if response.status_code == 429:
            raise HTTPException(429, "Riot rate limit reached; retry later", headers={"Retry-After": "60"})
        if response.status_code in {401, 403}:
            raise HTTPException(503, "Riot access is unavailable; check approved credentials")
        if response.status_code == 404:
            raise HTTPException(404, "Riot match or account not found")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Riot request failed") from None


def link_url(user_id: int, region: str) -> str:
    if region not in REGIONS:
        raise HTTPException(422, "Unsupported Riot region")
    if not all((settings.riot_client_id, settings.riot_client_secret, settings.riot_redirect_uri)):
        raise HTTPException(503, "Riot linking requires an approved production RSO client")
    state = secrets.token_urlsafe(32)
    try:
        redis.set("rso:" + state, json.dumps({"user_id": user_id, "region": region}), ex=300)
    except RedisError:
        raise HTTPException(503, "Account linking unavailable") from None
    return settings.riot_auth_url + "?" + urlencode({
        "client_id": settings.riot_client_id, "redirect_uri": settings.riot_redirect_uri,
        "response_type": "code", "scope": "openid", "state": state,
    })


class RiotAccount(BaseModel):
    puuid: str = Field(min_length=1, max_length=100)
    gameName: str = Field(min_length=1, max_length=50)
    tagLine: str = Field(min_length=1, max_length=10)


def finish_link(code: str, state: str) -> tuple[int, str, RiotAccount]:
    try:
        value = redis.getdel("rso:" + state)
    except RedisError:
        raise HTTPException(503, "Account linking unavailable") from None
    if not value:
        raise HTTPException(400, "Invalid or expired Riot linking request")
    pending = json.loads(value)
    tokens = request_json("POST", settings.riot_token_url,
        auth=(settings.riot_client_id, settings.riot_client_secret),
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.riot_redirect_uri})
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        raise HTTPException(502, "Invalid Riot token response")
    try:
        account = RiotAccount.model_validate(request_json("GET", settings.riot_account_url,
            headers={"Authorization": "Bearer " + access}))
    except ValidationError:
        raise HTTPException(502, "Invalid Riot account response") from None
    return pending["user_id"], pending["region"], account


def fetch_match(region: str, match_id: str) -> dict:
    if region not in REGIONS:
        raise HTTPException(422, "Unsupported Riot region")
    if not settings.riot_api_key:
        raise HTTPException(503, "Riot API key is not configured")
    # Cache persisted matches in PostgreSQL at ingestion; do not retry in loops.
    return request_json("GET", f"https://{region}.api.riotgames.com/val/match/v1/matches/{match_id}",
        headers={"X-Riot-Token": settings.riot_api_key})
