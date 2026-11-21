"""Тимчасовий інструмент: показати конкретні завдання черги повністю."""
import io
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

ids = sys.argv[1:]
home = r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE"
queue = json.load(io.open(home + r"\queue.json", encoding="utf-8"))

for task in queue.get("tasks", []):
    if ids and task.get("id") not in ids:
        continue
    print("=" * 100)
    print("id", task.get("id"), "| status", task.get("status"))
    print("text:", task.get("text"))
    print("result:", (task.get("result") or "")[:500])
    print("error:", task.get("error"))
    print("started", task.get("started_at"), "finished", task.get("finished_at"))
    for entry in task.get("history") or []:
        print("   %-11s | %s" % (entry.get("kind"), (entry.get("text") or "")[:150].replace("\n", " ")))
