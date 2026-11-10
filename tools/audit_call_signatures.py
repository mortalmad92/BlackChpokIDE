"""Пошук викликів функцій пакета з неправильними аргументами.

Статичний аналіз ловить те, що в користувача впало б ``TypeError``:

* keyword-аргумент, якого немає в сигнатурі;
* більше позиційних аргументів, ніж приймає функція;
* не передано обов'язковий аргумент (позиційний або keyword-only).

Резолвимо лише те, що видно в межах пакета ``blackchpok_ide``: функції
модулів, методи класів і методи ``self.<name>`` у межах свого класу.
Динамічні виклики (``*args``, ``**kwargs``, ``getattr``) не перевіряємо.

Запуск: ``python tools/audit_call_signatures.py`` — код виходу 1, якщо є
підозрілі виклики.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE = pathlib.Path("blackchpok_ide")
ROOT = "blackchpok_ide"


class Signature:
    """Спрощене уявлення про параметри функції."""

    __slots__ = ("positional", "optional", "kwonly_required", "kwonly_optional",
                 "vararg", "kwarg")

    def __init__(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        positional = [a.arg for a in (*args.posonlyargs, *args.args)]
        defaults = len(args.defaults)
        required = positional[: len(positional) - defaults]
        self.positional = positional
        self.optional = set(positional[len(required):])
        self.kwonly_required = {
            a.arg for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is None
        }
        self.kwonly_optional = {
            a.arg for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None
        }
        self.vararg = args.vararg is not None
        self.kwarg = args.kwarg is not None

    @property
    def required_positional(self) -> list[str]:
        return [name for name in self.positional if name not in self.optional]

    def bound(self) -> "Signature":
        """Сигнатура методу без неявного ``self``."""
        clone = Signature.__new__(Signature)
        clone.positional = self.positional[1:]
        clone.optional = self.optional - {self.positional[0]} if self.positional else set()
        clone.kwonly_required = set(self.kwonly_required)
        clone.kwonly_optional = set(self.kwonly_optional)
        clone.vararg = self.vararg
        clone.kwarg = self.kwarg
        return clone

    def unbound(self) -> "Signature":
        """Сигнатура ``@staticmethod``: перший параметр НЕ неявний."""
        clone = Signature.__new__(Signature)
        clone.positional = list(self.positional)
        clone.optional = set(self.optional)
        clone.kwonly_required = set(self.kwonly_required)
        clone.kwonly_optional = set(self.kwonly_optional)
        clone.vararg = self.vararg
        clone.kwarg = self.kwarg
        return clone

    def accepts(self, name: str) -> bool:
        return (name in self.positional or name in self.optional
                or name in self.kwonly_required or name in self.kwonly_optional)


def module_name(path: pathlib.Path) -> str:
    parts = path.relative_to(PACKAGE).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((ROOT, *parts))


def collect() -> tuple[dict[tuple[str, str], Signature], dict[tuple[str, str], Signature]]:
    """(модульні функції, методи класів) за (модуль, ім'я).

    Методи зберігаються вже «зв'язаними» (без ``self``), крім
    ``@staticmethod`` — у них перший параметр справжній.
    """
    functions: dict[tuple[str, str], Signature] = {}
    methods: dict[tuple[str, str], Signature] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        module = module_name(path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[(module, node.name)] = Signature(node)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    signature = Signature(item)
                    static = any(
                        isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
                        for decorator in item.decorator_list
                    )
                    methods[(module, f"{node.name}.{item.name}")] = (
                        signature.unbound() if static else signature.bound())
    return functions, methods


class Checker(ast.NodeVisitor):
    """Обхід одного файла з відомим контекстом (модуль, клас)."""

    def __init__(self, path: pathlib.Path, functions, methods) -> None:
        self.path = path
        self.functions = functions
        self.methods = methods
        self.imports: dict[str, str] = {}
        self.class_stack: list[str] = []
        self.problems = 0

    # ── контекст імпорту ───────────────────────────────────────────────────
    def _load_imports(self, tree: ast.Module, module: str) -> None:
        self.module = module
        package = module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package
                    for _ in range(node.level - 1):
                        base = base.rpartition(".")[0]
                    source = f"{base}.{node.module}" if node.module else base
                else:
                    source = node.module or ""
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = f"{source}.{alias.name}"

    # ── обхід ──────────────────────────────────────────────────────────────
    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        signature = self._resolve(node.func)
        if signature is not None:
            self._check(node, signature)
        self.generic_visit(node)

    # ── розв'язання цілі ───────────────────────────────────────────────────
    def _resolve(self, func: ast.expr) -> tuple[str, Signature] | None:
        if isinstance(func, ast.Name) and func.id in self.imports:
            target = self.imports[func.id]
            module, _, name = target.rpartition(".")
            found = self.functions.get((module, name))
            if found is not None:
                return target, found
            return None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = func.value.id
            if base == "self" and self.class_stack:
                owner = ".".join((*self.class_stack, func.attr))
                found = self.methods.get((self.module, owner))
                if found is not None:
                    return owner, found
                return None
            if base in self.imports:
                target = self.imports[base]
                module, _, name = target.rpartition(".")
                found = self.methods.get((module, f"{name}.{func.attr}"))
                if found is not None:
                    return f"{target}.{func.attr}", found
                found = self.functions.get((module, name))
                if found is not None and func.attr == "__call__":
                    return target, found
        return None

    # ── перевірка ──────────────────────────────────────────────────────────
    def _check(self, node: ast.Call, resolved: tuple[str, Signature]) -> None:
        label, signature = resolved
        named = {kw.arg for kw in node.keywords if kw.arg}
        has_star = any(kw.arg is None for kw in node.keywords)
        limit = len(signature.positional) + (10**6 if signature.vararg else 0)
        if len(node.args) > limit:
            self._report(node, f"зайвих позиційних аргументів "
                               f"({len(node.args)} > {len(signature.positional)}) у {label}")
            return
        if not signature.kwarg and not has_star:
            for name in sorted(named - {n for n in signature.positional}
                               - signature.optional - signature.kwonly_required
                               - signature.kwonly_optional):
                self._report(node, f"невідомий аргумент {name!r} у {label}")
        required = signature.required_positional[len(node.args):]
        has_star_args = any(isinstance(arg, ast.Starred) for arg in node.args)
        for name in required:
            if name not in named and not signature.vararg and not has_star_args:
                self._report(node, f"не передано обов'язковий аргумент {name!r} у {label}")
        if not has_star:
            for name in sorted(signature.kwonly_required - named):
                self._report(node, f"не передано обов'язковий keyword-only {name!r} у {label}")

    def _report(self, node: ast.Call, message: str) -> None:
        print(f"{self.path}:{node.lineno}: {message}")
        self.problems += 1


def main() -> int:
    functions, methods = collect()
    total = 0
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        checker = Checker(path, functions, methods)
        checker._load_imports(tree, module_name(path))
        checker.visit(tree)
        total += checker.problems
    print(f"Підозрілих викликів: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
