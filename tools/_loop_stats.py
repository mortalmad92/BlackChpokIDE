"""Тимчасовий інструмент: статистика циклів у живих завданнях черги."""
import io
import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

home = r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE"
queue = json.load(io.open(home + r"\queue.json", encoding="utf-8"))
tasks = queue.get("tasks", [])

tool_re = re.compile(r"^(?P<name>[a-z_]+)\((?P<args>.*)\)$")

for t in sorted(tasks, key=lambda x: x.get("created_at") or 0):
    hist = t.get("history") or []
    tools = [h.get("text") for h in hist if h.get("kind") == "tool"]
    if not tools:
        continue
    paths = Counter()
    kinds = Counter()
    for entry in tools:
        m = tool_re.match(entry or "")
        if not m:
            kinds[entry or ""] += 1
            continue
        kinds[m.group("name")] += 1
        pm = re.search(r"path=([^,)]+)", m.group("args"))
        if pm:
            paths[pm.group(1)] += 1
    print("=" * 90)
    print("id", t.get("id"), "| status", t.get("status"), "|", (t.get("text") or "")[:80].replace("\n", " "))
    print("  tool calls:", len(tools), "| kinds:", dict(kinds))
    print("  paths:", dict(paths))
    stamp = {}
    for h in hist:
        stamp.setdefault(h.get("kind"), []).append(h.get("at"))
    starts = stamp.get("start", [])
    ends = stamp.get("done") or stamp.get("failed")
    if starts and ends:
        print("  duration: %.0f s" % (ends[-1] - starts[0]))
