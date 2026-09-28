import { useState, useEffect, useCallback, useRef } from 'react';
import { api, type Citation, type VideoAnalysis, type TranscriptSegment, type VideoFrame } from './shared/api';
import { library, type SavedVideo } from './shared/library';
import { FeatureViews } from './FeatureViews';
import { Bookmark, BookmarkCheck } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

interface VideoContext {
  url: string;
  title: string;
  channel: string;
  currentTime: number;
  duration: number;
  videoId: string | null;
  transcript_data?: TranscriptSegment[];
}

const modeTabs = { quick: 'overview', deep: 'summary', visual: 'visual' } as const;

function formatTime(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function App() {
  const [videoContext, setVideoContext] = useState<VideoContext | null>(null);
  const [analysis, setAnalysis] = useState<VideoAnalysis | null>(null);
  const [transcriptData, setTranscriptData] = useState<TranscriptSegment[] | undefined>();
  const [savedVideos, setSavedVideos] = useState<SavedVideo[]>([]);
  const [playerTime, setPlayerTime] = useState(0);
  const [focusTime, setFocusTime] = useState<number | undefined>();
  const [playerState, setPlayerState] = useState<{ currentTime: number; duration: number; paused: boolean } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('overview');
  const activeVideoId = useRef<string | null>(null);
  const viewAnalysis = analysis || savedVideos[0]?.analysis;
  const visibleTab = !analysis && !['library', 'compare'].includes(activeTab) ? 'library' : activeTab;

  const refreshLibrary = useCallback(() => { library.list().then(setSavedVideos).catch(err => setError(String(err))); }, []);

  const restoreSavedVideo = (videoId: string | null) => {
    if (!videoId) return;
    library.get(videoId).then(saved => {
      if (!saved || activeVideoId.current !== videoId) return;
      setAnalysis(saved.analysis);
      setTranscriptData(saved.transcript);
    }).catch(err => setError(String(err)));
  };

  const fetchContext = () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs: chrome.tabs.Tab[]) => {
      const activeTab = tabs[0];
      if (activeTab && activeTab.id && activeTab.url?.includes('youtube.com/watch')) {
        chrome.tabs.sendMessage(activeTab.id, { type: 'GET_VIDEO_CONTEXT' }, (response: any) => {
          if (response) {
            if (activeVideoId.current !== response.videoId) {
              setAnalysis(null);
              setTranscriptData(undefined);
              setLoading(false);
              setActiveTab('overview');
            }
            activeVideoId.current = response.videoId;
            setVideoContext(response);
            setPlayerTime(response.currentTime || 0);
            setError(null);
            restoreSavedVideo(response.videoId);
          } else {
             // Not loaded yet or injected yet
             const videoId = activeTab.url ? new URLSearchParams(new URL(activeTab.url).search).get('v') : null;
             if (activeVideoId.current !== videoId) {
               setAnalysis(null);
               setTranscriptData(undefined);
               setLoading(false);
               setActiveTab('overview');
             }
             activeVideoId.current = videoId;
             setVideoContext({
                 url: activeTab.url || '',
                 title: activeTab.title || 'YouTube Video',
                 channel: '',
                 currentTime: 0,
                 duration: 0,
                 videoId
             });
             restoreSavedVideo(videoId);
          }
        });
      } else {
        activeVideoId.current = null;
        setVideoContext(null);
        setAnalysis(null);
        setTranscriptData(undefined);
        setLoading(false);
        setActiveTab('overview');
        setError("Please open a YouTube video to use the Analyzer.");
      }
    });
  };

  useEffect(() => {
    fetchContext();
    refreshLibrary();

    const listener = (message: any) => {
      if (message.type === 'VIDEO_CHANGED') {
        activeVideoId.current = null;
        setAnalysis(null); // Reset analysis on new video
        setTranscriptData(undefined);
        setLoading(false);
        setActiveTab('overview');
        fetchContext();
      }
    };
    
    chrome.runtime.onMessage.addListener(listener);
    chrome.tabs.onActivated.addListener(fetchContext);
    return () => {
      chrome.runtime.onMessage.removeListener(listener);
      chrome.tabs.onActivated.removeListener(fetchContext);
    };
  }, [refreshLibrary]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
        if (!tabs[0]?.id || !tabs[0].url?.includes('youtube.com/watch')) return;
        chrome.tabs.sendMessage(tabs[0].id, { type: 'GET_PLAYER_STATE' }, response => {
          if (!chrome.runtime.lastError && response?.videoId === videoContext?.videoId) {
            setPlayerTime(response.currentTime);
            setPlayerState(response);
          }
        });
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [videoContext?.videoId]);

  const handleAnalyze = async (mode: 'quick' | 'deep' | 'visual') => {
    if (!videoContext?.url) return;
    const targetTab = modeTabs[mode];
    if (analysis && (mode !== 'visual' || analysis.deep_analysis)) {
      setActiveTab(targetTab);
      return;
    }
    const videoId = videoContext.videoId;
    setLoading(true);
    setError(null);
    try {
      let transcript_data = videoContext.transcript_data;
      if (!transcript_data && videoId) {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs[0]?.id) {
          const fresh = await chrome.tabs.sendMessage(tabs[0].id, { type: 'GET_VIDEO_CONTEXT' }).catch(() => null);
          if (fresh?.videoId === videoId) transcript_data = fresh.transcript_data;
        }
      }
      const captureVisualFrames = async (): Promise<VideoFrame[]> => {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        const tabId = tabs[0]?.id;
        const duration = playerState?.duration || videoContext.duration || 0;
        if (!tabId || !Number.isFinite(duration) || duration <= 0) throw new Error('The player is not ready for visual analysis.');
        const times = Array.from(new Set(Array.from({ length: 3 }, (_, index) => Math.round(duration * (index + 0.5) / 3 * 10) / 10)));
        const originalTime = playerState?.currentTime ?? videoContext.currentTime;
        const wasPaused = playerState?.paused ?? true;
        const frames: VideoFrame[] = [];
        let lastCapture = 0;
        try {
          for (const time of times) {
            const frame = await chrome.tabs.sendMessage(tabId, { type: 'CAPTURE_FRAME', videoId, time });
            if (frame?.error || !frame?.rect?.width || !frame?.rect?.height) throw new Error(frame?.error || 'The video is outside the visible tab.');
            await new Promise(resolve => setTimeout(resolve, Math.max(0, 550 - (Date.now() - lastCapture))));
            const screenshot = await chrome.tabs.captureVisibleTab(tabs[0].windowId, { format: 'jpeg', quality: 70 }).catch(error => {
              if (String(error).includes("'activeTab' permission is required")) {
                throw new Error('Click the analyzer extension icon on this YouTube tab, then retry Analyze visuals.');
              }
              throw error;
            });
            lastCapture = Date.now();
            const image = new Image();
            image.src = screenshot;
            await image.decode();
            const scaleX = image.naturalWidth / frame.viewport.width;
            const scaleY = image.naturalHeight / frame.viewport.height;
            const x = Math.max(0, frame.rect.x * scaleX);
            const y = Math.max(0, frame.rect.y * scaleY);
            const width = Math.min(frame.rect.width * scaleX, image.naturalWidth - x);
            const height = Math.min(frame.rect.height * scaleY, image.naturalHeight - y);
            if (width <= 0 || height <= 0) throw new Error('The video is outside the visible tab.');
            const canvas = document.createElement('canvas');
            canvas.width = Math.min(960, Math.round(width));
            canvas.height = Math.round(canvas.width * height / width);
            const context = canvas.getContext('2d');
            if (!context) throw new Error('Unable to prepare a video frame.');
            context.drawImage(image, x, y, width, height, 0, 0, canvas.width, canvas.height);
            let encoded = canvas.toDataURL('image/jpeg', 0.7);
            if (encoded.length > 330_000) encoded = canvas.toDataURL('image/jpeg', 0.45);
            if (encoded.length > 330_000) {
              canvas.width = Math.min(720, Math.round(width));
              canvas.height = Math.round(canvas.width * height / width);
              context.drawImage(image, x, y, width, height, 0, 0, canvas.width, canvas.height);
              encoded = canvas.toDataURL('image/jpeg', 0.45);
            }
            if (encoded.length > 330_000) throw new Error('A video frame exceeds the upload limit.');
            frames.push({ start: frame.start, image: encoded });
          }
        } finally {
          await chrome.tabs.sendMessage(tabId, { type: 'SEEK_TO', time: originalTime, play: !wasPaused }).catch(() => {});
        }
        return frames;
      };
      const result = analysis || await api.analyzeVideo(videoContext.url, transcript_data);
      if (activeVideoId.current !== videoId) return;
      if (!analysis) {
        setTranscriptData(result.transcript_data || transcript_data);
        setAnalysis(result);
        setActiveTab(mode === 'visual' ? 'overview' : targetTab);
      }
      if (mode === 'visual') {
        if (!videoId) throw new Error('Video ID unavailable for visual analysis.');
        const frames = await captureVisualFrames();
        const deep_analysis = await api.visual(videoId, transcriptData || result.transcript_data || transcript_data || [], frames);
        if (activeVideoId.current !== videoId) return;
        setAnalysis({ ...result, deep_analysis });
      }
      setActiveTab(targetTab);
    } catch (err: any) {
      if (activeVideoId.current === videoId) setError(err.message || 'Failed to analyze video');
    } finally {
      if (activeVideoId.current === videoId) setLoading(false);
    }
  };

  const handleSeek = (time: number, play = false) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs: chrome.tabs.Tab[]) => {
      if (tabs[0]?.id) {
        chrome.tabs.sendMessage(tabs[0].id, { type: 'SEEK_TO', time, play });
      }
    });
  };

  const pauseVideo = () => chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    if (tabs[0]?.id) chrome.tabs.sendMessage(tabs[0].id, { type: 'PAUSE_VIDEO' });
  });

  const saveCurrent = async () => {
    if (!analysis || !videoContext?.videoId) return;
    const previous = savedVideos.find(item => item.videoId === videoContext.videoId);
    await library.put({ videoId: videoContext.videoId, title: videoContext.title, channel: videoContext.channel, analysis, transcript: transcriptData || analysis.transcript_data || [], notes: previous?.notes || [], savedAt: new Date().toISOString() });
    refreshLibrary();
  };

  if (!videoContext && !error) {
    return <div className="loader">Detecting YouTube video...</div>;
  }

  if (error && !videoContext) {
    return <div className="loader">{error}</div>;
  }

  return (
    <div className="app-container">
      <div className="header">
        <div className="video-info">
          <div className="video-title">{videoContext?.title}</div>
          <div className="video-channel">{videoContext?.channel}</div>
        </div>
        <div className="analysis-controls">
          <div className="analysis-modes" role="group" aria-label="Analysis views">
            {(['quick', 'deep', 'visual'] as const).map(mode => (
              <button
                key={mode}
                type="button"
                className={`analysis-mode ${analysis && activeTab === modeTabs[mode] ? 'active' : ''}`}
                aria-pressed={!!analysis && activeTab === modeTabs[mode]}
                disabled={loading}
                onClick={() => void handleAnalyze(mode)}
              >
                {mode.charAt(0).toUpperCase() + mode.slice(1)}
              </button>
            ))}
          </div>
          {analysis && videoContext?.videoId && (
            <button className="icon-button" title="Save video to library" aria-label="Save video to library" onClick={() => void saveCurrent()}>
              {savedVideos.some(item => item.videoId === videoContext.videoId) ? <BookmarkCheck size={18} /> : <Bookmark size={18} />}
            </button>
          )}
        </div>
      </div>

      {error && <div style={{padding: 16, color: 'var(--error-color)'}}>{error}</div>}

      {loading && (
        <div className="loader">
          Analyzing video... this may take a moment.
        </div>
      )}

      {viewAnalysis && !loading && (
        <>
          <div className="tabs">
            {(analysis ? ['chapters', 'topics', 'timeline', 'plan', 'live', 'claims', 'study', 'library', 'compare', 'ask ai'] : ['library', 'compare']).map(tab => (
              <button
                type="button"
                key={tab} 
                className={`tab ${visibleTab === tab ? 'active' : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>

          <div className="content-area">
            {analysis && visibleTab === 'overview' && (
              <div>
                {analysis.feature_warnings?.map((warning, index) => <p className={warning.startsWith('Long video:') ? 'coverage-notice' : 'feature-error'} key={index}>{warning}</p>)}
                <h3>Executive Summary</h3>
                <p>{analysis.executive_summary}</p>
                {analysis.content_type && <p><strong>Type:</strong> {analysis.content_type}</p>}
                
                <h3>Conclusions</h3>
                <ul>
                  {analysis.conclusions.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}

            {analysis && visibleTab === 'summary' && (
              <div>
                {analysis.feature_warnings?.map((warning, index) => <p className={warning.startsWith('Long video:') ? 'coverage-notice' : 'feature-error'} key={index}>{warning}</p>)}
                <h3>Detailed Summary</h3>
                <ReactMarkdown>{analysis.detailed_summary}</ReactMarkdown>
                
                <h3>Key Points</h3>
                {analysis.key_points.map((kp, i) => (
                  <div key={i} className="card">
                    <h4>{kp.title}</h4>
                    <p>{kp.explanation}</p>
                    <div>
                      {kp.evidence.map((ev, j) => {
                        const status = analysis.evidence_checks?.find(check => check.point_index === i && check.start === ev.start)?.status || 'uncertain';
                        return <button key={j} className="timestamp" onClick={() => handleSeek(ev.start)} title={ev.text || ''}>
                          {formatTime(ev.start)} · {status === 'matched' ? 'quote matched' : status}
                        </button>;
                      })}
                      {kp.evidence.length === 0 && <span className="kicker">No timestamped evidence</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {analysis && visibleTab === 'visual' && (
              <div>
                <h3>Visual Analysis</h3>
                {analysis.deep_analysis ? (
                  <>
                    <ReactMarkdown>{analysis.deep_analysis.visual_summary}</ReactMarkdown>
                    <h3>Visual Moments</h3>
                    {analysis.deep_analysis.visual_events.map((event, index) => (
                      <article className="feature-item" key={index}>
                        <button className="timestamp" onClick={() => handleSeek(event.start)}>{formatTime(event.start)}</button>
                        <h4>{event.kind}</h4>
                        <p>{event.description}</p>
                      </article>
                    ))}
                    <h3>What the speaker missed</h3>
                    {analysis.deep_analysis.visual_gaps.map((gap, index) => (
                      <article className="feature-item" key={index}>
                        <button className="timestamp" onClick={() => handleSeek(gap.start)}>{formatTime(gap.start)}</button>
                        <h4>{gap.visual_detail}</h4>
                        <p>Spoken: {gap.spoken_context}</p>
                        <p>{gap.why_it_matters}</p>
                      </article>
                    ))}
                  </>
                ) : <p>Select Visual to analyze the video frames.</p>}
              </div>
            )}

            {analysis && visibleTab === 'chapters' && (
              <div>
                {analysis.chapters.map((ch, i) => (
                  <div key={i} className="card">
                    <h4 style={{display: 'flex', alignItems: 'center', gap: 8}}>
                       <span className="timestamp" onClick={() => handleSeek(ch.start)}>{formatTime(ch.start)}</span>
                       {ch.title}
                    </h4>
                    <p>{ch.summary}</p>
                  </div>
                ))}
              </div>
            )}
            
            {analysis && visibleTab === 'topics' && (
              <div>
                {analysis.topics.map((t, i) => (
                  <div key={i} className="card">
                    <h4>{t.name} {t.importance ? `(${t.importance})` : ''}</h4>
                    <p>{t.description}</p>
                    <div>
                      {t.timestamp_ranges.map((tr, j) => (
                        <span key={j} className="timestamp" onClick={() => handleSeek(tr.start)}>
                          {formatTime(tr.start)}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {analysis && visibleTab === 'ask ai' && (
              videoContext?.videoId ? (
                <ChatInterface videoId={videoContext.videoId} transcriptData={transcriptData} onSeek={handleSeek} focusTime={focusTime} />
              ) : (
                <p>Video ID unavailable for this tab.</p>
              )
            )}
            {videoContext?.videoId && (
              <FeatureViews key={videoContext.videoId} tab={visibleTab} videoId={videoContext.videoId} title={videoContext.title} analysis={viewAnalysis} transcript={transcriptData || []} playerTime={playerTime} playerState={playerState} savedVideos={savedVideos} refreshLibrary={refreshLibrary} onSeek={handleSeek} onPause={pauseVideo} onAskMoment={() => { setFocusTime(playerTime); setActiveTab('ask ai'); }} />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ChatInterface({ videoId, transcriptData, onSeek, focusTime }: { videoId: string, transcriptData?: TranscriptSegment[], onSeek: (time: number) => void, focusTime?: number }) {
  const [messages, setMessages] = useState<Array<{role: string, content: string, citations?: Citation[]}>>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setLoading(true);
    
    try {
      const res = await api.askQuestion(videoId, userMsg, transcriptData, undefined, focusTime);
      setMessages(prev => [...prev, { role: 'assistant', content: res.answer, citations: res.citations }]);
    } catch (err: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.length === 0 && <p style={{color: '#666', textAlign: 'center'}}>{focusTime === undefined ? 'Ask a question about the video...' : `Ask about ${formatTime(focusTime)} or another moment.`}</p>}
        {messages.map((m, i) => (
          <div key={i} className={`chat-message chat-${m.role}`}>
            <ReactMarkdown>{m.content}</ReactMarkdown>
            {m.citations && m.citations.length > 0 && (
              <div style={{marginTop: 8}}>
                <strong>Sources:</strong>
                {m.citations.map((c, j) => (
                  <button key={j} className="timestamp" onClick={() => onSeek(c.start)} title={c.excerpt}>
                    {c.label || formatTime(c.start)} · {c.status}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && <div className="chat-message chat-assistant">Thinking...</div>}
      </div>
      <div className="chat-input-area">
        <input 
          type="text" 
          className="chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Ask AI..."
          disabled={loading}
        />
        <button className="btn btn-primary" onClick={handleSend} disabled={loading}>Send</button>
      </div>
    </div>
  );
}
