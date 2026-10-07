"""Hourly media cleanup: storage first, then cascading database deletion."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import text

if __name__ == "__main__" and "--cron" in sys.argv:
    os.environ.update(json.loads(Path("/run/cleanup-env.json").read_text()))

from app.core.db import SessionLocal
from app.services import storage


def cleanup() -> int:
    removed = 0
    with SessionLocal() as db:
        ids = db.scalars(text("SELECT id FROM videos WHERE expires_at<now() ORDER BY expires_at")).all()
    for video_id in ids:
        try:
            with SessionLocal() as db:
                video = db.execute(text("SELECT storage_key FROM videos WHERE id=:id AND expires_at<now() "
                    "FOR UPDATE"), {"id": video_id}).first()
                if not video:
                    continue
                keys = db.scalars(text("SELECT storage_key FROM clips WHERE video_id=:id AND storage_key IS NOT NULL"),
                    {"id": video_id}).all()
                for key in [*keys, video.storage_key]:
                    storage.delete(key)
                # Existing FKs cascade to clips, shares and processing_jobs.
                db.execute(text("DELETE FROM videos WHERE id=:id"), {"id": video_id})
                db.commit()
                removed += 1
        except Exception as error:
            # Keep the row and its keys so the next hourly run can retry idempotently.
            logging.error("Media cleanup failed for video %s (%s)", video_id, type(error).__name__)
    return removed


if __name__ == "__main__":
    if "--schedule" in sys.argv:
        # Cron does not inherit container environment; keep it in a root-only runtime file.
        env_file = Path("/run/cleanup-env.json")
        env_file.touch(mode=0o600)
        env_file.write_text(json.dumps(dict(os.environ)))
        subprocess.run(["crontab", "-"], input="0 * * * * cd /app && /usr/local/bin/python -m app.workers.cleanup --cron >> /proc/1/fd/1 2>> /proc/1/fd/2\n",
            text=True, check=True)
        os.execvp("cron", ["cron", "-f"])
    print(f"Removed {cleanup()} expired uploads", flush=True)
