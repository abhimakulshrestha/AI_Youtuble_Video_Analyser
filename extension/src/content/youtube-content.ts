function getVideoElement(): HTMLVideoElement | null {
  return document.querySelector('video.html5-main-video') || document.querySelector('video');
}

function extractVideoContext() {
  const video = getVideoElement();
  
  // Try to find the title
  let title = document.title;
  const titleEl = document.querySelector('h1.ytd-watch-metadata yt-formatted-string') || document.querySelector('h1.title');
  if (titleEl) {
    title = titleEl.textContent || title;
  }
  
  // Try to find channel name
  let channel = "";
  const channelEl = document.querySelector('ytd-channel-name yt-formatted-string a');
  if (channelEl) {
    channel = channelEl.textContent || "";
  }
  
  return {
    url: window.location.href,
    title: title.replace(/^\(\d+\)\s*/, ''), // Remove notification count
    channel,
    currentTime: video ? video.currentTime : 0,
    duration: video ? video.duration : 0,
    videoId: new URLSearchParams(window.location.search).get('v')
  };
}

function extractJsonObject(source: string, markerIndex: number): string | null {
  const jsonStart = source.indexOf('{', markerIndex);
  if (jsonStart === -1) return null;

  let depth = 0;
  let inString = false;
  let escapeNext = false;

  for (let i = jsonStart; i < source.length; i++) {
    const char = source[i];
    if (escapeNext) {
      escapeNext = false;
      continue;
    }
    if (char === '\\') {
      escapeNext = true;
      continue;
    }
    if (char === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;

    if (char === '{') depth++;
    if (char === '}') depth--;
    if (depth === 0) return source.slice(jsonStart, i + 1);
  }

  return null;
}

function extractPlayerResponseFromText(source: string): any | null {
  const markers = [
    'ytInitialPlayerResponse =',
    'ytInitialPlayerResponse=',
    'var ytInitialPlayerResponse =',
    'window["ytInitialPlayerResponse"] =',
    '"ytInitialPlayerResponse":',
  ];

  for (const marker of markers) {
    let searchFrom = 0;
    while (searchFrom < source.length) {
      const markerIndex = source.indexOf(marker, searchFrom);
      if (markerIndex === -1) break;
      const jsonObject = extractJsonObject(source, markerIndex + marker.length);
      if (jsonObject) {
        try {
          return JSON.parse(jsonObject);
        } catch {
          // Keep searching; YouTube can include similarly named fields elsewhere.
        }
      }
      searchFrom = markerIndex + marker.length;
    }
  }

  return null;
}

function extractPlayerResponseFromDOM(): any | null {
  const windowPlayerResponse = (window as any).ytInitialPlayerResponse;
  if (windowPlayerResponse) return windowPlayerResponse;

  const scripts = Array.from(document.scripts);
  for (let i = scripts.length - 1; i >= 0; i--) {
    const text = scripts[i].textContent;
    if (!text || !text.includes('ytInitialPlayerResponse')) continue;

    const playerResponse = extractPlayerResponseFromText(text);
    if (playerResponse) return playerResponse;
  }

  return null;
}

function parseTranscriptJson(payload: string): any[] | null {
  try {
    const json = JSON.parse(payload.replace(/^\)\]\}'\s*/, ''));
    const transcriptData = [];

    for (const event of (json.events || [])) {
      if (!event.segs) continue;
      const text = event.segs.map((segment: any) => segment.utf8 || '').join('').trim();
      if (!text) continue;

      transcriptData.push({
        text,
        start: (event.tStartMs || 0) / 1000.0,
        duration: (event.dDurationMs || 0) / 1000.0,
      });
    }

    return transcriptData.length > 0 ? transcriptData : null;
  } catch {
    return null;
  }
}

function parseTranscriptXml(payload: string): any[] | null {
  const doc = new DOMParser().parseFromString(payload, 'text/xml');
  if (doc.querySelector('parsererror')) return null;

  const transcriptData = Array.from(doc.querySelectorAll('text'))
    .map((node) => ({
      text: (node.textContent || '').trim(),
      start: Number(node.getAttribute('start') || 0),
      duration: Number(node.getAttribute('dur') || 0),
    }))
    .filter((segment) => segment.text);

  return transcriptData.length > 0 ? transcriptData : null;
}

async function fetchTranscriptFromDOM(): Promise<any[] | null> {
  try {
    const data = extractPlayerResponseFromDOM();
    const currentVideoId = new URLSearchParams(window.location.search).get('v');
    if (data?.videoDetails?.videoId && data.videoDetails.videoId !== currentVideoId) return null;
    const tracks = data?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (!tracks || tracks.length === 0) return null;

    const track = tracks.find((item: any) => item.languageCode === 'en')
      || tracks.find((item: any) => item.languageCode?.startsWith('en'))
      || tracks[0];
    if (!track?.baseUrl) return null;

    const separator = track.baseUrl.includes('?') ? '&' : '?';
    const res = await fetch(`${track.baseUrl}${separator}fmt=json3`, { credentials: 'include' });
    if (!res.ok) return null;

    const payload = await res.text();
    return parseTranscriptJson(payload) || parseTranscriptXml(payload);
  } catch {
    return null;
  }
}

async function seekFrame(video: HTMLVideoElement, time: number): Promise<void> {
  if (Math.abs(video.currentTime - time) < 0.15) return;
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => { video.removeEventListener('seeked', done); reject(new Error('Timed out seeking the video.')); }, 6000);
    const done = () => { window.clearTimeout(timer); resolve(); };
    video.addEventListener('seeked', done, { once: true });
    video.currentTime = time;
  });
  await new Promise<void>(resolve => {
    const timer = window.setTimeout(resolve, 700);
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(() => { window.clearTimeout(timer); resolve(); });
  });
}

chrome.runtime.onMessage.addListener((message: any, _sender: chrome.runtime.MessageSender, sendResponse: (response?: any) => void) => {
  if (message.type === 'GET_VIDEO_CONTEXT') {
    (async () => {
       const context = extractVideoContext();
       const transcript = await fetchTranscriptFromDOM();
       sendResponse({ ...context, transcript_data: transcript });
    })();
    return true;
  }
  
  if (message.type === 'SEEK_TO') {
    const video = getVideoElement();
    if (video && typeof message.time === 'number') {
      video.currentTime = message.time;
      if (message.play) void video.play();
      sendResponse({ success: true, time: video.currentTime });
    } else {
      sendResponse({ success: false, error: 'Video element not found' });
    }
    return true;
  }
  if (message.type === 'GET_PLAYER_STATE') {
    const video = getVideoElement();
    sendResponse({ videoId: new URLSearchParams(window.location.search).get('v'), currentTime: video?.currentTime ?? 0, duration: video?.duration ?? 0, paused: video?.paused ?? true });
    return true;
  }
  if (message.type === 'CAPTURE_FRAME') {
    const video = getVideoElement();
    if (message.videoId !== new URLSearchParams(window.location.search).get('v') || !video || !Number.isFinite(video.duration)) {
      sendResponse({ error: 'The video changed or is not ready for frame capture.' });
      return true;
    }
    video.pause();
    const time = Math.min(Math.max(0, Number(message.time) || 0), Math.max(0, video.duration - 0.2));
    void seekFrame(video, time).then(() => {
      const rect = video.getBoundingClientRect();
      sendResponse({ start: time, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, viewport: { width: window.innerWidth, height: window.innerHeight } });
    }).catch(error => sendResponse({ error: String(error) }));
    return true;
  }
  if (message.type === 'PAUSE_VIDEO') {
    getVideoElement()?.pause();
    sendResponse({ success: true });
    return true;
  }
});
