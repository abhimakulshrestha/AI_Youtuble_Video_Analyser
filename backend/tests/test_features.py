from fastapi.testclient import TestClient

from app.api import endpoints
from app.main import app
from app.models.schemas import VideoAnalysis, KeyPoint, TimestampEvidence
from app.services.evidence import check_analysis, check_excerpt
from app.services.multimodal_service import MultimodalService
from app.models.schemas import VideoFrame
import asyncio
from app.services.groq_client import GroqError


VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "qbjpa0NgmuI"
TRANSCRIPT = [
    {"text": "Solar panels turn sunlight into electricity.", "start": 5, "duration": 5},
    {"text": "The inverter changes direct current to alternating current.", "start": 10, "duration": 5},
]
FRAME = {"start": 5, "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlX8AAAAASUVORK5CYII="}
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

    async def analyze_frames(self, frames, transcript):
        assert frames[0].start == 5
        return {"visual_summary": "A solar diagram is shown.", "visual_events": [{"start": 5, "kind": "diagram", "description": "Panel wiring"}], "visual_gaps": []}


def test_evidence_grading():
    checks = check_analysis(ANALYSIS, TRANSCRIPT)
    assert checks[0].status == "matched"
    assert check_excerpt(5, "Panels are useful", TRANSCRIPT)[0] == "uncertain"
    assert check_excerpt(300, "Solar panels", TRANSCRIPT)[0] == "unsupported"


def test_feature_routes(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")
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

    visual = client.post(f"/api/videos/{VIDEO_A}/visual", json={"transcript_data": TRANSCRIPT, "frames": [FRAME]})
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
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")

    class QuotaMultimodal:
        async def analyze_frames(self, frames, transcript):
            raise GroqError(429, "Groq rate limit exceeded")

    monkeypatch.setattr(endpoints, "MultimodalService", QuotaMultimodal)
    monkeypatch.setattr(endpoints.TranscriptService, "fetch_transcript", lambda *_: TRANSCRIPT)
    response = TestClient(app).post(f"/api/videos/{VIDEO_A}/visual", json={"frames": [FRAME]})
    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()


def test_search_citations_determine_checked_status():
    class Client:
        async def chat(self, messages, **kwargs):
            assert kwargs["tools"][0]["type"] == "browser_search"
            return {"choices": [{"message": {
                "content": "**SUPPORTED**: confirmed by the source",
                "executed_tools": [{"search_results": {"results": [{"url": "https://example.org/solar", "title": "Solar source"}]}}],
            }}]}

    service = MultimodalService(Client())
    checked = asyncio.run(service.check_claim("Solar panels convert sunlight."))
    assert checked.verdict == "supported"
    assert checked.sources[0].title == "Solar source"

    class NoCitationClient:
        async def chat(self, messages, **kwargs):
            return {"choices": [{"message": {"content": "SUPPORTED", "executed_tools": []}}]}

    unchecked = asyncio.run(MultimodalService(NoCitationClient()).check_claim("Solar panels convert sunlight."))
    assert unchecked.verdict == "unchecked"


def test_video_analysis_uses_groq_images():
    class Client:
        async def chat(self, messages, **kwargs):
            content = messages[0]["content"]
            assert content[2] == {"type": "image_url", "image_url": {"url": FRAME["image"]}}
            assert kwargs["model"] == endpoints.settings.GROQ_VISION_MODEL
            assert kwargs["response_format"] == {"type": "json_object"}
            return {"choices": [{"message": {"content": '{"visual_summary":"Demo","visual_events":[{"start":5,"kind":"slide","description":"Solar diagram"}],"visual_gaps":[]}'}}]}

    result = asyncio.run(MultimodalService(Client()).analyze_frames([VideoFrame(**FRAME)], TRANSCRIPT))
    assert result["visual_summary"] == "Sampled 1 frames. Demo"
    assert result["visual_events"][0]["start"] == 5


def test_visual_route_rejects_missing_or_invalid_frames(monkeypatch):
    monkeypatch.setattr(endpoints.settings, "GROQ_API_KEY", "test-key")
    client = TestClient(app)
    assert client.post(f"/api/videos/{VIDEO_A}/visual", json={"transcript_data": TRANSCRIPT}).status_code == 422
    assert client.post(f"/api/videos/{VIDEO_A}/visual", json={"transcript_data": TRANSCRIPT, "frames": [{"start": 5, "image": "https://example.org/x.jpg"}]}).status_code == 422
    assert client.post(f"/api/videos/{VIDEO_A}/visual", json={"transcript_data": TRANSCRIPT, "frames": [FRAME] * 4}).status_code == 422
