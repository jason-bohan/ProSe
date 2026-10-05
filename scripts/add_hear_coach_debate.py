"""Add hearCoach function to debate_web.py."""

path = r"C:\repos\ProSe\prose\debate_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Add hearCoach function before use-suggestion event listener
old = """  $('use-suggestion').addEventListener('click', () => {
    if (state) { $('reply').value = state.coach.suggestion; $('reply').focus(); }
  });
  $('hear-coach').addEventListener('click', hearCoach);"""

new = """  function hearCoach() {
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

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print("hearCoach function added to debate_web.py")
else:
    print("Pattern not found")
