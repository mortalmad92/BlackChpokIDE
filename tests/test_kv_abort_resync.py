"""Регресія: мітка KV-кешу не має розходитись із рушієм після скасування.

Живий дефект (відтворено на RTX 3060, Qwen2.5-Coder-14B, ctx 16384):

    скасування посеред prefill
    → ggml: failed with error 1  (це GGML_STATUS_ABORTED = 1, не CUDA-збій)
    → llama_decode повертає 2    (DECODE_ABORTED)
    → рушій ЛИШАЄ пораховані ubatch-і в пам'яті (llama.h)
    → наша мітка каже 0 токенів, рушій має 1536
    → наступний хід декодує з нуля поверх наявних даних
    → llama_decode повертає -1 («inconsistent sequence positions»)
    → LLMError → агент повторює ту саму зіпсовану генерацію
    → контекст заклинює до перезавантаження моделі = «модель перестала
      відповідати», ззовні «програма зависла».

Ці тести не потребують моделі: вони підставляють рушій-двійник із тими
самими методами й перевіряють саме ЛОГІКУ синхронізації.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.native import _abi  # noqa: E402
from blackchpok_ide.native.kv import CacheManager  # noqa: E402


class FakeMemory:
    """Дескриптор пам'яті KV (``llama_get_memory``)."""

    def __init__(self, engine: "FakeLib") -> None:
        self._engine = engine


class FakeLib:
    """Мінімальний двійник llama.dll — лише те, що чіпає ``CacheManager``."""

    def __init__(self, *, real_tokens: int = 0) -> None:
        self.real_tokens = real_tokens      # скільки токенів СПРАВДІ в рушії
        self.cleared = 0
        self.truncated: list[int] = []

    # ── llama.h ───────────────────────────────────────────────────────────
    def llama_get_memory(self, _ctx):        # noqa: N802 - ім'я C-функції
        return FakeMemory(self)

    def llama_memory_seq_pos_max(self, _memory, _seq):    # noqa: N802
        # Рушій повертає ПОЗИЦІЮ, а не кількість: порожній кеш → -1.
        return self.real_tokens - 1

    def llama_memory_clear(self, _memory, _data):          # noqa: N802
        self.cleared += 1
        self.real_tokens = 0
        return True

    def llama_memory_seq_rm(self, _memory, _seq, p0, p1):  # noqa: N802
        self.truncated.append(int(p0))
        if p1 == -1:
            self.real_tokens = min(self.real_tokens, int(p0))
        return True


class TestKvResyncAfterAbort(TestCase):
    """Скасування лишає дані в рушії — мітка мусить це побачити."""

    def _manager(self, *, real_tokens: int, mirror_tokens: int) -> tuple[CacheManager, FakeLib]:
        lib = FakeLib(real_tokens=real_tokens)
        cache = CacheManager(lib, ctx=1, capacity=16384)     # type: ignore[arg-type]
        cache.state.tokens = list(range(mirror_tokens))
        return cache, lib

    def test_resync_reads_real_length_from_engine(self) -> None:
        """``resync`` бере довжину З РУШІЯ, а не з власної мітки."""
        cache, _lib = self._manager(real_tokens=1536, mirror_tokens=0)
        length = cache.resync()
        self.assertEqual(length, 1536,
                         "resync мусить повернути реальну кількість токенів")

    def test_resync_clears_stale_mirror(self) -> None:
        """Після розсинхрону дзеркало порожнє: позиції відновити неможливо."""
        cache, _lib = self._manager(real_tokens=1536, mirror_tokens=0)
        cache.resync()
        self.assertEqual(cache.length, 0,
                         "вміст токенів невідомий — дзеркало мусить бути порожнім")

    def test_resync_on_empty_engine_keeps_zero(self) -> None:
        """Порожній рушій (pos_max = -1) дає нуль, а не -1."""
        cache, _lib = self._manager(real_tokens=0, mirror_tokens=0)
        self.assertEqual(cache.resync(), 0)

    def test_prepare_clears_when_mirror_disagrees(self) -> None:
        """ГОЛОВНА регресія: ``prepare`` не довіряє хибній мітці.

        Саме тут був дефект: мітка казала 0, рушій мав 1536 токенів, і
        ``prepare`` повертав ``skip = 0`` → ``llama_decode`` падав з ``-1``.
        """
        cache, lib = self._manager(real_tokens=1536, mirror_tokens=0)
        prompt = list(range(100, 140))
        skip = cache.prepare(prompt)
        self.assertEqual(skip, 0,
                         "після розсинхрону промпт треба перерахувати з нуля")
        self.assertEqual(lib.cleared, 1,
                         "розсинхронізований кеш мусить бути очищений")

    def test_prepare_keeps_prefix_when_in_sync(self) -> None:
        """Коли рушій і мітка згодні — спільний префікс перевикористовується."""
        prefix = list(range(50))
        cache, lib = self._manager(real_tokens=len(prefix), mirror_tokens=len(prefix))
        cache.state.tokens = list(prefix)
        skip = cache.prepare(prefix + [999, 1000])
        self.assertEqual(skip, len(prefix),
                         "синхронний кеш мусить дати перевикористання префікса")
        self.assertEqual(lib.cleared, 0, "синхронний кеш не можна чистити")


class TestDecodeCodesAreDistinguished(TestCase):
    """Коди ``llama_decode`` мусять розрізнятись, а не зливатись у «cancel»."""

    def test_aborted_constant_matches_llama_h(self) -> None:
        self.assertEqual(_abi.DECODE_ABORTED, 2,
                         "llama.h: 2 = aborted")

    def test_error_codes_have_explanations(self) -> None:
        self.assertIn(_abi.DECODE_ERROR, _abi.DECODE_ERROR_TEXT)
        self.assertIn(_abi.DECODE_NO_MEMORY, _abi.DECODE_ERROR_TEXT)

    def test_error_text_mentions_position_desync(self) -> None:
        text = _abi.DECODE_ERROR_TEXT[_abi.DECODE_ERROR].lower()
        self.assertIn("позиц", text,
                      "код -1 найчастіше означає саме розсинхрон позицій")


if __name__ == "__main__":
    main()
