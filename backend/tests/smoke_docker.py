"""Run inside the API container of the disposable vclips-smoke Compose project."""
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import SessionLocal
from app.services import storage
from app.workers.cleanup import cleanup


def run() -> None:
    if make_url(settings.database_url).database != "vclips_smoke_test" or settings.app_env != "development":
        raise RuntimeError("Docker smoke checks require the disposable vclips_smoke_test database")
    with httpx.Client(base_url="http://frontend", timeout=60) as client:
        def request(method: str, path: str, expected: int = 200, **kwargs):
            response = client.request(method, path if path.startswith("/api/") else "/api" + path, **kwargs)
            assert response.status_code == expected, f"{method} endpoint returned {response.status_code}; expected {expected}"
            return response.json() if response.content and response.headers.get("content-type", "").startswith("application/json") else response

        assert client.get("/").status_code == 200
        assert "http://localhost:8000" not in client.get("/").headers["content-security-policy"]
        assert request("GET", "/health/db") == {"status": "ok"}
        account = {"email": "docker-smoke@example.test", "password": "docker-validation-password-only", "display_name": "Docker smoke"}
        auth = request("POST", "/auth/register", 201, json=account)
        client.headers["Authorization"] = "Bearer " + auth["access_token"]
        uid = request("GET", "/auth/me")["id"]
        assert request("POST", "/auth/login", json=account)["token_type"] == "bearer"
        with SessionLocal() as db:
            match_id = db.scalar(text("INSERT INTO matches(riot_match_id,map_id,queue_id,started_at,duration_ms) "
                "VALUES (:riot_id,'synthetic','DOCKER SMOKE: synthetic timestamps',now(),3000) RETURNING id"),
                {"riot_id": "smoke-" + secrets.token_hex(8)})
            db.execute(text("INSERT INTO match_players(match_id,puuid,user_id) VALUES (:match,'smoke-player',:uid)"),
                {"match": match_id, "uid": uid})
            db.execute(text("INSERT INTO rounds(match_id,round_number) VALUES (:match,0)"), {"match": match_id})
            db.execute(text("INSERT INTO kill_events(match_id,round_number,killer_puuid,victim_puuid,"
                "time_since_game_start_ms,time_since_round_start_ms) VALUES (:match,0,'smoke-player','smoke-opponent',1000,1000)"),
                {"match": match_id})
            db.commit()
        assert len(request("GET", f"/matches/{match_id}/kills")) == 1
        print("PASS: frontend proxy, fresh migrations, Redis-backed auth, synthetic match ownership", flush=True)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.mp4"
            subprocess.run([settings.ffmpeg_path, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=10", "-t", "3", "-c:v", "libx264", str(path)], check=True, capture_output=True)
            footage = path.read_bytes()
            video = request("POST", "/videos", 201, json={"match_id": match_id, "original_name": "../../tiny.mp4", "size_bytes": len(footage)})
            video_id = video["id"]
            split = len(footage) // 2
            request("PUT", f"/videos/{video_id}/chunks?offset=0", content=footage[:split])
            request("POST", f"/videos/{video_id}/complete", 409)
            request("PUT", f"/videos/{video_id}/chunks?offset=0", 409, content=footage[:split])
            request("PUT", f"/videos/{video_id}/chunks?offset={split}", content=footage[split:])
            assert request("POST", f"/videos/{video_id}/complete")["status"] == "validated"
        request("PATCH", f"/videos/{video_id}/sync", json={"sync_offset_ms": 0})
        print("PASS: chunk upload, offset conflict, incomplete upload, ffprobe validation, sync", flush=True)

        for mode in ("copy", "reencode"):
            ids = request("POST", f"/videos/{video_id}/clips", 202, json={"encode_mode": mode})
            assert len(ids) == 1
            assert request("POST", f"/videos/{video_id}/clips", 202, json={"encode_mode": mode}) == ids
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            clips = request("GET", f"/videos/{video_id}/clips")
            assert all(clip["status"] != "failed" for clip in clips), "Real RQ worker reported a failed job"
            if len(clips) == 2 and all(clip["status"] == "ready" for clip in clips):
                break
            time.sleep(2)
        else:
            raise AssertionError("Real RQ worker did not finish within 60 seconds")
        for clip in clips:
            assert clip["progress"] == 100 and clip["duration_ms"] > 0 and clip["peak_mem_kb"] > 0
            media = request("GET", f"/clips/{clip['id']}/media")
            assert media["url"].startswith(settings.frontend_url + "/api/media/")
            path = urlsplit(media["url"]).path
            downloaded = request("GET", path)
            assert downloaded.headers["content-type"].startswith("video/mp4")
            assert downloaded.content.startswith(b"\x00\x00")
            print(f"PASS: real RQ + FFmpeg {clip['encode_mode']}, {clip['duration_ms']} ms, peak {clip['peak_mem_kb']} KiB", flush=True)

        clip_id = clips[0]["id"]
        share = request("POST", f"/clips/{clip_id}/shares", 201, json={})
        private = request("POST", f"/clips/{clip_id}/shares", 201, json={"visibility": "private"})
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        request("POST", f"/clips/{clip_id}/shares", 422, json={"expires_at": expired})
        owner = client.headers.pop("Authorization")
        public = request("GET", "/shares/" + share["token"])
        assert request("GET", urlsplit(public["url"]).path).status_code == 200
        request("GET", "/shares/" + private["token"], 404)
        assert client.get("/share/" + share["token"]).status_code == 200
        client.headers["Authorization"] = owner
        request("DELETE", "/shares/" + share["token"], 204)
        request("GET", urlsplit(public["url"]).path, 404)
        request("GET", "/shares/" + share["token"], 404)
        print("PASS: anonymous share playback, private share rejection, expiry, revocation, public page route", flush=True)
        other = request("POST", "/auth/register", 201, json={**account, "email": "docker-other@example.test"})
        client.headers["Authorization"] = "Bearer " + other["access_token"]
        request("GET", f"/videos/{video_id}", 404)
        request("GET", f"/clips/{clip_id}/media", 404)
        request("POST", f"/clips/{clip_id}/shares", 404, json={})
        request("DELETE", "/shares/" + private["token"], 404)
        print("PASS: cross-user video, clip and share authorization", flush=True)
        with SessionLocal() as db:
            keys = [db.scalar(text("SELECT storage_key FROM videos WHERE id=:id"), {"id": video_id}),
                *db.scalars(text("SELECT storage_key FROM clips WHERE video_id=:id"), {"id": video_id}).all()]
            db.execute(text("UPDATE videos SET created_at=now()-interval '73 hours' WHERE id=:id"), {"id": video_id})
            db.commit()
        client.headers["Authorization"] = owner
        request("GET", f"/videos/{video_id}", 404)
        request("GET", "/shares/" + private["token"], 404)
        assert cleanup() == 1
        assert all(not storage.path_for(key).exists() for key in keys)
        with SessionLocal() as db:
            assert db.scalar(text("SELECT count(*) FROM processing_jobs")) == 0
            assert db.scalar(text("SELECT count(*) FROM shares")) == 0
        print("PASS: 72-hour media expiry, file deletion and cascading record cleanup", flush=True)
    with httpx.Client(base_url="http://api:8000", timeout=15) as direct:
        statuses = [direct.post("/auth/login", json={**account, "password": "incorrect-smoke-password"}).status_code for _ in range(21)]
        assert 401 in statuses and statuses[-1] == 429
    print("PASS: real Redis auth rate limit; COMPLETE Docker smoke pipeline passed", flush=True)


if __name__ == "__main__":
    run()
