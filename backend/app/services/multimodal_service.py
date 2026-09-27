import re

from app.config import settings
from app.models.features import ClaimCheckResult, DeepAnalysis, ExternalSource
from app.services.llm_service import parse_json_object
from app.services.openrouter_client import OpenRouterClient, OpenRouterError, first_message, message_text


class MultimodalService:
    def __init__(self, client: OpenRouterClient | None = None):
        self.client = client or OpenRouterClient()

    async def analyze_video(self, video_url: str, transcript: list[dict] | None = None) -> dict:
        transcript_context = [
            {"start": item.get("start", 0), "text": str(item.get("text", ""))[:500]}
            for item in (transcript or [])[::max(1, len(transcript or []) // 120 or 1)][:120]
        ]
        prompt = (
            "Analyze the video's audio and visuals together. Return only JSON with this shape: "
            '{"visual_summary":string,"visual_events":[{"start":number,"kind":string,"description":string}],'
            '"visual_gaps":[{"start":number,"visual_detail":string,"spoken_context":string,"why_it_matters":string}]}. '
            "visual_gaps are useful information clearly visible in slides, charts, diagrams, or demonstrations but barely or never spoken. "
            "Use timestamps in seconds. Do not invent details. Empty arrays are correct when no evidence exists. "
            f"Use this sampled narration transcript to distinguish shown content from spoken content: {transcript_context}"
        )
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "video_url", "video_url": {"url": video_url}},
            ],
        }]
        try:
            return await self._analyze_with_model(messages, settings.OPENROUTER_VIDEO_MODEL)
        except OpenRouterError as exc:
            can_retry = exc.status_code in {404, 408, 409, 429} or exc.status_code >= 500
            if not settings.OPENROUTER_VIDEO_FALLBACK_MODEL or not can_retry:
                raise
            return await self._analyze_with_model(messages, settings.OPENROUTER_VIDEO_FALLBACK_MODEL)
        except ValueError:
            if not settings.OPENROUTER_VIDEO_FALLBACK_MODEL:
                raise
            return await self._analyze_with_model(messages, settings.OPENROUTER_VIDEO_FALLBACK_MODEL)

    async def _analyze_with_model(self, messages: list[dict], model: str) -> dict:
        response = await self.client.chat(
            messages,
            model=model,
            response_format={"type": "json_object"},
            max_tokens=5000,
        )
        data = parse_json_object(message_text(first_message(response)))
        return DeepAnalysis.model_validate(data).model_dump()

    async def check_claim(self, claim: str) -> ClaimCheckResult:
        response = await self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You verify factual claims using web search. You must search before answering. "
                        "Begin with exactly SUPPORTED, DISPUTED, or UNCLEAR, then give a concise evidence-based explanation."
                    ),
                },
                {"role": "user", "content": claim},
            ],
            tools=[{
                "type": "openrouter:web_search",
                "parameters": {"engine": "auto", "max_results": 5, "max_total_results": 5, "max_uses": 1},
            }],
            max_tool_calls=1,
            max_tokens=1200,
        )
        message = first_message(response)
        answer = message_text(message).strip()
        sources: list[ExternalSource] = []
        for annotation in message.get("annotations", []) or []:
            if annotation.get("type") != "url_citation":
                continue
            citation = annotation.get("url_citation", annotation)
            url = str(citation.get("url", ""))
            if url.startswith(("https://", "http://")) and url not in {source.url for source in sources}:
                sources.append(ExternalSource(url=url, title=str(citation.get("title") or url)))

        prefix = re.split(r"[\s:.-]", answer, maxsplit=1)[0].lower() if answer else ""
        verdict = prefix if sources and prefix in {"supported", "disputed", "unclear"} else "unchecked"
        return ClaimCheckResult(
            claim=claim,
            verdict=verdict,
            explanation=answer or "OpenRouter returned no claim-check explanation.",
            sources=sources,
        )
