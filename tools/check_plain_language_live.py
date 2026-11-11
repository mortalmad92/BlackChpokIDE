"""Наскрізна перевірка: чи виконує агент задачі, описані простими словами.

Кожен сценарій — це побутова фраза й очікуваний ФАКТ на диску. Ніяких
оцінок «схоже, зрозумів»: перевіряємо, що файл справді створено й у ньому
є те, що просили.

Запуск:  .venv\\Scripts\\python.exe tools\\check_plain_language_live.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: (назва, фраза як каже людина, перевірка вмісту теки)
SCENARIOS: list[tuple[str, str, list[str]]] = [
    ("калькулятор",
     "зроби мені калькулятор на пітоні",
     [".py"]),
    ("привітання",
     "напиши програму яка питає ім'я і вітається",
     [".py"]),
    ("файл із текстом",
     "створи файл notes.txt і запиши туди три рядки про проєкт",
     [".txt"]),
]


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

    from blackchpok_ide import queue_engine, task_plan
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures += 1

    for title, phrase, suffixes in SCENARIOS:
        workspace = Path(tempfile.mkdtemp(prefix="plain-"))
        print()
        print("=" * 76)
        print(f"СЦЕНАРІЙ: {title}")
        print(f"фраза: «{phrase}»")
        info = task_plan.understand(phrase)
        print(f"зрозумілий намір: {','.join(info.intents)} · "
              f"інструменти: {', '.join(task_plan.tools_for_stage(phrase))}")
        print("=" * 76)

        settings = Settings.load()
        settings.workspace = str(workspace)
        settings.first_run_done = True
        settings.project_chosen = True
        # Автозапуск НЕ вимикаємо: перевірка має поводитись як справжній
        # користувач, який просто відкрив IDE. Раніше тут стояло
        # ``auto_start = False`` (залишок від часів llama-server на 8080),
        # і модель не піднімалась узагалі — усі три сценарії падали з
        # «файлів на диску: []», хоч намір був правильний.
        settings.engine.auto_start = True
        settings.agent.queue_auto_run = False
        # Достатньо кроків на: читання, запис, перевірку синтаксису й
        # виправлення. Типових 8 мало, коли модель спершу читає файл.
        settings.agent.max_steps = 12
        settings.ui.view = "workspace"

        from blackchpok_ide.main_window import BlackChpokIDE

        app = BlackChpokIDE(settings)
        app.geometry("1400x860")
        try:
            pump(app, 1.8)
            app.hide_welcome()
            pump(app, 0.4)
            idle = 0.0
            while app.agent.busy and idle < 90:
                pump(app, 0.5)
                idle += 0.5

            check(f"{title}: намір не «балачка»", info.is_action,
                  info.primary)

            # Надсилаємо фразу як звичайний користувач.
            app.chat._send(phrase)
            waited = 0.0
            while app.agent.busy and waited < 300:
                pump(app, 0.5)
                waited += 0.5
            pump(app, 0.5)

            # Якщо агент склав план — дочікуємось і виконання.
            if app._planning:
                while app._planning and waited < 400:
                    pump(app, 0.5)
                    waited += 0.5
            if app.task_queue.tasks:
                print(f"   план: {len(app.task_queue.tasks)} кроків, виконую…")
                run_started = time.time()
                stall = 0.0
                last = -1
                while time.time() - run_started < 420:
                    pump(app, 0.5)
                    progress = app.task_queue.progress()
                    if progress["done"] != last:
                        last = progress["done"]
                        stall = 0.0
                    else:
                        stall += 0.5
                    if app.task_queue.paused:
                        app.resume_queue()
                    if not app.task_queue.running_id and not app.agent.busy:
                        if app.executor.next_task() is None:
                            break
                        app.executor.start_next()
                    if stall > 180:
                        break
                print(f"   підсумок черги: {app.task_queue.progress()}")

            files = sorted(p.name for p in workspace.iterdir() if p.is_file())
            print(f"   файли на диску: {files}")
            found = [name for name in files
                     if any(name.lower().endswith(suffix) for suffix in suffixes)
                     and not name.endswith(".bak")]
            check(f"{title}: агент створив файл", bool(found), str(found))

            # У файлі має бути реальний код/текст, а не заглушка
            if found:
                body = (workspace / found[0]).read_text(
                    encoding="utf-8", errors="replace")
                check(f"{title}: файл не порожній", len(body.strip()) > 20,
                      f"{len(body)} символів")
                print(f"   початок файлу: {body[:120]!r}")
        finally:
            try:
                app.agent.cancel()
                app.task_queue.clear()
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
            shutil.rmtree(workspace, ignore_errors=True)

    print()
    print("=" * 76)
    print("Прості фрази наживо:", "успішно" if failures == 0
          else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
