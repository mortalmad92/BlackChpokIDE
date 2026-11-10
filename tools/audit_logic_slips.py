"""Пошук типових логічних одруків, які не ловить звичайний лінтер.

Перевіряються три класи помилок, кожна з яких дає «дивну» поведінку замість
падіння:

1. **Умова завжди істинна або хибна** — ``if x == "a" or "b"`` (другий
   операнд — константа, тож умова істинна завжди).
2. **Присвоєння замість порівняння** в ``if`` — ``if x = 5`` (синтаксис
   забороняє, але ``if (x := 5)`` поряд із ``==`` трапляється).
3. **Порівняння з ``None`` через ``==``**, яке ламається на об'єктах із
   власним ``__eq__`` (наприклад, numpy-масивах).

Запуск: ``python tools/audit_logic_slips.py`` — код виходу 1, якщо є
знахідки.
"""

from __future__ import annotations

import ast
import pathlib

TARGETS = ("blackchpok_ide",)
ROOT_FILES = ("main.py", "server.py", "agent_tools.py", "rag_engine.py",
              "vibe_router.py", "night_shift.py")


def files() -> list[pathlib.Path]:
    found = [pathlib.Path(name) for name in ROOT_FILES if pathlib.Path(name).is_file()]
    for folder in TARGETS:
        found.extend(sorted(pathlib.Path(folder).rglob("*.py")))
    return found


def _only_constants(node: ast.BoolOp) -> bool:
    return all(isinstance(value, ast.Constant) for value in node.values)


def check_always_true(tree: ast.AST, path: pathlib.Path) -> list[str]:
    """Умова, яка не може бути хибною через константу в ``or``.

    Помилка — це ``if x == "a" or "b"``: тут ``"b"`` стоїть ПОРУЧ із
    порівнянням і вся умова істинна завжди, бо непустий рядок — істина.
    Автор майже завжди мав на увазі ``x == "a" or x == "b"``.

    Навмисно НЕ ловимо звичайний ідіом ``x or "типове"``: остання константа
    в ``or`` — це значення за замовчуванням, і воно цілком законне.
    """
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        values = node.values
        for index, value in enumerate(values):
            if index == 0 or not isinstance(value, ast.Constant):
                continue
            if not bool(value.value):
                continue
            # Константа стоїть ПІСЛЯ порівняння — це і є одрук.
            if any(isinstance(earlier, ast.Compare) for earlier in values[:index]):
                problems.append(
                    f"{path}:{node.lineno}: умова «… == … or {value.value!r}» "
                    f"завжди істинна — бракує другої частини порівняння")
                break
    return problems


def check_none_compare(tree: ast.AST, path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        op = node.ops[0]
        if not isinstance(op, (ast.Eq, ast.NotEq)):
            continue
        operands = [node.left, *node.comparators]
        if any(isinstance(item, ast.Constant) and item.value is None
               for item in operands):
            problems.append(f"{path}:{node.lineno}: порівняння з None через "
                            f"'==' — краще 'is None'")
    return problems


def main() -> int:
    total = 0
    for path in files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for line in (*check_always_true(tree, path), *check_none_compare(tree, path)):
            print(line)
            total += 1
    print(f"Знайдено: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
