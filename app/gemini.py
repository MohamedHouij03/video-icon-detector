import mimetypes
import time
from pathlib import Path

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)

ICON_PROMPT = """Find every icon shown on screen in this video.

Count as an icon: emojis, stickers, graphic overlays and symbols added in editing
(hearts, arrows, stars, check marks), logos, and app or UI icons (like, subscribe,
play, settings buttons). Do not count ordinary physical objects filmed by the
camera (furniture, clothes, pets) unless a logo or printed symbol is clearly legible.

Report one sighting per separate appearance, with start and end timestamps (MM:SS)
measured from the start of the video. If the same icon comes back later, report it
again as a new sighting. If several icons are on screen together, report each one.
Use the same name for the same icon every time. Only report icons you can actually
see; if there are none, return an empty list."""


class GeminiError(Exception):
    """Gemini rejected the input or returned an unusable answer. Not retryable."""


class IconSighting(BaseModel):
    icon: str = Field(description="Short, consistent name, e.g. 'broken heart', 'snowflake emoji', 'YouTube logo'")
    category: str = Field(description="One of: emoji, sticker, symbol, logo, ui_icon, other")
    description: str = Field(description="What it looks like and what it means in context")
    start: str = Field(description="When it first appears, MM:SS from the start of the video")
    end: str = Field(description="When it disappears, MM:SS from the start of the video")
    position: str = Field(description="Where on screen, e.g. 'top-left', 'center', 'bottom-right'")


class IconDetections(BaseModel):
    sightings: list[IconSighting]


def is_transient(e: Exception) -> bool:
    """True for errors that may succeed on a later attempt (overload, rate limit)."""
    if isinstance(e, errors.ServerError):
        return True
    return isinstance(e, errors.ClientError) and e.code == 429


def _generate(contents, config=None) -> tuple[types.GenerateContentResponse, str]:
    """Call the primary model, falling back to the next one on transient errors.

    Returns the response and the name of the model that produced it.
    """
    models = [settings.gemini_model, *settings.gemini_fallback_models]
    for i, model in enumerate(models):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response, model
        except (errors.ServerError, errors.ClientError) as e:
            if not is_transient(e) or i == len(models) - 1:
                raise


def describe_frame(image_bytes: bytes, question: str) -> str:
    response, _ = _generate([types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), question])
    return response.text


def _upload(video_path: Path) -> types.File:
    # Gemini keeps uploads for about 48 hours; reuse a matching one instead of sending the file again
    stat = video_path.stat()
    display_name = f"{video_path.stem[:80]}-{stat.st_size}-{int(stat.st_mtime)}"
    for f in client.files.list():
        if f.display_name == display_name and f.state == types.FileState.ACTIVE:
            return f

    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    f = client.files.upload(file=video_path, config={"display_name": display_name, "mime_type": mime_type})
    while f.state == types.FileState.PROCESSING:
        time.sleep(5)
        f = client.files.get(name=f.name)

    if f.state != types.FileState.ACTIVE:
        raise GeminiError(f"Gemini could not process the video: {f.error}")
    return f


def detect_icons(video_path: Path, fps: float = 1.0, on_stage=lambda stage: None) -> tuple[IconDetections, str]:
    """Find every icon in the video, with timestamps relative to its start.

    Gemini samples the video at `fps` frames per second. Higher values catch icons
    that are on screen for less than a second, at a proportional token cost.
    Returns the detections and the model that produced them.
    """
    on_stage("uploading")
    video = _upload(video_path)

    on_stage("analyzing")
    response, model = _generate(
        contents=[
            types.Part(
                file_data=types.FileData(file_uri=video.uri, mime_type=video.mime_type),
                video_metadata=types.VideoMetadata(fps=fps),
            ),
            ICON_PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=IconDetections,
        ),
    )
    if response.parsed is None:
        raise GeminiError(f"Could not parse Gemini's answer: {(response.text or '')[:500]}")
    return response.parsed, model
