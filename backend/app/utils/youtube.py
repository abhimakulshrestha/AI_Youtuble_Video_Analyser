import re
from urllib.parse import urlparse, parse_qs
from typing import Optional

def extract_video_id(url: str) -> Optional[str]:
    """
    Extracts the YouTube video ID from a given URL.
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    """
    if not url:
        return None

    # Handle youtu.be format
    if "youtu.be" in url:
        parsed = urlparse(url)
        return parsed.path.lstrip("/")
        
    # Handle standard watch URLs
    if "youtube.com/watch" in url:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        return query.get("v", [None])[0]
        
    # Handle shorts
    if "youtube.com/shorts/" in url:
        parsed = urlparse(url)
        parts = parsed.path.split("/")
        if len(parts) >= 3 and parts[1] == "shorts":
            return parts[2]
            
    # Handle embed
    if "youtube.com/embed/" in url:
        parsed = urlparse(url)
        parts = parsed.path.split("/")
        if len(parts) >= 3 and parts[1] == "embed":
            return parts[2]

    # If it's just an 11-character string, assume it's an ID
    if re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        return url
        
    return None

def is_valid_youtube_id(video_id: str) -> bool:
    if not video_id:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_-]{11}$", video_id))
