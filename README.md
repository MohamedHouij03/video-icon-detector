# Video Icon Detector

Find the icons, emojis, stickers and logos that appear in a video, and get the exact timestamps for each one. Detection runs on Google Gemini's video understanding. A FastAPI service queues scans through Celery, and a built-in web player shows each detection on top of the video as it plays.

Typical uses: auditing graphic overlays in edited videos, indexing logo appearances for sponsorship reports, or checking which UI icons show up in a screen recording.

## How it works

1. The selected range of the video is cut with ffmpeg and scaled down to 720p.
2. The clip is uploaded to Gemini, which samples it at the chosen frame rate and returns every icon it sees as structured JSON.
3. Timestamps are validated against the clip length, shifted back to match the full video, and saved as a JSON and Markdown report.

```
browser ── FastAPI ── Redis ── Celery worker ── ffmpeg
                                    └────────── Gemini API
```

If the primary Gemini model is overloaded or rate limited, the request moves to the next model in the fallback list. If every model is busy, the job is retried with exponential backoff.

## Requirements

- Python 3.11 or newer
- [ffmpeg](https://ffmpeg.org/download.html) on your `PATH`
- Redis (a `docker-compose.yml` is included)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

## Setup

```bash
git clone https://github.com/<your-username>/video-icon-detector.git
cd video-icon-detector

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then set GEMINI_API_KEY and VIDEO_PATH
docker compose up -d             # starts Redis on port 6379
```

## Running

Start the worker and the API in two terminals:

```bash
celery -A app.worker worker --loglevel=info
uvicorn app.api:app --reload
```

Open http://127.0.0.1:8000, choose a start time and length, and click **Scan for icons**. When the scan finishes, play the video: detected icons are labelled on screen while they are visible, and the timeline shows one row per icon. Click any row or sighting to jump to it.

Interactive API docs are at http://127.0.0.1:8000/docs.

### Without Redis

For a one-off scan, the command-line tool runs everything in the current process:

```bash
python -m app.cli --start 0 --length 60
```

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/scans` | Start a scan. Body: `start` and `length` in seconds, `fps` (default 1, max 5) |
| `GET` | `/api/tasks/{task_id}` | Job status, progress stage, result or error |
| `GET` | `/api/reports` | Saved reports, newest first |
| `GET` | `/api/reports/{job_id}?format=json\|md` | Download a report |
| `POST` | `/api/frames` | Ask a question about the frame at a `timestamp` |
| `GET` | `/api/video` | Stream the configured video |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/scans \
  -H "Content-Type: application/json" \
  -d '{"start": 0, "length": 60, "fps": 1}'
```

## Report format

Each sighting in a report looks like this:

```json
{
  "icon": "broken heart",
  "category": "emoji",
  "description": "Red broken heart next to the speaker, used as a reaction",
  "position": "left",
  "start": "0:18",
  "end": "0:24",
  "start_seconds": 18.0,
  "end_seconds": 24.0
}
```

The report also includes a per-icon summary (appearance count, time on screen, timestamps), the scanned range, and the model that produced it. Reports are written to `reports/` as JSON and Markdown.

## Configuration

All settings are read from environment variables or `.env`.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | required | Gemini API key |
| `VIDEO_PATH` | required | Video to analyze, absolute or relative to the project root |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Primary model |
| `GEMINI_FALLBACK_MODELS` | `["gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash"]` | Tried in order when the primary model is busy |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker and result backend |
| `REPORTS_DIR` | `reports` | Where reports are saved |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests do not call Gemini or need Redis or ffmpeg.

## Limitations

- Positions are coarse ("top-left", "center"), so on-screen labels mark the area of an icon, not a bounding box.
- At 1 fps, icons shown for less than a second can be missed. Use 2 to 4 fps for fast edits, at a higher token cost.
- One video is configured at a time through `VIDEO_PATH`.

## Project structure

```
app/
  api.py        FastAPI routes
  worker.py     Celery tasks and retry policy
  scanner.py    Cut, detect and report pipeline
  gemini.py     Gemini client, prompt and model fallback
  video.py      ffmpeg helpers
  report.py     Report building and Markdown export
  cli.py        Command-line scan
  static/       Web player
tests/
```
