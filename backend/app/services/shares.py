import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.shares import CreateShare, Media, Share
from app.services import storage


def owned_clip(db: Session, user_id: int, clip_id: int) -> dict:
    clip = db.execute(text("SELECT c.* FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=:id AND v.user_id=:uid"),
        {"id": clip_id, "uid": user_id}).mappings().first()
    if not clip:
        raise HTTPException(404, "Clip not found")
    if clip["status"] != "ready":
        raise HTTPException(409, "Clip is not ready")
    return dict(clip)


def create(db: Session, user_id: int, clip_id: int, data: CreateShare) -> Share:
    owned_clip(db, user_id, clip_id)
    if data.expires_at and data.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(422, "Share expiry must be in the future")
    token = secrets.token_urlsafe(32)
    db.execute(text("INSERT INTO shares(clip_id,token,visibility,expires_at) VALUES (:id,:token,:visibility,:expires)"),
        {"id": clip_id, "token": token, "visibility": data.visibility, "expires": data.expires_at})
    db.commit()
    return Share(token=token, url=settings.frontend_url + "/share/" + token,
        visibility=data.visibility, expires_at=data.expires_at)


def public_clip(db: Session, token: str, user_id: int | None = None) -> dict:
    share = db.execute(text("SELECT c.*,s.expires_at,s.visibility,v.user_id FROM shares s "
        "JOIN clips c ON c.id=s.clip_id JOIN videos v ON v.id=c.video_id "
        "WHERE s.token=:token AND c.status='ready' AND (s.expires_at IS NULL OR s.expires_at>now())"),
        {"token": token}).mappings().first()
    if not share or share["visibility"] == "private" and share["user_id"] != user_id:
        raise HTTPException(404, "Share not found or expired")
    return dict(share)


def media(clip: dict, *, share_token: str | None = None, user_id: int | None = None) -> Media:
    now = datetime.now(timezone.utc)
    expires = min(now + timedelta(seconds=60), clip.get("expires_at") or now + timedelta(seconds=60))
    seconds = int((expires - now).total_seconds())
    if seconds < 1:
        raise HTTPException(404, "Share expired")
    if settings.storage_bucket:
        url = storage.s3().generate_presigned_url("get_object", Params={"Bucket": settings.storage_bucket,
            "Key": clip["storage_key"]}, ExpiresIn=seconds)
    else:
        token = jwt.encode({"aud": "media", "exp": expires, "clip_id": clip["id"],
            "share": share_token, "user_id": user_id}, settings.jwt_secret, algorithm="HS256")
        url = settings.public_api_url + "/media/" + token
    return Media(url=url, expires_in=seconds)
