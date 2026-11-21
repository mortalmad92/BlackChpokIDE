"""Тимчасовий інструмент: чи ростиме черга, чи є дублікати завдань."""
import io
import json
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

home = r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE"
queue = json.load(io.open(home + r"\queue.json", encoding="utf-8"))
tasks = queue.get("tasks", [])

print("tasks:", len(tasks), "| statuses:", dict(Counter(t.get("status") for t in tasks)))
texts = Counter((t.get("text") or "")[:120] for t in tasks)
print("\nдублікати текстів завдань:")
for text, count in texts.items():
    if count > 1:
        print("  x%d  %s" % (count, text.replace("\n", " ")))

now = time.time()
print("\nостанні 8 за часом створення:")
for t in sorted(tasks, key=lambda x: x.get("created_at") or 0)[-8:]:
    created = t.get("created_at") or 0
    print("  %-14s %-12s %5.0f с тому | %s" % (
        t.get("id"), t.get("status"), now - created,
        (t.get("text") or "")[:70].replace("\n", " ")))
