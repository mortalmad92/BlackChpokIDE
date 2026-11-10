"""Бюджет контексту: запит мусить вміщатись у вікно моделі.

Знайдено живим прогоном: схеми 21 інструмента (~2100 токенів) не входили
в розрахунок, тому «60% вікна на історію» давало запити на 8900 токенів
при вікні 8192 — сервер відповідав ``exceed_context_size_error`` і агент
безпорадно повторював спробу.

Запуск: python -m unittest tests.test_context_budget -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent import AgentSession, AgentRunner  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings  # noqa: E402


def _runner(limit: int = 8192) -> AgentRunner:
    runner = AgentRunner.__new__(AgentRunner)
    runner.session = AgentSession(AgentSettings(), ROOT)
    runner.session.context_limit = limit
    runner.registry = ToolRegistry(ROOT)
    runner.mcp_manager = None
    runner.settings_ref = None
    runner.tools_enabled = True
    runner.mode_prompt = ""
    runner.max_steps_override = 0
    schemas = runner.tool_schemas()
    runner.session._schemas_cache = schemas
    return runner


class TestContextBudget(unittest.TestCase):
    def test_schemas_are_counted(self) -> None:
        runner = _runner()
        # Схеми мають займати помітну частину вікна, а не нуль.
        self.assertGreater(runner.session._tools_tokens(), 1000)

    def test_budget_leaves_room_for_tools(self) -> None:
        runner = _runner(8192)
        budget = runner.session._token_chars_budget()
        tools = runner.session._tools_tokens()
        system = runner.session._tokens_in(
            str(runner.session.system_message().get("content") or ""))
        # Історія + схеми + системний промпт + запас мають вміщатись у вікно.
        self.assertLess(budget + tools + system, 8192)

    def test_huge_user_message_does_not_overflow(self) -> None:
        runner = _runner(8192)
        runner.session.add_user("x" * 40_000)
        runner.session.trim()
        self.assertLessEqual(runner.session._estimate_tokens(), 8192)

    def test_long_history_is_trimmed(self) -> None:
        runner = _runner(8192)
        for index in range(40):
            runner.session.add_user(f"повідомлення {index} " * 60)
            runner.session.add_assistant(f"відповідь {index} " * 60)
        runner.session.trim()
        self.assertLessEqual(runner.session._estimate_tokens(), 8192)

    def test_small_window_still_fits(self) -> None:
        runner = _runner(4096)
        runner.session.add_user("y" * 20_000)
        runner.session.trim()
        self.assertLessEqual(runner.session._estimate_tokens(), 4096)

    def test_empty_session_is_small(self) -> None:
        runner = _runner()
        self.assertLessEqual(runner.session._estimate_tokens(), 4000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
