"""Перевірка стилю коду без зовнішніх лінтерів (лише stdlib).

Навіщо власна перевірка, а не ruff/flake8: проєкт має працювати на чистій
машині без установки пакетів, а CI не має залежати від версії лінтера.
Правила навмисно м'які — фіксують те, що вже є в коді, і ловлять лише
явні огріхи:

* табуляція в відступах (Python її дозволяє, але проєкт пише пробілами);
* пробіли в кінці рядка;
* синтаксичні помилки (компіляція);
* модулі без докстрінга;
* ``except:`` без типу (перехоплює навіть Ctrl+C);
* ``import *`` (забруднює простір імен).

Запуск:
    python tests/check_style.py            # перевірити
    python tests/check_style.py --strict   # ще й довжина рядка 100
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "blackchpok_ide"
TESTS = ROOT / "tests"

#: Максимальна довжина рядка (як у pyproject.toml).
MAX_LINE = 100

failures: list[str] = []


def fail(where: str, message: str) -> None:
    failures.append(f"{where}: {message}")


def check_file(path: Path, *, strict: bool) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(path.name, f"не читається: {exc}")
        return

    # Файл може лежати поза проєктом (перевірка окремого фрагмента в тесті) —
    # тоді показуємо просто його ім'я, а не відносний шлях.
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = Path(path.name)
    lines = source.splitlines()

    # ── 1. Синтаксис
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        fail(f"{rel}:{exc.lineno}", f"синтаксична помилка: {exc.msg}")
        return

    # ── 2. Пробіли/табуляція
    for number, line in enumerate(lines, 1):
        if line != line.rstrip():
            fail(f"{rel}:{number}", "пробіли в кінці рядка")
        if "\t" in line:
            fail(f"{rel}:{number}", "табуляція в рядку")
        if strict and len(line) > MAX_LINE:
            fail(f"{rel}:{number}", f"рядок {len(line)} > {MAX_LINE} символів")

    # ── 3. Докстрінг модуля
    if path.parent == PKG and not ast.get_docstring(tree):
        fail(str(rel), "немає докстрінга модуля")

    # ── 4. Небезпечні конструкції
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            fail(f"{rel}:{node.lineno}", "голий `except:` без типу")
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    fail(f"{rel}:{node.lineno}", "import *")


def main() -> int:
    strict = "--strict" in sys.argv
    targets = sorted(PKG.glob("*.py")) + sorted(TESTS.glob("*.py"))
    for path in targets:
        check_file(path, strict=strict)

    print(f"Перевірено файлів: {len(targets)}"
          + (" (строгий режим)" if strict else ""))
    if failures:
        print(f"\nПроблем: {len(failures)}")
        for item in failures[:60]:
            print(f"  ✗ {item}")
        if len(failures) > 60:
            print(f"  … і ще {len(failures) - 60}")
        return 1
    print("Стиль у порядку.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
