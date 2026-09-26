from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from typing import List, Dict, Any, Optional
import hashlib

class TranscriptService:
    @staticmethod
    def fetch_transcript(video_id: str, preferred_language: str = "en") -> List[Dict[str, Any]]:
        """
        Fetches the transcript for the given video_id.
        Tries youtube_transcript_api first, then falls back to yt-dlp if IP blocked.
        """
        try:
            transcript_list = YouTubeTranscriptApi().list(video_id)
            
            transcript = None
            try:
                transcript = transcript_list.find_transcript([preferred_language])
            except NoTranscriptFound:
                pass
                
            if not transcript and preferred_language != "en":
                try:
                    transcript = transcript_list.find_transcript(["en"])
                except NoTranscriptFound:
                    pass
            
            if not transcript:
                transcript = next(iter(transcript_list))
                
            if transcript.is_translatable and transcript.language_code != preferred_language:
                try:
                    transcript = transcript.translate(preferred_language)
                except Exception:
                    pass
                    
            return transcript.fetch().to_raw_data()
            
        except Exception as api_err:
            print(f"youtube-transcript-api failed ({api_err}). Falling back to yt-dlp...")
            # Fallback to yt-dlp when IP is blocked
            try:
                import yt_dlp
                import httpx
                
                ydl_opts = {'quiet': True, 'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    subs = info.get('subtitles') or {}
                    auto_subs = info.get('automatic_captions') or {}
                    
                    target_sub = None
                    for lang in [preferred_language, 'en']:
                        if lang in subs:
                            target_sub = subs[lang]
                            break
                        if lang in auto_subs:
                            target_sub = auto_subs[lang]
                            break
                    
                    if not target_sub:
                        if subs: target_sub = list(subs.values())[0]
                        elif auto_subs: target_sub = list(auto_subs.values())[0]
                        else: raise Exception("No subtitles found via fallback.")
                        
                    json3_url = next((s['url'] for s in target_sub if s['ext'] == 'json3'), None)
                    if not json3_url:
                        raise Exception("No JSON3 subtitle format found via fallback.")
                        
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    res = httpx.get(json3_url, headers=headers, timeout=30.0)
                    if res.status_code != 200:
                        raise Exception(f"Failed to fetch subtitle URL, got status {res.status_code}")
                    data = res.json()
                    
                    transcript_data = []
                    for event in data.get('events', []):
                        if 'segs' not in event: continue
                        text = "".join(seg.get('utf8', '') for seg in event['segs']).strip()
                        if not text: continue
                        
                        start = event.get('tStartMs', 0) / 1000.0
                        duration = event.get('dDurationMs', 0) / 1000.0
                        transcript_data.append({
                            "text": text,
                            "start": start,
                            "duration": duration
                        })
                    return transcript_data
                    
            except Exception as fallback_err:
                raise Exception(f"Failed to fetch transcript (both API and fallback failed). Fallback error: {str(fallback_err)}")

    @staticmethod
    def get_transcript_hash(transcript_data: List[Dict[str, Any]]) -> str:
        """
        Returns a deterministic hash of the transcript data.
        """
        text_content = "".join([t.get("text", "") for t in transcript_data])
        return hashlib.sha256(text_content.encode('utf-8')).hexdigest()

    @staticmethod
    def chunk_transcript(transcript_data: List[Dict[str, Any]], 
                         max_tokens: int = 1200, 
                         overlap_tokens: int = 200) -> List[Dict[str, Any]]:
        """
        Chunks the transcript while preserving timestamp boundaries.
        Uses a simplistic character count estimation for tokens (approx 4 chars/token) 
        if tiktoken is too slow, but here we can just use word boundaries or characters
        for simplicity, ensuring we don't break individual transcript lines.
        """
        # A simple token approximation: 1 token ~= 4 characters
        max_chars = max_tokens * 4
        overlap_chars = overlap_tokens * 4
        
        chunks = []
        current_chunk = []
        current_chars = 0
        current_start = -1.0
        has_new_items = False
        
        for item in transcript_data:
            text = item.get("text", "").strip()
            if not text:
                continue
                
            start = item.get("start", 0.0)
            duration = item.get("duration", 0.0)
            end = start + duration
            
            if current_start == -1.0:
                current_start = start
                
            current_chunk.append({
                "text": text,
                "start": start,
                "end": end
            })
            current_chars += len(text)
            has_new_items = True
            
            if current_chars >= max_chars:
                # Finalize chunk
                chunk_text = " ".join([c["text"] for c in current_chunk])
                chunks.append({
                    "start_time": current_start,
                    "end_time": current_chunk[-1]["end"],
                    "text": chunk_text
                })
                
                # Create overlap by keeping the last few items
                overlap_chars_accum = 0
                overlap_chunk = []
                for past_item in reversed(current_chunk):
                    if overlap_chars_accum >= overlap_chars and len(overlap_chunk) > 0:
                        break
                    overlap_chunk.insert(0, past_item)
                    overlap_chars_accum += len(past_item["text"])
                    
                current_chunk = overlap_chunk
                current_chars = sum(len(c["text"]) for c in current_chunk)
                current_start = current_chunk[0]["start"] if current_chunk else -1.0
                has_new_items = False
                
        # Add remaining
        if current_chunk and has_new_items:
            chunk_text = " ".join([c["text"] for c in current_chunk])
            chunks.append({
                "start_time": current_chunk[0]["start"],
                "end_time": current_chunk[-1]["end"],
                "text": chunk_text
            })
                
        return chunks
