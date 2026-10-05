import { createGMPlugin } from './vendor/gm-plugin-web-sdk.esm.js';
import { MemoMindDisplay } from './display-bridge.mjs';

const byId = id => document.getElementById(id);
const status = text => { byId('status').textContent = text; };
const conn = state => {
  document.body.dataset.conn = state;
  const action = document.querySelector('#connect .row-lbl');
  if (action && action.firstChild) {
    action.firstChild.textContent =
      ['wait', 'live', 'sample'].includes(state) ? 'stop' : 'connect';
  }
};
const gm = createGMPlugin();
let stream = null, display = null, disconnectTimer = null;
let hudOrigin = null; // Server origin of the connected stream, for button forwards.
let stopping = false;
const ready = gm.ready(); // Handshake starts independently of network/device operations.

// The bubble persists through transient SSE reconnects; only a sustained outage
// (readyState never returns to OPEN within the grace period) clears the display.
function armDisconnectTimer() {
  clearTimeout(disconnectTimer);
  disconnectTimer = setTimeout(() => {
    if (stream && stream.readyState !== EventSource.OPEN) {
      status('Connection lost; clearing display.');
      void display.clear();
    }
  }, 60000);
}
function clearDisconnectTimer() { clearTimeout(disconnectTimer); disconnectTimer = null; }

async function disconnect() {
  if (stopping) return;
  stopping = true;
  if (stream) stream.close();
  stream = null;
  conn('off');
  clearDisconnectTimer();
  byId('preview').textContent = 'No suggestion.';
  byId('connect').disabled = true;
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
  try {
    await ready;
    if (display) await display.close();
    display = new MemoMindDisplay(gm, error => status('Display unavailable: ' + error.message));
    const prompt = 'SAMPLE CUE\nWhat evidence supports that claim?';
    byId('preview').textContent = prompt;
    status('Sample display only; no AI request. Stays until you disconnect or show it again.');
    conn('sample');
    await display.push({
      version: 2, seq: 1, status: 'ready', prompt, speaker: 'Sample',
      mood_label: 'confident', mood_intensity: 3, momentum_pct: 65,
      expires_at: Date.now() / 1000 + 15,
    });
  } catch (error) { status(error.message || String(error)); }
  finally { byId('sample').disabled = false; byId('connect').disabled = false; }
});

// Remember the last pasted link so the page loads ready to connect.
try {
  const saved = localStorage.getItem('prose.hud.url');
  if (saved) byId('session-url').value = saved;
} catch (_) { /* Storage is optional. */ }

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
    const globalStream = url.pathname === '/hud/stream';
    if (!globalStream && url.pathname !== '/api/copilot/events') {
      throw new Error('Paste the glasses stream link from ProSe.');
    }
    if (globalStream) {
      if (url.username || url.password || url.search)
        throw new Error('Paste the glasses stream link from ProSe.');
    } else {
      if (!url.searchParams.get('session_id') || url.username || url.password)
        throw new Error('Paste the glasses stream link from ProSe.');
      url.searchParams.set('view', 'glasses');
    }
    try { localStorage.setItem('prose.hud.url', url.href); } catch (_) { /* Optional. */ }
    hudOrigin = url.origin;
    await ready;
    if (display) await display.close();
    byId('preview').textContent = 'Listening…';
    display = new MemoMindDisplay(gm, error => {
      status('Display unavailable: ' + (error.message || String(error)));
      void disconnect();
    });
    const active = new EventSource(url.href);
    stream = active;
    conn('wait');
    byId('connect').disabled = false;
    active.onopen = () => {
      if (stream !== active) return;
      clearDisconnectTimer();
      conn('live');
      status('Connected. Waiting for a live cue.');
    };
    active.addEventListener('frame', event => {
      if (stream !== active) return;
      try {
        const frame = JSON.parse(event.data);
        if (frame.version !== 2) throw new Error('Unsupported cue format');
        clearDisconnectTimer();
        void display.push(frame).catch(error => { status(error.message); void disconnect(); });
        // Only a ready frame may change what's shown; everything else (thinking,
        // listening, unavailable, expired) leaves the current bubble as-is.
        if (frame.status === 'ready') {
          const lines = [frame.prompt || 'Listening…'];
          if (frame.mood_label) {
            lines.push(`${frame.speaker || 'Speaker'}: ${frame.mood_label} ${frame.mood_intensity}/5`);
          }
          byId('preview').textContent = lines.join('\n');
        }
      } catch (error) { status(error.message); void disconnect(); }
    });
    active.addEventListener('stopped', () => { status('Session stopped.'); void disconnect(); });
    active.onerror = () => {
      if (stream !== active) return;
      conn('lost');
      status('Connection interrupted; reconnecting.');
      armDisconnectTimer();
    };
  } catch (error) {
    status(error.message || String(error));
    await disconnect();
  }
});
byId('connect').addEventListener('click', event => {
  if (stream || display) {
    event.preventDefault();
    status('Disconnected.');
    void disconnect();
  }
});

// Row 04 opens the full phone controller on the server; row 05 embeds the
// personality matrix here, writing tone/mode preferences straight to the
// stream origin (the only menu actions this foreign origin may perform).
let tone = {debate: {humor: 2, rhetoric: 2, attack: 2, listening: 2},
            litigation: {directness: 2, formality: 2, encouragement: 2, urgency: 2}};
let tonePoles = {debate: {humor: ['humor', 'seriousness'], rhetoric: ['reason', 'rhetoric'],
                          attack: ['build', 'attack'], listening: ['press', 'listen']},
                 litigation: {directness: ['measured', 'blunt'], formality: ['plain', 'formal'],
                          encouragement: ['exacting', 'supportive'],
                          urgency: ['unhurried', 'urgent']}};
let toneMode = 'debate';
let toneTimer = null;

const serverBase = () => {
  try { return new URL(byId('session-url').value).origin; }
  catch (_) { return null; }
};
const syncControllerHref = () => {
  const link = byId('controller');
  const base = serverBase();
  if (base) {
    link.setAttribute('href', base + '/controller');
    link.removeAttribute('aria-disabled');
  } else {
    link.removeAttribute('href');
    link.setAttribute('aria-disabled', 'true');
  }
};
byId('session-url').addEventListener('input', syncControllerHref);
byId('controller').addEventListener('click', event => {
  if (!serverBase()) {
    event.preventDefault();
    status('Paste the glasses stream link first.');
  }
});
syncControllerHref();

function adoptMatrix(snapshot) {
  if (snapshot.tones) tone = snapshot.tones;
  if (snapshot.tone_poles) tonePoles = snapshot.tone_poles;
  if (snapshot.tone_mode) toneMode = snapshot.tone_mode;
  renderMatrix();
}
function renderMatrix() {
  const poles = tonePoles[toneMode] || {};
  const traits = Object.keys(poles);
  const values = tone[toneMode] || {};
  for (const [id, active] of [['tone-debate', toneMode === 'debate'],
                              ['tone-litigation', toneMode === 'litigation']]) {
    byId(id).classList.toggle('on', active);
    byId(id).setAttribute('aria-pressed', String(active));
  }
  for (const [id, slot] of [['xy-a', 0], ['xy-b', 1]]) {
    const fx = traits[slot * 2], fy = traits[slot * 2 + 1];
    if (!fx || !fy) continue;
    const el = byId(id);
    el.dataset.x = fx; el.dataset.y = fy;
    const vx = values[fx] ?? 2, vy = values[fy] ?? 2;
    const dot = el.querySelector('.xy-dot');
    dot.style.left = ((vx / 4) * 100) + '%';
    dot.style.top = ((1 - vy / 4) * 100) + '%';
    const xl = poles[fx] || [fx, fx], yl = poles[fy] || [fy, fy];
    el.querySelector('.xy-head').textContent =
      xl[0] + ' ↔ ' + xl[1] + ' × ' + yl[0] + ' ↔ ' + yl[1];
    el.querySelector('.xy-val').textContent = 'x ' + vx + '/4 · y ' + vy + '/4';
  }
}
async function matrixFetch(body) {
  const base = serverBase();
  if (!base) throw new Error('Paste the glasses stream link first.');
  const response = await fetch(base + '/api/hud/menu', body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  } : undefined);
  if (!response.ok) throw new Error('Controller unreachable (' + response.status + ')');
  adoptMatrix(await response.json());
}
function scheduleMatrixSync() {
  clearTimeout(toneTimer);
  toneTimer = setTimeout(() => void syncMatrix(), 140);
}
async function syncMatrix() {
  try {
    await matrixFetch({action: 'tone', mode: toneMode,
      tone: Object.assign({}, tone[toneMode])});
  } catch (error) { status(error.message || String(error)); }
}
function bindMatrixPad(id) {
  const el = byId(id);
  const grid = el.querySelector('.xy-grid');
  let dragging = false;
  const apply = event => {
    const rect = grid.getBoundingClientRect();
    const px = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const py = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    const nx = Math.round(px * 4);
    const ny = 4 - Math.round(py * 4);
    const values = tone[toneMode];
    const fx = el.dataset.x, fy = el.dataset.y;
    if (values[fx] !== nx || values[fy] !== ny) {
      values[fx] = nx; values[fy] = ny;
      renderMatrix(); scheduleMatrixSync();
    }
  };
  grid.addEventListener('pointerdown', event => {
    dragging = true;
    grid.setPointerCapture(event.pointerId);
    apply(event);
    event.preventDefault();
  });
  grid.addEventListener('pointermove', event => { if (dragging) apply(event); });
  grid.addEventListener('pointerup', () => {
    if (!dragging) return;
    dragging = false;
    clearTimeout(toneTimer);
    void syncMatrix();
  });
  grid.addEventListener('pointercancel', () => { dragging = false; });
}
bindMatrixPad('xy-a');
bindMatrixPad('xy-b');
for (const [id, next] of [['tone-debate', 'debate'], ['tone-litigation', 'litigation']]) {
  byId(id).addEventListener('click', async () => {
    if (next === toneMode) return;
    try { await matrixFetch({action: 'mode', mode: next}); }
    catch (error) { status(error.message || String(error)); }
  });
}
byId('matrix').addEventListener('toggle', () => {
  if (!byId('matrix').open) return;
  matrixFetch(null).catch(error => status(error.message || String(error)));
});
renderMatrix();

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { status('Paused. Reconnect to resume.'); void disconnect(); }
});
window.addEventListener('pagehide', () => { void disconnect().finally(() => gm.close()); });
ready.then(() => {
  // Glasses accessory buttons arrive on the HUD channel and only drive the
  // launcher state machine; POST them to the connected server verbatim.
  gm.plugin.onMessage(({ channel, data }) => {
    if (channel !== 20560 || !hudOrigin) return;
    let message;
    try { message = JSON.parse(new TextDecoder().decode(data)); } catch (_) { return; }
    if (!message || typeof message.button !== 'string') return;
    fetch(hudOrigin + '/api/hud/button', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ button: message.button }),
    }).catch(() => {});
  });
  status('MemoMind host ready.');
  byId('connect').disabled = false;
  byId('sample').disabled = false;
  if (byId('session-url').value.trim()) {
    status('Auto-connecting to ProSe…');
    byId('connect-form').requestSubmit();
  }
}).catch(error => status('Open this plugin in MemoMind Studio/App: ' + error.message));
