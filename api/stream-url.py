"""
Vercel serverless function: GET /api/stream-url?video_id=<id>

Uses yt-dlp as a Python library (not subprocess) to extract the best
audio-only stream URL server-side. The device IP never touches YouTube.

Response 200:
  { "url": "...", "ext": "webm", "filesize": 12345678, "duration": 360 }

Errors:
  400  { "error": "video_id is required" }
  404  { "error": "Video unavailable or private" }
  500  { "error": "<message>" }
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import yt_dlp


def _get_stream_url(video_id: str) -> dict:
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Don't write anything to disk
        "noplaylist": True,
    }

    url = f"https://www.youtube.com/watch?v={video_id}"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("yt-dlp returned no info")

    # Try audio-only formats first (vcodec == "none")
    formats = info.get("formats") or []
    audio_only = [
        f for f in formats
        if f.get("vcodec", "none") == "none"
        and f.get("acodec", "none") not in ("none", None)
        and f.get("url")
    ]

    if audio_only:
        # Highest average bitrate wins
        audio_only.sort(key=lambda f: f.get("abr") or f.get("tbr") or 0, reverse=True)
        chosen = audio_only[0]
    else:
        # Fall back to the top-level url yt-dlp already resolved
        top_url = info.get("url")
        if not top_url:
            raise RuntimeError("No audio stream found for this video")
        chosen = {
            "url": top_url,
            "ext": info.get("ext", "mp4"),
            "filesize": info.get("filesize"),
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
        video_id = (params.get("video_id") or [None])[0]

        if not video_id:
            self._respond(400, {"error": "video_id is required"})
            return

        # Sanitise: YouTube IDs are 11 alphanumeric + hyphen/underscore chars
        if not all(c.isalnum() or c in "-_" for c in video_id) or len(video_id) > 20:
            self._respond(400, {"error": "invalid video_id"})
            return

        try:
            data = _get_stream_url(video_id)
            self._respond(200, data)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Video unavailable" in msg or "Private video" in msg or "not available" in msg:
                self._respond(404, {"error": "Video unavailable or private"})
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
        pass  # silence default request logging
