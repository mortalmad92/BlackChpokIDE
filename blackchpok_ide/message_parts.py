"""Структуровані частини повідомлення: текст, код, diff, статус інструмента.

Навіщо окремий шар, якщо є markdown:

* **збереження** — у ``chats.json`` лежить текст повідомлення. Коли
  потрібно показати повідомлення інакше (експорт, пошук, панель змін),
  доводиться заново розбирати markdown і сподіватись, що розбір
  збігається з тим, що бачив користувач;
* **перевірка** — «код окремим блоком» і «сирий JSON не потрапив у чат»
  стають властивостями ДАНИХ, а не наслідком того, як спрацював рендерер;
* **однакова форма** — і для відповіді моделі, і для результату
  інструмента, і для diff.

Модуль чистий: без tkinter, без мережі. Рендерер лише читає ці частини;
жодних других правил розбору в ньому немає.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import markdown_view

__all__ = [
    "DiffLine",
    "MessagePart",
    "PARTS",
    "build_parts",
    "code_parts",
    "diff_summary",
    "has_code",
    "parse_diff",
    "parts_to_markdown",
    "text_of",
]


#: Типи частин (концепція з вимог до UI-представлення).
PARTS: tuple[str, ...] = (
    "text", "code", "diff", "file_reference", "tool_status",
)

#: Ознаки того, що рядок — посилання на файл у тексті.
_FILE_REF_RE = re.compile(
    r"`([\w./\\-]+\.(?:py|pyi|js|jsx|ts|tsx|json|md|txt|html|css|scss|less|"
    r"yml|yaml|toml|ini|cfg|sql|ps1|bat|cmd|c|cpp|h|hpp|cs|java|rs|go|php|rb|kt))`",
    re.IGNORECASE,
)


@dataclass
class MessagePart:
    """Одна частина повідомлення.

    ``kind`` — один із :data:`PARTS`. Поля заповнюються за типом:
    ``code`` має ``language`` і ``content``; ``diff`` — ``filename`` і
    ``content``; ``file_reference`` — ``path``; ``tool_status`` —
    ``tool_name`` і ``status``.
    """

    kind: str
    content: str = ""
    language: str = ""
    filename: str = ""
    path: str = ""
    tool_name: str = ""
    status: str = ""            # running | success | error
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.kind}
        if self.kind == "code":
            data.update({"language": self.language, "content": self.content})
            if self.filename:
                data["filename"] = self.filename
        elif self.kind == "diff":
            data.update({"filename": self.filename, "content": self.content})
        elif self.kind == "file_reference":
            data.update({"path": self.path})
            if self.summary:
                data["description"] = self.summary
        elif self.kind == "tool_status":
            data.update({"toolName": self.tool_name, "status": self.status,
                         "summary": self.summary})
        else:
            data["content"] = self.content
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "MessagePart | None":
        if not isinstance(data, dict):
            return None
        kind = str(data.get("type") or "").strip()
        if kind not in PARTS:
            return None
        if kind == "code":
            return cls(kind=kind, content=str(data.get("content") or ""),
                       language=str(data.get("language") or ""),
                       filename=str(data.get("filename") or ""))
        if kind == "diff":
            return cls(kind=kind, content=str(data.get("content") or ""),
                       filename=str(data.get("filename") or ""))
        if kind == "file_reference":
            return cls(kind=kind, path=str(data.get("path") or ""),
                       summary=str(data.get("description") or ""))
        if kind == "tool_status":
            return cls(kind=kind, tool_name=str(data.get("toolName") or ""),
                       status=str(data.get("status") or ""),
                       summary=str(data.get("summary") or ""))
        return cls(kind="text", content=str(data.get("content") or ""))


def build_parts(text: str, *, language_map: bool = True) -> list[MessagePart]:
    """Розділити відповідь на частини: текст, коди й посилання на файли.

    Спирається на :func:`markdown_view.parse_markdown` — той самий розбір,
    що й рендерер. Це важливо: якщо б тут був СВІЙ парсер, «код у чаті»
    міг би виглядати по-різному залежно від місця показу.
    """
    del language_map
    parts: list[MessagePart] = []
    for segment in markdown_view.parse_markdown(text or ""):
        if segment.kind == "code":
            parts.append(MessagePart(
                kind="code", content=segment.text,
                language=(segment.language or "").strip()))
            continue
        # Звичайні блоки (заголовки, списки, цитати) лишаються текстом:
        # вони не потребують окремого відображення, але їхній порядок
        # із кодами зберігається.
        rendered = _segment_markdown(segment)
        if not rendered:
            continue
        if parts and parts[-1].kind == "text":
            parts[-1].content += "\n" + rendered
        else:
            parts.append(MessagePart(kind="text", content=rendered))

    # Посилання на файли — окремими частинами, щоб UI міг зробити їх
    # клікабельними, не шукаючи регуляркою по готовому тексту.
    for match in _FILE_REF_RE.finditer(text or ""):
        path = match.group(1).replace("\\", "/")
        if any(item.kind == "file_reference" and item.path == path for item in parts):
            continue
        parts.append(MessagePart(kind="file_reference", path=path))
    return parts


def _segment_markdown(segment: Any) -> str:
    """Повернути part у markdown-вигляді (щоб не втратити структуру)."""
    kind = getattr(segment, "kind", "text")
    body = getattr(segment, "text", "")
    if kind == "heading":
        level = max(1, min(6, int(getattr(segment, "level", 1) or 1)))
        return "#" * level + " " + body
    if kind == "bullet":
        return body
    if kind == "quote":
        return "\n".join("> " + line for line in body.split("\n"))
    if kind == "table":
        return body
    if kind == "hr":
        return "---"
    return body


def code_parts(parts: Sequence[MessagePart]) -> list[MessagePart]:
    """Лише кодові частини (для «вставити в редактор»)."""
    return [item for item in parts if item.kind == "code"]


def has_code(parts: Sequence[MessagePart]) -> bool:
    """Чи є у повідомленні хоч один блок коду."""
    return any(item.kind == "code" for item in parts)


def text_of(parts: Sequence[MessagePart]) -> str:
    """Скласти частини назад у markdown (для збереження й копіювання).

    ``file_reference`` НЕ додається: ця частина лише ПОЗНАЧАЄ шлях, який
    уже є в тексті. Якби ми його дописали, кожне збереження й повторне
    відкриття чату додавало б новий рядок — і текст ріс би сам собою.
    """
    chunks: list[str] = []
    for item in parts or ():
        if item.kind == "code":
            fence = "`" * 3
            header = item.language or ""
            chunks.append(f"{fence}{header}\n{item.content}\n{fence}")
        elif item.kind == "diff":
            fence = "`" * 3
            chunks.append(f"{fence}diff {item.filename}\n{item.content}\n{fence}")
        elif item.kind == "file_reference":
            continue
        elif item.kind == "tool_status":
            mark = {"running": "…", "success": "✓", "error": "✗"}.get(item.status, "·")
            chunks.append(f"{mark} {item.summary or item.tool_name}")
        else:
            chunks.append(item.content)
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


def parts_to_markdown(parts: Iterable[MessagePart]) -> str:
    """Те саме, що :func:`text_of`, але приймає будь-який ітератор."""
    return text_of(list(parts or ()))


# ─── Diff ───────────────────────────────────────────────────────────────────

@dataclass
class DiffLine:
    """Один рядок diff: доданий, видалений або контекст."""

    kind: str            # add | del | ctx
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text}


def parse_diff(old_text: str, new_text: str, *, context: int = 2) -> list[DiffLine]:
    """Порахувати різницю двох версій файлу для показу людині.

    Той самий підхід, що й ``chat_panel.make_diff_lines``, але тут — дані,
    а не віджети: їх можна зберегти, порахувати й перевірити тестом.
    """
    import difflib

    diff = difflib.unified_diff(
        (old_text or "").splitlines(), (new_text or "").splitlines(),
        lineterm="", n=max(0, int(context)),
    )
    rows: list[DiffLine] = []
    for line in list(diff)[2:]:
        if line.startswith("+") and not line.startswith("+++"):
            rows.append(DiffLine("add", line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            rows.append(DiffLine("del", line[1:]))
        else:
            rows.append(DiffLine("ctx", line))
    return rows


def diff_summary(rows: Sequence[DiffLine]) -> str:
    """Короткий підпис «+N −M» для заголовка картки змін."""
    added = sum(1 for row in rows or () if row.kind == "add")
    removed = sum(1 for row in rows or () if row.kind == "del")
    if not added and not removed:
        return "без змін"
    return f"+{added} −{removed}"
