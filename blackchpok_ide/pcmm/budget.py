"""Бюджет контексту: реальні токени моделі, а не «символи на токен».

Завдання модуля — зібрати з кандидатів (спогади, файли, результати
інструментів) такий блок, який:

1. влізе у вікно моделі з запасом на відповідь;
2. не містить дублів;
3. зберігає КРИТИЧНІ обмеження (їх не можна викидати ніколи);
4. має максимальну цінність на токен;
5. може пояснити, чому кожен фрагмент увійшов.

Підрахунок токенів — через :class:`~blackchpok_ide.native.tokenizer.Tokenizer`
завантаженої моделі. Якщо токенайзера немає, модуль ЧЕСНО повертає
``exact=False`` у звіті, а не вдає точність.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

LOG = logging.getLogger("blackchpok.pcmm.budget")

#: Скільки вікна лишаємо під відповідь моделі (частка).
RESPONSE_SHARE = 0.30
#: Мінімальний запас під відповідь (токенів).
MIN_RESPONSE_TOKENS = 256
#: Частка бюджету, яку дозволено віддати «критичним» фрагментам.
CRITICAL_SHARE = 0.5


@dataclass
class ContextPiece:
    """Один фрагмент, який претендує на місце в контексті."""

    text: str
    label: str = ""
    score: float = 0.0
    kind: str = "memory"
    critical: bool = False
    tokens: int = 0
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "score": round(self.score, 4),
            "tokens": self.tokens,
            "critical": self.critical,
            "reason": self.reason,
        }


@dataclass
class BudgetReport:
    """Що саме увійшло в контекст і скільки це коштувало."""

    pieces: list[ContextPiece] = field(default_factory=list)
    dropped: list[ContextPiece] = field(default_factory=list)
    budget: int = 0
    used: int = 0
    exact: bool = True
    note: str = ""

    @property
    def text(self) -> str:
        return "\n\n".join(piece.text for piece in self.pieces if piece.text)

    @property
    def free(self) -> int:
        return max(0, self.budget - self.used)

    def explain(self) -> list[str]:
        """Пояснення включення/виключення — для інтерфейсу й журналу."""
        lines = []
        for piece in self.pieces:
            lines.append(f"+ [{piece.label}] {piece.tokens} ток · {piece.reason}")
        for piece in self.dropped:
            lines.append(f"- [{piece.label}] {piece.tokens} ток · не влізло")
        return lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "used": self.used,
            "free": self.free,
            "exact": self.exact,
            "note": self.note,
            "included": [piece.to_dict() for piece in self.pieces],
            "dropped": [piece.to_dict() for piece in self.dropped],
        }


class BudgetGovernor:
    """Збирає контекст під бюджет вікна моделі."""

    def __init__(self, counter: Callable[[str], int] | None = None, *,
                 exact: bool = True) -> None:
        self._counter = counter
        self.exact = exact

    @classmethod
    def for_tokenizer(cls, tokenizer: Any) -> "BudgetGovernor":
        """Губернатор на реальному токенайзері моделі."""
        return cls(counter=lambda text: tokenizer.count(text, add_special=False),
                   exact=True)

    @classmethod
    def heuristic(cls) -> "BudgetGovernor":
        """Запасний варіант: оцінка. Позначається як НЕточна."""
        def counter(text: str) -> int:
            cyrillic = sum(1 for char in text if "\u0400" <= char <= "\u04FF")
            share = cyrillic / len(text) if text else 0.0
            per_token = 1.7 if share > 0.5 else 3.6
            return max(1, int(len(text) / per_token))

        return cls(counter=counter, exact=False)

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._counter is None:
            return BudgetGovernor.heuristic().count(text)
        return int(self._counter(text))

    # ── основний відбір ───────────────────────────────────────────────────
    def fit(self, pieces: Sequence[ContextPiece], *, window: int,
            reserve_tokens: int = 0, max_share: float = 0.7) -> BudgetReport:
        """Обрати фрагменти, що влізають у ``window``.

        Порядок: спершу критичні (обмеження, помилки), далі — за
        співвідношенням «цінність / токен». Дублі відкидаються.
        """
        window = max(64, int(window))
        reserve = max(MIN_RESPONSE_TOKENS, reserve_tokens)
        budget = max(0, int(window * max_share) - reserve)
        report = BudgetReport(budget=budget, exact=self.exact)
        if budget <= 0:
            report.note = "Бюджету немає: вікно надто мале."
            report.dropped = list(pieces)
            return report

        seen: set[str] = set()
        prepared: list[ContextPiece] = []
        for piece in pieces:
            text = (piece.text or "").strip()
            if not text:
                continue
            normalised = " ".join(text.split()).lower()
            if normalised in seen:
                continue
            seen.add(normalised)
            piece.tokens = piece.tokens or self.count(text)
            prepared.append(piece)

        prepared.sort(key=lambda item: (not item.critical, -item.score))
        critical_limit = int(budget * CRITICAL_SHARE)
        used = 0
        for piece in prepared:
            if piece.critical and used + piece.tokens <= max(critical_limit, budget):
                report.pieces.append(piece)
                used += piece.tokens
        # Решта — за співвідношенням цінність/токен.
        rest = [piece for piece in prepared if piece not in report.pieces]
        rest.sort(key=lambda item: (item.score / max(1, item.tokens)), reverse=True)
        for piece in rest:
            if used + piece.tokens <= budget:
                report.pieces.append(piece)
                used += piece.tokens
            else:
                report.dropped.append(piece)
        report.used = used
        if not report.pieces and prepared:
            first = min(prepared, key=lambda item: item.tokens)
            if first.tokens <= budget:
                report.pieces.append(first)
                report.used = first.tokens
        return report

    # ── готові блоки ──────────────────────────────────────────────────────
    @staticmethod
    def memory_piece(memory: Any, *, score: float, reason: str) -> ContextPiece:
        """Фрагмент контексту зі спогаду PCMM."""
        from .models import Memory

        if isinstance(memory, Memory):
            label = f"{memory.kind}:{memory.id[-6:]}"
            source = f" ({memory.provenance or memory.source})" if (
                memory.provenance or memory.source) else ""
            text = f"[{memory.kind}]{source} {memory.content}"
            critical = memory.kind in {"constraint", "preference"}
            return ContextPiece(text=text, label=label, score=score,
                                kind="memory", critical=critical, reason=reason,
                                payload=memory.to_dict())
        raise TypeError("Очікується Memory")

    @staticmethod
    def text_piece(text: str, *, label: str, score: float = 0.5,
                   kind: str = "text", critical: bool = False,
                   reason: str = "") -> ContextPiece:
        return ContextPiece(text=text, label=label, score=score, kind=kind,
                            critical=critical, reason=reason)


def trim_to_tokens(text: str, governor: BudgetGovernor, limit: int) -> str:
    """Обрізати текст до ``limit`` токенів, не рвучи посеред слова."""
    if limit <= 0:
        return ""
    if governor.count(text) <= limit:
        return text
    # Двійковий пошук по довжині: символи не лінійні щодо токенів.
    low, high = 0, len(text)
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = text[:middle]
        if governor.count(candidate) <= limit:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    if not best:
        return ""
    cut = best.rstrip()
    # Дотягуємо до межі слова/рядка, щоб не обривати ім'я навпіл.
    for separator in ("\n", " "):
        position = cut.rfind(separator)
        if position > len(cut) * 0.7:
            return cut[:position] + "…"
    return cut + "…"


__all__ = [
    "BudgetGovernor",
    "BudgetReport",
    "CRITICAL_SHARE",
    "ContextPiece",
    "MIN_RESPONSE_TOKENS",
    "RESPONSE_SHARE",
    "trim_to_tokens",
]
