"""Параметри семплінгу й побудова ланцюжка семплерів llama.cpp.

Чому окремий модуль: параметри генерації — це те, що користувач міняє
найчастіше, і саме тут найлегше зробити «фільтр, що нічого не фільтрує».
Тому всі значення валідуються, а порядок семплерів фіксований і пояснений.

Порядок (як у llama.cpp і як радять автори квантизованих моделей):

    penalties → top_k → top_p → min_p → temp → dist

``penalties`` стоять першими, бо штраф має застосовуватись до сирих
логітів; ``temp`` — останнім перед випадковим вибором, інакше вона
масштабує вже відфільтрований розподіл і спотворює top_p.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from ._abi import FLASH_ATTN
from ._bindings import LlamaLibrary

LOG = logging.getLogger("blackchpok.native.sampling")

#: Межі, за які користувач не може вийти (щоб не зламати генерацію).
LIMITS = {
    "temperature": (0.0, 5.0),
    "top_p": (0.0, 1.0),
    "top_k": (0, 1_000_000),
    "min_p": (0.0, 1.0),
    "repeat_penalty": (0.0, 4.0),
    "repeat_last_n": (-1, 100_000),
    "presence_penalty": (-2.0, 2.0),
    "frequency_penalty": (-2.0, 2.0),
    "max_tokens": (1, 1_000_000),
}

DEFAULT_STOP = ("<|im_end|>", "<|endoftext|>", "<|eot_id|>", "</s>")


@dataclass
class SamplingParams:
    """Параметри генерації одного запиту."""

    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    min_p: float = 0.05
    repeat_penalty: float = 1.1
    repeat_last_n: int = 64
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    max_tokens: int = 1024
    seed: int = -1
    stop: tuple[str, ...] = field(default_factory=tuple)
    grammar: str = ""

    def normalised(self) -> "SamplingParams":
        """Привести значення до допустимих меж (не кидаючи винятку)."""
        def clamp(value: float, key: str) -> float:
            low, high = LIMITS[key]
            return max(low, min(high, float(value)))

        self.temperature = clamp(self.temperature, "temperature")
        self.top_p = clamp(self.top_p, "top_p")
        self.min_p = clamp(self.min_p, "min_p")
        self.top_k = int(clamp(self.top_k, "top_k"))
        self.repeat_penalty = clamp(self.repeat_penalty, "repeat_penalty")
        self.repeat_last_n = int(clamp(self.repeat_last_n, "repeat_last_n"))
        self.presence_penalty = clamp(self.presence_penalty, "presence_penalty")
        self.frequency_penalty = clamp(self.frequency_penalty, "frequency_penalty")
        self.max_tokens = int(clamp(self.max_tokens, "max_tokens"))
        if self.seed < 0:
            self.seed = random.randint(0, 2 ** 31 - 1)
        self.stop = tuple(str(item) for item in self.stop if str(item))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplingParams":
        """Створити зі словника, ігноруючи невідомі ключі."""
        known = {field_name for field_name in cls.__dataclass_fields__}
        payload = {key: value for key, value in (data or {}).items() if key in known}
        if "stop" in payload and isinstance(payload["stop"], str):
            payload["stop"] = (payload["stop"],)
        return cls(**payload).normalised()

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "repeat_penalty": self.repeat_penalty,
            "repeat_last_n": self.repeat_last_n,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "stop": list(self.stop),
            "grammar": self.grammar,
        }

    def describe(self) -> str:
        """Короткий підпис для інтерфейсу."""
        mode = "greedy" if self.temperature <= 0 else f"T={self.temperature:g}"
        return f"{mode} · top_p {self.top_p:g} · top_k {self.top_k}"


class GrammarUnsupported(RuntimeError):
    """Граматика несумісна з цією збіркою llama.cpp.

    Заміряно на build b12129: ``root ::= [A-C]+`` працює, а
    ``root ::= "AAA" | "BBB"`` валить процес C++-винятком
    (``OSError 0xe06d7363``) під час ``llama_sampler_sample``, хоч сам
    ``llama_sampler_init_grammar`` повертає валідний вказівник. Тобто
    перевірити граматику «на березі» неможливо — тільки під час семплінгу.
    """


class SamplerChain:
    """Ланцюжок семплерів llama.cpp із коректним звільненням пам'яті."""

    def __init__(self, lib: LlamaLibrary, params: SamplingParams, *,
                 n_vocab: int = 0, vocab: int = 0) -> None:
        self._lib = lib
        self.params = params.normalised()
        # Словник потрібен ДО побудови ланцюжка: граматика
        # (``llama_sampler_init_grammar``) бере його першим аргументом.
        # Раніше ``attach_vocab`` викликався після ``_build``, тому
        # граматика отримувала 0 і не працювала зовсім.
        self._vocab = int(vocab)
        self._n_vocab = int(n_vocab)
        self._grammar = bool((params.grammar or "").strip())
        self._chain = 0
        self._build()

    def _build(self) -> None:
        lib = self._lib
        settings = lib.llama_sampler_chain_default_params()
        chain = lib.llama_sampler_chain_init(settings)
        if not chain:
            raise RuntimeError("Не вдалось створити ланцюжок семплерів.")
        self._chain = chain
        params = self.params

        # Граматика мусить стояти ПЕРЕД вибором токена в будь-якому режимі —
        # зокрема при температурі 0. Раніше тут був ранній ``return`` для
        # greedy, і граматика просто не додавалась: модель відповідала
        # вільним текстом попри обмеження.
        grammar_sampler = self._grammar_sampler()
        if params.temperature <= 0.0:
            # Температура 0 = детермінований вибір найімовірнішого токена.
            if grammar_sampler:
                lib.llama_sampler_chain_add(chain, grammar_sampler)
            lib.llama_sampler_chain_add(chain, lib.llama_sampler_init_greedy())
            return

        if params.repeat_penalty != 1.0 or params.presence_penalty or params.frequency_penalty:
            # Сигнатура llama_sampler_init_penalties у цій версії рушія
            # починається з n_vocab. Без нього перший аргумент з'їдався як
            # розмір словника, і 64 перетворювалось на «штрафувати 64 останні
            # токени зі словником 64» — вихід ставав безглуздим.
            lib.llama_sampler_chain_add(
                chain,
                lib.llama_sampler_init_penalties(
                    self._n_vocab,
                    params.repeat_last_n,
                    params.repeat_penalty,
                    params.frequency_penalty,
                    params.presence_penalty,
                ),
            )
        if params.top_k > 0:
            lib.llama_sampler_chain_add(chain, lib.llama_sampler_init_top_k(params.top_k))
        if params.top_p < 1.0:
            lib.llama_sampler_chain_add(
                chain, lib.llama_sampler_init_top_p(params.top_p, 1))
        if params.min_p > 0.0:
            lib.llama_sampler_chain_add(
                chain, lib.llama_sampler_init_min_p(params.min_p, 1))
        if grammar_sampler:
            lib.llama_sampler_chain_add(chain, grammar_sampler)
        lib.llama_sampler_chain_add(chain, lib.llama_sampler_init_temp(params.temperature))
        lib.llama_sampler_chain_add(chain, lib.llama_sampler_init_dist(params.seed))

    def _grammar_sampler(self) -> int:
        """Створити семплер граматики, якщо її задано і є словник.

        ``llama_sampler_init_grammar`` першим аргументом бере ``llama_vocab``.
        Нуль (немає словника) або побита граматика дають ``None`` — тоді
        ланцюжок будується без обмеження, але й не видає себе за робочий.
        """
        grammar = (self.params.grammar or "").strip()
        if not grammar or not self._vocab:
            if grammar and not self._vocab:
                LOG.warning("Граматику задано, але словник не передано — "
                            "обмеження НЕ діятиме")
            return 0
        try:
            handle = self._lib.llama_sampler_init_grammar(
                self._vocab, grammar.encode("utf-8"), b"root")
        except Exception:                            # noqa: BLE001
            LOG.warning("Граматику не створено", exc_info=True)
            return 0
        if not handle:
            LOG.warning("Граматика синтаксично некоректна — ігнорую")
        return int(handle or 0)

    def attach_vocab(self, vocab: int, *, n_vocab: int = 0) -> None:
        """Запам'ятати словник (для діагностики й повторного використання)."""
        self._vocab = int(vocab)
        if n_vocab:
            self._n_vocab = int(n_vocab)

    @property
    def handle(self) -> int:
        return self._chain

    @property
    def size(self) -> int:
        return int(self._lib.llama_sampler_chain_n(self._chain)) if self._chain else 0

    def sample(self, ctx: int, index: int = -1) -> int:
        """Обрати наступний токен із логітів контексту.

        Якщо в ланцюжку є граматика й ця збірка рушія на ній падає
        (C++-виняток усередині ``llama_sampler_sample``), кидаємо
        :class:`GrammarUnsupported` — виклик має зняти семплер граматики й
        продовжити без обмеження, а не втратити весь процес.
        """
        if self._grammar:
            try:
                return int(self._lib.llama_sampler_sample(self._chain, ctx, index))
            except OSError as exc:
                raise GrammarUnsupported(
                    "Ця збірка llama.cpp не обробляє таку граматику "
                    f"(виняток рушія: {exc}). Спробуй простішу форму, "
                    "наприклад класи символів [A-Z ].") from exc
        return int(self._lib.llama_sampler_sample(self._chain, ctx, index))

    def accept(self, token: int) -> None:
        """Повідомити семплери, що токен справді пішов у контекст.

        Той самий захист, що й у :meth:`sample`: на «літеральних» граматиках
        ця збірка llama.cpp кидає C++-виняток саме тут.
        """
        if self._grammar:
            try:
                self._lib.llama_sampler_accept(self._chain, token)
                return
            except OSError as exc:
                raise GrammarUnsupported(
                    "Ця збірка llama.cpp не обробляє таку граматику "
                    f"(виняток рушія: {exc}). Спробуй класи символів [A-Z ]."
                ) from exc
        self._lib.llama_sampler_accept(self._chain, token)

    def reset(self) -> None:
        self._lib.llama_sampler_reset(self._chain)

    def free(self) -> None:
        if self._chain:
            self._lib.llama_sampler_free(self._chain)
            self._chain = 0

    def __enter__(self) -> "SamplerChain":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.free()

    def __del__(self) -> None:                       # pragma: no cover - страховка
        try:
            self.free()
        except Exception:                            # noqa: BLE001
            pass


def flash_attn_value(mode: str) -> int:
    """Перевести ``on/off/auto`` у значення ``llama_flash_attn_type``."""
    return FLASH_ATTN.get((mode or "auto").strip().lower(), FLASH_ATTN["auto"])


class StopMatcher:
    """Детектор стоп-послідовностей у потоці тексту.

    Потрібен, щоб не віддавати користувачу службові токени на кшталт
    ``<|im_end|>`` і водночас не «з'їсти» легітимний текст, який лише
    починається так само. Тому тримаємо хвіст довжиною в найдовший стоп.
    """

    def __init__(self, stops: tuple[str, ...] | list[str] | None = None) -> None:
        self.stops = tuple(item for item in (stops or ()) if item)
        self._buffer = ""
        self._max = max((len(item) for item in self.stops), default=0)
        self.matched = ""

    def feed(self, text: str) -> str:
        """Додати текст; повернути безпечну частину (без хвоста-кандидата)."""
        if not self.stops:
            return text
        self._buffer += text
        for stop in self.stops:
            position = self._buffer.find(stop)
            if position >= 0:
                safe = self._buffer[:position]
                self.matched = stop
                self._buffer = ""
                return safe
        if self._max <= 1:
            safe, self._buffer = self._buffer, ""
            return safe
        # Хвіст, який ще може стати початком стопа, лишаємо в буфері.
        keep = 0
        for size in range(min(self._max - 1, len(self._buffer)), 0, -1):
            tail = self._buffer[-size:]
            if any(stop.startswith(tail) for stop in self.stops):
                keep = size
                break
        if keep:
            safe = self._buffer[:-keep]
            self._buffer = self._buffer[-keep:]
            return safe
        safe, self._buffer = self._buffer, ""
        return safe

    def flush(self) -> str:
        """Віддати залишок буфера після завершення генерації."""
        rest, self._buffer = self._buffer, ""
        return rest

    @property
    def stopped(self) -> bool:
        return bool(self.matched)


__all__ = [
    "DEFAULT_STOP",
    "GrammarUnsupported",
    "LIMITS",
    "SamplerChain",
    "SamplingParams",
    "StopMatcher",
    "flash_attn_value",
]
