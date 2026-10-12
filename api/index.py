from youtube_transcript_api import YouTubeTranscriptApi
from flask import Flask, request, jsonify

application = Flask(__name__)
ytt_api = YouTubeTranscriptApi()

@application.route('/')
@application.route('/api')
def get_transcript():
    video_id = request.args.get('video_id')

    if not video_id:
        return jsonify({'error': 'video_id is required'}), 400

    try:
        fetched = ytt_api.fetch(video_id)
        entries = fetched.to_raw_data()
        text = ' '.join([e['text'] for e in entries])
        return jsonify({
            'transcript': text,
            'word_count': len(text.split())
        })
    except Exception as e:
        error = str(e)
        status = 404 if 'disabled' in error.lower() or 'no transcript' in error.lower() else 500
        return jsonify({'error': error}), status