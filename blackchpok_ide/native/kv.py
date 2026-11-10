"""Керування KV-кешем: переиспользование префікса, скидання, статистика.

Навіщо це окремо: у діалозі кожен новий запит містить увесь попередній
контекст. Якщо декодувати його щоразу з нуля, агент платить секундами на
кожен крок. llama.cpp уміє продовжити обчислення з наявного кешу — треба
лише сказати йому, скільки токенів уже є і з якої позиції продовжувати.

Модуль зберігає «дзеркало» того, що зараз лежить у кеші:

* ``tokens`` — послідовність токенів у кеші;
* після нового промпту шукає найдовший спільний префікс;
* якщо він збігається — ріже кеш до нього й декодує лише хвіст.

Це класичний prefix caching; нічого екзотичного, зате дає помітне
прискорення на довгих діалогах, бо неалізована частина промпту
(системний блок + історія) не перераховується.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from ._bindings import LlamaLibrary

LOG = logging.getLogger("blackchpok.native.kv")


@dataclass
class CacheState:
    """Що зараз у KV-кеші."""

    tokens: list[int] = field(default_factory=list)
    #: Скільки запитів скористались наявним кешем.
    reuse_hits: int = 0
    #: Скільки токенів перераховано замість повторного використання.
    recomputed: int = 0
    #: Скільки токенів зекономлено завдяки переиспользованию.
    saved: int = 0

    def reset(self) -> None:
        self.tokens = []

    @property
    def length(self) -> int:
        return len(self.tokens)


class CacheManager:
    """Дзеркало KV-кешу конкретного контексту llama.cpp.

    Один екземпляр на :class:`~.engine.EngineContext`. Усі операції з
    рушієм серіалізовані зовнішнім ``threading.Lock`` — сам llama.cpp не
    потокобезпечний для одного контексту.
    """

    def __init__(self, lib: LlamaLibrary, ctx: int, *, capacity: int = 0) -> None:
        self._lib = lib
        self._ctx = ctx
        self._lock = threading.RLock()
        self.state = CacheState()
        self.capacity = int(capacity or 0)

    # ── стан ──────────────────────────────────────────────────────────────
    @property
    def length(self) -> int:
        return self.state.length

    def full(self) -> bool:
        """Чи кеш заповнений настільки, що новий промпт не влізе."""
        if not self.capacity:
            return False
        return self.state.length >= self.capacity

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "cached_tokens": self.state.length,
                "capacity": self.capacity,
                "reuse_hits": self.state.reuse_hits,
                "saved_tokens": self.state.saved,
                "recomputed_tokens": self.state.recomputed,
            }

    # ── операції ──────────────────────────────────────────────────────────
    def clear(self) -> None:
        """Повністю очистити кеш (нова розмова, зміна моделі)."""
        with self._lock:
            memory = self._lib.llama_get_memory(self._ctx)
            if memory:
                self._lib.llama_memory_clear(memory, True)
            self.state.reset()

    def truncate(self, keep: int) -> int:
        """Лишити в кеші перші ``keep`` токенів; повернути фактичну довжину.

        Повернене значення — ДЖЕРЕЛО ІСТИНИ для виклику: якщо рушій не
        зміг відрізати хвіст і кеш довелось очистити, повертається 0, і
        промпт декодується заново. Раніше тут повертався «бажаний»
        ``keep`` навіть після повного очищення — і генерація йшла з
        порожнього кешу, даючи безглузді токени.
        """
        with self._lock:
            keep = max(0, min(int(keep), self.state.length))
            if keep == self.state.length:
                return keep
            if keep == 0:
                self.clear()
                return 0
            memory = self._lib.llama_get_memory(self._ctx)
            if not memory:
                self.state.tokens = self.state.tokens[:keep]
                return keep
            removed = bool(self._lib.llama_memory_seq_rm(memory, 0, keep, -1))
            if not removed:
                # Рушій не зміг відрізати хвіст — чистимо повністю, щоб не
                # отримати «брудний» контекст і хибні відповіді.
                LOG.debug("llama_memory_seq_rm відмовив — повне очищення")
                self._lib.llama_memory_clear(memory, True)
                self.state.tokens = []
                return 0
            self.state.tokens = self.state.tokens[:keep]
            return keep

    def prepare(self, tokens: list[int]) -> int:
        """Підготувати кеш під новий промпт; повернути індекс початку декодування.

        Повернене значення ``skip`` означає: перші ``skip`` токенів уже
        лежать у кеші, декодувати треба з ``tokens[skip:]``. Значення
        завжди узгоджене з РЕАЛЬНИМ вмістом кешу після обрізання.
        """
        with self._lock:
            if not tokens:
                self.clear()
                return 0
            if self.capacity and len(tokens) > self.capacity:
                # Промпт довший за вікно: лишаємо хвіст, який точно влізе.
                LOG.warning("Промпт (%d токенів) довший за контекст (%d) — обрізаю",
                            len(tokens), self.capacity)
                tokens = tokens[-self.capacity:]
            common = self._common_prefix(self.state.tokens, tokens)
            actual = self.state.length
            if common < actual:
                actual = self.truncate(common)
            if actual:
                self.state.reuse_hits += 1
                self.state.saved += actual
            self.state.recomputed += max(0, len(tokens) - actual)
            return actual

    def committed(self, tokens: list[int]) -> None:
        """Зафіксувати, що токени справді декодовані й лежать у кеші."""
        with self._lock:
            self.state.tokens.extend(tokens)

    def set_tokens(self, tokens: list[int]) -> None:
        """Задати вміст кешу явно (після повного перерахунку)."""
        with self._lock:
            self.state.tokens = list(tokens)

    @staticmethod
    def _common_prefix(left: list[int], right: list[int]) -> int:
        limit = min(len(left), len(right))
        index = 0
        while index < limit and left[index] == right[index]:
            index += 1
        return index

    # ── діагностика ───────────────────────────────────────────────────────
    def describe(self) -> str:
        data = self.stats()
        used = data["cached_tokens"]
        total = data["capacity"] or used
        percent = (used / total * 100) if total else 0.0
        return (f"KV: {used}/{total} токенів ({percent:.0f}%) · "
                f"переиспользовано {data['saved_tokens']}")


def estimate_kv_bytes(layers: int, kv_heads: int, head_dim: int,
                      ctx: int, bytes_per_element: float = 2.0) -> int:
    """Оцінити обсяг KV-кешу в байтах (для показу й планування)."""
    if min(layers, kv_heads, head_dim, ctx) <= 0:
        return 0
    return int(layers * kv_heads * head_dim * 2 * ctx * bytes_per_element)


__all__ = ["CacheManager", "CacheState", "estimate_kv_bytes"]
