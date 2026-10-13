"""
Vercel serverless function: GET /api/stream-url?video_id=<id>

Returns the best audio-only stream URL for a YouTube video, extracted
server-side by yt-dlp so the device IP is never exposed to YouTube.

Response (200):
  {
    "url": "https://...",          # direct audio stream URL (expires ~6 h)
    "ext": "webm",                 # container extension
    "filesize": 12345678,          # bytes (may be null)
    "duration": 360                # seconds (may be null)
  }

Error responses:
  400  { "error": "video_id is required" }
  404  { "error": "No audio stream found" }
  500  { "error": "<yt-dlp error message>" }
"""

import json
import subprocess
import sys

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def _get_stream_url(video_id: str) -> dict:
    """Run yt-dlp in a subprocess and return the best audio stream info."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    # yt-dlp flags:
    #   -f bestaudio        — best audio-only format
    #   --get-url           — print the direct URL to stdout
    #   --print-json        — print full format JSON to stdout (we use this instead)
    #
    # We use --dump-single-json to get everything in one shot.
    result = subprocess.run(
        [
            sys.executable, "-m", "yt_dlp",
            "--quiet",
            "--no-warnings",
            "--skip-download",
            "--format", "bestaudio/best",
            "--dump-single-json",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=25,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip() or "yt-dlp failed with no output"
        raise RuntimeError(stderr)

    info = json.loads(result.stdout)

    # Pick the best audio-only format, falling back to the requested format.
    chosen = None

    # Try audio-only formats first (vcodec == "none")
    formats = info.get("formats") or []
    audio_only = [
        f for f in formats
        if f.get("vcodec", "none") == "none" and f.get("acodec", "none") != "none"
    ]
    if audio_only:
        # Prefer highest abr (average bitrate)
        audio_only.sort(key=lambda f: f.get("abr") or 0, reverse=True)
        chosen = audio_only[0]

    # Fall back to the top-level url (already the best match yt-dlp chose)
    if not chosen:
        top_url = info.get("url")
        if not top_url:
            raise RuntimeError("No audio stream found")
        chosen = {
            "url": top_url,
            "ext": info.get("ext", "mp4"),
            "filesize": info.get("filesize"),
            "duration": info.get("duration"),
        }

    return {
        "url": chosen["url"],
        "ext": chosen.get("ext", "webm"),
        "filesize": chosen.get("filesize"),
        "duration": info.get("duration"),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        video_id = params.get("video_id", [None])[0]

        if not video_id:
            self._respond(400, {"error": "video_id is required"})
            return

        # Sanitise: only allow alphanumeric + hyphen/underscore (YouTube IDs are 11 chars)
        if not all(c.isalnum() or c in "-_" for c in video_id) or len(video_id) > 20:
            self._respond(400, {"error": "invalid video_id"})
            return

        try:
            data = _get_stream_url(video_id)
            if not data.get("url"):
                self._respond(404, {"error": "No audio stream found"})
            else:
                self._respond(200, data)
        except subprocess.TimeoutExpired:
            self._respond(500, {"error": "yt-dlp timed out (>25 s)"})
        except RuntimeError as e:
            msg = str(e)
            if "Video unavailable" in msg or "Private video" in msg:
                self._respond(404, {"error": msg})
            else:
                self._respond(500, {"error": msg})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # silence default access log
