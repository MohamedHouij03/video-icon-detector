import re
import uuid
from pathlib import Path
from typing import Literal

from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app import library, video
from app.report import delete_report, delete_reports, list_reports, report_path
from app.worker import celery_app, describe_video_frame, scan_video

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Video Icon Detector",
    description="Detect icons, emojis, stickers and logos in videos, with timestamps, using Google Gemini.",
    version="1.1.0",
)


class ScanRequest(BaseModel):
    video: str = Field(description="File name of a video in the videos folder")
    start: float = Field(default=0.0, ge=0, description="Where to start scanning, in seconds")
    length: float | None = Field(default=None, gt=0, description="How many seconds to scan; omit to scan to the end")
    fps: float = Field(default=1.0, gt=0, le=5, description="Frames per second sampled by Gemini")


class FrameRequest(BaseModel):
    video: str = Field(description="File name of a video in the videos folder")
    timestamp: str = Field(
        pattern=r"^(\d+(\.\d+)?|(\d{1,2}:)?\d{1,2}:\d{1,2}(\.\d+)?)$",
        description="Seconds (20, 12.5) or [HH:]MM:SS (00:00:20)",
        examples=["00:00:20"],
    )
    question: str = Field(min_length=1, examples=["Which icons are visible in this frame?"])


def _video_path(name: str) -> Path:
    try:
        return library.resolve(name)
    except library.VideoNotFound:
        raise HTTPException(status_code=404, detail=f"Video not found: {name}")


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


# Pages

@app.get("/", include_in_schema=False)
async def library_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/watch/{name}", include_in_schema=False)
async def player_page(name: str):
    try:
        library.resolve(name)
    except library.VideoNotFound:
        return RedirectResponse("/")
    return FileResponse(STATIC_DIR / "player.html")


@app.get("/static/{file}", include_in_schema=False)
async def static_file(file: str):
    path = (STATIC_DIR / file).resolve()
    if path.parent != STATIC_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


# Videos

@app.get("/api/videos", summary="List available videos")
def get_videos():
    reports = list_reports()
    videos = library.list_videos()
    for v in videos:
        scans = [r for r in reports if r["video"] == v["name"]]
        v["scans"] = len(scans)
        v["last_scan"] = scans[0] if scans else None
    return videos


@app.get("/api/videos/{name}/stream", summary="Stream a video")
async def stream_video(name: str):
    # FileResponse supports Range requests, so the player can seek without a full download
    return FileResponse(_video_path(name))


@app.get("/api/videos/{name}/thumbnail", summary="Thumbnail of a video")
def video_thumbnail(name: str):
    try:
        image = library.thumbnail(_video_path(name))
    except video.VideoError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


# Jobs

@app.post("/api/scans", status_code=202, summary="Start an icon scan")
async def start_scan(req: ScanRequest):
    _video_path(req.video)
    return _queue(scan_video, video_name=req.video, start=req.start, length=req.length, fps=req.fps)


@app.post("/api/frames", status_code=202, summary="Ask a question about a single frame")
async def describe_frame(req: FrameRequest):
    _video_path(req.video)
    return _queue(describe_video_frame, video_name=req.video, timestamp=req.timestamp, question=req.question)


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


# Reports

@app.get("/api/reports", summary="List saved reports")
async def get_reports(video: str | None = None):
    return list_reports(video)


@app.delete("/api/reports", summary="Delete every report for a video")
async def clear_reports(video: str):
    return {"deleted": delete_reports(video)}


@app.get("/api/reports/{job_id}", summary="Download a report as JSON or Markdown")
async def get_report(job_id: uuid.UUID, format: Literal["json", "md"] = "json"):
    path = report_path(str(job_id), format)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    media_type = "application/json" if format == "json" else "text/markdown; charset=utf-8"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.delete("/api/reports/{job_id}", summary="Delete one report")
async def remove_report(job_id: uuid.UUID):
    if not delete_report(str(job_id)):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": 1}
