import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import api
from app.report import save_report

client = TestClient(api.app)


@pytest.fixture
def clip(videos_dir):
    (videos_dir / "clip.mp4").write_bytes(b"fake video")
    return "clip.mp4"


@pytest.fixture
def queued():
    with mock.patch.object(api.scan_video, "delay", return_value=mock.Mock(id="task-1")) as scan, \
         mock.patch.object(api.describe_video_frame, "delay", return_value=mock.Mock(id="task-2")) as frame:
        yield scan, frame


def saved_report(video="clip.mp4", icons=0):
    job_id = str(uuid.uuid4())
    save_report({
        "job_id": job_id, "video": video, "duration": "1:00", "range_start": 0, "range_end": 60,
        "model": "m", "fps": 1, "generated_at": f"2026-01-01T00:00:{icons:02d}",
        "distinct_icons": icons, "total_sightings": icons, "summary": [], "sightings": [],
    })
    return job_id


# Pages

def test_library_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Video Icon Detector" in response.text


def test_player_page_for_known_video(clip):
    response = client.get(f"/watch/{clip}")
    assert response.status_code == 200
    assert 'id="video"' in response.text


def test_player_page_for_unknown_video_redirects_home():
    response = client.get("/watch/missing.mp4", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/"


def test_static_files_cannot_escape_the_folder():
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/..%2Fapi.py").status_code == 404


# Videos

def test_video_list_includes_scan_summary(clip):
    saved_report(icons=2)
    latest = saved_report(icons=5)
    [video] = client.get("/api/videos").json()
    assert video["name"] == clip
    assert video["scans"] == 2
    assert video["last_scan"]["job_id"] == latest


def test_stream_supports_range_requests(clip):
    response = client.get(f"/api/videos/{clip}/stream", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"fake"


def test_unknown_video_returns_404():
    assert client.get("/api/videos/missing.mp4/stream").status_code == 404


# Jobs

def test_start_scan(clip, queued):
    response = client.post("/api/scans", json={"video": clip, "start": 30, "length": 60})
    assert response.status_code == 202
    assert response.json()["task_id"] == "task-1"
    kwargs = queued[0].call_args.kwargs
    assert (kwargs["video_name"], kwargs["start"], kwargs["length"], kwargs["fps"]) == (clip, 30, 60, 1.0)


def test_scan_of_unknown_video_is_rejected(queued):
    assert client.post("/api/scans", json={"video": "missing.mp4"}).status_code == 404
    queued[0].assert_not_called()


@pytest.mark.parametrize("body", [{}, {"fps": 50}, {"start": -1}, {"length": 0}])
def test_scan_rejects_invalid_input(clip, queued, body):
    assert client.post("/api/scans", json={"video": clip, **body} if body else {}).status_code == 422


@pytest.mark.parametrize("timestamp, status", [("20", 202), ("12.5", 202), ("00:20", 202), ("01:02:03.5", 202),
                                               ("abc", 422), ("1:2:3:4", 422)])
def test_frame_timestamp_validation(clip, queued, timestamp, status):
    response = client.post("/api/frames", json={"video": clip, "timestamp": timestamp, "question": "What is shown?"})
    assert response.status_code == status


def test_failed_task_returns_readable_error():
    gemini_error = Exception(
        "<class 'google.genai.errors.ServerError'>([\"503 UNAVAILABLE. {'error': {'code': 503, "
        "'message': 'High demand.', 'status': 'UNAVAILABLE'}}\"])"
    )
    result = mock.Mock(status="FAILURE", result=gemini_error)
    result.successful.return_value, result.failed.return_value = False, True
    with mock.patch.object(api, "AsyncResult", return_value=result):
        body = client.get("/api/tasks/task-1").json()
    assert body["error"] == "503 UNAVAILABLE: High demand."


# Reports

def test_reports_are_filtered_by_video():
    mine = saved_report("clip.mp4")
    saved_report("other.mp4")
    assert [r["job_id"] for r in client.get("/api/reports?video=clip.mp4").json()] == [mine]
    assert len(client.get("/api/reports").json()) == 2


def test_report_downloads():
    job_id = saved_report()
    assert client.get(f"/api/reports/{job_id}").json()["job_id"] == job_id
    assert client.get(f"/api/reports/{job_id}?format=md").text.startswith("# Icon report")


def test_unknown_report_returns_404():
    assert client.get(f"/api/reports/{uuid.uuid4()}").status_code == 404


def test_report_id_must_be_a_uuid():
    assert client.get("/api/reports/..%2F.env").status_code in (404, 422)


def test_clear_reports_for_one_video(reports_dir):
    saved_report("clip.mp4")
    saved_report("clip.mp4")
    other = saved_report("other.mp4")

    assert client.delete("/api/reports?video=clip.mp4").json() == {"deleted": 2}
    assert [r["job_id"] for r in client.get("/api/reports").json()] == [other]
    assert len(list(reports_dir.iterdir())) == 2  # the other video's .json and .md


def test_clear_requires_a_video():
    assert client.delete("/api/reports").status_code == 422


def test_delete_single_report():
    job_id = saved_report()
    assert client.delete(f"/api/reports/{job_id}").json() == {"deleted": 1}
    assert client.delete(f"/api/reports/{job_id}").status_code == 404
