"""Add hear-coach-btn event listener and disabled state to controller_web.py JS."""

path = r"C:\repos\ProSe\prose\controller_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

# Add event listener for hear-coach-btn
old = "  $('use-suggestion').addEventListener('click', useSuggestion);"
new = """  $('use-suggestion').addEventListener('click', useSuggestion);
  $('hear-coach-btn').addEventListener('click', hearCoach);"""

if old in content:
    content = content.replace(old, new, 1)
    print("Hear coach event listener added")
else:
    print("Event listener pattern not found")

# Add disabled state for hear-coach-btn in renderFight
old2 = "  $('use-suggestion').disabled = busy || !coach.suggestion;"
new2 = """  $('use-suggestion').disabled = busy || !coach.suggestion;
  $('hear-coach-btn').disabled = busy || !coach.suggestion || !window.speechSynthesis;"""

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("Hear coach disabled state added")
else:
    print("Disabled state pattern not found")

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)
