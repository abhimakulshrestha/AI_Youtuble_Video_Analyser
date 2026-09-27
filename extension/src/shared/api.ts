const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api").replace(/\/$/, '');

export interface TimestampEvidence {
  start: number;
  end: number | null;
  text: string | null;
}

export interface KeyPoint {
  title: string;
  explanation: string;
  evidence: TimestampEvidence[];
}

export interface Chapter {
  title: string;
  start: number;
  end: number;
  summary: string;
  key_points: string[];
}

export interface Topic {
  name: string;
  description: string;
  importance?: string;
  timestamp_ranges: TimestampEvidence[];
}

export interface VideoAnalysis {
  executive_summary: string;
  detailed_summary: string;
  content_type: string | null;
  key_points: KeyPoint[];
  chapters: Chapter[];
  topics: Topic[];
  entities: any[];
  terminology: any[];
  statistics: any[];
  action_items: any[];
  conclusions: string[];
  deep_analysis?: { visual_summary: string; visual_events: VisualEvent[]; visual_gaps: VisualGap[] };
  evidence_checks?: EvidenceCheck[];
  transcript_data?: TranscriptSegment[];
  feature_warnings?: string[];
}

export interface VideoFrame { start: number; image: string }

export interface TranscriptSegment { text: string; start: number; duration: number }
export interface EvidenceCheck { point_index: number; start: number | null; status: 'matched' | 'uncertain' | 'unsupported'; transcript_excerpt: string }
export interface VisualEvent { start: number; kind: string; description: string }
export interface VisualGap { start: number; visual_detail: string; spoken_context: string; why_it_matters: string }
export interface DeepAnalysis { visual_summary: string; visual_events: VisualEvent[]; visual_gaps: VisualGap[] }
export interface PlanClip { title: string; reason: string; start: number; end: number }
export interface WatchPlan { goal: string; budget_seconds: number; total_seconds: number; clips: PlanClip[] }
export interface QuizQuestion { question: string; options: string[]; answer_index: number; explanation: string; start: number }
export interface StudySet { questions: QuizQuestion[]; flashcards: { front: string; back: string; start: number }[] }
export interface ClaimCandidate { text: string; start: number; status: 'unchecked' }
export interface ClaimCheckResult { claim: string; verdict: 'supported' | 'disputed' | 'unclear' | 'unchecked'; explanation: string; sources: { title: string; url: string }[] }
export interface CompareResult { summary: string; agreements: ComparisonFinding[]; differences: ComparisonFinding[] }
export interface ComparisonFinding { text: string; references: { video_id: string; start: number; excerpt: string; status: string }[] }

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP error ${res.status}`);
  }
  return res.json();
}

export interface Citation {
  start: number;
  end: number;
  label: string;
  excerpt: string;
  status: 'matched' | 'uncertain' | 'unsupported';
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
}

export const api = {
  async analyzeVideo(url: string, transcript_data?: any[], mode: "quick" | "deep" = "quick", frames?: VideoFrame[]): Promise<VideoAnalysis> {
    const res = await fetch(`${API_BASE}/videos/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, mode, language: "en", transcript_data, frames })
    });
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP error ${res.status}`);
    }
    
    return await res.json();
  },

  async askQuestion(videoId: string, question: string, transcriptData?: any[], contextHints?: string, focusTime?: number): Promise<ChatResponse> {
    const res = await fetch(`${API_BASE}/videos/${videoId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context_hints: contextHints, transcript_data: transcriptData, focus_time: focusTime })
    });
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP error ${res.status}`);
    }
    
    return await res.json();
  },
  
  async getTranscript(videoId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/videos/${videoId}/transcript`);
    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }
    const data = await res.json();
    return data.transcript;
  },
  plan(videoId: string, goal: string, minutes: number, transcript_data: TranscriptSegment[], analysis: VideoAnalysis) {
    return post<WatchPlan>(`/videos/${videoId}/plan`, { goal, minutes, transcript_data, analysis });
  },
  visual(videoId: string, transcript_data: TranscriptSegment[], frames: VideoFrame[]) {
    return post<DeepAnalysis>(`/videos/${videoId}/visual`, { transcript_data, frames });
  },
  study(videoId: string, transcript_data: TranscriptSegment[], analysis: VideoAnalysis) {
    return post<StudySet>(`/videos/${videoId}/study`, { transcript_data, analysis });
  },
  claims(videoId: string, transcript_data: TranscriptSegment[], analysis: VideoAnalysis) {
    return post<ClaimCandidate[]>(`/videos/${videoId}/claims`, { transcript_data, analysis });
  },
  checkClaim(claim: string) {
    return post<ClaimCheckResult>('/claims/check', { claim });
  },
  compare(videos: { video_id: string; title: string; analysis: VideoAnalysis; transcript_data: TranscriptSegment[] }[], question: string) {
    return post<CompareResult>('/videos/compare', { videos, question });
  },
};
