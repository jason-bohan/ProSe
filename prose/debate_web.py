"""Phone and desktop practice room; no glasses required."""

from __future__ import annotations

import html

from .debate import PERSONAS, TEMPERAMENTS

PRACTICE_CSS = """
.practice-intro{max-width:720px;margin-bottom:1.4rem;color:var(--g9)}
.practice-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr);gap:1.25rem;align-items:start}
.practice-grid .card{margin-top:0}.practice-grid h2{font-weight:700;font-size:1.15rem;margin:0 0 .8rem}
.practice-grid fieldset{border:0;padding:0;margin:0;min-width:0}
.practice-grid label{font-weight:400;text-transform:none}.practice-grid textarea{min-height:80px;font-family:inherit}
.practice-grid input[type=text]{font-family:inherit}.practice-grid .pair{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.practice-grid .row{margin-bottom:.8rem}.practice-grid .btn-row{flex-wrap:wrap}
.practice-grid [hidden]{display:none!important}.practice-grid button:disabled{opacity:.4;cursor:default}
.practice-grid :focus-visible{outline:2px solid var(--o);outline-offset:3px}
.practice-grid .eyebrow{font:700 11px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}
.practice-grid .coach-card{background:var(--k);border-color:var(--k);color:var(--tw);position:sticky;top:1rem}
.coach-card blockquote{margin:1rem 0;padding:1rem 1.15rem;border:1px solid #555;border-radius:1.15rem;
 border-bottom-left-radius:.3rem;background:#171719;font-size:1.15rem;font-weight:400;line-height:1.5;
 white-space:pre-wrap;overflow-wrap:anywhere}
.coach-card h3{text-transform:none;font-weight:700;margin-top:1.1rem;color:var(--tw)}.coach-card p{white-space:pre-wrap}
.coach-card .eyebrow{color:var(--o)}
.coach-card .small{color:#9a9a9a}.coach-card a{color:var(--tw)}
.coach-card button{background:var(--o);color:var(--w)}
.coach-card button:hover{background:#ff6a30;opacity:1}
.coach-card button:active{background:var(--tw);color:var(--k)}
.practice-grid .coach-foot{font-size:.8rem;color:#9a9a9a;border-top:1px solid #2a2a30;padding-top:1rem}
#practice-status{min-height:1.5rem;margin:.7rem 0;font-size:.9rem}#practice-status.error{color:#a21b22}
.practice-grid .conversation{max-height:520px;overflow-y:auto;overscroll-behavior:contain;padding-right:.3rem}
.practice-grid .bubble{width:fit-content;max-width:min(88%,42rem);padding:.8rem 1rem;margin:.75rem 0;
 border:1px solid var(--face2);border-radius:1.1rem;background:var(--w);box-shadow:0 3px 12px #0000000c}
.practice-grid .bubble.opponent{background:var(--face);border-color:var(--g3);border-bottom-left-radius:.3rem;margin-right:auto}
.practice-grid .bubble.you{border-color:var(--k);border-bottom-right-radius:.3rem;margin-left:auto}.practice-grid .bubble p{margin:.4rem 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
.practice-grid .bubble strong{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.practice-grid .small{font-size:.83rem;color:var(--g9)}.practice-grid .voice-toggle{display:flex;gap:.5rem;align-items:center;font-size:.85rem}
.practice-grid .topic-button{background:var(--w);color:var(--k);font-size:.78rem;border:1px solid var(--g3);padding:.4rem .65rem}
.practice-grid .topic-button:hover{background:var(--face)}
.practice-grid summary{font-weight:700}.practice-grid .empty{padding:2rem .5rem;text-align:center;color:var(--grey)}
@media(max-width:780px){.practice-grid{grid-template-columns:1fr}.practice-grid .coach-card{position:static;grid-row:1}.practice-grid .pair{grid-template-columns:1fr}.container{padding:1rem}.practice-grid .conversation{max-height:400px}}
"""

PRACTICE_JS = r"""
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canSpeak = 'speechSynthesis' in window;
  const storageKey = 'prose-debate-session';
  const modelKey = 'prose-debate-model';
  const voiceKey = 'prose-debate-voice';
  let voices = [];
  function loadVoices() {
    try { voices = speechSynthesis.getVoices(); } catch (_) { voices = []; }
  }
  function populateVoiceDropdown() {
    const sel = $('practice-voice');
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
    const sel = $('practice-voice');
    if (!sel) return;
    try { localStorage.setItem(voiceKey, sel.value); } catch (_) { /* Optional. */ }
  }
  function loadVoice() {
    try {
      const saved = localStorage.getItem(voiceKey);
      if (saved) {
        const sel = $('practice-voice');
        if (sel && Array.from(sel.options).some(o => o.value === saved)) sel.value = saved;
      }
    } catch (_) { /* Optional. */ }
  }
  function getSelectedVoice() {
    const sel = $('practice-voice');
    if (!sel || !sel.value) return null;
    return voices.find(v => v.name === sel.value) || null;
  }
  speechSynthesis.addEventListener('voiceschanged', loadVoices);
  loadVoices();
  loadVoice();
  let state = null, session = null, busy = false, ended = false, recognition = null;
  const notice = (text, error=false) => {
    $('practice-status').textContent = text;
    $('practice-status').classList.toggle('error', error);
  };
  function remember(value) {
    try { if (value) sessionStorage.setItem(storageKey, value); else sessionStorage.removeItem(storageKey); }
    catch (_) { /* Practice still works when storage is unavailable. */ }
  }
  function modelDetails() {
    const option = $('practice-model').selectedOptions[0];
    $('model-help').textContent = option ? option.dataset.description : '';
    if (!session && option) $('provider').textContent = 'AI: ' + option.dataset.model;
  }
  function rememberModel() {
    try { localStorage.setItem(modelKey, $('practice-model').value); } catch (_) { /* Optional. */ }
  }
  async function api(action, body) {
    const response = await fetch('/api/practice/' + action, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    let data;
    try { data = await response.json(); }
    catch (_) { data = null; }
    if (!response.ok) {
      const error = new Error(data && data.error || 'Practice request failed (HTTP ' + response.status + ').');
      error.status = response.status;
      throw error;
    }
    if (!data || typeof data !== 'object') throw new Error('Practice server returned an invalid response.');
    return data;
  }
  function controls() {
    populateVoiceDropdown();
    const active = Boolean(session), finished = ended || Boolean(state && state.complete);
    $('practice-settings').disabled = busy || active;
    $('practice-model').disabled = busy;
    $('practice-voice').disabled = busy || !canSpeak;
    $('practice-start').disabled = busy || active || $('practice-start').dataset.configured !== 'yes';
    $('practice-end').disabled = busy || !active;
    $('reply').disabled = busy || !active || finished;
    $('practice-send').disabled = busy || !active || finished || !state;
    $('use-suggestion').disabled = busy || !active || finished || !state;
    $('hear-coach').disabled = busy || !canSpeak || !state || !state.coach || !state.coach.suggestion;
    $('dictate').disabled = busy || !active || finished || !Speech;
    $('hear-opponent').disabled = busy || !canSpeak || !state || !state.messages.length;
    $('read-aloud').disabled = !canSpeak;
    $('reconnect').disabled = busy;
    $('download-debate').disabled = !state || busy;
    $('practice-setup').open = !active;
  }
  function render(next) {
    state = next; session = next.session_id; ended = false; remember(session);
    const c = next.config;
    for (const name of ['topic','position','persona','temperament','opponent_position','custom_persona','method']) {
      document.querySelector('[name="' + name + '"]').value = c[name];
    }
    $('practice-vocabulary').checked = c.vocabulary !== false;
    $('practice-legal-review').checked = Boolean(c.legal_review);
    $('practice-jurisdiction').value = c.jurisdiction || 'Unspecified';
    $('knowledge-pack').value = c.knowledge_pack || '';
    $('include-legal-context').checked = Boolean(c.include_legal_context);
    $('include-case-documents').checked = Boolean(c.include_case_documents);
    customFields();
    $('practice-summary').textContent = c.topic + ' · ' + c.temperament + ' opponent';
    $('round-label').textContent = 'Round ' + next.turn + ' / ' + next.max_turns;
    $('provider').textContent = 'AI: ' + next.model;
    $('practice-model').value = next.model_id;
    modelDetails(); rememberModel();
    $('coach-model').textContent = 'Suggestion from ' + (next.coach_model || next.model);
    const log = $('conversation'); log.replaceChildren();
    if (!next.messages.length) {
      const empty = document.createElement('p'); empty.className = 'empty';
      empty.textContent = 'Your coach has an opening ready. Edit it or write your own to begin.';
      log.append(empty);
    }
    for (const message of next.messages) {
      const item = document.createElement('article');
      item.className = 'bubble ' + (message.speaker === 'You' ? 'you' : 'opponent');
      const name = document.createElement('strong'); name.textContent = message.speaker;
      const text = document.createElement('p'); text.textContent = message.text;
      item.append(name, text); log.append(item);
    }
    log.scrollTop = log.scrollHeight;
    $('suggestion').textContent = next.coach.suggestion;
    $('coach-why').textContent = next.coach.why;
    $('coach-feedback').textContent = next.coach.feedback;
    $('feedback-section').hidden = !next.coach.feedback;
    $('coach-check').textContent = next.coach.check;
    $('check-section').hidden = !next.coach.check;
    $('listen-summary').textContent = next.coach.listening || '';
    $('topic-map').textContent = next.coach.topic_map || '';
    $('method-tip').textContent = next.coach.method_tip || '';
    $('learning-section').hidden = !next.coach.topic_map && !next.coach.method_tip;
    const words = next.target_words || [];
    $('focus-words').replaceChildren();
    for (const item of words) {
      const line = document.createElement('p');
      const link = document.createElement('a'); link.href = '/vocabulary?word=' + encodeURIComponent(item.word);
      link.target = '_blank'; link.rel = 'noopener'; link.textContent = item.word;
      line.append(link, ' — ' + item.definition); $('focus-words').append(line);
    }
    $('vocabulary-section').hidden = !words.length;
    $('vocabulary-feedback').textContent = next.coach.vocabulary_feedback || '';
    $('vocabulary-used').textContent = (next.words_used || []).length ? 'Words in your last reply: ' + next.words_used.join(', ') + '. Recall is reviewed separately.' : '';
    $('coach-label').textContent = next.turn ? 'Your next move' : 'Your opening';
    const review = next.coach.legal_review;
    $('legal-review-section').hidden = !review;
    $('legal-review-status').textContent = review ? review.message : '';
    $('legal-review-analysis').textContent = review && review.analysis || '';
    $('legal-review-details').textContent = review ? [
      review.question ? 'Question: ' + review.question : '',
      ...(review.uncertainties || []).map(text => 'To check: ' + text),
      (review.sources || []).length ? 'Supplied sources: ' + review.sources.map(s => s.title).join('; ') : '',
      'Specialist: ' + review.model
    ].filter(Boolean).join('\n') : '';
    $('reconnect').hidden = true;
    const passages = next.coach.research_sources || [];
    $('research-section').hidden = !c.knowledge_pack;
    $('research-note').textContent = next.coach.research_note || '';
    $('research-passages').replaceChildren();
    for (const s of passages) {
      const detail = document.createElement('details'), heading = document.createElement('summary');
      heading.textContent = (s.cited ? 'Referenced: ' : 'Supplied: ') + s.title;
      const meta = document.createElement('p'); meta.className = 'small';
      meta.textContent = s.id + ' · ' + s.category + ' · ' + s.edition;
      const passage = document.createElement('p'); passage.style.whiteSpace = 'pre-wrap'; passage.textContent = s.text;
      const link = document.createElement('a'); link.href = /^https?:\/\//.test(s.url) ? s.url : '/research'; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = s.kind === 'case' ? 'Case documents in Research' : 'Original publication';
      detail.append(heading, meta, passage, link); $('research-passages').append(detail);
    }
    controls();
  }
  function customFields() {
    const custom = $('persona').value === 'custom';
    $('custom-row').hidden = !custom; $('custom-persona').required = custom;
  }
  function stopAudio() {
    if (recognition) { const current = recognition; recognition = null; current.abort(); }
    $('dictate').textContent = 'Dictate reply';
    if (canSpeak) speechSynthesis.cancel();
  }
  function speakOpponent() {
    if (!canSpeak || !state || !state.messages.length) return;
    stopAudio();
    const utterance = new SpeechSynthesisUtterance(state.messages[state.messages.length - 1].text);
    utterance.lang = 'en-US';
    utterance.onerror = event => {
      if (!['interrupted','canceled'].includes(event.error)) notice('Read-aloud unavailable. The reply is shown in the conversation.', true);
    };
    speechSynthesis.speak(utterance);
  }
  $('practice-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy || session) return;
    const brief = Object.fromEntries(new FormData(event.target));
    brief.vocabulary = $('practice-vocabulary').checked;
    brief.model_id = $('practice-model').value;
    brief.legal_review = $('practice-legal-review').checked;
    brief.include_legal_context = $('include-legal-context').checked;
    brief.include_case_documents = $('include-case-documents').checked;
    brief.document_ids = Array.from(document.querySelectorAll('[name=document_ids]:checked'), x => x.value);
    busy = true; stopAudio(); controls(); notice('Your coach is preparing an opening…');
    try {
      render(await api('sessions', brief)); $('reply').value = '';
      notice('Opening ready. Use the suggestion or write your own.');
    } catch (error) { notice(error.message, true); }
    finally { busy = false; controls(); }
  });
  $('practice-model').addEventListener('change', async () => {
    modelDetails();
    if (!session) { rememberModel(); return; }
    if (busy || !state) return;
    const previous = state.model_id;
    busy = true; stopAudio(); controls(); notice('Switching AI model…');
    try {
      render(await api('model', {session_id:session, expected_turn:state.turn, model_id:$('practice-model').value}));
      notice('Model changed. Your conversation and draft are kept; the next reply uses ' + state.model + '.');
    } catch (error) {
      $('practice-model').value = previous; modelDetails(); notice(error.message, true);
      $('reconnect').hidden = false;
    } finally { busy = false; controls(); }
  });
  $('reply-form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = $('reply').value.trim();
    if (busy || !session || !state || !text || state.complete || ended) return;
    const previousTurn = state.turn;
    busy = true; stopAudio(); controls(); notice('Your opponent is responding, then your coach will suggest a reply…');
    try {
      render(await api('turn', {session_id:session, expected_turn:previousTurn, text}));
      $('reply').value = '';
      notice(state.complete ? '20 rounds complete. Download your conversation or start a new debate.' : 'Your turn.');
      if ($('read-aloud').checked) speakOpponent();
    } catch (error) {
      notice(error.message, true);
      try {
        const latest = await api('state', {session_id:session});
        render(latest);
        if (latest.turn > previousTurn) { $('reply').value = ''; notice('Your reply was received. Conversation restored.'); }
      } catch (syncError) {
        if (syncError.status === 404) { session = null; remember(null); ended = true; }
        else $('reconnect').hidden = false;
      }
    } finally { busy = false; controls(); }
  });
  $('use-suggestion').addEventListener('click', () => {
    if (state) { $('reply').value = state.coach.suggestion; $('reply').focus(); }
  });
  $('reply').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('reply-form').requestSubmit(); }
  });
  $('practice-end').addEventListener('click', async () => {
    if (!session || busy) return;
    busy = true; stopAudio(); controls();
    try {
      await api('stop', {session_id:session}); session = null; remember(null); ended = true;
      notice('Practice ended. You can download this conversation or start another.');
    } catch (error) { notice(error.message, true); }
    finally { busy = false; controls(); }
  });
  $('dictate').addEventListener('click', () => {
    if (recognition) { stopAudio(); notice('Dictation stopped. Review your reply before sending.'); return; }
    if (!Speech || busy) return;
    stopAudio();
    const r = new Speech(); recognition = r;
    r.lang = 'en-US'; r.continuous = true; r.interimResults = false;
    r.onresult = event => {
      if (recognition !== r) return;
      const words = [];
      for (let i=event.resultIndex; i<event.results.length; i++) if (event.results[i].isFinal) words.push(event.results[i][0].transcript);
      $('reply').value = ($('reply').value + ' ' + words.join(' ')).trim().slice(0,4000);
    };
    r.onerror = event => { if (recognition === r) notice('Dictation: ' + event.error + '. You can type your reply.', true); };
    r.onend = () => { if (recognition === r) { recognition = null; $('dictate').textContent = 'Dictate reply'; } };
    try { r.start(); $('dictate').textContent = 'Stop dictation'; notice('Listening. Review your words, then send.'); }
    catch (_) { recognition = null; notice('Microphone unavailable. You can type your reply.', true); }
  });
  $('hear-opponent').addEventListener('click', speakOpponent);
  $('read-aloud').addEventListener('change', () => { if (!$('read-aloud').checked && canSpeak) speechSynthesis.cancel(); });
  $('persona').addEventListener('change', customFields);
  const topics = {
    tariffs:['Should the government impose broad tariffs on imported goods?', 'I oppose broad tariffs because consumer costs and retaliation can outweigh their benefits.'],
    speech:['Should social media platforms moderate lawful but harmful content?', 'Platforms should have transparent moderation rules and a meaningful appeals process.'],
    transit:['Should our city invest more in public transportation?', 'Reliable public transit is worth public investment because it expands access to jobs and services.'],
    scouting:['What rules and review process should govern removing a youth Scout from a troop in Indiana?', 'I want the troop to identify the applicable written policy, explain its decision, and consider a constructive response before removing a Scout.']
  };
  for (const button of document.querySelectorAll('[data-topic]')) button.addEventListener('click', () => {
    const [topic, position] = topics[button.dataset.topic]; $('topic').value = topic; $('position').value = position;
    if (button.dataset.topic === 'scouting') {
      $('knowledge-pack').value = 'scouting'; $('practice-jurisdiction').value = 'Indiana';
      $('persona').value = 'custom'; $('custom-persona').value = 'A fictional troop committee member concerned about consistent rules, youth safety, and the effect of behavior on the troop. Defend the need for a fair, workable decision without inventing incidents or policies.'; customFields();
    } else $('knowledge-pack').value = '';
  });
  $('download-debate').addEventListener('click', () => {
    if (!state) return;
    const text = ['ProSe debate practice — fictional AI opponent', state.config.topic,
      'Your position: ' + state.config.position, 'Opponent: ' + state.config.persona + ' / ' + state.config.temperament,
      '', ...state.messages.map(m => m.speaker + ': ' + m.text + '\n'),
      'Coach feedback: ' + state.coach.feedback, 'Suggested next reply: ' + state.coach.suggestion,
      'Research note: ' + (state.coach.research_note || ''),
      ...(state.coach.research_sources || []).map(s => s.id + ' | ' + s.title + ' | ' + s.url + ' | ' + s.edition)].join('\n');
    const url = URL.createObjectURL(new Blob([text], {type:'text/plain;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'debate-practice.txt'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  async function restore() {
    if (!session || busy) return;
    busy = true; controls(); notice('Restoring practice…');
    try { render(await api('state', {session_id:session})); notice('Practice restored.'); }
    catch (error) {
      notice(error.message, true);
      if (error.status === 404) { session = null; remember(null); }
      else $('reconnect').hidden = false;
    } finally { busy = false; controls(); }
  }
  $('reconnect').addEventListener('click', restore);
  window.addEventListener('pagehide', stopAudio);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopAudio(); });
  try { session = sessionStorage.getItem(storageKey); } catch (_) { /* Optional session recovery. */ }
  try {
    const saved = localStorage.getItem(modelKey);
    if (Array.from($('practice-model').options).some(option => option.value === saved)) $('practice-model').value = saved;
  } catch (_) { /* Optional model preference. */ }
  if (!Speech) $('voice-help').textContent = 'Dictation is unavailable in this browser. Type your reply to practice.';
  customFields(); modelDetails(); controls(); if (session) restore();
  if (!session && new URLSearchParams(location.search).get('topic') === 'scouting') document.querySelector('[data-topic="scouting"]').click();
})();
"""


def render_practice_page(css: str, nav: str, status: dict, documents: list | None = None) -> str:
    def options(items: dict, selected: str) -> str:
        return "".join(f'<option value="{key}"{" selected" if key == selected else ""}>'
                       f'{html.escape(value[0])}</option>' for key, value in items.items())

    model = html.escape(status.get("model", "Model not configured"))
    configured = "yes" if status.get("configured") else "no"
    notice = html.escape(status.get("error", "Choose your topic and opponent to begin."))
    choices = "".join(
        f'<option value="{html.escape(item["id"], quote=True)}"'
        f' data-description="{html.escape(item["description"], quote=True)}"'
        f' data-model="{html.escape(item["model"], quote=True)}"'
        f'{" selected" if item["id"] == status.get("default_model_id") else ""}>'
        f'{html.escape(item["label"])}</option>' for item in status.get("choices", [])
    )
    warning = html.escape(status.get("configuration_warning", ""))
    specialist = status.get("legal_specialist", {})
    legal_disabled = "" if specialist.get("configured") else " disabled"
    legal_help = ("Your coach can ask Saul a legal question, then consider its review. Adds response time."
                  if specialist.get("configured") else "Legal specialist setup is not complete yet.")
    documents_html = "".join(
        f'<label class="voice-toggle"><input type="checkbox" name="document_ids" '
        f'value="{html.escape(doc.doc_id, quote=True)}">{html.escape(doc.name)}</label>'
        for doc in documents or []
    ) or '<p class="small">Import documents in Discovery to include excerpts.</p>'
    body = """
<p class="practice-intro">Build your argument before the real conversation. An AI opponent pushes back, while your private coach helps you find the words. Practice here on your phone or computer.</p>
<main id="main" class="practice-grid"><div>
<section class="card"><div class="row"><label for="practice-model">AI model</label><select id="practice-model" aria-describedby="model-help">__MODELS__</select><p id="model-help" class="small"></p><p class="small">Switch between turns to keep your conversation and draft. The selected model handles both opponent and coach.</p><p class="small">__MODEL_WARNING__</p></div>
<details id="practice-setup" open><summary id="practice-summary">Set up your debate</summary>
<form id="practice-form"><fieldset id="practice-settings">
<div class="row"><label for="topic">Topic or question</label><input id="topic" name="topic" type="text" maxlength="500" required placeholder="What do you want to debate?"></div>
<div class="btn-row"><span class="small">Try:</span><button type="button" class="topic-button" data-topic="tariffs">Tariffs</button><button type="button" class="topic-button" data-topic="speech">Online speech</button><button type="button" class="topic-button" data-topic="transit">Public transit</button><button type="button" class="topic-button" data-topic="scouting">Scout removal</button></div>
<div class="row"><label for="position">Your position</label><textarea id="position" name="position" maxlength="1000" required placeholder="What do you want to argue for?"></textarea></div>
<div class="pair"><div class="row"><label for="persona">Opponent outlook</label><select id="persona" name="persona">__PERSONAS__</select></div>
<div class="row"><label for="temperament">Temperament</label><select id="temperament" name="temperament">__TEMPERAMENTS__</select></div></div>
<div class="row" id="custom-row" hidden><label for="custom-persona">Describe your fictional opponent</label><textarea id="custom-persona" name="custom_persona" maxlength="1000" placeholder="A skeptical city council member who cares about budgets…"></textarea></div>
<div class="row"><label for="opponent-position">Opponent's position (optional)</label><input id="opponent-position" name="opponent_position" type="text" maxlength="1000" placeholder="Leave blank for the AI to choose a counterposition"></div>
<div class="row"><label for="practice-method">Coaching exercise</label><select id="practice-method" name="method"><option value="listening">Listen and map the disagreement · Bo Seo inspired</option><option value="structure">State → Support → Explain → Conclude</option><option value="free">Free debate</option></select></div>
<label class="voice-toggle"><input id="practice-vocabulary" name="vocabulary" type="checkbox" checked> Practice my vocabulary focus words</label><p class="small">Select words in your <a href="/vocabulary" target="_blank" rel="noopener">vocabulary notebook</a> before starting. Your coach helps you use them naturally.</p>
<div class="row"><label for="knowledge-pack">Research library</label><select id="knowledge-pack" name="knowledge_pack"><option value="">No research pack</option><option value="scouting">Scouting America · national policy guides</option></select><p class="small">Searches your saved library for relevant passages each turn and supplies them to the opponent and coach. <a href="/research" target="_blank" rel="noopener">Browse sources and coverage</a>.</p></div>
<label class="voice-toggle"><input id="include-legal-context" type="checkbox"> Include legal reference material from the research pack</label><p class="small">Leave off for a guideline discussion. Statutes and cases have separate applicability limits.</p>
<label class="voice-toggle"><input id="include-case-documents" type="checkbox"> Include my imported case documents</label><p class="small">Relevant excerpts will be sent to your selected AI model, and Saul if consultation is enabled. Case documents may contain private information; check the selected provider before starting.</p>
<label class="voice-toggle"><input id="practice-legal-review" type="checkbox"__LEGAL_DISABLED__> Consult legal specialist (Saul)</label><p class="small">__LEGAL_HELP__</p>
<details><summary>Legal context and source excerpts</summary><div class="row"><label for="practice-jurisdiction">Jurisdiction</label><input id="practice-jurisdiction" name="jurisdiction" type="text" value="Unspecified" maxlength="160" placeholder="US federal, Indiana, or another jurisdiction"></div>
<div class="row"><label for="practice-rule">Applicable rule (optional)</label><textarea id="practice-rule" name="governing_rule" maxlength="6000" placeholder="Paste the rule text, citation, jurisdiction and date."></textarea></div><p class="small">Choose up to six documents. The first 3,000 characters of each are supplied to your coach and, when consulted, Saul. Excerpts are not live legal research.</p>__DOCUMENTS__</details>
<p class="small">Personas are fictional practice partners. Outlook sets their priorities; temperament sets how they argue.</p>
</fieldset><button id="practice-start" data-configured="__CONFIGURED__" type="submit">Start practice</button></form></details>
<div id="practice-status" role="status" aria-live="polite">__NOTICE__</div><button type="button" id="reconnect" hidden>Reconnect</button>
<div class="btn-row"><span id="round-label" class="small">Ready when you are</span><span id="provider" class="small">AI: __MODEL__</span></div></section>
<section class="card"><h2>The conversation</h2>
<div id="conversation" class="conversation" role="log" aria-live="polite" aria-relevant="additions"
aria-label="Debate conversation"><p class="empty">Choose a topic above. Your coach will suggest the first thing to say.</p></div>
<div class="btn-row"><label class="voice-toggle"><input id="read-aloud" type="checkbox"> Read opponent aloud</label><button type="button" id="hear-opponent" disabled>Hear opponent</button></div>
<form id="reply-form"><label for="reply">Your reply</label><textarea id="reply" maxlength="4000" required disabled placeholder="Use your coach's suggestion, edit it, or write your own…"></textarea>
<div class="btn-row"><button id="practice-send" type="submit" disabled>Send reply</button><button id="dictate" type="button" disabled>Dictate reply</button><span class="small">Ctrl / ⌘ + Enter to send</span></div></form>
<p class="small" id="voice-help">Dictation uses your browser's speech service, which may process audio remotely. Review your words before sending.</p>
<div class="btn-row"><button id="practice-end" type="button" disabled>End practice</button><button id="download-debate" type="button" disabled>Download conversation</button></div></section></div>
<aside class="card coach-card" aria-label="Private debate coach"><div class="eyebrow">Private coach</div><h2 id="coach-label">Find your next words</h2><p id="coach-model" class="small"></p>
<blockquote id="suggestion">Your opening suggestion will appear here.</blockquote><button id="use-suggestion" type="button" disabled>Use this suggestion</button><button id="hear-coach" type="button" disabled>Hear coach</button>
<p id="coach-why" class="small">You choose what to say. Suggestions go into your reply box for editing.</p>
<section id="feedback-section" hidden><h3>On your last reply</h3><p id="coach-feedback"></p></section>
<section id="check-section" hidden><h3>Worth checking</h3><p id="coach-check"></p></section>
<section id="learning-section" hidden><h3>Listen, map, respond</h3><p id="listen-summary"></p><p id="topic-map" class="small"></p><p id="method-tip"></p></section>
<section id="vocabulary-section" hidden><h3>Your focus words</h3><div id="focus-words" class="small"></div><p id="vocabulary-feedback"></p><p id="vocabulary-used" class="small"></p></section>
<section id="legal-review-section" hidden><h3>Legal specialist review</h3><p id="legal-review-status" class="small"></p><p id="legal-review-analysis"></p><p id="legal-review-details" class="small" style="white-space:pre-wrap"></p></section>
<section id="research-section" hidden><h3>Research passages</h3><p id="research-note" class="small"></p><div id="research-passages"></div></section>
<p class="coach-foot">Factual claims are not live-verified. Practice lasts up to 20 rounds; sessions expire after 30 idle minutes or a server restart.</p></aside></main>
"""
    for token, value in (("__PERSONAS__", options(PERSONAS, "maga")),
                         ("__TEMPERAMENTS__", options(TEMPERAMENTS, "stubborn")),
                         ("__MODEL__", model), ("__CONFIGURED__", configured),
                         ("__MODELS__", choices), ("__MODEL_WARNING__", warning),
                         ("__LEGAL_DISABLED__", legal_disabled), ("__LEGAL_HELP__", legal_help),
                         ("__DOCUMENTS__", documents_html),
                         ("__NOTICE__", notice)):
        body = body.replace(token, value)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Debate practice · LexGlasses</title><style>{css}{PRACTICE_CSS}</style>'
            f'</head><body><div class="container"><header class="header"><div>'
            f'<h1>Debate practice</h1><div class="badge">An opponent. A coach. Your voice.</div>'
            f'</div>{nav}</header>{body}'
            f'<footer>DISCLAIMER: practice transcripts and suggestions are '
            f'simulation only. Not legal advice; not for filing.</footer>'
            f'</div><script>{PRACTICE_JS}</script></body></html>')
