"""Перевірка, чи агент помічає зламаний синтаксис у своєму ж файлі."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent import AgentRunner  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="gate-"))
    settings = Settings.load()
    runner = AgentRunner(ToolRegistry(workspace), settings.llm,
                         settings.agent, workspace)

    # Класична помилка: апостроф усередині одинарних лапок
    broken = "name = input('Введіть ім'я: ')\nprint(name)\n"
    outcome = runner.call_tool("write_file", {"path": "hello.py", "content": broken})
    check("файл записано", (workspace / "hello.py").exists())
    check("у результаті є попередження",
          "синтаксична" in outcome.output.lower(), outcome.output[:100])
    check("файл запам'ятано як змінений",
          "hello.py" in runner._touched_files, str(runner._touched_files))

    # Головне: агент має ПОМІТИТИ це перед завершенням
    detected = runner._broken_python()
    check("агент помічає зламаний синтаксис", detected, str(detected))
    last = runner.session.messages[-1] if runner.session.messages else {}
    check("модель отримує прохання виправити",
          "синтаксична помилка" in str(last.get("content", "")).lower(),
          str(last.get("content", ""))[:120])

    # Правильний файл не має викликати попереджень
    runner._touched_files = []
    runner.session.messages.clear()
    runner.call_tool("write_file", {
        "path": "good.py",
        "content": 'name = input("Введіть ім\'я: ")\nprint(name)\n'})
    check("правильний файл не вважається зламаним",
          not runner._broken_python(), "ok")

    print()
    print("Виявлення зламаного синтаксису:",
          "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
