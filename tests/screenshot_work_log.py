"""Знімок живого журналу роботи в чаті."""

from __future__ import annotations

import sys
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


def grab(widget, target: Path) -> bool:
    try:
        from PIL import ImageGrab
    except ImportError:
        print("Pillow недоступний — знімок пропущено.")
        return False
    widget.update_idletasks()
    widget.update()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    if w < 2 or h < 2:
        print(f"Віджет без розміру ({w}x{h}) — пропущено.")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    if image.getbbox() is None:
        return False
    image.save(target)
    print(f"Знімок: {target} ({w}x{h})")
    return True


def main() -> int:
    from blackchpok_ide.agent import AgentEvent
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False

    app = BlackChpokIDE(settings)
    app.geometry("1560x940")
    pump(app, 1.2)
    app.toggle_focus_mode(True)
    pump(app, 0.6)

    chat = app.chat

    # Запит користувача.
    chat._new_card("ВИ", accent="#8fb6ff", bg="#15151b").add_action("", lambda: None)
    card = chat._cards[-1]
    chat._body_text(card, "Перевір, чи проходять тести проєкту, і виправ падіння.")

    # Живий журнал: роздуми, інструменти, проміжні коментарі.
    chat._handle_event(AgentEvent("status", "Запит до qwen2.5-coder-14b…"))
    chat._handle_event(AgentEvent("reasoning",
                                  "Спершу треба зрозуміти, як запускаються тести. "
                                  "Подивлюсь run_all.py і список тестів.", {"step": 0}))
    chat._handle_event(AgentEvent("tool_call", "read_file(file_path=tests/run_all.py)",
                                  {"call_id": "s1", "name": "read_file",
                                   "arguments": "file_path=tests/run_all.py"}))
    chat._handle_event(AgentEvent("tool_result",
                                  "Обирає всі перевірки проєкту послідовно.",
                                  {"call_id": "s1", "name": "read_file", "ok": True}))
    chat._handle_event(AgentEvent("reasoning",
                                  "Тепер запущу сам прогін і подивлюсь, що впало.",
                                  {"step": 1}))
    chat._handle_event(AgentEvent("tool_call",
                                  "run_command(command=python tests/run_all.py)",
                                  {"call_id": "s2", "name": "run_command",
                                   "arguments": "command=python tests/run_all.py"}))
    chat._handle_event(AgentEvent("tool_result", "PermissionError на тимчасових файлах",
                                  {"call_id": "s2", "name": "run_command", "ok": False}))
    chat._handle_event(AgentEvent("assistant",
                                  "Падіння стосується пісочниці, не логіки. Перевіряю далі.",
                                  {"step": 2, "final": False}))
    chat._handle_event(AgentEvent("tool_call", "search_text(query=tmpw6_)",
                                  {"call_id": "s3", "name": "search_text",
                                   "arguments": "query=tmpw6_"}))
    chat._handle_event(AgentEvent("tool_result", "2 збіги у tests/test_model_hub.py",
                                  {"call_id": "s3", "name": "search_text", "ok": True}))
    pump(app, 2.2)

    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)
    app.focus_force()
    pump(app, 1.2)

    ok = grab(app.conversation_host, ROOT / "assets" / "work_log.png")
    if not ok:
        pump(app, 0.8)
        ok = grab(app.conversation_host, ROOT / "assets" / "work_log.png")
    print("Журнал знято:", ok)

    app.attributes("-topmost", False)
    app.agent.cancel()
    app.destroy()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
