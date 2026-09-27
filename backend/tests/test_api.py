from fastapi.testclient import TestClient
import asyncio
import json
import httpx
import pytest

from app.api import endpoints
from app.main import app
from app.models.schemas import VideoAnalysis
from app.services import llm_service, transcript_service
from app.services import openrouter_client


VIDEO_ID = "dQw4w9WgXcQ"
TRANSCRIPT = [
    {"text": "A useful explanation of solar power.", "start": 0.0, "duration": 5.0},
    {"text": "Solar panels turn sunlight into electricity.", "start": 5.0, "duration": 5.0},
]


def test_openrouter_embedded_error_is_not_reported_as_empty_completion(monkeypatch):
    monkeypatch.setattr(openrouter_client.settings, "OPENROUTER_API_KEY", "test-key")
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"error": {"code": 400, "message": '{"message":"Could not decode video"}'}}))
    monkeypatch.setattr(openrouter_client.httpx, "AsyncClient", lambda **_: real_client(transport=transport))
    with pytest.raises(openrouter_client.OpenRouterError, match="Could not decode video") as exc:
        asyncio.run(openrouter_client.OpenRouterClient().chat([{"role": "user", "content": "test"}]))
    assert exc.value.status_code == 400


def test_free_models_use_only_the_requested_provider(monkeypatch):
    monkeypatch.setattr(openrouter_client.settings, "OPENROUTER_API_KEY", "test-key")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(openrouter_client.httpx, "AsyncClient", lambda **_: real_client(transport=transport))
    client = openrouter_client.OpenRouterClient()
    for model in (*openrouter_client.FREE_MODEL_PROVIDERS, "google/gemma-4-31b-it"):
        asyncio.run(client.chat([{"role": "user", "content": "test"}], model=model))
    for request, provider in zip(requests[:2], openrouter_client.FREE_MODEL_PROVIDERS.values()):
        assert request["provider"] == {"only": [provider], "allow_fallbacks": False}
    assert "provider" not in requests[2]


class FakeLLM:
    async def generate_full_analysis(self, chunks):
        assert chunks[0]["text"]
        return VideoAnalysis(
            executive_summary="Solar power overview",
            detailed_summary="Solar panels make electricity.",
            key_points=[], chapters=[], topics=[],
        )

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
    assert transcript_service.TranscriptService.get_transcript_hash(result)
    assert transcript_service.TranscriptService.chunk_transcript(result)[0]["start_time"] == 0


def test_analyze_ask_and_cors(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")
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


def test_missing_transcript_is_client_error(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(endpoints.TranscriptService, "fetch_transcript", lambda *_: [])
    response = TestClient(app).post(
        "/api/videos/analyze", json={"url": f"https://www.youtube.com/watch?v={VIDEO_ID}"}
    )
    assert response.status_code == 400
    assert "transcript" in response.json()["detail"].lower()


def test_openrouter_completion_is_parsed():
    payload = json.dumps({
        "executive_summary": "Summary", "detailed_summary": "Details",
        "key_points": [], "chapters": [], "topics": [],
    })

    class Client:
        async def chat(self, messages, **kwargs):
            assert messages[0]["role"] == "system"
            return {"choices": [{"message": {"content": f"```json\n{payload}\n```"}}]}

    service = llm_service.LLMService(Client())
    analysis = asyncio.run(service.generate_full_analysis([
        {"start_time": 0.0, "end_time": 5.0, "text": "Transcript text"}
    ]))
    assert analysis.executive_summary == "Summary"


def test_text_analysis_falls_back_from_gemma_to_qwen(monkeypatch):
    calls = []

    class Client:
        async def chat(self, messages, **kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise llm_service.OpenRouterError(503, "Gemma provider unavailable")
            return {"choices": [{"message": {"content": json.dumps({
                "executive_summary": "Fallback summary",
                "detailed_summary": "Fallback details",
                "key_points": [], "chapters": [], "topics": [],
            })}}]}

    service = llm_service.LLMService(Client())
    analysis = asyncio.run(service.generate_full_analysis([
        {"start_time": 0.0, "end_time": 5.0, "text": "Transcript text"}
    ]))
    assert analysis.executive_summary == "Fallback summary"
    assert calls == [
        llm_service.settings.OPENROUTER_MODEL,
        llm_service.settings.OPENROUTER_FALLBACK_MODEL,
    ]


def test_deep_analysis_is_returned(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(endpoints, "LLMService", FakeLLM)

    class FakeMultimodal:
        async def analyze_video(self, url, transcript=None):
            assert url == f"https://www.youtube.com/watch?v={VIDEO_ID}"
            assert transcript == TRANSCRIPT
            return {"visual_summary": "A diagram appears.", "visual_events": [], "visual_gaps": []}

    monkeypatch.setattr(endpoints, "MultimodalService", FakeMultimodal)
    response = TestClient(app).post(
        "/api/videos/analyze",
        json={"url": VIDEO_ID, "mode": "deep", "transcript_data": TRANSCRIPT},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deep_analysis"]["visual_summary"] == "A diagram appears."


def test_deep_analysis_keeps_transcript_result_when_visual_provider_is_limited(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(endpoints, "LLMService", FakeLLM)

    class LimitedMultimodal:
        async def analyze_video(self, url, transcript=None):
            raise openrouter_client.OpenRouterError(429, "Qwen is temporarily rate-limited upstream")

    monkeypatch.setattr(endpoints, "MultimodalService", LimitedMultimodal)
    response = TestClient(app).post(
        "/api/videos/analyze",
        json={"url": VIDEO_ID, "mode": "deep", "transcript_data": TRANSCRIPT},
    )
    assert response.status_code == 200
    assert response.json()["executive_summary"] == "Solar power overview"
    assert "deep_analysis" not in response.json()
    assert "rate-limited" in response.json()["feature_warnings"][0]


def test_health_names_openrouter(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["llm_provider"] == "openrouter"
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
