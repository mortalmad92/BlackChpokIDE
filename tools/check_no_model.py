"""Перевірка поведінки БЕЗ моделі — найчастіший стан нового користувача.

Програма не має падати, вдавати роботу чи мовчки стояти: кожна дія мусить
дати зрозуміле повідомлення українською.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            return
        time.sleep(0.01)


def main() -> int:
    import os
    import tempfile as _tempfile

    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    # ІЗОЛЯЦІЯ: ця перевірка ламає адресу моделі, тому працює у ВЛАСНІЙ
    # теці налаштувань. Інакше спільний settings.json лишався з мертвою
    # адресою 127.0.0.1:9, і наступні тести (автономний режим наживо)
    # падали з «немає з'єднання» — саме це й сталося під час повного прогону.
    isolated_home = Path(_tempfile.mkdtemp(prefix="nomodel-home-"))
    previous_home = os.environ.get("BLACKCHPOK_HOME")
    os.environ["BLACKCHPOK_HOME"] = str(isolated_home)

    from blackchpok_ide import queue_engine, task_planner
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    workspace = Path(_tempfile.mkdtemp(prefix="nomodel-"))
    settings = Settings.load()
    settings.workspace = str(workspace)
    settings.first_run_done = True
    settings.project_chosen = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"

    # Моделі немає й сервер недоступний.
    #
    # ВАЖЛИВО: ``_adopt_local_model`` на старті підхоплює будь-яку модель,
    # яку бачить локальний сервер — це ПРАВИЛЬНА поведінка (інакше агент
    # писав би «модель не вибрана», хоч вона вже працює). Тому після
    # створення вікна гасимо модель примусово, щоб перевірити саме
    # сценарій «нічого немає».
    settings.llm.model = ""
    settings.llm.base_url = "http://127.0.0.1:9/v1"   # гарантовано закритий

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1400x860")
    try:
        pump(app, 1.6)
        app.hide_welcome()
        pump(app, 0.5)

        # Гасимо модель після старту — перевіряємо роботу «з нуля».
        app.settings.llm.model = ""
        app.settings.llm.base_url = "http://127.0.0.1:9/v1"
        app.chat.set_model_label("модель не вибрана")

        check("вікно відкрилось без моделі", app.winfo_exists() == 1)
        check("модель чесно «не вибрана»",
              "не вибрана" in app._model_summary()[0],
              app._model_summary()[0])

        # Планувальник має чесно відмовити
        result = task_planner.plan_with_model(
            "зроби щось велике", app.settings.llm)
        check("планувальник відмовляє чесно", not result.ok, result.error[:90])
        check("причина зрозуміла й українською",
              any(word in result.error for word in
                  ("Модель не вибрана", "Немає з'єднання", "недоступ")),
              result.error[:90])

        # Розбиття через UI: має поставити ОДИН крок, а не вдати план
        app.task_queue.clear()
        app._split_task_to_queue("Створи великий вебсайт із базою даних і кабінетом")
        waited = 0.0
        while app._planning and waited < 120:
            pump(app, 0.5)
            waited += 0.5
        pump(app, 0.5)
        tasks = app.task_queue.tasks
        check("завдання не загубилось", len(tasks) >= 1, f"{len(tasks)} кроків")
        check("без моделі — один крок, а не вигаданий план",
              len(tasks) == 1, f"{len(tasks)}")
        check("план не склався — причина названа",
              "план не склався" in app.status_label.cget("text").lower()
              or "не склався" in app.status_label.cget("text").lower(),
              app.status_label.cget("text")[:80])

        # Центр завдань малює цей крок без помилок
        app.show_bottom("tasks")
        pump(app, 0.4)
        check("центр завдань живий", bool(app.task_center._rows), "рядки є")

        # Запуск кроку без моделі не має «зависати»
        app.executor.start_next()
        waited = 0.0
        while app.executor.current is not None and waited < 60:
            pump(app, 0.5)
            waited += 0.5
        step = app.task_queue.tasks[0]
        check("крок завершився, а не завис",
              step.status in (queue_engine.DONE, queue_engine.FAILED),
              step.status)

        # Перепланування чесно відмовляє
        app.replan_now()
        pump(app, 0.3)
        check("перепланування без моделі не бреше",
              "не вдалось" in app.status_label.cget("text").lower()
              or not app._planning,
              app.status_label.cget("text")[:60])

        # Звичайний чат: агент має сказати про проблему, а не мовчати
        app.chat._send("привіт")
        waited = 0.0
        while app.agent.busy and waited < 60:
            pump(app, 0.5)
            waited += 0.5
        pump(app, 0.5)
        check("чат не завис без моделі", not app.agent.busy)
    finally:
        try:
            app.agent.cancel()
            app.task_queue.clear()
            app.destroy()
        except Exception:  # noqa: BLE001
            pass
        import shutil

        # Прибираємо ІЗОЛЬОВАНУ теку налаштувань і повертаємо змінну.
        if previous_home is None:
            os.environ.pop("BLACKCHPOK_HOME", None)
        else:
            os.environ["BLACKCHPOK_HOME"] = previous_home
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(isolated_home, ignore_errors=True)

    print()
    print("Робота без моделі:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
