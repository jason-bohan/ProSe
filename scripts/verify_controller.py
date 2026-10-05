"""Verify controller_web.py has all voice management code."""

path = r"C:\repos\ProSe\prose\controller_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

checks = [
    "const voiceKey",
    "function loadVoices",
    "function getSelectedVoice",
    "function loadVoice",
    "function rememberVoice",
    "function populateVoiceDropdown",
]

for check in checks:
    if check in content:
        print(f"OK: {check}")
    else:
        print(f"MISSING: {check}")
