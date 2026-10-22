import os
import shutil
import sys
import tempfile
from pathlib import Path

import ffmpeg


class VideoError(Exception):
    """ffmpeg could not read or process the video. Not retryable."""


def _refresh_windows_path():
    # A shell started before ffmpeg was installed keeps a stale PATH;
    # reload it from the registry so ffmpeg and ffprobe can still be found.
    if sys.platform != "win32" or shutil.which("ffmpeg"):
        return
    import winreg

    keys = [
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]
    paths = [os.environ.get("PATH", "")]
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as key:
                paths.append(os.path.expandvars(winreg.QueryValueEx(key, "Path")[0]))
        except OSError:
            pass
    os.environ["PATH"] = os.pathsep.join(paths)


_refresh_windows_path()


def _run(stream):
    try:
        stream.run(overwrite_output=True, quiet=True)
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace").strip() if e.stderr else ""
        raise VideoError(f"ffmpeg failed: {stderr[-500:]}") from None
    except FileNotFoundError:
        raise VideoError("ffmpeg not found on PATH") from None


def _require(video_path: Path):
    if not Path(video_path).exists():
        raise VideoError(f"Video not found: {video_path}")


def duration(video_path: Path) -> float:
    _require(video_path)
    try:
        return float(ffmpeg.probe(str(video_path))["format"]["duration"])
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace").strip() if e.stderr else ""
        raise VideoError(f"ffprobe failed: {stderr[-500:]}") from None
    except FileNotFoundError:
        raise VideoError("ffprobe not found on PATH") from None


def extract_frame(video_path: Path, timestamp: str, width: int | None = None) -> bytes:
    """Return the frame at `timestamp` (seconds or [HH:]MM:SS) as JPEG bytes,
    optionally scaled down to `width` pixels."""
    _require(video_path)
    with tempfile.TemporaryDirectory() as tmp:
        frame_path = os.path.join(tmp, "frame.jpg")
        options = {"vframes": 1}
        if width:
            options["vf"] = f"scale={width}:-2"
        _run(ffmpeg.input(str(video_path), ss=timestamp).output(frame_path, **options))
        # ffmpeg succeeds without writing anything when the timestamp is past the end
        if not os.path.exists(frame_path) or os.path.getsize(frame_path) == 0:
            raise VideoError(f"No frame at {timestamp}, is it past the end of the video?")
        with open(frame_path, "rb") as f:
            return f.read()


def cut_clip(video_path: Path, start: float, length: float, clip_path: Path):
    """Write `length` seconds from `start` to `clip_path`, scaled down to at most 720p.

    The clip is re-encoded rather than stream-copied so it starts exactly at `start`
    instead of the previous keyframe, which keeps the reported timestamps accurate.
    """
    _require(video_path)
    _run(
        ffmpeg
        .input(str(video_path), ss=start, t=length)
        .output(
            str(clip_path),
            vf="scale=-2:'min(720,ih)'",
            vcodec="libx264",
            preset="veryfast",
            crf=26,
            acodec="aac",
            movflags="+faststart",
        )
    )
