from app.utils.youtube import extract_video_id, is_valid_youtube_id

def test_extract_video_id():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == "dQw4w9WgXcQ"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("invalid") is None

def test_is_valid_youtube_id():
    assert is_valid_youtube_id("dQw4w9WgXcQ") is True
    assert is_valid_youtube_id("dQw4w9WgXcQ_") is False
    assert is_valid_youtube_id("dQw4w9WgXc-") is True
    assert is_valid_youtube_id("dQw4w9WgXc") is False
    assert is_valid_youtube_id("dQw4w9WgXcQ1") is False
