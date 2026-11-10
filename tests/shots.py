"""Зняти серію скриншотів нового інтерфейсу для перевірки композиції.

Запуск:  .venv\\Scripts\\python.exe tests/shots.py
Файли:   .buildtmp/shots/*.png
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


def grab(app, name: str, extra: tuple = ()) -> None:
    from PIL import ImageGrab

    # Вікно має бути справді зверху: інакше в кадр потрапляє чуже вікно,
    # яке випадково опинилось поверх (браузер, термінал тощо).
    try:
        app.lift()
        app.focus_force()
        app.attributes("-topmost", True)
        app.update()
        time.sleep(0.35)
        app.update()
        # Спливні картки (селектор, меню) — окремі Toplevel: піднімаємо їх
        # ПІСЛЯ головного вікна, інакше main window їх перекриває.
        for window in extra:
            if window is None:
                continue
            try:
                window.lift()
                window.attributes("-topmost", True)
                window.update()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.25)
        app.update()
    except Exception:  # noqa: BLE001
        pass
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    menu = app.nametowidget(app.cget("menu")) if app.cget("menu") else None
    menu_h = menu.winfo_height() if menu is not None else 0
    if menu_h <= 1:
        menu_h = 24
    image = ImageGrab.grab(bbox=(x, y - menu_h, x + w, y + h))
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{name}.png"
    image.save(target)
    visible = [("popover", bool(getattr(win, "visible", False))) for win in extra if win]
    print("saved", target.name, image.size, visible or "")


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
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.font_size = 12
    settings.ui.view = "chat"
    settings.ui.bottom_visible = False
    settings.llm.model = settings.llm.model or "qwen2.5-coder-14b-instruct"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1500x920+30+20")
    pump(app, 1.8)
    app.hide_welcome()
    app.open_path(ROOT / "main.py")
    pump(app, 0.8)

    # 1. Діалог із реальними повідомленнями (центрована колонка)
    app.chat.new_chat()
    pump(app, 0.3)
    app.chat._write("\nВИ\n", "user_role")
    app.chat._write("Перевір проєкт і скажи, що робить server.py\n", "user_text")
    app.chat._write("\nАГЕНТ\n", "assistant_role")
    app.chat._write_markdown(
        "Прочитав структуру. Основні модулі:\n"
        "- `server.py` — MCP-сервер з єдиним інструментом master_agent_router\n"
        "- `agent_tools.py` — реалізація файлових дій і терміналу\n\n"
        "```python\ndef master_agent_router(intent='auto', request=''):\n    ...\n```\n"
    )
    app.chat._add_assistant(
        "Готово. Прочитав 3 файли, змін не вносив — усе вже відповідає опису."
    )
    pump(app, 1.0)
    grab(app, "01-chat")

    # 2. Робоча область (редактор + термінал)
    app.set_view("workspace")
    app.show_bottom("terminal")
    app.terminal.run("python --version")
    pump(app, 1.6)
    grab(app, "02-workspace")

    # 3. Селектор моделей
    app.set_view("chat")
    pump(app, 0.5)
    app.show_model_selector()
    pump(app, 0.9)
    grab(app, "03-model-selector", extra=(app._model_selector,))
    if app._model_selector is not None:
        app._model_selector.close()
    pump(app, 0.3)

    # 4. Меню режимів
    app.show_mode_menu()
    pump(app, 0.6)
    grab(app, "04-modes", extra=(app._mode_menu,))
    if app._mode_menu is not None:
        app._mode_menu.close()
    pump(app, 0.3)

    # 5. Панель файлів (проєкт)
    app.show_side("explorer")
    pump(app, 0.6)
    grab(app, "05-explorer")

    # 6. MCP
    app._rail_action("mcp")
    pump(app, 0.6)
    grab(app, "06-mcp")

    # 7. База знань / RAG
    app._rail_action("knowledge")
    pump(app, 1.2)
    grab(app, "07-knowledge")

    # 8. Агенти (справи)
    app._rail_action("agents")
    pump(app, 0.5)
    grab(app, "08-agents")

    # 9. Вузьке вікно — редактор має лишитись, контекст згорнутись.
    app.set_view("workspace")
    pump(app, 1.0)
    app.geometry("1100x700+30+20")
    pump(app, 1.2)
    grab(app, "09-narrow")

    app.agent.cancel()
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
