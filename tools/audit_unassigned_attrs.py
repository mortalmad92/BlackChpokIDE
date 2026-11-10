"""Пошук атрибутів, які читають, але ніде не створюють (типові одруки).

Для кожного класу збираються всі ``self.<attr>`` у читанні та в записі
(``self.x = ...``, ``self.x: T = ...``, ``self.x += ...``,
``setattr(self, "x", ...)``). Читання вважається безпечним, якщо ім'я:

* десь записується як атрибут у тому ж пакеті;
* є методом якогось класу пакета;
* є модульною функцією пакета;
* належить tkinter/ttk або протоколу Python (див. ``INHERITED_PREFIXES``).

Усе інше при виконанні дасть ``AttributeError`` — це справжній дефект.

Запуск: ``python tools/audit_unassigned_attrs.py`` — код виходу 1, якщо є
підозрілі читання.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE = pathlib.Path("blackchpok_ide")

#: Префікси методів, які дає сам tkinter/ttk.
INHERITED_PREFIXES = (
    "winfo_", "grid_", "pack_", "place_", "tk_", "event_", "after",
    "bind", "unbind", "config", "cget", "clipboard_", "selection_",
    "columnconfigure", "rowconfigure", "grid_columnconfigure",
    "grid_rowconfigure", "nametowidget", "register", "keys", "focus_",
    "selection", "getvar", "setvar", "wait_", "update", "destroy",
    "protocol", "attributes", "geometry", "resizable", "title", "iconbitmap",
    "iconphoto", "minsize", "maxsize", "state", "lift", "lower", "withdraw",
    "deiconify", "overrideredirect", "transient", "grab_", "transient_",
)

#: Точні імена, які теж дає tkinter або протокол Python.
INHERITED_EXACT = {
    "master", "tk", "children", "_w", "_name", "widgetName", "_last_child_ids",
    "_tclCommands", "menu", "index", "insert", "delete", "see", "get", "add",
    "wm_geometry", "wm_title", "grid", "pack", "coords", "create_oval",
    "itemconfigure", "send_header", "end_headers", "rowconfigure", "columnconfigure",
}


def is_inherited(name: str) -> bool:
    if name in INHERITED_EXACT or name.startswith("__"):
        return True
    return any(name.startswith(prefix) for prefix in INHERITED_PREFIXES)


def collect() -> tuple[set[str], dict[str, dict[str, set[int]]]]:
    """Зібрати всі імена, що десь створюються, і всі читання по файлах."""
    known: set[str] = set()
    reads_by_file: dict[str, dict[str, set[int]]] = {}
    trees: list[tuple[pathlib.Path, ast.Module]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            trees.append((path, ast.parse(path.read_text(encoding="utf-8", errors="replace"))))
        except SyntaxError:
            continue
    for _path, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                known.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    known.update(_written(target))
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                known.update(_written(node.target))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "setattr" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                known.add(node.args[1].value)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    known.add(alias.asname or alias.name)
            elif isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                known.add(target.id)
                    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
                        target = stmt.target
                        if isinstance(target, ast.Name):
                            known.add(target.id)
                    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        known.add(stmt.name)
    for path, tree in trees:
        local: dict[str, set[int]] = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self" and isinstance(node.ctx, ast.Load)):
                local.setdefault(node.attr, set()).add(node.lineno)
        reads_by_file[str(path)] = local
    return known, reads_by_file


def _written(target: ast.expr) -> set[str]:
    found: set[str] = set()
    for inner in ast.walk(target):
        if (isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name)
                and inner.value.id == "self"):
            found.add(inner.attr)
    return found


def main() -> int:
    known, reads_by_file = collect()
    problems = 0
    for path, local in reads_by_file.items():
        for name, lines in sorted(local.items()):
            if name in known or is_inherited(name):
                continue
            shown = ", ".join(str(n) for n in sorted(lines)[:4])
            print(f"{path}: self.{name} читається (рядки {shown}), але ніде не створюється")
            problems += 1
    print(f"Підозрілих читань: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
