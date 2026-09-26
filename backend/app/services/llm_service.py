import json
from typing import Any

from app.config import settings
from app.models.schemas import VideoAnalysis
from app.services.openrouter_client import OpenRouterClient, OpenRouterError, first_message, message_text


def parse_json_object(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The model did not return a JSON object.")
    return json.loads(value[start:end + 1])


class LLMService:
    def __init__(self, client: OpenRouterClient | None = None):
        self.client = client or OpenRouterClient()

    async def generate_json(self, instruction: str, payload: Any) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": instruction + " Return only one valid JSON object without Markdown. Never invent source timestamps or quotes.",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        models = list(dict.fromkeys(filter(None, [settings.OPENROUTER_MODEL, settings.OPENROUTER_FALLBACK_MODEL])))
        last_error: Exception | None = None
        for index, model in enumerate(models):
            try:
                response = await self.client.chat(
                    messages,
                    model=model,
                    max_tokens=6000,
                    response_format={"type": "json_object"},
                )
                return parse_json_object(message_text(first_message(response)))
            except OpenRouterError as exc:
                last_error = exc
                retryable = exc.status_code in {404, 408, 409, 429} or exc.status_code >= 500
                if not retryable or index == len(models) - 1:
                    raise
            except ValueError as exc:
                last_error = exc
                if index == len(models) - 1:
                    raise
        raise last_error or RuntimeError("No OpenRouter text model is configured.")

    async def generate_full_analysis(self, chunks: list[dict[str, Any]]) -> VideoAnalysis:
        if not chunks:
            raise ValueError("No transcript chunks provided.")
        context = [
            {"start": item["start_time"], "end": item["end_time"], "text": item["text"]}
            for item in chunks
        ]
        data = await self.generate_json(
            """Analyze this video transcript comprehensively. Use this exact schema:
            {"executive_summary":string,"detailed_summary":string,"content_type":string|null,
            "key_points":[{"title":string,"explanation":string,"evidence":[{"start":number,"end":number|null,"text":string|null}]}],
            "chapters":[{"title":string,"start":number,"end":number,"summary":string,"key_points":[string]}],
            "topics":[{"name":string,"description":string,"importance":string|null,"timestamp_ranges":[{"start":number,"end":number|null,"text":string|null}]}],
            "entities":[object],"terminology":[{"term":string,"definition":string}],"statistics":[object],
            "action_items":[object],"conclusions":[string]}.
            Evidence text must quote the supplied transcript exactly. Use only supplied timestamps.""",
            {"transcript": context},
        )
        return VideoAnalysis.model_validate(data)

    async def answer_question(self, question: str, retrieved_docs: list[dict[str, Any]]) -> dict[str, Any]:
        context = [
            {"start": item["start_time"], "end": item["end_time"], "text": item["text"]}
            for item in retrieved_docs
        ]
        return await self.generate_json(
            """Answer strictly from the supplied transcript. If it is insufficient, say so. Return:
            {"answer":string,"citations":[{"start":number,"end":number,"label":string,"excerpt":string}]}.
            Citation excerpts must be exact transcript quotes and timestamps must come from the supplied segments.""",
            {"question": question, "transcript": context},
        )
