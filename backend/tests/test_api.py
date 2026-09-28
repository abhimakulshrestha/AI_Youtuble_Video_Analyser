from fastapi.testclient import TestClient
import asyncio
import json
import httpx
import pytest

from app.api import endpoints
from app.main import app
from app.models.schemas import VideoAnalysis
from app.services import llm_service, transcript_service
from app.services import groq_client


VIDEO_ID = "dQw4w9WgXcQ"
TRANSCRIPT = [
    {"text": "A useful explanation of solar power.", "start": 0.0, "duration": 5.0},
    {"text": "Solar panels turn sunlight into electricity.", "start": 5.0, "duration": 5.0},
]


def test_groq_client_uses_qwen_json_mode(monkeypatch):
    monkeypatch.setattr(groq_client.settings, "GROQ_API_KEY", "test-key")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(groq_client.httpx, "AsyncClient", lambda **_: real_client(transport=httpx.MockTransport(respond)))
    result = asyncio.run(groq_client.GroqClient().chat(
        [{"role": "user", "content": "test"}], model="qwen/qwen3.8-27b",
        response_format={"type": "json_object"}, max_tokens=128,
    ))
    assert result["choices"][0]["message"]["content"] == '{"ok":true}'
    assert requests[0]["model"] == "qwen/qwen3.8-27b"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["reasoning_effort"] == "none"
    asyncio.run(groq_client.GroqClient().chat([{"role": "user", "content": "test"}], model="openai/gpt-oss-20b"))
    assert "reasoning_effort" not in requests[1]


class FakeLLM:
    async def generate_full_analysis(self, transcript):
        assert transcript[0]["text"]
        return VideoAnalysis(
            executive_summary="Solar power overview",
            detailed_summary="Solar panels make electricity.",
            key_points=[], chapters=[], topics=[],
        ), False

    async def answer_question(self, question, chunks):
        assert "Solar panels" in chunks[0]["text"]
        return {"answer": "They use sunlight.", "citations": []}


def test_transcript_api_objects_are_normalized(monkeypatch):
    class Fetched:
        def to_raw_data(self):
            return TRANSCRIPT

    class Track:
        is_translatable = False
        language_code = "en"

        def fetch(self):
            return Fetched()

    class Tracks:
        def find_transcript(self, languages):
            return Track()

    class API:
        def list(self, video_id):
            return Tracks()

    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", API)
    result = transcript_service.TranscriptService.fetch_transcript(VIDEO_ID)
    assert result == TRANSCRIPT
    assert transcript_service.TranscriptService.chunk_transcript(result)[0]["start_time"] == 0


def test_transcript_failure_does_not_expose_bot_diagnostics(monkeypatch):
    class BlockedAPI:
        def list(self, video_id):
            raise RuntimeError("Sign in to confirm you're not a bot; use cookies from browser")

    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", BlockedAPI)
    with pytest.raises(RuntimeError, match="YouTube did not provide captions") as exc:
        transcript_service.TranscriptService.fetch_transcript(VIDEO_ID)
    assert "cookies" not in str(exc.value)


def test_analyze_ask_and_cors(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(endpoints, "LLMService", FakeLLM)
    client = TestClient(app)
    preflight = client.options(
        "/api/videos/analyze",
        headers={
            "Origin": "chrome-extension://mooccjcompedlladaghhckoklkjlcnko",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"]

    analysis = client.post(
        "/api/videos/analyze",
        json={"url": f"https://www.youtube.com/watch?v={VIDEO_ID}", "transcript_data": TRANSCRIPT},
    )
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["executive_summary"] == "Solar power overview"

    answer = client.post(
        f"/api/videos/{VIDEO_ID}/ask",
        json={"question": "How do solar panels work?", "transcript_data": TRANSCRIPT},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["answer"] == "They use sunlight."


def test_long_video_question_keeps_groq_context_bounded(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")

    class MeasuringLLM(FakeLLM):
        async def answer_question(self, question, chunks):
            assert sum(len(chunk["text"]) for chunk in chunks) < 16000
            return {"answer": "The context is bounded.", "citations": []}

    monkeypatch.setattr(endpoints, "LLMService", MeasuringLLM)
    transcript = [{"text": "Solar panels turn sunlight into electricity. " * 3, "start": i * 5, "duration": 5} for i in range(400)]
    response = TestClient(app).post(
        f"/api/videos/{VIDEO_ID}/ask",
        json={"question": "How do solar panels work?", "focus_time": 1000, "transcript_data": transcript},
    )
    assert response.status_code == 200, response.text


def test_missing_transcript_is_client_error(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(endpoints.TranscriptService, "fetch_transcript", lambda *_: [])
    response = TestClient(app).post(
        "/api/videos/analyze", json={"url": f"https://www.youtube.com/watch?v={VIDEO_ID}"}
    )
    assert response.status_code == 400
    assert "transcript" in response.json()["detail"].lower()


def test_groq_completion_is_parsed():
    payload = json.dumps({
        "executive_summary": "Summary", "detailed_summary": "Details",
        "key_points": [], "chapters": [], "topics": [],
    })

    class Client:
        async def chat(self, messages, **kwargs):
            assert messages[0]["role"] == "system"
            return {"choices": [{"message": {"content": f"```json\n{payload}\n```"}}]}

    service = llm_service.LLMService(Client())
    analysis, sampled = asyncio.run(service.generate_full_analysis([
        {"start": 0.0, "duration": 5.0, "text": "Transcript text"}
    ]))
    assert analysis.executive_summary == "Summary"
    assert sampled is False


def test_single_conclusion_from_groq_is_normalized():
    analysis = VideoAnalysis.model_validate({
        "executive_summary": "Summary", "detailed_summary": "Details",
        "key_points": [], "chapters": [], "topics": [], "conclusions": "One conclusion",
    })
    assert analysis.conclusions == ["One conclusion"]


def test_blank_model_list_items_are_discarded():
    analysis = VideoAnalysis.model_validate({
        "executive_summary": "Summary", "detailed_summary": "Details",
        "key_points": [], "chapters": [], "topics": ["", {"name": "Solar", "description": "Power", "timestamp_ranges": []}],
    })
    assert len(analysis.topics) == 1


def test_optional_record_objects_from_groq_are_normalized():
    analysis = VideoAnalysis.model_validate({
        "executive_summary": "Summary", "detailed_summary": "Details",
        "key_points": [], "chapters": [], "topics": [],
        "statistics": {}, "action_items": {"task": "Review the clip"},
    })
    assert analysis.statistics == []
    assert analysis.action_items == [{"task": "Review the clip"}]


def test_long_transcript_is_sampled_across_video():
    captured = {}

    class Client:
        async def chat(self, messages, **kwargs):
            captured.update(json.loads(messages[1]["content"]))
            return {"choices": [{"message": {"content": json.dumps({
                "executive_summary": "Sampled", "detailed_summary": "Sampled excerpts",
                "key_points": [], "chapters": [], "topics": [],
            })}}]}

    transcript = [{"text": "Detailed line " * 8, "start": i * 6, "duration": 6} for i in range(600)]
    analysis, sampled = asyncio.run(llm_service.LLMService(Client()).generate_full_analysis(transcript))
    excerpts = captured["transcript"]
    assert analysis.executive_summary == "Sampled"
    assert sampled is True
    assert len(json.dumps(excerpts)) <= 12000
    assert excerpts[0]["start"] == 0
    assert excerpts[-1]["start"] == 3594


def test_feature_context_preserves_segment_timestamps():
    context = endpoints.short_context(TRANSCRIPT)
    assert [item["start"] for item in context["transcript"]] == [0, 5]
    long_context = endpoints.short_context([
        {"text": "Detailed line " * 8, "start": i * 6, "duration": 6} for i in range(600)
    ])
    assert len(json.dumps(long_context["transcript"])) <= 10000
    assert long_context["transcript"][0]["start"] == 0
    assert long_context["transcript"][-1]["start"] == 3594


def test_watch_plan_gets_contiguous_windows(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")

    class MeasuringLLM:
        async def generate_json(self, instruction, payload):
            windows = payload["transcript"]
            assert windows[0]["end"] - windows[0]["start"] >= 20
            assert len(json.dumps(windows)) < 10000
            return {"clips": [{"title": "Solar steps", "reason": "Practical guidance", "start": windows[0]["start"], "end": windows[0]["end"]}]}

    monkeypatch.setattr(endpoints, "LLMService", MeasuringLLM)
    transcript = [{"text": "Inspect the roof and install the solar panel. " * 2, "start": i * 5, "duration": 5} for i in range(400)]
    response = TestClient(app).post(
        f"/api/videos/{VIDEO_ID}/plan",
        json={"goal": "Practical solar steps", "minutes": 3, "transcript_data": transcript},
    )
    assert response.status_code == 200, response.text
    assert response.json()["clips"][0]["end"] - response.json()["clips"][0]["start"] >= 20


def test_text_analysis_falls_back_from_gpt_oss_to_qwen():
    calls = []

    class Client:
        async def chat(self, messages, **kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise llm_service.GroqError(503, "GPT-OSS unavailable")
            return {"choices": [{"message": {"content": json.dumps({
                "executive_summary": "Fallback summary",
                "detailed_summary": "Fallback details",
                "key_points": [], "chapters": [], "topics": [],
            })}}]}

    service = llm_service.LLMService(Client())
    analysis, _ = asyncio.run(service.generate_full_analysis([
        {"start": 0.0, "duration": 5.0, "text": "Transcript text"}
    ]))
    assert analysis.executive_summary == "Fallback summary"
    assert calls == [llm_service.settings.GROQ_MODEL, llm_service.settings.GROQ_FALLBACK_MODEL]


def test_invalid_groq_json_falls_back_to_qwen():
    calls = []

    class Client:
        async def chat(self, messages, **kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise llm_service.GroqError(400, "Failed to validate JSON. Please adjust your prompt.")
            return {"choices": [{"message": {"content": '{"answer":"Grounded answer","citations":[]}'}}]}

    result = asyncio.run(llm_service.LLMService(Client()).answer_question("What happened?", []))
    assert result["answer"] == "Grounded answer"
    assert calls == [llm_service.settings.GROQ_MODEL, llm_service.settings.GROQ_FALLBACK_MODEL]


def test_health_names_groq(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["llm_provider"] == "groq"
    assert response.json()["llm_model"] == "openai/gpt-oss-20b"
    assert response.json()["video_model"] == "qwen/qwen3.8-27b"
    assert response.json()["multimodal_provider"] is True


def test_chunking_keeps_short_tail_without_duplicate_final_chunk():
    transcript = [
        {"text": "a" * 20, "start": 0.0, "duration": 1.0},
        {"text": "last segment", "start": 1.0, "duration": 1.0},
    ]
    chunks = transcript_service.TranscriptService.chunk_transcript(
        transcript, max_tokens=5, overlap_tokens=2
    )
    assert len(chunks) == 2
    assert "last segment" in chunks[-1]["text"]
    single = transcript_service.TranscriptService.chunk_transcript(
        transcript[:1], max_tokens=5, overlap_tokens=2
    )
    assert len(single) == 1
