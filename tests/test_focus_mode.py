"""Перевірка режиму «тільки чат» і панелі «Справи» у справжньому вікні."""

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

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.opensave = fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    # Тест перевіряє згортання робочої області, тому стартує з виду, де вона
    # справді показана (а не з того, що лишилось у налаштуваннях).
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1560x900")
    pump(app, 1.0)

    check("режим спочатку вимкнений", app._focus_mode is False)
    check("робоча область показана", app.centre.winfo_ismapped() == 1,
          f"visible={app.centre.winfo_ismapped()}")

    chat_before = app.conversation_host.winfo_width()

    # ── вмикаємо режим «тільки чат»
    app.toggle_focus_mode(True)
    pump(app, 0.8)
    check("режим увімкнено", app._focus_mode is True)
    check("редактор згорнуто", app.centre.winfo_ismapped() == 0,
          f"visible={app.centre.winfo_ismapped()}")
    check("розмова видима", app.conversation_host.winfo_ismapped() == 1)
    chat_after = app.conversation_host.winfo_width()
    check("розмова стала ширшою за редактор", chat_after > chat_before,
          f"{chat_before} → {chat_after}")

    # ── панелі все ще доступні за бажанням
    for key in ("explorer", "cases", "queue"):
        app.show_side(key)
        pump(app, 0.25)
        widget = app._side_widgets[key]
        check(f"панель «{key}» відкривається в режимі чату",
              widget.winfo_ismapped() == 1)

    # ── вимикаємо: редактор повертається
    app.toggle_focus_mode(False)
    pump(app, 0.8)
    check("режим вимкнено", app._focus_mode is False)
    check("редактор повернувся", app.centre.winfo_ismapped() == 1)
    check("розмова знову на місці", app.conversation_host.winfo_ismapped() == 1)

    # ── «Справи» оживають від подій агента
    app.show_side("cases")
    pump(app, 0.3)
    app._case_begin("Перевірити, що агент описує роботу")
    from blackchpok_ide.agent import AgentEvent

    app._case_on_event(AgentEvent("status", "Запит до моделі…"))
    app._case_on_event(AgentEvent("tool_call", "read_file(path=main.py)",
                                  {"call_id": "x1", "name": "read_file"}))
    pump(app, 0.3)

    case = app.case_book.current()
    check("справу створено з чату", case is not None)
    check("кроки видно в моделі", case is not None and len(case.steps) >= 2,
          str(len(case.steps) if case else 0))

    dots = app.cases_panel._dots
    running = [d for d in dots if d.winfo_exists() and d.state == "running"]
    check("є живі крапки під час роботи", len(running) >= 1, f"{len(running)}")

    # Анімація рухає кільце.
    if running:
        dot = running[0]
        before = dot.coords(dot._ring)
        pump(app, 0.35)
        after = dot.coords(dot._ring)
        check("кільце справді анімується", before != after, f"{before} → {after}")

    app._case_on_event(AgentEvent("tool_result", "ок", {"call_id": "x1",
                                                       "name": "read_file", "ok": True}))
    app._case_on_event(AgentEvent("done", "", {"ok": True}))
    pump(app, 0.3)
    check("справу завершено", case is not None and case.status == "готово",
          case.status if case else "")

    app.agent.cancel()
    app.destroy()
    print()
    print("Режим чату й справи:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
