import json
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.gemini import IconDetections


def parse_timestamp(ts: str) -> float:
    """Convert '1:05', '01:05', '0:01:05' or '65' to seconds."""
    seconds = 0.0
    for part in ts.strip().split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def format_timestamp(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_report(
    job_id: str,
    video_name: str,
    video_duration: float,
    detections: IconDetections,
    *,
    fps: float,
    model: str,
    offset: float = 0.0,
    scanned_length: float | None = None,
) -> dict:
    """Turn raw detections into a report.

    Detection timestamps are relative to the scanned clip, which starts `offset`
    seconds into the video. They are shifted so the report matches the full video.
    """
    if scanned_length is None:
        scanned_length = video_duration - offset

    sightings, dropped = [], 0
    for s in detections.sightings:
        try:
            start, end = parse_timestamp(s.start), parse_timestamp(s.end)
        except ValueError:
            dropped += 1
            continue
        # A sighting that starts after the clip ends cannot be real
        if start > scanned_length:
            dropped += 1
            continue
        end = min(max(end, start), scanned_length)
        start, end = start + offset, end + offset
        sightings.append({
            "icon": s.icon.strip(),
            "category": s.category.strip().lower(),
            "description": s.description.strip(),
            "position": s.position.strip(),
            "start": format_timestamp(start),
            "end": format_timestamp(end),
            "start_seconds": round(start, 1),
            "end_seconds": round(end, 1),
        })
    sightings.sort(key=lambda s: s["start_seconds"])

    summary = {}
    for s in sightings:
        entry = summary.setdefault(s["icon"].lower(), {
            "icon": s["icon"],
            "category": s["category"],
            "appearances": 0,
            "seconds_on_screen": 0.0,
            "timestamps": [],
        })
        entry["appearances"] += 1
        entry["seconds_on_screen"] = round(entry["seconds_on_screen"] + s["end_seconds"] - s["start_seconds"], 1)
        entry["timestamps"].append(f"{s['start']}-{s['end']}")

    return {
        "job_id": job_id,
        "video": video_name,
        "duration": format_timestamp(video_duration),
        "duration_seconds": round(video_duration, 1),
        "range_start": round(offset, 1),
        "range_end": round(offset + scanned_length, 1),
        "model": model,
        "fps": fps,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "distinct_icons": len(summary),
        "total_sightings": len(sightings),
        "dropped_sightings": dropped,
        "summary": sorted(summary.values(), key=lambda e: -e["appearances"]),
        "sightings": sightings,
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(report: dict) -> str:
    lines = [
        f"# Icon report: {report['video']}",
        "",
        f"Scanned {format_timestamp(report['range_start'])}-{format_timestamp(report['range_end'])}"
        f" of {report['duration']} with `{report['model']}` at {report['fps']} fps,"
        f" generated {report['generated_at']}.",
        "",
        f"**{report['distinct_icons']} distinct icons, {report['total_sightings']} appearances.**",
        "",
    ]
    if not report["sightings"]:
        lines.append("No icons were found in the scanned range.")
        return "\n".join(lines) + "\n"

    lines += ["## Summary", "", "| Icon | Type | Appearances | When |", "|---|---|---|---|"]
    for e in report["summary"]:
        lines.append(f"| {_cell(e['icon'])} | {e['category']} | {e['appearances']} | {', '.join(e['timestamps'])} |")

    lines += ["", "## Timeline", "", "| Start | End | Icon | Type | Position | Description |", "|---|---|---|---|---|---|"]
    for s in report["sightings"]:
        lines.append(
            f"| {s['start']} | {s['end']} | {_cell(s['icon'])} | {s['category']} "
            f"| {_cell(s['position'])} | {_cell(s['description'])} |"
        )
    return "\n".join(lines) + "\n"


def report_path(job_id: str, fmt: str) -> Path:
    return settings.reports_dir / f"{job_id}.{fmt}"


def save_report(report: dict) -> Path:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path(report["job_id"], "json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    md_path = report_path(report["job_id"], "md")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return md_path


def list_reports(video: str | None = None) -> list[dict]:
    """Saved reports, newest first, with headline fields only. Optionally for one video."""
    fields = ("job_id", "video", "generated_at", "range_start", "range_end", "fps", "distinct_icons", "total_sightings")
    reports = []
    for path in settings.reports_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if video is None or data.get("video") == video:
            reports.append({k: data.get(k) for k in fields})
    return sorted(reports, key=lambda r: r["generated_at"] or "", reverse=True)


def delete_report(job_id: str) -> bool:
    found = False
    for fmt in ("json", "md"):
        path = report_path(job_id, fmt)
        if path.exists():
            path.unlink()
            found = True
    return found


def delete_reports(video: str) -> int:
    """Delete every saved report for a video and return how many were removed."""
    return sum(delete_report(r["job_id"]) for r in list_reports(video))
