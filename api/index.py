"""
Vercel serverless – single entry point for all /api/* routes.

Routes:
  GET /api/stream-url?video_id=<id>
      → yt-dlp extracts the best audio stream URL server-side.
        Returns: { "url": "...", "ext": "webm", "filesize": N, "duration": N }

  GET /api/transcript/<video_id>          (legacy – path param)
  GET /api?video_id=<id>                  (legacy – query param)
      → youtube-transcript-api fetches captions.
        Returns: { "transcript": "...", "word_count": N }

Why a single file?
  Vercel treats api/index.py as a wildcard catch-all for every /api/* path,
  so adding separate files (api/stream-url.py) doesn't create new routes —
  they all still land here.  Path-based routing inside this handler is the
  only reliable approach.
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------------------------
# yt-dlp stream-URL extraction
# ---------------------------------------------------------------------------

def _stream_url(video_id: str) -> dict:
    import os
    import yt_dlp  # imported lazily so cold-start for transcript is faster

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "tv"],
                "player_skip": ["webpage", "configs"],
            }
        },
    }

    cookie_content = os.environ.get("YOUTUBE_COOKIES")
    cookie_path = "/tmp/cookies.txt"
    if cookie_content:
        try:
            with open(cookie_path, "w") as f:
                f.write(cookie_content)
            ydl_opts["cookiefile"] = cookie_path
        except Exception:
            pass

    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(yt_url, download=False)

    if not info:
        raise RuntimeError("yt-dlp returned no info")

    formats = info.get("formats") or []
    audio_only = [
        f for f in formats
        if f.get("vcodec", "none") == "none"
        and f.get("acodec", "none") not in ("none", None)
        and f.get("url")
    ]

    if audio_only:
        audio_only.sort(key=lambda f: f.get("abr") or f.get("tbr") or 0, reverse=True)
        chosen = audio_only[0]
    else:
        top_url = info.get("url")
        if not top_url:
            raise RuntimeError("No audio stream found for this video")
        chosen = {"url": top_url, "ext": info.get("ext", "mp4"), "filesize": info.get("filesize")}

    return {
        "url": chosen["url"],
        "ext": chosen.get("ext", "webm"),
        "filesize": chosen.get("filesize"),
        "duration": info.get("duration"),
    }


# ---------------------------------------------------------------------------
# youtube-transcript-api caption fetch
# ---------------------------------------------------------------------------

def _transcript(video_id: str) -> dict:
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt = YouTubeTranscriptApi()
    fetched = ytt.fetch(video_id)
    entries = fetched.to_raw_data()
    text = " ".join(e["text"] for e in entries)
    return {"transcript": text, "word_count": len(text.split())}


# ---------------------------------------------------------------------------
# Vercel handler
# ---------------------------------------------------------------------------

def _sanitize_video_id(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not all(c.isalnum() or c in "-_" for c in raw) or len(raw) > 20:
        return None
    return raw


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path.endswith("/stream-url"):
            self._handle_stream_url(params)
        else:
            self._handle_transcript(path, params)

    # ------------------------------------------------------------------
    # /api/stream-url?video_id=<id>
    # ------------------------------------------------------------------
    def _handle_stream_url(self, params: dict):
        raw_id = (params.get("video_id") or [None])[0]
        video_id = _sanitize_video_id(raw_id)

        if not video_id:
            self._respond(400, {"error": "video_id is required"})
            return

        try:
            data = _stream_url(video_id)
            self._respond(200, data)
        except Exception as e:
            import yt_dlp
            msg = str(e)
            if isinstance(e, yt_dlp.utils.DownloadError) and (
                "unavailable" in msg.lower() or "private" in msg.lower()
            ):
                self._respond(404, {"error": "Video unavailable or private"})
            else:
                self._respond(500, {"error": msg})

    # ------------------------------------------------------------------
    # /api/transcript/<video_id>  or  /api?video_id=<id>
    # ------------------------------------------------------------------
    def _handle_transcript(self, path: str, params: dict):
        # Try query param first, then last path segment
        raw_id = (params.get("video_id") or [None])[0]
        if not raw_id:
            raw_id = path.split("/")[-1] or None

        video_id = _sanitize_video_id(raw_id)
        if not video_id:
            self._respond(400, {"error": "video_id is required"})
            return

        try:
            data = _transcript(video_id)
            self._respond(200, data)
        except Exception as e:
            self._respond(500, {"error": str(e)})

    # ------------------------------------------------------------------
    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass