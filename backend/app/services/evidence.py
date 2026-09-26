import re

from app.models.features import EvidenceCheck
from app.models.schemas import VideoAnalysis


def video_end(transcript: list[dict]) -> float:
    return max((float(item.get("start", 0)) + float(item.get("duration", 0)) for item in transcript), default=0.0)


def check_excerpt(start: float, excerpt: str, transcript: list[dict]) -> tuple[str, str]:
    nearby = [item for item in transcript if abs(float(item.get("start", 0)) - start) <= 12]
    if not nearby:
        return "unsupported", ""
    spoken = " ".join(str(item.get("text", "")) for item in nearby).strip()
    normalized = lambda value: " ".join(re.findall(r"[a-z0-9]+", value.lower()))
    quote = normalized(excerpt)
    if len(quote) >= 12 and quote in normalized(spoken):
        return "matched", spoken[:320]
    return "uncertain", spoken[:320]


def check_analysis(analysis: VideoAnalysis, transcript: list[dict]) -> list[EvidenceCheck]:
    checks = []
    for index, point in enumerate(analysis.key_points):
        if not point.evidence:
            checks.append(EvidenceCheck(point_index=index, status="unsupported"))
            continue
        for evidence in point.evidence:
            status, spoken = check_excerpt(evidence.start, evidence.text or "", transcript)
            checks.append(EvidenceCheck(point_index=index, start=evidence.start, status=status, transcript_excerpt=spoken))
    return checks


def bound_start(start: float, transcript: list[dict]) -> float:
    return min(max(0.0, start), video_end(transcript))
