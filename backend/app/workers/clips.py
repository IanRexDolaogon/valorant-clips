import os
import subprocess
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.services import storage


def encode(source, output, start_ms: int, end_ms: int, mode: str) -> None:
    if mode not in {"copy", "reencode"} or start_ms < 0 or end_ms <= start_ms:
        raise ValueError("Invalid clip request")
    args = [settings.ffmpeg_path, "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe",
        "-ss", str(start_ms / 1000), "-i", str(source), "-t", str((end_ms - start_ms) / 1000),
        "-map", "0:v:0", "-map", "0:a:0?"]
    args += ["-c", "copy"] if mode == "copy" else ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
    # Stream copy starts at keyframes; choose reencode for exact timing.
    subprocess.run(args + ["-movflags", "+faststart", "-f", "mp4", str(output)],
        check=True, capture_output=True, timeout=settings.ffmpeg_timeout_seconds)
    storage.probe(output)


def peak_memory() -> int | None:
    if os.name == "nt":
        # ponytail: per-job RSS is measured in Linux RQ child processes; run the Docker worker for Windows metrics.
        return None
    import resource
    return int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


def failed(clip_id: int) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE clips SET status='failed' WHERE id=:id AND status!='ready'"), {"id": clip_id})
        db.execute(text("UPDATE processing_jobs SET status='failed',error='Clip processing failed',finished_at=now() "
            "WHERE clip_id=:id AND status!='ready'"), {"id": clip_id})
        db.commit()


def failure_callback(job, connection, *args, **kwargs) -> None:
    failed(int(job.args[0]))


def process(clip_id: int) -> None:
    started = time.perf_counter()
    output = None
    try:
        with SessionLocal() as db:
            clip = db.execute(text("SELECT c.*,v.storage_key AS source_key,v.duration_ms FROM clips c JOIN videos v "
                "ON v.id=c.video_id WHERE c.id=:id AND v.status='validated' FOR UPDATE OF c"),
                {"id": clip_id}).mappings().first()
            if not clip or clip["status"] != "queued":
                return
            clip = dict(clip)
            if clip["end_ms"] > clip["duration_ms"]:
                raise ValueError("Clip exceeds recording")
            db.execute(text("UPDATE clips SET status='processing' WHERE id=:id"), {"id": clip_id})
            db.execute(text("UPDATE processing_jobs SET status='processing',progress=10,started_at=now() WHERE clip_id=:id"), {"id": clip_id})
            db.commit()
        key = uuid.uuid4().hex + ".mp4"
        output = storage.path_for(key)
        temporary = output.with_suffix(".partial")
        try:
            encode(storage.source(clip["source_key"]), temporary, clip["start_ms"], clip["end_ms"], clip["encode_mode"])
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        storage.publish(key)
        with SessionLocal() as db:
            db.execute(text("UPDATE clips SET status='ready',storage_key=:key WHERE id=:id"), {"key": key, "id": clip_id})
            db.execute(text("UPDATE processing_jobs SET status='ready',progress=100,duration_ms=:duration,"
                "peak_mem_kb=:memory,error=NULL,finished_at=:finished WHERE clip_id=:id"),
                {"duration": int((time.perf_counter() - started) * 1000), "memory": peak_memory(),
                 "finished": datetime.now(timezone.utc), "id": clip_id})
            db.commit()
    except Exception:
        if output:
            output.unlink(missing_ok=True)
        failed(clip_id)
        raise RuntimeError("Clip processing failed") from None
