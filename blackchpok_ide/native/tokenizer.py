"""Реальний tokenizer моделі — замість оцінки «символів на токен».

Ідея: підрахунок токенів мусить іти через ту саму модель, яка потім
генерує. Інакше бюджет контексту бреше: для української кирилиці
евристика «3.5 символа на токен» дає похибку до 2 разів, і агент або
обрізає історію завчасно, або отримує «context overflow» від рушія.

Модуль тонкий: тримає ``llama_vocab`` і робить переклад текст↔токени.
Кеш на 4096 записів прибирає повторну токенізацію того самого системного
промпту на кожному кроці агента.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import threading
from dataclasses import dataclass

from ._abi import llama_token
from ._bindings import LlamaLibrary

LOG = logging.getLogger("blackchpok.native.tokenizer")

#: Скільки результатів токенізації пам'ятаємо.
CACHE_LIMIT = 4096
#: Початковий розмір буфера токенів.
_INITIAL_TOKENS = 1024


class TokenizerError(RuntimeError):
    """Токенізація неможлива (немає словника або помилка рушія)."""


@dataclass(frozen=True)
class Token:
    """Один токен: id і його текстове подання."""

    id: int
    text: str


class StreamingDecoder:
    """Інкрементальне декодування токенів у текст.

    Один символ кирилиці може складатись із двох токенів (а емодзі — і з
    чотирьох). Якщо декодувати кожен токен окремо, на межі з'являється
    ``��``. Тут незавершена послідовність байтів ПРИТРИМУЄТЬСЯ до наступного
    виклику — так само, як це робить ``codecs.getincrementaldecoder``.
    """

    def __init__(self, tokenizer: "Tokenizer", *, skip_special: bool = True) -> None:
        self._tokenizer = tokenizer
        self._skip_special = skip_special
        self._pending = bytearray()

    def push(self, token: int) -> str:
        """Додати токен; повернути готовий текст (можливо, порожній)."""
        self._pending.extend(
            self._tokenizer._token_bytes(int(token),          # noqa: SLF001
                                         skip_special=self._skip_special))
        return self._drain(final=False)

    def flush(self) -> str:
        """Віддати залишок (кінець генерації)."""
        text = self._drain(final=True)
        self._pending.clear()
        return text

    def _drain(self, *, final: bool) -> str:
        if not self._pending:
            return ""
        raw = bytes(self._pending)
        if final:
            self._pending.clear()
            return raw.decode("utf-8", "replace")
        # Знаходимо найдовший коректний префікс: ріжемо лише незавершений
        # хвіст, а не додаємо «заміну символу».
        for trim in range(0, min(4, len(raw)) + 1):
            candidate = raw[: len(raw) - trim] if trim else raw
            try:
                text = candidate.decode("utf-8")
            except UnicodeDecodeError:
                continue
            del self._pending[: len(candidate)]
            return text
        return ""


class Tokenizer:
    """Обгортка над ``llama_vocab`` конкретної моделі."""

    def __init__(self, lib: LlamaLibrary, vocab: int) -> None:
        if not vocab:
            raise TokenizerError("Немає словника моделі.")
        self._lib = lib
        self._vocab = vocab
        self._n_tokens = int(lib.llama_vocab_n_tokens(vocab))
        self._lock = threading.RLock()
        self._encode_cache: dict[tuple[str, bool, bool], tuple[int, ...]] = {}
        self._decode_cache: dict[int, str] = {}
        self._count_cache: dict[str, int] = {}
        self._stats = {"encoded_calls": 0, "encoded_hits": 0, "tokens_counted": 0}

    # ── властивості ────────────────────────────────────────────────────────
    @property
    def size(self) -> int:
        """Розмір словника."""
        return self._n_tokens

    @property
    def bos(self) -> int:
        return int(self._lib.llama_vocab_bos(self._vocab))

    @property
    def eos(self) -> int:
        return int(self._lib.llama_vocab_eos(self._vocab))

    @property
    def adds_bos(self) -> bool:
        return bool(self._lib.llama_vocab_get_add_bos(self._vocab))

    def stats(self) -> dict[str, int]:
        with self._lock:
            data = dict(self._stats)
        data["cache_entries"] = len(self._encode_cache)
        return data

    # ── токенізація ────────────────────────────────────────────────────────
    def encode(self, text: str, *, add_special: bool | None = None,
               parse_special: bool = True) -> list[int]:
        """Перетворити текст у токени.

        ``add_special=None`` означає «як налаштована модель» (типово BOS
        додається для першого фрагмента промпту).
        """
        if not text:
            return []
        special = self.adds_bos if add_special is None else bool(add_special)
        key = (text, special, parse_special)
        with self._lock:
            self._stats["encoded_calls"] += 1
            cached = self._encode_cache.get(key)
            if cached is not None:
                self._stats["encoded_hits"] += 1
                return list(cached)
        tokens = self._encode_uncached(text, add_special=special,
                                       parse_special=parse_special)
        with self._lock:
            if len(self._encode_cache) >= CACHE_LIMIT:
                # Простий, але передбачуваний вихід: чистимо половину.
                for stale in list(self._encode_cache)[: CACHE_LIMIT // 2]:
                    self._encode_cache.pop(stale, None)
            self._encode_cache[key] = tuple(tokens)
        return tokens

    def _encode_uncached(self, text: str, *, add_special: bool,
                         parse_special: bool) -> list[int]:
        raw = text.encode("utf-8")
        capacity = max(_INITIAL_TOKENS, len(raw) // 2 + 16)
        with self._lock:
            for _ in range(6):
                buffer = (llama_token * capacity)()
                produced = int(self._lib.llama_tokenize(
                    self._vocab, raw, len(raw), buffer, capacity,
                    add_special, parse_special))
                if produced >= 0:
                    return [int(buffer[i]) for i in range(produced)]
                # Від'ємне значення — скільки токенів потрібно насправді.
                need = -produced
                if need <= capacity:
                    raise TokenizerError(f"Токенізація не вдалась (потрібно {need}).")
                capacity = need + 8
        raise TokenizerError("Не вдалось виділити буфер токенів.")

    def decode(self, tokens: list[int], *, skip_special: bool = True) -> str:
        """Перетворити токени назад у текст.

        УВАГА про UTF-8: один символ кирилиці (``є``, ``ї``, ``ґ``) часто
        розкладається на ДВА токени, і кожен із них окремо НЕ є валідним
        UTF-8. Якщо декодувати їх поштучно з ``errors="replace"``, на місці
        літери з'являється ``��`` — саме це псувало відповіді агента.

        Тому збираємо БАЙТИ всіх токенів і декодуємо один раз: тоді
        послідовність байтів склеюється правильно.
        """
        if not tokens:
            return ""
        raw = bytearray()
        for token in tokens:
            raw.extend(self._token_bytes(int(token), skip_special=skip_special))
        if not raw:
            return ""
        return bytes(raw).decode("utf-8", "replace")

    def _token_bytes(self, token: int, *, skip_special: bool) -> bytes:
        """Сирий UTF-8 фрагмент одного токена (без декодування)."""
        buffer = ctypes.create_string_buffer(256)
        with self._lock:
            length = int(self._lib.llama_token_to_piece(
                self._vocab, token, buffer, 256, 0, skip_special))
            if length < 0:
                buffer = ctypes.create_string_buffer(-length + 8)
                length = int(self._lib.llama_token_to_piece(
                    self._vocab, token, buffer, len(buffer), 0, skip_special))
        if length <= 0:
            return b""
        return buffer.raw[:length]

    def token_text(self, token: int, *, skip_special: bool = True) -> str:
        """Текст одного токена (з кешем)."""
        cached = self._decode_cache.get(token)
        if cached is not None:
            return cached
        piece = self._piece_uncached(token, skip_special=skip_special)
        with self._lock:
            if len(self._decode_cache) < CACHE_LIMIT * 4:
                self._decode_cache[token] = piece
        return piece

    def _piece_uncached(self, token: int, *, skip_special: bool) -> str:
        buffer = ctypes.create_string_buffer(256)
        with self._lock:
            length = int(self._lib.llama_token_to_piece(
                self._vocab, token, buffer, 256, 0, skip_special))
            if length < 0:
                buffer = ctypes.create_string_buffer(-length + 8)
                length = int(self._lib.llama_token_to_piece(
                    self._vocab, token, buffer, len(buffer), 0, skip_special))
        if length <= 0:
            return ""
        return buffer.raw[:length].decode("utf-8", "replace")

    # ── підрахунок ─────────────────────────────────────────────────────────
    def count(self, text: str, *, add_special: bool = False) -> int:
        """Скільки токенів у тексті (для бюджету контексту)."""
        if not text:
            return 0
        with self._lock:
            cached = self._count_cache.get(text)
        if cached is not None:
            return cached
        value = len(self.encode(text, add_special=add_special))
        with self._lock:
            self._stats["tokens_counted"] += value
            if len(self._count_cache) >= CACHE_LIMIT:
                for stale in list(self._count_cache)[: CACHE_LIMIT // 2]:
                    self._count_cache.pop(stale, None)
            self._count_cache[text] = value
        return value

    def count_messages(self, messages: list[dict], *,
                       formatter: "object | None" = None) -> int:
        """Токени в списку повідомлень чату.

        Якщо переданий форматер (див. :mod:`.chatfmt`), рахуємо РЕАЛЬНИЙ
        промпт після застосування шаблону — разом із службовими токенами
        ролей, які модель справді бачить.
        """
        if formatter is not None:
            text = formatter.render(messages, add_assistant=False)
            return self.count(text, add_special=False)
        total = 0
        for message in messages:
            total += self.count(str(message.get("content") or ""), add_special=False)
            total += 4                     # службові токени ролі й розділювачі
        return total

    def is_eog(self, token: int) -> bool:
        """Чи токен завершує генерацію (EOS/EOT)."""
        return bool(self._lib.llama_vocab_is_eog(self._vocab, token))

    def tokens_and_pieces(self, text: str) -> list[Token]:
        """Розбір тексту на токени з текстом — для діагностики й навчання."""
        return [Token(token=token, text=self.token_text(token, skip_special=False))
                for token in self.encode(text)]

    def clear_cache(self) -> None:
        with self._lock:
            self._encode_cache.clear()
            self._decode_cache.clear()
            self._count_cache.clear()


@functools.lru_cache(maxsize=8)
def estimate_ratio(text: str) -> float:
    """Співвідношення «токенів на символ» для швидкої оцінки без рушія.

    Використовується ЛИШЕ там, де токенайзера ще немає (наприклад, у
    підказках до завантаження). Для бюджету контексту завжди береться
    :meth:`Tokenizer.count`.
    """
    cyrillic = sum(1 for char in text if "\u0400" <= char <= "\u04FF")
    if not text:
        return 0.0
    share = cyrillic / len(text)
    return 0.45 + 0.35 * share


__all__ = [
    "CACHE_LIMIT",
    "StreamingDecoder",
    "Token",
    "Tokenizer",
    "TokenizerError",
    "estimate_ratio",
]
