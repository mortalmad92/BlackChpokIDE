"""AST-аналіз Python у реальному часі: символи, помилки, структура.

Модуль дає редактору все, що потрібно для «живого» розуміння коду:

* **символи** — функції, класи, методи (з вкладеністю), змінні, імпорти;
* **помилки** — синтаксичні з точною позицією, щоб підсвітити рядок;
* **дерево** — для покрокового огляду структури;
* **статистика** — складність, довжина, кількість гілок.

Розбір інкрементальний: поки користувач друкує, ми не перебудовуємо все
заново, а кешуємо за хешем тексту. Модуль не тягне tkinter.
"""

from __future__ import annotations

import ast
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# ── Типи символів ────────────────────────────────────────────────────────────

FUNCTION = "function"
METHOD = "method"
CLASS = "class"
ASYNC = "async"
VARIABLE = "variable"
IMPORT = "import"
PROPERTY = "property"

#: Позначки для інтерфейсу.
ICONS: dict[str, str] = {
    FUNCTION: "ƒ",
    METHOD: "ƒ",
    ASYNC: "ƒᵃ",
    CLASS: "◈",
    VARIABLE: "▪",
    IMPORT: "⇢",
    PROPERTY: "◇",
}

#: Кольори для позначок (узгоджені з темою).
COLOUR_KEYS: dict[str, str] = {
    FUNCTION: "function",
    METHOD: "function",
    ASYNC: "control",
    CLASS: "type",
    VARIABLE: "constant",
    IMPORT: "string",
    PROPERTY: "decorator",
}


@dataclass
class Symbol:
    """Один символ у файлі."""

    name: str
    kind: str = FUNCTION
    line: int = 1                    # рядок оголошення (1-based)
    col: int = 0
    end_line: int = 0                # останній рядок тіла
    depth: int = 0                   # вкладеність (0 — верхній рівень)
    parent: str = ""                 # ім'я класу для методів
    docstring: str = ""
    decorators: tuple[str, ...] = ()
    signature: str = ""              # короткий підпис із параметрами
    is_property: bool = False

    @property
    def icon(self) -> str:
        if self.is_property:
            return ICONS[PROPERTY]
        return ICONS.get(self.kind, "·")

    @property
    def colour_key(self) -> str:
        if self.is_property:
            return COLOUR_KEYS[PROPERTY]
        return COLOUR_KEYS.get(self.kind, "function")

    @property
    def label(self) -> str:
        """Підпис для панелі структури."""
        if self.kind in (FUNCTION, METHOD, ASYNC):
            return f"{self.icon} {self.name}{self.signature}"
        if self.kind == CLASS:
            return f"{self.icon} {self.name}"
        if self.kind == IMPORT:
            return f"{self.icon} {self.name}"
        return f"{self.icon} {self.name}"

    @property
    def span(self) -> int:
        """Скільки рядків займає."""
        if self.end_line and self.end_line >= self.line:
            return self.end_line - self.line + 1
        return 1

    def matches(self, query: str) -> bool:
        return not query or query.lower() in self.name.lower()


@dataclass
class SyntaxProblem:
    """Синтаксична помилка з точним місцем."""

    message: str
    line: int = 0
    col: int = 0
    text: str = ""

    @property
    def short(self) -> str:
        """Короткий опис українською (без «invalid syntax» англійською)."""
        low = (self.message or "").lower()
        if "expected" in low and ":" in low:
            return "Очікується двокрапка в кінці рядка"
        if "unexpected eof" in low or "unexpected end" in low:
            return "Файл обривається — не закрито блок або дужку"
        if "unmatched" in low or "never closed" in low:
            return "Не закрито дужку або лапку"
        if "indent" in low:
            return "Порушено відступ"
        if "invalid syntax" in low:
            return "Синтаксис не зрозумілий Python"
        if "eol while scanning" in low:
            return "Рядок не закінчено (лапка?)"
        return self.message


@dataclass
class Metrics:
    """Коротка статистика файлу."""

    lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    functions: int = 0
    classes: int = 0
    imports: int = 0
    branches: int = 0
    max_depth: int = 0

    @property
    def summary(self) -> str:
        return (f"{self.code_lines} рядків коду · {self.functions} функцій · "
                f"{self.classes} класів · {self.imports} імпортів")


@dataclass
class Analysis:
    """Результат розбору одного файлу."""

    ok: bool = False
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Symbol] = field(default_factory=list)
    variables: list[Symbol] = field(default_factory=list)
    problem: Optional[SyntaxProblem] = None
    metrics: Metrics = field(default_factory=Metrics)
    tree: Optional[ast.AST] = None
    elapsed: float = 0.0
    digest: str = ""

    def by_kind(self, *kinds: str) -> list[Symbol]:
        return [sym for sym in self.symbols if sym.kind in kinds]

    def find(self, query: str) -> list[Symbol]:
        return [sym for sym in self.symbols if sym.matches(query)]

    def at_line(self, line: int) -> Optional[Symbol]:
        """Символ, у тілі якого стоїть курсор (найглибший)."""
        best: Optional[Symbol] = None
        for sym in self.symbols:
            if sym.line <= line <= (sym.end_line or sym.line):
                if best is None or sym.depth >= best.depth:
                    best = sym
        return best

    @property
    def outline(self) -> list[Symbol]:
        """Символи для панелі структури (без змінних)."""
        return [sym for sym in self.symbols if sym.kind != VARIABLE]


# ───────────────────────────────────────────────────────────────────────────────

_CACHE: dict[str, Analysis] = {}
_CACHE_LIMIT = 24


def digest(text: str) -> str:
    """Хеш тексту — щоб не розбирати те саме двічі."""
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:20]


def _signature(node: ast.AST) -> str:
    """Короткий підпис функції: (a, b=1, *args, **kw)."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""
    args = node.args
    parts: list[str] = []
    for index, arg in enumerate(getattr(args, "posonlyargs", [])):
        parts.append(arg.arg)
        if index == len(getattr(args, "posonlyargs", [])) - 1:
            parts.append("/")
    for arg in args.args:
        parts.append(arg.arg)
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for arg in args.kwonlyargs:
        parts.append(arg.arg)
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    text = ", ".join(part for part in parts if part)
    if len(text) > 42:
        text = text[:41] + "…"
    return f"({text})"


def _docstring(node: ast.AST) -> str:
    try:
        raw = ast.get_docstring(node) or ""
    except (TypeError, ValueError):
        return ""
    first = raw.strip().splitlines()[0] if raw.strip() else ""
    return first[:120]


def _decorators(node: ast.AST) -> tuple[str, ...]:
    out: list[str] = []
    for decorator in getattr(node, "decorator_list", []) or []:
        try:
            out.append(ast.unparse(decorator))
        except (AttributeError, ValueError):
            name = getattr(decorator, "id", "") or getattr(decorator, "attr", "")
            if name:
                out.append(str(name))
    return tuple(out)


def _is_property(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", []) or []:
        name = ""
        if isinstance(decorator, ast.Name):
            name = decorator.id
        elif isinstance(decorator, ast.Attribute):
            name = decorator.attr
        elif isinstance(decorator, ast.Call):
            inner = decorator.func
            name = getattr(inner, "id", "") or getattr(inner, "attr", "")
        if name in {"property", "cached_property", "setter", "getter"}:
            return True
    return False


def _walk_body(body: Iterable[ast.stmt], *, depth: int, parent: str,
               out: list[Symbol], metrics: Metrics) -> None:
    """Обійти тіло блоку й додати символи."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_async = isinstance(node, ast.AsyncFunctionDef)
            kind = ASYNC if is_async else (METHOD if parent else FUNCTION)
            symbol = Symbol(
                name=node.name,
                kind=kind,
                line=node.lineno,
                col=node.col_offset,
                end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                depth=depth,
                parent=parent,
                docstring=_docstring(node),
                decorators=_decorators(node),
                signature=_signature(node),
                is_property=_is_property(node),
            )
            out.append(symbol)
            metrics.functions += 1
            metrics.max_depth = max(metrics.max_depth, depth)
            _walk_body(node.body, depth=depth + 1, parent=parent, out=out,
                       metrics=metrics)
        elif isinstance(node, ast.ClassDef):
            out.append(Symbol(
                name=node.name,
                kind=CLASS,
                line=node.lineno,
                col=node.col_offset,
                end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                depth=depth,
                docstring=_docstring(node),
                decorators=_decorators(node),
            ))
            metrics.classes += 1
            metrics.max_depth = max(metrics.max_depth, depth)
            _walk_body(node.body, depth=depth + 1, parent=node.name, out=out,
                       metrics=metrics)
        elif isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try,
                               ast.AsyncFor, ast.AsyncWith, ast.Match)):
            metrics.branches += 1
            for attr in ("body", "orelse", "finalbody"):
                inner = getattr(node, attr, None)
                if isinstance(inner, list):
                    _walk_body(inner, depth=depth, parent=parent, out=out,
                               metrics=metrics)
            for handler in getattr(node, "handlers", []) or []:
                _walk_body(getattr(handler, "body", []), depth=depth,
                           parent=parent, out=out, metrics=metrics)
        elif depth == 0 and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    out.append(Symbol(name=target.id, kind=VARIABLE,
                                      line=node.lineno,
                                      col=node.col_offset, depth=depth))


def _collect_imports(tree: ast.AST) -> list[Symbol]:
    """Імпорти з номерами рядків."""
    found: list[Symbol] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(Symbol(
                    name=alias.asname or alias.name,
                    kind=IMPORT,
                    line=node.lineno,
                    col=node.col_offset,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                label = alias.asname or alias.name
                name = f"{module}.{label}" if module else label
                found.append(Symbol(
                    name=name,
                    kind=IMPORT,
                    line=node.lineno,
                    col=node.col_offset,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                ))
    return found


def _count_lines(text: str, metrics: Metrics) -> None:
    """ Порахувати рядки коду, коментарів і порожніх. """
    lines = (text or "").splitlines()
    metrics.lines = len(lines)
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            metrics.blank_lines += 1
        elif stripped.startswith("#"):
            metrics.comment_lines += 1
        else:
            metrics.code_lines += 1


def analyse(text: str, *, use_cache: bool = True) -> Analysis:
    """Розібрати Python-текст. Ніколи не кидає винятків."""
    started = time.perf_counter()
    key = digest(text)
    if use_cache and key in _CACHE:
        cached = _CACHE[key]
        cached.elapsed = (time.perf_counter() - started) * 1000
        return cached

    result = Analysis(digest=key)
    _count_lines(text, result.metrics)
    # BOM на початку тексту не є помилкою коду — прибираємо, інакше
    # ast.parse падає з «invalid non-printable character U+FEFF».
    clean = (text or "").lstrip("\ufeff")
    try:
        tree = ast.parse(clean)
    except SyntaxError as exc:
        result.problem = SyntaxProblem(
            message=str(exc.msg or exc),
            line=int(exc.lineno or 0),
            col=int(exc.offset or 0),
            text=(exc.text or "").rstrip(),
        )
        result.elapsed = (time.perf_counter() - started) * 1000
        if use_cache:
            _remember(key, result)
        return result
    except (ValueError, MemoryError, RecursionError) as exc:
        result.problem = SyntaxProblem(message=str(exc)[:160])
        result.elapsed = (time.perf_counter() - started) * 1000
        return result

    result.ok = True
    result.tree = tree
    symbols: list[Symbol] = []
    _walk_body(tree.body, depth=0, parent="", out=symbols, metrics=result.metrics)
    result.symbols = sorted(symbols, key=lambda sym: (sym.line, sym.depth))
    result.imports = _collect_imports(tree)
    result.variables = [sym for sym in result.symbols if sym.kind == VARIABLE]
    result.metrics.imports = len(result.imports)
    result.elapsed = (time.perf_counter() - started) * 1000
    if use_cache:
        _remember(key, result)
    return result


def _remember(key: str, result: Analysis) -> None:
    """Покласти в кеш, прибравши найстаріший."""
    if len(_CACHE) >= _CACHE_LIMIT:
        try:
            _CACHE.pop(next(iter(_CACHE)))
        except StopIteration:
            pass
    _CACHE[key] = result


def clear_cache() -> None:
    _CACHE.clear()


def describe_line(text: str, line: int) -> str:
    """Що саме на цьому рядку — для смуги стану."""
    result = analyse(text)
    symbol = result.at_line(line)
    if symbol is None:
        return ""
    return f"{symbol.label} · рядки {symbol.line}–{symbol.end_line or symbol.line}"


def unparse(node: ast.AST) -> str:
    """Безпечний ``ast.unparse`` (для показу вузла)."""
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, RecursionError):
        return type(node).__name__


def tree_rows(tree: Optional[ast.AST], *, limit: int = 400) -> list[tuple[int, str, str]]:
    """Рядки для перегляду AST: (глибина, тип вузла, короткий текст)."""
    rows: list[tuple[int, str, str]] = []
    if tree is None:
        return rows

    def walk(node: ast.AST, depth: int) -> None:
        if len(rows) >= limit:
            return
        name = type(node).__name__
        snippet = ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            snippet = f"{node.name}{_signature(node)}"
        elif isinstance(node, ast.ClassDef):
            snippet = node.name
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            snippet = unparse(node)[:60]
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return, ast.Call)):
            snippet = unparse(node)[:60]
        rows.append((depth, name, snippet))
        for child in ast.iter_child_nodes(node):
            walk(child, depth + 1)

    walk(tree, 0)
    return rows


__all__ = [
    "Analysis",
    "ASYNC",
    "CLASS",
    "FUNCTION",
    "ICONS",
    "IMPORT",
    "METHOD",
    "Metrics",
    "PROPERTY",
    "Symbol",
    "SyntaxProblem",
    "VARIABLE",
    "analyse",
    "clear_cache",
    "describe_line",
    "digest",
    "tree_rows",
    "unparse",
]
