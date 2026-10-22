import re
import uuid
from pathlib import Path
from typing import Literal

from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.report import list_reports, report_path
from app.worker import celery_app, describe_video_frame, scan_video

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Video Icon Detector",
    description="Detect icons, emojis, stickers and logos in a video, with timestamps, using Google Gemini.",
    version="1.0.0",
)


class ScanRequest(BaseModel):
    start: float = Field(default=0.0, ge=0, description="Where to start scanning, in seconds")
    length: float | None = Field(default=None, gt=0, description="How many seconds to scan; omit to scan to the end")
    fps: float = Field(default=1.0, gt=0, le=5, description="Frames per second sampled by Gemini")


class FrameRequest(BaseModel):
    timestamp: str = Field(
        pattern=r"^(\d+(\.\d+)?|(\d{1,2}:)?\d{1,2}:\d{1,2}(\.\d+)?)$",
        description="Seconds (20, 12.5) or [HH:]MM:SS (00:00:20)",
        examples=["00:00:20"],
    )
    question: str = Field(min_length=1, examples=["Which icons are visible in this frame?"])


def _queue(task, **kwargs) -> dict:
    job_id = str(uuid.uuid4())
    try:
        result = task.delay(job_id=job_id, **kwargs)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not queue the job: {e}")
    return {"task_id": result.id, "job_id": job_id, "status": "queued"}


def _error_text(exc) -> str:
    # Celery returns Gemini errors as a generic Exception wrapping the original repr;
    # extract "503 UNAVAILABLE: <message>" when it is there
    text = str(exc)
    message = re.search(r"'message': '([^']*)'", text)
    if message:
        code = re.search(r"\b(\d{3} [A-Z_]+)\b", text)
        return f"{code.group(1)}: {message.group(1)}" if code else message.group(1)
    return f"{type(exc).__name__}: {text}"


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/video", summary="Stream the configured video")
async def stream_video():
    # FileResponse supports Range requests, so the player can seek without a full download
    return FileResponse(settings.video_path, media_type="video/mp4")


@app.post("/api/scans", status_code=202, summary="Start an icon scan")
async def start_scan(req: ScanRequest = ScanRequest()):
    return _queue(scan_video, start=req.start, length=req.length, fps=req.fps)


@app.post("/api/frames", status_code=202, summary="Ask a question about a single frame")
async def describe_frame(req: FrameRequest):
    return _queue(describe_video_frame, timestamp=req.timestamp, question=req.question)


@app.get("/api/tasks/{task_id}", summary="Get the status of a queued job")
async def task_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    response = {"task_id": task_id, "status": result.status, "progress": None, "result": None, "error": None}

    if result.successful():
        response["result"] = result.result
    elif result.status == "PROGRESS":
        response["progress"] = result.info
    elif result.failed() or result.status == "RETRY":
        response["error"] = _error_text(result.result)
    return response


@app.get("/api/reports", summary="List saved reports")
async def get_reports():
    return list_reports()


@app.get("/api/reports/{job_id}", summary="Download a report as JSON or Markdown")
async def get_report(job_id: uuid.UUID, format: Literal["json", "md"] = "json"):
    path = report_path(str(job_id), format)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    media_type = "application/json" if format == "json" else "text/markdown; charset=utf-8"
    return FileResponse(path, media_type=media_type, filename=path.name)
