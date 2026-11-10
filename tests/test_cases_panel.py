"""Тести панелі «Справи» й анімованих індикаторів.

Запуск:  python tests/test_cases_panel.py
Перевіряє модель (CaseBook), малювання панелі та анімацію крапок.
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


def test_model() -> None:
    """CaseBook: справи, кроки, завершення."""
    from blackchpok_ide import cases_panel

    book = cases_panel.CaseBook()
    check("порожня книга не має активної справи", book.current() is None)

    case = book.begin("Прочитай main.py і поясни, що він робить")
    check("справу створено", case is book.current())
    check("справа почалась як активна", case.status == cases_panel.RUNNING)
    check("назва скопійована", "main.py" in case.title)

    step = book.add_step("Запит до моделі…")
    check("крок додано", step is not None and len(case.steps) == 1)
    check("крок виконується", case.steps[0].status == cases_panel.RUNNING)
    check("активних кроків 1", case.active_steps == 1)

    book.add_step("read_file(path=main.py)", key="call_1")
    check("другий крок додано", len(case.steps) == 2)
    check("ключ кроку збережено", case.steps[1].key == "call_1")
    check("віха закрилась, коли почався інструмент",
          case.steps[0].status == cases_panel.DONE, case.steps[0].status)

    finished = book.finish_step(key="call_1", ok=True)
    check("завершення кроку за ключем", finished is True)
    check("крок став «готово»", case.steps[1].status == cases_panel.DONE)

    book.add_step("write_file(path=main.py)", key="call_2")
    book.finish_step(key="call_2", ok=False)
    check("невдалий крок позначено помилкою",
          case.steps[2].status == cases_panel.FAILED)

    book.end(ok=True, summary="Все зроблено")
    check("справу закрито", case.status == cases_panel.DONE)
    check("поточної справи більше немає", book.current() is None)
    check("усі кроки закрито",
          all(s.status != cases_panel.RUNNING for s in case.steps))
    check("підсумок збережено", case.summary == "Все зроблено")

    # Незавершена попередня справа закривається новою.
    first = book.begin("Перша задача")
    second = book.begin("Друга задача")
    check("нова справа стає поточною", book.current() is second)
    check("попередня справа закрилась", first.status == cases_panel.DONE)

    # Помилкове завершення.
    failing = book.begin("Зламана задача")
    book.add_step("run_command(pytest)", key="c9")
    book.finish_step(key="c9", ok=False)
    book.end(ok=False, error="pytest впав")
    check("справа з помилкою закрилась як помилка",
          failing.status == cases_panel.FAILED)
    check("текст помилки збережено", "pytest" in failing.error)

    counts = book.counts()
    check("лічильники рахують стани",
          counts[cases_panel.DONE] >= 2 and counts[cases_panel.FAILED] >= 1,
          str(counts))

    removed = book.clear_finished()
    check("прибирання завершених справ", removed >= 3 and not book.cases,
          f"прибрано {removed}")

    # Порожній крок не додається.
    book.begin("Перевірка порожнечі")
    check("порожній крок ігнорується", book.add_step("   ") is None)

    # Обмеження кількості кроків.
    for index in range(cases_panel.MAX_STEPS + 15):
        book.add_step(f"крок {index}")
    current = book.current()
    check("кількість кроків обмежена",
          len(current.steps) == cases_panel.MAX_STEPS, f"{len(current.steps)}")

    # Обмеження кількості справ.
    book.clear()
    for index in range(cases_panel.MAX_CASES + 10):
        book.begin(f"справа {index}")
        book.end(ok=True)
    check("кількість справ обмежена",
          len(book.cases) <= cases_panel.MAX_CASES, f"{len(book.cases)}")


def test_mark_helpers() -> None:
    """Дрібні помічники: змішування кольорів і тексти часу."""
    from blackchpok_ide import cases_panel, pulse

    check("blend(0) дає перший колір", pulse.blend("#4ade80", "#000000", 0.0) == "#4ade80")
    check("blend(1) дає другий колір", pulse.blend("#4ade80", "#000000", 1.0) == "#000000")
    mixed = pulse.blend("#ffffff", "#000000", 0.5)
    check("blend(0.5) посередині", mixed in {"#7f7f7f", "#808080"}, mixed)
    check("blend стійкий до сміття", pulse.blend("не-колір", "#000000", 0.5) == "не-колір")

    step = cases_panel.Step(text="перевірка")
    check("свіжий крок без часу", step.elapsed_text == "")

    case = cases_panel.Case(title="Довга назва " * 30)
    check("довга назва обрізається", len(case.short_title(40)) == 40,
          str(len(case.short_title(40))))
    check("переноси згортаються",
          cases_panel.Case(title="а\n\nб").short_title() == "а б")


def test_widgets() -> None:
    """Панель малюється наживо, крапки анімуються."""
    import tkinter as tk

    from blackchpok_ide import cases_panel, pulse, theme

    root = tk.Tk()
    root.geometry("360x700")
    fonts = theme.Theme(root)
    fonts.apply()

    book = cases_panel.CaseBook()
    panel = cases_panel.CasesPanel(root, fonts, book)
    panel.pack(fill="both", expand=True)
    root.update()

    check("порожня панель показує підказку", panel.empty.winfo_ismapped() == 1)

    book.begin("Прочитай файл і поясни")
    book.add_step("Запит до моделі…")
    root.update()

    check("рядок справи намальовано", len(panel._rows) == 1)
    check("підказка зникла", panel.empty.winfo_ismapped() == 0)
    check("крапки створено", len(panel._dots) >= 2, f"{len(panel._dots)} крапок")
    check("є крапка в стані виконання",
          any(d.state == pulse.PulseDot.RUNNING for d in panel._dots))

    # Анімація: тікер має рухати кільце.
    ticker = pulse.ticker_for(panel)
    check("тікер вікна створено", ticker is not None)
    running = next(d for d in panel._dots if d.state == pulse.PulseDot.RUNNING)
    before = running.coords(running._ring)
    # Прокачати кадри вручну: headless-середовище може не мати mainloop.
    for _ in range(3):
        ticker._tick()
        root.update()
    after = running.coords(running._ring)
    check("кільце анімується", before != after, f"{before} → {after}")
    check("кільце видиме під час роботи",
          running.itemcget(running._ring, "state") == "normal")

    book.add_step("read_file(path=main.py)", key="k1")
    root.update()
    check("другий крок видно", len(panel._dots) >= 3)

    book.finish_step(key="k1", ok=True)
    book.end(ok=True, summary="Готово")
    root.update()
    # Панель перебудувала рядки — беремо актуальні крапки, а не старі.
    check("після завершення немає активних крапок",
          not any(d.state == pulse.PulseDot.RUNNING for d in panel._dots
                  if d.winfo_exists()),
          str([d.state for d in panel._dots if d.winfo_exists()]))
    finished_dot = next((d for d in panel._dots if d.winfo_exists()), None)
    check("завершена справа має крапку «готово»",
          finished_dot is not None and finished_dot.state == pulse.PulseDot.DONE)
    if finished_dot is not None:
        check("у спокійному стані кільце сховане",
              finished_dot.itemcget(finished_dot._ring, "state") == "hidden")

    # Згортання/розгортання справи.
    case_id = book.cases[0].id
    panel._expanded.discard(case_id)
    panel.refresh()
    root.update()
    check("згорнута справа не показує кроків", case_id not in panel._expanded)
    panel.toggle_case(case_id)
    check("клік розгортає справу", case_id in panel._expanded)
    panel.toggle_case(case_id)
    check("повторний клік згортає", case_id not in panel._expanded)

    # Прибирання завершених через кнопку панелі.
    panel._clear_done()
    root.update()
    check("кнопка прибирання очищає список", not book.cases)

    # Знищення панелі не має лишати живих підписок.
    panel.destroy()
    root.update()
    ticker_after = pulse.ticker_for(root)
    check("після знищення панелі підписок не лишилось",
          ticker_after is None or not any(
              d.state == pulse.PulseDot.RUNNING for d in panel._dots
              if d.winfo_exists()),
          "" if ticker_after is None else str(len(ticker_after._subscribers)))

    pulse.forget_ticker(root)
    root.destroy()


def test_events_bridge() -> None:
    """Події агента перетворюються в кроки справи."""
    import tkinter as tk

    from blackchpok_ide import cases_panel, main_window, theme
    from blackchpok_ide.agent import AgentEvent

    root = tk.Tk()
    root.withdraw()
    fonts = theme.Theme(root)
    fonts.apply()

    # Мінімальний стенд: беремо справжній CaseBook і ту саму логіку вікна.
    book = cases_panel.CaseBook()

    class Stand:
        case_book = book

        def __init__(self) -> None:
            self.chat = type("Chat", (), {"runner": None})()

        _case_on_event = main_window.BlackChpokIDE._case_on_event

    stand = Stand()
    book.begin("Запит користувача")

    stand._case_on_event(AgentEvent("status", "Запит до qwen2.5-coder…"))
    stand._case_on_event(AgentEvent("tool_call", "read_file(path=main.py)",
                                    {"call_id": "c1", "name": "read_file"}))
    stand._case_on_event(AgentEvent("tool_result", "вміст файлу",
                                    {"call_id": "c1", "name": "read_file", "ok": True}))
    stand._case_on_event(AgentEvent("tool_call", "run_command(pytest)",
                                    {"call_id": "c2", "name": "run_command"}))
    stand._case_on_event(AgentEvent("tool_result", "помилка", {"call_id": "c2",
                                                              "name": "run_command",
                                                              "ok": False}))

    case = book.current()
    # Віха «Запит до моделі…» + два виклики інструментів = 3 кроки.
    check("кроки з подій створено", len(case.steps) == 3, f"{len(case.steps)}")
    check("кроки не залишились «у роботі»",
          all(s.status != cases_panel.RUNNING for s in case.steps),
          str([s.status for s in case.steps]))
    check("віха закрилась, коли почався інструмент",
          case.steps[0].status == cases_panel.DONE, case.steps[0].status)
    check("невдалий інструмент дав помилку",
          any(s.status == cases_panel.FAILED for s in case.steps))

    stand._case_on_event(AgentEvent("done", "", {"ok": True}))
    check("подія done закриває справу", case.status == cases_panel.DONE)

    # Помилка агента теж має стати кроком.
    book.begin("Другий запит")
    stand._case_on_event(AgentEvent("error", "Модель недоступна"))
    check("помилка агента стає кроком",
          any(s.status == cases_panel.FAILED for s in book.current().steps))

    root.destroy()


def main() -> int:
    test_model()
    test_mark_helpers()
    test_widgets()
    test_events_bridge()
    print()
    print("Справи:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_cases_panel.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
