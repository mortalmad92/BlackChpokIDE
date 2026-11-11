"""Реальний прогін публічних точок входу головного вікна з рядками.

Кожен метод, що приймає шлях, викликається з РЯДКОМ (як це роблять JSON,
палітра, пошук і панелі), у підпроцесі з таймаутом — щоб падіння одного
не зупиняло решту. Саме так знайдено баги `open_path` і `file_tree.reveal`.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMEOUT = 120

CASES = [
    ("open_path", "рядок"),
    ("send_file_to_agent", "рядок"),
    ("show_diff_for", "рядок"),
    ("set_workspace", "рядок"),
    ("open_recent_folder", "рядок"),
    ("show_ast_tree", "рядок"),
    ("show_symbols_report", "рядок"),
    ("reveal_file", "рядок"),
]

CHILD = r'''
import json, os, pathlib, sys, tempfile, tkinter as tk
sys.path.insert(0, os.environ["ROOT"])
from blackchpok_ide import main_window as mw
from blackchpok_ide.config import Settings
method, kind = os.environ["METHOD"], os.environ["KIND"]
work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_arg_"))
sample = work / "зразок.py"
sample.write_text("def f():\n    return 1\n", "utf-8")
app = mw.BlackChpokIDE(Settings())
root = app.master or app.winfo_toplevel()
root.withdraw()
func = getattr(app, method, None)
if func is None:
    print(json.dumps({"status": "missing"}))
    sys.exit(0)
arg = str(sample)
try:
    func(arg)
    root.update_idletasks()
    print(json.dumps({"status": "ok"}))
except Exception as exc:
    print(json.dumps({"status": "error", "type": type(exc).__name__, "msg": str(exc)[:200]}))
finally:
    try:
        app.on_close()
    except Exception:
        pass
'''


def main() -> int:
    script = pathlib.Path(tempfile.gettempdir()) / "_bchk_arg_child.py"
    script.write_text(CHILD, "utf-8")
    problems = 0
    for method, kind in CASES:
        env = dict(os.environ)
        env["ROOT"] = str(ROOT)
        env["METHOD"] = method
        env["KIND"] = kind
        env["PYTHONPATH"] = str(ROOT)
        env.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_arg_"))
        env.setdefault("MCP_WORKSPACE", str(ROOT))
        try:
            proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                                  text=True, timeout=TIMEOUT, env=env, encoding="utf-8",
                                  errors="replace")
        except subprocess.TimeoutExpired:
            print(f"ASK  {method}({kind}) — таймаут {TIMEOUT} с")
            problems += 1
            continue
        line = ""
        for raw in reversed((proc.stdout or "").splitlines()):
            if raw.strip().startswith("{"):
                line = raw.strip()
                break
        if not line:
            print(f"FAIL {method}({kind}) — немає результату")
            problems += 1
            continue
        data = json.loads(line)
        if data["status"] == "missing":
            print(f"SKIP {method} — методу немає")
        elif data["status"] == "ok":
            print(f"OK   {method}({kind})")
        else:
            print(f"FAIL {method}({kind}) — {data['type']}: {data['msg']}")
            problems += 1
    print(f"\nпроблем: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
