import os

# Settings are read at import time, so configure a test environment before importing the app
os.environ["GEMINI_API_KEY"] = "test-key"

import pytest  # noqa: E402

from app import library  # noqa: E402
from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def reports_dir(tmp_path, monkeypatch):
    path = tmp_path / "reports"
    monkeypatch.setattr(settings, "reports_dir", path)
    return path


@pytest.fixture(autouse=True)
def videos_dir(tmp_path, monkeypatch):
    path = tmp_path / "videos"
    path.mkdir()
    monkeypatch.setattr(settings, "videos_dir", path)
    # Video files in tests are empty placeholders, so never call ffprobe on them
    monkeypatch.setattr(library.video, "duration", lambda p: 60.0)
    library._duration.cache_clear()
    return path
