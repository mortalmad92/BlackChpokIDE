"""Перевірка захисту від синтаксичних помилок при записі файлів."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="syntax-"))
    registry = ToolRegistry(workspace)

    # Апостроф усередині одинарних лапок — класична помилка локальної моделі
    bad_python = "name = input('Введіть ім'я: ')\nprint(name)"
    result = registry.call("write_file", {"path": "bad.py", "content": bad_python})
    check("поганий Python: файл записано", (workspace / "bad.py").exists())
    check("поганий Python: попередження в результаті",
          "синтаксична помилка" in result.output.lower(), result.output[:90])
    check("поганий Python: названо рядок",
          "рядок" in result.output.lower(), result.output[:110])

    # Правильний код — без попереджень
    good = 'name = input("Введіть ім\'я: ")\nprint(f"Привіт, {name}!")'
    result = registry.call("write_file", {"path": "good.py", "content": good})
    check("добрий Python: без попереджень",
          "синтаксична помилка" not in result.output.lower(), result.output[:80])
    check("добрий Python: файл створено", (workspace / "good.py").exists())

    # Зламаний JSON — теж ловимо
    result = registry.call("write_file",
                           {"path": "bad.json", "content": '{"a": 1,}'})
    check("поганий JSON: попередження",
          "помилка" in result.output.lower() or "json" in result.output.lower(),
          result.output[:90])

    # Не-Python текст не перевіряємо
    result = registry.call("write_file",
                           {"path": "note.txt", "content": "ім'я і м'яч"})
    check("текстовий файл без попереджень",
          "синтаксична" not in result.output.lower(), result.output[:70])

    # edit_file теж перевіряє
    registry.call("write_file", {"path": "edit.py", "content": "x = 1\n"})
    result = registry.call("edit_file", {
        "path": "edit.py", "old_string": "x = 1",
        "new_string": "x = 'незакритий"})
    check("edit_file ловить зламаний синтаксис",
          "синтаксична помилка" in result.output.lower(), result.output[:90])

    print()
    print("Захист синтаксису:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
