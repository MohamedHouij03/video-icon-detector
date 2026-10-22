import os

# Settings are read at import time, so configure a test environment before importing the app
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["VIDEO_PATH"] = "tests/missing-video.mp4"

import pytest  # noqa: E402

from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def reports_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "reports_dir", tmp_path)
    return tmp_path
