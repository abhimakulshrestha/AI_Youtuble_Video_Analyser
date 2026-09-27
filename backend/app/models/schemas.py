import base64
import binascii

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Literal

class TimestampEvidence(BaseModel):
    start: float
    end: Optional[float] = None
    text: Optional[str] = None

class KeyPoint(BaseModel):
    title: str
    explanation: str
    evidence: List[TimestampEvidence]

class Chapter(BaseModel):
    title: str
    start: float
    end: float
    summary: str
    key_points: List[str]

class Topic(BaseModel):
    name: str
    description: str
    importance: Optional[str] = None
    timestamp_ranges: List[TimestampEvidence]

class VideoAnalysis(BaseModel):
    executive_summary: str
    detailed_summary: str
    content_type: Optional[str] = None
    key_points: List[KeyPoint]
    chapters: List[Chapter]
    topics: List[Topic]
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    terminology: List[Dict[str, Any]] = Field(default_factory=list)
    statistics: List[Dict[str, Any]] = Field(default_factory=list)
    action_items: List[Dict[str, Any]] = Field(default_factory=list)
    conclusions: List[str] = Field(default_factory=list)

    @field_validator("key_points", "chapters", "topics", "entities", "terminology", "statistics", "action_items", mode="before")
    @classmethod
    def discard_empty_records(cls, value: Any) -> Any:
        return [item for item in value if isinstance(item, (dict, BaseModel))] if isinstance(value, list) else value

    @field_validator("conclusions", mode="before")
    @classmethod
    def normalize_conclusions(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

class VideoFrame(BaseModel):
    start: float = Field(ge=0)
    image: str

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        header, separator, encoded = value.partition(",")
        if header not in {"data:image/jpeg;base64", "data:image/png;base64"} or not separator or len(value) > 340_000:
            raise ValueError("Frame must be a JPEG or PNG data URL under 250 KB.")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Frame has invalid base64 data.") from exc
        valid = image.startswith(b"\xff\xd8\xff") if "jpeg" in header else image.startswith(b"\x89PNG\r\n\x1a\n")
        if not valid or len(image) < 20 or len(image) > 250_000:
            raise ValueError("Frame must contain an image under 250 KB.")
        return value
    
class AnalyzeRequest(BaseModel):
    url: str
    language: str = "en"
    mode: Literal["quick", "deep"] = "quick"
    transcript_data: Optional[List[Dict[str, Any]]] = None
    frames: Optional[List[VideoFrame]] = Field(default=None, max_length=3)

class ChatRequest(BaseModel):
    question: str
    context_hints: Optional[str] = None
    transcript_data: Optional[List[Dict[str, Any]]] = None
    focus_time: Optional[float] = Field(default=None, ge=0)

class Citation(BaseModel):
    start: float
    end: float
    label: str
    excerpt: str
    status: Literal["matched", "uncertain", "unsupported"] = "uncertain"

class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]

class HealthResponse(BaseModel):
    status: str
    transcript_provider: bool
    rag_provider: bool
    multimodal_provider: bool
    llm_provider: str = "groq"
    llm_model: str
    llm_fallback_model: str | None = None
    video_model: str
