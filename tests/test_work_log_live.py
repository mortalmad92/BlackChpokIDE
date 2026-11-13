"""Живий прогін: справжній агент (офлайн-роутер) малює журнал у чаті."""

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

#: Скільки чекати на завершення роботи агента в живому прогоні (секунди).
#:
#: Стеля велика навмисно: справжня локальна модель 14B відповідає десятки
#: секунд. Раніше стояло фіксоване вікно 4 с, і тест падав просто тому, що
#: модель ще працювала — не через дефект коду.
AGENT_BUDGET_S = 180.0


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


def pump_until(app, predicate, timeout: float) -> bool:
    """Крутити цикл подій, доки ``predicate()`` не стане істинним.

    Фіксоване вікно очікування тут неправильне: офлайн-роутер відповідає
    за частки секунди, а справжня локальна модель 14B — за десятки секунд.
    Тест падав на «журнал завершено», хоч агент просто ще працював. Тепер
    чекаємо на СПРАВЖНЮ ознаку завершення, зі стелею — щоб справжнє
    зависання все одно було видно.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 - стан може ще не існувати
            continue
    app.update()
    return False


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.agent.offline_fallback = True

    app = BlackChpokIDE(settings)
    app.geometry("1400x880")
    pump(app, 1.0)

    app.agent.llm_settings.model = ""
    app.chat._send("покажи файли")

    def work_done() -> bool:
        """Агент закінчив: не працює й журнал справді припинив біг."""
        if getattr(app.agent, "busy", False):
            return False
        card = app.chat._log
        if card is None:
            for item in app.chat._cards:
                candidate = getattr(item, "log", None)
                if candidate is not None:
                    card = candidate
                    break
        if card is None:
            return False
        # Журнал мусить мати хоч один рядок кроку і не крутити таймер.
        return bool(card._rows) and card.running is False

    waited = pump_until(app, work_done, timeout=AGENT_BUDGET_S)
    check("агент завершив роботу за відведений час", waited,
          f"чекали {int(AGENT_BUDGET_S)} с")

    log = app.chat._log
    # Журнал міг завершитись і відчепитись — тоді шукаємо картку журналу.
    found = log
    if found is None:
        for card in app.chat._cards:
            candidate = getattr(card, "log", None)
            if candidate is not None:
                found = candidate
                break

    check("журнал створено під час роботи", found is not None)
    if found is not None:
        kinds = [row.kind for row in found._rows]
        texts = [row.label.cget("text") for row in found._rows]
        print("\n   Рядки журналу:")
        for row in found._rows:
            target = row.target.cget("text")
            print(f"   · [{row.kind}] {row.label.cget('text')} {target}")
        check("у журналі є крок інструмента", "tool" in kinds, str(kinds))
        check("журнал завершено", found.running is False)
        check("у заголовку є таймер", bool(found.timer_label.cget("text")),
              found.timer_label.cget("text"))
        check("рядки мають людські підписи",
              any(t in ("Дивиться теку", "Читає", "Шукає") for t in texts),
              str(texts))

    app.agent.cancel()
    app.destroy()
    print()
    print("Живий журнал:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
