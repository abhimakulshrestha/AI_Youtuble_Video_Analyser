from typing import Any

import httpx

from app.config import settings


class GroqError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class GroqClient:
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int = 4000,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "temperature": 0.2,
        }
        if model == "qwen/qwen3.8-27b":
            payload["reasoning_effort"] = "none"
        elif tools:
            payload["reasoning_effort"] = "low"
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                json=payload,
            )
        if response.is_error:
            try:
                message = response.json().get("error", {}).get("message") or response.reason_phrase
            except ValueError:
                message = response.reason_phrase
            raise GroqError(response.status_code, f"Groq request failed: {message}")
        data = response.json()
        if not data.get("choices"):
            raise GroqError(502, "Groq returned no completion choices.")
        return data


def first_message(response: dict[str, Any]) -> dict[str, Any]:
    return response["choices"][0].get("message", {})


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)) if isinstance(content, list) else ""
