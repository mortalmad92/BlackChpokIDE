"""Тимчасовий інструмент: показати останні траси агента людською мовою."""
import io
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

path = r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE\agent_traces.jsonl"
n = int(sys.argv[1]) if len(sys.argv) > 1 else 6

rows = [json.loads(line) for line in io.open(path, encoding="utf-8") if line.strip()]
print("total", len(rows))
for row in rows[-n:]:
    print("=" * 100)
    print("id", row.get("id"), "started", row.get("started_at"),
          "intent", row.get("intent_type"), "cont", row.get("continuation"))
    print("goal:", row.get("goal"))
    print("steps", row.get("steps"), "prompt_tokens", row.get("prompt_tokens"),
          "compl", row.get("completion_tokens"), "dur", row.get("duration"))
    tools = row.get("tools") or []
    print("tools(%d):" % len(tools), tools)
    print("changed", row.get("changed_files"), "failed", row.get("failed_calls"),
          "rejected", row.get("rejected_calls"))
    print("false_success", row.get("false_success"))
    print("answer_head:", (row.get("answer_head") or "")[:600])
