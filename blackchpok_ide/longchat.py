"""Нескінченний чат: те, що вийшло з вікна, стає хронікою, а не зникає.

Проблема, яку це вирішує. Локальна модель має вікно 8–32 тисячі токенів.
Розмова в IDE живе годинами: людина пояснює, агент читає файли, обидва
уточнюють. Щойно історія перевищує вікно, ``AgentSession.trim`` викидає
найдавніші блоки — і саме там лежали домовленості («портал на 8081»,
«старий пароль не чіпати», «файл перейменували з calc на calculator»).
Через це довгий чат деградує: агент перепитує вже пояснене й повторює
виправлені помилки. Користувач бачить це як «модель забула».

Що робить цей модуль. Витіснений блок не викидається, а **згортається**:

1. репліки людини й агента — у рядки по ~260 символів;
2. результат інструмента — у перший змістовний рядок (сирий дамп файлу
   в хроніку не потрапляє: він у RAG-індексі, і повторювати його в промпті
   означало б знову платити за нього токенами);
3. хроніка має власний бюджет (частка вікна), тож вона не з'їдає місце
   в поточної задачі;
4. те, що не влізло в хроніку, уже лежить у довгостроковій пам'яті
   (NEUROMESH) і в RAG — тобто «забуте» з промпту лишається доступним
   через пошук, і хроніка чесно про це каже.

Модуль не тягне tkinter, не звертається до диска й не знає нічого про
SQLite: ним користуються і агент, і запис чату, і тести.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from . import context_budget

LOG = logging.getLogger("blackchpok.longchat")

__all__ = [
    "ASSISTANT_CLIP",
    "ConversationDigest",
    "DIGEST_SHARE",
    "DigestEntry",
    "MAX_ENTRIES",
    "TOOL_CLIP",
    "USER_CLIP",
    "describe_digest",
]

#: Частка вікна моделі, яку дозволено віддати хроніці.
#:
#: 12% — свідомо мало. Хроніка існує для зв'язності, а не для переказу
#: розмови: усе змістовне вже в пам'яті. На вікні 16384 це ≈1966 токенів,
#: близько двох десятків рядків — рівно стільки, скільки треба, щоб
#: зрозуміти, «про що ми взагалі говорили».
DIGEST_SHARE = 0.12

#: Скільки рядків хроніки тримаємо в записі чату (решта — в пам'яті).
MAX_ENTRIES = 80

#: Межі текстів, які потрапляють у хроніку.
USER_CLIP = 260
ASSISTANT_CLIP = 260
TOOL_CLIP = 160

#: Стеля символів на відрендерений блок (коли токени порахувати нічим).
MAX_RENDER_CHARS = 4200

#: Ролі, з яких будується хроніка.
_ROLES = ("user", "assistant", "tool")

#: Початки рядків, які в хроніці нічого не варті: службові підказки агенту,
#: порожні звіти, повторення того самого.
_NOISE_PREFIXES = (
    "ти не дав ні тексту", "твої файли збережено", "ти написав код у чаті",
    "ти виконав пошук", "робота ще не завершена", "пошук в інтернеті тут",
    "не повторюй", "продовжуй роботу",
)


def _collapse(text: str) -> str:
    """Згорнути пробіли й переноси рядків в один — хроніка це рядок."""
    return " ".join(str(text or "").split())


def _clip(text: str, limit: int) -> str:
    """Обрізати по межі слова, додавши «…» (щоб не рвати слово навпіл)."""
    body = _collapse(text)
    if len(body) <= limit:
        return body
    cut = body[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut + "…"


def _looks_noisy(body: str) -> bool:
    """Чи це службовий рядок, який у хроніку не додає змісту."""
    low = body.lower()
    return any(low.startswith(prefix) for prefix in _NOISE_PREFIXES)


@dataclass
class DigestEntry:
    """Один рядок хроніки: що сказали або що зробили."""

    role: str = "user"
    text: str = ""
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "text": self.text, "at": self.at}

    @classmethod
    def from_dict(cls, data: Any) -> "DigestEntry | None":
        if not isinstance(data, Mapping):
            return None
        role = str(data.get("role") or "").strip().lower()
        text = _collapse(data.get("text") or "")
        if role not in _ROLES or not text:
            return None
        try:
            at = float(data.get("at") or time.time())
        except (TypeError, ValueError):
            at = time.time()
        return cls(role=role, text=text, at=at)

    def label(self) -> str:
        return {"user": "Людина", "assistant": "Агент",
                "tool": "Інструмент"}.get(self.role, self.role)

    def render(self) -> str:
        return f"• {self.label()}: {self.text}"


class ConversationDigest:
    """Хроніка розмови: стислий слід того, що вже не вміщується у вікно.

    Живе в ЗАПИСІ ЧАТУ (``chat_store.Chat.digest``), а не в програмі: після
    перезапуску IDE довгий чат мусить пам'ятати свій початок так само, як
    і повідомлення.
    """

    def __init__(self, entries: Iterable[DigestEntry] | None = None) -> None:
        self.entries: list[DigestEntry] = [item for item in (entries or ())
                                           if isinstance(item, DigestEntry)]
        #: Скільки рядків уже витиснуто з самої хроніки (пішли в пам'ять).
        self.trimmed: int = 0
        #: Скільки блоків історії взагалі вийшло з вікна.
        self.absorbed_blocks: int = 0

    # ── наповнення ────────────────────────────────────────────────────────
    def absorb(self, messages: Iterable[Any]) -> int:
        """Додати витіснений блок історії; повернути кількість нових рядків.

        Повтор того самого тексту поспіль не додається: модель часто пише
        «Готово.» кілька разів, і хроніка з таких рядків ставала б
        беззмістовною.
        """
        added = 0
        for message in messages or ():
            entry = self._entry_for(message)
            if entry is None:
                continue
            if self.entries and self.entries[-1].role == entry.role \
                    and self.entries[-1].text == entry.text:
                continue
            self.entries.append(entry)
            added += 1
        if added:
            self.absorbed_blocks += 1
        self._trim()
        return added

    def add(self, role: str, text: str) -> bool:
        """Додати один рядок вручну (напр. рішення користувача)."""
        entry = self._entry_for({"role": role, "content": text})
        if entry is None:
            return False
        if self.entries and self.entries[-1].role == entry.role \
                and self.entries[-1].text == entry.text:
            return False
        self.entries.append(entry)
        self._trim()
        return True

    def _entry_for(self, message: Any) -> "DigestEntry | None":
        """Перетворити повідомлення історії в рядок хроніки."""
        if isinstance(message, Mapping):
            role = str(message.get("role") or "").strip().lower()
            body = _collapse(message.get("content") or "")
            name = str(message.get("name") or message.get("tool_name") or "")
        else:
            role = str(getattr(message, "role", "") or "").strip().lower()
            body = _collapse(getattr(message, "text", "") or "")
            name = ""
        if role not in _ROLES or not body:
            return None
        if role == "tool":
            # Результат інструмента: лише перший змістовний рядок. Сирий
            # вивід read_file — це сотні рядків коду, які вже є в RAG.
            first = next((line.strip() for line in
                          str(message.get("content") if isinstance(message, Mapping)
                              else body).splitlines() if line.strip()), "")
            body = _clip(first or body, TOOL_CLIP)
            body = f"{name or 'tool'}: {body}"
        elif role == "user":
            if _looks_noisy(body):
                return None
            body = _clip(body, USER_CLIP)
        else:
            if _looks_noisy(body):
                return None
            body = _clip(body, ASSISTANT_CLIP)
        return DigestEntry(role=role, text=body)

    def _trim(self) -> None:
        """Лишити MAX_ENTRIES найновіших рядків."""
        extra = len(self.entries) - MAX_ENTRIES
        if extra > 0:
            del self.entries[:extra]
            self.trimmed += extra

    # ── відображення ──────────────────────────────────────────────────────
    def render(self, *, window_tokens: int = 0, counter: Any = None,
               share: float = DIGEST_SHARE, max_entries: int = 0) -> str:
        """Блок для промпту — стільки рядків, скільки вміщається в бюджет.

        Порядок — хронологічний. Якщо бюджет малий, лишаються НАЙНОВІШІ
        рядки: вони найближчі до живої частини розмови й краще пояснюють
        «що ми робимо зараз». Старіші не втрачені — вони в пам'яті, і про
        це прямо сказано в блоці.
        """
        if not self.entries:
            return ""
        limit_entries = int(max_entries or 0) or MAX_ENTRIES
        chosen: list[DigestEntry] = []
        used = 0
        budget = 0
        if window_tokens and window_tokens > 0:
            budget = max(120, int(window_tokens * max(0.02, min(0.5, share))))
        # Заголовок теж коштує токенів — рахуємо його одразу.
        header = "Хроніка розмови (стиснуто, бо не вміщається у вікно):"
        used += context_budget.estimate_tokens(header, counter=counter)
        for entry in reversed(self.entries[-limit_entries:]):
            line = entry.render()
            cost = context_budget.estimate_tokens(line, counter=counter)
            if budget and used + cost > budget:
                break
            if not budget:
                # Без вікна обмежуємось символами: так блок не розростеться
                # в моделі, яка ще не завантажена.
                grown = sum(len(item.render()) + 1 for item in chosen) + len(line)
                if grown > MAX_RENDER_CHARS:
                    break
            chosen.append(entry)
            used += cost
        if not chosen:
            return ""
        chosen.reverse()
        lines = [header, *(entry.render() for entry in chosen)]
        missing = len(self.entries) - len(chosen)
        if missing > 0 or self.trimmed:
            total = missing + self.trimmed
            lines.append(f"(ще {total} давніших вузлів — у довгостроковій "
                         f"пам'яті: пошук у NEUROMESH і RAG)")
        return "\n".join(lines)

    def memory_text(self, *, limit: int = 1400) -> str:
        """Текст для запису в довгострокову пам'ять (стисло, з мітками)."""
        if not self.entries:
            return ""
        parts: list[str] = []
        used = 0
        for entry in self.entries:
            block = f"{entry.label()}: {entry.text}"
            if used + len(block) + 3 > limit:
                break
            parts.append(block)
            used += len(block) + 3
        if not parts:
            return ""
        return "Хроніка розмови (витиснуто з вікна). " + " | ".join(parts)

    # ── серіалізація ──────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "trimmed": self.trimmed,
            "absorbed_blocks": self.absorbed_blocks,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ConversationDigest":
        """Відновити хроніку з диска, терпимо до сміття."""
        digest = cls()
        if not isinstance(data, Mapping):
            return digest
        raw = data.get("entries")
        if isinstance(raw, list):
            for item in raw:
                entry = DigestEntry.from_dict(item)
                if entry is not None:
                    digest.entries.append(entry)
        digest.entries = digest.entries[-MAX_ENTRIES:]
        try:
            digest.trimmed = max(0, int(data.get("trimmed") or 0))
        except (TypeError, ValueError):
            digest.trimmed = 0
        try:
            digest.absorbed_blocks = max(0, int(data.get("absorbed_blocks") or 0))
        except (TypeError, ValueError):
            digest.absorbed_blocks = 0
        return digest

    # ── службове ──────────────────────────────────────────────────────────
    def clear(self) -> None:
        self.entries.clear()
        self.trimmed = 0
        self.absorbed_blocks = 0

    def stats(self) -> dict[str, Any]:
        return {
            "entries": len(self.entries),
            "trimmed": self.trimmed,
            "absorbed_blocks": self.absorbed_blocks,
            "chars": sum(len(entry.text) for entry in self.entries),
        }

    @property
    def empty(self) -> bool:
        return not self.entries


def describe_digest(digest: Any) -> str:
    """Один рядок для журналу: скільки розмови вже живе поза вікном."""
    if not isinstance(digest, ConversationDigest) or digest.empty:
        return "Хроніка розмови порожня."
    stats = digest.stats()
    parts = [f"{stats['entries']} вузлів"]
    if stats["absorbed_blocks"]:
        parts.append(f"{stats['absorbed_blocks']} блоків витиснуто")
    if stats["trimmed"]:
        parts.append(f"{stats['trimmed']} — у пам'яті")
    return "Хроніка: " + ", ".join(parts) + "."
