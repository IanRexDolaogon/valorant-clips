"""The jobs table is the durable outbox; recover queued work after Redis/API restarts."""
import logging
import time

from rq import Queue, Worker
from rq.exceptions import DuplicateJobError
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.rate_limit import redis
from app.workers.clips import failure_callback


def run() -> None:
    queue = Queue("clips", connection=redis)
    # CV demo: one RQ worker, one job at a time; do not scale worker replicas.
    while True:
        try:
            with SessionLocal() as db:
                ids = db.scalars(text("SELECT clip_id FROM processing_jobs WHERE status='queued' ORDER BY id LIMIT 100")).all()
            for clip_id in ids:
                try:
                    queue.enqueue("app.workers.clips.process", clip_id, job_id=f"clip-{clip_id}", unique=True,
                        job_timeout=settings.ffmpeg_timeout_seconds + 60, on_failure=failure_callback, on_stopped=failure_callback)
                except DuplicateJobError:
                    pass
            Worker([queue], connection=redis).work(burst=True)
        except Exception as error:
            logging.error("Worker dispatch unavailable (%s)", type(error).__name__)
        time.sleep(2)


if __name__ == "__main__":
    run()
