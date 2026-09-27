import re

from app.config import settings
from app.models.features import ClaimCheckResult, DeepAnalysis, ExternalSource
from app.models.schemas import VideoFrame
from app.services.groq_client import GroqClient, first_message, message_text
from app.services.llm_service import parse_json_object


class MultimodalService:
    def __init__(self, client: GroqClient | None = None):
        self.client = client or GroqClient()

    async def analyze_frames(self, frames: list[VideoFrame], transcript: list[dict]) -> dict:
        content = [{"type": "text", "text": (
            "Examine only these timestamped video frames and compare visible content with the nearby spoken transcript. "
            "Return one JSON object with visual_summary, visual_events:[{start,kind,description}], "
            "visual_gaps:[{start,visual_detail,spoken_context,why_it_matters}]. "
            "Use only supplied frame timestamps. A visual gap requires a concrete visible detail absent from nearby narration; "
            "do not claim it was never said elsewhere. Empty arrays are valid. "
            f"Nearby transcript: {self._nearby_transcript(frames, transcript)}"
        )}]
        for frame in frames:
            content.extend([
                {"type": "text", "text": f"Frame at {frame.start:.1f} seconds:"},
                {"type": "image_url", "image_url": {"url": frame.image}},
            ])
        response = await self.client.chat(
            [{"role": "user", "content": content}], model=settings.GROQ_VISION_MODEL,
            max_tokens=600, response_format={"type": "json_object"},
        )
        result = DeepAnalysis.model_validate(parse_json_object(message_text(first_message(response))))
        allowed = [frame.start for frame in frames]
        events = []
        gaps = []
        for event in result.visual_events:
            nearest = min(allowed, key=lambda start: abs(start - event.start))
            if abs(nearest - event.start) <= 2:
                events.append(event.model_copy(update={"start": nearest}))
        for gap in result.visual_gaps:
            nearest = min(allowed, key=lambda start: abs(start - gap.start))
            if abs(nearest - gap.start) <= 2:
                gaps.append(gap.model_copy(update={"start": nearest}))
        return DeepAnalysis(
            visual_summary=f"Sampled {len(frames)} frames. {result.visual_summary.strip()}",
            visual_events=events, visual_gaps=gaps,
        ).model_dump()

    @staticmethod
    def _nearby_transcript(frames: list[VideoFrame], transcript: list[dict]) -> list[dict]:
        return [
            {"start": item.get("start", 0), "text": str(item.get("text", ""))[:300]}
            for item in transcript
            if any(abs(float(item.get("start", 0)) - frame.start) <= 15 for frame in frames)
        ][:30]

    async def check_claim(self, claim: str) -> ClaimCheckResult:
        response = await self.client.chat(
            [{"role": "user", "content": (
                "Search outside sources to check this factual claim. Begin with SUPPORTED, DISPUTED, or UNCLEAR, "
                "then give a concise explanation grounded in the retrieved sources. Claim: " + claim
            )}],
            model=settings.GROQ_SEARCH_MODEL,
            tools=[{"type": "browser_search"}], tool_choice="required", max_tokens=1200,
        )
        message = first_message(response)
        answer = message_text(message).strip()
        sources: list[ExternalSource] = []
        for tool in message.get("executed_tools", []) or []:
            for item in (tool.get("search_results") or {}).get("results", []):
                url = str(item.get("url", ""))
                if url.startswith(("https://", "http://")) and url not in {source.url for source in sources}:
                    sources.append(ExternalSource(url=url, title=str(item.get("title") or url)))
        marker = re.match(r"\W*(SUPPORTED|DISPUTED|UNCLEAR)\b", answer, re.IGNORECASE)
        verdict = marker.group(1).lower() if sources and marker else "unchecked"
        return ClaimCheckResult(
            claim=claim, verdict=verdict,
            explanation=answer or "Groq returned no claim-check explanation.", sources=sources[:5],
        )
