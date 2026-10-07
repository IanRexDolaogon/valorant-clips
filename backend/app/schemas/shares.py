from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CreateShare(BaseModel):
    visibility: Literal["public", "unlisted", "private"] = "unlisted"
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Expiry must include a timezone")
        return value


class Share(BaseModel):
    token: str
    url: str
    visibility: str
    expires_at: datetime | None


class Media(BaseModel):
    url: str
    expires_in: int = Field(gt=0)
