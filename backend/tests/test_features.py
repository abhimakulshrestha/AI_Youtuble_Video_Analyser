from fastapi.testclient import TestClient

from app.api import endpoints
from app.main import app
from app.models.schemas import VideoAnalysis, KeyPoint, TimestampEvidence
from app.services.evidence import check_analysis, check_excerpt
from app.services.multimodal_service import MultimodalService
import asyncio
from app.services.openrouter_client import OpenRouterError


VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "qbjpa0NgmuI"
TRANSCRIPT = [
    {"text": "Solar panels turn sunlight into electricity.", "start": 5, "duration": 5},
    {"text": "The inverter changes direct current to alternating current.", "start": 10, "duration": 5},
]
ANALYSIS = VideoAnalysis(
    executive_summary="Solar basics", detailed_summary="Solar panels and an inverter.",
    key_points=[KeyPoint(title="Panels", explanation="They generate power", evidence=[TimestampEvidence(start=5, end=10, text="Solar panels turn sunlight into electricity")])],
    chapters=[], topics=[],
)


class FakeLLM:
    async def generate_json(self, instruction, payload):
        if "watch plan" in instruction:
            return {"clips": [
                {"title": "Panels", "reason": "Basic mechanism", "start": 5, "end": 10},
                {"title": "Inverter", "reason": "Practical component", "start": 10, "end": 100},
            ]}
        if "study set" in instruction:
            return {"questions": [
                {"question": "What do panels do?", "options": ["Convert light", "Make fuel", "Store water", "None"], "answer_index": 0, "explanation": "They convert sunlight.", "start": 5},
                {"question": "Bad question", "options": ["A"], "answer_index": 4, "explanation": "Invalid", "start": 5},
            ], "flashcards": [{"front": "Inverter", "back": "Changes current", "start": 10}]}
        if "factual claims" in instruction:
            return {"claims": [{"text": "Solar panels turn sunlight into electricity.", "start": 5}]}
        if "Compare only" in instruction:
            return {"summary": "Same core idea", "agreements": [{"text": "Panels work with light", "references": [
                {"video_id": VIDEO_A, "start": 5, "excerpt": "Solar panels turn sunlight into electricity"},
                {"video_id": VIDEO_B, "start": 5, "excerpt": "Solar panels turn sunlight into electricity"},
            ]}], "differences": [{"text": "Unsubstantiated", "references": [{"video_id": VIDEO_A, "start": 5, "excerpt": ""}]}]}
        raise AssertionError(instruction)


class FakeMultimodal:
    async def check_claim(self, claim):
        return {"claim": claim, "verdict": "supported", "explanation": "The source confirms it.", "sources": [{"title": "Source", "url": "https://example.org/solar"}]}

    async def analyze_video(self, url, transcript=None):
        assert url == f"https://www.youtube.com/watch?v={VIDEO_A}"
        return {"visual_summary": "A solar diagram is shown.", "visual_events": [{"start": 5, "kind": "diagram", "description": "Panel wiring"}], "visual_gaps": []}


def test_evidence_grading():
    checks = check_analysis(ANALYSIS, TRANSCRIPT)
    assert checks[0].status == "matched"
    assert check_excerpt(5, "Panels are useful", TRANSCRIPT)[0] == "uncertain"
    assert check_excerpt(300, "Solar panels", TRANSCRIPT)[0] == "unsupported"


def test_feature_routes(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(endpoints, "LLMService", FakeLLM)
    monkeypatch.setattr(endpoints, "MultimodalService", FakeMultimodal)
    monkeypatch.setattr(endpoints.TranscriptService, "fetch_transcript", lambda *_: TRANSCRIPT)
    client = TestClient(app)
    common = {"transcript_data": TRANSCRIPT, "analysis": ANALYSIS.model_dump()}

    plan = client.post(f"/api/videos/{VIDEO_A}/plan", json={**common, "goal": "Learn solar", "minutes": 1})
    assert plan.status_code == 200, plan.text
    assert plan.json()["total_seconds"] == 10
    assert plan.json()["clips"][-1]["end"] == 15

    study = client.post(f"/api/videos/{VIDEO_A}/study", json=common)
    assert study.status_code == 200, study.text
    assert len(study.json()["questions"]) == 1
    assert study.json()["flashcards"][0]["start"] == 10

    claims = client.post(f"/api/videos/{VIDEO_A}/claims", json=common)
    assert claims.status_code == 200, claims.text
    assert claims.json()[0]["status"] == "unchecked"

    checked = client.post("/api/claims/check", json={"claim": claims.json()[0]["text"]})
    assert checked.status_code == 200, checked.text
    assert checked.json()["sources"][0]["url"] == "https://example.org/solar"

    visual = client.post(f"/api/videos/{VIDEO_A}/visual", json={"transcript_data": TRANSCRIPT})
    assert visual.status_code == 200, visual.text
    assert visual.json()["visual_events"][0]["kind"] == "diagram"

    videos = [{"video_id": video_id, "title": video_id, "analysis": ANALYSIS.model_dump(), "transcript_data": TRANSCRIPT} for video_id in [VIDEO_A, VIDEO_B]]
    comparison = client.post("/api/videos/compare", json={"videos": videos})
    assert comparison.status_code == 200, comparison.text
    assert len(comparison.json()["agreements"]) == 1
    assert comparison.json()["agreements"][0]["references"][0]["status"] == "matched"
    assert comparison.json()["differences"] == []

    duplicate = client.post("/api/videos/compare", json={"videos": [videos[0], videos[0]]})
    assert duplicate.status_code == 400


def test_quota_error_has_actionable_status(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_API_KEY", "test-key")

    class QuotaMultimodal:
        async def analyze_video(self, url, transcript=None):
            raise OpenRouterError(429, "OpenRouter request failed: rate limit exceeded")

    monkeypatch.setattr(endpoints, "MultimodalService", QuotaMultimodal)
    monkeypatch.setattr(endpoints.TranscriptService, "fetch_transcript", lambda *_: TRANSCRIPT)
    response = TestClient(app).post(f"/api/videos/{VIDEO_A}/visual", json={})
    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()


def test_search_citations_determine_checked_status():
    class Client:
        async def chat(self, messages, **kwargs):
            assert kwargs["tools"][0]["type"] == "openrouter:web_search"
            return {"choices": [{"message": {
                "content": "SUPPORTED: confirmed by the source",
                "annotations": [{"type": "url_citation", "url_citation": {"url": "https://example.org/solar", "title": "Solar source"}}],
            }}]}

    service = MultimodalService(Client())
    checked = asyncio.run(service.check_claim("Solar panels convert sunlight."))
    assert checked.verdict == "supported"
    assert checked.sources[0].title == "Solar source"

    class NoCitationClient:
        async def chat(self, messages, **kwargs):
            return {"choices": [{"message": {"content": "SUPPORTED", "annotations": []}}]}

    unchecked = asyncio.run(MultimodalService(NoCitationClient()).check_claim("Solar panels convert sunlight."))
    assert unchecked.verdict == "unchecked"


def test_video_analysis_uses_openrouter_video_content(monkeypatch):
    class Client:
        async def chat(self, messages, **kwargs):
            content = messages[0]["content"]
            assert content[1] == {"type": "video_url", "video_url": {"url": "https://media.example/video.mp4"}}
            assert kwargs["model"] == endpoints.settings.OPENROUTER_VIDEO_MODEL
            assert kwargs["response_format"] == {"type": "json_object"}
            return {"choices": [{"message": {"content": '{"visual_summary":"Demo","visual_events":[],"visual_gaps":[]}'}}]}

    monkeypatch.setattr(MultimodalService, "_resolve_video_url", staticmethod(lambda _: "https://media.example/video.mp4"))
    result = asyncio.run(MultimodalService(Client()).analyze_video(f"https://www.youtube.com/watch?v={VIDEO_A}", TRANSCRIPT))
    assert result["visual_summary"] == "Demo"


def test_video_analysis_uses_configured_fallback(monkeypatch):
    calls = []

    class Client:
        async def chat(self, messages, **kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise OpenRouterError(429, "Qwen provider is rate limited")
            return {"choices": [{"message": {"content": '{"visual_summary":"Fallback","visual_events":[],"visual_gaps":[]}'}}]}

    monkeypatch.setattr(MultimodalService, "_resolve_video_url", staticmethod(lambda _: "https://media.example/video.mp4"))
    monkeypatch.setattr(endpoints.settings, "OPENROUTER_VIDEO_FALLBACK_MODEL", "google/gemma-4-31b-it:free")
    result = asyncio.run(MultimodalService(Client()).analyze_video(f"https://www.youtube.com/watch?v={VIDEO_A}", TRANSCRIPT))
    assert result["visual_summary"] == "Fallback"
    assert calls == [
        endpoints.settings.OPENROUTER_VIDEO_MODEL,
        "google/gemma-4-31b-it:free",
    ]
