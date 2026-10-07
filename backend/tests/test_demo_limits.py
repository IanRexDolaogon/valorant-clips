import asyncio
import subprocess
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.uploads import UploadLimit
from app.services import storage
from app.workers import cleanup, clips as worker
from tests.test_pipeline import recording, signed_in, match_id, upload


@pytest.mark.parametrize("header,pieces,expected", [
    (b"10000001", [], 413),
    (None, [b"x" * 5_000_000, b"x" * 5_000_001], 413),
    (None, [b"x" * 10_000_000], 204),
])
def test_middleware_rejects_before_handler(header, pieces, expected):
    called = []
    sent = []
    messages = [{"type": "http.request", "body": piece, "more_body": i < len(pieces)-1}
        for i, piece in enumerate(pieces)]
    async def handler(scope, receive, send):
        called.append(True)
        assert len((await receive())["body"]) == 10_000_000
        await send({"type": "http.response.start", "status": 204, "headers": []})
    async def receive():
        return messages.pop(0)
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "path": "/videos/1/chunks", "method": "PUT",
        "headers": [(b"content-length", header)] if header else []}
    asyncio.run(UploadLimit(handler)(scope, receive, send))
    assert sent[0]["status"] == expected
    assert bool(called) == (expected == 204)


@pytest.mark.parametrize("duration,status", [(15, 200), (15.1, 400)])
def test_duration_boundary_before_publication(api_client, match_id, tmp_path, monkeypatch, duration, status):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    path = tmp_path / "length.mp4"
    subprocess.run([settings.ffmpeg_path, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=size=32x32:rate=10", "-t", str(duration), "-c:v", "libx264", str(path)], check=True, capture_output=True)
    body = path.read_bytes()
    video = api_client.post("/videos", json={"match_id": match_id, "original_name": "length.mp4", "size_bytes": len(body)}).json()
    assert api_client.put(f"/videos/{video['id']}/chunks?offset=0", content=body).status_code == 200
    published = []
    monkeypatch.setattr(storage, "publish", lambda key: published.append(key))
    assert api_client.post(f"/videos/{video['id']}/complete").status_code == status
    assert bool(published) == (status == 200)


def test_declared_total_cannot_bypass_limit_with_small_chunks(api_client, match_id):
    assert api_client.post("/videos", json={"match_id": match_id,
        "original_name": "too-big.mp4", "size_bytes": 10_000_001}).status_code == 413


def expire(db, video_id):
    db.execute(text("UPDATE videos SET created_at=now()-interval '73 hours' WHERE id=:id"), {"id": video_id})


def test_expiry_blocks_access_and_cleanup_deletes_storage_first(api_client, match_id, recording, db_connection, monkeypatch):
    video_id = upload(api_client, match_id, recording)
    row = db_connection.execute(text("SELECT created_at,expires_at FROM videos WHERE id=:id"), {"id": video_id}).one()
    assert row.expires_at - row.created_at == timedelta(hours=72)
    clip_id = api_client.post(f"/videos/{video_id}/clips", json={}).json()[0]
    factory = sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(cleanup, "SessionLocal", factory)
    worker.process(clip_id)
    share = api_client.post(f"/clips/{clip_id}/shares", json={}).json()
    media = api_client.get("/shares/" + share["token"]).json()["url"]
    keys = db_connection.execute(text("SELECT v.storage_key,c.storage_key FROM videos v JOIN clips c ON c.video_id=v.id WHERE v.id=:id"),
        {"id": video_id}).one()
    expire(db_connection, video_id)
    for path in [f"/videos/{video_id}", f"/clips/{clip_id}/media", "/shares/"+share["token"], media]:
        assert api_client.get(path).status_code == 404
    assert api_client.get("/videos").json() == []
    assert api_client.post(f"/videos/{video_id}/clips", json={}).status_code == 404
    monkeypatch.setattr(settings, "storage_bucket", "fake-demo-bucket")
    calls = []
    class Bucket:
        def delete_object(self, **kwargs):
            assert db_connection.scalar(text("SELECT id FROM videos WHERE id=:id"), {"id": video_id})
            assert storage.path_for(kwargs["Key"]).exists()
            calls.append(kwargs)
    monkeypatch.setattr(storage, "s3", Bucket)
    assert cleanup.cleanup() == 1
    assert {call["Key"] for call in calls} == set(keys)
    assert all(call["Bucket"] == "fake-demo-bucket" for call in calls)
    assert all(not storage.path_for(key).exists() for key in keys)
    assert db_connection.scalar(text("SELECT count(*) FROM videos")) == 0
    for table in ("clips", "shares", "processing_jobs"):
        assert db_connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
    assert cleanup.cleanup() == 0


def test_failed_storage_delete_keeps_row_for_retry(api_client, match_id, recording, db_connection, monkeypatch):
    video_id = upload(api_client, match_id, recording)
    monkeypatch.setattr(cleanup, "SessionLocal", sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint"))
    assert cleanup.cleanup() == 0  # unexpired media survives
    expire(db_connection, video_id)
    key = db_connection.scalar(text("SELECT storage_key FROM videos WHERE id=:id"), {"id": video_id})
    monkeypatch.setattr(settings, "storage_bucket", "fake-demo-bucket")
    class Unavailable:
        def delete_object(self, **kwargs):
            raise OSError("unavailable")
    monkeypatch.setattr(storage, "s3", Unavailable)
    assert cleanup.cleanup() == 0
    assert storage.path_for(key).exists()
    assert db_connection.scalar(text("SELECT id FROM videos WHERE id=:id"), {"id": video_id}) == video_id
    monkeypatch.setattr(settings, "storage_bucket", "")
    assert cleanup.cleanup() == 1


def test_worker_skips_expired_upload(api_client, match_id, recording, db_connection, monkeypatch):
    video_id = upload(api_client, match_id, recording)
    clip_id = api_client.post(f"/videos/{video_id}/clips", json={}).json()[0]
    expire(db_connection, video_id)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint"))
    monkeypatch.setattr(worker, "encode", lambda *args: pytest.fail("Expired upload must never be encoded"))
    worker.process(clip_id)
