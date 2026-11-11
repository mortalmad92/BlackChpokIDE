"""Яка команда ламає вікно для наступних команд.

Запускає команди послідовно в ОДНОМУ процесі й після кожної перевіряє,
чи живі ключові віджети (header, terminal, bottom_tabs). Перша команда,
після якої віджет зникає, — винуватець.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import tkinter as tk
from unittest import mock

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_br_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tkinter import simpledialog  # noqa: E402

from blackchpok_ide import command_registry, commands  # noqa: E402
from blackchpok_ide import main_window as mw  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

SKIP_PREFIX = (
    "app.exit", "file.quit", "model.", "engine.", "hub.", "browser.",
    "preview.start", "mcp.", "voice.", "autonomous.", "night.", "deploy.",
    "publish.", "install.", "update.", "download.", "social.", "help.about",
)


def alive(widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_br_ws_"))
    (work / "a.py").write_text("def f():\n    return 1\n", "utf-8")
    for name in ("showerror", "showinfo", "showwarning"):
        setattr(mw.messagebox, name, lambda *a, **k: None)
    mw.messagebox.askyesno = lambda *a, **k: False
    mw.messagebox.askokcancel = lambda *a, **k: False
    mw.filedialog.askopenfilename = lambda *a, **k: str(work / "a.py")
    mw.filedialog.askdirectory = lambda *a, **k: str(work)
    mw.filedialog.asksaveasfilename = lambda *a, **k: str(work / "new.py")
    simpledialog.askstring = lambda *a, **k: ""

    settings = Settings()
    settings.remember_workspace(str(work))
    app = mw.BlackChpokIDE(settings)
    root = app.master or app.winfo_toplevel()
    root.withdraw()
    root.update_idletasks()
    command_registry.register_all(app)

    watched = {
        "header": app.header,
        "terminal": app.terminal,
        "bottom_tabs": app.bottom_tabs,
        "tabs": app.tabs,
        "chat": app.chat,
        "file_tree": app.file_tree,
        "centre": app.centre,
        "h_split": app.h_split,
    }
    before = {name: alive(widget) for name, widget in watched.items()}
    print("живі на старті:", {k: v for k, v in before.items() if not v} or "усі")

    keys = [c.key for c in commands.all_commands() if not c.key.startswith(SKIP_PREFIX)]
    broken_by = []
    for key in keys:
        found = [c for c in commands.all_commands() if c.key == key]
        if not found or not found[0].is_enabled():
            continue
        try:
            found[0].action()
            root.update_idletasks()
        except Exception as exc:  # noqa: BLE001
            print(f"ЗБІЙ {key}: {type(exc).__name__}: {str(exc)[:80]}")
            continue
        dead = [name for name, widget in watched.items() if alive(widget) is False]
        if dead:
            broken_by.append((key, dead))
            print(f"ЗЛАМАВ {key} -> зникли {dead}")
        root.update_idletasks()

    app.on_close()
    print(f"\nкоманд, що ламають вікно: {len(broken_by)}")
    for key, dead in broken_by:
        print(f"  {key}: {dead}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
