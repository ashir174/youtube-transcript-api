from youtube_transcript_api import YouTubeTranscriptApi
import json

ytt_api = YouTubeTranscriptApi()

def application(environ, start_response):
    from urllib.parse import parse_qs
    params = parse_qs(environ.get('QUERY_STRING', ''))
    video_id = params.get('video_id', [None])[0]

    if not video_id:
        body = json.dumps({'error': 'video_id is required'}).encode()
        start_response('400 Bad Request', [('Content-Type', 'application/json')])
        return [body]

    try:
        fetched = ytt_api.fetch(video_id)
        entries = fetched.to_raw_data()
        text = ' '.join([e['text'] for e in entries])
        body = json.dumps({'transcript': text, 'word_count': len(text.split())}).encode()
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [body]
    except Exception as e:
        body = json.dumps({'error': str(e)}).encode()
        start_response('500 Internal Server Error', [('Content-Type', 'application/json')])
        return [body]