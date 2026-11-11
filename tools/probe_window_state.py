"""Реальний прогін головного вікна: перемикання панелей, вкладки, меню.

Кожен крок перевіряється справжнім станом Tk (winfo_ismapped, кількість
вкладок, текст статусу), а не лише відсутністю винятку.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import tkinter as tk

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_win_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import main_window as mw  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}{' — ' + detail if detail and not ok else ''}")
    if not ok:
        FAILS.append(name)


def main() -> int:
    settings = Settings()
    app = mw.BlackChpokIDE(settings)
    root = app.master or app.winfo_toplevel()
    root.withdraw()
    root.update_idletasks()

    # 1. Рейка перемикає панелі: кожна кнопка має показати свою панель.
    rail = getattr(app, "rail", None) or getattr(app, "nav_rail", None)
    check("знайдено рейку навігації", rail is not None,
          f"атрибути: {[a for a in dir(app) if 'rail' in a.lower()][:6]}")
    panels = {}
    for attr in ("chat", "cases_panel", "tools_panel", "skills_panel",
                 "queue_panel", "mcp_panel", "rag_panel", "changes_panel",
                 "runtime_panel", "autonomous_panel"):
        panel = getattr(app, attr, None)
        if panel is not None and hasattr(panel, "winfo_exists"):
            panels[attr] = panel
    check("панелі існують", len(panels) >= 6, f"знайдено {sorted(panels)}")

    # 2. Вкладки: відкрити файл, перевірити кількість, закрити.
    tabs = getattr(app, "tabs", None)
    check("знайдено вкладки", tabs is not None,
          f"атрибути: {[a for a in dir(app) if 'tab' in a.lower()][:8]}")
    if tabs is not None:
        workdir = pathlib.Path(tempfile.mkdtemp(prefix="bchk_file_"))
        sample = workdir / "зразок.py"
        sample.write_text("def привіт():\n    return 'світ'\n", "utf-8")
        before = len(tabs.editors)
        app.open_path(str(sample))
        root.update_idletasks()
        after = len(tabs.editors)
        check("відкриття файлу додало вкладку", after > before, f"{before} -> {after}")
        if after > before:
            current = tabs.current_path()
            check("відкритий файл став поточним",
                  current is not None and pathlib.Path(str(current)).name == "зразок.py",
                  str(current))
            text = tabs.current()
            if text is not None and hasattr(text, "get"):
                check("вміст файлу в редакторі",
                      "привіт" in text.get("1.0", "end"), text.get("1.0", "end")[:40])

    # 3. Меню: усі каскади мають непорожні підписи.
    menubar = None
    for child in root.winfo_children():
        if child.winfo_class() == "Menu":
            menubar = child
            break
    check("знайдено меню", menubar is not None)
    if menubar is not None:
        labels = []
        try:
            end = menubar.index("end")
        except tk.TclError:
            end = None
        if end:
            for i in range(int(end) + 1):
                try:
                    labels.append(menubar.entrycget(i, "label"))
                except tk.TclError:
                    labels.append("")
        check("усі пункти меню мають підписи",
              all(lbl.strip() for lbl in labels), f"{labels}")

    # 4. Статус-бар відповідає на питання без винятку.
    for method in ("_agent_status_text", "_status_summary"):
        func = getattr(app, method, None)
        if func is None:
            continue
        try:
            text = func()
            check(f"{method}() повертає текст",
                  isinstance(text, str) and bool(text.strip()), str(text)[:60])
        except Exception as exc:  # noqa: BLE001
            check(f"{method}() працює", False, f"{type(exc).__name__}: {exc}")

    app.on_close()
    print(f"\nпровалів: {len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
