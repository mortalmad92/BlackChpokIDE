"""Наскрізна перевірка: IDE сама запускає модель, планує й виконує кроки.

Це найважливіший тест роботоздатності: береться порожня тека, IDE піднімає
локальну модель своїм рушієм, складає план і виконує його справжніми
інструментами агента.

Запуск:  .venv\\Scripts\\python.exe tools\\check_full_cycle.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOAL = (
    "Створи в теці файл greeting.py з функцією hello(name), яка повертає "
    "рядок привітання, і файл test_greeting.py з одним тестом для неї. "
    "Потім запусти тести."
)


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            return
        time.sleep(0.01)


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import queue_engine
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    workspace = Path(tempfile.mkdtemp(prefix="fullcycle-"))
    print("тека проєкту:", workspace)
    print("модель:", Settings.load().llm.model)
    print()

    settings = Settings.load()
    settings.workspace = str(workspace)
    settings.first_run_done = True
    settings.project_chosen = True
    # Модель уже працює на 8080 — IDE має підхопити її й не піднімати вдруге.
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = True
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1400x880")
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures += 1

    try:
        pump(app, 2.0)
        app.hide_welcome()
        pump(app, 0.5)
        idle = 0.0
        while app.agent.busy and idle < 120:
            pump(app, 0.5)
            idle += 0.5

        # 1. Модель доступна й обрана
        check("модель вибрана", bool(app.settings.llm.model), app.settings.llm.model)
        check("сервер моделі відповідає", app._server_alive())
        model, kind = app._model_summary()
        check("панель контексту бачить модель", model != "не вибрана", f"{model} · {kind}")

        # 2. План складає локальна модель
        before = len(app.task_queue.tasks)
        print(f"\n   задач у черзі до планування: {before}")
        if before:
            print("   УВАГА: черга не порожня — можливі дублі між прогонами")
            for task in app.task_queue.tasks:
                print(f"     {task.number or '--'} {task.status}: {task.title[:50]}")
        started = time.time()
        app._split_task_to_queue(GOAL)
        while app._planning and time.time() - started < 400:
            pump(app, 0.5)
        pump(app, 0.5)
        tasks = app.task_queue.tasks
        check("модель склала план", len(tasks) >= 3, f"{len(tasks)} кроків за {time.time()-started:.0f} с")
        check("кроки пронумеровані", all(t.number for t in tasks),
              str([t.number for t in tasks]))
        check("у кроків є залежності", any(t.depends_on for t in tasks))
        print("\n   план:")
        for task in tasks:
            print(f"     {task.number:02d}. {task.title[:62]}")

        # 3. Виконання справжнім агентом
        print("\n   виконую…")
        started = time.time()
        stall = 0.0
        last_done = -1
        while time.time() - started < 600:
            pump(app, 0.5)
            progress = app.task_queue.progress()
            if progress["done"] != last_done:
                last_done = progress["done"]
                stall = 0.0
            else:
                stall += 0.5
            if app.task_queue.paused:
                app.resume_queue()
            if not app.task_queue.running_id and not app.agent.busy:
                if app.executor.next_task() is None:
                    break
                app.executor.start_next()
            if stall > 150:
                check("немає зависання", False, f"стояло {stall:.0f} с")
                break

        progress = app.task_queue.progress()
        elapsed = time.time() - started
        print(f"\n   готово за {elapsed:.0f} с: {progress}")
        check("усі кроки завершено", progress["pending"] == 0 and progress["active"] == 0,
              str(progress))
        check("жодного збою", progress["errors"] == 0, str(progress["errors"]))

        # Діагностика збоїв: показуємо ПРИЧИНУ кожного невдалого кроку —
        # без цього незрозуміло, чому локальна модель іноді не дає результату.
        for task in app.task_queue.tasks:
            if task.status == queue_engine.FAILED:
                print(f"\n   ЗБІЙ кроку {task.number:02d}: {task.title[:60]}")
                print(f"      причина: {task.error[:300]}")
                print(f"      файли: {task.files_changed}")
                print(f"      спроб: {task.attempts}")
                for entry in task.history[-8:]:
                    print(f"      · [{entry.get('kind')}] "
                          f"{str(entry.get('text'))[:150]}")

        # 4. Результат СПРАВДІ на диску
        files = sorted(p.name for p in workspace.iterdir() if p.is_file())
        print("   файли:", files)
        check("агент створив файли", any(f.endswith(".py") for f in files), str(files))
        greeting = workspace / "greeting.py"
        if greeting.exists():
            body = greeting.read_text(encoding="utf-8", errors="replace")
            check("у файлі є функція hello", "def hello" in body, body[:60].replace("\n", " "))

        # 5. Звіт і збереження
        report = app.executor.report(chat_id=app._active_chat_id())
        check("звіт сформовано", "Усього кроків" in report)
        check("черга збережена", app.task_queue.path.exists())

        # 6. Перезапуск: черга й статуси відновлюються
        app.task_queue.save()
        restored = queue_engine.TaskQueue(app.task_queue.path)
        check("після перезапуску статуси збережено",
              len(restored.tasks) == len(app.task_queue.tasks),
              f"{len(restored.tasks)} з {len(app.task_queue.tasks)}")
        check("жоден крок не «висить» активним",
              not any(t.active for t in restored.tasks))
    finally:
        try:
            app.agent.cancel()
            app.destroy()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(workspace, ignore_errors=True)

    print()
    print("Повний цикл:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
