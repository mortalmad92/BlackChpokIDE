"""Тести сценаріїв поведінки: набір із tools/eval_scenarios.py.

Сценарії там описані як ДАНІ (фраза → очікуваний намір і дії). Тут вони
стають регресійними тестами: якщо правило розуміння зламається, це буде
видно не «на око», а падінням конкретного сценарію з назвою.

Запуск: python -m unittest tests.test_agent_scenarios -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import eval_scenarios  # noqa: E402


class TestScenarios(unittest.TestCase):
    """Кожен сценарій виконується окремим тестом із людською назвою."""


def _make_test(scenario: eval_scenarios.Scenario):
    def test(self: unittest.TestCase) -> None:
        result = eval_scenarios.evaluate_intent(scenario)
        self.assertTrue(result["passed"],
                        f"{scenario.name}: " + "; ".join(result["problems"]))

    test.__doc__ = f"[{scenario.category}] {scenario.message}"
    return test


#: Реєструємо по тесту на кожен сценарій — тоді звіт unittest показує,
#: ЯКИЙ саме випадок зламався, а не «щось у наборі».
for _scenario in eval_scenarios.SCENARIOS:
    _name = "test_" + _scenario.category.lower() + "_" + str(
        eval_scenarios.SCENARIOS.index(_scenario) + 1).zfill(2)
    setattr(TestScenarios, _name, _make_test(_scenario))


class TestSuiteHealth(unittest.TestCase):
    """Сам набір має бути осмисленим і покривати всі категорії."""

    def test_all_categories_present(self) -> None:
        found = {item.category for item in eval_scenarios.SCENARIOS}
        self.assertEqual(found, set(eval_scenarios.CATEGORIES),
                         "кожна категорія мусить мати хоч один сценарій")

    def test_scenarios_have_names(self) -> None:
        names = [item.name for item in eval_scenarios.SCENARIOS]
        self.assertEqual(len(names), len(set(names)), "назви мають бути унікальні")

    def test_summary_report(self) -> None:
        summary = eval_scenarios.run_all(verbose=False)
        self.assertEqual(summary["total"], len(eval_scenarios.SCENARIOS))
        self.assertEqual(summary["passed"], summary["total"],
                         "усі сценарії мають проходити")

    def test_spec_report_mentions_all_tools(self) -> None:
        """Кількість не хардкодимо: вона змінюється разом зі схемами."""
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        report = eval_scenarios.spec_report()
        self.assertIn(f"Інструментів описано: {len(TOOL_SCHEMAS)}", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
