import os
import shutil
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.videos import Upload
from app.services import matches, storage


def owned_video(db: Session, user_id: int, video_id: int, *, lock: bool = False) -> dict:
    query = "SELECT * FROM videos WHERE id=:id AND user_id=:uid"
    if lock:
        query += " FOR UPDATE"
    video = db.execute(text(query), {"id": video_id, "uid": user_id}).mappings().first()
    if not video:
        raise HTTPException(404, "Video not found")
    return dict(video)


def start(db: Session, user_id: int, data: Upload) -> dict:
    if data.size_bytes > settings.max_upload_bytes:
        raise HTTPException(413, "Recording exceeds upload size limit")
    matches.owned_match(db, user_id, data.match_id)
    key = uuid.uuid4().hex + ".source"
    video = db.execute(text("INSERT INTO videos(user_id,match_id,storage_key,original_name,size_bytes) "
        "VALUES (:uid,:match,:key,:name,:size) RETURNING *"),
        {"uid": user_id, "match": data.match_id, "key": key, "name": data.original_name, "size": data.size_bytes}).mappings().one()
    db.commit()
    return dict(video)


def append(db: Session, user_id: int, video_id: int, offset: int, chunk, size: int) -> dict:
    video = owned_video(db, user_id, video_id, lock=True)
    if video["status"] != "uploading" or offset != video["upload_offset_bytes"]:
        raise HTTPException(409, "Upload offset or status changed; refresh the upload")
    if size <= 0 or size > settings.max_chunk_bytes or offset + size > video["size_bytes"]:
        raise HTTPException(413, "Chunk exceeds recording or chunk size limit")
    path = storage.path_for(video["storage_key"])
    # The DB offset is authoritative; remove an uncommitted tail after a crash.
    if offset > 0 and (not path.exists() or path.stat().st_size < offset):
        raise HTTPException(409, "Upload file is incomplete; start a new upload")
    try:
        with path.open("r+b" if path.exists() else "w+b") as output:
            output.truncate(offset)
            output.seek(offset)
            shutil.copyfileobj(chunk, output)
            output.flush()
            os.fsync(output.fileno())
        db.execute(text("UPDATE videos SET upload_offset_bytes=:offset WHERE id=:id"),
            {"offset": offset + size, "id": video_id})
        db.commit()
    except OSError:
        db.rollback()
        raise HTTPException(503, "Recording storage unavailable; retry the chunk") from None
    return owned_video(db, user_id, video_id)


def finish(db: Session, user_id: int, video_id: int) -> dict:
    video = owned_video(db, user_id, video_id, lock=True)
    if video["status"] == "validated":
        return video
    if video["status"] != "uploading" or video["upload_offset_bytes"] != video["size_bytes"]:
        raise HTTPException(409, "Recording upload is incomplete")
    path = storage.path_for(video["storage_key"])
    try:
        if not path.exists() or path.stat().st_size != video["size_bytes"]:
            raise HTTPException(422, "Recording size does not match upload")
        duration = storage.probe(path)
        storage.publish(video["storage_key"])
    except HTTPException:
        db.execute(text("UPDATE videos SET status='failed' WHERE id=:id"), {"id": video_id})
        db.commit()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(503, "Recording storage unavailable; retry completion") from None
    db.execute(text("UPDATE videos SET status='validated',duration_ms=:duration WHERE id=:id"),
        {"duration": duration, "id": video_id})
    db.commit()
    return owned_video(db, user_id, video_id)


def set_offset(db: Session, user_id: int, video_id: int, offset: int) -> dict:
    video = owned_video(db, user_id, video_id, lock=True)
    if video["status"] != "validated":
        raise HTTPException(409, "Validate the recording before setting its offset")
    if db.scalar(text("SELECT id FROM clips WHERE video_id=:id LIMIT 1"), {"id": video_id}):
        raise HTTPException(409, "This recording already has planned clips; upload again to use a different offset")
    db.execute(text("UPDATE videos SET sync_offset_ms=:offset WHERE id=:id"), {"id": video_id, "offset": offset})
    db.commit()
    return owned_video(db, user_id, video_id)
