"""Тимчасовий інструмент: скільки разів агент переписував ті самі файли."""
import io
import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

home = r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE"
queue = json.load(io.open(home + r"\queue.json", encoding="utf-8"))
tasks = queue.get("tasks", [])

writes = Counter()
runs = Counter()
for task in tasks:
    for entry in task.get("history") or []:
        text = entry.get("text") or ""
        if entry.get("kind") != "tool":
            continue
        match = re.match(r"write_file\(path=([^,)]+)", text)
        if match:
            writes[match.group(1)] += 1
        match = re.match(r"run_command\(command=([^)]*)", text)
        if match:
            runs[match.group(1)] += 1

print("Записів файлів (усі задачі черги):")
for path, count in writes.most_common():
    print("  %2d x %s" % (count, path))
print("\nКоманди:")
for cmd, count in runs.most_common(6):
    print("  %2d x %s" % (count, cmd))
