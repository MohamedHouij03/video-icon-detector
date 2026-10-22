from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.8-flash"
    # Tried in order when the primary model is overloaded or rate limited
    gemini_fallback_models: list[str] = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash"]

    video_path: Path
    reports_dir: Path = ROOT_DIR / "reports"
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @field_validator("video_path", "reports_dir")
    @classmethod
    def _relative_to_root(cls, path: Path) -> Path:
        return path if path.is_absolute() else ROOT_DIR / path


settings = Settings()
