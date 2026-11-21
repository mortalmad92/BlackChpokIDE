"""Автовизначення контексту ПІД КОЖЕН ЗАПИТ (вимога 21.11.2026).

Що перевіряється. Користувач просив: «зроби автовизначення в залежності від
потреби на запит користувача». До цієї зміни бюджет був ОДНИМ числом на всю
сесію (``WORKING_WINDOW = 32768``): «привіт» і «продовж велику роботу»
отримували однаково, тож дрібниця чекала так само довго, як велика справа.

Тепер розмір вибирає :func:`context_budget.working_window` за виміряною
потребою, а :meth:`AgentRunner.refresh_budget_for_request` перераховує його
перед КОЖНИМ кроком. Ці тести — охоронці саме цієї поведінки.

Запуск: python -m unittest tests.test_adaptive_context_per_request -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import context_budget  # noqa: E402
from blackchpok_ide.agent import AgentRunner  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402

WINDOW = 131_072


def make_runner(window: int = WINDOW) -> AgentRunner:
    runner = AgentRunner(ToolRegistry(ROOT), LLMSettings(), AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.adopt_context_window(props_ctx=window, source="тест")
    runner.tool_schemas()
    return runner


class TestWorkingWindowMath(unittest.TestCase):
    """Сама формула: більше потреби — більше бюджету, стелі — не порушує."""

    def test_more_need_means_more_budget(self) -> None:
        """Зростання виміряної потреби не може ЗМЕНШУВАТИ бюджет.

        Починаємо з 1 000, а не з 0: ``needed=0`` — це ОКРЕМИЙ випадок
        «потребу не міряли», і він навмисно обережний (типове число), а не
        точка на кривій.
        """
        sizes = [1_000, 4_000, 8_000, 16_000, 32_000, 64_000, 120_000]
        budgets = [
            context_budget.working_window(needed=want, window=WINDOW,
                                          fixed=12_836, room=6_144)
            for want in sizes
        ]
        for want, left, right in zip(sizes, budgets, budgets[1:]):
            self.assertLessEqual(left, right,
                                 f"бюджет зменшився при зростанні потреби: "
                                 f"{budgets}")

    def test_budget_pays_for_answer_and_margin(self) -> None:
        """Бюджет мусить бути БІЛЬШИМ за потребу: відповідь теж кудись іде."""
        for want in (4_000, 12_000, 30_000):
            with self.subTest(needed=want):
                budget = context_budget.working_window(
                    needed=want, window=WINDOW, fixed=8_000, room=2_048)
                self.assertGreater(
                    budget, want,
                    f"потреба {want} → бюджет {budget}: моделі не лишиться "
                    f"місця на відповідь")

    def test_never_above_window(self) -> None:
        """Вікно — стеля: більше за нього не буває за жодної потреби."""
        for window in (2_048, 8_192, 16_384, 65_536):
            with self.subTest(window=window):
                budget = context_budget.working_window(
                    needed=window * 4, window=window, fixed=1_000, room=1_024)
                self.assertLessEqual(budget, max(window,
                                                 context_budget.MIN_USABLE_WINDOW))

    def test_ceiling_from_settings_is_respected(self) -> None:
        """Стеля людини (``working_context``) сильніша за потребу."""
        budget = context_budget.working_window(
            needed=100_000, window=WINDOW, fixed=12_000, room=24_576,
            ceiling=32_768)
        self.assertLessEqual(budget, 32_768)

    def test_unknown_need_is_cautious(self) -> None:
        """Потреба невідома — обережне типове число, а не все вікно."""
        budget = context_budget.working_window(needed=0, window=WINDOW)
        self.assertLessEqual(budget, context_budget.WORKING_WINDOW)
        self.assertGreaterEqual(budget, context_budget.MIN_USABLE_WINDOW)

    def test_max_mode_takes_whole_window(self) -> None:
        """Режим ``max`` — «хочу все»: вікно цілком, стеля знята."""
        budget = context_budget.working_window(
            needed=1_000, window=WINDOW, mode="max")
        self.assertEqual(budget, WINDOW)


class TestLatencyEstimate(unittest.TestCase):
    """Оцінка часу — з ЗАМІРЯНИХ точок, а не вигадана."""

    def test_matches_measured_points(self) -> None:
        for tokens, seconds in context_budget.LATENCY_TABLE:
            with self.subTest(tokens=tokens):
                self.assertAlmostEqual(
                    context_budget.latency_seconds(tokens), seconds, delta=0.2,
                    msg=f"{tokens} токенів мало б дати ~{seconds} с")

    def test_grows_with_size(self) -> None:
        previous = -1.0
        for size in (1_000, 4_000, 8_000, 16_000, 32_000, 64_000, 120_000):
            value = context_budget.latency_seconds(size)
            self.assertGreater(value, previous, f"час не зріс на {size}")
            previous = value


class TestBudgetPlanKeepsHistory(unittest.TestCase):
    """Вузький робочий бюджет не має лишати історію НУЛЕМ.

    Живий регрес 21.11.2026: при 91 інструменті схеми зайняли 11 520
    токенів, і на історію лишалось нуль — відповіді перестали надходити.
    """

    def test_history_survives_narrow_budget(self) -> None:
        budget = context_budget.plan(
            WINDOW, system_tokens=3_190, tools_tokens=9_646,
            needed=20_000, room=6_144)
        self.assertGreater(budget.history, 0, budget.text())
        self.assertGreater(budget.payload, 0, budget.text())

    def test_parts_never_exceed_working_budget(self) -> None:
        for need in (2_000, 8_000, 20_000, 60_000):
            with self.subTest(needed=need):
                budget = context_budget.plan(
                    WINDOW, system_tokens=3_190, tools_tokens=9_646,
                    needed=need, room=6_144)
                total = (budget.answer + budget.history + budget.tools
                         + budget.system + budget.safety + budget.payload)
                self.assertLessEqual(total, budget.effective + 1,
                                     f"{budget.text()}: частини більші за "
                                     f"робочий бюджет")


class TestPerRequestInAgent(unittest.TestCase):
    """Агент СПРАВДІ перераховує бюджет під кожен запит."""

    def test_cheap_request_is_cheaper_than_deep_one(self) -> None:
        runner = make_runner()
        cheap = self._budget_for(runner, "привіт")
        deep = self._budget_for(runner, "продовж роботу над проєктом")
        self.assertLess(
            cheap.working, deep.working,
            f"«привіт» ({cheap.working}) і «продовж» ({deep.working}) "
            f"отримали однаковий бюджет — автовизначення не працює")

    def test_budget_within_window_and_at_least_minimum(self) -> None:
        runner = make_runner()
        budget = self._budget_for(runner, "виправ баг у agent.py")
        self.assertLessEqual(budget.working, budget.window)
        self.assertGreaterEqual(budget.working,
                                context_budget.MIN_USABLE_WINDOW)

    def test_history_growth_raises_budget(self) -> None:
        """Більше даних у сесії — більший бюджет: це і є «за потребою»."""
        runner = make_runner()
        small = self._budget_for(runner, "продовж роботу")
        for index in range(3):
            runner.session.messages.append(
                {"role": "tool", "tool_call_id": f"c{index}",
                 "name": "read_file", "content": "тіло файлу " * 4_000})
        runner._context_plan_cache = None
        large = runner.refresh_budget_for_request(with_tools=True)
        self.assertGreater(large.working, small.working,
                           f"історія виросла, а бюджет — ні: "
                           f"{small.text()} → {large.text()}")

    def test_ceiling_from_settings_limits_agent(self) -> None:
        runner = make_runner()
        runner.agent_settings.working_context = 24_576
        runner.session.add_user("продовж роботу")
        runner._context_plan_cache = None
        budget = runner.refresh_budget_for_request(with_tools=True)
        self.assertLessEqual(budget.working, 24_576, budget.text())

    def test_full_mode_uses_whole_window(self) -> None:
        runner = make_runner()
        runner.agent_settings.context_mode = "full"
        runner.session.add_user("привіт")
        runner._context_plan_cache = None
        budget = runner.refresh_budget_for_request(with_tools=True)
        self.assertEqual(budget.working, WINDOW, budget.text())

    def test_chat_without_tools_ignores_schema_weight(self) -> None:
        """У розмові схеми НЕ надсилаються — їхня вага не має роздувати план."""
        runner = make_runner()
        with_tools = self._budget_for(runner, "привіт", with_tools=True)
        plain = self._budget_for(runner, "привіт", with_tools=False)
        self.assertLess(plain.working, with_tools.working,
                        f"схеми враховані в розмові: {plain.text()}")

    def test_unknown_window_keeps_previous_budget(self) -> None:
        """Вікно невідоме — не падаємо й не вигадуємо: лишаємо як було."""
        runner = make_runner()
        before = runner._context_budget
        runner.session.context_limit = 0
        runner._context_window = None
        budget = runner.refresh_budget_for_request()
        self.assertIs(budget, before,
                      "без вікна мусить лишитись попередній бюджет")

    @staticmethod
    def _budget_for(runner: AgentRunner, text: str,
                    *, with_tools: bool = True):
        runner.session.messages.clear()
        runner.session.add_user(text)
        runner._context_plan_cache = None
        return runner.refresh_budget_for_request(with_tools=with_tools)


class TestAgentSessionUsesWorkingBudget(unittest.TestCase):
    """Стискання історії рахується від РОБОЧОГО бюджету, а не від вікна.

    Регрес, який це закриває: «один результат інструмента не більший за
    чверть вікна» при вікні 131 072 давало 32 768 токенів на ОДИН
    результат — і жоден план не тримався.
    """

    def test_tool_result_clipped_to_working_budget(self) -> None:
        runner = make_runner()
        runner.session.add_user("прочитай файл")
        runner._context_plan_cache = None
        budget = runner.refresh_budget_for_request()
        runner.session._context_budget = budget
        session = runner.session
        session.messages.append({"role": "tool", "tool_call_id": "c1",
                                 "name": "read_file",
                                 "content": "x" * 4_000_000})
        session._clip_tool_results()
        body = str(session.messages[-1]["content"])
        # Чверть робочого бюджету в символах (≈3 символи на токен) плюс хвіст.
        ceiling = int(budget.working * 0.25 * 3) + 200
        self.assertLessEqual(
            len(body), ceiling,
            f"результат {len(body)} символів при робочому бюджеті "
            f"{budget.working} — стискання рахує від вікна, а не від плану")

    def test_trim_fits_session_into_working_budget(self) -> None:
        runner = make_runner()
        runner.session.add_user("виправ баг")
        for index in range(24):
            runner.session.messages.append(
                {"role": "tool", "tool_call_id": f"c{index}",
                 "name": "read_file", "content": "великий файл " * 6_000})
        runner._context_plan_cache = None
        budget = runner.refresh_budget_for_request()
        runner.session._context_budget = budget
        runner.session.trim()
        self.assertLessEqual(
            runner.session._estimate_tokens(), budget.effective,
            f"сесія не влізла у робочий бюджет {budget.text()}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
