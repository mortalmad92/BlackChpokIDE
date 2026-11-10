"""Шукає методи, що роблять `.resolve()` / `.name` без приведення до Path.

Клас дефекту: публічний метод оголошує `path: Path`, але викликається з
рядком — падає з `'str' object has no attribute ...`. Саме так падав
`file_tree.reveal` і `rag_engine.LocalRAG.__init__`.
"""
from __future__ import annotations

import ast
import pathlib
import sys

SKIP = {".venv", "userdata", ".git", ".buildtmp", ".quarantine", "__pycache__",
        "dist", "build", "logs", "tests", "tools"}

PATH_METHODS = {"resolve", "relative_to", "iterdir", "rglob", "glob", "is_file",
                "is_dir", "exists", "read_text", "write_text", "read_bytes",
                "stat", "suffix", "stem", "unlink", "mkdir", "as_posix"}


class Finder(ast.NodeVisitor):
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.findings: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Параметри з анотацією Path (або Path | str)
        path_params = set()
        args = node.args
        for arg in list(args.args) + list(args.kwonlyargs):
            ann = arg.annotation
            if ann is None:
                continue
            text = ast.unparse(ann)
            if "Path" in text:
                path_params.add(arg.arg)
        if not path_params:
            self.generic_visit(node)
            return
        # Чи є в тілі приведення до Path?
        converted = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call):
                func = sub.value.func
                name = getattr(func, "id", "") or getattr(func, "attr", "")
                if name == "Path":
                    for target in sub.targets:
                        if isinstance(target, ast.Name):
                            converted.add(target.id)
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
                continue
            if sub.func.attr not in PATH_METHODS:
                continue
            base = sub.func.value
            if not isinstance(base, ast.Name) or base.id not in path_params:
                continue
            if base.id in converted:
                continue
            self.findings.append(
                f"{self.path}:{sub.lineno}: {node.name}() робить "
                f"«{base.id}.{sub.func.attr}()» без приведення до Path")
        self.generic_visit(node)


def main() -> int:
    found: list[str] = []
    for path in sorted(pathlib.Path(".").rglob("*.py")):
        if set(path.parts) & SKIP:
            continue
        try:
            tree = ast.parse(path.read_text("utf-8", errors="replace"))
        except SyntaxError:
            continue
        finder = Finder(path)
        finder.visit(tree)
        found.extend(finder.findings)
    print(f"знайдено: {len(found)}")
    for line in found:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
