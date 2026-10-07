from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import password_hasher, token_for
from app.schemas.auth import Login, Register

dummy_hash = password_hasher.hash("invalid-password-for-unknown-user")


def register(db: Session, data: Register) -> str:
    # Check token configuration before committing a user who cannot log in.
    token_for(1)
    try:
        user_id = db.scalar(text(
            "INSERT INTO users(email,password_hash,display_name) "
            "VALUES (:email,:password_hash,:name) RETURNING id"
        ), {"email": data.email, "password_hash": password_hasher.hash(data.password), "name": data.display_name})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered") from None
    return token_for(user_id)


def login(db: Session, data: Login) -> str:
    row = db.execute(text(
        "SELECT id,password_hash FROM users WHERE lower(email)=:email"
    ), {"email": data.email}).mappings().first()
    try:
        valid = password_hasher.verify(row["password_hash"] if row else dummy_hash, data.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not row or not valid:
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    return token_for(row["id"])
