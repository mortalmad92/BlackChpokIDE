"""Наскрізна перевірка режиму глибокого аналізу у справжньому вікні.

Перевіряємо те, що видно користувачу в чаті:

1. на складну задачу з'являється картка «Глибоке розмислення» з таймером;
2. наративи моделі стають окремими абзацами (а не одним блоком);
3. виклики інструментів згортаються в групи з людськими назвами;
4. панель задач показує кружечки, стани й підсумок;
5. блок «Поточна ціль» показує ціль;
6. коротке доручення режим НЕ вмикає.

Запуск: python tests/test_deep_mode_live.py
"""

from __future__ import annotations

import sys
import tempfile
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
    global failures
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
    settings.workspace = tempfile.mkdtemp()
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"

    app = BlackChpokIDE(settings)
    app.withdraw()
    try:
        pump(app, 0.6)
        chat = app.chat

        # ── 1. Коротке доручення режим не вмикає
        check("коротке доручення без режиму",
              not chat._deep_wanted("запусти тести"))
        check("явний /план вмикає режим",
              chat._deep_wanted("/план зроби сайт"))

        # ── 2. Старт сеансу
        goal = ("Потрібно реалізувати режим глибокого аналізу в чаті. "
                "Додати поступовий вивід думок, список задач, таймер і ціль.")
        card = chat.begin_deep(goal)
        pump(app, 0.3)
        check("картка аналізу створена", card is not None and card.winfo_exists())
        check("сеанс активний", chat.deep_active())
        check("ціль збережена в картці", bool(card.session.goal), card.session.goal[:40])
        check("блок цілі показує текст",
              "Поточна ціль" in str(card.goal_label.cget("text")),
              str(card.goal_label.cget("text"))[:50])

        # ── 3. Наративи — окремі абзаци
        check("картка стартує без вигаданих думок", card.session.narrations == 0,
              str(card.session.narrations))
        chat._deep_narration("Розберуся, що зараз відкриває браузер.")
        chat._deep_narration("Тепер зрозуміло. Перевірю ще кілька місць.")
        pump(app, 0.2)
        check("обидва наративи пораховані", card.session.narrations == 2,
              str(card.session.narrations))
        texts = [str(w.cget("text")) for w in card.thoughts.winfo_children()
                 if w.winfo_class() == "Label"]
        check("наратив «Розберуся» окремим підписом",
              any("Розберуся" in t for t in texts), str(texts)[:100])
        check("наратив «Тепер зрозуміло» окремим підписом",
              any("Тепер зрозуміло" in t for t in texts), str(texts)[:100])
        check("наративи не склеєні в один абзац", len(texts) == 2, str(len(texts)))

        # ── 4. Групи інструментів
        # ``AgentEvent`` приймає дані словником (kind, text, data), а не
        # keyword-аргументами — саме так їх формує AgentRunner._emit.
        chat._handle_event(AgentEvent(
            "tool_call", "read_file(path=main.py)",
            {"name": "read_file", "arguments": "path=main.py", "call_id": "c1"}))
        chat._handle_event(AgentEvent(
            "tool_result", "ok",
            {"name": "read_file", "ok": True, "call_id": "c1"}))
        chat._handle_event(AgentEvent(
            "tool_call", "search_text(query=def )",
            {"name": "search_text", "arguments": "query=def ", "call_id": "c2"}))
        chat._handle_event(AgentEvent(
            "tool_result", "ok",
            {"name": "search_text", "ok": True, "call_id": "c2"}))
        pump(app, 0.3)
        group = card._group
        check("група кроків створена", group is not None)
        if group is not None:
            check("заголовок групи людською мовою",
                  "Читання файлів" in str(group.title_label.cget("text")),
                  str(group.title_label.cget("text")))
            check("група згорнута за замовчуванням", not group.expanded)
            group.toggle()
            pump(app, 0.1)
            check("група розгортається", group.expanded)
            group.toggle()
            pump(app, 0.1)
            check("група згортається назад", not group.expanded)

        # ── 5. План задач
        steps = [
            "browser_panel: реєстр відкривача URL + рядок адреси",
            "preview_panel/live_preview: публічний open_url",
            "main_window: open_url_in_browser + меню",
            "env_setup.py: перевірка пакетів і програм",
            "first_run.py: багатокроковий майстер",
            "Тести нового функціоналу",
            "Оновити IDE_README_UK.md",
        ]
        chat.set_deep_plan(steps)
        pump(app, 0.3)
        check("усі задачі в плані", len(card.session.tasks) == len(steps),
              str(len(card.session.tasks)))
        check("рядки задач намальовані", len(card._task_rows) == len(steps),
              str(len(card._task_rows)))
        check("підсумок показує очікування",
              "очікуванні" in str(card.tasks_count.cget("text")),
              str(card.tasks_count.cget("text")))
        check("перша задача має кружечок ○",
              card.session.tasks[0].mark == deep_mode.STATE_MARKS[deep_mode.STATE_PENDING])

        # ── 6. Задача стає активною (кружечок ◐)
        first = card.session.start_work()
        card.paint_task(first.index)
        pump(app, 0.2)
        check("перша задача в процесі", first.state == deep_mode.STATE_RUNNING)
        check("маркер змінився на ◐",
              card.session.tasks[0].mark == "◐", card.session.tasks[0].mark)
        summary = str(card.tasks_count.cget("text"))
        check("підсумок «1 у процесі»", "1 у процесі" in summary, summary)
        check("підсумок рахує решту", "6 в очікуванні" in summary, summary)

        # ── 7. Таймер іде
        pump(app, 1.2)
        timer = str(card.timer_label.cget("text"))
        check("таймер показує час", timer != "0с", timer)
        check("заголовок «Глибоке розмислення»",
              "Глибоке" in str(card.title_label.cget("text")),
              str(card.title_label.cget("text")))

        # ── 8. Завершення
        chat.end_deep(ok=True)
        pump(app, 0.3)
        check("сеанс закрито", not chat.deep_active())
        check("фаза «готово»", card.session.phase == deep_mode.PHASE_DONE,
              card.session.phase)
        check("усі задачі позначені готовими",
              all(t.state == deep_mode.STATE_DONE for t in card.session.tasks))
        check("заголовок змінився на «Аналіз завершен»",
              "завершен" in str(card.title_label.cget("text")).lower(),
              str(card.title_label.cget("text")))

        # ── 9. Новий чат прибирає стан
        chat.begin_deep("ще одна складна задача для перевірки очищення стану")
        pump(app, 0.2)
        check("другий сеанс активний", chat.deep_active())
        chat.new_chat()
        pump(app, 0.3)
        check("після нового чату сеанс скинуто", not chat.deep_active())

        # ── 10. Ціль через вікно IDE
        app._set_goal("Мета: довести режим до кінця")
        pump(app, 0.2)
        check("вікно передало ціль у чат",
              chat.current_goal.startswith("Мета:"), chat.current_goal[:40])

        # ── 11. Режим вмикається самим _send, а не лише через API
        # Модель не потрібна: перевіряємо, що картка з'явилась і що агент
        # отримав запит (підміняємо runner, щоб не чекати мережу).
        chat.new_chat()
        pump(app, 0.2)
        started: list[str] = []

        class FakeRunner:
            busy = False

            def start(self, text: str, **_kw) -> None:
                started.append(text)

            def reset(self) -> None:
                pass

        real_runner = chat.runner
        chat.runner = FakeRunner()  # type: ignore[assignment]
        try:
            chat.settings.llm.model = ""     # без моделі — план не питаємо
            chat._send("/план реалізуй глибокий аналіз у чаті з задачами й таймером")
            pump(app, 0.5)
            check("_send створив картку аналізу", chat.deep_active())
            check("агент усе одно отримав запит", bool(started), str(started)[:60])
        finally:
            chat.end_deep(ok=False)
            chat.runner = real_runner
            chat.set_busy(False)

        # ── 12. Черга задач план НЕ складає
        # Регресія: `_send` почав чекати на план перед стартом агента, і
        # автономний режим (який іде через `run_next_task` → `_send`)
        # зависав у стані «зупиняється», бо агент так і не стартував.
        chat.new_chat()
        pump(app, 0.2)
        started.clear()

        class QueueRunner:
            busy = False

            def start(self, text: str, **_kw) -> None:
                started.append(text)

            def reset(self) -> None:
                pass

        real_runner = chat.runner
        chat.runner = QueueRunner()  # type: ignore[assignment]
        try:
            chat.settings.llm.model = "test-model"   # план був би можливий
            chat._send("/план складна задача для черги з багатьма вимогами",
                       deep=False)
            pump(app, 0.4)
            check("черга не створює картку аналізу", not chat.deep_active())
            check("черга одразу запускає агента", bool(started), str(started)[:50])
        finally:
            chat.runner = real_runner
            chat.set_busy(False)
            chat.end_deep(ok=False)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        failures += 1
    finally:
        try:
            app.on_close()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Глибокий аналіз: успішно" if failures == 0
          else f"Глибокий аналіз: помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
