import pytest

from app.gemini import IconDetections, IconSighting
from app.report import build_report, format_timestamp, list_reports, parse_timestamp, save_report, to_markdown


def sighting(icon, start, end, description="red heart"):
    return IconSighting(icon=icon, category="Emoji", description=description, start=start, end=end, position="top-left")


@pytest.mark.parametrize("ts, seconds", [("65", 65), ("1:05", 65), ("01:05", 65), ("0:01:05", 65), ("12.5", 12.5)])
def test_parse_timestamp(ts, seconds):
    assert parse_timestamp(ts) == seconds


@pytest.mark.parametrize("seconds, ts", [(0, "0:00"), (65, "1:05"), (3725, "1:02:05")])
def test_format_timestamp(seconds, ts):
    assert format_timestamp(seconds) == ts


def make_report(sightings, offset=0.0, scanned_length=60.0):
    return build_report(
        "job-1", "video.mp4", 300.0, IconDetections(sightings=sightings),
        fps=1.0, model="gemini-test", offset=offset, scanned_length=scanned_length,
    )


def test_sightings_are_sorted_and_grouped():
    report = make_report([
        sighting("Broken heart", "00:20", "00:24"),
        sighting("snowflake", "00:05", "00:07"),
        sighting("broken heart", "00:40", "00:41"),
    ])
    assert [s["start"] for s in report["sightings"]] == ["0:05", "0:20", "0:40"]
    assert report["distinct_icons"] == 2
    assert report["summary"][0]["appearances"] == 2
    assert report["summary"][0]["timestamps"] == ["0:20-0:24", "0:40-0:41"]


def test_invalid_sightings_are_dropped_or_clamped():
    report = make_report([
        sighting("ghost", "05:00", "05:05"),     # starts after the 60s clip
        sighting("bad", "abc", "00:01"),         # unparseable
        sighting("arrow", "00:30", "00:10"),     # ends before it starts
        sighting("star", "00:50", "02:00"),      # runs past the clip
    ])
    assert report["dropped_sightings"] == 2
    arrow, star = report["sightings"]
    assert arrow["end_seconds"] == arrow["start_seconds"] == 30
    assert star["end_seconds"] == 60


def test_timestamps_are_shifted_to_the_full_video():
    report = make_report([sighting("heart", "00:10", "00:12")], offset=120, scanned_length=60)
    s = report["sightings"][0]
    assert (s["start"], s["end"]) == ("2:10", "2:12")
    assert (report["range_start"], report["range_end"]) == (120, 180)


def test_markdown_escapes_table_cells():
    report = make_report([sighting("heart", "00:01", "00:02", description="red | pink")])
    assert "red \\| pink" in to_markdown(report)


def test_markdown_without_sightings():
    assert "No icons were found" in to_markdown(make_report([]))


def test_save_and_list(reports_dir):
    report = make_report([sighting("heart", "00:01", "00:02")])
    md_path = save_report(report)
    assert md_path.exists() and (reports_dir / "job-1.json").exists()
    assert list_reports()[0]["job_id"] == "job-1"
