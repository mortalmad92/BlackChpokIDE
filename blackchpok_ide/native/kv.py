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

    def resync(self) -> int:
        """Привести «дзеркало» до РЕАЛЬНОГО вмісту KV-кешу рушія.

        Навіщо це критично. ``llama_decode`` може повернути ``2``
        (``DECODE_ABORTED``), коли його перервав наш abort-callback. У цьому
        разі llama.cpp ЛИШАЄ в пам'яті вже пораховані ubatch-і (це прямо
        задокументовано в ``llama.h``: «processed ubatches will remain in the
        context's memory»), але наш ``prepare()`` про них не знає — він
        довіряє власній мітці (``state.tokens``).

        Заміряно на справжньому рушії (RTX 3060, Qwen2.5-Coder-14B): після
        скасування посеред prefill мітка показувала **0**, а
        ``llama_memory_seq_pos_max`` — **1535** (тобто в кеші лежало 1536
        токенів). Наступний хід брав ``skip = 0`` і декодував поверх наявних
        даних → ``llama_decode`` повертав ``-1`` («inconsistent sequence
        positions»), виняток летів у ``llm_client`` → ``LLMError`` → агент
        повторював ТУ САМУ зіпсовану генерацію, а контекст лишався
        зіпсованим до перезавантаження моделі. Ззовні це виглядало як
        «модель перестала відповідати / програма зависла».

        Повертає фактичну кількість токенів у кеші.
        """
        with self._lock:
            memory = self._lib.llama_get_memory(self._ctx)
            if not memory:
                # Рушій не дає дескриптора пам'яті — безпечно почати з нуля.
                self.clear()
                return 0
            try:
                position = int(self._lib.llama_memory_seq_pos_max(memory, 0))
            except Exception:                        # noqa: BLE001
                LOG.debug("Позицію KV не прочитано — очищаю", exc_info=True)
                self.clear()
                return 0
            if position < 0:
                # Порожній кеш: мітка теж мусить бути порожньою.
                if self.state.tokens:
                    LOG.info("KV-кеш рушія порожній, мітка мала %d — синхронізую",
                             len(self.state.tokens))
                self.state.tokens = []
                return 0
            length = position + 1
            if self.state.length != length:
                LOG.info("Мітку KV-кешу відновлено з рушія: %d → %d токенів",
                         self.state.length, length)
                # Вміст токенів відновити неможливо, а позиції мусять бути
                # точними. Тому лишаємо порожнє дзеркало: ``prepare()``
                # побачить розбіжність і чисто перерахує промпт.
                self.state.tokens = []
            return length

    def _verify_against_engine(self) -> None:
        """Звірити «дзеркало» з РЕАЛЬНОЮ позицією рушія перед новим промптом.

        Розсинхрон виникає після ``llama_decode`` з кодом ``2``
        (``DECODE_ABORTED``): рушій лишає в пам'яті вже пораховані ubatch-і,
        а наша мітка про них не знає (заміряно: мітка 0, реально 1536).

        Політика безпечна: якщо довжини розійшлись — ПОВНЕ очищення. Це
        коштує одного повторного prefill, але гарантує правильні позиції.
        Часткове «відновлення» неможливе: вміст обрізаних токенів нам
        невідомий, а позиції мусять бути точними.
        """
        memory = self._lib.llama_get_memory(self._ctx)
        if not memory:
            return
        try:
            position = int(self._lib.llama_memory_seq_pos_max(memory, 0))
        except Exception:                            # noqa: BLE001
            LOG.debug("Позицію KV не прочитано", exc_info=True)
            return
        real = 0 if position < 0 else position + 1
        if real == self.state.length:
            return
        LOG.info("KV-кеш розійшовся з міткою (мітка %d, рушій %d) — "
                 "очищаю перед новим промптом", self.state.length, real)
        self._lib.llama_memory_clear(memory, True)
        self.state.tokens = []

    def prepare(self, tokens: list[int]) -> int:
        """Підготувати кеш під новий промпт; повернути індекс початку декодування.

        Повернене значення ``skip`` означає: перші ``skip`` токенів уже
        лежать у кеші, декодувати треба з ``tokens[skip:]``. Значення
        завжди узгоджене з РЕАЛЬНИМ вмістом кешу після обрізання.
        """
        with self._lock:
            # ── Спершу звірка з рушієм ────────────────────────────────────
            # Мітка могла розійтись із реальним кешем (скасування посеред
            # decode лишає пораховані ubatch-і). Довіряти мітці наосліп
            # означало б декодувати з неправильної позиції — рушій відповідає
            # ``-1`` і контекст заклинює до перезавантаження моделі.
            self._verify_against_engine()
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
