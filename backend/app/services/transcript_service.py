from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from typing import List, Dict, Any
import hashlib
import json


def sample_transcript(transcript: List[Dict[str, Any]], max_chars: int = 12000) -> tuple[List[Dict[str, Any]], bool]:
    context = [
        {"start": item["start"], "end": item["start"] + item.get("duration", 0), "text": item["text"]}
        for item in transcript if item.get("text", "").strip()
    ]
    if not context:
        raise ValueError("No usable transcript segments provided.")
    sampled = len(json.dumps(context, ensure_ascii=False)) > max_chars
    if sampled:
        original = context
        count = min(len(original), 200)
        while True:
            indices = (round(index * (len(original) - 1) / max(1, count - 1)) for index in range(count))
            context = [{**original[index], "text": original[index]["text"][:200]} for index in indices]
            if len(json.dumps(context, ensure_ascii=False)) <= max_chars or count == 1:
                break
            count = max(1, int(count * 0.8))
    return context, sampled

class TranscriptService:
    @staticmethod
    def fetch_transcript(video_id: str, preferred_language: str = "en") -> List[Dict[str, Any]]:
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
        except (TranscriptsDisabled, NoTranscriptFound) as exc:
            raise ValueError("This video has no accessible captions.") from exc
        except Exception as exc:
            raise RuntimeError("YouTube did not provide captions to the server. Reload the extension and YouTube tab, then retry.") from exc

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
