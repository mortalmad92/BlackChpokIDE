"""Перевірка толерантної правки edit_file (неточний фрагмент від моделі)."""

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


SOURCE = '''"""Калькулятор."""


def add(a, b):
    return a + b


def average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)
'''


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="fuzzy-"))
    registry = ToolRegistry(workspace)
    path = workspace / "calc.py"

    # 1. Точний фрагмент — працює як раніше
    path.write_text(SOURCE, encoding="utf-8")
    out = registry.call("edit_file", {
        "path": "calc.py", "old_string": "    return a + b",
        "new_string": "    return a + b  # сума"})
    check("точний фрагмент замінено", out.ok, out.output[:60])

    # 2. Інші лапки в запиті — модель часто ставить подвійні
    path.write_text(SOURCE, encoding="utf-8")
    out = registry.call("edit_file", {
        "path": "calc.py",
        "old_string": 'return total / len(numbers)',
        "new_string": "return total / max(1, len(numbers))"})
    check("без відступу — усе одно знайдено", out.ok, out.output[:70])
    body = path.read_text(encoding="utf-8")
    check("заміну справді внесено", "max(1, len(numbers))" in body)

    # 3. Зайві пробіли в кінці рядків у запиті
    path.write_text(SOURCE, encoding="utf-8")
    out = registry.call("edit_file", {
        "path": "calc.py",
        "old_string": "    total = 0   \n    for n in numbers:",
        "new_string": "    total = 0\n    for n in numbers:  # цикл"})
    check("зайві пробіли пробачено", out.ok, out.output[:70])

    # 4. Фрагмента справді немає — має бути зрозуміла відмова
    path.write_text(SOURCE, encoding="utf-8")
    out = registry.call("edit_file", {
        "path": "calc.py", "old_string": "def nonexistent_function",
        "new_string": "x"})
    check("вигаданий фрагмент відхилено", not out.ok, out.output[:60])
    check("відмова зрозуміла",
          "не знайдено" in out.output.lower(), out.output[:70])

    # 5. Толерантність не має ламати файл
    check("файл компілюється після всіх правок", _compiles(path))

    # 6. Дублікат без replace_all — відмова
    path.write_text("x = 1\ny = 1\n", encoding="utf-8")
    out = registry.call("edit_file", {
        "path": "calc.py", "old_string": "= 1", "new_string": "= 2"})
    check("неоднозначний фрагмент відхилено", not out.ok, out.output[:70])

    print()
    print("Толерантна правка:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


def _compiles(path: Path) -> bool:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return True
    except SyntaxError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
