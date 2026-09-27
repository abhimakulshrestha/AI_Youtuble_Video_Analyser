from pydantic import BaseModel, Field
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
    
class AnalyzeRequest(BaseModel):
    url: str
    language: str = "en"
    mode: Literal["quick", "deep"] = "quick"
    transcript_data: Optional[List[Dict[str, Any]]] = None

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
    llm_provider: str = "openrouter"
    llm_model: str
    llm_fallback_model: str | None = None
    groq_model: str | None = None
    video_model: str
    video_fallback_model: str | None = None
