import { createGMPlugin } from './vendor/gm-plugin-web-sdk.esm.js';
import { MemoMindDisplay } from './display-bridge.mjs';

const byId = id => document.getElementById(id);
const status = text => { byId('status').textContent = text; };
const gm = createGMPlugin();
let stream = null, display = null, previewTimer = null;
let stopping = false;
const ready = gm.ready(); // Handshake starts independently of network/device operations.

async function disconnect() {
  if (stopping) return;
  stopping = true;
  if (stream) stream.close();
  stream = null;
  clearTimeout(previewTimer);
  byId('preview').textContent = 'No suggestion.';
  byId('connect').disabled = true;
  byId('disconnect').disabled = true;
  byId('sample').disabled = true;
  if (display) await display.close();
  display = null;
  stopping = false;
  byId('connect').disabled = false;
  byId('sample').disabled = false;
}

byId('sample').addEventListener('click', async () => {
  if (stream || stopping) return;
  byId('sample').disabled = true;
  byId('connect').disabled = true;
  try {
    await ready;
    if (display) await display.close();
    display = new MemoMindDisplay(gm, error => status('Display unavailable: ' + error.message));
    const prompt = 'SAMPLE CUE\nWhat evidence supports that claim?';
    byId('preview').textContent = prompt;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => { byId('preview').textContent = 'No suggestion.'; }, 15000);
    status('Sample display only; no AI request. The cue clears after 15 seconds.');
    byId('disconnect').disabled = false;
    await display.push({seq: 1, status: 'ready', prompt, expires_at: Date.now()/1000 + 15});
  } catch (error) { status(error.message || String(error)); }
  finally { byId('sample').disabled = false; byId('connect').disabled = false; }
});

byId('connect-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (stream || stopping) return;
  byId('connect').disabled = true;
  byId('sample').disabled = true;
  try {
    const url = new URL(byId('session-url').value);
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if (url.protocol !== 'https:' && !(local && url.protocol === 'http:')) {
      throw new Error('Use an HTTPS service reachable from the phone.');
    }
    if (url.pathname !== '/api/copilot/events' || !url.searchParams.get('session_id') ||
        url.username || url.password) throw new Error('Paste the glasses stream link from ProSe.');
    url.searchParams.set('view', 'glasses');
    await ready;
    if (display) await display.close();
    clearTimeout(previewTimer);
    byId('preview').textContent = 'Listening…';
    display = new MemoMindDisplay(gm, error => {
      status('Display unavailable: ' + (error.message || String(error)));
      void disconnect();
    });
    const active = new EventSource(url.href);
    stream = active;
    byId('disconnect').disabled = false;
    active.onopen = () => { if (stream === active) status('Connected. Waiting for a live cue.'); };
    active.addEventListener('frame', event => {
      if (stream !== active) return;
      try {
        const frame = JSON.parse(event.data);
        if (frame.version !== 1) throw new Error('Unsupported cue format');
        clearTimeout(previewTimer);
        const ttl = Number.isFinite(frame.expires_at) ? frame.expires_at * 1000 - Date.now() : 0;
        byId('preview').textContent = ttl > 0 ? (frame.prompt || 'Listening…') : 'Listening…';
        if (ttl > 0) previewTimer = setTimeout(() => {
          byId('preview').textContent = 'Listening…';
        }, Math.min(ttl, 15000));
        void display.push(frame).catch(error => { status(error.message); void disconnect(); });
      } catch (error) { status(error.message); void disconnect(); }
    });
    active.addEventListener('stopped', () => { status('Session stopped.'); void disconnect(); });
    active.onerror = () => {
      if (stream !== active) return;
      status('Connection interrupted; reconnecting.');
      byId('preview').textContent = 'No suggestion.';
      void display.clear();
    };
  } catch (error) {
    status(error.message || String(error));
    await disconnect();
  }
});
byId('disconnect').addEventListener('click', () => { status('Disconnected.'); void disconnect(); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { status('Paused. Reconnect to resume.'); void disconnect(); }
});
window.addEventListener('pagehide', () => { void disconnect().finally(() => gm.close()); });
ready.then(() => {
  status('MemoMind host ready. Connect a ProSe session.');
  byId('connect').disabled = false;
  byId('sample').disabled = false;
}).catch(error => status('Open this plugin in MemoMind Studio/App: ' + error.message));
