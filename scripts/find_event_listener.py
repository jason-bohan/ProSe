"""Find use-suggestion event listener in debate_web.py."""

path = r"C:\repos\ProSe\prose\debate_web.py"
with open(path, encoding="utf-8", newline="") as f:
    content = f.read()

idx = content.find("use-suggestion")
if idx >= 0:
    print("Found 'use-suggestion' at index", idx)
    # Find the addEventListener after it
    idx2 = content.find("addEventListener", idx)
    if idx2 >= 0:
        print("Found addEventListener at", idx2)
        print("Context:")
        print(repr(content[idx2-100:idx2+300]))
    else:
        print("addEventListener not found after use-suggestion")
else:
    print("use-suggestion not found")
