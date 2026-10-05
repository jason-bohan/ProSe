"""Add voice management code to controller_web.py."""

path = r"C:\repos\ProSe\prose\controller_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Add voice management code after KEY definition
old = "const KEY = 'prose.controller.session';"
new = """const KEY = 'prose.controller.session';
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

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print("Voice management code added to controller_web.py")
else:
    print("Pattern not found")
