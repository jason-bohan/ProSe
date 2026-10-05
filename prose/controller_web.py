"""Phone-first controller page: HUD launcher, debate setup, and animated fight view."""
from __future__ import annotations

import html

from .debate import PERSONAS, TEMPERAMENTS

CONTROLLER_CSS = r"""
.vh{position:absolute;width:1px;height:1px;overflow:hidden;
clip-path:inset(50%);white-space:nowrap}
:root{--pad:clamp(.9rem,4vw,1.4rem)}
body{background:var(--k);color:var(--tw)}
a{color:var(--tw)}
a:hover{color:var(--o)}
.wrap{max-width:34rem;margin:0 auto;padding:var(--pad);padding-bottom:7.5rem}
.top{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem}
.top strong{color:var(--g);font-size:1.1rem;letter-spacing:.08em}
.top nav{margin-left:auto}
.mode-list{display:grid;gap:.7rem}
.mode-card{display:block;width:100%;text-align:left;background:transparent;color:var(--tw);
 border:2px solid var(--g3);border-radius:12px;padding:1rem;cursor:pointer;
 font:inherit;transition:border-color .15s,transform .1s}
.mode-card:active{transform:scale(.985)}
.mode-card .idx{color:var(--o);font-weight:700;margin-right:.6rem}
.mode-card h3{margin:.15rem 0 .3rem;color:var(--tw);font-size:1.05rem}
.mode-card p{margin:0;color:#9a9a9a;font-size:.82rem}
.mode-card.sel{border-color:var(--g);background:rgba(0,255,128,.06)}
.mode-card.sel h3{color:var(--g)}
.setup-grid{display:grid;gap:.75rem}
.setup-grid label{display:grid;gap:.3rem;font-size:.85rem;color:#b9b9b9}
.setup-grid input,.setup-grid select,.setup-grid textarea{
 background:#0c0c0c;color:var(--tw);border:1px solid var(--g3);border-radius:8px;
 padding:.6rem;font:inherit;font-size:.95rem}
.setup-grid textarea{min-height:4.5rem;resize:vertical}
.toggle{grid-template-columns:auto 1fr;align-items:center;gap:.6rem!important}
.toggle input{width:1.15rem;height:1.15rem;accent-color:var(--g)}
details.cases{border:1px solid var(--g3);border-radius:8px;padding:.5rem .7rem}
details.cases summary{cursor:pointer;color:var(--o);font-size:.85rem}
.case-row{display:flex;gap:.55rem;align-items:center;padding:.28rem 0;font-size:.85rem}
.case-row input{accent-color:var(--g)}
.matrix{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;margin:.6rem 0}
.xy{display:grid;gap:.35rem;min-width:0}
.xy-head{font-size:.68rem;letter-spacing:.08em;color:#9a9a9a;text-transform:lowercase}
.xy-grid{position:relative;aspect-ratio:1;border:2px solid var(--g3);border-radius:12px;
 background:#0c0c0c;touch-action:none;cursor:crosshair;overflow:hidden;
 background-image:repeating-linear-gradient(0deg,transparent 0 calc(25% - 1px),
 #232323 calc(25% - 1px) 25%),repeating-linear-gradient(90deg,transparent 0 calc(25% - 1px),
 #232323 calc(25% - 1px) 25%)}
.xy-grid::before{content:"";position:absolute;left:0;right:0;top:var(--y,50%);height:1px;
 background:#ffffff26;pointer-events:none}
.xy-grid::after{content:"";position:absolute;top:0;bottom:0;left:var(--x,50%);width:1px;
 background:#ffffff26;pointer-events:none}
.xy-dot{position:absolute;width:.95rem;height:.95rem;border-radius:50%;background:var(--o);
 left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:none;
 box-shadow:0 0 0 2px #00000099,0 0 8px #ff5a2488}
.xy:active .xy-grid{border-color:var(--o)}
.xy-val{font-size:.72rem;color:var(--g);letter-spacing:.03em;text-transform:lowercase;
 overflow-wrap:anywhere}
.mode-seg{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin:.7rem 0 .2rem}
.seg{min-height:44px;background:transparent;color:#9a9a9a;border:2px solid var(--g3);
 border-radius:10px;font:inherit;font-size:.78rem;letter-spacing:.1em;cursor:pointer}
.seg.on{border-color:var(--o);color:var(--o)}
.btn-row{display:flex;gap:.7rem;margin-top:.4rem;flex-wrap:wrap}
button.primary{flex:1;background:var(--g);color:#001a0d;border:0;border-radius:10px;
 padding:.9rem 1rem;font:inherit;font-weight:700;letter-spacing:.06em;cursor:pointer}
button.ghost{background:transparent;color:var(--tw);border:1px solid var(--g3);
 border-radius:10px;padding:.9rem 1rem;font:inherit;cursor:pointer}
.fight-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem;
 border:2px solid var(--g3);border-radius:12px;padding:.7rem .9rem;margin-bottom:.7rem;
 animation:pop .3s ease-out both}
.fight-head .side{font-weight:700;letter-spacing:.05em;font-size:.95rem}
.fight-head .you{color:var(--g)}
.fight-head .foe{color:var(--y);text-align:right}
.fight-head .vs{color:var(--o);font-weight:700}
.meter-row{display:flex;align-items:center;gap:.6rem;margin:.4rem 0 .2rem}
.meter-label{font-size:.7rem;letter-spacing:.14em;color:#8a8a8a}
.meter{flex:1;height:12px;border:1px solid var(--g3);border-radius:7px;overflow:hidden;
 background:#0c0c0c}
.meter i{display:block;height:100%;width:50%;background:var(--g);border-radius:7px;
 transition:width .6s ease-out}
.meter.flash{animation:hitflash .55s ease-out 1}
#meter-pct{font-size:.85rem;color:var(--g);min-width:2.6rem;text-align:right}
.round{font-size:.75rem;color:#8a8a8a;margin:.25rem 0 .6rem;letter-spacing:.05em}
.thinking{display:flex;gap:.4rem;padding:.4rem 0}
.thinking i{width:.55rem;height:.55rem;border-radius:50%;background:var(--g);
 animation:dots 1s ease-in-out infinite}
.thinking i:nth-child(2){animation-delay:.15s}
.thinking i:nth-child(3){animation-delay:.3s}
.transcript{display:grid;gap:.5rem;max-height:34vh;overflow-y:auto;padding-right:.2rem;
 margin-bottom:.7rem}
.bubble{border:1px solid var(--g3);border-radius:10px;padding:.55rem .7rem;
 animation:slidein .25s ease-out both}
.bubble strong{display:block;font-size:.68rem;letter-spacing:.12em;color:#8a8a8a;
 margin-bottom:.2rem}
.bubble p{margin:0;font-size:.92rem;white-space:pre-wrap}
.bubble.you{border-color:var(--g1);background:rgba(0,255,128,.05)}
.bubble.you strong{color:var(--g)}
.bubble.foe{border-color:var(--o);background:rgba(255,176,32,.05)}
.bubble.foe strong{color:var(--y)}
.bubble.fresh.foe{animation:foeland .4s ease-out both}
.coach{border:1px dashed var(--g3);border-radius:10px;padding:.7rem;margin-bottom:.7rem}
.coach h3{margin:0 0 .35rem;font-size:.72rem;letter-spacing:.14em;color:var(--o)}
.coach blockquote{margin:0 0 .4rem;font-size:.95rem;color:var(--tw)}
.coach p{margin:.25rem 0 0;font-size:.8rem;color:#9a9a9a}
.coach .fb{color:var(--g)}
#draft{width:100%;box-sizing:border-box;min-height:5rem;background:#0c0c0c;color:var(--tw);
 border:1px solid var(--g3);border-radius:10px;padding:.7rem;font:inherit;font-size:.95rem;
 resize:vertical}
.gamepad{position:fixed;left:0;right:0;bottom:0;background:#050505ee;
 border-top:2px solid var(--g3);padding:.55rem var(--pad) .7rem;
 display:flex;align-items:center;justify-content:space-between;gap:.4rem}
.pad-group{display:flex;gap:.4rem}
.pad-btn{min-width:3rem;min-height:3rem;border-radius:12px;border:2px solid var(--g3);
 background:#101010;color:var(--tw);font:inherit;font-weight:700;font-size:.8rem;
 cursor:pointer;padding:.35rem .5rem;letter-spacing:.04em}
.pad-btn:active{background:var(--g);color:#001a0d;border-color:var(--g)}
.pad-btn.go{border-color:var(--g);color:var(--g)}
.pad-btn.danger{border-color:#a33;color:#e77}
.pad-btn[disabled]{opacity:.35}
.dpad{display:grid;grid-template-columns:repeat(3,2.4rem);grid-auto-rows:2.4rem;gap:.25rem}
.dpad .pad-btn{min-width:0;min-height:0;padding:0;font-size:.9rem}
.dpad .up{grid-column:2}
.dpad .left{grid-column:1;grid-row:2}
.dpad .down{grid-column:2;grid-row:2}
.dpad .right{grid-column:3;grid-row:2}
.toast{position:fixed;left:50%;bottom:8.2rem;transform:translateX(-50%);
 background:var(--o);color:#111;font-size:.8rem;font-weight:700;border-radius:8px;
 padding:.5rem .8rem;z-index:9;animation:pop .2s ease-out both}
.hud-link{margin-top:1.2rem;border-top:1px solid var(--g3);padding-top:.8rem}
.hud-link label{display:grid;gap:.35rem;font-size:.8rem;color:#b9b9b9}
.hud-link input{background:#0c0c0c;color:var(--g);border:1px solid var(--g3);
 border-radius:8px;padding:.55rem;font:inherit;font-size:.8rem}
.disclaimer{margin-top:1rem;font-size:.72rem;color:#7a7a7a;line-height:1.45}
@keyframes pop{from{opacity:0;transform:scale(.94)}to{opacity:1;transform:scale(1)}}
@keyframes slidein{from{opacity:0;transform:translateX(-10px)}
 to{opacity:1;transform:translateX(0)}}
@keyframes foeland{0%{transform:translateX(0)}25%{transform:translateX(-6px) rotate(-1deg)}
 55%{transform:translateX(5px)}80%{transform:translateX(-3px)}
 100%{transform:translateX(0)}}
@keyframes hitflash{0%{box-shadow:0 0 0 2px #fff}
 100%{box-shadow:0 0 0 2px transparent}}
@keyframes dots{0%,100%{opacity:.25;transform:translateY(0)}
 50%{opacity:1;transform:translateY(-3px)}}
"""

CONTROLLER_JS = r"""
const $ = id => document.getElementById(id);
let modes = [], index = 0, mode = '', view = 'menu', session = null, state = null;
const TRAITS = {debate: ['humor', 'rhetoric', 'attack', 'listening'],
                litigation: ['directness', 'formality', 'encouragement', 'urgency']};
let tone = {debate: {humor: 2, rhetoric: 2, attack: 2, listening: 2},
            litigation: {directness: 2, formality: 2, encouragement: 2, urgency: 2}};
let tonePoles = {debate: {humor: ['humor', 'seriousness'], rhetoric: ['reason', 'rhetoric'],
                          attack: ['build', 'attack'], listening: ['press', 'listen']},
                 litigation: {directness: ['measured', 'blunt'], formality: ['plain', 'formal'],
                          encouragement: ['exacting', 'supportive'],
                          urgency: ['unhurried', 'urgent']}};
let toneMode = 'debate';
let toneTimer = null;
let busy = false, rec = null, poll = null, lastTurn = -1, soundTurn = -1;
const KEY = 'prose.controller.session';
  const voiceKey = 'prose-hud-voice';
  let voices = [];
  function loadVoices() {
    try { voices = speechSynthesis.getVoices(); } catch (_) { voices = []; }
  }
  function populateVoiceDropdown() {
    const sel = $('hud-voice');
    if (!sel || !voices.length) return;
    const current = sel.value;
    sel.replaceChildren();
    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = '(Browser default)';
    sel.appendChild(defaultOpt);
    const grouped = {};
    voices.forEach(v => {
      const lang = (v.lang || '').split('-')[0].toUpperCase();
      if (!grouped[lang]) grouped[lang] = [];
      grouped[lang].push(v);
    });
    Object.keys(grouped).sort().forEach(lang => {
      const g = document.createElement('optgroup');
      g.label = lang;
      grouped[lang].forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.name;
        opt.textContent = v.name + (v.localService ? ' (local)' : ' (remote)');
        if (v.name === current) opt.selected = true;
        g.appendChild(opt);
      });
      sel.appendChild(g);
    });
  }
  function rememberVoice() {
    const sel = $('hud-voice');
    if (!sel) return;
    try { localStorage.setItem(voiceKey, sel.value); } catch (_) { /* Optional. */ }
  }
  function loadVoice() {
    try {
      const saved = localStorage.getItem(voiceKey);
      if (saved) {
        const sel = $('hud-voice');
        if (sel && Array.from(sel.options).some(o => o.value === saved)) sel.value = saved;
      }
    } catch (_) { /* Optional. */ }
  }
  function getSelectedVoice() {
    const sel = $('hud-voice');
    if (!sel || !sel.value) return null;
    return voices.find(v => v.name === sel.value) || null;
  }
  function refreshVoices() {
    loadVoices();
    populateVoiceDropdown();
    loadVoice();
  }
  speechSynthesis.addEventListener('voiceschanged', refreshVoices);
  refreshVoices();

/* V2-lite: every sound is oscillator/noise math generated on the fly --
 * zero audio bytes shipped, the way .kkrieger's synth did it, but tuned to
 * OP-1 style blips instead of 2004 demo tunes. */
let soundOn = true;
let audioCtx = null;
function actx() {
  if (!soundOn) return null;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!audioCtx) audioCtx = new AC();
    if (audioCtx.state === 'suspended') void audioCtx.resume();
    return audioCtx.state === 'running' ? audioCtx : null;
  } catch (_) { return null; }
}
function beep(freq, ms, type, peak, delay) {
  const ac = actx(); if (!ac) return;
  const t0 = ac.currentTime + (delay || 0);
  const osc = ac.createOscillator(), gain = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(peak, t0 + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + ms / 1000);
  osc.connect(gain); gain.connect(ac.destination);
  osc.start(t0); osc.stop(t0 + ms / 1000 + 0.03);
}
function punchNoise(ms, peak) {
  const ac = actx(); if (!ac) return;
  const len = Math.max(1, Math.floor(ac.sampleRate * ms / 1000));
  const buf = ac.createBuffer(1, len, ac.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const src = ac.createBufferSource(); src.buffer = buf;
  const filter = ac.createBiquadFilter();
  filter.type = 'lowpass'; filter.frequency.value = 480;
  const gain = ac.createGain(); gain.gain.value = peak;
  src.connect(filter); filter.connect(gain); gain.connect(ac.destination);
  src.start();
}
const sfx = {
  tick() { beep(1320, 30, 'square', 0.04); },
  blip() { beep(720, 80, 'triangle', 0.07); },
  thud() { punchNoise(150, 0.22); beep(88, 120, 'sine', 0.18); },
  crack() { punchNoise(90, 0.14); beep(220, 140, 'sawtooth', 0.06); },
  sting() {
    beep(523, 90, 'triangle', 0.07, 0);
    beep(659, 90, 'triangle', 0.07, 0.11);
    beep(784, 150, 'triangle', 0.08, 0.22);
  },
  end() { beep(392, 160, 'sine', 0.06); beep(262, 220, 'sine', 0.06, 0.09); },
};

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  });
  let data; try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const message = (data && data.error) || 'Controller request failed (HTTP ' +
      res.status + ').';
    const err = new Error(message);
    err.status = res.status; throw err;
  }
  if (!data || typeof data !== 'object')
    throw new Error('Controller returned an invalid response.');
  return data;
}
async function getMenu() {
  const response = await fetch('/api/hud/menu');
  let data; try { data = await response.json(); } catch (_) { data = null; }
  if (!response.ok)
    throw new Error('Could not load the controller menu (HTTP ' + response.status + ').');
  if (!data || typeof data !== 'object')
    throw new Error('Controller returned an invalid menu.');
  return data;
}
function show(next) {
  view = next;
  for (const name of ['menu', 'setup', 'fight', 'tone'])
    $('view-' + name).hidden = name !== next;
  padState();
  $('hud-voice').addEventListener('change', rememberVoice);
  populateVoiceDropdown();
}
function toast(text, ms = 1600) {
  const el = $('toast'); el.textContent = text; el.hidden = false;
  clearTimeout(el._t); el._t = setTimeout(() => { el.hidden = true; }, ms);
}
function remember(value) {
  try { if (value) sessionStorage.setItem(KEY, value); else sessionStorage.removeItem(KEY); }
  catch (_) { /* Storage is optional. */ }
}
async function loadMenu() {
  try {
    const snap = await getMenu();
    modes = snap.modes || []; index = snap.index || 0; mode = snap.mode || '';
    adoptTone(snap);
    renderMenu();
    if (snap.state === 'setup') { applyMode(mode); show('setup'); }
    else if (snap.state === 'tone') { renderTone(); show('tone'); }
    else show('menu');
  } catch (error) { toast(error.message); }
}
function adoptTone(snap) {
  if (!snap) return;
  if (snap.tones) tone = snap.tones;
  if (snap.tone_poles) tonePoles = snap.tone_poles;
  if (snap.tone_mode) toneMode = snap.tone_mode;
}
function renderMenu() {
  const list = $('mode-list'); list.replaceChildren();
  modes.forEach((m, i) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'mode-card' + (i === index ? ' sel' : '');
    card.innerHTML = '<span class="idx">' + (i + 1) + '</span>';
    const h = document.createElement('h3'); h.textContent = m.title;
    const p = document.createElement('p'); p.textContent = m.hint;
    card.append(h, p);
    card.addEventListener('click', () => {
      const delta = i - index;
      Promise.resolve(delta ? moveMenu(delta) : null).then(selectMode);
    });
    list.append(card);
  });
}
async function moveMenu(delta, force) {
  try {
    const snap = await post('/api/hud/menu',
      force ? {action: 'move', delta: 0} : {action: 'move', delta});
    modes = snap.modes; index = snap.index; renderMenu();
    sfx.tick();
    return snap;
  } catch (error) { toast(error.message); }
}
async function selectMode() {
  try {
    const snap = await post('/api/hud/menu', {action: 'select'});
    modes = snap.modes; index = snap.index; mode = snap.mode;
    adoptTone(snap);
    sfx.blip();
    if (snap.state === 'tone') { renderTone(); show('tone'); }
    else { applyMode(mode); show('setup'); }
  } catch (error) { toast(error.message); }
}
async function backToMenu() {
  stopPoll();
  if (session) {
    sfx.end();
    try { await post('/api/practice/stop', {session_id: session}); } catch (_) {}
  }
  session = null; state = null; remember(null); lastTurn = -1; soundTurn = -1;
  try { await post('/api/hud/menu', {action: 'back'}); } catch (_) {}
  await loadMenu();
}
function renderTone() {
  const traits = TRAITS[toneMode], values = tone[toneMode], labels = tonePoles[toneMode] || {};
  $('tone-mode-label').textContent = toneMode;
  $('tone-debate').classList.toggle('on', toneMode === 'debate');
  $('tone-litigation').classList.toggle('on', toneMode === 'litigation');
  for (const pair of [['xy-a', 0, 1], ['xy-b', 2, 3]]) {
    const el = $(pair[0]), fx = traits[pair[1]], fy = traits[pair[2]];
    el.dataset.x = fx; el.dataset.y = fy;
    const gx = (values[fx] / 4) * 100, gy = (1 - values[fy] / 4) * 100;
    const grid = el.querySelector('.xy-grid');
    grid.style.setProperty('--x', gx + '%');
    grid.style.setProperty('--y', gy + '%');
    const dot = el.querySelector('.xy-dot');
    dot.style.left = gx + '%';
    dot.style.top = gy + '%';
    const xl = labels[fx] || [fx, fx], yl = labels[fy] || [fy, fy];
    el.querySelector('.xy-head').textContent =
      xl[0] + ' ↔ ' + xl[1] + ' × ' + yl[0] + ' ↔ ' + yl[1];
    $(pair[0] + '-val').textContent =
      'x ' + values[fx] + '/4 · y ' + values[fy] + '/4';
  }
}
async function syncTone() {
  try {
    await post('/api/hud/menu', {action: 'tone', mode: toneMode,
      tone: Object.assign({}, tone[toneMode])});
  }
  catch (error) { toast(error.message); }
}
async function setToneMode(next) {
  if (next === toneMode) return;
  try {
    const snap = await post('/api/hud/menu', {action: 'mode', mode: next});
    adoptTone(snap);
    renderTone(); sfx.blip();
  } catch (error) { toast(error.message); }
}
function scheduleToneSync() {
  clearTimeout(toneTimer);
  toneTimer = setTimeout(syncTone, 140);
}
function bindPad(id) {
  const el = $(id);
  const grid = el.querySelector('.xy-grid');
  let dragging = false;
  const apply = event => {
    const rect = grid.getBoundingClientRect();
    const px = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const py = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    const nx = Math.round(px * 4);
    const ny = 4 - Math.round(py * 4);
    const fx = el.dataset.x, fy = el.dataset.y;
    const values = tone[toneMode];
    if (values[fx] !== nx || values[fy] !== ny) {
      values[fx] = nx; values[fy] = ny;
      renderTone(); sfx.tick(); scheduleToneSync();
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
    syncTone();
  });
  grid.addEventListener('pointercancel', () => { dragging = false; });
}
async function leaveTone() {
  try { await post('/api/hud/menu', {action: 'back'}); } catch (_) {}
  await loadMenu();
}
function applyMode(id) {
  const cfg = (modes[index] && modes[index].config) || {};
  $('setup-title').textContent = id === 'litigation' ? 'Litigation setup' : 'Debate setup';
  $('f-method').value = cfg.method || 'listening';
  $('f-legal').checked = Boolean(cfg.legal_review);
  $('f-docs').checked = Boolean(cfg.include_case_documents);
  $('f-context').checked = Boolean(cfg.include_legal_context);
  if (id === 'litigation' && !$('f-topic').value) $('f-topic').value = 'Case practice';
}
function startSession() {
  const topic = $('f-topic').value.trim();
  const position = $('f-position').value.trim();
  if (!topic || !position) { toast('Topic and position are required.'); return; }
  const ids = Array.from(document.querySelectorAll('.case-row input:checked')).map(c => c.value);
  if (ids.length > 6) { toast('Select at most six case files.'); return; }
  const body = {
    topic, position,
    persona: $('f-persona').value,
    temperament: $('f-temperament').value,
    method: $('f-method').value,
    jurisdiction: $('f-jurisdiction').value.trim() || 'Unspecified',
    vocabulary: true,
    legal_review: $('f-legal').checked,
    include_case_documents: $('f-docs').checked,
    include_legal_context: $('f-context').checked,
    model_id: $('f-model').value,
    document_ids: ids
  };
  busy = true; padState();
  post('/api/practice/sessions', body)
    .then(created => {
      session = created.session_id; remember(session); enterFight(created); sfx.sting();
    })
    .catch(error => toast(error.message))
    .finally(() => { busy = false; padState(); });
}
function enterFight(snapshot) {
  state = snapshot; lastTurn = -1; soundTurn = snapshot.turn;
  show('fight'); renderFight(snapshot, true); startPoll();
}
function renderFight(next, immediate) {
  state = next;
  const cfg = next.config || {};
  const foe = (cfg.persona || 'opponent').toUpperCase() + ' · ' + (cfg.temperament || '');
  $('foe-name').textContent = foe;
  $('round-row').textContent = 'Round ' + next.turn + ' / ' + next.max_turns +
    ' · ' + (next.model || '');
  const score = next.hud_score || {};
  if (Number.isFinite(score.momentum)) setMeter(score.momentum, score.delta > 0);
  if (next.turn !== soundTurn) {
    if (score.hit) sfx.thud();
    else if (Number.isFinite(score.delta) && score.delta < 0) sfx.crack();
    soundTurn = next.turn;
  }
  const log = $('transcript');
  const adding = next.messages.length > lastTurn && lastTurn >= 0;
  log.replaceChildren();
  next.messages.forEach((m, i) => {
    const item = document.createElement('article');
    const you = m.speaker === 'You';
    const fresh = adding && i === next.messages.length - 1 && !you;
    item.className = 'bubble ' + (you ? 'you' : 'foe') + (fresh ? ' fresh' : '');
    const name = document.createElement('strong'); name.textContent = m.speaker;
    const text = document.createElement('p'); text.textContent = m.text;
    item.append(name, text); log.append(item);
  });
  log.scrollTop = log.scrollHeight;
  lastTurn = next.messages.length;
  const coach = next.coach || {};
  $('suggestion').textContent = coach.suggestion || '';
  $('why').textContent = coach.why || '';
  $('coach-fb').textContent = coach.feedback || '';
  $('coach-fb').hidden = !coach.feedback;
  $('voc-fb').textContent = coach.vocabulary_feedback || '';
  $('voc-fb').hidden = !coach.vocabulary_feedback;
  $('use-suggestion').disabled = busy || !coach.suggestion;
  $('hear-coach-btn').disabled = busy || !coach.suggestion || !window.speechSynthesis;
  padState();
}
function setMeter(pct, hit) {
  const fill = $('meter-fill');
  fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
  $('meter-pct').textContent = Math.round(pct) + '%';
  if (hit) { const m = fill.parentElement; m.classList.remove('flash');
    void m.offsetWidth; m.classList.add('flash'); }
}
function thinking(on) {
  $('thinking').hidden = !on;
  padState();
}
function startPoll() {
  stopPoll();
  poll = setInterval(async () => {
    if (!session || busy || view !== 'fight') return;
    try {
      const next = await post('/api/practice/state', {session_id: session});
      thinking(false); renderFight(next, false);
      if (next.complete) { toast('Debate complete — press END.'); stopPoll(); }
    } catch (error) {
      if (error.status === 409) { thinking(true); return; }
      if (error.status === 404) { backToMenu(); return; }
      toast(error.message);
    }
  }, 2000);
}
function stopPoll() { if (poll) clearInterval(poll); poll = null; thinking(false); }
function sendReply() {
  if (!session || busy || !state) return;
  const text = $('draft').value.trim();
  if (!text) { toast('Write a reply first (B loads the coach suggestion).'); return; }
  busy = true; thinking(true); padState();
  post('/api/practice/turn', {session_id: session, text, expected_turn: state.turn})
    .then(next => { $('draft').value = ''; renderFight(next, true); })
    .catch(error => { if (error.status !== 409) toast(error.message); })
    .finally(() => { busy = false; thinking(false); padState(); });
}
function hearCoach() {
  if (!state || !state.coach || !state.coach.suggestion || !window.speechSynthesis) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(state.coach.suggestion);
  utter.rate = 1.02;
  const voice = getSelectedVoice();
  if (voice) utter.voice = voice;
  speechSynthesis.speak(utter);
}
function useSuggestion() {
  if (!state || !state.coach || !state.coach.suggestion) return;
  $('draft').value = state.coach.suggestion;
  $('draft').focus();
  toast('Coach suggestion loaded.');
  sfx.blip();
}
function hearOpponent() {
  if (!state || !state.messages.length || !window.speechSynthesis) return;
  const last = [...state.messages].reverse().find(m => m.speaker !== 'You');
  if (!last) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(last.text);
  utter.rate = 1.02;
  const voice = getSelectedVoice();
  if (voice) utter.voice = voice;
  speechSynthesis.speak(utter);
}
function dictate() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice dictation is not available here.'); return; }
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.interimResults = true;
  const voice = getSelectedVoice();
  rec.lang = voice && voice.lang ? voice.lang : 'en-US';
  const base = $('draft').value;
  rec.onresult = event => {
    let text = '';
    for (const r of event.results) text += r[0].transcript;
    $('draft').value = (base ? base + ' ' : '') + text;
  };
  rec.onerror = () => toast('Dictation stopped.');
  rec.onend = () => { rec = null; padState(); };
  rec.start(); padState();
}
function padState() {
  const pad = $('gamepad');
  const menu = view === 'menu', setup = view === 'setup', fight = view === 'fight';
  const matrix = view === 'tone';
  $('pad-a').textContent = menu ? 'PICK' : setup ? 'START' : matrix ? 'DONE' : 'SEND';
  $('pad-a').disabled = busy;
  $('pad-b').textContent = menu ? 'HOME' : setup || matrix ? 'BACK' : 'SUGGEST';
  $('pad-b').disabled = fight && !$statecoach();
  $('pad-x').disabled = !fight;
  $('pad-y').disabled = !fight;
  $('pad-end').hidden = !fight;
  for (const id of ['pad-left', 'pad-right', 'pad-up', 'pad-down'])
    $(id).disabled = fight || matrix;
  pad.dataset.view = view;
}
function $statecoach() { return Boolean(state && state.coach && state.coach.suggestion); }
function press(action) {
  if (view === 'menu') {
    if (action === 'left' || action === 'up') moveMenu(-1);
    else if (action === 'right' || action === 'down') moveMenu(1);
    else if (action === 'a') selectMode();
    return;
  }
  if (view === 'setup') {
    if (action === 'b' || action === 'back') {
      post('/api/hud/menu', {action: 'back'}).then(loadMenu).catch(() => {});
      show('menu');
    }
    else if (action === 'a') startSession();
    return;
  }
  if (view === 'tone') {
    if (action === 'a' || action === 'b' || action === 'back') leaveTone();
    return;
  }
  if (view === 'fight') {
    if (action === 'a' || action === 'right') sendReply();
    else if (action === 'b') useSuggestion();
    else if (action === 'x') hearOpponent();
    else if (action === 'y') dictate();
    else if (action === 'left') $('draft').value = '';
    else if (action === 'end') backToMenu();
  }
}
document.addEventListener('DOMContentLoaded', () => {
  $('hud-link').value = location.origin + '/hud/stream';
  for (const [id, action] of [['pad-left', 'left'], ['pad-right', 'right'],
    ['pad-up', 'up'], ['pad-down', 'down'], ['pad-a', 'a'], ['pad-b', 'b'],
    ['pad-x', 'x'], ['pad-y', 'y'], ['pad-end', 'end']])
    $(id).addEventListener('click', () => press(action));
  $('start-btn').addEventListener('click', startSession);
  $('pad-snd').addEventListener('click', () => {
    soundOn = !soundOn;
    $('pad-snd').textContent = soundOn ? 'SND ON' : 'SND OFF';
    $('pad-snd').setAttribute('aria-pressed', String(soundOn));
    if (soundOn) sfx.tick();
  });
  $('setup-back').addEventListener('click', () => press('back'));
  $('tone-back').addEventListener('click', leaveTone);
  $('tone-debate').addEventListener('click', () => setToneMode('debate'));
  $('tone-litigation').addEventListener('click', () => setToneMode('litigation'));
  bindPad('xy-a');
  bindPad('xy-b');
  $('send-btn').addEventListener('click', sendReply);
  $('use-suggestion').addEventListener('click', useSuggestion);
  $('hear-coach-btn').addEventListener('click', hearCoach);
  $('hear-btn').addEventListener('click', hearOpponent);
  $('dictate-btn').addEventListener('click', dictate);
  $('end-btn').addEventListener('click', backToMenu);
  document.addEventListener('keydown', event => {
    if (event.target.matches('input,textarea,select')) return;
    const map = {ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up',
      ArrowDown: 'down', a: 'a', b: 'b', x: 'x', y: 'y', Enter: 'a', Escape: 'b'};
    const action = map[event.key];
    if (action) { event.preventDefault(); press(action); }
  });
  let saved = null;
  try { saved = sessionStorage.getItem(KEY); } catch (_) { /* Optional. */ }
  if (saved) {
    session = saved;
    post('/api/practice/state', {session_id: session})
      .then(snapshot => enterFight(snapshot))
      .catch(() => { remember(null); session = null; loadMenu(); });
  } else loadMenu();
  padState();
});
"""


def _options(items: list[tuple[str, str]], selected: str = "") -> str:
    return "".join(
        f"<option value=\"{html.escape(value, quote=True)}\""
        f"{' selected' if value == selected else ''}>"
        f"{html.escape(label)}</option>"
        for value, label in items
    )


def render_controller_page(
    css: str, nav: str, status: dict, documents: list[tuple[str, str]]
) -> str:
    personas = _options([(key, value[0]) for key, value in PERSONAS.items()])
    temperaments = _options(
        [(key, value[0]) for key, value in TEMPERAMENTS.items()], "stubborn"
    )
    methods = _options(
        [("listening", "Listening — focus on rebuttals"),
         ("structure", "Structure — IRAC discipline"),
         ("free", "Free — open exchange")]
    )
    models = _options(
        [(c["id"], c["label"]) for c in status.get("choices", [])],
        status.get("default_model_id", ""),
    )
    cases = "".join(
        f"<label class=\"case-row\"><input type=\"checkbox\" value=\""
        f"{html.escape(doc_id, quote=True)}\" checked> "
        f"{html.escape(name)}</label>"
        for doc_id, name in documents
    ) or "<p class=\"small\">No case files yet — import them under Documents.</p>"
    warning = status.get("configuration_warning") or ""
    if warning:
        warning = f"<p class=\"disclaimer\">{html.escape(warning)}</p>"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Controller · LexGlasses</title>"
        f"<style>{css}{CONTROLLER_CSS}</style></head><body><div class=\"wrap\">"
        "<h1 class=\"vh\">ProSe controller</h1>"
        f"<header class=\"top\"><strong>PROSE</strong> / CONTROLLER {nav}</header>"

        "<main id=\"main\">"
        "<section id=\"view-menu\">"
        "<p class=\"small\">The glasses mirror this cursor. Move it, then press "
        "PICK to configure on this phone.</p>"
        "<div id=\"mode-list\" class=\"mode-list\"></div>"
        "</section>"

        "<section id=\"view-setup\" hidden><div class=\"setup-grid\">"
        "<h2 id=\"setup-title\">Setup</h2>"
        "<label>Topic<input id=\"f-topic\" maxlength=\"500\" "
        "placeholder=\"e.g. School cell-phone bans\"></label>"
        "<label>Your position<textarea id=\"f-position\" maxlength=\"1000\" "
        "placeholder=\"The position you will argue\"></textarea></label>"
        "<label>Opponent<select id=\"f-persona\">" + personas + "</select></label>"
        "<label>Temperament<select id=\"f-temperament\">" + temperaments
        + "</select></label>"
        "<label>Practice method<select id=\"f-method\">" + methods + "</select></label>"
        "<label>Jurisdiction<input id=\"f-jurisdiction\" value=\"Unspecified\" "
        "maxlength=\"160\"></label>"
        "<label>AI model<select id=\"f-model\">" + models + "</select></label>"
        "<label>Voice<select id=\"hud-voice\"><option value=\"\">"
        "(Browser default)</option></select></label><p class=\"small\">"
        "Select a voice for dictation and read-aloud. Changes apply to "
        "the next session.</p>"
        "<label class=\"toggle\"><input type=\"checkbox\" id=\"f-legal\">"
        "Legal review with the specialist</label>"
        "<label class=\"toggle\"><input type=\"checkbox\" id=\"f-context\">"
        "Include legal context</label>"
        "<label class=\"toggle\"><input type=\"checkbox\" id=\"f-docs\">"
        "Use my case documents for rebuttals</label>"
        "<details class=\"cases\"><summary>Case files for this session</summary>"
        + cases + "</details>"
        "<div class=\"btn-row\">"
        "<button type=\"button\" class=\"primary\" id=\"start-btn\">START</button>"
        "<button type=\"button\" class=\"ghost\" id=\"setup-back\">BACK</button>"
        "</div></div></section>"

        "<section id=\"view-tone\" hidden>"
        "<p class=\"small\">Drag each dot — the glasses mirror follows your "
        "finger. Each axis runs pole to pole, 0–4. <span id=\"tone-mode-label\"></span> matrix.</p>"
        "<div class=\"mode-seg\">"
        "<button type=\"button\" class=\"seg\" id=\"tone-debate\">DEBATE</button>"
        "<button type=\"button\" class=\"seg\" id=\"tone-litigation\">LITIGATION</button>"
        "</div>"
        "<div class=\"matrix\">"
        "<div class=\"xy\" id=\"xy-a\" data-x=\"humor\" data-y=\"rhetoric\">"
        "<span class=\"xy-head\"></span>"
        "<div class=\"xy-grid\"><i class=\"xy-dot\"></i></div>"
        "<span class=\"xy-val\" id=\"xy-a-val\"></span></div>"
        "<div class=\"xy\" id=\"xy-b\" data-x=\"attack\" data-y=\"listening\">"
        "<span class=\"xy-head\"></span>"
        "<div class=\"xy-grid\"><i class=\"xy-dot\"></i></div>"
        "<span class=\"xy-val\" id=\"xy-b-val\"></span></div>"
        "</div>"
        "<div class=\"btn-row\">"
        "<button type=\"button\" class=\"ghost\" id=\"tone-back\">BACK</button>"
        "</div></section>"

        "<section id=\"view-fight\" hidden>"
        "<div class=\"fight-head\"><span class=\"side you\">YOU</span>"
        "<span class=\"vs\">VS</span>"
        "<span class=\"side foe\" id=\"foe-name\">OPPONENT</span></div>"
        "<div class=\"meter-row\"><span class=\"meter-label\">CONFIDENCE</span>"
        "<div class=\"meter\"><i id=\"meter-fill\"></i></div>"
        "<span id=\"meter-pct\">50%</span></div>"
        "<div class=\"round\" id=\"round-row\">Round 0</div>"
        "<div class=\"thinking\" id=\"thinking\" hidden><i></i><i></i><i></i></div>"
        "<div class=\"transcript\" id=\"transcript\"></div>"
        "<div class=\"coach\"><h3>COACH — NEXT MOVE</h3>"
        "<blockquote id=\"suggestion\"></blockquote>"
        "<p id=\"why\"></p><p id=\"coach-fb\" class=\"fb\" hidden></p>"
        "<p id=\"voc-fb\" hidden></p>"
        "<div class=\"btn-row\">"
        "<button type=\"button\" class=\"ghost\" id=\"use-suggestion\">Use suggestion</button>"
        "<button type=\"button\" class=\"ghost\" id=\"hear-coach-btn\">Hear coach</button>"
        "<button type=\"button\" class=\"ghost\" id=\"hear-btn\">Hear opponent</button>"
        "<button type=\"button\" class=\"ghost\" id=\"dictate-btn\">Dictate</button>"
        "</div></div>"
        "<textarea id=\"draft\" placeholder=\"Your reply…\"></textarea>"
        "<div class=\"btn-row\">"
        "<button type=\"button\" class=\"primary\" id=\"send-btn\">SEND</button>"
        "<button type=\"button\" class=\"ghost\" id=\"end-btn\">END</button>"
        "</div></section>"

        "<div class=\"gamepad\" id=\"gamepad\">"
        "<div class=\"dpad\">"
        "<button type=\"button\" class=\"pad-btn up\" id=\"pad-up\">▲</button>"
        "<button type=\"button\" class=\"pad-btn left\" id=\"pad-left\">◀</button>"
        "<button type=\"button\" class=\"pad-btn down\" id=\"pad-down\">▼</button>"
        "<button type=\"button\" class=\"pad-btn right\" id=\"pad-right\">▶</button>"
        "</div>"
        "<div class=\"pad-group\">"
        "<button type=\"button\" class=\"pad-btn\" id=\"pad-x\">HEAR</button>"
        "<button type=\"button\" class=\"pad-btn\" id=\"pad-y\">MIC</button>"
        "<button type=\"button\" class=\"pad-btn\" id=\"pad-snd\" "
        "aria-pressed=\"true\">SND ON</button>"
        "</div>"
        "<div class=\"pad-group\">"
        "<button type=\"button\" class=\"pad-btn\" id=\"pad-b\">BACK</button>"
        "<button type=\"button\" class=\"pad-btn go\" id=\"pad-a\">PICK</button>"
        "<button type=\"button\" class=\"pad-btn danger\" id=\"pad-end\" hidden>END</button>"
        "</div></div>"

        "<div class=\"toast\" id=\"toast\" hidden></div>"

        "<section class=\"hud-link\"><label>Glasses stream link (paste once into "
        "the MemoMind relay)<input id=\"hud-link\" readonly></label>"
        "<p class=\"small\">The menu, confidence, and coach cues follow this link "
        "automatically — no per-session copying.</p></section>"
        + warning +
        "</main>"
        "<footer class=\"disclaimer\">PREPARATION AID ONLY — NOT LEGAL ADVICE. "
        "ProSe helps you practice and prepare; it does not determine what the "
        "law requires and does not replace a lawyer.</footer>"
        "</div>"
        f"<script>{CONTROLLER_JS}</script></body></html>"
    )
