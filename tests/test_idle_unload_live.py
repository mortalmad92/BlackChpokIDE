"""Наскрізна перевірка звільнення відеокарти у справжньому вікні IDE.

Модель тут фейкова: перевіряємо саму логіку — що простій вивантажує
модель, що автономний режим цьому заважає, що будь-яка дія користувача
скидає таймер, і що «Зупинити агента» не плутається з вивантаженням.

Запуск: python tests/test_idle_unload_live.py
"""

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


class FakeServer:
    """Підміна керованого llama-server: рахує зупинки."""

    def __init__(self) -> None:
        self.running = True
        self.stops = 0

    def stop(self) -> None:
        self.running = False
        self.stops += 1


def main() -> int:
    global failures
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False

    app = BlackChpokIDE(settings)
    app.withdraw()
    try:
        pump(app, 0.5)
        server = FakeServer()
        app._managed_server = server
        keeper = app.model_keeper

        # ── 1. Модель завантажена, простій короткий — не вивантажуємо
        keeper.tracker.policy.enabled = True
        keeper.tracker.policy.idle_seconds = 60
        keeper.tracker.touch()
        check("модель вважається завантаженою", keeper.loaded)
        check("щойно активний користувач — модель лишається",
              not keeper.poll(busy=False, autonomous=False))
        check("сервер не зупинено", server.stops == 0)

        # ── 2. Довгий простій — вивантажуємо
        keeper.tracker.last_touch -= 10_000
        check("довгий простій вивантажує модель",
              keeper.poll(busy=False, autonomous=False))
        check("сервер справді зупинено", server.stops == 1)
        check("стан показує «вивантажена»", not keeper.loaded)

        # ── 3. Друге вивантаження не робить нічого (моделі вже немає)
        keeper.tracker.last_touch -= 10_000
        check("повторне вивантаження не спрацьовує",
              not keeper.poll(busy=False, autonomous=False))
        check("зайвих зупинок немає", server.stops == 1)

        # ── 4. Автономний режим блокує вивантаження
        server2 = FakeServer()
        app._managed_server = server2
        keeper.tracker.touch()
        keeper.tracker.last_touch -= 10_000
        project = ROOT
        app.autonomous_engine.project = project
        app.autonomous_engine.state = "працює"
        check("в автономному режимі модель не вивантажується",
              not keeper.poll(busy=False, autonomous=app.autonomous_engine.active))
        check("сервер автономного режиму працює", server2.stops == 0)
        app.autonomous_engine.confirm_stop()

        # ── 5. Дія користувача скидає таймер
        keeper.tracker.last_touch -= 10_000
        before = keeper.tracker.idle_seconds
        app._wake_on_action()
        after = keeper.tracker.idle_seconds
        check("дія користувача скидає таймер простою", after < before,
              f"{int(before)} с → {int(after)} с")
        check("після дії вивантаження не потрібне",
              not keeper.tracker.should_unload(busy=False, autonomous=False,
                                               loaded=keeper.loaded))

        # ── 6. «Зупинити агента» ≠ «вивантажити модель»
        server3 = FakeServer()
        app._managed_server = server3
        keeper.tracker.touch()
        app.stop_agent()
        pump(app, 0.2)
        check("зупинка агента не чіпає модель", server3.stops == 0 and keeper.loaded)

        # ── 7. Ручне вивантаження з меню
        app.unload_model_now()
        check("меню «Вивантажити модель» спрацьовує", server3.stops == 1)
        check("статус повідомляє про вивантаження",
              "ивантаж" in str(app.status_label.cget("text")))

        # ── 8. Без керованого сервера — чесна відповідь, не падіння
        app._managed_server = None
        app.unload_model_now()
        check("без сервера немає помилки, лише статус",
              app.status_label.cget("text") != "")

        # ── 9. Налаштування простою читаються з Settings
        check("поріг простою читається з налаштувань",
              keeper.tracker.policy.idle_seconds >= 60,
              str(keeper.tracker.policy.idle_seconds))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        failures += 1
    finally:
        try:
            app.on_close()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Звільнення відеокарти: успішно" if failures == 0
          else f"Звільнення відеокарти: помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
