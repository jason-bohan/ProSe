"""Add voice selector to controller_web.py HTML."""

path = r"C:\repos\ProSe\prose\controller_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Add voice selector after AI model label
old = '"<label>AI model<select id=\\"f-model\\">" + models + "</select></label>"'
new = '"<label>AI model<select id=\\"f-model\\">" + models + "</select></label>"\n        "<label>Voice<select id=\\"hud-voice\\"><option value=\\"\\">(Browser default)</option></select></label><p class=\\"small\\">Select a voice for dictation and read-aloud. Changes apply to the next session.</p>"'

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print("Voice selector added to controller HTML")
else:
    print("Pattern not found")
