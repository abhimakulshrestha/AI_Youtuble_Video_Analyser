from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.schemas import VideoAnalysis, VideoFrame


TranscriptData = list[dict[str, Any]]


class EvidenceCheck(BaseModel):
    point_index: int
    start: float | None = None
    status: Literal["matched", "uncertain", "unsupported"]
    transcript_excerpt: str = ""


class PlanRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=300)
    minutes: int = Field(ge=1, le=60)
    transcript_data: TranscriptData | None = None
    analysis: VideoAnalysis | None = None


class PlanClip(BaseModel):
    title: str
    reason: str
    start: float
    end: float


class WatchPlan(BaseModel):
    goal: str
    budget_seconds: int
    total_seconds: float
    clips: list[PlanClip]


class StudyRequest(BaseModel):
    transcript_data: TranscriptData | None = None
    analysis: VideoAnalysis | None = None


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    answer_index: int
    explanation: str
    start: float


class Flashcard(BaseModel):
    front: str
    back: str
    start: float


class StudySet(BaseModel):
    questions: list[QuizQuestion]
    flashcards: list[Flashcard]


class ClaimRequest(BaseModel):
    transcript_data: TranscriptData | None = None
    analysis: VideoAnalysis | None = None


class ClaimCandidate(BaseModel):
    text: str
    start: float
    status: Literal["unchecked"] = "unchecked"


class ClaimCheckRequest(BaseModel):
    claim: str = Field(min_length=5, max_length=500)


class ExternalSource(BaseModel):
    title: str
    url: str


class ClaimCheckResult(BaseModel):
    claim: str
    verdict: Literal["supported", "disputed", "unclear", "unchecked"]
    explanation: str
    sources: list[ExternalSource]


class ComparisonVideo(BaseModel):
    video_id: str
    title: str
    analysis: VideoAnalysis
    transcript_data: TranscriptData


class CompareRequest(BaseModel):
    videos: list[ComparisonVideo] = Field(min_length=2, max_length=4)
    question: str = Field(default="What do these videos agree and disagree about?", max_length=300)


class VideoReference(BaseModel):
    video_id: str
    start: float
    excerpt: str = ""
    status: Literal["matched", "uncertain", "unsupported"] = "uncertain"


class ComparisonFinding(BaseModel):
    text: str
    references: list[VideoReference]


class CompareResult(BaseModel):
    summary: str
    agreements: list[ComparisonFinding]
    differences: list[ComparisonFinding]


class VisualEvent(BaseModel):
    start: float
    kind: str
    description: str


class VisualGap(BaseModel):
    start: float
    visual_detail: str
    spoken_context: str
    why_it_matters: str


class DeepAnalysis(BaseModel):
    visual_summary: str
    visual_events: list[VisualEvent] = Field(default_factory=list)
    visual_gaps: list[VisualGap] = Field(default_factory=list)


class VisualRequest(BaseModel):
    transcript_data: TranscriptData | None = None
    frames: list[VideoFrame] = Field(min_length=1, max_length=3)
