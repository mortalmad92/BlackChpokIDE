"""Охоронець бюджету контексту: відповіді мусять надходити ЗАВЖДИ.

Регрес, який цей файл закриває (живий прогін 21.11.2026):

Після переходу на «повний набір інструментів» кількість схем зросла до 91
(MCP + пам'ять + скіли + саморобні інструменти). У вікні 16 384 вони зайняли
11 520 токенів. Бюджет виглядав так:

    вікно 16 384 · відповідь 4 096 · історія 0 · інструменти 4 252 · система 8 939

Тобто на ІСТОРІЮ лишалось НУЛЬ токенів. Модель не бачила, що вже зроблено,
і відповіді перестали надходити до чату — саме те, на що поскаржився
користувач.

Причина: ``_full_set_fits()`` перевіряла лише «вікно ≥ 16k», а не реальну
вагу схем. Тепер перевірка міряє токени й лишає частку на розмову.

Запуск: python -m unittest tests.test_context_budget_floor -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import context_budget  # noqa: E402
from blackchpok_ide.agent import (AgentRunner, AgentSession,  # noqa: E402
                                  HISTORY_FLOOR_SHARE)
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402

WINDOWS = (8192, 16384, 32768, 65536)


def make_runner(window: int) -> AgentRunner:
    runner = AgentRunner(ToolRegistry(ROOT), LLMSettings(),
                         AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = True
    runner.adopt_context_window(props_ctx=window)
    return runner


class TestHistoryAlwaysHasRoom(unittest.TestCase):
    """На історію лишається місце за БУДЬ-якого вікна."""

    def test_budget_keeps_history(self) -> None:
        for window in WINDOWS:
            with self.subTest(window=window):
                runner = make_runner(window)
                runner.tool_schemas()
                budget = runner._context_budget
                self.assertIsNotNone(budget)
                self.assertGreater(
                    budget.history, 0,
                    f"вікно {window}: історія 0 — відповіді не надходитимуть; "
                    f"{budget.text()}")
                self.assertGreaterEqual(
                    budget.history, 1024,
                    f"вікно {window}: історії замало; {budget.text()}")

    def test_schemas_do_not_eat_the_window(self) -> None:
        """Схеми + система не мають займати понад 2/3 вікна."""
        for window in WINDOWS:
            with self.subTest(window=window):
                runner = make_runner(window)
                runner.tool_schemas()
                system = AgentSession._tokens_in(
                    str(runner.session.system_message().get("content") or ""))
                tools = runner.session._tools_tokens()
                spent = system + tools
                self.assertLess(
                    spent, int(window * 0.75),
                    f"вікно {window}: службові дані {spent} токенів "
                    f"(система {system} + схеми {tools}) з'їли майже все")


class TestFullSetFitIsMeasured(unittest.TestCase):
    """``_full_set_fits`` міряє РЕАЛЬНУ вагу, а не лише розмір вікна."""

    def test_small_window_does_not_fit(self) -> None:
        runner = make_runner(8192)
        schemas = runner._available_schemas()
        self.assertFalse(runner._full_set_fits(schemas))

    def test_huge_schemas_do_not_fit_any_window(self) -> None:
        """Штучно величезний набір не проходить навіть вікно 16k.

        Це той самий випадок, що стався насправді: 91 інструмент.
        """
        runner = make_runner(16384)
        huge = []
        for index in range(200):
            huge.append({
                "type": "function",
                "function": {
                    "name": f"tool_{index}",
                    "description": "Опис інструмента " * 20,
                    "parameters": {"type": "object", "properties": {
                        f"p{index}": {"type": "string",
                                      "description": "параметр " * 10}}},
                },
            })
        self.assertFalse(runner._full_set_fits(huge))

    def test_small_set_fits_big_window(self) -> None:
        runner = make_runner(65536)
        small = runner._available_schemas()[:3]
        self.assertTrue(runner._full_set_fits(small))

    def test_unknown_window_is_optimistic(self) -> None:
        """Невідоме вікно не блокує повний набір (типово ≥16k)."""
        runner = make_runner(16384)
        runner.session.context_limit = 0
        self.assertTrue(runner._full_set_fits([{"type": "function",
                                               "function": {"name": "x"}}]))


class TestFloorShareSane(unittest.TestCase):
    """Частка на історію — у розумних межах (не 0 і не понад половину)."""

    def test_share_range(self) -> None:
        self.assertGreaterEqual(HISTORY_FLOOR_SHARE, 0.25)
        self.assertLessEqual(HISTORY_FLOOR_SHARE, 0.5)


class TestBudgetMath(unittest.TestCase):
    """Сама формула бюджету: службові дані не роблять історію від'ємною."""

    def test_overload_does_not_break_budget(self) -> None:
        budget = context_budget.plan(16384, system_tokens=12000,
                                     tools_tokens=8000)
        self.assertGreaterEqual(budget.history, 0)
        self.assertTrue(budget.notes, "переповнення мусить бути позначене")

    def test_normal_case_leaves_history(self) -> None:
        budget = context_budget.plan(16384, system_tokens=3200,
                                     tools_tokens=2200)
        self.assertGreater(budget.history, 2048)
        self.assertFalse(budget.notes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
