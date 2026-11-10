"""Знімок режиму глибокого аналізу в чаті.

Запуск: python tests/screenshot_deep.py
Результат: assets/deep_mode.png
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

STEPS = (
    "browser_panel: реєстр відкривача URL + рядок адреси + перехід на будь-який URL",
    "preview_panel/live_preview: публічний open_url для довільних адрес",
    "main_window: open_url_in_browser + реєстрація відкривача + меню/шорткат",
    "Прибрати системний браузер у changes_panel, model_hub_panel, settings_dialog",
    "env_setup.py: перевірка й встановлення пакетів Python та програм (git/node)",
    "first_run.py: багатокроковий майстер (залізо → бібліотеки → програми → модель)",
    "Тести нового функціоналу + повний прогін",
    "Оновити IDE_README_UK.md",
)

NARRATIONS = (
    "Розберуся, що зараз відкриває браузер і як влаштований вбудований браузер.",
    "Тепер зрозуміло. Перевірю ще кілька місць, де відкривається системний браузер.",
    "Маю повну картину. Складу план і почну.",
)


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def shoot(widget, target: Path) -> bool:
    try:
        from PIL import ImageGrab
    except ImportError:
        print("Pillow недоступний — знімок пропущено.")
        return False
    root = widget.winfo_toplevel()
    try:
        root.attributes("-topmost", True)
    except Exception:  # noqa: BLE001
        pass
    try:
        for _ in range(4):
            widget.update_idletasks()
            widget.update()
            time.sleep(0.1)
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        w, h = widget.winfo_width(), widget.winfo_height()
        if w < 2 or h < 2:
            print(f"віджет без розміру ({w}x{h})")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(target)
        print(f"Знімок: {target} ({w}x{h})")
        return True
    finally:
        try:
            root.attributes("-topmost", False)
        except Exception:  # noqa: BLE001
            pass


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

    from blackchpok_ide import deep_mode
    from blackchpok_ide.agent import AgentEvent
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "chat"

    app = BlackChpokIDE(settings)
    app.geometry("1180x980+40+20")
    app.deiconify()
    pump(app, 1.4)
    # Стартовий екран перекриває колонку діалогу: без цього знімок показує
    # «Сплануй, збери або /…» замість картки аналізу.
    app.hide_welcome()
    pump(app, 0.4)

    chat = app.chat
    goal = ("BlackChpok IDE, частина 2: (1) жодне місце в IDE не відкриває "
            "системний браузер ПК (зокрема git-сторінку завантаження) — усе "
            "йде у вбудований браузер; (2) вбудований браузер відкриває "
            "локальні сайти й будь-які адреси з інтернету.")
    chat.begin_deep(goal)
    pump(app, 0.3)
    chat._deep_narration(NARRATIONS[0])

    # Перша група: читання файлів і пошук
    for name, arguments in (
        ("read_file", "path=blackchpok_ide/main_window.py"),
        ("search_text", "query=webbrowser.open"),
        ("read_file", "path=blackchpok_ide/browser_panel.py"),
        ("run_command", "command=python -m py_compile ..."),
    ):
        chat._handle_event(AgentEvent(
            "tool_call", f"{name}({arguments})",
            {"name": name, "arguments": arguments, "call_id": name + arguments[:6]}))
        chat._handle_event(AgentEvent(
            "tool_result", "ok",
            {"name": name, "ok": True, "call_id": name + arguments[:6]}))
        pump(app, 0.05)
    chat._deep_narration(NARRATIONS[1])

    for name, arguments in (
        ("read_file", "path=blackchpok_ide/changes_panel.py"),
        ("read_file", "path=blackchpok_ide/settings_dialog.py"),
    ):
        chat._handle_event(AgentEvent(
            "tool_call", f"{name}({arguments})",
            {"name": name, "arguments": arguments, "call_id": "b" + name[:6]}))
        chat._handle_event(AgentEvent(
            "tool_result", "ok",
            {"name": name, "ok": True, "call_id": "b" + name[:6]}))
        pump(app, 0.05)

    chat.set_deep_plan(STEPS)
    pump(app, 0.3)
    card = chat.deep_card
    first = card.session.start_work()
    card.paint_task(first.index)
    chat.set_goal(goal)
    app._sync_chat_title()
    pump(app, 1.6)

    out = ROOT / "assets" / "deep_mode.png"
    # Прокручуємо до самої картки аналізу, інакше в кадр потрапляє низ
    # стрічки (порожній екран із композером).
    try:
        chat.scroll.canvas.update_idletasks()
        chat.scroll.canvas.yview_moveto(0.0)
        pump(app, 0.4)
    except Exception:  # noqa: BLE001
        pass
    shoot(app, out)
    if card is not None and card.winfo_exists():
        shoot(card, ROOT / "assets" / "deep_card.png")

    try:
        chat.end_deep(ok=True)
    except Exception:  # noqa: BLE001
        pass
    app.on_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
