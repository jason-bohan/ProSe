"""Debug: show exact content around use-suggestion in debate_web.py."""

path = r"C:\repos\ProSe\prose\debate_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Find use-suggestion
idx = content.find("use-suggestion")
if idx >= 0:
    print("Found at index", idx)
    print("Context (200 chars before):")
    print(repr(content[idx-200:idx+300]))
else:
    print("Not found")
