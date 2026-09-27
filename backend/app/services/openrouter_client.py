import json
from typing import Any

import httpx

from app.config import settings


FREE_MODEL_PROVIDERS = {
    "qwen/qwen3.8-27b:free": "modelrun/fp4",
    "google/gemma-4-31b-it:free": "google-ai-studio",
}


class OpenRouterError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class OpenRouterClient:
    def __init__(self):
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not set.")
        self.url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": settings.OPENROUTER_APP_NAME,
        }
        if settings.OPENROUTER_SITE_URL:
            self.headers["HTTP-Referer"] = settings.OPENROUTER_SITE_URL

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4000,
        temperature: float = 0.2,
        tools: list[dict[str, Any]] | None = None,
        max_tool_calls: int | None = None,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or settings.OPENROUTER_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        provider = FREE_MODEL_PROVIDERS.get(payload["model"])
        if provider:
            payload["provider"] = {"only": [provider], "allow_fallbacks": False}
        if settings.OPENROUTER_REASONING_ENABLED:
            payload["reasoning"] = {"enabled": True, "exclude": True}
        if tools:
            payload["tools"] = tools
        if max_tool_calls is not None:
            payload["max_tool_calls"] = max_tool_calls
        if response_format:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
            response = await client.post(self.url, headers=self.headers, json=payload)

        if response.is_error:
            try:
                error = response.json().get("error", {})
                message = error.get("message") or response.reason_phrase
                metadata = error.get("metadata") or {}
                provider = metadata.get("provider_name") or metadata.get("provider")
                raw = metadata.get("raw")
                if isinstance(raw, str) and raw.strip():
                    try:
                        raw_data = json.loads(raw)
                        raw_error = raw_data.get("error", raw_data) if isinstance(raw_data, dict) else {}
                        raw_message = raw_error.get("message") if isinstance(raw_error, dict) else None
                        message = raw_message or message
                    except ValueError:
                        if len(raw) <= 300:
                            message = raw
                if provider:
                    message = f"{message} (provider: {provider})"
            except ValueError:
                message = response.reason_phrase
            raise OpenRouterError(response.status_code, f"OpenRouter request failed: {message}")

        data = response.json()
        if data.get("error"):
            error = data["error"]
            message = error.get("message") or "Provider returned error"
            try:
                message = json.loads(message).get("message", message)
            except (ValueError, AttributeError):
                pass
            code = error.get("code")
            raise OpenRouterError(code if isinstance(code, int) and 400 <= code <= 599 else 502, f"OpenRouter request failed: {message}")
        if not data.get("choices"):
            raise OpenRouterError(502, "OpenRouter returned no completion choices.")
        return data


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


def first_message(response: dict[str, Any]) -> dict[str, Any]:
    return response["choices"][0].get("message", {})
