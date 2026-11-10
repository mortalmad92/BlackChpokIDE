"""Пошук відкладених замикань над змінною винятку (джерело NameError).

Python видаляє ``except ... as exc`` після виходу з блоку. Якщо ``exc``
захоплюється лямбдою або вкладеною функцією, яка виконується пізніше
(напр. ``self._ui_call(lambda: ...)``), у момент виклику змінної вже
немає — і замість справжньої причини користувач бачить ``NameError``.

Запуск: ``python tools/audit_deferred_exc.py`` — код виходу 1, якщо знайдено.
"""

from __future__ import annotations

import ast
import pathlib
import sys

TARGETS = ("blackchpok_ide", "tests", "tools")
ROOT_FILES = (
    "main.py",
    "server.py",
    "agent_tools.py",
    "rag_engine.py",
    "vibe_router.py",
    "night_shift.py",
)
NESTED = (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)


def _files() -> list[pathlib.Path]:
    found = [pathlib.Path(name) for name in ROOT_FILES if pathlib.Path(name).is_file()]
    for folder in TARGETS:
        found.extend(sorted(pathlib.Path(folder).rglob("*.py")))
    return found


def scan(path: pathlib.Path) -> list[tuple[int, str]]:
    """Повернути (рядок, назва змінної) для кожної небезпечної лямбди."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    problems: list[tuple[int, str]] = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        name = handler.name
        for node in ast.walk(handler):
            if not isinstance(node, NESTED):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Name) and inner.id == name
                        and isinstance(inner.ctx, ast.Load)):
                    problems.append((getattr(node, "lineno", 0), name))
                    break
    return problems


def main() -> int:
    total = 0
    for path in _files():
        for line, name in scan(path):
            print(f"{path}:{line}: відкладене замикання над {name!r}")
            total += 1
    print(f"Знайдено: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
