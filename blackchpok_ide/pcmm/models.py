"""Модель спогаду PCMM: типи, provenance, впевненість, зв'язки.

Один спогад — це не «шматок тексту», а твердження з ІСТОРІЄЮ:

* ``kind`` — що це: факт, рішення, помилка, виправлення, завдання,
  залежність файлів, результат інструмента, обмеження, зміна;
* ``source`` і ``provenance`` — ЗВІДКИ це взято (файл:рядок, інструмент,
  повідомлення користувача) — без цього неможливо перевірити твердження;
* ``confidence`` — наскільки віримо (0..1), окремо від «важливості»;
* ``valid_from``/``valid_to`` — коли факт діяв (часовий вимір);
* ``superseded_by`` — чим замінено, замість видалення.

Видаляти підтверджений факт не можна: він позначається як застарілий і
лишається в історії. Це і є «причинно-наслідкова пам'ять» у практичному
сенсі: видно, ЩО змінилось, КОЛИ і ЧОМУ.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

#: Типи спогадів (розширювати можна, але не перейменовувати — на них
#: спираються ваги пошуку й інтерфейс).
KINDS = (
    "fact",        # перевірене твердження про проєкт
    "decision",    # прийняте рішення (і чому)
    "error",       # помилка, яка трапилась
    "fix",         # виправлення помилки
    "task",        # завдання його стан
    "dependency",  # залежність файлів/модулів
    "tool",        # результат інструмента
    "constraint",  # технічне обмеження (не можна/не робимо)
    "change",      # історія змін
    "preference",  # уподобання користувача
)

#: Базові ваги типів: обмеження й виправлення корисніші за «сирі» факти.
KIND_WEIGHT = {
    "constraint": 1.30,
    "fix": 1.20,
    "decision": 1.15,
    "fact": 1.10,
    "preference": 1.05,
    "dependency": 1.00,
    "error": 0.95,
    "task": 0.90,
    "change": 0.85,
    "tool": 0.80,
}

#: Зв'язки між спогадами.
RELATIONS = (
    "caused",      # A спричинив B
    "fixed_by",    # A виправлено B
    "depends_on",  # A залежить від B
    "contradicts", # A суперечить B
    "supersedes",  # A замінює B
    "related",     # просто пов'язано
    "part_of",     # A — частина B
)

#: Лексема: слово, число або ідентифікатор. Одинарні символи ТЕЖ беремо:
#: інакше «порт 8080» і «порт 9090» давали б однаковий набір лексем, і
#: різні факти вважались би дублікатом (саме так зникали записи «Запис 1»,
#: «Запис 2» — цифра не потрапляла в лексеми).
_WORD = re.compile(r"[\w\u0400-\u04FF][\w\u0400-\u04FF.\-/#]*", re.UNICODE)

#: Стоп-слова для лексемного порівняння (UK/EN — проєкт двомовний).
STOPWORDS = frozenset("""
і й та в у на з із до по за від як що це цей ця ці про для не ні так але або
the a an and or of to in on for with is are was were be been being it this that
these those as at by from not no yes if then than so but do does did done have has
had can could should would will shall may might must
""".split())


def fingerprint(content: str, kind: str = "") -> str:
    """Відбиток змісту для пошуку дублікатів (не хеш для криптографії).

    Рахуємо з ТИХ САМИХ лексем, що й пошук: інакше «Порт — 8080.» і
    «Порт — 8080!» давали б різні відбитки й осідали двома спогадами.
    """
    words = sorted(set(tokens_of(content)))
    payload = f"{kind}|" + " ".join(words)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def content_hash(content: str) -> str:
    """Точний хеш змісту: ловить буквальні повтори.

    Нормалізуємо пробіли Й кінцеву пунктуацію, щоб «Порт — 8080.» і
    «Порт — 8080!» не ставали двома спогадами з однаковим змістом.
    """
    words = [word.strip(".,;:!?…—–\"'()[]{}<>«»") for word in
             _WORD.findall((content or "").lower())]
    normalised = " ".join(word for word in words if word)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]


def tokens_of(text: str) -> list[str]:
    """Лексеми без стоп-слів (для BM25 і перекриття).

    Кінцева пунктуація зрізається: «8080.» і «8080!» — те саме число, і
    інакше два однакові факти вважались би різними (а «Запис 1» і «Запис 2»
    навпаки — однаковими, бо цифра не потрапляла в лексеми).
    """
    out: list[str] = []
    for word in _WORD.findall(text or ""):
        cleaned = word.strip(".,;:!?…—–\"'()[]{}<>«»")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in STOPWORDS:
            continue
        out.append(lowered)
    return out


def now() -> float:
    return time.time()


@dataclass
class Memory:
    """Один спогад PCMM."""

    id: str = ""
    kind: str = "fact"
    content: str = ""
    summary: str = ""
    source: str = ""
    provenance: str = ""
    confidence: float = 0.6
    created_at: float = 0.0
    updated_at: float = 0.0
    accessed_at: float = 0.0
    hits: int = 0
    task: str = ""
    files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    valid_from: float = 0.0
    valid_to: float = 0.0
    superseded_by: str = ""
    content_hash: str = ""
    fingerprint: str = ""
    embedding: list[float] = field(default_factory=list)
    embed_model: str = ""

    def __post_init__(self) -> None:
        stamp = now()
        if not self.id:
            self.id = f"m-{uuid.uuid4().hex[:16]}"
        if self.kind not in KINDS:
            self.kind = "fact"
        if not self.created_at:
            self.created_at = stamp
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.valid_from:
            self.valid_from = self.created_at
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if not self.summary:
            self.summary = make_summary(self.content)
        if not self.content_hash:
            self.content_hash = content_hash(self.content)
        if not self.fingerprint:
            self.fingerprint = fingerprint(self.content, self.kind)

    @property
    def is_active(self) -> bool:
        """Факт діє зараз (не застарілий і не замінений)."""
        return not self.superseded_by and (not self.valid_to or self.valid_to > now())

    @property
    def age_days(self) -> float:
        return max(0.0, (now() - self.created_at) / 86400.0)

    @property
    def kind_weight(self) -> float:
        return KIND_WEIGHT.get(self.kind, 1.0)

    # ── серіалізація ──────────────────────────────────────────────────────
    def to_row(self) -> tuple:
        return (
            self.id, self.kind, self.content, self.summary, self.source,
            self.provenance, self.confidence, self.created_at, self.updated_at,
            self.accessed_at, self.hits, self.task,
            json.dumps(self.files, ensure_ascii=False),
            json.dumps(self.tags, ensure_ascii=False),
            self.valid_from, self.valid_to, self.superseded_by,
            self.fingerprint, self.content_hash,
            json.dumps(self.embedding) if self.embedding else "",
            self.embed_model, "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "content": self.content,
            "summary": self.summary,
            "source": self.source,
            "provenance": self.provenance,
            "confidence": round(self.confidence, 3),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "accessed_at": self.accessed_at,
            "hits": self.hits,
            "task": self.task,
            "files": list(self.files),
            "tags": list(self.tags),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "superseded_by": self.superseded_by,
            "active": self.is_active,
            "age_days": round(self.age_days, 2),
            "has_embedding": bool(self.embedding),
        }

    @classmethod
    def from_row(cls, row: "Any") -> "Memory":
        def _json(value: Any) -> list:
            if not value:
                return []
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
            return parsed if isinstance(parsed, list) else []

        return cls(
            id=str(row["id"]),
            kind=str(row["kind"]),
            content=str(row["content"]),
            summary=str(row["summary"] or ""),
            source=str(row["source"] or ""),
            provenance=str(row["provenance"] or ""),
            confidence=float(row["confidence"] or 0.5),
            created_at=float(row["created_at"] or 0),
            updated_at=float(row["updated_at"] or 0),
            accessed_at=float(row["accessed_at"] or 0),
            hits=int(row["hits"] or 0),
            task=str(row["task"] or ""),
            files=_json(row["files"]),
            tags=_json(row["tags"]),
            valid_from=float(row["valid_from"] or 0),
            valid_to=float(row["valid_to"] or 0),
            superseded_by=str(row["superseded_by"] or ""),
            fingerprint=str(row["fingerprint"] or ""),
            content_hash=str(row["content_hash"] or ""),
            embedding=_json(row["embedding"]),
            embed_model=str(row["embed_model"] or ""),
        )


def make_summary(content: str, limit: int = 160) -> str:
    """Короткий підпис спогаду (перший рядок або обрізаний текст)."""
    text = " ".join((content or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut + "…"


def overlap(left: str, right: str) -> float:
    """Частка спільних лексем (для виявлення дублікатів без векторів)."""
    first, second = set(tokens_of(left)), set(tokens_of(right))
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def contradiction_score(left: str, right: str) -> float:
    """Наскільки два твердження схожі за темою, але різні за змістом.

    Це евристика, і вона так і подається в інтерфейсі. Вона ловить
    найчастіший випадок у коді: «функція X робить A» проти «функція X
    робить B» — високе перекриття теми (спільні імена) при низькій
    схожості решти тексту.
    """
    left_tokens, right_tokens = set(tokens_of(left)), set(tokens_of(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(shared) / len(union)
    differs = len(left_tokens ^ right_tokens) / len(union)
    if jaccard < 0.25 or differs < 0.35:
        return 0.0
    # Є ідентифікатори (імена, шляхи), навколо яких «крутиться» факт.
    identifiers = {token for token in shared
                   if "_" in token or "." in token or "/" in token}
    bonus = 0.15 if identifiers else 0.0
    return min(1.0, jaccard * 0.6 + differs * 0.4 + bonus)


def merge_contents(items: Iterable[Memory]) -> str:
    """Об'єднати сумісні факти в один текст (без втрати змісту)."""
    seen: list[str] = []
    for item in items:
        text = " ".join(item.content.split())
        if not text:
            continue
        if any(overlap(text, existing) > 0.8 for existing in seen):
            continue
        seen.append(text)
    return " ".join(seen)


__all__ = [
    "KIND_WEIGHT",
    "KINDS",
    "Memory",
    "RELATIONS",
    "STOPWORDS",
    "content_hash",
    "contradiction_score",
    "fingerprint",
    "make_summary",
    "merge_contents",
    "now",
    "overlap",
    "tokens_of",
]
