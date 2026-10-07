from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.videos import owned_video


def window(kill_ms: int, offset_ms: int, duration_ms: int, before_ms: int, after_ms: int) -> tuple[int, int] | None:
    if min(kill_ms, duration_ms, before_ms, after_ms) < 0 or before_ms + after_ms == 0:
        raise ValueError("Invalid clip timing")
    time = kill_ms + offset_ms
    if time < 0 or time >= duration_ms:
        return None
    start, end = max(0, time - before_ms), min(duration_ms, time + after_ms)
    return (start, end) if end > start else None


def plan(db: Session, user_id: int, video_id: int, mode: str) -> list[int]:
    video = owned_video(db, user_id, video_id, lock=True)
    if video["status"] != "validated" or not video["duration_ms"]:
        raise HTTPException(409, "Validate the recording before planning clips")
    kills = db.execute(text("SELECT k.id,k.time_since_game_start_ms FROM kill_events k "
        "JOIN match_players p ON p.match_id=k.match_id AND p.puuid=k.killer_puuid "
        "WHERE k.match_id=:match AND p.user_id=:uid ORDER BY k.time_since_game_start_ms,k.id"),
        {"match": video["match_id"], "uid": user_id}).mappings()
    ids = []
    for kill in kills:
        bounds = window(kill["time_since_game_start_ms"], video["sync_offset_ms"], video["duration_ms"],
            settings.padding_before_ms, settings.padding_after_ms)
        if not bounds:
            continue
        start, end = bounds
        clip_id = db.scalar(text("INSERT INTO clips(video_id,kill_event_id,start_ms,end_ms,encode_mode) "
            "VALUES (:video,:kill,:start,:end,:mode) ON CONFLICT ON CONSTRAINT uq_clip_window "
            "DO UPDATE SET video_id=EXCLUDED.video_id RETURNING id"),
            {"video": video_id, "kill": kill["id"], "start": start, "end": end, "mode": mode})
        db.execute(text("INSERT INTO processing_jobs(clip_id,encode_mode) VALUES (:clip,:mode) ON CONFLICT (clip_id) DO NOTHING"),
            {"clip": clip_id, "mode": mode})
        ids.append(clip_id)
    db.commit()
    return ids
