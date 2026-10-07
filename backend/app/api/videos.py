import tempfile
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import upload_limit
from app.core.security import current_user
from app.schemas.videos import Clip, Offset, Plan, Upload, Video
from app.services import clip_planner, videos

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[Depends(upload_limit)])


@router.post("", response_model=Video, status_code=201)
def start(data: Upload, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return videos.start(db, user_id, data)


@router.get("", response_model=list[Video])
def list_videos(user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("SELECT * FROM videos WHERE user_id=:uid ORDER BY id DESC LIMIT 100"),
        {"uid": user_id}).mappings()]


@router.get("/{video_id}", response_model=Video)
def get_video(video_id: int, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return videos.owned_video(db, user_id, video_id)


@router.put("/{video_id}/chunks", response_model=Video)
async def chunk(video_id: int, request: Request, offset: Annotated[int, Query(ge=0)],
    user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    videos.owned_video(db, user_id, video_id)
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=settings.max_chunk_bytes) as body:
        async for piece in request.stream():
            size += len(piece)
            if size > settings.max_chunk_bytes:
                raise HTTPException(413, "Chunk exceeds size limit")
            body.write(piece)
        body.seek(0)
        return videos.append(db, user_id, video_id, offset, body, size)


@router.post("/{video_id}/complete", response_model=Video)
def complete(video_id: int, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return videos.finish(db, user_id, video_id)


@router.patch("/{video_id}/sync", response_model=Video)
def sync(video_id: int, data: Offset, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return videos.set_offset(db, user_id, video_id, data.sync_offset_ms)


@router.post("/{video_id}/clips", response_model=list[int], status_code=202)
def plan(video_id: int, data: Plan, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> list[int]:
    return clip_planner.plan(db, user_id, video_id, data.encode_mode)


@router.get("/{video_id}/clips", response_model=list[Clip])
def clips(video_id: int, user_id: int = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    videos.owned_video(db, user_id, video_id)
    return [dict(row) for row in db.execute(text("SELECT c.id,c.video_id,c.kill_event_id,c.start_ms,c.end_ms,c.encode_mode,"
        "c.status,j.progress,j.duration_ms,j.peak_mem_kb,j.error FROM clips c JOIN processing_jobs j ON j.clip_id=c.id "
        "WHERE c.video_id=:id ORDER BY c.start_ms,c.id"), {"id": video_id}).mappings()]
