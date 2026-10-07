import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.api.auth import router as auth_router
from app.api.matches import router as matches_router
from app.api.videos import router as videos_router
from app.api.shares import router as shares_router
from app.core.config import settings
from app.core.uploads import UploadLimit

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env == "production":
        if len(settings.jwt_secret) < 32 or not settings.frontend_url.startswith("https://") or not settings.public_api_url.startswith("https://"):
            raise RuntimeError("Production requires a strong JWT secret and HTTPS public URLs")
    yield


app = FastAPI(title="Valorant Clips API", lifespan=lifespan)
app.add_middleware(UploadLimit)
app.include_router(auth_router)
app.include_router(matches_router)
app.include_router(videos_router)
app.include_router(shares_router)


@app.exception_handler(RequestValidationError)
async def invalid_input(request, error: RequestValidationError) -> JSONResponse:
    # Validation responses must not echo passwords or uploaded request data.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]} for item in error.errors()
    ]})


@app.exception_handler(SQLAlchemyError)
async def unavailable_database(request, error: SQLAlchemyError) -> JSONResponse:
    logging.error("Database operation failed (%s)", type(error).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database operation unavailable"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}
