import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services import riot_client
from app.workers import clips as worker


@pytest.fixture
def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "storage_bucket", "")
    path = tmp_path / "recording.mp4"
    subprocess.run([settings.ffmpeg_path, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=160x90:rate=10", "-t", "3", "-c:v", "libx264", str(path)], check=True, capture_output=True)
    return path.read_bytes()


@pytest.fixture
def signed_in(api_client):
    response = api_client.post("/auth/register", json={"email": "pipeline@example.com",
        "password": "pipeline-long-password", "display_name": "Player"})
    api_client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    return api_client.get("/auth/me").json()["id"]


@pytest.fixture
def match_id(api_client, signed_in, db_connection, monkeypatch):
    account_id = db_connection.scalar(text("INSERT INTO riot_accounts(user_id,puuid,game_name,tag_line,region) "
        "VALUES (:uid,'test-player','Test','0000','ap') RETURNING id"), {"uid": signed_in})
    payload = {"matchInfo": {"matchId": "test-match", "mapId": "test-map", "gameStartMillis": 1700000000000,
        "gameLengthMillis": 3000, "queueId": "test"}, "players": [{"puuid": "test-player"}],
        "roundResults": [{"roundNum": 0, "playerStats": [{"kills": [
            {"killer": "test-player", "victim": "test-victim", "timeSinceGameStartMillis": 1000, "timeSinceRoundStartMillis": 1000}]}]}]}
    monkeypatch.setattr(riot_client, "fetch_match", lambda *args: payload)
    response = api_client.post("/matches/import", json={"account_id": account_id, "match_id": "test-match"})
    assert response.status_code == 201
    again = api_client.post("/matches/import", json={"account_id": account_id, "match_id": "test-match"})
    assert again.json() == response.json()
    match = response.json()["id"]
    assert len(api_client.get(f"/matches/{match}/kills").json()) == 1
    return match


def upload(api_client, match_id, recording):
    start = api_client.post("/videos", json={"match_id": match_id, "original_name": "../../recording.mp4", "size_bytes": len(recording)})
    assert start.status_code == 201
    video_id = start.json()["id"]
    half = len(recording) // 2
    assert api_client.put(f"/videos/{video_id}/chunks?offset=0", content=recording[:half]).status_code == 200
    assert api_client.post(f"/videos/{video_id}/complete").status_code == 409
    assert api_client.put(f"/videos/{video_id}/chunks?offset=0", content=recording[:half]).status_code == 409
    assert api_client.put(f"/videos/{video_id}/chunks?offset={half}", content=recording[half:]).status_code == 200
    assert api_client.post(f"/videos/{video_id}/complete").status_code == 200
    return video_id


@pytest.mark.parametrize("mode", ["copy", "reencode"])
def test_recording_to_clip_and_revocable_share(api_client, match_id, recording, db_connection, monkeypatch, mode):
    video_id = upload(api_client, match_id, recording)
    assert api_client.patch(f"/videos/{video_id}/sync", json={"sync_offset_ms": 0}).status_code == 200
    response = api_client.post(f"/videos/{video_id}/clips", json={"encode_mode": mode})
    assert response.status_code == 202
    clip_id = response.json()[0]
    assert api_client.post(f"/videos/{video_id}/clips", json={"encode_mode": mode}).json() == [clip_id]
    assert api_client.patch(f"/videos/{video_id}/sync", json={"sync_offset_ms": 1}).status_code == 409
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint"))
    worker.process(clip_id)
    worker.process(clip_id) # duplicate delivery must not process a ready clip again
    clip = api_client.get(f"/videos/{video_id}/clips").json()[0]
    assert clip["status"] == "ready" and clip["progress"] == 100
    assert clip["duration_ms"] > 0
    share = api_client.post(f"/clips/{clip_id}/shares", json={}).json()
    media = api_client.get("/shares/" + share["token"])
    assert media.status_code == 200
    assert api_client.get(media.json()["url"]).content.startswith(b"\x00\x00")
    assert api_client.delete("/shares/" + share["token"]).status_code == 204
    assert api_client.get(media.json()["url"]).status_code == 404
    assert api_client.get("/shares/" + share["token"]).status_code == 404


def test_private_and_expired_shares_require_owner(api_client, match_id, recording, db_connection, monkeypatch):
    video_id = upload(api_client, match_id, recording)
    clip_id = api_client.post(f"/videos/{video_id}/clips", json={}).json()[0]
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint"))
    worker.process(clip_id)
    token = api_client.post(f"/clips/{clip_id}/shares", json={"visibility": "private"}).json()["token"]
    assert api_client.get("/shares/" + token).status_code == 200
    owner = api_client.headers.pop("Authorization")
    assert api_client.get("/shares/" + token).status_code == 404
    api_client.headers["Authorization"] = owner
    expires = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert api_client.post(f"/clips/{clip_id}/shares", json={"expires_at": expires}).status_code == 422
    db_connection.execute(text("UPDATE shares SET expires_at=:expiry WHERE token=:token"),
        {"expiry": datetime.now(timezone.utc) - timedelta(minutes=1), "token": token})
    assert api_client.get("/shares/" + token).status_code == 404


def test_other_user_cannot_read_or_modify_recording(api_client, match_id, recording):
    video_id = upload(api_client, match_id, recording)
    token = api_client.post("/auth/register", json={"email": "other@example.com", "password": "other-long-password",
        "display_name": "Other"}).json()["access_token"]
    api_client.headers["Authorization"] = "Bearer " + token
    for path in [f"/videos/{video_id}", f"/videos/{video_id}/clips", f"/matches/{match_id}/kills"]:
        assert api_client.get(path).status_code == 404
    assert api_client.put(f"/videos/{video_id}/chunks?offset=0", content=b"x").status_code == 404
    assert api_client.post(f"/videos/{video_id}/clips", json={}).status_code == 404


def test_upload_rejects_oversized_chunks_and_fake_video(api_client, match_id, recording, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    assert api_client.post("/videos", json={"match_id": match_id, "original_name": "x.mp4", "size_bytes": 101}).status_code == 413
    video_id = api_client.post("/videos", json={"match_id": match_id, "original_name": "x.mp4", "size_bytes": 4}).json()["id"]
    monkeypatch.setattr(settings, "max_chunk_bytes", 2)
    assert api_client.put(f"/videos/{video_id}/chunks?offset=0", content=b"fake").status_code == 413
    monkeypatch.setattr(settings, "max_chunk_bytes", 8)
    assert api_client.put(f"/videos/{video_id}/chunks?offset=0", content=b"fake").status_code == 200
    assert api_client.post(f"/videos/{video_id}/complete").status_code == 422
    assert api_client.get(f"/videos/{video_id}").json()["status"] == "failed"


def test_worker_failure_records_safe_error(api_client, match_id, recording, db_connection, monkeypatch):
    video_id = upload(api_client, match_id, recording)
    clip_id = api_client.post(f"/videos/{video_id}/clips", json={}).json()[0]
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint"))
    def fail(*args):
        raise RuntimeError("secret path and internal details")
    monkeypatch.setattr(worker, "encode", fail)
    with pytest.raises(RuntimeError, match="Clip processing failed"):
        worker.process(clip_id)
    clip = api_client.get(f"/videos/{video_id}/clips").json()[0]
    assert clip["status"] == "failed" and clip["error"] == "Clip processing failed"
