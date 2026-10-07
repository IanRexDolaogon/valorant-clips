from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def token_for(user_id: int) -> str:
    if len(settings.jwt_secret) < 32 or settings.jwt_secret == "change_me":
        raise HTTPException(503, "Configure a random JWT_SECRET of at least 32 characters")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.token_minutes)},
        settings.jwt_secret, algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> int:
    try:
        if credentials is None or len(settings.jwt_secret) < 32:
            raise ValueError
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
        user_id = int(payload["sub"])
        if user_id <= 0 or not db.scalar(text("SELECT id FROM users WHERE id=:id"), {"id": user_id}):
            raise ValueError
        return user_id
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from None
