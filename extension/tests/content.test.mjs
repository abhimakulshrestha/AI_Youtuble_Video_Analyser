import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

test('an open transcript panel waits for segments and returns them', async () => {
  const videoId = 'MhqzITOrGk0';
  const segments = [];
  let listener;
  let onMutation;
  const panel = {
    getAttribute: () => 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED',
    querySelector: selector => selector === 'transcript-segment-view-model' ? segments[0] : null,
    querySelectorAll: () => segments,
  };
  const document = {
    title: 'Test video',
    documentElement: {},
    querySelector(selector) {
      if (selector === 'ytd-watch-flexy') return { getAttribute: () => videoId };
      if (selector.includes('PAmodern_transcript_view')) return panel;
      return null;
    },
  };
  const window = {
    location: { href: `https://www.youtube.com/watch?v=${videoId}`, search: `?v=${videoId}` },
    setTimeout,
    clearTimeout,
  };
  class MutationObserver {
    constructor(callback) { onMutation = callback; }
    observe() {}
    disconnect() {}
  }
  const chrome = { runtime: { onMessage: { addListener(callback) { listener = callback; } } } };
  runInNewContext(readFileSync(new URL('../dist/assets/content.js', import.meta.url), 'utf8'), {
    chrome, document, window, location: window.location, URLSearchParams, MutationObserver,
  });

  const response = new Promise(resolve => listener({ type: 'GET_VIDEO_CONTEXT' }, {}, resolve));
  segments.push({
    querySelector(selector) {
      return { textContent: selector.includes('Timestamp') ? '0:08' : 'Caption from the video' };
    },
  });
  onMutation();
  const context = await response;
  assert.equal(context.videoId, videoId);
  assert.equal(context.transcript_data.length, 1);
  assert.equal(context.transcript_data[0].text, 'Caption from the video');
  assert.equal(context.transcript_data[0].start, 8);
});
