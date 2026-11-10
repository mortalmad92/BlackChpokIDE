"""Живий запуск вікна IDE: побудова, реальні панелі, чисте закриття.

Перевіряє те, чого не бачать юніт-тести: вікно справді створюється, панелі
показують РЕАЛЬНІ дані (модель, контекст, реєстр інструментів), і закриття
не лишає винятків.

Запуск: python tools/check_gui_live.py
"""

from __future__ import annotations

import os
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

# Ізолюємо дані: жодного впливу на справжні налаштування користувача.
os.environ.setdefault("BLACKCHPOK_HOME",
                      tempfile.mkdtemp(prefix="bchp-guilive-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            app.update()
        except Exception:  # noqa: BLE001 - вікно могло закритись
            return
        time.sleep(0.02)


def main() -> int:
    from blackchpok_ide import theme
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    import tkinter as tk

    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as exc:
        print(f"[SKIP] Немає дисплея: {exc}")
        return 0

    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.first_run_done = True
    settings.engine.auto_start = False      # не піднімаємо модель із GUI
    settings.llm.base_url = "http://127.0.0.1:8080/v1"
    settings.llm.model = settings.llm.model or "qwen25vl3b"

    from blackchpok_ide.main_window import BlackChpokIDE

    print("Будую вікно…")
    app = BlackChpokIDE(settings)
    app.update_idletasks()
    app.update()
    check("вікно створено", bool(app.winfo_exists()))

    # Панелі мають існувати й бути наповненими.
    for name, widget in (("контекст", getattr(app, "context", None)),
                         ("чат", getattr(app, "chat", None)),
                         ("вкладки", getattr(app, "tabs", None))):
        check(f"панель «{name}» існує", widget is not None)

    # Реєстр інструментів: РЕАЛЬНІ числа (лінивість або повний набір).
    try:
        state = app.agent.tool_registry_state()
    except Exception as exc:  # noqa: BLE001
        state = {}
        check("стан реєстру доступний", False, str(exc))
    total = int(state.get("total") or 0)
    eager = int(state.get("eager") or 0)
    print(f"      реєстр: {state}")
    check("реєстр інструментів заповнено", total > 0, str(total))
    check("схем у запиті не більше, ніж інструментів",
          eager <= total or total == 0, f"{eager} <= {total}")

    # Єдине джерело стану сервера має відповісти (сервер піднятий).
    from blackchpok_ide import server_state

    state_srv = server_state.probe_server(settings.llm.base_url,
                                         api_key=settings.llm.api_key,
                                         timeout=3)
    print(f"      сервер: {state_srv.note()}")
    check("стан сервера визначено",
          state_srv.reachable or bool(state_srv.error))
    if state_srv.reachable:
        check("контекст від сервера відомий", state_srv.context > 0,
              f"{state_srv.context} ({state_srv.context_source})")

    # Даємо інтерфейсу попрацювати: таймери, фонові опитування, панель.
    pump(app, 2.5)
    check("інтерфейс живий після 2.5 с", bool(app.winfo_exists()))

    # Панель контексту має показати реальні показники реєстру.
    try:
        panel_state = app._registry_state_for_panel()
    except Exception as exc:  # noqa: BLE001
        panel_state = {}
        print(f"      panel error: {exc}")
    check("панель отримує стан реєстру",
          int(panel_state.get("total") or 0) > 0, str(panel_state))

    # Чесність підрахунку токенів — реальний стан, не вигаданий.
    exact = app._counter_is_exact()
    print(f"      точний tokenizer: {exact}")

    # Закриття.
    print("Закриваю вікно…")
    try:
        app.destroy()
    except Exception as exc:  # noqa: BLE001
        check("вікно закрилось без винятку", False, str(exc))
    else:
        check("вікно закрилось без винятку", True)

    print()
    print("GUI: " + ("УСПІШНО" if not failures else f"ЗБОЇВ: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
