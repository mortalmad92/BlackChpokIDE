"""Рендерер Markdown для панелі чату BlackChpok IDE.

Модуль свідомо не імпортує ``tkinter`` на рівні модуля — усе, що стосується
віджетів, імпортується ліниво (всередині методів). Завдяки цьому
:func:`parse_markdown` та :func:`parse_inline` — чисті функції, які можна
викликати у фоновому потоці або в тестах без дисплея.

Типовий порядок інтеграції::

    renderer = MarkdownRenderer(self.history, self.fonts, ChatPalette())
    renderer.configure_tags()                 # один раз (або після зміни теми)
    codes = renderer.render(answer_text)      # тексти блоків коду
    # правий клік по блоку коду -> renderer.copy_code(index)
    # «вставити в редактор»   -> editor.insert("end", codes[index])
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

__all__ = [
    "ChatPalette",
    "Segment",
    "MarkdownRenderer",
    "parse_markdown",
    "parse_inline",
    "plain_text",
]


# ── Палітра ─────────────────────────────────────────────────────────────────

@dataclass
class ChatPalette:
    """Кольори, якими малюється markdown у панелі чату.

    Значення за замовчуванням — темна тема IDE (наближена до VS Code Dark).
    """

    fg: str = "#d4d4d4"
    fg_dim: str = "#8b8b8b"
    fg_bright: str = "#ffffff"
    accent: str = "#4f8cff"
    success: str = "#3fb950"
    warn: str = "#d29922"
    error: str = "#f85149"
    code_bg: str = "#141416"
    code_fg: str = "#ce9178"
    border: str = "#26262a"
    bg: str = "#0e0e10"
    bg_input: str = "#17171a"
    selection: str = "#264f78"


# ── Сегменти ────────────────────────────────────────────────────────────────

@dataclass
class Segment:
    """Один блок документа.

    ``kind`` — один із: "text", "code", "heading", "bullet", "quote",
    "table", "hr", "rule_code".

    ``index`` — порядковий номер блоку коду (для "вставити в редактор"),
    для решти сегментів дорівнює -1.
    """

    kind: str
    text: str
    language: str = ""
    level: int = 0
    index: int = -1


# ── Регулярні вирази розбору ────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_HEADING_RE = re.compile(r"^ {0,3}(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t]*#*[ \t]*$")
_HR_RE = re.compile(r"^ {0,3}(?P<char>[-*_])(?:[ \t]*(?P=char)){2,}[ \t]*$")
_QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?(?P<text>.*)$")
_BULLET_RE = re.compile(r"^ {0,3}(?P<marker>[-*+]|\d{1,3}[.)])[ \t]+(?P<text>.*)$")
_TABLE_SEP_RE = re.compile(r"^[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)+\|?[ \t]*$")

#: Інлайн-код: `код` або ``код із бектиками``.
_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)(?P<body>.+?)(?P=ticks)")

#: Наголоси та посилання. Жирний — перед курсивом; порожні краї заборонені.
_EMPHASIS_RE = re.compile(
    r"\[(?P<link_label>[^\]\n]*)\]\((?P<link_url>[^)\s]*)\)"
    r"|\*\*(?!\s)(?P<bold>.+?)(?<!\s)\*\*"
    r"|(?<!\w)__(?!\s)(?P<bold_u>.+?)(?<!\s)__(?!\w)"
    r"|(?<![\w*])\*(?!\s)(?P<italic>.+?)(?<!\s)\*(?![\w*])"
    r"|(?<!\w)_(?!\s)(?P<italic_u>.+?)(?<!\s)_(?!\w)"
    r"|(?P<plain>[^\[\]*_`]+)"
)


# ── Чистий розбір ───────────────────────────────────────────────────────────

def _split_row(line: str) -> list[str]:
    """Поділяє рядок таблиці на клітинки (екрановані \\| не рахуються)."""
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|") and not raw.endswith("\\|"):
        raw = raw[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", raw)]


def _starts_table(lines: Sequence[str], index: int) -> bool:
    """Чи починається на ``index`` проста pipe-таблиця."""
    if index + 1 >= len(lines):
        return False
    head = lines[index]
    sep = lines[index + 1]
    if "|" not in head:
        return False
    return bool(_TABLE_SEP_RE.match(sep))


def parse_markdown(text: str) -> list[Segment]:
    """Розбирає markdown на список :class:`Segment`.

    Підтримується: блоки коду ```lang … ``` (у тому числі незакритий блок —
    він теж вважається кодом), заголовки ``#``..``######``, марковані списки
    ``- ``, ``* ``, ``+ `` і нумеровані ``1. ``, цитати ``> ``, горизонтальні
    лінії ``---`` / ``***``, прості pipe-таблиці (один сегмент з «сирими»
    рядками) та звичайні абзаци.

    Порожні рядки розділяють абзаци; сусідні прості рядки склеюються в один
    сегмент "text" з ``\\n`` усередині. Функція не торкається tkinter.
    """
    if not text:
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[Segment] = []
    paragraph: list[str] = []
    code_index = -1

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            segments.append(Segment(kind="text", text="\n".join(paragraph)))
            paragraph = []

    i = 0
    total = len(lines)
    while i < total:
        line = lines[i]
        stripped = line.strip()

        # 1. Блок коду (у тому числі незакритий — до кінця тексту).
        fence = _FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            fence_char = fence.group("fence")[0]
            fence_len = len(fence.group("fence"))
            info = (fence.group("info") or "").strip()
            language = ""
            if info:
                language = info.split()[0].strip("{}")
                language = language.lstrip(".").strip()
            body: list[str] = []
            i += 1
            closed = False
            while i < total:
                candidate = lines[i]
                closing = re.match(r"^ {0,3}(?P<fence>`{3,}|~{3,})[ \t]*$", candidate)
                if (
                    closing
                    and closing.group("fence")[0] == fence_char
                    and len(closing.group("fence")) >= fence_len
                ):
                    closed = True
                    i += 1
                    break
                body.append(candidate)
                i += 1
            body_text = "\n".join(body)
            if not closed:
                # Хвіст із порожніх рядків у незакритому блоці не потрібен.
                body_text = body_text.rstrip("\n")
            code_index += 1
            segments.append(
                Segment(
                    kind="code",
                    text=body_text,
                    language=language,
                    index=code_index,
                )
            )
            continue

        # 2. Порожній рядок — межа абзацу.
        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # 3. Заголовок.
        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            segments.append(
                Segment(
                    kind="heading",
                    text=heading.group("text"),
                    level=len(heading.group("hashes")),
                )
            )
            i += 1
            continue

        # 4. Горизонтальна лінія.
        if _HR_RE.match(line):
            flush_paragraph()
            segments.append(Segment(kind="hr", text=stripped))
            i += 1
            continue

        # 5. Таблиця.
        if _starts_table(lines, i):
            flush_paragraph()
            rows: list[str] = []
            while i < total and lines[i].strip() and "|" in lines[i]:
                rows.append(lines[i].rstrip())
                i += 1
            segments.append(Segment(kind="table", text="\n".join(rows)))
            continue

        # 6. Цитата: сусідні рядки склеюються в один блок.
        quote = _QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            quoted: list[str] = []
            while i < total:
                current = _QUOTE_RE.match(lines[i])
                if not current:
                    break
                quoted.append(current.group("text"))
                i += 1
            segments.append(Segment(kind="quote", text="\n".join(quoted)))
            continue

        # 7. Елемент списку (маркер зберігається в тексті сегмента).
        if _BULLET_RE.match(line):
            flush_paragraph()
            segments.append(Segment(kind="bullet", text=stripped))
            i += 1
            continue

        # 8. Звичайний рядок абзацу.
        paragraph.append(line.rstrip())
        i += 1

    flush_paragraph()
    return segments


def _parse_emphasis(chunk: str) -> list[tuple[str, str]]:
    """Розбирає наголоси й посилання у фрагменті без інлайн-коду."""
    result: list[tuple[str, str]] = []
    position = 0
    for match in _EMPHASIS_RE.finditer(chunk):
        if match.start() > position:
            result.append(("text", chunk[position:match.start()]))
        if match.group("link_label") is not None:
            label = match.group("link_label")
            url = match.group("link_url")
            result.append(("link", f"{label} ({url})" if url else label))
        elif match.group("bold") is not None:
            result.append(("bold", match.group("bold")))
        elif match.group("bold_u") is not None:
            result.append(("bold", match.group("bold_u")))
        elif match.group("italic") is not None:
            result.append(("italic", match.group("italic")))
        elif match.group("italic_u") is not None:
            result.append(("italic", match.group("italic_u")))
        else:
            result.append(("text", match.group("plain") or ""))
        position = match.end()
    if position < len(chunk):
        result.append(("text", chunk[position:]))
    return result


def _merge_plain(chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Склеює сусідні шматки "text" — інакше зайві дрібні вставки в віджет."""
    merged: list[tuple[str, str]] = []
    for style, visible in chunks:
        if not visible:
            continue
        if style == "text" and merged and merged[-1][0] == "text":
            merged[-1] = ("text", merged[-1][1] + visible)
        else:
            merged.append((style, visible))
    return merged


def parse_inline(text: str) -> list[tuple[str, str]]:
    """Розбирає інлайн-розмітку на пари ``(стиль, видимий текст)``.

    Стилі: "text", "bold", "italic", "code", "link". Для посилання
    ``[підпис](url)`` повертається видимий текст ``"підпис (url)"``, тож
    адреса не втрачається.
    """
    if not text:
        return []
    result: list[tuple[str, str]] = []
    position = 0
    for match in _CODE_SPAN_RE.finditer(text):
        if match.start() > position:
            result.extend(_parse_emphasis(text[position:match.start()]))
        body = match.group("body")
        if len(body) > 2 and body.startswith(" ") and body.endswith(" ") and body.strip():
            body = body[1:-1]
        result.append(("code", body))
        position = match.end()
    if position < len(text):
        result.extend(_parse_emphasis(text[position:]))
    return _merge_plain(result)


def _visible(text: str) -> str:
    """Текст без інлайн-маркерів (для таблиць, підказок, довжин)."""
    return "".join(chunk for _style, chunk in parse_inline(text))


def plain_text(markdown: str) -> str:
    """Повертає markdown зі знятими маркерами — для підказок і статусу."""
    if not markdown:
        return ""
    lines: list[str] = []
    for segment in parse_markdown(markdown):
        if segment.kind == "text":
            lines.append(_visible(segment.text))
        elif segment.kind == "heading":
            lines.append(_visible(segment.text))
        elif segment.kind == "bullet":
            content = segment.text
            marker = _BULLET_RE.match(content)
            if marker:
                content = marker.group("text")
            lines.append("• " + _visible(content))
        elif segment.kind == "quote":
            for part in segment.text.split("\n"):
                lines.append(_visible(part))
        elif segment.kind == "table":
            for row in segment.text.split("\n"):
                if _TABLE_SEP_RE.match(row):
                    continue
                cells = [_visible(cell) for cell in _split_row(row)]
                lines.append("  ".join(cell for cell in cells if cell))
        elif segment.kind == "code":
            lines.append(segment.text)
        elif segment.kind == "hr":
            lines.append("—" * 12)
        # "rule_code" у звичайному тексті не показуємо
    return "\n".join(line for line in lines if line is not None).strip("\n")


# ── Рендеринг у tk.Text ─────────────────────────────────────────────────────

#: Скільки символів коду ще підсвічуємо. Довший блок малюємо без підсвітки:
#: користь від неї мала, а робота на кожне перемальовування — помітна.
_HIGHLIGHT_LIMIT = 24_000

#: Відповідність «мова у шапці блоку → розширення для :mod:`syntax`.
#:
#: Моделі пишуть по-різному: ``python``, ``py``, ``Python3``, ``ts``,
#: ``bash``/``shell``/``sh``. Зводимо все до одного розширення, інакше
#: підсвітка мовчки не вмикалась би на половині блоків.
_LANGUAGE_EXT: dict[str, str] = {
    "py": "py", "python": "py", "python3": "py", "pyi": "py",
    "js": "js", "javascript": "js", "node": "js", "mjs": "js",
    "ts": "ts", "typescript": "ts",
    "tsx": "tsx", "jsx": "jsx",
    "json": "json", "jsonc": "json", "jsonl": "json",
    "html": "html", "htm": "html", "xml": "xml", "svg": "svg",
    "css": "css", "scss": "scss", "less": "less",
    "sql": "sql", "sqlite": "sql",
    "sh": "sh", "bash": "bash", "shell": "bash", "zsh": "bash",
    "ps1": "ps1", "powershell": "ps1", "pwsh": "ps1",
    "bat": "bat", "cmd": "bat", "batcmd": "bat",
    "yaml": "yaml", "yml": "yaml", "toml": "toml", "ini": "ini",
    "cfg": "cfg", "conf": "conf",
    "md": "md", "markdown": "md", "mdx": "mdx",
    "c": "c", "h": "h", "cc": "cc", "cpp": "cpp", "c++": "cpp",
    "hpp": "hpp", "cs": "cs", "csharp": "cs", "java": "java",
    "rs": "rs", "rust": "rs", "go": "go", "golang": "go",
    "kt": "kt", "kotlin": "kt", "swift": "swift", "dart": "dart",
}


def _syntax_ext(language: str) -> str:
    """Розширення для підсвітки за назвою мови з блоку коду (``""`` — не знаємо)."""
    clean = (language or "").strip().lower()
    if not clean:
        return ""
    # «python title=calc.py» або «js {.numberLines}» — беремо перше слово.
    clean = clean.split()[0].strip("{}.")
    return _LANGUAGE_EXT.get(clean, clean if clean.isalnum() else "")


def code_language(name: str) -> str:
    """Назва мови за іменем файлу (для шапки блоку коду)."""
    ext = (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
    for label, mapped in _LANGUAGE_EXT.items():
        if mapped == ext and label.isalpha() and len(label) > len(ext):
            return label
    return ext or "код"

class MarkdownRenderer:
    """Малює markdown у ``tk.Text`` через теги (жодних вбудованих кнопок).

    Клітинка коду — це три рядки-тексти: шапка ("python · копіювати"),
    тіло з реальними переносами рядків і підвал-лінійка. Копіювання та
    «вставити в редактор» виконує виклик, який має індекс блоку.
    """

    #: Ширина декоративних ліній (у символах).
    RULE_WIDTH = 40

    #: Скільки рядків коду показувати до згортання (0 — показувати все).
    #:
    #: Довгий блок на 2000 рядків розтягував картку на кілька екранів і
    #: витісняв поле вводу. Повний код однаково живе у файлі, у чаті
    #: достатньо початку — з чесним підписом, скільки рядків приховано.
    COLLAPSE_AFTER = 40

    def __init__(self, text_widget: Any, fonts: Any, palette: Optional[ChatPalette] = None,
                 *, highlight: bool = True,
                 collapse_after: Optional[int] = None) -> None:
        self.text = text_widget
        self.fonts = fonts
        self.palette = palette or ChatPalette()
        self.highlight = bool(highlight)
        self._collapse_limit = (self.COLLAPSE_AFTER if collapse_after is None
                                else max(0, int(collapse_after)))
        self._blocks: list[str] = []
        self._configured = False
        self._syntax_ready = False

    # ── шрифти ──
    def _font(self, base: Any, *, size_delta: int = 0, slant: str = "", weight: str = "") -> Any:
        """Повертає похідний шрифт; за будь-якої помилки — базовий."""
        try:
            actual = base.actual()
            family = actual.get("family") or "Consolas"
            size = int(actual.get("size") or 10)
            if size_delta:
                size = size + size_delta if size > 0 else size - size_delta
            spec: list[Any] = [family, size]
            style = " ".join(part for part in (weight, slant) if part)
            if style:
                spec.append(style)
            return tuple(spec)
        except Exception:  # noqa: BLE001 — шрифти можуть бути будь-яким об'єктом
            return base

    # ── теги ──
    def configure_tags(self) -> None:
        """Створює/оновлює всі теги на віджеті. Безпечно викликати повторно."""
        palette = self.palette
        widget = self.text
        chat = getattr(self.fonts, "chat", None)
        chat_code = getattr(self.fonts, "chat_code", None)
        ui_bold = getattr(self.fonts, "ui_bold", None)
        ui_small = getattr(self.fonts, "ui_small", None)

        widget.tag_configure("md_text", foreground=palette.fg, font=chat, spacing1=2, spacing3=2)
        widget.tag_configure("md_bold", foreground=palette.fg_bright, font=ui_bold)
        widget.tag_configure("md_italic", foreground=palette.fg, font=self._font(chat, slant="italic"))
        widget.tag_configure(
            "md_inline_code",
            foreground=palette.code_fg,
            background=palette.code_bg,
            font=chat_code,
            lmargin1=2,
            lmargin2=2,
        )
        widget.tag_configure(
            "md_h1",
            foreground=palette.fg_bright,
            font=self._font(ui_bold, size_delta=4),
            spacing1=10,
            spacing3=4,
        )
        widget.tag_configure(
            "md_h2",
            foreground=palette.accent,
            font=self._font(ui_bold, size_delta=2),
            spacing1=8,
            spacing3=3,
        )
        widget.tag_configure(
            "md_h3",
            foreground=palette.fg,
            font=self._font(ui_bold, size_delta=1),
            spacing1=6,
            spacing3=2,
        )
        widget.tag_configure(
            "md_bullet",
            foreground=palette.fg,
            lmargin1=14,
            lmargin2=26,
            spacing1=1,
        )
        widget.tag_configure(
            "md_quote",
            foreground=palette.fg_dim,
            background=palette.bg_input,
            lmargin1=14,
            lmargin2=14,
            spacing1=2,
            spacing3=2,
        )
        widget.tag_configure("md_rule", foreground=palette.border, background=palette.bg, spacing1=6, spacing3=6)
        widget.tag_configure("md_table", foreground=palette.fg, font=chat_code, spacing1=1, spacing3=1)
        widget.tag_configure("md_link", foreground=palette.accent, underline=True)
        widget.tag_configure(
            "md_code_header",
            foreground=palette.fg_dim,
            background=palette.border,
            font=ui_small,
            lmargin1=8,
            lmargin2=8,
            spacing1=6,
        )
        widget.tag_configure(
            "md_code_body",
            foreground=palette.code_fg,
            background=palette.code_bg,
            font=chat_code,
            lmargin1=10,
            lmargin2=10,
            rmargin=8,
        )
        widget.tag_configure(
            "md_code_footer",
            foreground=palette.border,
            background=palette.code_bg,
            font=ui_small,
            lmargin1=8,
            lmargin2=8,
            spacing3=8,
        )

        # Наголоси мають вигравати в базових тегів (порядок пріоритету в Tk).
        for tag in ("md_bold", "md_italic", "md_inline_code", "md_link"):
            try:
                widget.tag_raise(tag)
            except Exception:  # noqa: BLE001 — віджет може не мати тега
                pass

        self._configured = True

    def _ensure_base_tag(self, base_tag: str) -> str:
        """Створює базовий тег, якщо виклик передав власний."""
        try:
            existing = set(self.text.tag_names())
        except Exception:  # noqa: BLE001
            return base_tag
        if base_tag not in existing:
            self.text.tag_configure(
                base_tag,
                foreground=self.palette.fg,
                font=getattr(self.fonts, "chat", None),
            )
        return base_tag

    # ── вставка ──
    def _insert(self, text: str, tags: Any = None) -> None:
        if tags is None:
            self.text.insert("end", text)
        else:
            self.text.insert("end", text, tags)

    def _emit_inline(self, text: str, base_tag: str, extra: Sequence[str] = ()) -> None:
        """Вставляє текст з інлайн-розміткою, зберігаючи базовий тег."""
        for style, visible in parse_inline(text):
            if style == "bold":
                tags: Any = (base_tag, "md_bold", *extra)
            elif style == "italic":
                tags = (base_tag, "md_italic", *extra)
            elif style == "code":
                tags = (base_tag, "md_inline_code", *extra)
            elif style == "link":
                tags = (base_tag, "md_link", *extra)
            else:
                tags = (base_tag, *extra)
            self._insert(visible, tags)

    def _emit_code(self, segment: Segment, base_tag: str) -> None:
        """Блок коду: шапка з мовою, тіло з підсвіткою, підвал.

        Підсвітка береться з :mod:`syntax` — того самого, що малює редактор.
        Тому ``python`` у чаті виглядає так само, як у файлі, і не треба
        другої реалізації на кожну мову.
        """
        language = (segment.language or "").strip() or "код"
        lines = segment.text.split("\n")
        body = segment.text
        if body and not body.endswith("\n"):
            body += "\n"
        hidden = self._collapse_limit and len(lines) > self._collapse_limit
        shown = lines[: self._collapse_limit] if hidden else lines
        shown_body = "\n".join(shown) + ("\n" if shown else "")

        header = f"  {language}  ·  копіювати"
        if hidden:
            header += f"  ·  показано {self._collapse_limit} з {len(lines)} рядків"
        self._insert(header + "\n", "md_code_header")
        if shown_body:
            self._insert_code(shown_body, segment.language)
        self._insert("  " + "─" * self.RULE_WIDTH + "\n", "md_code_footer")
        if hidden:
            self._insert(
                f"  … ще {len(lines) - self._collapse_limit} рядків "
                "(повний код — у файлі)\n",
                "md_code_footer",
            )
        self._insert("\n", base_tag)

    def _insert_code(self, body: str, language: str) -> None:
        """Вставити код із підсвіткою синтаксису (``syntax``), якщо вийде.

        Підсвітка необов'язкова: будь-який збій лишає звичайний моноширинний
        текст. Довгі блоки не підсвічуємо — це зайва робота на кожен рух
        стрічки, а користь мала.
        """
        ext = _syntax_ext(language)
        config = None
        highlighter = None
        if self.highlight and len(body) <= _HIGHLIGHT_LIMIT and ext:
            try:
                from . import syntax as syntax_module

                config = syntax_module.language_for(f"x.{ext}")
                if config.name != "plain":
                    highlighter = syntax_module.Highlighter(config)
                    self._configure_syntax_tags(config)
            except Exception:              # noqa: BLE001 — підсвітка не критична
                highlighter = None
        start_line = int(str(self.text.index("end-1c")).split(".")[0])
        self._insert(body, "md_code_body")
        if highlighter is None:
            return
        for offset, line in enumerate(body.split("\n")):
            if not line:
                continue
            for begin, end, tag in highlighter.spans(line):
                try:
                    self.text.tag_add(
                        f"syn_{tag}", f"{start_line + offset}.{begin}",
                        f"{start_line + offset}.{end}")
                except Exception:          # noqa: BLE001 — індекс поза текстом
                    break

    def _configure_syntax_tags(self, config: Any) -> None:
        """Створити теги ``syn_*`` з кольорів теми (один раз на віджет)."""
        if self._syntax_ready:
            return
        try:
            from . import theme as theme_module

            colors = getattr(theme_module, "SYNTAX_COLORS", {}) or {}
        except Exception:                  # noqa: BLE001
            colors = {}
        code_font = getattr(self.fonts, "chat_code", None)
        bold_font = getattr(self.fonts, "ui_bold", None)
        for name, colour in colors.items():
            try:
                self.text.tag_configure(
                    f"syn_{name}",
                    foreground=colour,
                    font=bold_font if name in {"keyword", "control", "tag"} else code_font,
                )
            except Exception:              # noqa: BLE001
                continue
        for tag in list(colors):
            try:
                self.text.tag_raise(f"syn_{tag}")
            except Exception:              # noqa: BLE001
                continue
        self.text.tag_raise("md_code_body")
        for tag in list(colors):
            try:
                self.text.tag_raise(f"syn_{tag}")
            except Exception:              # noqa: BLE001
                continue
        self._syntax_ready = True

    def _emit_heading(self, segment: Segment, base_tag: str) -> None:
        level = segment.level if segment.level > 0 else 1
        tag = f"md_h{min(level, 3)}"
        self._emit_inline(segment.text, base_tag, extra=(tag,))
        self._insert("\n", (base_tag, tag))

    def _emit_bullet(self, segment: Segment, base_tag: str) -> None:
        match = _BULLET_RE.match(segment.text)
        marker = match.group("marker") if match else "-"
        content = match.group("text") if match else segment.text
        if marker[0].isdigit():
            prefix = marker if marker.endswith(".") else f"{marker[0]}."
        else:
            prefix = "•"
        self._insert(f"{prefix} ", ("md_bullet",))
        self._emit_inline(content, base_tag, extra=("md_bullet",))
        self._insert("\n", ("md_bullet",))

    def _emit_quote(self, segment: Segment, base_tag: str) -> None:
        for line in segment.text.split("\n"):
            self._insert("│ ", ("md_quote",))
            self._emit_inline(line, base_tag, extra=("md_quote",))
            self._insert("\n", ("md_quote",))

    def _emit_rule(self, segment: Segment, base_tag: str) -> None:
        self._insert("  " + "─" * self.RULE_WIDTH + "\n", ("md_rule",))
        self._insert("\n", base_tag)

    def _emit_table(self, segment: Segment, base_tag: str) -> None:
        rows = [
            line for line in segment.text.split("\n")
            if line.strip() and not _TABLE_SEP_RE.match(line)
        ]
        if not rows:
            return
        matrix = [[_visible(cell) for cell in _split_row(line)] for line in rows]
        columns = max(len(row) for row in matrix)
        widths = [0] * columns
        for row in matrix:
            for column, cell in enumerate(row):
                widths[column] = max(widths[column], len(cell))

        def render_row(cells: Sequence[str]) -> str:
            padded = [cell.ljust(widths[index]) for index, cell in enumerate(cells)]
            padded += [""] * (columns - len(padded))
            return "│ " + " │ ".join(padded) + " │\n"

        self._insert(render_row(matrix[0]), ("md_table", "md_bold"))
        self._insert("├" + "┼".join("─" * (width + 2) for width in widths) + "┤\n", ("md_table",))
        for row in matrix[1:]:
            self._insert(render_row(row), ("md_table",))
        self._insert("\n", base_tag)

    def _emit(self, segment: Segment, base_tag: str) -> None:
        if segment.kind == "code":
            self._emit_code(segment, base_tag)
        elif segment.kind == "heading":
            self._emit_heading(segment, base_tag)
        elif segment.kind == "bullet":
            self._emit_bullet(segment, base_tag)
        elif segment.kind == "quote":
            self._emit_quote(segment, base_tag)
        elif segment.kind == "table":
            self._emit_table(segment, base_tag)
        elif segment.kind == "hr":
            self._emit_rule(segment, base_tag)
        elif segment.kind == "rule_code":
            self._insert("  " + "· " * (self.RULE_WIDTH // 2) + "\n", ("md_rule", "md_code_body"))
        else:
            self._emit_inline(segment.text, base_tag)
            self._insert("\n", base_tag)

    # ── публічний API ──
    def render(self, markdown: str, *, base_tag: str = "md_text", clear: bool = True) -> list[str]:
        """Пише markdown у віджет і повертає тексти блоків коду.

        Стан віджета виклик не змінює: якщо він був "disabled", його
        тимчасово вмикають і в кінці повертають назад.
        """
        if not self._configured:
            self.configure_tags()

        segments = parse_markdown(markdown or "")
        blocks = [segment.text for segment in segments if segment.kind == "code"]

        previous_state = str(self.text.cget("state"))
        restore_disabled = previous_state == "disabled"
        if restore_disabled:
            self.text.configure(state="normal")
        try:
            if clear:
                self.text.delete("1.0", "end")
            base = self._ensure_base_tag(base_tag)
            for segment in segments:
                self._emit(segment, base)
            self._blocks = blocks
        finally:
            if restore_disabled:
                self.text.configure(state="disabled")
        return blocks

    def get_code(self, index: int) -> Optional[str]:
        """Текст блоку коду за індексом (для «вставити в редактор»)."""
        if 0 <= index < len(self._blocks):
            return self._blocks[index]
        return None

    def copy_code(self, index: int) -> bool:
        """Копіює блок коду в буфер обміну. ``False`` — якщо індексу немає."""
        if not (0 <= index < len(self._blocks)):
            return False
        try:
            self.text.clipboard_clear()
            self.text.clipboard_append(self._blocks[index])
            return True
        except Exception:  # noqa: BLE001 — буфер недоступний (наприклад, без дисплея)
            return False

    @property
    def code_blocks(self) -> list[str]:
        """Тексти блоків коду з останнього :meth:`render`."""
        return list(self._blocks)
