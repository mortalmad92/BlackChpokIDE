"""Пошук НЕВИЗНАЧЕНИХ імен у функціях пакета (спрощений pyflakes).

Навіщо: дефект ``NameError: name 'low' is not defined`` у ``agent_tools``
пройшов усі тести й виявився лише в живому прогоні. Цей скрипт ловить таке
статично: для кожної функції збирає локальні імена (присвоєння, аргументи,
імпорти, comprehension, ``with``/``for``/``except as``) і перевіряє, чи
кожне ЗАВАНТАЖУВАНЕ ім'я справді десь визначене.

Свідомо консервативний: краще пропустити, ніж дати хибний сигнал. Тому
ігноруємо те, що не можемо довести (``getattr``-динаміка, ``global``,
``nonlocal``, зірочкові імпорти, ``eval``/``exec``).
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(r"C:\AI\blackchpock_ai")
BUILTINS = set(dir(builtins))
#: Імена, які Python кладе в модуль сам.
MODULE_GLOBALS = {"__file__", "__name__", "__doc__", "__package__",
                 "__spec__", "__loader__", "__builtins__", "__dict__"}


def _names_bound(node: ast.AST, out: set[str]) -> None:
    """Зібрати імена, які вузол ЗАВАНТАЖУЄ у своїй області видимості."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            out.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(child.name)
        elif isinstance(child, ast.ClassDef):
            out.add(child.name)
        elif isinstance(child, ast.arg):
            out.add(child.arg)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                name = alias.asname or alias.name.split(".")[0]
                if name != "*":
                    out.add(name)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            out.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            out.update(child.names)


def _scope_nodes(func: ast.AST) -> list[ast.AST]:
    """Вузли, що належать САМЕ цій функції (без вкладених).

    Вкладені функції мають власну область, але зовнішні імена їм видимі —
    тому їхні ВІЛЬНІ імена перевіряємо разом із зовнішньою функцією.
    """
    nodes: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        nodes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            # Заходимо всередину: вільні імена вкладеної функції можуть
            # бути визначені тут. Її ВЛАСНІ аргументи додаємо окремо.
            inner = set()
            _names_bound(node, inner)
            stack.extend(ast.iter_child_nodes(node))
            continue
        stack.extend(ast.iter_child_nodes(node))
    return nodes


def audit_function(func: ast.AST, module_names: set[str]) -> list[str]:
    problems: list[str] = []
    bound: set[str] = set()
    _names_bound(func, bound)
    if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = func.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            bound.add(arg.arg)
        if args.vararg:
            bound.add(args.vararg.arg)
        if args.kwarg:
            bound.add(args.kwarg.arg)
    loaded: list[tuple[str, int]] = []
    for node in _scope_nodes(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.append((node.id, node.lineno))
    for name, line in loaded:
        if name in bound or name in module_names or name in BUILTINS \
                or name in MODULE_GLOBALS:
            continue
        problems.append(f"ряд {line}: «{name}» не визначено")
    return problems


def main() -> int:
    files = [p for p in (ROOT / "blackchpok_ide").rglob("*.py")]
    files.append(ROOT / "agent_tools.py")
    files.append(ROOT / "server.py")
    total = 0
    for path in files:
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            print(f"{path.name}: СИНТАКСИС: {exc}")
            total += 1
            continue
        # Імена рівня модуля + все, що завантажується через `from x import *`.
        module_names: set[str] = set()
        star_import = False
        for node in tree.body:
            _names_bound(node, module_names)
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "*" for alias in node.names):
                    star_import = True
        if star_import:
            # Зірочковий імпорт робить будь-яке ім'я «можливим» — такий
            # файл не перевіряємо, щоб не давати хибних сигналів.
            continue
        printed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            problems = audit_function(node, module_names)
            if not problems:
                continue
            if not printed:
                print(f"\n{path.relative_to(ROOT)}")
                printed = True
            for problem in problems[:6]:
                print(f"   {node.name}(): {problem}")
            total += len(problems)
    print(f"\nневизначених імен: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
