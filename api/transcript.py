from youtube_transcript_api import YouTubeTranscriptApi
import json

ytt_api = YouTubeTranscriptApi()

def handler(request):
    video_id = request.args.get('video_id')
    
    if not video_id:
        return Response(
            json.dumps({'error': 'video_id is required'}),
            status=400,
            mimetype='application/json'
        )

    try:
        fetched = ytt_api.fetch(video_id)
        entries = fetched.to_raw_data()
        text = ' '.join([e['text'] for e in entries])
        return Response(
            json.dumps({'transcript': text, 'word_count': len(text.split())}),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        error = str(e)
        status = 404 if 'disabled' in error.lower() or 'no transcript' in error.lower() else 500
        return Response(
            json.dumps({'error': error}),
            status=status,
            mimetype='application/json'
        )