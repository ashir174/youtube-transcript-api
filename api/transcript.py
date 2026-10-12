from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi
import json

ytt_api = YouTubeTranscriptApi()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        video_id = params.get('video_id', [None])[0]

        if not video_id:
            self._respond(400, {'error': 'video_id is required'})
            return

        try:
            fetched = ytt_api.fetch(video_id)
            entries = fetched.to_raw_data()
            text = ' '.join([e['text'] for e in entries])
            self._respond(200, {
                'transcript': text,
                'word_count': len(text.split())
            })
        except Exception as e:
            error = str(e)
            if 'disabled' in error.lower() or 'no transcript' in error.lower():
                self._respond(404, {'error': 'no_captions'})
            else:
                self._respond(500, {'error': error})

    def _respond(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
