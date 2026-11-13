"""Живе вікно: чи справді є пункт меню, діалог і питання в чаті.

Перевіряємо ІНТЕРФЕЙС, а не логіку: логіка вже покрита
``tests/test_git_publish.py`` і ``tests/live_git_offer.py``. Тут важливо,
що користувач СПРАВДІ побачить питання й зможе натиснути «Так».

Запуск: python tests/live_git_ui.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}"
          f"{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1
    return bool(condition)


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main() -> int:
    if shutil.which("git") is None:
        print("[SKIP] git не встановлено")
        return 0

    import tkinter.messagebox as mb

    from blackchpok_ide import git_repo
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()

    tmp = Path(tempfile.mkdtemp(prefix="live-git-ui-"))
    remote = tmp / "origin.git"
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    work = tmp / "project"
    work.mkdir()
    for args in (("init", "--initial-branch=main"),
                 ("config", "user.name", "Тест"),
                 ("config", "user.email", "test@example.com"),
                 ("remote", "add", "origin", str(remote))):
        git(work, *args)
    (work / "app.py").write_text("print('v1')\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-m", "початок")
    git(work, "push", "-u", "origin", "main")

    settings = Settings()
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.workspace = str(work)
    settings.project_chosen = True
    settings.agent.git_offer_publish = True

    # Діалоги не мають чекати людину; фіксуємо, що нас СПИТАЛИ.
    asked: list[str] = []
    mb.askyesno = lambda title, question, **k: (asked.append(question), True)[1]
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None

    from blackchpok_ide.main_window import BlackChpokIDE

    print("=== 1. Відкриваю вікно ===")
    app = BlackChpokIDE(settings)
    app._adopt_local_model = lambda: None
    app.geometry("1400x860")
    pump(app, 2.0)
    check("вікно створено", app.winfo_exists() == 1)

    print()
    print("=== 2. Пункт меню «Оновити файли на GitHub…» ===")
    from blackchpok_ide import commands

    names = {command.key for command in commands.all_commands()}
    check("команда зареєстрована", "git.publish" in names)
    command = next((item for item in commands.all_commands()
                    if item.key == "git.publish"), None)
    check("підпис зрозумілий", bool(command) and "GitHub" in command.label,
          command.label if command else "—")
    check("у групі «git»", bool(command) and command.group == "git",
          command.group if command else "—")

    print()
    print("=== 3. Вікно вміє показати питання й відправити ===")
    check("є обробник питання", hasattr(app, "_on_git_offer"))
    check("є спільна точка відправки", hasattr(app, "github_publish"))
    check("чат підключений до питання", app.chat.on_git_offer is not None)

    print()
    print("=== 4. Діалог показує СПРАВЖНІ дані й відправляє ===")
    (work / "app.py").write_text("print('v2 — після агента')\n", encoding="utf-8")
    current = git_repo.state(work)
    app._on_git_offer({
        "remote": current.remote,
        "branch": current.branch,
        "changed": current.changed,
        "message": "оновлено app.py (BlackChpok IDE)",
    })
    check("людину запитали", len(asked) == 1, f"{len(asked)} діалогів")
    if asked:
        text = asked[0]
        check("у діалозі є адреса", str(remote) in text or "origin" in text)
        check("у діалозі є гілка", "main" in text)
        check("у діалозі є файл", "app.py" in text)
    # Відправка йде у фоні — чекаємо, доки коміт з'явиться на «GitHub».
    pushed = False
    for _ in range(100):
        pump(app, 0.2)
        if git(remote, "log", "--oneline", "main").stdout.count("\n") == 2:
            pushed = True
            break
    check("зміни дійшли до репозиторію", pushed,
          git(remote, "log", "--oneline", "main").stdout.strip())

    print()
    print("=== 5. «Ні» не відправляє нічого ===")
    mb.askyesno = lambda *a, **k: False
    (work / "app.py").write_text("print('v3')\n", encoding="utf-8")
    before = git(remote, "log", "--oneline", "main").stdout
    app._on_git_offer({"remote": current.remote, "branch": "main",
                       "changed": ["app.py"], "message": "x"})
    pump(app, 1.5)
    after = git(remote, "log", "--oneline", "main").stdout
    check("після «Ні» нічого не поїхало", before == after,
          f"комітів було {before.count(chr(10))}, стало {after.count(chr(10))}")

    app.destroy()
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("Git у вікні: " + ("успішно" if not failures else f"збоїв {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
