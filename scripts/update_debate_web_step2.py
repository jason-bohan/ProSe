"""Patch debate_web.py steps 7-10: hear coach, buttons, controls."""

path = r"C:\repos\ProSe\prose\debate_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Step 7: Add hearCoach function and update useSuggestion
old7 = """  $('use-suggestion').addEventListener('click', () => {
    if (state) { $('reply').value = state.coach.suggestion; $('reply').focus(); }
  });"""

new7 = """  function hearCoach() {
    if (!canSpeak || !state || !state.coach || !state.coach.suggestion) return;
    stopAudio();
    const utterance = new SpeechSynthesisUtterance(state.coach.suggestion);
    utterance.lang = 'en-US';
    const voice = getSelectedVoice();
    if (voice) utterance.voice = voice;
    speechSynthesis.speak(utterance);
  }
  $('use-suggestion').addEventListener('click', () => {
    if (state) { $('reply').value = state.coach.suggestion; $('reply').focus(); }
  });
  $('hear-coach').addEventListener('click', hearCoach);"""

content = content.replace(old7, new7, 1)

# Step 8: Add "Hear coach" button next to "Use suggestion"
old8 = '<button id="use-suggestion" type="button" disabled>Use this suggestion</button>'
new8 = '<button id="use-suggestion" type="button" disabled>Use this suggestion</button><button id="hear-coach" type="button" disabled>Hear coach</button>'

content = content.replace(old8, new8, 1)

# Step 9: Update controls to enable/disable hear-coach
old9 = "    $('use-suggestion').disabled = busy || !active || finished || !state;"
new9 = "    $('use-suggestion').disabled = busy || !active || finished || !state;\n    $('hear-coach').disabled = busy || !canSpeak || !state || !state.coach || !state.coach.suggestion;"

content = content.replace(old9, new9, 1)

# Step 10: Add populateVoiceDropdown call in controls()
old10 = "  function controls() {"
new10 = """  function controls() {
    populateVoiceDropdown();"""

content = content.replace(old10, new10, 1)

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)

print("debate_web.py steps 7-10 done")
