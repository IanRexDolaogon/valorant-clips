from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rate_limit import auth_limit
from app.core.security import current_user
from app.schemas.auth import Login, Register, Token, User
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(auth_limit)])


@router.post("/register", response_model=Token, status_code=201)
def register(data: Register, db: Session = Depends(get_db)) -> Token:
    return Token(access_token=auth.register(db, data))


@router.post("/login", response_model=Token)
def login(data: Login, db: Session = Depends(get_db)) -> Token:
    return Token(access_token=auth.login(db, data))


@router.get("/me", response_model=User)
def me(user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> User:
    return User(**db.execute(text(
        "SELECT id,email,display_name FROM users WHERE id=:id"
    ), {"id": user_id}).mappings().one())
