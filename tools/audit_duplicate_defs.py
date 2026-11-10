"""Пошук ПОВТОРНИХ визначень у тому самому класі або модулі.

Python мовчки лишає останнє визначення: якщо в класі два ``def set_online``,
перше тіло НІКОЛИ не виконається. Це не синтаксична помилка й не
попередження — просто мертвий код, який виглядає як робочий (і саме так
зникають виправлення: правили перше визначення, а працює друге).

Так само для функцій і присвоєнь на рівні модуля.

Запуск: ``python tools/audit_duplicate_defs.py`` — код виходу 1, якщо є
знахідки.
"""

from __future__ import annotations

import ast
import pathlib

TARGETS = ("blackchpok_ide", "tests", "tools")
ROOT_FILES = ("main.py", "server.py", "agent_tools.py", "rag_engine.py",
              "vibe_router.py", "night_shift.py")
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def files() -> list[pathlib.Path]:
    found = [pathlib.Path(name) for name in ROOT_FILES if pathlib.Path(name).is_file()]
    for folder in TARGETS:
        found.extend(sorted(pathlib.Path(folder).rglob("*.py")))
    return found


def _is_property_accessor(node: ast.stmt, previous: ast.stmt | None) -> bool:
    """Чи це друга половина ``property`` (``@x.setter`` / ``@x.deleter``).

    Такий повтор — не дефект: Python складає з них один атрибут-властивість.
    """
    if not isinstance(node, DEFS) or previous is None:
        return False
    for decorator in getattr(node, "decorator_list", ()):
        if (isinstance(decorator, ast.Attribute)
                and decorator.attr in ("setter", "deleter", "getter")):
            return True
    return False


def _scan_scope(body: list[ast.stmt], where: str, path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    seen: dict[str, tuple[int, ast.stmt]] = {}
    for node in body:
        if isinstance(node, DEFS):
            name = node.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                first = seen.get(target.id)
                if first is not None:
                    problems.append(f"{path}:{node.lineno}: «{target.id}» у {where} "
                                    f"вже визначено в рядку {first[0]}")
                seen[target.id] = (node.lineno, node)
            continue
        else:
            continue
        first = seen.get(name)
        if first is not None:
            if _is_property_accessor(node, first[1]):
                continue              # @x.setter — так і має бути
            problems.append(f"{path}:{node.lineno}: ПОВТОРНЕ визначення "
                            f"«{name}» у {where} (перше — рядок {first[0]})")
        else:
            seen[name] = (node.lineno, node)
    return problems


def main() -> int:
    total = 0
    for path in files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for line in _scan_scope(tree.body, "модулі", path):
            print(line)
            total += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for line in _scan_scope(node.body, f"класі {node.name}", path):
                    # Клас може легітимно перевизначати успадковане — але
                    # ДВІЧІ в тому самому тілі це завжди дефект.
                    print(line)
                    total += 1
    print(f"Повторних визначень: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
