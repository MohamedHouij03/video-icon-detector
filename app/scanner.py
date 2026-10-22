import tempfile
from pathlib import Path

from app import video
from app.config import settings
from app.gemini import detect_icons
from app.report import build_report, save_report


def run_scan(job_id: str, start: float = 0.0, length: float | None = None, fps: float = 1.0,
             on_stage=lambda stage: None) -> dict:
    """Scan `length` seconds of the configured video from `start` (to the end if None),
    save the report to disk and return it."""
    total = video.duration(settings.video_path)
    if start >= total:
        raise video.VideoError(f"Start {start:.0f}s is past the end of the video ({total:.0f}s)")
    length = min(length or total, total - start)

    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.mp4"
        on_stage("cutting clip")
        video.cut_clip(settings.video_path, start, length, clip)
        detections, model = detect_icons(clip, fps=fps, on_stage=on_stage)

    report = build_report(
        job_id,
        settings.video_path.name,
        total,
        detections,
        fps=fps,
        model=model,
        offset=start,
        scanned_length=length,
    )
    save_report(report)
    return report
