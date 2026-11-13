"""Перевірка: справжній агент (офлайн-роутер) наповнює «Справи» кроками.

Модель не піднімаємо — використовуємо офлайн-фолбек, який теж іде через
той самий цикл подій ``AgentEvent``, що й справжня LLM.
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

#: Скільки чекати на завершення роботи агента в живому прогоні (секунди).
#:
#: Стеля навмисно велика: справжня локальна модель 14B на цьому залізі
#: відповідає десятки секунд. Це не «поблажка тесту» — це єдина межа, за
#: якою справжнє зависання справді видно. Раніше стояло фіксоване вікно
#: 4 с, і тест падав просто тому, що модель ще працювала.
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

    Навіщо замість фіксованого ``pump(app, 4.0)``. Час роботи залежить від
    того, ЧИМ відповідає агент:

    * офлайн-роутер — частки секунди;
    * справжня локальна модель на 14B — десятки секунд.

    Фіксовані 4 секунди проходили лише для першого випадку. Коли агент
    законно починає працювати з моделлю (а він це робить, щойно вона є),
    тест падав на «справа завершилась — виконується», хоч агент просто ще
    працював. Тепер чекаємо на СПРАВЖНЮ ознаку завершення й маємо стелю,
    щоб справжнє зависання все одно було видно.
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

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.agent.offline_fallback = True

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1400x860")
    pump(app, 1.0)
    app.show_side("cases")
    pump(app, 0.3)

    # Без моделі агент піде офлайн-роутером — але події ті самі.
    app.agent.llm_settings.model = ""
    app.chat._send("покажи файли")

    def finished() -> bool:
        """Агент завершив роботу й жоден крок справи не лишився активним."""
        if getattr(app.agent, "busy", False):
            return False
        if not app.case_book.cases:
            return False
        current = app.case_book.cases[0]
        return (current.status != "виконується"
                and all(step.status != "виконується" for step in current.steps))

    done = pump_until(app, finished, timeout=AGENT_BUDGET_S)
    check("агент завершив роботу за відведений час", done,
          f"чекали {int(AGENT_BUDGET_S)} с")

    case = app.case_book.cases[0] if app.case_book.cases else None
    check("справа створилась із реального запиту", case is not None)
    if case is not None:
        check("у справі є кроки", len(case.steps) >= 1, f"{len(case.steps)}")
        check("справа завершилась", case.status != "виконується", case.status)
        check("жоден крок не «висить»",
              all(s.status != "виконується" for s in case.steps),
              str([f"{s.status}:{s.text[:30]}" for s in case.steps]))
        print("\n   Кроки справи:")
        for step in case.steps:
            print(f"   · [{step.status}] {step.text[:70]}")

    check("панель намалювала справу", len(app.cases_panel._rows) >= 1,
          f"{len(app.cases_panel._rows)} рядків")
    check("після роботи немає активних крапок",
          not any(d.state == "running" for d in app.cases_panel._dots
                  if d.winfo_exists()))

    app.agent.cancel()
    app.destroy()
    print()
    print("Живі справи:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
