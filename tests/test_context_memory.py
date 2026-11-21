"""Контекст за РЕАЛЬНОЮ пам'яттю, а не фіксовані 4096 токенів.

Питання користувача (21.11.2026): «а збільшити контекст за допомогою великої
кількості RAM, яка є в мене на компʼютері, не варіант?».

Відповідь: так, і це вже працює. Заміряно на цій машині
(RTX 3060 12 ГБ + 64 ГБ RAM, модель Qwen2.5-Coder-14B Q4):

    ctx  16 384 · f16 · GPU  → 11.9 / 12.3 ГБ VRAM (упритул)
    ctx  32 768 · q8_0 · GPU → 11.9 ГБ VRAM, 43.0 ГБ RAM вільно
    ctx  65 536 · q8_0 · GPU → 11.9 ГБ VRAM, 39.7 ГБ RAM вільно
    ctx 131 072 · q8_0 · GPU → 11.9 ГБ VRAM, 32.9 ГБ RAM вільно
    ctx 131 072 · q8_0 · RAM →  9.9 ГБ VRAM, 30.7 ГБ RAM вільно

Тобто 131 072 токени (тренувальне вікно моделі) завантажуються за 10.4 с і
працюють. Раніше типовим було 16 384 — увосьмеро менше.

Запуск: python -m unittest tests.test_context_memory -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.native import engine  # noqa: E402

MODEL = ROOT / "userdata" / "models" / "qwen2.5-coder-14b-instruct-q4_k_m.gguf"


class TestMemoryProbes(unittest.TestCase):
    """Замір вільної пам'яті працює й дає правдоподібні числа."""

    def test_free_ram_is_plausible(self) -> None:
        free = engine._free_ram_bytes()
        self.assertGreater(free, 0, "вільну RAM не визначено")
        # Менше за 64 ТБ — інакше це явно помилка обчислення.
        self.assertLess(free, 64 * 1024 ** 4)

    def test_free_vram_is_plausible(self) -> None:
        free = engine._free_vram_bytes()
        if free == 0:
            self.skipTest("nvidia-smi недоступний")
        self.assertGreater(free, 0)
        self.assertLess(free, 512 * 1024 ** 3)


class TestContextLadder(unittest.TestCase):
    """Драбина розмірів: від найбільшого до найменшого."""

    def test_ladder_is_descending(self) -> None:
        sizes = engine._CONTEXT_LADDER
        self.assertEqual(list(sizes), sorted(sizes, reverse=True))
        self.assertEqual(sizes[0], 131_072,
                         "найбільший розмір має бути тренувальним вікном")

    def test_ladder_covers_small_windows(self) -> None:
        self.assertIn(4_096, engine._CONTEXT_LADDER)
        self.assertIn(8_192, engine._CONTEXT_LADDER)


class TestBestContext(unittest.TestCase):
    """Підбір контексту за реальною пам'яттю."""

    def test_picks_large_context_on_this_machine(self) -> None:
        if not MODEL.exists():
            self.skipTest("моделі немає на диску")
        chosen = engine._best_context(MODEL, gpu_layers=999)
        self.assertGreaterEqual(
            chosen, 16_384,
            f"контекст менший за типовий: {chosen}")
        # На цій машині заміряно 131 072 — саме стільки й має обратись.
        self.assertEqual(chosen, 131_072,
                         f"очікували тренувальне вікно, отримали {chosen}")

    def test_never_exceeds_training_window(self) -> None:
        if not MODEL.exists():
            self.skipTest("моделі немає на диску")
        chosen = engine._best_context(MODEL, gpu_layers=999)
        report = engine.inspect_mod.inspect(MODEL)
        train = int(getattr(report, "context_train", 0) or 0)
        if train:
            self.assertLessEqual(chosen, train,
                                 "контекст більший за тренувальний")

    def test_missing_file_gives_safe_value(self) -> None:
        chosen = engine._best_context(Path("немає.gguf"), gpu_layers=999)
        self.assertGreaterEqual(chosen, engine.MIN_CTX)


class TestEngineUsesIt(unittest.TestCase):
    """Рушій справді бере підібраний контекст (жива перевірка)."""

    def test_engine_loads_big_context(self) -> None:
        if not MODEL.exists():
            self.skipTest("моделі немає на диску")
        eng = engine.NativeEngine()
        try:
            info = eng.load(str(MODEL),
                            engine.LoadOptions(n_ctx=0, n_gpu_layers=999))
            actual = int(info.get("context_actual") or 0)
            train = int(info.get("context_train") or 0)
            self.assertGreater(actual, 16_384,
                               f"рушій узяв малий контекст: {actual}")
            if train:
                self.assertLessEqual(actual, train)
        finally:
            try:
                eng.unload()
            except Exception:                         # noqa: BLE001
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
