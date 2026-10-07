from typing import Annotated

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import auth_limit
from app.core.security import current_user
from app.services import matches, riot_client

router = APIRouter(tags=["matches"], dependencies=[Depends(auth_limit)])


class ImportMatch(BaseModel):
    account_id: int = Field(gt=0)
    match_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")


class Identifier(BaseModel):
    id: int


class Link(BaseModel):
    url: str


@router.get("/riot/link", response_model=Link)
def link(region: str, response: Response, user_id: int = Depends(current_user)) -> Link:
    from urllib.parse import parse_qs, urlparse
    url = riot_client.link_url(user_id, region)
    state = parse_qs(urlparse(url).query)["state"][0]
    response.set_cookie("rso_state", state, httponly=True, secure=settings.app_env == "production", samesite="lax", max_age=300)
    return Link(url=url)


@router.get("/riot/callback")
def callback(
    code: Annotated[str, Query(min_length=1, max_length=4096)],
    state: Annotated[str, Query(min_length=20, max_length=100)],
    rso_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not rso_state or not secrets.compare_digest(state, rso_state):
        raise HTTPException(400, "Riot linking request does not match this browser")
    user_id, region, account = riot_client.finish_link(code, state)
    try:
        db.execute(text("INSERT INTO riot_accounts(user_id,puuid,game_name,tag_line,region) "
            "VALUES (:uid,:puuid,:name,:tag,:region) ON CONFLICT (puuid) DO UPDATE SET "
            "game_name=EXCLUDED.game_name,tag_line=EXCLUDED.tag_line,region=EXCLUDED.region "
            "WHERE riot_accounts.user_id=EXCLUDED.user_id RETURNING id"),
            {"uid": user_id, "puuid": account.puuid, "name": account.gameName, "tag": account.tagLine, "region": region}).scalar_one()
        db.commit()
    except (IntegrityError, NoResultFound):
        db.rollback()
        raise HTTPException(409, "Riot account is linked to another user") from None
    response = RedirectResponse(settings.frontend_url, status_code=303)
    response.delete_cookie("rso_state")
    return response


@router.get("/riot/accounts", response_model=list[dict])
def accounts(user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text(
        "SELECT id,game_name,tag_line,region FROM riot_accounts WHERE user_id=:uid ORDER BY id"), {"uid": user_id}).mappings()]


@router.post("/matches/import", response_model=Identifier, status_code=201)
def import_match(data: ImportMatch, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> Identifier:
    return Identifier(id=matches.ingest(db, user_id, data.account_id, data.match_id))


@router.get("/matches", response_model=list[dict])
def list_matches(user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("SELECT DISTINCT m.* FROM matches m JOIN match_players p "
        "ON p.match_id=m.id WHERE p.user_id=:uid ORDER BY m.started_at DESC LIMIT 100"), {"uid": user_id}).mappings()]


@router.get("/matches/{match_id}/kills", response_model=list[dict])
def kills(match_id: int, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    matches.owned_match(db, user_id, match_id)
    return [dict(row) for row in db.execute(text("SELECT k.* FROM kill_events k JOIN match_players p "
        "ON p.match_id=k.match_id AND p.puuid=k.killer_puuid WHERE k.match_id=:id AND p.user_id=:uid "
        "ORDER BY k.time_since_game_start_ms,k.id"), {"id": match_id, "uid": user_id}).mappings()]
