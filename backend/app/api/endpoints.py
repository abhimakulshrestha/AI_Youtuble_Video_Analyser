import re

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.schemas import AnalyzeRequest, ChatRequest, ChatResponse, HealthResponse
from app.models.features import (
    ClaimCheckRequest, ClaimRequest, CompareRequest, CompareResult, PlanRequest,
    WatchPlan, StudyRequest, StudySet, ClaimCandidate, DeepAnalysis,
    VisualRequest,
)
from app.services.evidence import bound_start, check_analysis, check_excerpt, video_end
from app.services.llm_service import LLMService
from app.services.multimodal_service import MultimodalService
from app.services.groq_client import GroqError
from app.services.transcript_service import TranscriptService, sample_transcript
from app.utils.youtube import extract_video_id, is_valid_youtube_id

router = APIRouter()


def upstream_failure(action: str, exc: Exception) -> HTTPException:
    if isinstance(exc, GroqError):
        status = exc.status_code if exc.status_code in {400, 401, 402, 403, 408, 409, 429} else 502
        return HTTPException(status_code=status, detail=f"{action}: {exc}")
    if isinstance(exc, NotImplementedError):
        return HTTPException(status_code=501, detail=str(exc))
    return HTTPException(status_code=502, detail=f"{action}: {exc}")


def get_transcript_data(video_id: str, language: str, supplied: list[dict] | None) -> list[dict]:
    try:
        transcript = supplied or TranscriptService.fetch_transcript(video_id, language)
        if not transcript or not any(item.get("text", "").strip() for item in transcript):
            raise ValueError("No transcript is available for this video.")
        return transcript
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Transcript unavailable: {exc}") from exc


def select_relevant_chunks(chunks: list[dict], question: str, k: int = 8) -> list[dict]:
    terms = set(re.findall(r"[a-z0-9]{3,}", question.lower())) - {
        "the", "and", "for", "that", "this", "what", "when", "where", "which", "how", "does", "was", "are", "about", "video"
    }
    ranked = sorted(
        enumerate(chunks),
        key=lambda pair: sum(pair[1]["text"].lower().count(term) for term in terms),
        reverse=True,
    )
    return [chunk for _, chunk in sorted(ranked[:k], key=lambda pair: pair[0])]


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        status="ok",
        transcript_provider=True,
        rag_provider=bool(settings.GROQ_API_KEY),
        multimodal_provider=bool(settings.GROQ_API_KEY),
        llm_model=settings.GROQ_MODEL,
        llm_fallback_model=settings.GROQ_FALLBACK_MODEL or None,
        video_model=settings.GROQ_VISION_MODEL,
    )


@router.post("/videos/analyze")
async def analyze_video(request: AnalyzeRequest):
    video_id = extract_video_id(request.url)
    if not video_id or not is_valid_youtube_id(video_id):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL or ID")
    require_groq()

    transcript = get_transcript_data(video_id, request.language, request.transcript_data)
    try:
        analysis, sampled = await LLMService().generate_full_analysis(transcript)
        result = analysis.model_dump()
        result["transcript_data"] = transcript
        result["evidence_checks"] = [check.model_dump() for check in check_analysis(analysis, transcript)]
        if sampled:
            result["feature_warnings"] = ["Long video: analysis uses evenly spaced transcript excerpts, so some details may be missed."]
        return result
    except Exception as exc:
        raise upstream_failure("Analysis failed", exc) from exc


@router.post("/videos/{video_id}/visual", response_model=DeepAnalysis)
async def analyze_visuals(video_id: str, request: VisualRequest):
    require_video(video_id)
    try:
        transcript = get_transcript_data(video_id, "en", request.transcript_data)
        return await MultimodalService().analyze_frames(request.frames, transcript)
    except Exception as exc:
        raise upstream_failure("Visual analysis failed", exc) from exc


@router.post("/videos/{video_id}/ask", response_model=ChatResponse)
async def ask_question(video_id: str, request: ChatRequest):
    if not is_valid_youtube_id(video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")
    require_groq()

    transcript = get_transcript_data(video_id, "en", request.transcript_data)
    chunks = TranscriptService.chunk_transcript(transcript, max_tokens=300, overlap_tokens=40)
    if not chunks:
        raise HTTPException(status_code=400, detail="No usable transcript segments were found.")
    selected = select_relevant_chunks(chunks, f"{request.question} {request.context_hints or ''}")
    if request.focus_time is not None:
        nearby = sorted(chunks, key=lambda chunk: abs(chunk["start_time"] - request.focus_time))[:2]
        selected = sorted({id(chunk): chunk for chunk in selected + nearby}.values(), key=lambda chunk: chunk["start_time"])
    try:
        result = await LLMService().answer_question(request.question, selected)
        for citation in result.get("citations", []):
            status, spoken = check_excerpt(citation.get("start", -1), citation.get("excerpt", ""), transcript)
            citation["status"] = status
            citation["excerpt"] = spoken or citation.get("excerpt", "")
        return ChatResponse(**result)
    except Exception as exc:
        raise upstream_failure("Failed to generate answer", exc) from exc


def require_video(video_id: str) -> None:
    if not is_valid_youtube_id(video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")
    require_groq()


def require_groq() -> None:
    if not settings.GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured on the server.")


def short_context(transcript: list[dict], analysis=None) -> dict:
    sampled, _ = sample_transcript(transcript, max_chars=10000)
    return {
        "analysis": {"summary": analysis.executive_summary[:1600], "key_points": [point.model_dump() for point in analysis.key_points[:12]], "chapters": [chapter.model_dump() for chapter in analysis.chapters[:20]]} if analysis else None,
        "transcript": sampled,
        "duration": video_end(transcript),
    }


@router.post("/videos/{video_id}/plan", response_model=WatchPlan)
async def create_plan(video_id: str, request: PlanRequest):
    require_video(video_id)
    transcript = get_transcript_data(video_id, "en", request.transcript_data)
    try:
        context = short_context(transcript, request.analysis)
        chunks = TranscriptService.chunk_transcript(transcript, max_tokens=250, overlap_tokens=0)
        context["transcript"] = [
            {"start": chunk["start_time"], "end": chunk["end_time"], "text": chunk["text"][:1400]}
            for chunk in select_relevant_chunks(chunks, request.goal, k=6)
        ]
        data = await LLMService().generate_json(
            "Build a goal-based watch plan. Return {clips:[{title,reason,start,end}]}. Choose useful nonoverlapping clips in chronological order that fit the time budget. Each clip must stay within a supplied transcript window; prefer 20-90 second moments over isolated utterances when the source allows it. Explain the contribution of each clip. Prefer actual steps for a practical goal.",
            {"goal": request.goal, "budget_seconds": request.minutes * 60, **context},
        )
        clips = []
        remaining = request.minutes * 60
        for raw in sorted(data.get("clips", []), key=lambda clip: float(clip["start"])):
            start = bound_start(float(raw["start"]), transcript)
            end = min(bound_start(float(raw["end"]), transcript), start + remaining)
            if clips and start < clips[-1]["end"]:
                start = clips[-1]["end"]
            if end <= start or remaining <= 0:
                continue
            clips.append({"title": str(raw["title"]), "reason": str(raw["reason"]), "start": start, "end": end})
            remaining -= end - start
        if not clips:
            raise ValueError("No usable clips were returned.")
        return WatchPlan(goal=request.goal, budget_seconds=request.minutes * 60, total_seconds=sum(c["end"] - c["start"] for c in clips), clips=clips)
    except Exception as exc:
        raise upstream_failure("Watch plan failed", exc) from exc


@router.post("/videos/{video_id}/study", response_model=StudySet)
async def create_study_set(video_id: str, request: StudyRequest):
    require_video(video_id)
    transcript = get_transcript_data(video_id, "en", request.transcript_data)
    try:
        data = await LLMService().generate_json(
            "Create a small study set grounded in the transcript. Return {questions:[{question,options:[four choices],answer_index:0..3,explanation,start}],flashcards:[{front,back,start}]}. Use only available source timestamps. No trick questions.",
            short_context(transcript, request.analysis),
        )
        result = StudySet.model_validate(data)
        result.questions = [q for q in result.questions if len(q.options) == 4 and 0 <= q.answer_index < 4 and 0 <= q.start <= video_end(transcript)]
        result.flashcards = [card for card in result.flashcards if 0 <= card.start <= video_end(transcript)]
        return result
    except Exception as exc:
        raise upstream_failure("Study set failed", exc) from exc


@router.post("/videos/{video_id}/claims", response_model=list[ClaimCandidate])
async def extract_claims(video_id: str, request: ClaimRequest):
    require_video(video_id)
    transcript = get_transcript_data(video_id, "en", request.transcript_data)
    try:
        data = await LLMService().generate_json(
            "Identify at most five objectively checkable factual claims actually spoken in this transcript. Return {claims:[{text,start}]}. Exclude opinions and advice. Use only source timestamps. Empty list is valid.",
            short_context(transcript, request.analysis),
        )
        return [ClaimCandidate(text=str(item["text"]), start=float(item["start"])) for item in data.get("claims", [])[:5] if 0 <= float(item["start"]) <= video_end(transcript)]
    except Exception as exc:
        raise upstream_failure("Claim extraction failed", exc) from exc


@router.post("/claims/check")
async def check_claim(request: ClaimCheckRequest):
    require_groq()
    try:
        return await MultimodalService().check_claim(request.claim)
    except Exception as exc:
        raise upstream_failure("Claim check failed", exc) from exc


@router.post("/videos/compare", response_model=CompareResult)
async def compare_videos(request: CompareRequest):
    require_groq()
    if len({v.video_id for v in request.videos}) != len(request.videos) or any(not is_valid_youtube_id(v.video_id) for v in request.videos):
        raise HTTPException(status_code=400, detail="Provide distinct valid YouTube videos.")
    try:
        data = await LLMService().generate_json(
            "Compare only the supplied videos. Return {summary,agreements:[{text,references:[{video_id,start,excerpt}]}],differences:[same]}. Every finding needs references from at least two distinct videos. Include exact short transcript excerpts where possible. If none, use empty arrays. Do not manufacture contradictions.",
            {"question": request.question, "videos": [{"video_id": v.video_id, "title": v.title, **short_context(v.transcript_data, v.analysis)} for v in request.videos]},
        )
        result = CompareResult.model_validate(data)
        videos = {v.video_id: v for v in request.videos}
        for group in (result.agreements, result.differences):
            for finding in group:
                finding.references = [ref for ref in finding.references if ref.video_id in videos]
                for ref in finding.references:
                    ref.status, spoken = check_excerpt(ref.start, ref.excerpt, videos[ref.video_id].transcript_data)
                    if spoken:
                        ref.excerpt = spoken
            group[:] = [finding for finding in group if len({ref.video_id for ref in finding.references if ref.status != "unsupported"}) >= 2]
        return result
    except Exception as exc:
        raise upstream_failure("Comparison failed", exc) from exc
