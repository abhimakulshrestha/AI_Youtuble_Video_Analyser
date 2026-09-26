import { useEffect, useState } from 'react';
import { ExternalLink, Pause, Play, Plus, Trash2 } from 'lucide-react';
import { api, type ClaimCandidate, type ClaimCheckResult, type CompareResult, type StudySet, type TranscriptSegment, type VideoAnalysis, type WatchPlan } from './shared/api';
import { library, type SavedVideo } from './shared/library';

type Props = {
  tab: string;
  videoId: string;
  title: string;
  analysis: VideoAnalysis;
  transcript: TranscriptSegment[];
  playerTime: number;
  playerState: { currentTime: number; duration: number; paused: boolean } | null;
  savedVideos: SavedVideo[];
  refreshLibrary: () => void;
  onSeek: (time: number, play?: boolean) => void;
  onPause: () => void;
  onAskMoment: () => void;
};

function time(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function sourceButton(start: number, onSeek: Props['onSeek'], label?: string) {
  return <button className="timestamp" onClick={() => onSeek(start)}>{label || time(start)}</button>;
}

export function FeatureViews({ tab, videoId, analysis, transcript, playerTime, playerState, savedVideos, refreshLibrary, onSeek, onPause, onAskMoment }: Props) {
  const [goal, setGoal] = useState('Teach me the practical steps');
  const [minutes, setMinutes] = useState(8);
  const [plan, setPlan] = useState<WatchPlan | null>(null);
  const [clipIndex, setClipIndex] = useState<number | null>(null);
  const [study, setStudy] = useState<StudySet | null>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [flipped, setFlipped] = useState<Record<number, boolean>>({});
  const [claims, setClaims] = useState<ClaimCandidate[] | null>(null);
  const [checked, setChecked] = useState<Record<number, ClaimCheckResult>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [compareQuestion, setCompareQuestion] = useState('How do these explanations differ?');
  const [comparison, setComparison] = useState<CompareResult | null>(null);

  useEffect(() => {
    if (clipIndex === null || !plan || !playerState) return;
    const clip = plan.clips[clipIndex];
    if (!clip || playerState.currentTime < clip.end - 0.35) return;
    const next = clipIndex + 1;
    const timer = window.setTimeout(() => {
      if (next < plan.clips.length) {
        setClipIndex(next);
        onSeek(plan.clips[next].start, true);
      } else {
        setClipIndex(null);
        onPause();
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [clipIndex, plan, playerState, onSeek, onPause]);

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError('');
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(''); }
  }

  const currentChapter = analysis.chapters.find(ch => ch.start <= playerTime && playerTime < ch.end);
  const currentTopic = analysis.topics.find(topic => topic.timestamp_ranges.some(range => range.start <= playerTime && playerTime <= (range.end ?? range.start + 30)));
  const spoken = transcript.filter(item => Math.abs(item.start - playerTime) <= 8).map(item => item.text).join(' ');
  const definition = analysis.terminology.find(item => typeof item.term === 'string' && spoken.toLowerCase().includes(item.term.toLowerCase()));

  const timeline = [
    ...analysis.key_points.flatMap((point, index) => (point.evidence || []).map(evidence => ({ start: evidence.start, label: point.title, detail: evidence.text || '', type: 'Transcript', status: analysis.evidence_checks?.find(check => check.point_index === index && check.start === evidence.start)?.status || 'uncertain' }))),
    ...(analysis.deep_analysis?.visual_events || []).map(event => ({ start: event.start, label: event.kind, detail: event.description, type: 'Visual', status: 'observation' })),
    ...(analysis.deep_analysis?.visual_gaps || []).map(gap => ({ start: gap.start, label: 'Spoken-versus-shown', detail: gap.visual_detail, type: 'Visual gap', status: 'observation' })),
  ].sort((a, b) => a.start - b.start);

  async function addNote() {
    const existing = savedVideos.find(item => item.videoId === videoId);
    if (!existing || !note.trim()) return;
    await library.put({ ...existing, notes: [...existing.notes, { text: note.trim(), start: playerTime, createdAt: new Date().toISOString() }] });
    setNote('');
    refreshLibrary();
  }

  function openReference(reference: { video_id: string; start: number }) {
    if (reference.video_id === videoId) onSeek(reference.start);
    else chrome.tabs.create({ url: `https://www.youtube.com/watch?v=${reference.video_id}&t=${Math.floor(reference.start)}s` });
  }

  return <div className="feature-root" hidden={!['timeline', 'plan', 'live', 'claims', 'study', 'library', 'compare'].includes(tab)}>
    {error && <p className="feature-error" role="alert">{error}</p>}

    {tab === 'plan' && <section>
      <h3>Watch plan</h3>
      <label className="field-label">Your goal<input value={goal} onChange={event => setGoal(event.target.value)} maxLength={300} /></label>
      <label className="field-label">Minutes<input type="number" min={1} max={60} value={minutes} onChange={event => setMinutes(Number(event.target.value))} /></label>
      <button className="btn btn-primary" disabled={!!busy || !transcript.length || goal.trim().length < 3 || minutes < 1 || minutes > 60} onClick={() => void run('plan', async () => { setClipIndex(null); setPlan(await api.plan(videoId, goal, minutes, transcript, analysis)); })}>{busy === 'plan' ? 'Building...' : 'Build plan'}</button>
      {!transcript.length && <p>Transcript unavailable. Analyze this video again to build a plan.</p>}
      {plan && <>
        <div className="feature-row"><strong>{time(plan.total_seconds)} selected</strong><span>{plan.clips.length} moments</span></div>
        <div className="feature-row">
          <button className="btn btn-primary" onClick={() => { setClipIndex(0); onSeek(plan.clips[0].start, true); }}><Play size={15} /> Play plan</button>
          {clipIndex !== null && <button className="icon-button" title="Stop plan" aria-label="Stop plan" onClick={() => { setClipIndex(null); onPause(); }}><Pause size={18} /></button>}
        </div>
        {plan.clips.map((clip, index) => <article className={`feature-item ${clipIndex === index ? 'is-current' : ''}`} key={`${clip.start}-${index}`}>
          <div className="feature-row">{sourceButton(clip.start, onSeek, `${time(clip.start)}–${time(clip.end)}`)}<strong>{clip.title}</strong></div>
          <p>{clip.reason}</p>
        </article>)}
      </>}
    </section>}

    {tab === 'live' && <section>
      <div className="feature-row"><h3>Live companion</h3><span>{time(playerTime)} {playerState?.paused ? 'Paused' : 'Playing'}</span></div>
      <article className="feature-item"><span className="kicker">Current chapter</span><h4>{currentChapter?.title || 'No chapter at this moment'}</h4><p>{currentChapter?.summary || spoken || 'Play the video to follow its content.'}</p></article>
      {currentTopic && <article className="feature-item"><span className="kicker">Topic</span><h4>{currentTopic.name}</h4><p>{currentTopic.description}</p></article>}
      {definition && <article className="feature-item"><span className="kicker">Definition</span><h4>{definition.term}</h4><p>{definition.definition}</p></article>}
      {spoken && <article className="feature-item"><span className="kicker">Transcript nearby</span><p>{spoken}</p></article>}
      <button className="btn btn-primary" onClick={onAskMoment}>Ask about this moment</button>
    </section>}

    {tab === 'timeline' && <section>
      <h3>Evidence timeline</h3>
      {timeline.length === 0 && <p>No timestamped evidence is available.</p>}
      {timeline.map((event, index) => <article className="feature-item" key={`${event.type}-${event.start}-${index}`}>
        <div className="feature-row">{sourceButton(event.start, onSeek)}<span className="kicker">{event.type} · {event.status === 'matched' ? 'quote matched' : event.status}</span></div>
        <h4>{event.label}</h4><p>{event.detail}</p>
      </article>)}
      {analysis.deep_analysis?.visual_gaps && analysis.deep_analysis.visual_gaps.length > 0 && <><h3>What the speaker missed</h3>{analysis.deep_analysis.visual_gaps.map((gap, index) => <article className="feature-item" key={index}>{sourceButton(gap.start, onSeek)}<h4>{gap.visual_detail}</h4><p>Spoken: {gap.spoken_context}</p><p>{gap.why_it_matters}</p></article>)}</>}
      {!analysis.deep_analysis && <p>Run Analyze visuals to include slides, demonstrations, and information absent from the narration.</p>}
    </section>}

    {tab === 'claims' && <section>
      <h3>Claim checker</h3>
      <button className="btn btn-secondary" disabled={!!busy || !transcript.length} onClick={() => void run('claims', async () => setClaims(await api.claims(videoId, transcript, analysis)))}>{busy === 'claims' ? 'Finding...' : 'Find factual claims'}</button>
      {claims?.length === 0 && <p>No objectively checkable claims were found.</p>}
      {claims?.map((claim, index) => <article className="feature-item" key={index}>
        <div className="feature-row">{sourceButton(claim.start, onSeek)}<span className="kicker">{checked[index]?.verdict || 'unchecked'}</span></div>
        <p>{claim.text}</p>
        {!checked[index] && <button className="btn btn-secondary" disabled={!!busy} onClick={() => void run(`claim-${index}`, async () => { const result = await api.checkClaim(claim.text); setChecked(current => ({ ...current, [index]: result })); })}>{busy === `claim-${index}` ? 'Checking...' : 'Check with search'}</button>}
        {checked[index] && <><p>{checked[index].explanation}</p>{checked[index].sources.map(source => <a className="source-link" href={source.url} target="_blank" rel="noopener noreferrer" key={source.url}>{source.title} <ExternalLink size={13} /></a>)}</>}
      </article>)}
    </section>}

    {tab === 'study' && <section>
      <h3>Study mode</h3>
      <button className="btn btn-secondary" disabled={!!busy || !transcript.length} onClick={() => void run('study', async () => { setStudy(await api.study(videoId, transcript, analysis)); setAnswers({}); setFlipped({}); })}>{busy === 'study' ? 'Generating...' : 'Generate study set'}</button>
      {study?.questions.map((question, index) => <article className="feature-item" key={index}>
        <div className="feature-row"><span className="kicker">Question {index + 1}</span>{sourceButton(question.start, onSeek)}</div>
        <h4>{question.question}</h4>
        <div className="option-list">{question.options.map((option, optionIndex) => <button key={optionIndex} className={`option ${answers[index] === optionIndex ? 'selected' : ''}`} onClick={() => setAnswers(previous => ({ ...previous, [index]: optionIndex }))}>{option}</button>)}</div>
        {answers[index] !== undefined && <p className={answers[index] === question.answer_index ? 'correct' : 'incorrect'}>{answers[index] === question.answer_index ? 'Correct. ' : `Answer: ${question.options[question.answer_index]}. `}{question.explanation}</p>}
      </article>)}
      {study?.flashcards.length ? <h3>Flashcards</h3> : null}
      {study?.flashcards.map((card, index) => <article className="feature-item" key={index}><div className="feature-row"><span className="kicker">Card {index + 1}</span>{sourceButton(card.start, onSeek)}</div><h4>{card.front}</h4>{flipped[index] && <p>{card.back}</p>}<button className="btn btn-secondary" onClick={() => setFlipped(previous => ({ ...previous, [index]: !previous[index] }))}>{flipped[index] ? 'Hide answer' : 'Show answer'}</button></article>)}
    </section>}

    {tab === 'library' && <section>
      <h3>Knowledge library</h3>
      {savedVideos.length === 0 && <p>Save an analyzed video with the bookmark button to build your library.</p>}
      {savedVideos.map(video => <article className="feature-item" key={video.videoId}>
        <div className="feature-row"><strong>{video.title}</strong><button className="icon-button" title={`Remove ${video.title}`} aria-label={`Remove ${video.title}`} onClick={() => void run('remove', async () => { await library.remove(video.videoId); refreshLibrary(); })}><Trash2 size={16} /></button></div>
        <span className="kicker">{video.channel} · {video.notes.length} notes</span>
        <p>{video.analysis.executive_summary}</p>
        <a className="source-link" href={`https://www.youtube.com/watch?v=${video.videoId}`} target="_blank" rel="noopener noreferrer">Open video <ExternalLink size={13} /></a>
        {video.notes.map((entry, index) => <p key={index}>{video.videoId === videoId ? sourceButton(entry.start, onSeek) : <button className="timestamp" onClick={() => openReference({ video_id: video.videoId, start: entry.start })}>{time(entry.start)}</button>} {entry.text}</p>)}
      </article>)}
      {savedVideos.some(video => video.videoId === videoId) && <div className="feature-row"><input className="text-field" placeholder="Note about this moment" value={note} onChange={event => setNote(event.target.value)} /><button className="icon-button" title="Add timestamped note" aria-label="Add timestamped note" disabled={!note.trim()} onClick={() => void run('note', addNote)}><Plus size={18} /></button></div>}
    </section>}

    {tab === 'compare' && <section>
      <h3>Compare videos</h3>
      {savedVideos.length < 2 && <p>Save at least two analyzed videos to compare them.</p>}
      {savedVideos.map(video => <label className="video-choice" key={video.videoId}><input type="checkbox" checked={selected.includes(video.videoId)} disabled={!selected.includes(video.videoId) && selected.length >= 4} onChange={event => setSelected(current => event.target.checked ? [...current, video.videoId] : current.filter(id => id !== video.videoId))} />{video.title}</label>)}
      <label className="field-label">Comparison question<input value={compareQuestion} onChange={event => setCompareQuestion(event.target.value)} /></label>
      <button className="btn btn-primary" disabled={!!busy || selected.length < 2} onClick={() => void run('compare', async () => setComparison(await api.compare(savedVideos.filter(video => selected.includes(video.videoId)).map(video => ({ video_id: video.videoId, title: video.title, analysis: video.analysis, transcript_data: video.transcript })), compareQuestion)))}>{busy === 'compare' ? 'Comparing...' : 'Compare'}</button>
      {comparison && <><p>{comparison.summary}</p>{(['agreements', 'differences'] as const).map(group => <div key={group}><h4>{group === 'agreements' ? 'Agreements' : 'Differences'}</h4>{comparison[group].length === 0 && <p>None supported by the selected videos.</p>}{comparison[group].map((finding, index) => <article className="feature-item" key={index}><p>{finding.text}</p><div className="comparison-sources">{finding.references.map((reference, refIndex) => <div key={refIndex}><button className="timestamp" onClick={() => openReference(reference)}>{savedVideos.find(video => video.videoId === reference.video_id)?.title || reference.video_id} · {time(reference.start)}</button><span className="kicker">{reference.status}</span><p>{reference.excerpt}</p></div>)}</div></article>)}</div>)}</>}
    </section>}
  </div>;
}
