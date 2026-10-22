"""Run an icon scan from the command line, without Redis or a Celery worker.

    python -m app.cli --start 0 --length 60
"""
import argparse
import uuid

from app.report import report_path
from app.scanner import run_scan


def main():
    parser = argparse.ArgumentParser(description="Detect icons in the configured video and save a report.")
    parser.add_argument("--start", type=float, default=0.0, help="start of the scan, in seconds (default: 0)")
    parser.add_argument("--length", type=float, default=None, help="seconds to scan (default: to the end)")
    parser.add_argument("--fps", type=float, default=1.0, help="frames per second sampled by Gemini (default: 1)")
    args = parser.parse_args()

    report = run_scan(
        str(uuid.uuid4()),
        start=args.start,
        length=args.length,
        fps=args.fps,
        on_stage=lambda stage: print(f"{stage.capitalize()}..."),
    )
    print(f"Found {report['distinct_icons']} distinct icons in {report['total_sightings']} appearances.")
    print(f"Report: {report_path(report['job_id'], 'md')}")


if __name__ == "__main__":
    main()
