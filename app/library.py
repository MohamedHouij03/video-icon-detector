from functools import lru_cache
from pathlib import Path

from app import video
from app.config import settings

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


class VideoNotFound(Exception):
    pass


def resolve(name: str) -> Path:
    """Map a video name to its file, refusing anything outside the videos folder."""
    folder = settings.videos_dir.resolve()
    path = (folder / name).resolve()
    if path.parent != folder or path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
        raise VideoNotFound(name)
    return path


@lru_cache(maxsize=256)
def _duration(path: Path, mtime: float) -> float | None:
    try:
        return video.duration(path)
    except video.VideoError:
        return None


@lru_cache(maxsize=64)
def _thumbnail(path: Path, mtime: float) -> bytes:
    total = _duration(path, mtime) or 0
    return video.extract_frame(path, str(round(total * 0.1, 1)), width=480)


def duration(path: Path) -> float | None:
    return _duration(path, path.stat().st_mtime)


def thumbnail(path: Path) -> bytes:
    return _thumbnail(path, path.stat().st_mtime)


def list_videos() -> list[dict]:
    if not settings.videos_dir.is_dir():
        return []
    videos = []
    for path in sorted(settings.videos_dir.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append({
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "duration_seconds": duration(path),
            })
    return videos
