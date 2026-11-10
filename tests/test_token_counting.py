"""Регресії точного підрахунку токенів (Етап 3, 10.11.2026).

Що було зламано
---------------
Точний tokenizer підключався, але **не діяв**: лічильник зберігався в
``contextvars.ContextVar``, а ``contextvars`` не успадковуються новим
потоком. Агент працює саме в новому потоці (``AgentRunner._run``), тому
бачив ``None`` і рахував евристикою.

Гірше: евристик було ЧОТИРИ, і вони розходились:

===================  ==========================================
``agent.py``         ``кирилиця/1.6 + латиниця/3.6 + 8``
``context_budget``   ``кирилиця/1.6 + латиниця/3.6 + 6 + 2``
``context_stats``    ``len(text)/3.5``
``tool_lazy``        ``len(json)/3.5``
===================  ==========================================

Заміряно на одному українському реченні: **50 проти 23** токенів — понад
два рази. Саме ця оцінка вирішує, скільки історії лишити в промпті.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import agent, context_budget, context_stats  # noqa: E402

UK_TEXT = ("Привіт! Скільки файлів у теці blackchpok_ide? "
           "Виклич інструмент і покажи результат.")


class TestCounterCrossesThreads(unittest.TestCase):
    """Головний дефект: лічильник мусить бути видно з іншого потоку."""

    def setUp(self) -> None:
        agent.set_token_counter(None)
        context_stats.set_token_counter(None)

    def tearDown(self) -> None:
        agent.set_token_counter(None)
        context_stats.set_token_counter(None)

    def test_agent_counter_visible_in_worker_thread(self) -> None:
        agent.set_token_counter(lambda text: 1000)
        seen: dict[str, object] = {}

        def work() -> None:
            seen["counter"] = agent.current_token_counter()

        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertIsNotNone(
            seen.get("counter"),
            "contextvars не переходять у новий потік — саме це й ламало "
            "точний підрахунок")

    def test_stats_counter_visible_in_worker_thread(self) -> None:
        context_stats.set_token_counter(lambda text: 1000)
        seen: dict[str, int] = {}

        def work() -> None:
            seen["tokens"] = context_stats.estimate_tokens("щось")

        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertEqual(seen.get("tokens"), 1000)

    def test_runner_has_set_token_counter_method(self) -> None:
        """``main_window`` кликав через getattr — методу не існувало."""
        self.assertTrue(
            hasattr(agent.AgentRunner, "set_token_counter"),
            "без цього методу виклик у main_window стає тихим no-op")

    def test_runner_method_installs_globally(self) -> None:
        runner = agent.AgentRunner.__new__(agent.AgentRunner)
        runner._token_counter = None
        runner._context_window = None
        runner._context_budget = None
        runner.set_token_counter(lambda text: 7)
        self.assertIsNotNone(agent.current_token_counter())
        # 7 токенів від лічильника + PER_MESSAGE_OVERHEAD (6) на повідомлення.
        expected = 7 + context_budget.PER_MESSAGE_OVERHEAD
        self.assertEqual(agent.AgentSession._tokens_in("abc"), expected)

    def test_counter_can_be_removed(self) -> None:
        agent.set_token_counter(lambda text: 999)
        agent.set_token_counter(None)
        self.assertIsNone(agent.current_token_counter())
        self.assertFalse(context_stats.estimate_is_exact())


class TestHeuristicsAreUnified(unittest.TestCase):
    """Запасний варіант мусить бути ОДИН, а не чотири."""

    def setUp(self) -> None:
        agent.set_token_counter(None)
        context_stats.set_token_counter(None)

    def tearDown(self) -> None:
        agent.set_token_counter(None)
        context_stats.set_token_counter(None)

    def test_agent_and_budget_agree(self) -> None:
        self.assertEqual(agent.AgentSession._tokens_in(UK_TEXT),
                         context_budget.estimate_tokens(UK_TEXT))

    def test_agent_and_stats_agree(self) -> None:
        self.assertEqual(agent.AgentSession._tokens_in(UK_TEXT),
                         context_stats.estimate_tokens(UK_TEXT))

    def test_all_three_agree(self) -> None:
        values = {
            agent.AgentSession._tokens_in(UK_TEXT),
            context_budget.estimate_tokens(UK_TEXT),
            context_stats.estimate_tokens(UK_TEXT),
        }
        self.assertEqual(len(values), 1,
                         f"три різні оцінки для одного тексту: {sorted(values)}")

    def test_estimate_is_positive(self) -> None:
        self.assertGreater(context_budget.estimate_tokens(UK_TEXT), 0)

    def test_empty_text_is_zero(self) -> None:
        self.assertEqual(context_budget.estimate_tokens(""), 0)
        self.assertEqual(context_stats.estimate_tokens(""), 0)

    def test_exact_counter_wins_over_heuristic(self) -> None:
        agent.set_token_counter(lambda text: 89)
        context_stats.set_token_counter(lambda text: 89)
        self.assertEqual(context_budget.estimate_tokens(
            UK_TEXT, counter=agent.current_token_counter()), 95)  # 89 + overhead
        self.assertEqual(context_stats.estimate_tokens(UK_TEXT), 89)


if __name__ == "__main__":
    unittest.main(verbosity=2)
