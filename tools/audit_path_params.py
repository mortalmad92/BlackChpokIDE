"""Знайти функції, які викликають методи ``Path`` на параметрі-рядку.

Типова анотація каже ``root: Path``, але кличуть із рядком (змінна
оточення, тест, ``str(path)``). Тоді ``root.resolve()`` падає з
``AttributeError: 'str' object has no attribute 'resolve'`` — і функція
мовчки не працює. Реальний приклад такого дефекту: ``LocalRAG(root=…)``.

Скрипт шукає параметри без перетворення (``param = Path(param)`` або
``Path(param)`` у перших рядках), на яких одразу викликано метод ``Path``.

Запуск: ``python tools/audit_path_params.py`` — код виходу 1, якщо є
знахідки.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE = pathlib.Path("blackchpok_ide")
ROOT_FILES = ("main.py", "server.py", "agent_tools.py", "rag_engine.py",
              "vibe_router.py", "night_shift.py")

#: Методи, які є лише в ``pathlib.Path``.
PATH_METHODS = frozenset({
    "resolve", "exists", "is_dir", "is_file", "iterdir", "rglob", "glob",
    "mkdir", "read_text", "write_text", "read_bytes", "write_bytes",
    "relative_to", "with_suffix", "with_name", "as_posix", "is_absolute",
    "rmdir", "unlink", "stat", "samefile", "readlink", "hardlink_to",
})


def files() -> list[pathlib.Path]:
    found = [pathlib.Path(name) for name in ROOT_FILES if pathlib.Path(name).is_file()]
    for folder in (PACKAGE,):
        found.extend(sorted(folder.rglob("*.py")))
    return found


def _converted_names(body: list[ast.stmt], params: list[str]) -> set[str]:
    """Імена параметрів, які всередині функції перетворено на ``Path``."""
    safe: set[str] = set()
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "Path":
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in params:
                        safe.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (isinstance(func, ast.Name) and func.id == "Path"
                    and isinstance(node.target, ast.Name)):
                safe.add(node.target.id)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "Path" and node.args):
            inner = node.args[0]
            if isinstance(inner, ast.Name) and inner.id in params:
                safe.add(inner.id + "\0used")       # позначка «вже обгорнуто»
    return safe


def check_function(node: ast.FunctionDef | ast.AsyncFunctionDef,
                   path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    params = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args,
                                 *node.args.kwonlyargs)]
    if not params:
        return problems
    # Анотації: цікавлять лише ті, що заявлені як Path.
    annotations = {arg.arg: ast.unparse(arg.annotation) if arg.annotation else ""
                   for arg in (*node.args.posonlyargs, *node.args.args,
                               *node.args.kwonlyargs)}
    declared = [name for name in params if "Path" in annotations.get(name, "")]
    if not declared:
        return problems
    safe = _converted_names(node.body, params)
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        func = inner.func
        if not isinstance(func, ast.Attribute) or func.attr not in PATH_METHODS:
            continue
        owner = func.value
        if not isinstance(owner, ast.Name) or owner.id not in declared:
            continue
        if owner.id in safe:
            continue
        problems.append(
            f"{path}:{inner.lineno}: «{owner.id}» заявлений як Path, але "
            f"викликано .{func.attr}() без перетворення — впаде на рядку")
    return problems


def main() -> int:
    total = 0
    for path in files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for line in check_function(node, path):
                    print(line)
                    total += 1
    print(f"Знайдено: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
