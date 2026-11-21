"""Тимчасовий інструмент: деталі останніх завдань черги."""
import io
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

home = r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE"
queue = json.load(io.open(home + r"\queue.json", encoding="utf-8"))
tasks = queue.get("tasks", [])
print("tasks:", len(tasks))
tasks_sorted = sorted(tasks, key=lambda t: t.get("created_at") or 0)
for t in tasks_sorted[-14:]:
    print("=" * 100)
    print("num", t.get("number"), "id", t.get("id"), "status", t.get("status"))
    print("created", t.get("created_at"), "started", t.get("started_at"), "finished", t.get("finished_at"))
    print("origin", t.get("origin"), "skill", t.get("skill"), "attempts", t.get("attempts"), "depends_on", t.get("depends_on"))
    print("text:", (t.get("text") or "")[:300].replace("\n", " "))
    print("goal:", (t.get("goal") or "")[:200])
    print("error:", t.get("error"), "result:", (t.get("result") or "")[:200].replace("\n", " "))
    print("files_changed:", t.get("files_changed"))
    hist = t.get("history") or []
    print("history len", len(hist))
    seen = {}
    for h in hist[-25:]:
        key = (h.get("kind"), (h.get("text") or "")[:90])
        seen[key] = seen.get(key, 0) + 1
        print("   ", h.get("kind"), "|", (h.get("text") or "")[:160].replace("\n", " "))
    print("dups:", {k: v for k, v in seen.items() if v > 1})
