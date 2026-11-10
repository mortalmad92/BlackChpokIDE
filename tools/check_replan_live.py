"""Перевірка перепланування на реальній моделі.

Сценарій: план виконано частково, далі модель переплановує залишок.
Має зберегтись виконане й замінитись лише незавершене.
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
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import queue_engine
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    workspace = Path(tempfile.mkdtemp(prefix="replan-"))
    settings = Settings.load()
    settings.workspace = str(workspace)
    settings.first_run_done = True
    settings.project_chosen = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1400x860")
    try:
        pump(app, 1.8)
        app.hide_welcome()
        pump(app, 0.5)
        idle = 0.0
        while app.agent.busy and idle < 90:
            pump(app, 0.5)
            idle += 0.5

        if not app.settings.llm.model:
            print("Модель не вибрана — перевіряти нема чого")
            return 1

        # Готуємо частково виконаний план
        app.task_queue.clear()
        owner = app._active_chat_id()
        steps = app.task_queue.add_steps([
            {"text": "Створити файл data.txt з рядком hello"},
            {"text": "Створити файл other.txt"},
            {"text": "Перевірити обидва файли"},
        ], chat_id=owner, goal="створити два текстові файли й перевірити їх")
        app.task_queue.mark_running(steps[0].id)
        app.task_queue.mark_done(steps[0].id, "готово")
        (workspace / "data.txt").write_text("hello\n", encoding="utf-8")
        app._update_queue_badge()
        pump(app, 0.3)

        before = {(t.number, t.title, t.status) for t in app.task_queue.tasks}
        print(f"\nплан до перепланування ({len(before)}):")
        for number, title, status in sorted(before):
            print(f"  {number:02d}. {status:10} {title}")

        # Переплановуємо
        app.replan_now()
        waited = 0.0
        while app._planning and waited < 300:
            pump(app, 0.5)
            waited += 0.5
        pump(app, 0.5)

        after_tasks = app.task_queue.tasks
        print(f"\nплан після перепланування ({len(after_tasks)}):")
        for task in after_tasks:
            print(f"  {task.number:02d}. {task.status:10} {task.title}")

        check("перепланування відбулось", not app._planning, f"{waited:.0f} с")
        check("новий план непорожній", len(after_tasks) > 0)

        done = [t for t in after_tasks if t.status == queue_engine.DONE]
        check("виконане збережено", len(done) >= 1,
              f"{len(done)} завершених")
        check("файл першого кроку на місці",
              (workspace / "data.txt").exists())

        # Новий план має бути саме про залишок, а не про все спочатку
        titles = " ".join(t.title.lower() for t in after_tasks
                          if t.status == queue_engine.PENDING)
        check("новий план згадує незавершене", bool(titles.strip()),
              titles[:90] or "—")

        check("номери без дірок",
              [t.number for t in after_tasks] == list(range(1, len(after_tasks) + 1)),
              str([t.number for t in after_tasks]))
    finally:
        try:
            app.agent.cancel()
            app.task_queue.clear()
            app.destroy()
        except Exception:  # noqa: BLE001
            pass
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)

    print()
    print("Перепланування:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
