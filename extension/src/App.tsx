import { useState, useEffect, useCallback } from 'react';
import { api, type VideoAnalysis, type TranscriptSegment } from './shared/api';
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
  const [transcriptData, setTranscriptData] = useState<any[] | undefined>();
  const [savedVideos, setSavedVideos] = useState<SavedVideo[]>([]);
  const [playerTime, setPlayerTime] = useState(0);
  const [focusTime, setFocusTime] = useState<number | undefined>();
  const [playerState, setPlayerState] = useState<{ currentTime: number; duration: number; paused: boolean } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('overview');

  const refreshLibrary = useCallback(() => { library.list().then(setSavedVideos).catch(err => setError(String(err))); }, []);

  const restoreSavedVideo = (videoId: string | null) => {
    if (!videoId) return;
    library.get(videoId).then(saved => {
      if (!saved) return;
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
            setVideoContext(response);
            setPlayerTime(response.currentTime || 0);
            setError(null);
            restoreSavedVideo(response.videoId);
          } else {
             // Not loaded yet or injected yet
             const videoId = activeTab.url ? new URLSearchParams(new URL(activeTab.url).search).get('v') : null;
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
        setVideoContext(null);
        setError("Please open a YouTube video to use the Analyzer.");
      }
    });
  };

  useEffect(() => {
    fetchContext();
    refreshLibrary();

    const listener = (message: any) => {
      if (message.type === 'VIDEO_CHANGED') {
        setAnalysis(null); // Reset analysis on new video
        setTranscriptData(undefined);
        fetchContext();
      }
    };
    
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
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

  const handleAnalyze = async (mode: 'quick' | 'deep') => {
    if (!videoContext?.url) return;
    setLoading(true);
    setError(null);
    try {
      if (mode === 'deep' && analysis && videoContext.videoId) {
        const deep_analysis = await api.visual(videoContext.videoId, transcriptData || analysis.transcript_data);
        setAnalysis({ ...analysis, deep_analysis });
        setActiveTab('timeline');
        return;
      }
      let transcript_data = videoContext.transcript_data;
      if (!transcript_data && videoContext.videoId) {
          transcript_data = await api.fetchTranscriptNatively(videoContext.videoId) || undefined;
      }
      const result = await api.analyzeVideo(videoContext.url, transcript_data, mode);
      setTranscriptData(result.transcript_data || transcript_data);
      setAnalysis(result);
      setActiveTab('summary');
    } catch (err: any) {
      setError(err.message || 'Failed to analyze video');
    } finally {
      setLoading(false);
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
        {analysis && videoContext?.videoId && (
          <div className="header-actions">
            {!analysis.deep_analysis && <button className="btn btn-secondary" disabled={loading} onClick={() => void handleAnalyze('deep')}>Analyze visuals</button>}
            <button className="icon-button" title="Save video to library" aria-label="Save video to library" onClick={() => void saveCurrent()}>
              {savedVideos.some(item => item.videoId === videoContext.videoId) ? <BookmarkCheck size={18} /> : <Bookmark size={18} />}
            </button>
          </div>
        )}
        
        {!analysis && !loading && (
          <div className="button-group">
            <button className="btn btn-primary" onClick={() => void handleAnalyze('quick')}>Quick Analyze</button>
            <button className="btn btn-secondary" onClick={() => void handleAnalyze('deep')}>Deep Analyze</button>
          </div>
        )}
      </div>

      {error && <div style={{padding: 16, color: 'var(--error-color)'}}>{error}</div>}

      {loading && (
        <div className="loader">
          Analyzing video... this may take a moment.
        </div>
      )}

      {analysis && !loading && (
        <>
          <div className="tabs">
            {['overview', 'summary', 'chapters', 'topics', 'timeline', 'plan', 'live', 'claims', 'study', 'library', 'compare', 'ask ai'].map(tab => (
              <button
                type="button"
                key={tab} 
                className={`tab ${activeTab === tab ? 'active' : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>

          <div className="content-area">
            {activeTab === 'overview' && (
              <div>
                {analysis.feature_warnings?.map((warning, index) => <p className="feature-error" key={index}>{warning}</p>)}
                <h3>Executive Summary</h3>
                <p>{analysis.executive_summary}</p>
                {analysis.content_type && <p><strong>Type:</strong> {analysis.content_type}</p>}
                
                <h3>Conclusions</h3>
                <ul>
                  {analysis.conclusions.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}

            {activeTab === 'summary' && (
              <div>
                <h3>Detailed Summary</h3>
                <ReactMarkdown>{analysis.detailed_summary}</ReactMarkdown>
                {analysis.deep_analysis?.visual_summary && (
                  <>
                    <h3>Visual Analysis</h3>
                    <ReactMarkdown>{analysis.deep_analysis.visual_summary}</ReactMarkdown>
                  </>
                )}
                
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

            {activeTab === 'chapters' && (
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
            
            {activeTab === 'topics' && (
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

            {activeTab === 'ask ai' && (
              videoContext?.videoId ? (
                <ChatInterface videoId={videoContext.videoId} transcriptData={transcriptData} onSeek={handleSeek} focusTime={focusTime} />
              ) : (
                <p>Video ID unavailable for this tab.</p>
              )
            )}
            {videoContext?.videoId && (
              <FeatureViews tab={activeTab} videoId={videoContext.videoId} title={videoContext.title} analysis={analysis} transcript={transcriptData || []} playerTime={playerTime} playerState={playerState} savedVideos={savedVideos} refreshLibrary={refreshLibrary} onSeek={handleSeek} onPause={pauseVideo} onAskMoment={() => { setFocusTime(playerTime); setActiveTab('ask ai'); }} />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ChatInterface({ videoId, transcriptData, onSeek, focusTime }: { videoId: string, transcriptData?: any[], onSeek: (time: number) => void, focusTime?: number }) {
  const [messages, setMessages] = useState<Array<{role: string, content: string, citations?: any[]}>>([]);
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
