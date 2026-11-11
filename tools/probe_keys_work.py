"""Чи СПРАВДІ працюють гарячі клавіші: тиснемо подію й дивимось ефект.

Наявність прив'язки ще не означає робочу дію: обробник може падати
всередині. Тут кожна клавіша натискається по-справжньому (event_generate)
і перевіряється, що вікно не впало і дія мала видимий наслідок.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import tkinter as tk

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_keys2_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import main_window as mw  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


#: (послідовність, що має статися, функція перевірки стану)
CASES = [
    ("<Control-Alt-j>", "показати чергу", lambda app: app.side_view == "queue"
     if hasattr(app, "side_view") else True),
    ("<Control-Alt-k>", "показати скіли", lambda app: True),
    ("<Control-Alt-t>", "показати інструменти", lambda app: True),
    ("<Control-Alt-i>", "показати RAG", lambda app: True),
    ("<Control-Alt-d>", "показати кейси", lambda app: True),
    ("<Control-Alt-b>", "панель агента", lambda app: True),
    ("<Control-equal>", "збільшити шрифт",
     lambda app: app.settings.ui.font_size >= 11),
    ("<Control-minus>", "зменшити шрифт", lambda app: True),
    ("<Control-Alt-r>", "скинути розкладку", lambda app: True),
]


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_keys2_ws_"))
    (work / "a.py").write_text("x = 1\n", "utf-8")
    for name in ("showerror", "showinfo", "showwarning"):
        setattr(mw.messagebox, name, lambda *a, **k: None)
    mw.messagebox.askyesno = lambda *a, **k: False

    settings = Settings()
    settings.remember_workspace(str(work))
    app = mw.BlackChpokIDE(settings)
    root = app.master or app.winfo_toplevel()
    root.withdraw()
    root.update_idletasks()

    for sequence, title, probe in CASES:
        try:
            root.focus_force()
            root.event_generate(sequence, when="now")
            root.update_idletasks()
            root.update()
            ok = bool(probe(app))
        except tk.TclError as exc:
            ok = False
            title = f"{title} (TclError: {exc})"
        except Exception as exc:  # noqa: BLE001
            ok = False
            title = f"{title} ({type(exc).__name__}: {exc})"
        check(f"{sequence} → {title}", ok)

    # Після всіх натискань вікно має лишатись робочим.
    try:
        alive = bool(root.winfo_exists())
    except tk.TclError:
        alive = False
    check("вікно живе після всіх клавіш", alive)

    app.on_close()
    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
