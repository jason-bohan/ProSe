"""Patch controller_web.py to add voice selection for dictation, hear opponent, and coach."""

path = r"C:\repos\ProSe\prose\controller_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Step 1: Add voice management code after KEY definition
old1 = "  const KEY = 'prose-hud-session';"
new1 = """  const KEY = 'prose-hud-session';
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
  speechSynthesis.addEventListener('voiceschanged', loadVoices);
  loadVoices();
  loadVoice();"""

content = content.replace(old1, new1, 1)

# Step 2: Update hearOpponent to use selected voice
old2 = """function hearOpponent() {
  if (!state || !state.messages.length || !window.speechSynthesis) return;
  const last = [...state.messages].reverse().find(m => m.speaker !== 'You');
  if (!last) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(last.text);
  utter.rate = 1.02; speechSynthesis.speak(utter);
}"""

new2 = """function hearOpponent() {
  if (!state || !state.messages.length || !window.speechSynthesis) return;
  const last = [...state.messages].reverse().find(m => m.speaker !== 'You');
  if (!last) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(last.text);
  utter.rate = 1.02;
  const voice = getSelectedVoice();
  if (voice) utter.voice = voice;
  speechSynthesis.speak(utter);
}"""

content = content.replace(old2, new2, 1)

# Step 3: Update dictate() to use selected voice
old3 = """function dictate() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice dictation is not available here.'); return; }
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.lang = 'en-US'; rec.interimResults = true;"""

new3 = """function dictate() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice dictation is not available here.'); return; }
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.lang = 'en-US'; rec.interimResults = true;
  const voice = getSelectedVoice();
  if (voice) rec.voice = voice;"""

content = content.replace(old3, new3, 1)

# Step 4: Add hearCoach function
old4 = "function useSuggestion() {"
new4 = """function hearCoach() {
  if (!state || !state.coach || !state.coach.suggestion || !window.speechSynthesis) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(state.coach.suggestion);
  utter.rate = 1.02;
  const voice = getSelectedVoice();
  if (voice) utter.voice = voice;
  speechSynthesis.speak(utter);
}
function useSuggestion() {"""

content = content.replace(old4, new4, 1)

# Step 5: Add populateVoiceDropdown in DOMContentLoaded
old5 = "  padState();"
new5 = """  padState();
  populateVoiceDropdown();"""

content = content.replace(old5, new5, 1)

# Step 6: Add event listener for voice change
old6 = "  padState();"
new6 = """  padState();
  $('hud-voice').addEventListener('change', rememberVoice);"""

content = content.replace(old6, new6, 1)

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)

print("controller_web.py steps 1-6 done")
