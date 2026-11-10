"""Знімок панелі «Справи» з живими індикаторами."""

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
    """Знімок віджета через Pillow (ImageGrab по координатах вікна)."""
    try:
        from PIL import ImageGrab
    except ImportError:
        print("Pillow недоступний — знімок пропущено.")
        return False
    widget.update_idletasks()
    widget.update()
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    w = widget.winfo_width()
    h = widget.winfo_height()
    if w < 2 or h < 2:
        print(f"Віджет {widget} не має розміру ({w}x{h}) — знімок пропущено.")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    # Порожній (увесь чорний) кадр означає, що вікно ще не відмалювалось.
    if image.getbbox() is None:
        print("Кадр порожній — повторюємо після паузи.")
        return False
    image.save(target)
    print(f"Знімок: {target} ({w}x{h})")
    return True


def main() -> int:
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False

    from blackchpok_ide.agent import AgentEvent
    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1560x940")
    pump(app, 1.2)
    app.show_side("cases")
    app.toggle_focus_mode(True)
    pump(app, 0.8)

    # Справа, яка вже завершилась — щоб було видно обидва стани.
    app._case_begin("Перевір, чи проходять тести проєкту")
    for text, key in (("Запит до моделі…", ""),
                      ("read_file(path=tests/run_all.py)", "a1"),
                      ("run_command(python tests/run_all.py)", "a2")):
        app._case_on_event(AgentEvent("tool_call", text, {"call_id": key or "s1",
                                                         "name": "tool"}))
    app._case_on_event(AgentEvent("tool_result", "ок", {"call_id": "a1", "ok": True}))
    app._case_on_event(AgentEvent("tool_result", "ок", {"call_id": "a2", "ok": True}))
    app._case_on_event(AgentEvent("done", "", {"ok": True}))
    pump(app, 0.4)

    # Активна справа — та, що «зараз виконується».
    app._case_begin("Додай тести для cases_panel і запусти їх")
    for text, key in (("Запит до qwen2.5-coder-14b…", ""),
                      ("read_file(path=blackchpok_ide/cases_panel.py)", "b1"),
                      ("write_file(path=tests/test_cases_panel.py)", "b2"),
                      ("run_command(python tests/test_cases_panel.py)", "b3")):
        app._case_on_event(AgentEvent("tool_call", text, {"call_id": key or "s2",
                                                         "name": "tool"}))
    app._case_on_event(AgentEvent("tool_result", "ок", {"call_id": "b1", "ok": True}))
    app._case_on_event(AgentEvent("tool_result", "ок", {"call_id": "b2", "ok": True}))
    pump(app, 1.4)

    app.cases_panel.refresh()
    pump(app, 0.5)

    # Вікно має бути на передньому плані, інакше ImageGrab знімає чорний кадр.
    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)
    app.update()
    pump(app, 1.0)
    app.focus_force()
    pump(app, 0.6)

    ok = grab(app.cases_panel, ROOT / "assets" / "cases_panel.png")
    if not ok:
        pump(app, 0.8)
        ok = grab(app.cases_panel, ROOT / "assets" / "cases_panel.png")
    grab(app, ROOT / "assets" / "focus_mode.png")
    app.attributes("-topmost", False)
    print("Панель знято:", ok)

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
