"""Скриншот великого статусу моделі й самодіагностики.

Запуск:  .venv\\Scripts\\python.exe tests/shots_model_status.py
Файли:   .buildtmp/shots/status-*.png
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


def grab(app, name: str) -> Path:
    from PIL import ImageGrab

    try:
        app.lift()
        app.focus_force()
        app.attributes("-topmost", True)
        app.update()
        time.sleep(0.5)
    except Exception:  # noqa: BLE001
        pass
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    menu = app.nametowidget(app.cget("menu")) if app.cget("menu") else None
    menu_h = menu.winfo_height() if menu is not None else 0
    if menu_h <= 1:
        menu_h = 26
    image = ImageGrab.grab(bbox=(x, y - menu_h, x + w, y + h))
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
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.font_size = 12
    settings.ui.view = "chat"
    settings.ui.bottom_visible = False

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1660x980+30+20")
    pump(app, 2.2)
    app.hide_welcome()
    app.chat.new_chat()
    pump(app, 0.4)

    # 1. Офлайн: червоний кружечок великими літерами.
    app.header_bar.set_model_status(False, detail="сервер не відповідає")
    pump(app, 0.5)
    grab(app, "status-01-offline")

    # 2. Онлайн: зелений кружечок великими літерами.
    app.header_bar.set_model_status(
        True, detail="http://127.0.0.1:8081/v1")
    pump(app, 0.5)
    grab(app, "status-02-online")

    # 3. Невідомо: сірий, без вигаданого зеленого.
    app.header_bar.set_model_status(None, detail="перевірка не завершилась")
    pump(app, 0.4)
    grab(app, "status-03-unknown")

    # 4. Самодіагностика в терміналі.
    app.header_bar.set_model_status(False, detail="перевірка")
    app.show_bottom("terminal")
    pump(app, 0.5)
    app.run_diagnostics()
    # Діагностика робить мережеві перевірки (до 24 портів по 1.5 с), тому
    # чекаємо довше за один кадр — інакше в кадрі лише заголовок звіту.
    pump(app, 25.0)
    grab(app, "status-04-diagnostics")

    app.agent.cancel()
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
