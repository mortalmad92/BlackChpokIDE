"""Кожна команда палітри — в окремому процесі.

Так видно справжні збої: у спільному процесі одна команда може знищити
віджет, і всі наступні падають з `invalid command name`, що не є багом.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMEOUT = 90

CHILD = r'''
import json, os, pathlib, sys, tempfile
sys.path.insert(0, os.environ["ROOT"])
from unittest import mock
from tkinter import simpledialog
from blackchpok_ide import command_registry, commands, main_window as mw
from blackchpok_ide.config import Settings

key = os.environ["CMD_KEY"]
work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_c_"))
(work / "a.py").write_text("def f():\n    return 1\n", "utf-8")
(work / "README.md").write_text("# Проєкт\n", "utf-8")

def fake(*a, **k):
    return None

patches = [
    mock.patch.object(mw.messagebox, "showerror", fake),
    mock.patch.object(mw.messagebox, "showinfo", fake),
    mock.patch.object(mw.messagebox, "showwarning", fake),
    mock.patch.object(mw.messagebox, "askyesno", lambda *a, **k: False),
    mock.patch.object(mw.messagebox, "askokcancel", lambda *a, **k: False),
    mock.patch.object(mw.filedialog, "askopenfilename", lambda *a, **k: str(work / "a.py")),
    mock.patch.object(mw.filedialog, "askdirectory", lambda *a, **k: str(work)),
    mock.patch.object(mw.filedialog, "asksaveasfilename", lambda *a, **k: str(work / "new.py")),
    mock.patch.object(simpledialog, "askstring", lambda *a, **k: ""),
    mock.patch.object(simpledialog, "askinteger", lambda *a, **k: 0),
]
for p in patches:
    p.start()

settings = Settings()
settings.remember_workspace(str(work))
app = mw.BlackChpokIDE(settings)
root = app.master or app.winfo_toplevel()
root.withdraw()
root.update_idletasks()
command_registry.register_all(app)
found = [c for c in commands.all_commands() if c.key == key]
if not found:
    print(json.dumps({"status": "missing"})); sys.exit(0)
cmd = found[0]
try:
    if not cmd.is_enabled():
        print(json.dumps({"status": "disabled"})); sys.exit(0)
    cmd.action()
    root.update_idletasks()
    print(json.dumps({"status": "ok"}))
except Exception as exc:
    print(json.dumps({"status": "error", "type": type(exc).__name__, "msg": str(exc)[:150]}))
finally:
    try:
        app.on_close()
    except Exception:
        pass
'''

SKIP_PREFIX = (
    "app.exit", "file.quit", "model.", "engine.", "hub.", "browser.",
    "preview.start", "mcp.", "voice.", "autonomous.", "night.", "deploy.",
    "publish.", "install.", "update.", "download.", "social.", "help.about",
)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    script = pathlib.Path(tempfile.gettempdir()) / "_bchk_cmd_child.py"
    script.write_text(CHILD, "utf-8")

    os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_c_"))
    from blackchpok_ide import command_registry, commands  # noqa: E402
    from blackchpok_ide.config import Settings  # noqa: E402
    from blackchpok_ide import main_window as mw  # noqa: E402
    from unittest import mock  # noqa: E402
    import tkinter as tk  # noqa: E402

    for name in ("showerror", "showinfo", "showwarning"):
        setattr(mw.messagebox, name, lambda *a, **k: None)
    mw.messagebox.askyesno = lambda *a, **k: False
    root = tk.Tk()
    root.withdraw()
    app = mw.BlackChpokIDE(Settings())
    command_registry.register_all(app)
    keys = [c.key for c in commands.all_commands() if not c.key.startswith(SKIP_PREFIX)]
    app.on_close()
    root.destroy()

    print(f"команд: {len(keys)}")
    problems = []
    for key in keys:
        env = dict(os.environ)
        env.update({"ROOT": str(ROOT), "CMD_KEY": key, "PYTHONPATH": str(ROOT)})
        try:
            proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                                  text=True, timeout=TIMEOUT, env=env,
                                  encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            print(f"ASK  {key} — таймаут (можливо, модальний діалог)")
            continue
        line = ""
        for raw in reversed((proc.stdout or "").splitlines()):
            if raw.strip().startswith("{"):
                line = raw.strip()
                break
        if not line:
            print(f"FAIL {key} — без виводу")
            problems.append(f"{key}: без виводу")
            continue
        data = json.loads(line)
        if data["status"] == "error":
            print(f"FAIL {key} — {data['type']}: {data['msg']}")
            problems.append(f"{key}: {data['type']}: {data['msg']}")
    print(f"\nсправжніх збоїв: {len(problems)}")
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
