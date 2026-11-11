"""Реальний прогін УСІХ методів вікна з безпечними аргументами.

Для кожного публічного методу будує аргументи за анотаціями та іменами
параметрів, викликає його в підпроцесі й ловить падіння. Діалоги
замінюються заглушками, щоб нічого не чекало натискання.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMEOUT = 100

CHILD = r'''
import json, os, pathlib, sys, tempfile, traceback
sys.path.insert(0, os.environ["ROOT"])
from unittest import mock
import tkinter as tk
from blackchpok_ide import main_window as mw
from blackchpok_ide.config import Settings

target = os.environ["METHOD"]
work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_m_"))
(work / "a.py").write_text("def f():\n    return 1\n", "utf-8")
(work / "b.py").write_text("y = 2\n", "utf-8")

ok, err = [], []
def fake(*a, **k):
    return True
# ``simpledialog`` імпортується ВСЕРЕДИНІ методів (``from tkinter import
# simpledialog``), тому патчити треба сам модуль, а не імʼя у вікні: інакше
# ``create_project_folder`` та ``open_url_dialog`` чекали на ввід і прогін
# «висі́в» на таймауті — хоч у програмі це нормальні діалоги.
import tkinter.simpledialog as _sd
_sd.askstring = lambda *a, **k: None
_sd.askinteger = lambda *a, **k: None
with mock.patch.object(mw.messagebox, "showerror", fake), \
     mock.patch.object(mw.messagebox, "showinfo", fake), \
     mock.patch.object(mw.messagebox, "showwarning", fake), \
     mock.patch.object(mw.messagebox, "askyesno", lambda *a, **k: False), \
     mock.patch.object(mw.messagebox, "askokcancel", lambda *a, **k: False), \
     mock.patch.object(mw.filedialog, "askopenfilename", lambda *a, **k: str(work / "a.py")), \
     mock.patch.object(mw.filedialog, "askdirectory", lambda *a, **k: str(work)), \
     mock.patch.object(mw.filedialog, "asksaveasfilename", lambda *a, **k: str(work / "new.py")):
    app = mw.BlackChpokIDE(Settings())
    root = app.master or app.winfo_toplevel()
    root.withdraw()
    func = getattr(app, target, None)
    if func is None:
        print(json.dumps({"status": "missing"})); sys.exit(0)
    import inspect
    sig = inspect.signature(func)
    args = []
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.default is not param.empty:
            continue
        low = name.lower()
        if "path" in low or "file" in low or low in {"target", "src", "dst"}:
            args.append(str(work / "a.py"))
        elif "folder" in low or "root" in low or "dir" in low or "workspace" in low:
            args.append(str(work))
        elif "line" in low or "count" in low or "index" in low:
            args.append(0)
        elif "text" in low or "phrase" in low or "query" in low or "name" in low or "prompt" in low:
            args.append("перевірка")
        else:
            args.append(None)
    try:
        func(*args)
        root.update_idletasks()
        print(json.dumps({"status": "ok", "args": len(args)}))
    except Exception as exc:
        print(json.dumps({"status": "error", "type": type(exc).__name__,
                          "msg": str(exc)[:180], "args": len(args),
                          "trace": traceback.format_exc().splitlines()[-3:]}))
    finally:
        try:
            app.on_close()
        except Exception:
            pass
'''

SKIP_METHODS = {
    # реально закривають процес або запускають довгі мережеві/модельні операції
    "quit", "destroy", "open_url_in_browser", "start_site", "stop_site",
    "unload_model_now", "free_vram_now", "start_autonomous", "stop_autonomous",
    "send_to_agent", "run_next_task", "replan_now", "install_engine",
}


def main() -> int:
    sys.path.insert(0, str(ROOT))
    script = pathlib.Path(tempfile.gettempdir()) / "_bchk_all_child.py"
    script.write_text(CHILD, "utf-8")

    import inspect

    from blackchpok_ide import main_window as mw
    methods = [name for name, value in vars(mw.BlackChpokIDE).items()
               if callable(value) and not name.startswith("_")
               and name not in SKIP_METHODS]
    print(f"методів для перевірки: {len(methods)}")
    problems = []
    for name in sorted(methods):
        env = dict(os.environ)
        env.update({"ROOT": str(ROOT), "METHOD": name, "PYTHONPATH": str(ROOT)})
        env.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_m_"))
        env.setdefault("MCP_WORKSPACE", str(ROOT))
        try:
            proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                                  text=True, timeout=TIMEOUT, env=env,
                                  encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            print(f"ASK  {name} — таймаут")
            problems.append(f"{name}: таймаут")
            continue
        line = ""
        for raw in reversed((proc.stdout or "").splitlines()):
            if raw.strip().startswith("{"):
                line = raw.strip()
                break
        if not line:
            print(f"FAIL {name} — немає JSON")
            problems.append(f"{name}: без виводу")
            continue
        data = json.loads(line)
        if data["status"] == "error":
            print(f"FAIL {name}/{data['args']} — {data['type']}: {data['msg']}")
            problems.append(f"{name}: {data['type']}: {data['msg']}")
    print(f"\nметодів із проблемами: {len(problems)}")
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
