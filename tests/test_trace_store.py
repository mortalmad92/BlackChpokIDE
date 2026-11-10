"""Тести вимірювання якості: traces і метрики з реальних ходів.

Мета — щоб «стало краще» можна було ПЕРЕВІРИТИ, а не заявити. Тому тут
перевіряються і самі метрики (формули), і те, що сховище не втрачає дані
й не ламається на пошкодженому файлі.

Запуск: python -m unittest tests.test_trace_store -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import trace_store  # noqa: E402


def _trace(**kwargs) -> trace_store.TurnTrace:
    defaults = {
        "intent_type": "edit",
        "language": "uk",
        "tools": ["read_file", "edit_file"],
        "changed_files": ["calc.py"],
        "steps": 2,
        "duration": 2.0,
        "human_readable": True,
        "answer_head": "Готово: додав множення.",
    }
    defaults.update(kwargs)
    return trace_store.TurnTrace(**defaults)


class TestMetrics(unittest.TestCase):
    """Кожна метрика має зрозумілий чисельник і знаменник."""

    def test_empty_sample_does_not_crash(self) -> None:
        values = trace_store.metric_values([])
        self.assertEqual(values["tool_selection_accuracy"], 0.0)
        self.assertEqual(values["human_readability"], 0.0)

    def test_clean_turn_scores_full(self) -> None:
        values = trace_store.metric_values([_trace()])
        self.assertEqual(values["tool_selection_accuracy"], 1.0)
        self.assertEqual(values["tool_argument_validity"], 1.0)
        self.assertEqual(values["human_readability"], 1.0)
        self.assertEqual(values["false_success_rate"], 0.0)

    def test_rejected_arguments_lower_validity(self) -> None:
        values = trace_store.metric_values([
            _trace(rejected_calls=1)])
        # 2 виклики, 1 відхилено → 1/2
        self.assertAlmostEqual(values["tool_argument_validity"], 0.5)

    def test_hallucinated_tool_is_counted(self) -> None:
        values = trace_store.metric_values([
            _trace(hallucinated_tool=True)])
        self.assertEqual(values["hallucinated_tool_rate"], 1.0)
        self.assertEqual(values["tool_selection_accuracy"], 0.0)

    def test_leaked_protocol_lowers_readability(self) -> None:
        values = trace_store.metric_values([
            _trace(leaked_protocol=True)])
        self.assertEqual(values["human_readability"], 0.0)

    def test_false_success_is_counted(self) -> None:
        values = trace_store.metric_values([
            _trace(false_success=True), _trace()])
        self.assertEqual(values["false_success_rate"], 0.5)

    def test_clarification_precision_and_recall(self) -> None:
        values = trace_store.metric_values([
            _trace(asked_clarification=True, clarification_useful=True),
            _trace(asked_clarification=True, clarification_useful=False),
            _trace(asked_clarification=False, clarification_useful=True),
        ])
        # precision: 1 корисне з 2 запитаних
        self.assertAlmostEqual(values["clarification_precision"], 0.5)
        # recall: 2 випадки, де потрібно; запитано в 1 з них
        self.assertAlmostEqual(values["clarification_recall"], 0.5)

    def test_averages(self) -> None:
        values = trace_store.metric_values([
            _trace(steps=1, duration=1.0, prompt_tokens=100, completion_tokens=50),
            _trace(steps=3, duration=3.0, prompt_tokens=200, completion_tokens=50),
        ])
        self.assertEqual(values["avg_steps"], 2.0)
        self.assertEqual(values["avg_duration"], 2.0)
        self.assertEqual(values["avg_tokens"], 200.0)

    def test_report_is_ukrainian_and_explains_metrics(self) -> None:
        report = trace_store.format_report(
            trace_store.aggregate([_trace()]))
        self.assertIn("Ходів у вибірці", report)
        for key in trace_store.METRIC_HELP:
            self.assertIn(key, report)


class TestStore(unittest.TestCase):
    """Сховище має бути простим і стійким."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.path = self.folder / "traces.jsonl"
        self.store = trace_store.TraceStore(self.path)

    def tearDown(self) -> None:
        for item in self.folder.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(self.folder.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
        self.folder.rmdir()

    def test_record_and_load(self) -> None:
        self.assertTrue(self.store.record(_trace()))
        loaded = self.store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].intent_type, "edit")
        self.assertEqual(loaded[0].changed_files, ["calc.py"])

    def test_broken_line_does_not_break_reading(self) -> None:
        self.store.record(_trace())
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write('{"битий json\n')
        self.store.record(_trace(intent_type="debug"))
        loaded = self.store.load(refresh=True)
        self.assertEqual(len(loaded), 2)

    def test_not_a_dict_line_is_skipped(self) -> None:
        self.path.write_text("[1, 2, 3]\n", encoding="utf-8")
        self.assertEqual(self.store.load(refresh=True), [])

    def test_summary_uses_aggregate(self) -> None:
        self.store.record(_trace())
        summary = self.store.summary()
        self.assertEqual(summary["turns"], 1)
        self.assertIn("metrics", summary)

    def test_examples_split_by_quality(self) -> None:
        self.store.record(_trace())
        self.store.record(_trace(leaked_protocol=True, human_readable=False))
        good = self.store.examples(good=True)
        bad = self.store.examples(good=False)
        self.assertEqual(len(good), 1)
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0].leaked_protocol)

    def test_clear(self) -> None:
        self.store.record(_trace())
        self.store.clear()
        self.assertEqual(self.store.load(refresh=True), [])

    def test_no_path_means_unavailable(self) -> None:
        store = trace_store.TraceStore(None)
        self.assertFalse(store.available())
        self.assertFalse(store.record(_trace()))
        self.assertEqual(store.load(), [])


class TestTraceFromEvents(unittest.TestCase):
    """Хід збирається з подій агента, без приватних міркувань."""

    def _event(self, kind: str, text: str = "", **data):
        from blackchpok_ide.agent import AgentEvent

        return AgentEvent(kind, text, data)

    def test_reasoning_is_not_stored(self) -> None:
        events = [
            self._event("reasoning", "міркую дуже довго…"),
            self._event("reasoning_token", "думка"),
            self._event("tool_call", "read_file(path=a.py)",
                        name="read_file", call_id="c1"),
        ]
        trace = trace_store.trace_from_events(events, answer="Готово.")
        self.assertEqual(trace.tools, ["read_file"])
        serialised = trace.to_dict()
        self.assertNotIn("reasoning", serialised)
        self.assertNotIn("думка", str(serialised))

    def test_hallucinated_tool_needs_known_list(self) -> None:
        events = [self._event("tool_call", "вигаданий()", name="вигаданий")]
        self.assertFalse(trace_store.trace_from_events(events).hallucinated_tool)
        self.assertTrue(trace_store.trace_from_events(
            events, known_tools=["read_file"]).hallucinated_tool)

    def test_changed_files_from_results(self) -> None:
        events = [
            self._event("tool_result", "Оновлено calc.py: замінено 1.",
                        name="edit_file", ok=True),
        ]
        trace = trace_store.trace_from_events(events, answer="Готово.")
        self.assertEqual(trace.changed_files, ["calc.py"])

    def test_false_success_when_nothing_changed(self) -> None:
        events = [
            self._event("tool_call", "list_dir(path=.)", name="list_dir"),
            self._event("tool_result", "a.py", name="list_dir", ok=True),
        ]
        trace = trace_store.trace_from_events(
            events, intent_type="edit", answer="Готово, усе змінено.")
        self.assertTrue(trace.false_success)

    def test_real_check_is_not_false_success(self) -> None:
        events = [
            self._event("tool_result", "OK", name="python_check", ok=True),
        ]
        trace = trace_store.trace_from_events(
            events, intent_type="edit", answer="Перевірив синтаксис.")
        self.assertFalse(trace.false_success)


class TestRoundTrip(unittest.TestCase):
    """Серіалізація не має втрачати поля."""

    def test_dict_round_trip(self) -> None:
        original = _trace(asked_clarification=True, clarification_useful=True,
                          prompt_tokens=10, completion_tokens=5, steps=3)
        restored = trace_store.TurnTrace.from_dict(original.to_dict())
        self.assertIsNotNone(restored)
        self.assertEqual(restored.tools, original.tools)
        self.assertEqual(restored.prompt_tokens, 10)
        self.assertTrue(restored.asked_clarification)
        self.assertTrue(restored.clarification_useful)

    def test_garbage_is_rejected(self) -> None:
        self.assertIsNone(trace_store.TurnTrace.from_dict("не словник"))
        self.assertIsNone(trace_store.TurnTrace.from_dict({"started_at": "вчора"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
