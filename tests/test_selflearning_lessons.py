"""Тести нових уроків самонавчання: «нуль тестів» і робота вхолосту.

Ці два правила виведені з живого прогону 21.11.2026, коли агент за годину
21 разів запустив ту саму команду тестів і 14 разів перезаписав один
тестовий файл. Обидва випадки давали «правильні» на вигляд кроки, тому
старий код не бачив у них приводу чогось навчатись.

Запуск: python -m unittest tests.test_selflearning_lessons -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import selflearning  # noqa: E402


def advice_text(lessons) -> str:
    return " ".join(lesson.advice for lesson in lessons)


class TestNoTestsLesson(unittest.TestCase):
    """«Ran 0 tests» — це урок про теку запуску, а не про вміст файлу."""

    def test_no_tests_output_teaches_the_fix(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("run_command", True,
                    "python -m unittest discover -v\nexit=5\nRan 0 tests in 0.000s\n"
                    "NO TESTS RAN")],
            goal="запустити тести", ok=True, steps=1, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(lessons, "цикл на «нуль тестів» не став уроком")
        text = advice_text(lessons)
        self.assertIn("-s tests", text)
        self.assertIn("Не переписуй", text)

    def test_no_tests_lesson_mentions_case_insensitively(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("run_command", True, "Ran 0 tests")],
            goal="тести", ok=True, steps=1, max_steps=10)
        self.assertTrue(any("тека запуску" in lesson.advice
                            for lesson in selflearning.extract_lessons(facts)))

    def test_other_command_output_teaches_nothing(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("run_command", True, "python main.py\nвсе добре")],
            goal="запустити", ok=True, steps=1, max_steps=10)
        self.assertEqual(selflearning.extract_lessons(facts), [])

    def test_real_test_failure_is_not_no_tests(self) -> None:
        """Справжній збій тесту — інша причина, і цього уроку бути не має."""
        facts = selflearning.TurnFacts(
            calls=[("run_command", False, "FAILED (failures=2)\nRan 5 tests")],
            goal="тести", ok=False, steps=1, max_steps=10)
        text = advice_text(selflearning.extract_lessons(facts))
        self.assertNotIn("-s tests", text)

    def test_repeat_count_is_kept(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("run_command", True, "Ran 0 tests")] * 3,
            goal="тести", ok=True, steps=3, max_steps=10)
        lesson = next(item for item in selflearning.extract_lessons(facts)
                      if "-s tests" in item.advice)
        self.assertGreaterEqual(lesson.times, 3)


class TestFruitlessRewriteLesson(unittest.TestCase):
    """Перезапис файлу без результату — привід змінити підхід."""

    def test_failed_turn_with_rewrites_is_a_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("write_file", True, "Записано tests/test_sample.py")] * 4,
            changed_files=["tests/test_sample.py"] * 4,
            goal="прибрати позначку", ok=False, steps=4, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        text = advice_text(lessons)
        self.assertIn("САМЕ потрібний рядок", text)

    def test_successful_turn_does_not_get_that_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("write_file", True, "Записано a.py")] * 4,
            changed_files=["a.py"] * 4,
            goal="створити", ok=True, steps=4, max_steps=10)
        text = advice_text(selflearning.extract_lessons(facts))
        self.assertNotIn("САМЕ потрібний рядок", text)

    def test_single_write_is_not_a_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("write_file", True, "Записано a.py")],
            changed_files=["a.py"], goal="створити", ok=False,
            steps=1, max_steps=10)
        text = advice_text(selflearning.extract_lessons(facts))
        self.assertNotIn("САМЕ потрібний рядок", text)


class TestLimitsStillHold(unittest.TestCase):
    """Нові правила не ламають обмеження «не більше WRITE_LIMIT уроків»."""

    def test_lessons_are_capped(self) -> None:
        facts = selflearning.TurnFacts(
            calls=([("run_command", True, "Ran 0 tests")] * 3
                   + [("write_file", True, "Записано f.py")] * 4
                   + [("list_dir", True, "файли")] * 4
                   + [("a", False, "помилка"), ("a", True, "ок")]),
            changed_files=["f.py"] * 4, syntax_repairs=2,
            asked_permission=True, goal="зробити все", ok=False,
            steps=10, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertLessEqual(len(lessons), selflearning.WRITE_LIMIT)
        self.assertTrue(lessons)


if __name__ == "__main__":
    unittest.main(verbosity=2)
