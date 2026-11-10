"""Скриншот пігулок композера: робочий простір і режим.

Запуск:  .venv\\Scripts\\python.exe tests/shots_composer_pills.py
Файли:   .buildtmp/shots/pills-*.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / ".buildtmp" / "shots"


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def grab(app, name: str, extra: tuple = ()) -> Path:
    from PIL import ImageGrab

    try:
        app.lift()
        app.focus_force()
        app.attributes("-topmost", True)
        app.update()
        time.sleep(0.4)
        for window in extra:
            if window is None:
                continue
            try:
                window.lift()
                window.attributes("-topmost", True)
                window.update()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)
        app.update()
    except Exception:  # noqa: BLE001
        pass
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{name}.png"
    image.save(target)
    print("saved", target.name, image.size)
    return target


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.recent = [str(ROOT), str(ROOT / "docs")]
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.font_size = 12
    settings.ui.view = "chat"
    settings.ui.bottom_visible = False

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1500x920+30+20")
    pump(app, 2.0)
    app.hide_welcome()
    app.chat.new_chat()
    pump(app, 0.5)
    app.chat._write("\nВИ\n", "user_role")
    app.chat._write("Скільки тут Python-файлів?\n", "user_text")
    pump(app, 0.6)
    grab(app, "pills-01-idle")

    app.show_workspace_menu(app.chat.workspace_btn)
    pump(app, 0.8)
    grab(app, "pills-02-workspace", extra=(app._workspace_menu,))
    if app._workspace_menu is not None:
        app._workspace_menu.hide()
    pump(app, 0.3)

    app.show_mode_menu(app.chat.mode_btn)
    pump(app, 0.8)
    grab(app, "pills-03-mode", extra=(app._mode_menu,))
    if app._mode_menu is not None:
        app._mode_menu.close()
    pump(app, 0.3)

    app.agent.cancel()
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
