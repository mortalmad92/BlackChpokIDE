"""Живий прогін: агент питає про GitHub і НЕ відправляє без згоди.

Перевіряється те, що просив користувач: git прив'язаний до чату й проєкту,
а агент ПИТАЄ, чи оновити файли на GitHub.

Сценарій іде через справжній ``AgentRunner`` (той самий шлях, що в GUI), а
замість GitHub — локальний bare-репозиторій: та сама семантика ``push``,
але без мережі й без потреби в токені.

Запуск: python tests/live_git_offer.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
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


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main() -> int:
    if shutil.which("git") is None:
        print("[SKIP] git не встановлено")
        return 0

    from blackchpok_ide import agent as agent_module
    from blackchpok_ide import agent_tools, chat_store, config, git_repo

    tmp = Path(tempfile.mkdtemp(prefix="live-git-"))
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

    print("=== 1. Чат прив'язаний до проєкту ===")
    store = chat_store.ChatStore(tmp / "chats.json")
    chat = store.create(title="Проєкт", workspace=str(work))
    check("чат має свою теку", chat.workspace == str(work))

    print()
    print("=== 2. Агент працює й змінює файл ===")
    settings = config.Settings()
    settings.agent.git_offer_publish = True
    registry = agent_tools.ToolRegistry(work)
    runner = agent_module.AgentRunner(registry, settings.llm,
                                      settings.agent, work)
    events: list = []

    # Імітуємо хід агента: файл змінено, ``touched_files`` заповнено.
    (work / "app.py").write_text("print('v2 — після роботи агента')\n",
                                 encoding="utf-8")
    runner._touched_files = ["app.py"]
    original = runner._emit
    runner._emit = lambda kind, text="", **data: (
        events.append((kind, text, data)), original(kind, text, **data))[0]
    runner._offer_git_publish(ok=True)
    runner._emit = original

    offers = [event for event in events if event[0] == "git_offer"]
    check("агент спитав про GitHub", len(offers) == 1,
          f"{len(offers)} подій")
    if offers:
        details = offers[0][2]
        print(f"    питання: {offers[0][1]}")
        check("у питанні є адреса", bool(details.get("remote")),
              str(details.get("remote")))
        check("у питанні є гілка", details.get("branch") == "main",
              str(details.get("branch")))
        check("у питанні є файли", "app.py" in (details.get("changed") or []),
              str(details.get("changed")))

    print()
    print("=== 3. Питання поставили — але НІЧОГО не відправлено ===")
    log_before = git(remote, "log", "--oneline", "main").stdout
    check("на GitHub ще немає нового коміту", log_before.count("\n") == 1,
          log_before.strip())

    print()
    print("=== 4. Користувач каже «так» у чаті ===")
    accepted = runner._answers_git_offer("так, онови")
    check("агент зрозумів «так»", accepted)
    check("звичайне «так» без питання не рахується",
          not agent_module.AgentRunner(registry, settings.llm,
                                       settings.agent, work)
          ._answers_git_offer("так"))

    print()
    print("=== 5. Відправка (те, що робить кнопка «Так») ===")
    result = runner.publish_to_git()
    check("відправка вдалась", result.ok, result.output)
    log_after = git(remote, "log", "--oneline", "main").stdout
    check("на GitHub з'явився новий коміт", log_after.count("\n") == 2,
          log_after.strip())
    check("у репозиторії немає .env", ".env" not in log_after)

    print()
    print("=== 6. Адреса запам'яталась для ЦЬОГО чату ===")
    current = git_repo.state(work)
    store.remember_git(chat.id, remote=current.remote)
    again = chat_store.ChatStore(tmp / "chats.json")
    check("адреса пережила перезапуск",
          bool(again.git_remote(chat.id)), again.git_remote(chat.id))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("Git-публікація: " + ("успішно" if not failures else f"збоїв {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
