import os

import httpx
from celery import Celery

from app import video
from app.config import settings
from app.gemini import describe_frame, is_transient
from app.scanner import run_scan

celery_app = Celery("video_icon_detector", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_track_started = True

# Celery's default prefork pool is not supported on Windows
if os.name == "nt":
    celery_app.conf.worker_pool = "solo"

MAX_RETRIES = 5


def _should_retry(e: Exception) -> bool:
    return is_transient(e) or isinstance(e, httpx.TransportError)


def _backoff(retries: int) -> int:
    return 30 * 2 ** retries


@celery_app.task(bind=True, max_retries=MAX_RETRIES)
def scan_video(self, job_id: str, start: float = 0.0, length: float | None = None, fps: float = 1.0):
    def on_stage(stage):
        self.update_state(state="PROGRESS", meta={"stage": stage})

    try:
        return run_scan(job_id, start=start, length=length, fps=fps, on_stage=on_stage)
    except Exception as e:
        if not _should_retry(e):
            raise
        raise self.retry(exc=e, countdown=_backoff(self.request.retries))


@celery_app.task(bind=True, max_retries=MAX_RETRIES)
def describe_video_frame(self, job_id: str, timestamp: str, question: str):
    try:
        image = video.extract_frame(settings.video_path, timestamp)
        answer = describe_frame(image, question)
    except Exception as e:
        if not _should_retry(e):
            raise
        raise self.retry(exc=e, countdown=_backoff(self.request.retries))

    return {"job_id": job_id, "timestamp": timestamp, "answer": answer}
