"""Створити ГОЛОВНЕ вікно IDE, прокрутити події й закрити.

Це найважливіша перевірка: якщо вікно не збирається, у користувача не
працює нічого. Тест створює ``BlackChpokIDE`` у прихованому стані, прокручує
чергу подій Tk кілька разів (щоб спрацювали ``after_idle``/``after``) і
закриває вікно.

Ізоляція обов'язкова: ``BLACKCHPOK_HOME`` має вказувати на тимчасову теку,
інакше перевірка чіпала б справжні налаштування й чати користувача.

Запуск:
    set BLACKCHPOK_HOME=<тимчасова тека>
    python tools/smoke_main_window.py
Код виходу 1, якщо вікно не зібралось або впало під час прокрутки.
"""

from __future__ import annotations

import os
import tempfile
import traceback
from pathlib import Path


def main() -> int:
    home = os.environ.get("BLACKCHPOK_HOME", "")
    if not home or "Temp" not in home and "tmp" not in home.lower():
        print("Відмова: BLACKCHPOK_HOME не вказує на тимчасову теку.")
        return 2
    workspace = Path(tempfile.mkdtemp(prefix="smoke-window-ws-"))
    (workspace / "hello.py").write_text("print('привіт')\n", encoding="utf-8")

    from blackchpok_ide.config import Settings
    from blackchpok_ide.main_window import BlackChpokIDE

    settings = Settings.load()
    settings.remember_workspace(str(workspace))
    settings.engine.auto_start = False
    settings.llm.auto_detect = False

    try:
        app = BlackChpokIDE(settings)
    except Exception:                                       # noqa: BLE001
        print("ВІКНО НЕ ЗІБРАЛОСЬ")
        traceback.print_exc()
        return 1

    failures = 0
    try:
        app.withdraw()
        for step in range(12):
            try:
                app.update_idletasks()
                app.update()
            except Exception:                               # noqa: BLE001
                print(f"ПОДІЇ ВПАЛИ на кроці {step}")
                traceback.print_exc()
                failures += 1
                break
    finally:
        try:
            app.on_close() if hasattr(app, "on_close") else app.destroy()
        except Exception:                                   # noqa: BLE001
            print("ЗАКРИТТЯ ВІКНА ВПАЛО")
            traceback.print_exc()
            failures += 1
        try:
            app.destroy()
        except Exception:                                   # noqa: BLE001
            pass
    print(f"Головне вікно: {'OK' if failures == 0 else 'ПРОБЛЕМ ' + str(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
