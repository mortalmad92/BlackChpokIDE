"""Перевірка пробного запуску created-скрипта: успіх і помилка виконання."""

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


def _runner() -> tuple[AgentRunner, Path]:
    workspace = Path(tempfile.mkdtemp(prefix="smoke-"))
    settings = Settings.load()
    runner = AgentRunner(ToolRegistry(workspace), settings.llm,
                         settings.agent, workspace)
    runner._smoke_done = False
    runner._touched_files = []
    return runner, workspace


def main() -> int:
    # 1. Коректний скрипт — помилки немає
    runner, workspace = _runner()
    runner.call_tool("write_file", {"path": "ok.py",
                                    "content": "print('привіт')\n"})
    detected = runner._run_smoke_check()
    check("коректний скрипт не дає помилки", not detected, str(detected))

    # 2. Скрипт падає під час виконання (синтаксис цілий)
    runner, workspace = _runner()
    runner.call_tool("write_file", {
        "path": "boom.py",
        "content": ("def f(numbers):\n"
                    "    return sum(numbers) / (len(numbers) - 1)\n\n"
                    "print(f([5]))\n")})
    detected = runner._run_smoke_check()
    check("помилка виконання помічена", detected, str(detected))
    last = runner.session.messages[-1] if runner.session.messages else {}
    check("модель отримує traceback",
          "Traceback" in str(last.get("content", "")),
          str(last.get("content", ""))[:100])

    # 3. Інтерактивний скрипт НЕ запускаємо (інакше зависне)
    runner, workspace = _runner()
    runner.call_tool("write_file", {
        "path": "ask.py",
        "content": "name = input('ім\\'я? ')\nprint(name)\n"})
    detected = runner._run_smoke_check()
    check("скрипт з input не запускається", not detected, str(detected))

    # 4. Повторний виклик не запускає вдруге
    runner, workspace = _runner()
    runner.call_tool("write_file", {"path": "a.py", "content": "print(1)\n"})
    runner._run_smoke_check()
    check("повторний запуск не дублюється",
          runner._run_smoke_check() is False, "ok")

    # 5. Без записаних файлів — нічого не робимо
    runner, workspace = _runner()
    check("без файлів перевірки немає",
          runner._run_smoke_check() is False, "ok")

    print()
    print("Пробний запуск:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
