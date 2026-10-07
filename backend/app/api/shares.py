from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import share_limit
from app.core.security import bearer, current_user
from app.schemas.shares import CreateShare, Media, Share
from app.services import shares, storage

router = APIRouter(tags=["shares"], dependencies=[Depends(share_limit)])
ShareToken = Annotated[str, Path(min_length=40, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


@router.post("/clips/{clip_id}/shares", response_model=Share, status_code=201)
def create(clip_id: int, data: CreateShare, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> Share:
    return shares.create(db, user_id, clip_id, data)


@router.get("/clips/{clip_id}/media", response_model=Media)
def preview(clip_id: int, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> Media:
    return shares.media(shares.owned_clip(db, user_id, clip_id), user_id=user_id)


@router.get("/shares/{token}", response_model=Media)
def get_share(token: ShareToken, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db)) -> Media:
    user_id = current_user(credentials, db) if credentials else None
    return shares.media(shares.public_clip(db, token, user_id), share_token=token, user_id=user_id)


@router.delete("/shares/{token}", status_code=204)
def revoke(token: ShareToken, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> None:
    row = db.execute(text("DELETE FROM shares s USING clips c,videos v WHERE s.token=:token "
        "AND s.clip_id=c.id AND c.video_id=v.id AND v.user_id=:uid RETURNING s.id"),
        {"token": token, "uid": user_id}).first()
    if not row:
        raise HTTPException(404, "Share not found")
    db.commit()


@router.get("/media/{token}")
def media_file(token: Annotated[str, Path(max_length=2048)], db: Session = Depends(get_db)) -> FileResponse:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience="media",
            options={"require": ["aud", "exp", "clip_id"]})
        if payload.get("share"):
            clip = shares.public_clip(db, payload["share"], payload.get("user_id"))
            if clip["id"] != payload["clip_id"]:
                raise ValueError
        else:
            clip = shares.owned_clip(db, payload["user_id"], payload["clip_id"])
        path = storage.source(clip["storage_key"])
        if not path.is_file():
            raise HTTPException(404, "Clip file unavailable")
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, no-store"})
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(404, "Media link not found or expired") from None
