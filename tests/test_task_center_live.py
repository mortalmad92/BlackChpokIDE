"""Тест живого центру завдань у вікні IDE.

Перевіряє те, чого не видно з юніт-тестів: панель справді малює чергу,
кнопки змінюють стан, деталі відкриваються, а компонування переживає
вузьке вікно.

Запуск: python tests/test_task_center_live.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def _neutralise() -> None:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001 - вікно могло закритись
            return
        time.sleep(0.02)


def _labels(widget, depth: int = 0) -> list[str]:
    """Усі тексти підписів у піддереві (для перевірки вмісту деталей)."""
    import tkinter as tk

    found: list[str] = []
    if depth > 12:
        return found
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            try:
                found.append(str(child.cget("text")))
            except Exception:  # noqa: BLE001
                pass
        found.extend(_labels(child, depth + 1))
    return found


def main() -> int:
    _neutralise()
    from blackchpok_ide import queue_engine
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    # Автозапуск вимкнено: тест керує станами вручну, без реальної моделі.
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"
    settings.ui.bottom_visible = True

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1560x900")
    try:
        pump(app, 1.4)
        app.hide_welcome()
        pump(app, 0.4)

        check("центр завдань існує", hasattr(app, "task_center"))
        check("виконавець підключений", app.task_center.executor is app.executor)
        check("вкладка завдань у нижній панелі",
              app.task_center in app.bottom_tabs.winfo_children())

        app.show_bottom("tasks")
        pump(app, 0.5)
        check("вкладка завдань активна",
              app.bottom_tabs.select() == str(app.task_center),
              app.bottom_tabs.select())

        # ── черга з реальними станами
        app.task_queue.clear()
        app.task_queue.set_paused(False)
        app.executor.stopped = False
        owner = app._active_chat_id()
        steps = app.task_queue.add_steps([
            {"text": "Аналіз структури проєкту та стеку",
             "detail": "Прочитати конфігурацію", "tools": ["list_dir"]},
            {"text": "Створити файл app.py", "depends_on": [1]},
            {"text": "Перевірити працездатність", "depends_on": [2]},
        ], chat_id=owner, goal="зробити застосунок")
        app._update_queue_badge()
        pump(app, 0.5)

        check("нумерація кроків від 01", [t.number for t in steps] == [1, 2, 3],
              str([t.number for t in steps]))
        check("рядки намальовано", len(app.task_center._rows) == 3,
              str(len(app.task_center._rows)))
        check("лічильник «усього»", app.task_center.count_labels["total"].cget("text") == "3",
              app.task_center.count_labels["total"].cget("text"))
        check("лічильник «у черзі»",
              app.task_center.count_labels["pending"].cget("text") == "3",
              app.task_center.count_labels["pending"].cget("text"))

        # Заблоковані кроки: другий і третій чекають на перший.
        waiting = app.task_queue.waiting_on_dependencies(chat_id=owner)
        check("залежні кроки чекають", len(waiting) == 2, str(len(waiting)))

        # ── деталі кроку
        app.task_center.select(steps[0].id)
        pump(app, 0.4)
        check("заголовок деталей", "01" in app.task_center.detail_title.cget("text"),
              app.task_center.detail_title.cget("text"))
        texts = _labels(app.task_center.detail_body)
        joined = " | ".join(texts)
        check("деталі: що потрібно зробити", "ЩО ПОТРІБНО БУЛО ЗРОБИТИ" in joined)
        check("деталі: загальна мета", "ЗАГАЛЬНА МЕТА" in joined)
        check("деталі: інструменти", "ІНСТРУМЕНТИ" in joined and "list_dir" in joined)
        check("деталі: журнал дій", "ЩО ЗРОБИЛА МОДЕЛЬ" in joined)

        # ── пауза / продовження
        app.pause_queue()
        pump(app, 0.3)
        check("пауза діє", app.task_queue.paused)
        check("на паузі крок не береться", app.executor.next_task() is None)
        app.resume_queue()
        pump(app, 0.3)
        check("продовження знімає паузу", not app.task_queue.paused)

        # ── активний крок: статус і підпис операції
        #
        # ВАЖЛИВО про ізоляцію. Живий агент пише ВЛАСНІ події в той самий
        # крок («Запит до qwen…», «Доказів недостатньо…»), і вони законно
        # перекривають підпис, який ми щойно поставили. Тому підпис
        # перевіряємо ОДРАЗУ після ``note_step``, не даючи циклу подій
        # вставити свою подію (раніше тут був ``pump(0.4)``, і тест падав
        # з «Запит до qwen…» — це поведінка системи, а не дефект).
        app.task_queue.mark_running(steps[0].id)
        app.executor.current_id = steps[0].id
        app.executor.note_step("read_file(app.py)")
        live = app.task_queue.get(steps[0].id)
        check("видно поточну операцію", "read_file" in live.current_step,
              live.current_step)
        pump(app, 0.4)
        check("активний крок «виконується»", live.status == queue_engine.RUNNING,
              live.status)
        stage = app.task_center.stage_label.cget("text")
        check("шапка показує активність", "01" in stage or "викон" in stage.lower(), stage)

        # ── зупинка
        app._plan_step_active = True
        app.stop_plan()
        pump(app, 0.3)
        check("зупинка призупиняє крок",
              app.task_queue.get(steps[0].id).status == queue_engine.PAUSED,
              app.task_queue.get(steps[0].id).status)
        app._plan_step_active = False

        # ── продовження після зупинки
        # «Продовжити» — явна дія користувача, тому вона не лише знімає
        # паузу, а й одразу відновлює роботу над кроком: крок переходить у
        # «очікує» (і далі в активний стан), але НЕ лишається призупиненим.
        app.resume_queue()
        pump(app, 0.4)
        resumed = app.task_queue.get(steps[0].id)
        check("продовження знімає «призупинено»",
              resumed.status != queue_engine.PAUSED, resumed.status)
        check("продовження відновлює роботу кроку",
              resumed.status in (queue_engine.PENDING, queue_engine.ANALYZING,
                                 queue_engine.RUNNING, queue_engine.DONE),
              resumed.status)
        # Прибираємо активний крок, щоб наступні перевірки були стабільні.
        # «Продовжити» могло справді віддати крок агенту — спиняємо його,
        # щоб тест не чекав на відповідь моделі.
        if app.agent.busy:
            app.agent.cancel()
            pump(app, 0.6)
        if app.task_queue.running_id:
            app.task_queue.mark_failed(app.task_queue.running_id, "тест")
        app._plan_step_active = False
        app.executor.current_id = ""
        app._running_task_id = ""
        pump(app, 0.2)

        # ── повтор невдалого
        app.task_queue.mark_failed(steps[1].id, "тестова помилка")
        app._update_queue_badge()
        pump(app, 0.3)
        check("лічильник помилок", app.task_center.count_labels["errors"].cget("text") == "1",
              app.task_center.count_labels["errors"].cget("text"))
        app.retry_plan_task(steps[1].id)
        pump(app, 0.3)
        check("повтор повертає в чергу",
              app.task_queue.get(steps[1].id).status == queue_engine.PENDING,
              app.task_queue.get(steps[1].id).status)

        # ── очищення завершених
        app.task_queue.mark_done(steps[0].id, "готово")
        app._update_queue_badge()
        pump(app, 0.3)
        app.clear_plan_finished()
        pump(app, 0.3)
        check("завершені прибрано",
              all(t.status != queue_engine.DONE for t in app.task_queue.tasks),
              str([t.status for t in app.task_queue.tasks]))

        # ── збереження на диску
        check("черга пише файл", app.task_queue.path.exists(), str(app.task_queue.path))

        # ── колонка контексту показує стан агента
        app._update_queue_badge()
        pump(app, 0.3)
        agent_join = " | ".join(_labels(app.context.agent_section["body"]))
        check("контекст: стан агента", "модель" in agent_join.lower(), agent_join[:60])
        project_join = " | ".join(_labels(app.context.project_section["body"]))
        check("контекст: проєкт", "blackchpock" in project_join.lower(), project_join[:60])
        tools_join = " | ".join(_labels(app.context.tools_section["body"]))
        check("контекст: інструменти", "read_file" in tools_join, tools_join[:60])

        # ── вузьке вікно
        app.geometry("1180x720")
        pump(app, 0.8)
        app.update_idletasks()
        check("вузьке вікно: центр живий", app.task_center.winfo_exists() == 1)
        narrow_detail = app.task_center.detail_host.winfo_width()
        narrow_list = app.task_center.list_view.winfo_width()
        check("вузьке вікно: деталі мають місце", narrow_detail > 120,
              f"{narrow_detail} px")
        check("вузьке вікно: список ширший за деталі",
              narrow_list > narrow_detail,
              f"список {narrow_list} / деталі {narrow_detail}")

        # Панель розтягнута на весь екран (``state("zoomed")``), тож
        # ``geometry()`` тут не діє — перевіряємо ПРОПОРЦІЮ колонок:
        # деталі мають отримати свою частку, а не залишок у кілька пікселів.
        app.update_idletasks()
        body_width = app.task_center.detail_host.winfo_width() + narrow_list
        share = narrow_detail / max(1, body_width)
        check("деталі мають свою частку ширини", 0.25 <= share <= 0.6,
              f"{share:.0%} від {body_width} px")
    finally:
        try:
            app.agent.cancel()
            app.task_queue.clear()
            app.destroy()
        except Exception:  # noqa: BLE001
            pass
        pump(app, 0.2)

    print()
    print(f"Перевірено тверджень: {checked}")
    print("Центр завдань:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
