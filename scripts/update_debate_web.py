"""Patch debate_web.py to add voice selection for dictation, read-aloud, and coach."""


path = r"C:\repos\ProSe\prose\debate_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Step 1: Add voice management code after modelKey
old1 = "  const modelKey = 'prose-debate-model';"
new1 = """  const modelKey = 'prose-debate-model';
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
  loadVoice();"""

content = content.replace(old1, new1, 1)

# Step 2: Update speakOpponent to use selected voice
old2 = """  function speakOpponent() {
    if (!canSpeak || !state || !state.messages.length) return;
    stopAudio();
    const utterance = new SpeechSynthesisUtterance(state.messages[state.messages.length - 1].text);
    utterance.lang = 'en-US';
    utterance.onerror = event => {
      if (!['interrupted','canceled'].includes(event.error)) notice('Read-aloud unavailable. The reply is shown in the conversation.', true);
    };
    speechSynthesis.speak(utterance);
  }"""

new2 = """  function speakOpponent() {
    if (!canSpeak || !state || !state.messages.length) return;
    stopAudio();
    const utterance = new SpeechSynthesisUtterance(state.messages[state.messages.length - 1].text);
    utterance.lang = 'en-US';
    const voice = getSelectedVoice();
    if (voice) utterance.voice = voice;
    utterance.onerror = event => {
      if (!['interrupted','canceled'].includes(event.error)) notice('Read-aloud unavailable. The reply is shown in the conversation.', true);
    };
    speechSynthesis.speak(utterance);
  }"""

content = content.replace(old2, new2, 1)

# Step 3: Update dictate() to use selected voice
old3 = """    if (!Speech || busy) return;
    stopAudio();
    recognition = new Speech();
    recognition.lang = 'en-US';
    recognition.interimResults = true;"""

new3 = """    if (!Speech || busy) return;
    stopAudio();
    recognition = new Speech();
    recognition.lang = 'en-US';
    recognition.interimResults = true;
    const voice = getSelectedVoice();
    if (voice) recognition.voice = voice;"""

content = content.replace(old3, new3, 1)

# Step 4: Add voice selector HTML after practice-model row
old4 = '  <div class="row"><label for="practice-model">AI model</label><select id="practice-model" name="model">__MODELS__</select><p class="small" id="model-help"></p></div>'
new4 = '  <div class="row"><label for="practice-model">AI model</label><select id="practice-model" name="model">__MODELS__</select><p class="small" id="model-help"></p></div><div class="row"><label for="practice-voice">Voice</label><select id="practice-voice"><option value="">(Browser default)</option></select><p class="small">Select a voice for dictation and read-aloud. Changes apply to the next session.</p></div>'

content = content.replace(old4, new4, 1)

# Step 5: Update controls() to enable/disable voice selector
old5 = "    $('practice-model').disabled = busy;"
new5 = "    $('practice-model').disabled = busy;\n    $('practice-voice').disabled = busy || !canSpeak;"

content = content.replace(old5, new5, 1)

# Step 6: Add rememberVoice call after rememberModel
old6 = """  function rememberModel() {
    try { localStorage.setItem(modelKey, $('practice-model').value); } catch (_) { /* Optional. */ }
  }"""

new6 = """  function rememberModel() {
    try { localStorage.setItem(modelKey, $('practice-model').value); } catch (_) { /* Optional. */ }
  }
  $('practice-voice').addEventListener('change', rememberVoice);"""

content = content.replace(old6, new6, 1)

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)

print("debate_web.py steps 1-6 done")
