"""Пошук недосяжного коду та однакових ключів у словниках.

Дві помилки, які не видно очима й не ловить звичайний лінтер:

* код ПІСЛЯ ``return``/``raise``/``break``/``continue`` у тому ж блоці —
  тобто гілка, яку автор дописав, але яка вже ніколи не виконається;
* повторений ключ у літералі ``{...}`` — друге значення тихо перекриває
  перше, і частина налаштувань зникає.

Запуск: ``python tools/audit_unreachable.py`` — код виходу 1, якщо є
знахідки.
"""

from __future__ import annotations

import ast
import pathlib

TARGETS = ("blackchpok_ide", "tests", "tools")
ROOT_FILES = ("main.py", "server.py", "agent_tools.py", "rag_engine.py",
              "vibe_router.py", "night_shift.py")
TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
#: Вузли, чиї тіла — це списки інструкцій (після них ще може бути код).
INSTRUCTION_HOLDERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                       ast.ClassDef, ast.If, ast.For, ast.AsyncFor, ast.While,
                       ast.With, ast.AsyncWith, ast.Try, ast.ExceptHandler)


def files() -> list[pathlib.Path]:
    found = [pathlib.Path(name) for name in ROOT_FILES if pathlib.Path(name).is_file()]
    for folder in TARGETS:
        found.extend(sorted(pathlib.Path(folder).rglob("*.py")))
    return found


def check_unreachable(tree: ast.AST, path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            if not isinstance(value, list):
                continue
            if not all(isinstance(item, ast.stmt) for item in value):
                continue
            for index, stmt in enumerate(value[:-1]):
                if not isinstance(stmt, TERMINATORS):
                    continue
                following = value[index + 1]
                if isinstance(following, ast.Expr) and isinstance(
                        following.value, ast.Constant) and isinstance(
                        following.value.value, str):
                    continue          # рядок-документація після гілки — не код
                problems.append(
                    f"{path}:{following.lineno}: недосяжний код після "
                    f"{type(stmt).__name__.lower()} (рядок {stmt.lineno})")
    return problems


def check_duplicate_keys(tree: ast.AST, path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen: set[str] = set()
        for key in node.keys:
            if not isinstance(key, ast.Constant) or not isinstance(
                    key.value, (str, int, float, bool, type(None))):
                continue
            marker = repr(key.value)
            if marker in seen:
                problems.append(f"{path}:{key.lineno}: повторений ключ {marker}")
            seen.add(marker)
    return problems


def main() -> int:
    total = 0
    for path in files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for line in (*check_unreachable(tree, path), *check_duplicate_keys(tree, path)):
            print(line)
            total += 1
    print(f"Знайдено: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
