import json
import re
import subprocess

import boto3
from fastapi import HTTPException

from app.core.config import settings


def path_for(key: str):
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|source)", key):
        raise ValueError("Invalid storage key")
    root = settings.storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = (root / key).resolve()
    if path.parent != root:
        raise ValueError("Storage path escapes its root")
    return path


def s3():
    return boto3.client("s3", endpoint_url=settings.storage_endpoint,
        region_name=settings.storage_region, aws_access_key_id=settings.storage_access_key,
        aws_secret_access_key=settings.storage_secret_key)


def publish(key: str) -> None:
    if settings.storage_bucket:
        s3().upload_file(str(path_for(key)), settings.storage_bucket, key,
            ExtraArgs={"ContentType": "video/mp4" if key.endswith(".mp4") else "application/octet-stream"})


def source(key: str):
    path = path_for(key)
    if not path.exists() and settings.storage_bucket:
        temporary = path.with_suffix(".download")
        s3().download_file(settings.storage_bucket, key, str(temporary))
        temporary.replace(path)
    return path


def probe(path) -> int:
    try:
        result = subprocess.run([
            settings.ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "format=duration,format_name:stream=codec_type", "-of", "json", str(path),
        ], capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        formats = set(data["format"]["format_name"].split(","))
        if not formats.intersection({"mov", "mp4", "matroska", "webm"}) or not any(
            stream.get("codec_type") == "video" for stream in data["streams"]
        ) or not 0 < duration <= 2147483:
            raise ValueError
        return int(duration * 1000)
    except (subprocess.SubprocessError, ValueError, KeyError, OSError):
        raise HTTPException(422, "Recording must be a valid MP4, MKV or WebM video") from None
