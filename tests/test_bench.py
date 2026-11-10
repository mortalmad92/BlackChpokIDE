"""Тести бенчмарку: метрики мусять бути виміряні, а не вигадані.

Головна вимога до цих тестів — ловити «красиві цифри»:

* якщо модель не завантажена, бенчмарк ЗОБОВ'ЯЗАНИЙ сказати ``skipped``
  із причиною, а не показати нулі як «результат»;
* перцентилі рахуються правильно (p50 ≤ p95 ≤ p99);
* ``Recall@K`` падає, коли правильний спогад вилучено з бази;
* порівняння двох звітів показує напрям зміни (більше/менше), а не лише
  абсолютні числа.

Запуск: ``python -m unittest tests.test_bench -v``
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import bench                                       # noqa: E402
from blackchpok_ide.native import _bindings                            # noqa: E402
from blackchpok_ide.pcmm import Neuromesh                              # noqa: E402


class TestPercentile(unittest.TestCase):
    """Перцентилі без numpy — щоб не тягнути залежність заради трьох чисел."""

    def test_single_value(self) -> None:
        self.assertEqual(bench.percentile([5.0], 0.95), 5.0)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(bench.percentile([], 0.5), 0.0)

    def test_order_is_monotonic(self) -> None:
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        p50 = bench.percentile(values, 0.5)
        p95 = bench.percentile(values, 0.95)
        p99 = bench.percentile(values, 0.99)
        self.assertLessEqual(p50, p95)
        self.assertLessEqual(p95, p99)
        self.assertAlmostEqual(p50, 55.0, places=1)

    def test_median_matches_statistics(self) -> None:
        import statistics

        values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        self.assertAlmostEqual(bench.percentile(values, 0.5),
                              statistics.median(values), places=6)


class TestMetric(unittest.TestCase):
    """Одна метрика: значення, одиниця, вибірка, перцентилі."""

    def test_metric_reports_percentiles(self) -> None:
        metric = bench.Metric("speed", 30.0, "ток/с", samples=[28.0, 30.0, 32.0])
        data = metric.to_dict()
        self.assertEqual(data["value"], 30.0)
        self.assertIn("p50", data)
        self.assertIn("p95", data)
        self.assertEqual(len(data["samples"]), 3)

    def test_metric_without_samples_has_no_percentiles(self) -> None:
        data = bench.Metric("load", 4000.0, "мс").to_dict()
        self.assertNotIn("p50", data)


class TestEngineBenchmarkSkipping(unittest.TestCase):
    """Без завантаженої моделі бенчмарк не показує нулі як успіх."""

    def test_skipped_without_model(self) -> None:
        class FakeEngine:
            loaded = False

        class FakeRuntime:
            engine = FakeEngine()

        report = bench.EngineBenchmark(FakeRuntime()).run(runs=1)
        self.assertEqual(report["status"], "skipped")
        self.assertTrue(report["reason"])
        self.assertEqual(report["metrics"], {})

    def test_missing_runtime_is_skipped(self) -> None:
        report = bench.EngineBenchmark(None).run(runs=1)
        self.assertEqual(report["status"], "skipped")


class TestMemoryBenchmark(unittest.TestCase):
    """Recall/Precision/MRR рахуються на реальній базі."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.memory = Neuromesh(Path(self._folder.name) / "bench.db")

    def tearDown(self) -> None:
        self.memory.close()
        self._folder.cleanup()

    def test_recall_is_high_when_memory_has_answers(self) -> None:
        report = bench.MemoryBenchmark(self.memory).run(k=3)
        self.assertEqual(report["status"], "ok")
        self.assertGreaterEqual(report["recall_at_k"], 0.8,
                                f"Recall@3 занизький: {report['details']}")
        self.assertGreater(report["mrr"], 0.5)

    def test_recall_drops_when_answers_are_absent(self) -> None:
        """Порожня база мусить давати Recall=0, а не «все добре»."""
        report = bench.MemoryBenchmark(self.memory).run(k=3, seed=False)
        self.assertIn(report["status"], {"ok", "skipped"})
        if report["status"] == "ok":
            self.assertEqual(report["recall_at_k"], 0.0)

    def test_details_explain_rank(self) -> None:
        report = bench.MemoryBenchmark(self.memory).run(k=3)
        for detail in report["details"]:
            self.assertIn("query", detail)
            self.assertIn("rank", detail)
            self.assertIn("policy", detail)

    def test_memory_benchmark_without_memory_is_skipped(self) -> None:
        report = bench.MemoryBenchmark(None).run()
        self.assertEqual(report["status"], "skipped")


class TestCompare(unittest.TestCase):
    """Порівняння звітів показує напрям зміни."""

    def test_compare_reports_ratio_and_delta(self) -> None:
        left = {"engine": {"metrics": {"tokens_per_second": {"value": 20.0}}},
                "memory": {"recall_at_k": 0.8, "mrr": 0.7}}
        right = {"engine": {"metrics": {"tokens_per_second": {"value": 30.0}}},
                 "memory": {"recall_at_k": 0.9, "mrr": 0.6}}
        diff = bench.compare(left, right)
        self.assertEqual(diff["engine"]["tokens_per_second"]["delta"], 10.0)
        self.assertAlmostEqual(diff["engine"]["tokens_per_second"]["ratio"], 1.5)
        self.assertAlmostEqual(diff["memory"]["mrr"]["delta"], -0.1, places=6)

    def test_compare_handles_missing_sections(self) -> None:
        diff = bench.compare({}, {})
        self.assertEqual(diff["engine"], {})
        self.assertEqual(diff["memory"], {})


class TestSaveAndLoad(unittest.TestCase):
    """Звіт зберігається й читається назад без втрат."""

    def test_save_roundtrip(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as folder:
            report = {"engine": {"status": "ok"}, "memory": {"status": "skipped"}}
            path = bench.save(report, Path(folder) / "nested" / "report.json")
            self.assertTrue(path.exists())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["engine"]["status"], "ok")


@unittest.skipUnless(
    _bindings.library_ready() and any(
        (ROOT / "userdata" / "models").glob("*.gguf")),
    "потрібні llama.dll і GGUF-модель")
class TestEngineBenchmarkLive(unittest.TestCase):
    """Живий прогін: метрики мусять бути додатними й узгодженими."""

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide.native.api import NativeRuntime

        folder = ROOT / "userdata" / "models"
        from blackchpok_ide.model_hub import is_projector_path

        # Проєктор зору (mmproj) — не модель. Перевіряємо це СПІЛЬНИМ
        # правилом: префікс ``mmproj`` не ловить офіційну назву mistralai
        # ``…-BF16-mmproj.gguf``, і тест брав проєктор за модель.
        candidates = [item for item in folder.glob("*.gguf")
                      if not is_projector_path(item)]
        cls.runtime = NativeRuntime()
        cls.runtime.load_model(str(min(candidates, key=lambda p: p.stat().st_size)),
                               ctx=2048, gpu_layers=0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runtime.shut_down()

    def test_metrics_are_positive_and_consistent(self) -> None:
        report = bench.EngineBenchmark(self.runtime).run(runs=1, max_tokens=16)
        self.assertEqual(report["status"], "ok", report.get("reason"))
        metrics = report["metrics"]
        self.assertGreater(metrics["tokens_per_second"]["value"], 0)
        self.assertGreater(metrics["time_to_first_token_ms"]["value"], 0)
        self.assertGreater(metrics["total_ms"]["value"], 0)
        self.assertGreater(metrics["peak_ram_mb"]["value"], 0,
                           "RAM процесу не вимірялась — 0 МБ це не «норма»")
        self.assertEqual(metrics["kv_cache_capacity"]["value"], 2048)

    def test_percentiles_present_for_multiple_runs(self) -> None:
        report = bench.EngineBenchmark(self.runtime).run(runs=2, max_tokens=8)
        data = report["metrics"]["tokens_per_second"]
        self.assertIn("p50", data)
        self.assertIn("p95", data)
        self.assertEqual(len(data["samples"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
