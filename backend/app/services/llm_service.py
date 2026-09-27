import json
from typing import Any

from app.config import settings
from app.models.schemas import VideoAnalysis
from app.services.groq_client import GroqClient, GroqError, first_message, message_text


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
    def __init__(self, client: GroqClient | None = None):
        self.client = client or GroqClient()

    async def generate_json(self, instruction: str, payload: Any) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": instruction + " Return only one valid JSON object without Markdown. Never invent source timestamps or quotes.",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        models = list(dict.fromkeys(filter(None, [settings.GROQ_MODEL, settings.GROQ_FALLBACK_MODEL])))
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
            except GroqError as exc:
                last_error = exc
                retryable = exc.status_code in {404, 408, 409, 429} or exc.status_code >= 500 or (
                    exc.status_code == 400 and "Failed to generate JSON" in str(exc)
                )
                if not retryable or index == len(models) - 1:
                    raise
            except ValueError as exc:
                last_error = exc
                if index == len(models) - 1:
                    raise
        raise last_error or RuntimeError("No text model is configured.")

    async def generate_full_analysis(self, transcript: list[dict[str, Any]]) -> tuple[VideoAnalysis, bool]:
        if not transcript:
            raise ValueError("No transcript segments provided.")
        context = [
            {"start": item["start"], "end": item["start"] + item.get("duration", 0), "text": item["text"]}
            for item in transcript if item.get("text", "").strip()
        ]
        if not context:
            raise ValueError("No usable transcript segments provided.")
        sampled = len(json.dumps(context, ensure_ascii=False)) > 12000
        if sampled:
            original = context
            count = min(len(original), 200)
            while True:
                indices = (round(index * (len(original) - 1) / max(1, count - 1)) for index in range(count))
                context = [{**original[index], "text": original[index]["text"][:200]} for index in indices]
                if len(json.dumps(context, ensure_ascii=False)) <= 12000 or count == 1:
                    break
                count = max(1, int(count * 0.8))
        data = await self.generate_json(
            """Analyze only the supplied transcript excerpts; do not imply unsampled moments were reviewed. Use this exact schema:
            {"executive_summary":string,"detailed_summary":string,"content_type":string|null,
            "key_points":[{"title":string,"explanation":string,"evidence":[{"start":number,"end":number|null,"text":string|null}]}],
            "chapters":[{"title":string,"start":number,"end":number,"summary":string,"key_points":[string]}],
            "topics":[{"name":string,"description":string,"importance":string|null,"timestamp_ranges":[{"start":number,"end":number|null,"text":string|null}]}],
            "entities":[object],"terminology":[{"term":string,"definition":string}],"statistics":[object],
            "action_items":[object],"conclusions":[string]}.
            Evidence text must quote the supplied transcript exactly. Use only supplied timestamps.""",
            {"transcript": context},
        )
        return VideoAnalysis.model_validate(data), sampled

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
