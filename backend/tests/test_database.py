import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.main import app


def test_migrations_create_all_tables_and_indexes(db_connection):
    inspector = inspect(db_connection)
    assert set(inspector.get_table_names()) == {
        "alembic_version", "users", "riot_accounts", "matches", "match_players",
        "rounds", "kill_events", "videos", "clips", "shares", "processing_jobs",
    }
    assert db_connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
    assert "idx_kills_match_time" in {
        index["name"] for index in inspector.get_indexes("kill_events")
    }
    index = next(i for i in inspector.get_indexes("clips") if i["name"] == "idx_clips_status")
    assert index["dialect_options"]["postgresql_where"]
    assert any(c["column_names"] == ["token"] for c in inspector.get_unique_constraints("shares"))


def test_database_rejects_invalid_clip_window(db_connection):
    with db_connection.begin_nested():
        user_id = db_connection.scalar(text(
            "INSERT INTO users(email,password_hash,display_name) "
            "VALUES ('constraint@example.com','test','Test') RETURNING id"
        ))
        video_id = db_connection.scalar(text(
            "INSERT INTO videos(user_id,storage_key,original_name,size_bytes) "
            "VALUES (:user_id,'test-video','test.mp4',1) RETURNING id"
        ), {"user_id": user_id})
        with pytest.raises(IntegrityError):
            with db_connection.begin_nested():
                db_connection.execute(text(
                    "INSERT INTO clips(video_id,start_ms,end_ms) VALUES (:id,100,100)"
                ), {"id": video_id})


def test_health_connects_to_postgresql(db_connection):
    with Session(bind=db_connection, join_transaction_mode="create_savepoint") as session:
        app.dependency_overrides[get_db] = lambda: session
        try:
            assert TestClient(app).get("/health/db").json() == {"status": "ok"}
        finally:
            app.dependency_overrides.clear()
