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

async function fetchTranscriptFromDOM(): Promise<{ text: string; start: number; duration: number }[] | null> {
  const videoId = new URLSearchParams(location.search).get('v');
  const watch = document.querySelector('ytd-watch-flexy');
  if (!videoId || watch?.getAttribute('video-id') !== videoId) return null;

  const selector = 'ytd-engagement-panel-section-list-renderer[target-id="PAmodern_transcript_view"]';
  let panel = document.querySelector(selector);
  const wasOpen = panel?.getAttribute('visibility') === 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED';
  if (!wasOpen) {
    const button = document.querySelector<HTMLButtonElement>('ytd-video-description-transcript-section-renderer button[aria-label="Show transcript"]');
    if (!button) return null;
    button.click();
    const ready = () => {
      const current = document.querySelector(selector);
      return current?.getAttribute('visibility') === 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED' && !!current.querySelector('transcript-segment-view-model');
    };
    if (!ready()) {
      await new Promise<void>(resolve => {
        const timer = window.setTimeout(() => { observer.disconnect(); resolve(); }, 8000);
        const observer = new MutationObserver(() => {
          if (!ready()) return;
          window.clearTimeout(timer);
          observer.disconnect();
          resolve();
        });
        observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['visibility'] });
      });
    }
    panel = document.querySelector(selector);
  }

  try {
    if (new URLSearchParams(location.search).get('v') !== videoId || panel?.getAttribute('visibility') !== 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED') return null;
    const segments = Array.from(panel.querySelectorAll('transcript-segment-view-model')).flatMap(node => {
      const time = node.querySelector('.ytwTranscriptSegmentViewModelTimestamp')?.textContent?.trim();
      const text = node.querySelector('span[role="text"]')?.textContent?.trim();
      if (!time || !text) return [];
      const parts = time.split(':').map(Number);
      if (parts.some(part => !Number.isFinite(part))) return [];
      return [{ text, start: parts.reduce((seconds, part) => seconds * 60 + part, 0), duration: 0 }];
    });
    for (let index = 0; index < segments.length; index++) {
      segments[index].duration = index + 1 < segments.length ? Math.max(0, segments[index + 1].start - segments[index].start) : 3;
    }
    return segments.length ? segments : null;
  } finally {
    if (!wasOpen) panel?.querySelector<HTMLButtonElement>('button[aria-label="Close"]')?.click();
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
