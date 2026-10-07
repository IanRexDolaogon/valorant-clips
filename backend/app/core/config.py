from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    app_env: Literal["development", "production"] = "development"
    database_url: str
    jwt_secret: str
    redis_url: str = "redis://localhost:6379/0"
    riot_api_key: str = ""
    token_minutes: int = 60
    auth_requests_per_minute: int = 20
    riot_client_id: str = ""
    riot_client_secret: str = ""
    riot_redirect_uri: str = ""
    riot_auth_url: str = "https://auth.riotgames.com/authorize"
    riot_token_url: str = "https://auth.riotgames.com/token"
    riot_account_url: str = "https://asia.api.riotgames.com/riot/account/v1/accounts/me"
    frontend_url: str = "http://localhost:5173"
    storage_dir: Path = Path("storage")
    max_upload_bytes: int = Field(default=10_000_000, gt=0, le=10_000_000)
    max_chunk_bytes: int = 8 * 1024 * 1024
    upload_requests_per_minute: int = 300
    share_requests_per_minute: int = 60
    padding_before_ms: int = 3000
    padding_after_ms: int = 2000
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ffmpeg_timeout_seconds: int = 600
    storage_bucket: str = ""
    storage_endpoint: str = ""
    storage_region: str = "sgp1"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    public_api_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )


settings = Settings()
