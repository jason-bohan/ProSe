"""Companion controls and session registry for the live reasoning HUD."""

from __future__ import annotations

import html
import secrets
import threading
import time

from .copilot import (
    CopilotError,
    CopilotSession,
    ModelCoach,
    SessionConfig,
    selected_sources,
)
from .legal_specialist import ConsultingCoach
from .model_choices import ModelChoices


class CopilotHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, CopilotSession] = {}
        self.models = ModelChoices()

    def status(self) -> dict:
        return self.models.status()

    def create(self, data: dict, documents: list) -> tuple[str, CopilotSession]:
        config = SessionConfig.from_dict(data)
        sources = selected_sources(data, documents, litigation=config.mode == "litigation")
        _, settings = self.models.resolve(data.get("model_id"))
        coach = ModelCoach(settings)
        if config.legal_review:
            coach = ConsultingCoach(coach, ModelCoach(self.models.specialist(),
                                                     max_completion_tokens=900))
        with self._lock:
            for key, session in list(self._sessions.items()):
                if session.closed or time.monotonic() - session.last_activity > 1800:
                    session.close()
                    del self._sessions[key]
            if len(self._sessions) >= 8:
                raise CopilotError("Eight sessions are already active; stop one before starting.")
            session_id = secrets.token_urlsafe(24)
            session = CopilotSession(config, coach, tuple(sources))
            self._sessions[session_id] = session
            return session_id, session

    def get(self, session_id: str) -> CopilotSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.closed:
                raise KeyError("session not found or stopped")
            if time.monotonic() - session.last_activity > 1800:
                session.close()
                del self._sessions[session_id]
                raise KeyError("session expired after 30 minutes without a transcript")
            return session

    def apply_tone(self, tone: dict, mode: str | None = None) -> int:
        """Best-effort: push one mode's tone dict to its open sessions; returns the count."""
        with self._lock:
            sessions = [s for s in self._sessions.values()
                        if mode is None or s.config.mode == mode]
        applied = 0
        for session in sessions:
            try:
                session.set_tone(tone)
                applied += 1
            except ValueError:
                continue  # closed between the snapshot and the write
        return applied

    def stop(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close()

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()


COPILOT_CSS = """
.coach-grid{display:grid;grid-template-columns:minmax(280px,1fr) minmax(300px,1.3fr);gap:1.25rem}
.coach-grid .card{margin:0 0 1.25rem}.lens{background:var(--k);color:var(--tw);
min-height:230px;padding:1.5rem;border:1px solid var(--k);border-radius:1.25rem}
.lens-label{font:12px ui-monospace,monospace;letter-spacing:.1em;color:var(--o)}
.lens h3{font-size:1.3rem;font-weight:600;line-height:1.4;margin:1rem 0 .55rem;
padding:.85rem 1rem;border:1px solid #45454a;border-radius:1rem;border-bottom-left-radius:.25rem;
background:#171719;color:var(--tw);white-space:pre-wrap;overflow-wrap:anywhere}
.lens p{font-size:.95rem;line-height:1.5;color:#c7c7cc;white-space:pre-wrap;overflow-wrap:anywhere}
.coach-help{font-size:.85rem;color:var(--g9)}
.coach-grid label.check{display:flex;gap:.5rem;align-items:center;text-transform:none}
.coach-grid button:disabled{opacity:.4;cursor:default}.coach-grid [hidden]{display:none}
.transcript-log{display:flex;flex-direction:column;gap:.5rem;max-height:300px;overflow:auto;
padding:.35rem .15rem;font-size:.9rem}
.transcript-log .turn{width:fit-content;max-width:88%;padding:.65rem .85rem;border:1px solid var(--g1);
border-radius:1rem;border-bottom-left-radius:.25rem;background:#101812;overflow-wrap:anywhere}
.transcript-log .turn strong{display:block;margin-bottom:.2rem;color:var(--o);font-size:.72rem;letter-spacing:.04em;text-transform:uppercase}
.transcript-log .turn p{margin:0;line-height:1.45;white-space:pre-wrap}
.source-list a{display:block}.coach-grid :focus-visible{outline:2px solid var(--o);outline-offset:3px}
 .coach-grid textarea.short{min-height:85px}.coach-grid .row-pair{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
 .matrix{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
 .xy{display:grid;gap:.35rem;min-width:0}
 .xy-head{font-size:.75rem;letter-spacing:.05em;color:var(--g9)}
 .xy-grid{position:relative;aspect-ratio:1;border:1px solid var(--g1);border-radius:12px;
  background:#0c0c0c;touch-action:none;cursor:crosshair;overflow:hidden;
  background-image:repeating-linear-gradient(0deg,transparent 0 calc(25% - 1px),
  #1e1e1e calc(25% - 1px) 25%),repeating-linear-gradient(90deg,transparent 0 calc(25% - 1px),
  #1e1e1e calc(25% - 1px) 25%)}
 .xy-grid::before{content:"";position:absolute;left:0;right:0;top:var(--y,50%);height:1px;
  background:#ffffff26;pointer-events:none}
 .xy-grid::after{content:"";position:absolute;top:0;bottom:0;left:var(--x,50%);width:1px;
  background:#ffffff26;pointer-events:none}
 .xy-dot{position:absolute;width:.95rem;height:.95rem;border-radius:50%;background:var(--o);
  left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:none;
  box-shadow:0 0 0 2px #00000099,0 0 8px #ff5a2488}
 .xy:active .xy-grid{border-color:var(--o)}
 .xy-val{font:12px ui-monospace,monospace;color:var(--g)}
 #tone-controls:disabled .xy-grid{opacity:.45;cursor:default}
 @media(max-width:760px){.coach-grid{grid-template-columns:1fr}.container{padding:1rem}}
 """

COPILOT_JS = r"""
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let session = null, stream = null, lastSeq = 0, lastTurn = 0, recognition = null;
  let starting = false, stopping = false, expiry = null, posting = false;
  const TRAITS = {debate: ['humor', 'rhetoric', 'attack', 'listening'],
                  litigation: ['directness', 'formality', 'encouragement', 'urgency']};
  let tone = {debate: {humor: 2, rhetoric: 2, attack: 2, listening: 2},
              litigation: {directness: 2, formality: 2, encouragement: 2, urgency: 2}};
  let tonePoles = {debate: {}, litigation: {}};
  let toneMode = 'debate', toneTimer = null;
  function adoptTone(snap) {
    if (!snap) return;
    if (snap.tones) tone = snap.tones;
    if (snap.tone_poles) tonePoles = snap.tone_poles;
  }
  const notice = text => { $('notice').textContent = text; };
  async function api(path, data) {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(data)});
    let result;
    try { result = await response.json(); } catch (_) { result = null; }
    if (!response.ok) throw new Error(result && result.error ||
      'Live coach request failed (HTTP ' + response.status + ').');
    if (!result || typeof result !== 'object') throw new Error('Live coach returned an invalid response.');
    return result;
  }
  const voiceKey = 'prose-voice';
  const legacyVoiceKeys = ['prose-hud-voice', 'prose-debate-voice'];
  let voices = [];
  let lastCue = '';
  function loadVoices() {
    try { voices = speechSynthesis.getVoices(); } catch (_) { voices = []; }
  }
  function populateVoiceDropdown() {
    const sel = $('copilot-voice');
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
    const sel = $('copilot-voice');
    if (!sel) return;
    try { localStorage.setItem(voiceKey, sel.value); } catch (_) { /* Optional. */ }
  }
  function loadVoice() {
    try {
      const saved = localStorage.getItem(voiceKey)
        || legacyVoiceKeys.map(key => localStorage.getItem(key)).find(Boolean);
      if (saved) {
        const sel = $('copilot-voice');
        if (sel && Array.from(sel.options).some(o => o.value === saved)) sel.value = saved;
      }
    } catch (_) { /* Optional. */ }
  }
  function getSelectedVoice() {
    const sel = $('copilot-voice');
    if (!sel || !sel.value) return null;
    return voices.find(v => v.name === sel.value) || null;
  }
  function refreshVoices() {
    loadVoices();
    populateVoiceDropdown();
    loadVoice();
  }
  if ('speechSynthesis' in window) {
    speechSynthesis.addEventListener('voiceschanged', refreshVoices);
    refreshVoices();
  }
  $('copilot-voice').addEventListener('change', rememberVoice);
  function hearCue() {
    if (!('speechSynthesis' in window) || !lastCue) return;
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(lastCue);
    utterance.lang = 'en-US';
    const voice = getSelectedVoice();
    if (voice) { utterance.voice = voice; utterance.lang = voice.lang; }
    utterance.onerror = event => {
      if (!['interrupted', 'canceled'].includes(event.error)) {
        notice('Read-aloud unavailable. The cue is shown in the glasses preview.');
      }
    };
    speechSynthesis.speak(utterance);
  }
  $('hear-cue').addEventListener('click', hearCue);
  function renderTone() {
    const traits = TRAITS[toneMode];
    const values = tone[toneMode];
    const labels = tonePoles[toneMode] || {};
    $('tone-mode-label').textContent = toneMode;
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
        xl[0] + ' \u2194 ' + xl[1] + ' \u00d7 ' + yl[0] + ' \u2194 ' + yl[1];
      $(pair[0] + '-val').textContent =
        'x ' + values[fx] + '/4 \u00b7 y ' + values[fy] + '/4';
    }
  }
  async function syncTone() {
    if (!session) return;
    try {
      await api('/api/hud/menu', {action: 'tone', mode: toneMode,
        tone: Object.assign({}, tone[toneMode])});
    }
    catch (err) { notice(err.message); }
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
      if ($('tone-controls').disabled) return;
      const rect = grid.getBoundingClientRect();
      const px = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const py = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
      const nx = Math.round(px * 4);
      const ny = 4 - Math.round(py * 4);
      const fx = el.dataset.x, fy = el.dataset.y;
      const values = tone[toneMode];
      if (values[fx] !== nx || values[fy] !== ny) {
        values[fx] = nx; values[fy] = ny;
        renderTone(); scheduleToneSync();
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
  function clearCue(text) {
    clearTimeout(expiry);
    lastCue = '';
    $('hear-cue').disabled = true;
    $('cue-kind').textContent = 'LISTENING'; $('cue').textContent = text;
    $('say').textContent = ''; $('rationale').textContent = '';
    $('question').textContent = ''; $('caveat').textContent = '';
    $('sources').replaceChildren();
    $('specialist-review').hidden = true;
    $('specialist-status').textContent = ''; $('specialist-analysis').textContent = '';
    $('specialist-details').textContent = '';
  }
  function frame(f) {
    if (f.seq <= lastSeq) return;
    lastSeq = f.seq;
    if (f.turn_id > lastTurn) {
      lastTurn = f.turn_id;
      const line = document.createElement('article');
      line.className = 'turn';
      const speaker = document.createElement('strong');
      speaker.textContent = f.speaker;
      const text = document.createElement('p');
      text.textContent = f.transcript;
      line.append(speaker, text);
      $('transcript-log').append(line);
      while ($('transcript-log').children.length > 60) $('transcript-log').firstChild.remove();
      $('transcript-log').scrollTop = $('transcript-log').scrollHeight;
    }
    clearCue(f.status === 'thinking' ? 'Listening. Preparing a suggestion…' : 'Keep listening.');
    $('latency').textContent = f.latency_ms == null ? '' : (f.latency_ms/1000).toFixed(1) + 's response';
    if (f.error) { notice(f.error); return; }
    if (f.legal_review) {
      const review = f.legal_review;
      $('specialist-review').hidden = false;
      $('specialist-status').textContent = review.message;
      $('specialist-analysis').textContent = review.analysis || '';
      $('specialist-details').textContent = [
        review.question ? 'Question: ' + review.question : '',
        ...(review.uncertainties || []).map(text => 'To check: ' + text),
        (review.sources || []).length ? 'Supplied sources: ' + review.sources.map(s => s.title).join('; ') : '',
        'Specialist: ' + review.model
      ].filter(Boolean).join('\n');
    }
    if (!f.cue || f.cue.kind === 'none') return;
    const remaining = f.expires_at ? f.expires_at * 1000 - Date.now() : 15000;
    if (remaining <= 0) return;
    notice('');
    $('cue-kind').textContent = 'SUGGESTED · ' + f.cue.kind.toUpperCase();
    $('cue').textContent = f.cue.headline;
    $('say').textContent = f.cue.say;
    $('rationale').textContent = f.cue.rationale;
    $('question').textContent = f.cue.next_question ? 'Ask next: ' + f.cue.next_question : '';
    $('caveat').textContent = f.cue.caveat;
    lastCue = f.cue.say || f.cue.headline || '';
    $('hear-cue').disabled = !lastCue;
    for (const source of f.cue.sources) {
      const item = document.createElement(source.url ? 'a' : 'span');
      item.textContent = source.title;
      if (source.url) { item.href = source.url; item.target = '_blank'; item.rel = 'noopener noreferrer'; }
      $('sources').append(item, document.createElement('br'));
    }
    expiry = setTimeout(() => clearCue('Keep listening.'), remaining);
  }
  function controls(active) {
    $('settings').disabled = active;
    $('start').disabled = active || starting || stopping;
    $('stop').disabled = !active || stopping;
    $('send').disabled = !active || posting;
    $('mic').disabled = !active || !Speech;
    $('tone-controls').disabled = !active;
  }
  $('config-form').addEventListener('submit', async event => {
    event.preventDefault(); if (session || starting || stopping) return;
    starting = true; controls(false); notice('Starting session…');
    const data = Object.fromEntries(new FormData(event.target));
    data.document_ids = Array.from(document.querySelectorAll('[name=document_ids]:checked'), x => x.value);
    data.legal_review = $('legal-review').checked;
    try {
      const result = await api('/api/copilot/sessions', data);
      session = result.session_id; lastSeq = lastTurn = 0;
      $('memo-link').value = location.origin + '/api/copilot/events?view=glasses&session_id=' + encodeURIComponent(session);
      $('transcript-log').replaceChildren(); clearCue('Ready. Add a transcript turn.');
      toneMode = data.mode;
      try { adoptTone(await (await fetch('/api/hud/menu')).json()); } catch (_) {}
      renderTone();
      const expected = session;
      stream = new EventSource('/api/copilot/events?session_id=' + encodeURIComponent(session));
      stream.addEventListener('frame', event => {
        if (session !== expected) return;
        try { frame(JSON.parse(event.data)); }
        catch (_) { notice('Received an unreadable live update. Reconnecting…'); }
      });
      stream.addEventListener('stopped', () => { if (session === expected) stopSession(); });
      stream.onopen = () => { if (session === expected) notice(''); };
      stream.onerror = () => { if (session === expected) { clearCue('Connection interrupted.'); notice('Reconnecting to the live session…'); } };
      notice('');
    } catch (err) { notice(err.message); }
    finally { starting = false; controls(!!session); }
  });
  async function stopSession() {
    if (stopping) return;
    stopping = true;
    const previous = session; session = null;
    $('memo-link').value = '';
    stopMic(); if (stream) stream.close(); stream = null;
    clearCue('Session stopped.'); controls(false);
    try { if (previous) await api('/api/copilot/stop', {session_id:previous}); }
    catch (err) { notice(err.message); }
    finally { stopping = false; controls(false); }
  }
  $('stop').addEventListener('click', stopSession);
  async function sendTurn(text, speaker) {
    const expected = session;
    if (!expected || !text.trim()) return false;
    try {
      const result = await api('/api/copilot/turn', {session_id:expected, text, speaker});
      if (session === expected) frame(result.frame);
      return true;
    } catch (err) { notice(err.message); return false; }
  }
  $('turn-form').addEventListener('submit', async event => {
    event.preventDefault(); if (posting) return;
    posting = true; controls(!!session);
    const text = $('utterance').value;
    try { if (await sendTurn(text, $('speaker').value)) { if ($('utterance').value === text) $('utterance').value = ''; } }
    finally { posting = false; controls(!!session); }
  });
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  function stopMic() { if (recognition) recognition.abort(); recognition = null; $('mic').textContent = 'Start microphone'; }
  $('mic').addEventListener('click', () => {
    if (recognition) { stopMic(); return; }
    if (!Speech || !session) return;
    const expected = session, rec = new Speech(); recognition = rec;
    rec.continuous = true; rec.interimResults = false;
    const voice = getSelectedVoice();
    rec.lang = voice && voice.lang ? voice.lang : 'en-US';
    rec.onresult = event => {
      for (let i=event.resultIndex; i<event.results.length; i++) {
        if (event.results[i].isFinal && session === expected) {
          sendTurn(event.results[i][0].transcript, $('speaker').value);
        }
      }
    };
    rec.onerror = event => notice('Microphone: ' + event.error + '. You can still paste transcript turns.');
    rec.onend = () => { if (recognition === rec) { recognition = null; $('mic').textContent = 'Start microphone'; } };
    try { rec.start(); $('mic').textContent = 'Stop microphone'; }
    catch (err) { stopMic(); notice(err.message); }
  });
  $('mode').addEventListener('change', () => {
    const litigation = $('mode').value === 'litigation';
    $('court-fields').hidden = !litigation;
    toneMode = $('mode').value;
    renderTone();
  });
  window.addEventListener('pagehide', () => {
    stopMic(); if (stream) stream.close();
    if (session) fetch('/api/copilot/stop', {method:'POST', keepalive:true,
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:session})}).catch(() => {});
  });
  if (!Speech) $('mic-help').textContent = 'Browser speech recognition is unavailable. Paste turns here or use the Vosk microphone CLI.';
  bindPad('xy-a'); bindPad('xy-b');
  toneMode = $('mode').value;
  renderTone(); controls(false);
  fetch('/api/hud/menu').then(r => r.json()).then(adoptTone).catch(() => {})
    .finally(renderTone);
})();
"""


def render_copilot_page(css: str, nav: str, status: dict, documents: list) -> str:
    e = html.escape
    if status["configured"]:
        model = ("Starting sends transcript turns, notes, and selected excerpts to your "
                 "selected main model. With legal consultation enabled, focused excerpts "
                 "also go to the configured Saul model.")
    else:
        model = e(status["error"])
    choices = "".join(
        f'<label class="check"><input type="checkbox" name="document_ids" '
        f'value="{e(doc.doc_id)}">{e(doc.name)}</label>' for doc in documents
    ) or '<p class="coach-help">Add source documents in Discovery to use them here.</p>'
    models = "".join(
        f'<option value="{e(item["id"], quote=True)}"'
        f'{" selected" if item["id"] == status.get("default_model_id") else ""}>'
        f'{e(item["label"])}</option>' for item in status.get("choices", [])
    )
    legal_configured = status.get("legal_specialist", {}).get("configured", False)
    body = """<main id="main" class="coach-grid">
<div><section class="card"><h2>Session brief</h2>
<p class="coach-help">Set your position and context before you begin.</p>
<form id="config-form"><fieldset id="settings" style="border:0;padding:0;margin:0">
<div class="row"><label for="coach-model">Main AI coach</label><select id="coach-model" name="model_id">__MODELS__</select></div>
<label class="check"><input id="legal-review" type="checkbox" data-configured="__LEGAL_CONFIGURED__"__LEGAL_DISABLED__> Consult legal specialist (Saul)</label><p class="coach-help">The main coach can request a legal review, then revise its cue. Reviews add delay and must fit a 13-second live cue budget; longer reviews work best in debate practice.</p>
<div class="row-pair"><div class="row"><label for="mode">Mode</label>
<select id="mode" name="mode"><option value="debate">Debate coach</option><option value="litigation">Litigation coach</option></select></div>
<div class="row"><label for="role">Your role</label><input id="role" name="role" type="text" value="Participant" maxlength="120" required></div></div>
<div class="row"><label for="goal">Position or objective</label><textarea class="short" id="goal" name="goal" maxlength="1000" placeholder="What are you trying to establish or challenge?"></textarea></div>
<div id="court-fields" hidden><div class="row-pair"><div class="row"><label for="jurisdiction">Governing law</label>
<select id="jurisdiction" name="jurisdiction"><option>Unspecified</option><option>US federal</option><option>State / other</option></select></div>
<div class="row"><label for="stage">Stage</label><select id="stage" name="stage">
<option value="discussion">Discussion</option><option value="direct">Direct examination</option><option value="cross">Cross-examination</option><option value="argument">Argument</option><option value="deposition">Deposition</option></select></div></div>
<div class="row"><label for="governing_rule">Applicable rule and jurisdiction (optional)</label><textarea class="short" id="governing_rule" name="governing_rule" maxlength="6000" placeholder="For state or local law, include the jurisdiction, rule text, citation, and effective date."></textarea></div></div>
<div class="row"><label for="notes">Key facts and context</label><textarea id="notes" name="notes" maxlength="12000" placeholder="Known facts, disputed points, evidence already admitted, and questions to resolve."></textarea></div>
<details><summary>Source documents</summary><p class="coach-help">Choose up to six. The first 3,000 characters of each are included.</p>__DOCUMENTS__</details>
</fieldset><p class="coach-help">__MODEL__</p>
<div class="btn-row"><button id="start" type="submit">Start session</button><button id="stop" type="button" disabled>Stop</button></div></form>
</section><section class="card"><h2>Live transcript</h2>
<form id="turn-form"><div class="row"><label for="speaker">Current speaker</label><input id="speaker" type="text" value="Other speaker" maxlength="100" required></div>
<div class="row"><label for="utterance">What was said</label><textarea class="short" id="utterance" maxlength="4000" required placeholder="Paste a statement or use the microphone."></textarea></div>
<div class="row"><label for="copilot-voice">Voice</label><select id="copilot-voice"><option value="">(Browser default)</option></select></div>
<div class="btn-row"><button id="send" type="submit" disabled>Send turn</button><button id="mic" type="button" disabled>Start microphone</button></div></form>
<p class="coach-help" id="mic-help">Microphone transcription uses your browser's speech service and may send audio to its provider. Set the speaker manually. The voice you pick sets the dictation language and is used by Hear cue. The Vosk CLI supports local transcription.</p>
<div id="transcript-log" class="transcript-log" role="log" aria-live="polite"
aria-relevant="additions" aria-label="Recent transcript"></div></section>
<section class="card"><h2>Personality matrix <span class="dim" id="tone-mode-label">debate</span></h2>
<p class="coach-help">Drag a pad: each axis runs from its left/bottom pole to its right/top pole, 0 to 4. Follows the mode in Session brief. Style only: it never changes sourcing or evidentiary rules.</p>
<fieldset id="tone-controls" disabled style="border:0;padding:0;margin:0">
<div class="matrix">
<div class="xy" id="xy-a" data-x="humor" data-y="rhetoric">
<div class="xy-head"></div>
<div class="xy-grid"><div class="xy-dot"></div></div>
<div class="xy-val" id="xy-a-val"></div>
</div>
<div class="xy" id="xy-b" data-x="attack" data-y="listening">
<div class="xy-head"></div>
<div class="xy-grid"><div class="xy-dot"></div></div>
<div class="xy-val" id="xy-b-val"></div>
</div>
</div>
</fieldset></section></div>
<div><section class="card"><h2>Glasses preview <span class="dim" id="latency"></span></h2>
<div class="lens" role="status" aria-live="polite"><div class="lens-label" id="cue-kind">STANDBY</div><h3 id="cue">Listen. Think. Respond.</h3><p id="say"></p></div>
<p class="coach-help">One suggested cue at a time. New speech clears the previous cue; slow responses are discarded.</p>
<div class="btn-row"><button type="button" id="hear-cue" disabled>Hear cue</button></div>
<p id="notice" role="status" aria-live="polite"></p></section>
<section class="card"><h2>Companion notes</h2><p id="rationale"></p><p id="question"></p><p id="caveat" class="coach-help"></p><div id="sources" class="source-list"></div>
<p class="coach-help">Suggestions use your recent conversation and selected sources. Source links identify supplied material; they do not certify the model's interpretation.</p></section>
<section class="card" id="specialist-review" hidden><h2>Legal specialist review</h2><p id="specialist-status" class="coach-help"></p><p id="specialist-analysis"></p><p id="specialist-details" class="coach-help" style="white-space:pre-wrap"></p></section>
<section class="card"><h2>Connect the glasses</h2><p>Use the microphone CLI to send the same cue frames through your JSONL or WebSocket bridge.</p>
<label for="memo-link">MemoMind stream link</label><input id="memo-link" type="text" readonly style="width:100%;padding:.5rem" placeholder="Start a session to get a link">
<p class="coach-help">Paste this private session link into the MemoMind display relay. The phone must be able to reach this server. See integrations/memomind/README.md.</p>
<pre>prose listen --mic --model PATH_TO_VOSK_MODEL --assist debate --transport jsonl=live_hud.jsonl</pre>
<p class="coach-help">Use <code>--assist litigation</code> for courtroom cues. Configure your case with <code>--context case.json</code>. See SETUP.md.</p></section></div></main>"""
    body = (body.replace("__DOCUMENTS__", choices).replace("__MODEL__", model)
            .replace("__MODELS__", models)
            .replace("__LEGAL_CONFIGURED__", "yes" if legal_configured else "no")
            .replace("__LEGAL_DISABLED__", "" if legal_configured else " disabled"))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Live coach · LexGlasses</title><style>{css}{COPILOT_CSS}</style></head>'
            f'<body><div class="container"><header class="header"><div><h1>Live coach</h1>'
            f'<div class="badge">Litigation &amp; debate · AR companion</div></div>{nav}</header>'
            f'{body}<footer>AI suggestions for review. Not legal advice. Courtroom use depends '
            f'on the court’s device and recording rules.</footer></div>'
            f'<script>{COPILOT_JS}</script></body></html>')
