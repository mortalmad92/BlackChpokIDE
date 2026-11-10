"""Регресії швидкості старту (Етап 2, 10.11.2026).

Заміряно до виправлень: старт IDE — **6.3–15.7 с**, з них:
``discover_server_url`` (24 порти × таймаут connect) — 8.3 с,
``server_responds`` (3 HTTP-спроби) — 4.6 с,
22× розбір метаданих GGUF — 2.3 с,
``probe_context_window`` з головного потоку — 1.0 с.

Після виправлень: **1.86 с**. Ці перевірки фіксують саме те, що дало
виграш, щоб воно не повернулось поступово.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import runtime  # noqa: E402
from blackchpok_ide.native import gguf  # noqa: E402


class TestPortProbeCost(unittest.TestCase):
    """Перевірка порту мусить бути дешевою: вона йде в циклі по 8 портах."""

    def test_probe_timeout_is_small(self) -> None:
        """Таймаут connect ≤ 0.1 с.

        Кожен закритий порт коштує РІВНО таймаут (заміряно: 0.35 → 369 мс,
        0.05 → 61 мс). При 24 портах 0.35 с давало 8.3 с старту.
        """
        self.assertLessEqual(runtime.PORT_PROBE_TIMEOUT, 0.1)

    def test_scan_range_is_bounded(self) -> None:
        """Скануємо не більше 12 портів: далі — це вже не «сусідній сервер»."""
        self.assertLessEqual(runtime.PORT_SCAN_RANGE, 12)
        self.assertGreaterEqual(runtime.PORT_SCAN_RANGE, 1)

    def test_closed_port_is_not_reported_busy(self) -> None:
        """Закритий порт не вважається зайнятим (і перевірка швидка)."""
        import time

        started = time.perf_counter()
        busy = runtime.port_is_busy(9)
        elapsed = time.perf_counter() - started
        self.assertFalse(busy)
        self.assertLess(elapsed, 0.35, f"перевірка порту тривала {elapsed:.2f} с")


class TestServerRespondsCache(unittest.TestCase):
    """Повторна перевірка того самого сервера не має ходити в мережу."""

    def test_negative_result_is_cached(self) -> None:
        """«Сервер не відповів» теж кешується — інакше чекаємо щоразу."""
        runtime.forget_server_responds()
        first = runtime.server_responds("http://127.0.0.1:9/v1", timeout=0.2)
        self.assertFalse(first)
        import time

        started = time.perf_counter()
        second = runtime.server_responds("http://127.0.0.1:9/v1", timeout=0.2)
        self.assertFalse(second)
        self.assertLess(time.perf_counter() - started, 0.05,
                        "друга перевірка пішла в мережу замість кешу")

    def test_forget_clears(self) -> None:
        """Скидання кешу змушує перевірити знову."""
        runtime.forget_server_responds()
        runtime.server_responds("http://127.0.0.1:9/v1", timeout=0.2)
        runtime.forget_server_responds("http://127.0.0.1:9/v1")
        self.assertFalse(runtime.server_responds("http://127.0.0.1:9/v1",
                                                 timeout=0.2))

    def test_use_cache_false_bypasses(self) -> None:
        """Явний обхід кешу працює (потрібно після зупинки сервера)."""
        runtime.forget_server_responds()
        runtime.server_responds("http://127.0.0.1:9/v1", timeout=0.2)
        self.assertFalse(runtime.server_responds("http://127.0.0.1:9/v1",
                                                 timeout=0.2, use_cache=False))


class TestGgufMetaCache(unittest.TestCase):
    """Розбір метаданих GGUF — найдорожча операція списку моделей."""

    def test_cached_reader_exists_and_is_exported(self) -> None:
        self.assertIn("read_meta_cached", gguf.__all__)
        self.assertTrue(callable(gguf.read_meta_cached))

    def test_missing_file_does_not_raise(self) -> None:
        """Неіснуючий файл — це ``_error`` у метаданих, а не виняток."""
        meta = gguf.read_meta_cached(ROOT / "нема-такого-файлу.gguf")
        self.assertIn("_error", meta.values)

    def test_second_read_is_faster(self) -> None:
        """Друге читання того самого файлу йде з кешу."""
        models = sorted((ROOT / "userdata" / "models").glob("*.gguf"))
        if not models:
            self.skipTest("немає GGUF-моделей для перевірки")
        target = models[0]
        import time

        gguf.clear_meta_cache()
        started = time.perf_counter()
        first = gguf.read_meta_cached(target)
        cold = time.perf_counter() - started
        started = time.perf_counter()
        second = gguf.read_meta_cached(target)
        warm = time.perf_counter() - started
        self.assertEqual(first.architecture, second.architecture)
        self.assertEqual(first.tensor_count, second.tensor_count)
        self.assertLess(warm, max(cold, 0.02),
                        f"кеш не діє: холодно {cold*1000:.1f} мс, тепло {warm*1000:.1f} мс")

    def test_cache_survives_refresh(self) -> None:
        """Кеш не спотворює дані: повторний розбір дає ті самі числа."""
        models = sorted((ROOT / "userdata" / "models").glob("*.gguf"))
        if not models:
            self.skipTest("немає GGUF-моделей для перевірки")
        target = models[0]
        gguf.clear_meta_cache()
        cached = gguf.read_meta_cached(target)
        fresh = gguf.read_meta_safe(target)
        self.assertEqual(cached.architecture, fresh.architecture)
        self.assertEqual(cached.tensor_count, fresh.tensor_count)
        self.assertEqual(cached.context_length, fresh.context_length)


class TestAgentWindowProbeIsOptional(unittest.TestCase):
    """Інтерфейс не має чекати на мережу, щоб намалювати панель схем."""

    def test_tool_schemas_accepts_probe_window_flag(self) -> None:
        import inspect

        from blackchpok_ide.agent import AgentRunner

        params = inspect.signature(AgentRunner.tool_schemas).parameters
        self.assertIn("probe_window", params)
        self.assertTrue(params["probe_window"].default,
                        "типове значення мусить бути True: агент чекає на вікно")


if __name__ == "__main__":
    unittest.main(verbosity=2)
