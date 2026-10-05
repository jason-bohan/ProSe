"""Add 'Hear coach' button to controller_web.py HTML."""

path = r"C:\repos\ProSe\prose\controller_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Add 'Hear coach' button next to 'Use suggestion'
old = '"<button type=\\"button\\" class=\\"ghost\\" id=\\"use-suggestion\\">Use suggestion</button>"'
new = '"<button type=\\"button\\" class=\\"ghost\\" id=\\"use-suggestion\\">Use suggestion</button>"\n        "<button type=\\"button\\" class=\\"ghost\\" id=\\"hear-coach-btn\\">Hear coach</button>"'

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print("Hear coach button added to controller HTML")
else:
    print("Pattern not found")
