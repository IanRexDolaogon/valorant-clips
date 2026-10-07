from typing import Literal
from datetime import datetime

from pydantic import BaseModel, Field


class Upload(BaseModel):
    match_id: int = Field(gt=0)
    original_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class Video(BaseModel):
    id: int
    match_id: int | None
    original_name: str
    size_bytes: int
    upload_offset_bytes: int
    duration_ms: int | None
    sync_offset_ms: int
    status: str
    expires_at: datetime


class Offset(BaseModel):
    sync_offset_ms: int = Field(ge=-2147483648, le=2147483647)


class Plan(BaseModel):
    encode_mode: Literal["copy", "reencode"] = "reencode"


class Clip(BaseModel):
    id: int
    video_id: int
    kill_event_id: int | None
    start_ms: int
    end_ms: int
    encode_mode: str
    status: str
    progress: int
    duration_ms: int | None
    peak_mem_kb: int | None
    error: str | None
