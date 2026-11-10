"""Підсвітка синтаксису для tkinter.Text без зовнішніх залежностей.

Працює інкрементально: перемальовує лише видимий діапазон рядків, тому
відкривати файли на кілька тисяч рядків можна без затримок.
"""

from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import theme


@dataclass(frozen=True)
class Language:
    name: str
    keywords: tuple[str, ...] = ()
    controls: tuple[str, ...] = ()
    builtins: tuple[str, ...] = ()
    line_comment: tuple[str, ...] = ()
    block_comment: tuple[tuple[str, str], ...] = ()
    strings: tuple[str, ...] = ('"', "'")
    triple_strings: tuple[str, ...] = ()
    decorator: str = ""
    multiline_strings: bool = True


PYTHON = Language(
    name="python",
    keywords=(
        "def", "class", "import", "from", "as", "return", "yield", "lambda", "global",
        "nonlocal", "pass", "assert", "del", "with", "async", "await", "raise", "except",
        "finally", "try", "and", "or", "not", "in", "is", "None", "True", "False",
    ),
    controls=("if", "elif", "else", "for", "while", "break", "continue", "match", "case"),
    builtins=(
        "print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set",
        "tuple", "open", "super", "isinstance", "enumerate", "zip", "map", "filter",
        "sorted", "sum", "min", "max", "any", "all", "type", "getattr", "setattr",
        "hasattr", "repr", "format", "abs", "round", "input", "vars", "dir", "id",
        "iter", "next", "callable", "property", "staticmethod", "classmethod",
    ),
    line_comment=("#",),
    triple_strings=('"""', "'''"),
    decorator="@",
)

JS_LIKE = Language(
    name="javascript",
    keywords=(
        "function", "const", "let", "var", "return", "class", "extends", "new", "this",
        "import", "export", "default", "from", "as", "typeof", "instanceof", "void",
        "delete", "in", "of", "async", "await", "yield", "static", "get", "set",
        "true", "false", "null", "undefined",
    ),
    controls=("if", "else", "for", "while", "switch", "case", "break", "continue", "try", "catch", "finally", "throw", "do"),
    builtins=("console", "document", "window", "JSON", "Object", "Array", "String", "Number", "Math", "Promise", "Map", "Set", "Date", "Math"),
    line_comment=("//",),
    block_comment=(("/*", "*/"),),
    strings=('"', "'", "`"),
    triple_strings=(),
)

TS_LIKE = Language(
    name="typescript",
    keywords=JS_LIKE.keywords + ("interface", "type", "enum", "implements", "public", "private", "protected", "readonly", "namespace", "declare", "abstract"),
    controls=JS_LIKE.controls,
    builtins=JS_LIKE.builtins + ("string", "number", "boolean", "any", "unknown", "never"),
    line_comment=("//",),
    block_comment=(("/*", "*/"),),
    strings=('"', "'", "`"),
)

C_LIKE = Language(
    name="clike",
    keywords=(
        "int", "char", "float", "double", "void", "long", "short", "unsigned", "signed",
        "const", "static", "struct", "class", "public", "private", "protected", "virtual",
        "return", "new", "delete", "namespace", "using", "template", "typename", "auto",
        "true", "false", "nullptr", "include", "define", "ifdef", "ifndef", "endif",
        "string", "bool", "var", "record", "object",
    ),
    controls=("if", "else", "for", "while", "switch", "case", "break", "continue", "do", "try", "catch", "throw", "foreach", "in", "is", "as"),
    builtins=("std", "cout", "cin", "endl", "printf", "malloc", "free", "sizeof", "Console", "Math", "String", "List"),
    line_comment=("//",),
    block_comment=(("/*", "*/"),),
)

SQL = Language(
    name="sql",
    keywords=("select", "from", "where", "join", "left", "right", "inner", "outer", "on", "group", "by", "order", "having", "limit", "offset", "insert", "into", "values", "update", "set", "delete", "create", "table", "index", "view", "drop", "alter", "add", "column", "primary", "key", "foreign", "references", "unique", "default", "null", "not", "and", "or", "as", "distinct", "union", "all", "case", "when", "then", "else", "end", "with", "begin", "commit", "rollback", "if", "exists"),
    controls=(),
    builtins=("count", "sum", "avg", "min", "max", "coalesce", "cast", "substr", "length", "lower", "upper", "round", "now", "date"),
    line_comment=("--",),
    block_comment=(("/*", "*/"),),
    strings=("'", '"'),
    multiline_strings=False,
)

SHELL = Language(
    name="shell",
    keywords=("echo", "set", "if", "else", "goto", "call", "exit", "cd", "for", "do", "done", "then", "fi", "function", "local", "export", "return", "shift", "source", "rem"),
    controls=(),
    builtins=("dir", "copy", "move", "del", "mkdir", "rmdir", "type", "findstr", "where", "python", "pip", "git", "pytest", "start", "powershell", "pwsh", "cmd"),
    line_comment=("#", "rem ", "::"),
    strings=('"', "'"),
    multiline_strings=False,
)

MARKDOWN = Language(
    name="markdown",
    keywords=(),
    controls=(),
    builtins=(),
    line_comment=(),
    strings=(),
    multiline_strings=False,
)

JSON_LANG = Language(
    name="json",
    keywords=("true", "false", "null"),
    line_comment=("//",),
    strings=('"',),
    multiline_strings=False,
)

HTML = Language(
    name="html",
    keywords=(),
    line_comment=(),
    block_comment=(("<!--", "-->"),),
    strings=('"', "'"),
)

CSS = Language(
    name="css",
    keywords=(),
    line_comment=(),
    block_comment=(("/*", "*/"),),
    strings=('"', "'"),
    multiline_strings=False,
)

YAML = Language(
    name="yaml",
    keywords=("true", "false", "null", "yes", "no"),
    line_comment=("#",),
    strings=('"', "'"),
    multiline_strings=False,
)

PLAIN = Language(name="plain", strings=(), multiline_strings=False)

_LANGUAGES: dict[str, Language] = {
    "py": PYTHON, "pyi": PYTHON, "pyw": PYTHON,
    "js": JS_LIKE, "jsx": JS_LIKE, "mjs": JS_LIKE, "cjs": JS_LIKE,
    "ts": TS_LIKE, "tsx": TS_LIKE,
    "c": C_LIKE, "h": C_LIKE, "cc": C_LIKE, "cpp": C_LIKE, "hpp": C_LIKE, "cs": C_LIKE, "java": C_LIKE, "rs": C_LIKE, "go": C_LIKE, "dart": C_LIKE, "kt": C_LIKE, "swift": C_LIKE,
    "sql": SQL,
    "sh": SHELL, "bash": SHELL, "ps1": SHELL, "bat": SHELL, "cmd": SHELL,
    "md": MARKDOWN, "mdx": MARKDOWN, "rst": MARKDOWN,
    "json": JSON_LANG, "jsonc": JSON_LANG, "jsonl": JSON_LANG,
    "html": HTML, "htm": HTML, "xml": HTML, "svg": HTML,
    "css": CSS, "scss": CSS, "less": CSS,
    "yaml": YAML, "yml": YAML,
    "toml": YAML, "ini": YAML, "cfg": YAML, "conf": YAML,
}


def language_for(filename: str) -> Language:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _LANGUAGES.get(ext, PLAIN)


COMMENT_MARKERS: dict[str, str] = {
    "python": "# ", "shell": "# ", "yaml": "# ", "sql": "-- ", "markdown": "<!-- ",
}


def comment_token(filename: str) -> str:
    return COMMENT_MARKERS.get(language_for(filename).name, "// ")


_TOKEN_CACHE: dict[str, re.Pattern[str]] = {}


def _word_pattern(words: Iterable[str]) -> str:
    items = sorted({w for w in words if w}, key=len, reverse=True)
    return "|".join(re.escape(word) for word in items)


class Highlighter:
    """Обчислює проміжки тексту для тегування певного діапазону рядків."""

    def __init__(self, lang: Language) -> None:
        self.lang = lang
        self._compile()

    def _compile(self) -> None:
        lang = self.lang
        parts: list[tuple[str, str]] = []
        if lang.keywords:
            parts.append(("keyword", rf"\b(?:{_word_pattern(lang.keywords)})\b"))
        if lang.controls:
            parts.append(("control", rf"\b(?:{_word_pattern(lang.controls)})\b"))
        if lang.builtins:
            parts.append(("builtin", rf"\b(?:{_word_pattern(lang.builtins)})\b"))
        if lang.line_comment:
            markers = "|".join(re.escape(m) for m in lang.line_comment)
            parts.append(("comment", rf"(?:{markers})[^\n]*"))
        for start, end in lang.block_comment:
            parts.append(("comment", rf"{re.escape(start)}(?:.|\n)*?{re.escape(end)}"))
        if lang.triple_strings:
            for quote in lang.triple_strings:
                parts.append(("string", rf"{re.escape(quote)}(?:.|\n)*?{re.escape(quote)}"))
        if lang.strings:
            quotes = "".join(re.escape(q) for q in lang.strings)
            parts.append(("string", rf"[{quotes}](?:\\.|[^\\\n{quotes}])*[{quotes}]?"))
        if lang.decorator:
            parts.append(("decorator", rf"{re.escape(lang.decorator)}[A-Za-z_][\w.]*"))
        parts.append(("number", r"\b(?:0[xX][0-9a-fA-F]+|\d+\.\d*(?:[eE][+-]?\d+)?|\d+)\b"))
        parts.append(("function", r"\b([A-Za-z_]\w*)(?=\s*\()"))
        parts.append(("self", r"\b(self|cls|this|super)\b"))
        source = "|".join(f"(?P<{group}{i}>{pattern})" for i, (group, pattern) in enumerate(parts))
        self._pattern = re.compile(source, re.MULTILINE)
        self._groups: list[tuple[str, str]] = []
        for i, (group, _pattern) in enumerate(parts):
            self._groups.append((f"{group}{i}", group))

    def spans(self, text: str) -> list[tuple[int, int, str]]:
        """Список (початок, кінець, тег) у координатах рядка."""
        found: list[tuple[int, int, str]] = []
        if self.lang.name == "plain":
            return found
        for match in self._pattern.finditer(text):
            for group_name, tag in self._groups:
                start = match.start(group_name)
                if start != -1:
                    end = match.end(group_name)
                    if end > start:
                        found.append((start, end, tag))
                    break
        if self.lang.name == "markdown":
            found.extend(_markdown_spans(text))
        if self.lang.name == "html":
            found.extend(_html_spans(text))
        if self.lang.name == "json":
            found.extend(_json_spans(text))
        found.sort(key=lambda item: (item[0], -item[1]))
        # прибираємо перекриття: перший (найдовший) тег перемагає
        result: list[tuple[int, int, str]] = []
        last_end = -1
        for start, end, tag in found:
            if start < last_end:
                if end <= last_end:
                    continue
                start = last_end
            result.append((start, end, tag))
            last_end = end
        return result


def _markdown_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    if re.match(r"^\s{0,3}#{1,6}\s", text):
        spans.append((0, len(text), "keyword"))
    if re.match(r"^\s{0,3}(```|~~~)", text):
        spans.append((0, len(text), "comment"))
    for match in re.finditer(r"`[^`\n]+`", text):
        spans.append((match.start(), match.end(), "string"))
    for match in re.finditer(r"\*\*[^*\n]+\*\*|__[^_\n]+__", text):
        spans.append((match.start(), match.end(), "keyword"))
    for match in re.finditer(r"\[[^\]\n]*\]\([^)\n]*\)", text):
        spans.append((match.start(), match.end(), "attribute"))
    if re.match(r"^\s*[-*+]\s", text) or re.match(r"^\s*\d+\.\s", text):
        spans.append((0, 1 if text.strip()[:1] in "-*+" else 2, "control"))
    return spans


def _html_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"</?([a-zA-Z][\w:-]*)", text):
        spans.append((match.start(), match.end(), "tag"))
    for match in re.finditer(r"([a-zA-Z_:][\w:.-]*)\s*=\s*", text):
        spans.append((match.start(1), match.end(1), "attribute"))
    return spans


def _json_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r'"(?:\\.|[^"\\])*"\s*:', text):
        spans.append((match.start(), match.start() + 1, "key"))
    return spans


_HIGHLIGHTER_CACHE: dict[str, Highlighter] = {}


def highlighter_for(filename: str) -> Highlighter:
    lang = language_for(filename)
    cached = _HIGHLIGHTER_CACHE.get(lang.name)
    if cached is None:
        cached = Highlighter(lang)
        _HIGHLIGHTER_CACHE[lang.name] = cached
    return cached


def configure_tags(text: tk.Text, mono_font, bold_font) -> None:
    """Створити теги підсвітки у віджеті Text."""
    for tag, color in theme.SYNTAX_COLORS.items():
        options = {
            "foreground": color,
            "font": bold_font if tag in {"keyword", "control", "tag"} else mono_font,
        }
        if tag == "comment":
            options["font"] = mono_font
        text.tag_configure(tag, **options)
    text.tag_configure("sel", background=theme.SELECTION, foreground=theme.FG_BRIGHT)
    text.tag_configure("current_line", background=theme.LINE_HL)
    text.tag_configure("line_added", background="#12261a")
    text.tag_configure("search_hit", background="#5a4b00", foreground=theme.FG_BRIGHT)
    text.tag_configure("search_current", background=theme.SELECTION, foreground=theme.FG_BRIGHT)
    text.tag_configure("bracket_match", background="#3a3d41")


def apply_highlight(text: tk.Text, filename: str, first: str, last: str) -> None:
    """Підсвітити рядки в діапазоні [first, last] (індекси Tk)."""
    highlighter = highlighter_for(filename)
    for tag in theme.SYNTAX_COLORS:
        text.tag_remove(tag, first, last)
    if highlighter.lang.name == "plain":
        return
    start_line = int(first.split(".")[0])
    end_line = int(last.split(".")[0])
    for line_no in range(start_line, end_line + 1):
        line_start = f"{line_no}.0"
        line_end = f"{line_no}.end"
        content = text.get(line_start, line_end)
        if not content:
            continue
        for begin, end, tag in highlighter.spans(content):
            text.tag_add(tag, f"{line_no}.{begin}", f"{line_no}.{end}")
