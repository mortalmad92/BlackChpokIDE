"""Знімки нового інтерфейсу: об'єднані чати й панель автономного режиму.

Запуск: python tests/screenshot_autonomous.py
Результат: assets/chats_merged.png, assets/autonomous_panel.png
"""

from __future__ import annotations

import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def grab(widget, target: Path, *, topmost: bool = True) -> bool:
    """Знімок віджета через Pillow.

    ``ImageGrab`` знімає ЕКРАН за координатами, тому будь-яке вікно поверх
    (у нас — сама оболонка, з якої запускають тест) потрапляє в кадр.
    На час знімка піднімаємо вікно IDE поверх усього й повертаємо як було.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        print("Pillow недоступний — знімок пропущено.")
        return False
    root = widget.winfo_toplevel()
    try:
        if topmost:
            root.attributes("-topmost", True)
    except Exception:  # noqa: BLE001 - не на всіх платформах є
        pass
    try:
        for _ in range(4):
            widget.update_idletasks()
            widget.update()
            time.sleep(0.1)
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        w, h = widget.winfo_width(), widget.winfo_height()
        if w < 2 or h < 2:
            print(f"Віджет {widget} не має розміру ({w}x{h}) — пропущено.")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        if image.getbbox() is None:
            return False
        image.save(target)
        print(f"Знімок: {target} ({w}x{h}) at {x},{y}")
        return True
    finally:
        if topmost:
            try:
                root.attributes("-topmost", False)
            except Exception:  # noqa: BLE001
                pass


def demo_project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    (root / "app").mkdir()
    (root / "app" / "core.py").write_text(
        "# TODO: доробити обробку помилок\n"
        "def run():\n"
        "    try:\n"
        "        return work()\n"
        "    except ValueError:\n"
        "        pass\n" + "print('debug')\n" * 8,
        encoding="utf-8",
    )
    return root


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import queue_engine
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    project = demo_project()
    settings = Settings.load()
    settings.workspace = str(project)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"

    app = BlackChpokIDE(settings)
    app.geometry("1560x940+40+30")
    app.deiconify()
    app.lift()
    app.focus_force()
    pump(app, 1.6)

    try:
        # ── 1. Об'єднаний список «Чати й агенти»
        app.chat_store.create(title="Рефакторинг auth.py")
        app.chat_store.create(title="Тести для chat_store")
        app.chat_store.create(title="Поясни main_window")
        app.show_side("chats")
        app.chat_list.refresh()
        pump(app, 0.6)
        grab(app.sidebar, ROOT / "assets" / "chats_merged.png")

        # ── 2. Панель автономного режиму з планом, чергою й журналом
        app.autonomous_engine.project = project
        app.settings.llm.model = app.settings.llm.model or "demo-model"
        app.start_autonomous()
        pump(app, 0.8)
        app.stop_agent()
        pump(app, 0.3)
        app.add_autonomous_task("виправ помилку в app/core.py")
        pump(app, 0.4)
        app.autonomous_engine.set_plan([
            "Розібрати позначку TODO у app/core.py:1",
            "Додати тести для app/core.py",
            "Замінити print() на журнал у app/core.py",
        ])
        app.autonomous_engine.log("Знайдено 3 покращення — додано в чергу.", kind="ok")
        app.autonomous_engine.log("Додано твою задачу (вищий пріоритет).", kind="user")
        app.show_autonomous()
        app.autonomous_panel.refresh()
        pump(app, 0.8)
        app.lift()
        pump(app, 0.3)
        grab(app.sidebar, ROOT / "assets" / "autonomous_panel.png")
        grab(app, ROOT / "assets" / "autonomous_full.png")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    finally:
        try:
            app.autonomous_engine.confirm_stop()
            app.task_queue.clear()
            app.on_close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
