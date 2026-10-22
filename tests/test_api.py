import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import api
from app.report import save_report

client = TestClient(api.app)


@pytest.fixture
def queued():
    with mock.patch.object(api.scan_video, "delay", return_value=mock.Mock(id="task-1")) as scan, \
         mock.patch.object(api.describe_video_frame, "delay", return_value=mock.Mock(id="task-2")) as frame:
        yield scan, frame


def test_index_serves_the_player():
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Video Icon Detector</title>" in response.text


def test_start_scan_with_defaults(queued):
    response = client.post("/api/scans")
    assert response.status_code == 202
    assert response.json()["task_id"] == "task-1"
    kwargs = queued[0].call_args.kwargs
    assert (kwargs["start"], kwargs["length"], kwargs["fps"]) == (0.0, None, 1.0)


@pytest.mark.parametrize("body", [{"fps": 50}, {"start": -1}, {"length": 0}])
def test_start_scan_rejects_invalid_input(queued, body):
    assert client.post("/api/scans", json=body).status_code == 422


@pytest.mark.parametrize("timestamp, status", [("20", 202), ("12.5", 202), ("00:20", 202), ("01:02:03.5", 202),
                                               ("abc", 422), ("1:2:3:4", 422)])
def test_frame_timestamp_validation(queued, timestamp, status):
    response = client.post("/api/frames", json={"timestamp": timestamp, "question": "What is shown?"})
    assert response.status_code == status


def test_reports_are_listed_and_downloadable():
    job_id = str(uuid.uuid4())
    save_report({
        "job_id": job_id, "video": "v.mp4", "duration": "1:00", "range_start": 0, "range_end": 60,
        "model": "m", "fps": 1, "generated_at": "2026-01-01T00:00:00",
        "distinct_icons": 0, "total_sightings": 0, "summary": [], "sightings": [],
    })
    assert client.get("/api/reports").json()[0]["job_id"] == job_id
    assert client.get(f"/api/reports/{job_id}").json()["job_id"] == job_id
    assert client.get(f"/api/reports/{job_id}?format=md").text.startswith("# Icon report")


def test_unknown_report_returns_404():
    assert client.get(f"/api/reports/{uuid.uuid4()}").status_code == 404


def test_report_id_must_be_a_uuid():
    assert client.get("/api/reports/..%2F.env").status_code in (404, 422)


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
