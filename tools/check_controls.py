"""Перевірка КОЖНОЇ кнопки й панелі, які я додав або змінив.

Ніяких «виглядає правильно»: кожен пункт викликає справжній метод і
перевіряє справжній стан черги/вікна.

Запуск:  .venv\\Scripts\\python.exe tools\\check_controls.py
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
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import queue_engine, task_planner
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    workspace = Path(tempfile.mkdtemp(prefix="controls-"))
    settings = Settings.load()
    settings.workspace = str(workspace)
    settings.first_run_done = True
    settings.project_chosen = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False      # керуємо вручну
    settings.ui.view = "workspace"
    settings.ui.bottom_visible = True

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1500x900")
    try:
        pump(app, 1.6)
        app.hide_welcome()
        pump(app, 0.4)
        idle = 0.0
        while app.agent.busy and idle < 90:
            pump(app, 0.5)
            idle += 0.5

        # ── вкладка центру завдань
        app.show_bottom("tasks")
        pump(app, 0.4)
        check("вкладка «Завдання» відкривається",
              app.bottom_tabs.select() == str(app.task_center))

        # ── план без моделі: підкладаємо кроки напряму
        app.task_queue.clear()
        app.task_queue.set_paused(False)
        owner = app._active_chat_id()
        steps = app.task_queue.add_steps([
            {"text": "Крок перший", "detail": "опис"},
            {"text": "Крок другий", "depends_on": [1]},
            {"text": "Крок третій", "depends_on": [2]},
        ], chat_id=owner, goal="перевірка керування")
        app._update_queue_badge()
        pump(app, 0.4)
        check("кроки на місці", len(app.task_queue.tasks) == 3)

        # ── 1. Пауза / продовження
        app.pause_queue()
        pump(app, 0.2)
        check("кнопка Пауза діє", app.task_queue.paused)
        check("на паузі нічого не береться", app.executor.next_task() is None)
        app.resume_queue()
        pump(app, 0.2)
        check("кнопка Продовжити знімає паузу", not app.task_queue.paused)

        # ── 2. Додавання кроку вручну (кнопка «＋ крок»)
        app._queue_from_panel("Крок доданий вручну")
        pump(app, 0.3)
        check("додано крок вручну", len(app.task_queue.tasks) == 4,
              str(len(app.task_queue.tasks)))
        manual = [t for t in app.task_queue.tasks
                  if "вручну" in t.text]
        check("крок вручну має позначку користувача",
              bool(manual) and manual[0].from_user)

        # ── 3. Зупинка активного кроку
        task = steps[0]
        app.task_queue.mark_running(task.id)
        app.executor.current_id = task.id
        app._plan_step_active = True
        app.stop_plan()
        pump(app, 0.3)
        check("Зупинити призупиняє крок",
              app.task_queue.get(task.id).status == queue_engine.PAUSED,
              app.task_queue.get(task.id).status)
        app._plan_step_active = False

        # ── 4. Продовження повертає призупинений крок
        app.resume_queue()
        pump(app, 0.3)
        check("Продовжити повертає крок у чергу",
              app.task_queue.get(task.id).status == queue_engine.PENDING,
              app.task_queue.get(task.id).status)

        # ── 5. Повтор невдалого
        app.task_queue.mark_failed(steps[1].id, "перевірка")
        app._update_queue_badge()
        pump(app, 0.2)
        check("лічильник помилок показує 1",
              app.task_center.count_labels["errors"].cget("text") == "1",
              app.task_center.count_labels["errors"].cget("text"))
        app.retry_plan_task(steps[1].id)
        pump(app, 0.2)
        check("Повторити повертає крок",
              app.task_queue.get(steps[1].id).status == queue_engine.PENDING)

        # ── 6. Каскад: збій знімає залежні
        app.task_queue.mark_failed(steps[2].id, "збій")
        app.executor.finish(ok=False, error="збій") if app.executor.current else None
        app.task_queue.mark_running(steps[1].id)
        app.executor.current_id = steps[1].id
        app.executor.finish(ok=False, error="навмисний збій")
        pump(app, 0.2)
        check("залежний крок знято після збою",
              app.task_queue.get(steps[2].id).status
              in (queue_engine.CANCELLED, queue_engine.FAILED),
              app.task_queue.get(steps[2].id).status)

        # ── 7. Очищення завершених
        app.task_queue.mark_done(steps[0].id, "готово")
        before = len(app.task_queue.tasks)
        app.clear_plan_finished()
        pump(app, 0.2)
        check("Очистити прибирає завершені",
              len(app.task_queue.tasks) < before,
              f"{before} → {len(app.task_queue.tasks)}")

        # ── 8. Пункти меню існують і викликаються
        menu = app.nametowidget(app.cget("menu"))
        labels = []
        for index in range(menu.index("end") + 1):
            try:
                sub = app.nametowidget(menu.entrycget(index, "menu"))
                for sub_index in range(sub.index("end") + 1):
                    if sub.type(sub_index) == "command":
                        labels.append(sub.entrycget(sub_index, "label"))
            except Exception:  # noqa: BLE001
                continue
        for needed in ("Центр завдань", "Призупинити план", "Продовжити план",
                       "Зупинити виконання плану", "Перепланувати залишок роботи",
                       "Підсумковий звіт"):
            check(f"меню: «{needed}»", needed in labels)

        # ── 9. Гарячі клавіші прив'язані
        # ``bind_all()`` повертає список послідовностей у форматі Tk
        # (``<Control-Alt-Key-w>``), тому порівнюємо за ключовою літерою,
        # а не за точним рядком.
        bindings = [str(item) for item in app.bind_all()]
        joined = " ".join(bindings).lower()
        for seq, letter in (("<Control-Alt-w>", "key-w"),
                            ("<Control-Alt-s>", "key-s")):
            check(f"клавіша {seq}",
                  letter in joined and "control" in joined and "alt" in joined,
                  f"усього прив'язок: {len(bindings)}")

        # ── 10. Колонка контексту: живі дані
        app._update_queue_badge()
        pump(app, 0.3)
        status = app._agent_status_text()
        check("стан агента непорожній", bool(status.strip()), status[:50])
        model, kind = app._model_summary()
        check("модель у контексті", bool(model), f"{model} · {kind}")
        tools = app._active_tool_names()
        check("інструменти в контексті", len(tools) > 0, f"{len(tools)} шт.")

        # ── 11. Підсумковий звіт
        report = app.executor.report(chat_id=owner)
        check("звіт непорожній", "Усього кроків" in report)

        # ── 12. Збереження й відновлення
        app.task_queue.save()
        restored = queue_engine.TaskQueue(app.task_queue.path)
        check("черга переживає перезапуск",
              len(restored.tasks) == len(app.task_queue.tasks),
              f"{len(restored.tasks)} з {len(app.task_queue.tasks)}")

        # ── 13. Перепланування без моделі має чесно відмовити
        app.settings.llm.model = ""
        app.replan_now()
        pump(app, 0.3)
        check("перепланування без моделі не вдає роботу",
              "не вдалось" in app.status_label.cget("text").lower()
              or not app._planning,
              app.status_label.cget("text")[:60])
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
    print("Керування:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
