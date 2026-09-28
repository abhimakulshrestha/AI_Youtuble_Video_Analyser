import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

test('toolbar click opens the panel through action.onClicked', () => {
  const manifest = JSON.parse(readFileSync(new URL('../dist/manifest.json', import.meta.url)));
  assert.ok(manifest.permissions.includes('activeTab'));
  assert.ok(manifest.permissions.includes('scripting'));
  assert.equal(manifest.action.default_popup, undefined);
  assert.ok(existsSync(new URL(`../dist/${manifest.side_panel.default_path}`, import.meta.url)));

  let onClicked;
  let panelBehavior;
  const opened = [];
  const chrome = {
    sidePanel: {
      setPanelBehavior(value) { panelBehavior = value; return Promise.resolve(); },
      open(value) { opened.push(value); return Promise.resolve(); },
    },
    action: { onClicked: { addListener(listener) { onClicked = listener; } } },
    tabs: { onUpdated: { addListener() {} } },
  };
  runInNewContext(readFileSync(new URL('../dist/assets/background.js', import.meta.url), 'utf8'), { chrome, console });
  assert.equal(panelBehavior.openPanelOnActionClick, false);
  assert.equal(typeof onClicked, 'function');
  onClicked({ id: 42 });
  assert.equal(opened.length, 1);
  assert.equal(opened[0].tabId, 42);
});
