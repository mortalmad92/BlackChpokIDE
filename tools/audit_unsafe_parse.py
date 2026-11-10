"""Знайти виклики ``json.loads``/``int()``/``float()`` без захисту.

Ці три виклики — джерело найчастіших «IDE не запускається»: файл стану
пошкоджено, а розбір падає з ``JSONDecodeError``/``ValueError`` просто в
конструкторі вікна. Скрипт показує кожне місце, яке НЕ стоїть усередині
``try``, щоб його можна було перевірити очима.

Запуск: ``python tools/audit_unsafe_parse.py`` — код виходу 1, якщо є
знахідки.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE = pathlib.Path("blackchpok_ide")
RISKY = {"json.loads", "int", "float"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _guarded_nodes(tree: ast.AST) -> set[int]:
    """``id()`` вузлів, які лежать усередині ``try``."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for statement in (*node.body, *[h for h in node.handlers]):
                for inner in ast.walk(statement):
                    inside.add(id(inner))
    return inside


def main() -> int:
    findings = 0
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError:
            continue
        guarded = _guarded_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name not in RISKY:
                continue
            if name == "int" or name == "float":
                # ``int(x)`` на власній змінній-лічильнику безпечний;
                # цікавить лише розбір зовнішнього тексту.
                if not node.args or not isinstance(
                        node.args[0], (ast.Subscript, ast.Call)):
                    continue
            if id(node) in guarded:
                continue
            line = source.splitlines()[node.lineno - 1].strip()
            print(f"{path}:{node.lineno}: {name} без try — {line[:96]}")
            findings += 1
    print(f"Незахищених розборів: {findings}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
