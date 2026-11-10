"""Тести логіки режиму глибокого аналізу (без tkinter).

Перевіряємо рішення, які легко зламати: коли вмикати режим, як групуються
кроки, як рухаються стани задач і що буде при збоях.

Запуск: python -m unittest tests.test_deep_mode -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import deep_mode as dm  # noqa: E402


class TestWhenToEnable(unittest.TestCase):
    """Режим має вмикатись на складних задачах і НЕ вмикатись на дрібних."""

    def test_short_request_stays_simple(self) -> None:
        for text in ("запусти тести", "відкрий main.py", "що це за файл?"):
            self.assertFalse(dm.wants_deep_plan(text), text)

    def test_explicit_plan_markers(self) -> None:
        for text in ("/план зроби сайт", "/plan refactor", "склади план роботи",
                     "детально проаналізуй проєкт"):
            self.assertTrue(dm.wants_deep_plan(text), text)

    def test_marker_is_case_insensitive(self) -> None:
        self.assertTrue(dm.wants_deep_plan("/ПЛАН зроби сайт"))

    def test_many_demands_trigger(self) -> None:
        text = ("Потрібно створити новий екран. Додай перевірку полів. "
                "Виправ помилки валідації. Перевір збереження даних.")
        self.assertTrue(dm.wants_deep_plan(text))

    def test_real_task_from_live_run_triggers(self) -> None:
        """Справжнє завдання користувача має вмикати режим.

        Регресія з живого прогону на локальній моделі: цей текст (184
        символи, 3 речення, 2 дієслова-вимоги) НЕ проходив старий поріг
        «4+ речення й 3+ вимоги», і режим не вмикався на задачі, для якої
        його й зробили.
        """
        task = ("Потрібно обєднати вкладки чати і агенти в одне. Зроби щоб були "
                "іконки закриття чатів біля кожного чату та архівування. Зроби "
                "адаптивний розмір чату і відповідей в залежності до екрану.")
        self.assertGreaterEqual(len(task), dm.SUBSTANTIAL_CHARS)
        self.assertTrue(dm.wants_deep_plan(task), "режим має вмикатись")

    def test_short_but_meaningful_still_simple(self) -> None:
        """Короткий текст не вмикає режим, навіть якщо там є «зроби»."""
        self.assertFalse(dm.wants_deep_plan("зроби рефакторинг"))
        self.assertFalse(dm.wants_deep_plan("треба виправити баг"))

    def test_single_sentence_does_not_trigger(self) -> None:
        text = "Будь ласка зроби так щоб у чаті було видно іконки закриття і все інше."
        self.assertLess(len(text), 120)
        self.assertFalse(dm.wants_deep_plan(text))

    def test_many_sentences_without_demands_do_not_trigger(self) -> None:
        """Опис без прохань — не привід будувати план."""
        text = ("Це модуль. Він має класи. Класи описують дані. "
                "Дані зберігаються у файлі.")
        self.assertFalse(dm.wants_deep_plan(text))

    def test_empty_text(self) -> None:
        self.assertFalse(dm.wants_deep_plan(""))
        self.assertFalse(dm.wants_deep_plan("   "))


class TestGrouping(unittest.TestCase):
    """Групування кроків за категоріями."""

    def test_read_and_search_group_together(self) -> None:
        title = dm.group_title(["read_file", "search_text"])
        self.assertIn("Читання файлів", title)
        self.assertIn("Пошук коду", title)

    def test_single_category(self) -> None:
        self.assertEqual(dm.group_title(["read_file"]), "Читання файлів")

    def test_commands_category(self) -> None:
        self.assertIn("Виконання команд", dm.group_title(["run_command"]))

    def test_edits_category(self) -> None:
        self.assertIn("Зміна файлів", dm.group_title(["edit_file", "write_file"]))

    def test_unknown_tool_falls_back(self) -> None:
        self.assertEqual(dm.category_of("щось_невідоме"), dm.CAT_OTHER)
        self.assertEqual(dm.group_title(["щось_невідоме"]), dm.CAT_LABELS[dm.CAT_OTHER])

    def test_router_prefix_is_stripped(self) -> None:
        self.assertEqual(dm.category_of("router:search_web"), dm.CAT_OTHER)
        self.assertEqual(dm.category_of("mcp:read_file"), dm.CAT_READ)

    def test_order_is_stable(self) -> None:
        """Порядок категорій не залежить від порядку інструментів."""
        first = dm.group_title(["run_command", "read_file"])
        second = dm.group_title(["read_file", "run_command"])
        self.assertEqual(first, second)
        self.assertLess(first.index("Читання"), first.index("Виконання"))


class TestSession(unittest.TestCase):
    """Стан сеансу: план, стани задач, підсумок."""

    def test_starts_in_analysis(self) -> None:
        session = dm.DeepSession(goal="мета")
        self.assertEqual(session.phase, dm.PHASE_ANALYSIS)
        self.assertFalse(session.done)

    def test_set_tasks_switches_to_plan(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["a", "b"])
        self.assertEqual(session.phase, dm.PHASE_PLAN)
        self.assertTrue(session.plan_shown)
        self.assertEqual(len(session.tasks), 2)

    def test_empty_plan_keeps_analysis(self) -> None:
        session = dm.DeepSession()
        session.set_tasks([])
        self.assertEqual(session.phase, dm.PHASE_ANALYSIS)
        self.assertFalse(session.plan_shown)

    def test_first_task_starts(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["перша", "друга"])
        task = session.start_work()
        self.assertIsNotNone(task)
        self.assertEqual(task.text, "перша")
        self.assertEqual(task.state, dm.STATE_RUNNING)
        self.assertEqual(session.phase, dm.PHASE_EXECUTE)

    def test_cannot_start_twice(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["єдина"])
        self.assertIsNotNone(session.start_work())
        self.assertIsNone(session.start_work(), "друга задача не має стартувати")

    def test_summary_text(self) -> None:
        session = dm.DeepSession()
        session.set_tasks([f"задача {i}" for i in range(8)])
        session.start_work()
        text = session.summary()
        self.assertIn("1 у процесі", text)
        self.assertIn("7 в очікуванні", text)

    def test_marks(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["a"])
        self.assertEqual(session.tasks[0].mark, "○")
        session.start_work()
        self.assertEqual(session.tasks[0].mark, "◐")
        session.mark(0, dm.STATE_DONE)
        self.assertEqual(session.tasks[0].mark, "●")

    def test_finish_ok_closes_all(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["a", "b", "c"])
        session.start_work()
        session.finish(ok=True)
        self.assertEqual(session.phase, dm.PHASE_DONE)
        self.assertTrue(all(t.state == dm.STATE_DONE for t in session.tasks))
        self.assertTrue(session.done)

    def test_finish_failure_marks_current(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["a", "b"])
        session.start_work()
        session.finish(ok=False)
        self.assertEqual(session.tasks[0].state, dm.STATE_FAILED)
        self.assertEqual(session.tasks[1].state, dm.STATE_PENDING)

    def test_elapsed_grows(self) -> None:
        session = dm.DeepSession()
        session.started_at -= 125
        self.assertGreaterEqual(session.elapsed, 120)
        self.assertIn("м", session.elapsed_text)

    def test_mark_unknown_index_is_safe(self) -> None:
        session = dm.DeepSession()
        session.set_tasks(["a"])
        self.assertIsNone(session.mark(99, dm.STATE_DONE))


class TestTasks(unittest.TestCase):
    """Побудова задач із рядків плану."""

    def test_strips_markers(self) -> None:
        tasks = dm.build_tasks(["- перша", "2. друга", "• третя", "* четверта"])
        self.assertEqual([t.text for t in tasks], ["перша", "друга", "третя", "четверта"])

    def test_skips_empty(self) -> None:
        tasks = dm.build_tasks(["", "   ", "справжня"])
        self.assertEqual(len(tasks), 1)

    def test_indexes_are_sequential(self) -> None:
        tasks = dm.build_tasks(["a", "b", "c"])
        self.assertEqual([t.index for t in tasks], [0, 1, 2])

    def test_limit_respected(self) -> None:
        tasks = dm.build_tasks([f"крок {i}" for i in range(100)])
        self.assertLessEqual(len(tasks), dm.MAX_TASKS)

    def test_long_task_is_trimmed(self) -> None:
        tasks = dm.build_tasks(["дуже довгий текст " * 40])
        self.assertLessEqual(len(tasks[0].text), 200)


class TestTimeFormat(unittest.TestCase):
    """Формати часу."""

    def test_thinking_time_seconds(self) -> None:
        self.assertEqual(dm.thinking_time(7), "7с")

    def test_thinking_time_minutes(self) -> None:
        self.assertEqual(dm.thinking_time(420), "7м 0с")

    def test_thinking_time_hours(self) -> None:
        self.assertEqual(dm.thinking_time(3661), "1г 1м 1с")

    def test_negative_is_zero(self) -> None:
        self.assertEqual(dm.thinking_time(-5), "0с")

    def test_human_time(self) -> None:
        self.assertEqual(dm.human_time(45), "45 с")
        self.assertEqual(dm.human_time(90), "1 хв 30 с")


class TestGoal(unittest.TestCase):
    """Блок «Поточна ціль»."""

    def test_goal_strips_politeness(self) -> None:
        self.assertEqual(dm.goal_from("Будь ласка, зроби сайт"), "зроби сайт")

    def test_goal_is_trimmed(self) -> None:
        self.assertLessEqual(len(dm.goal_from("довго " * 200)), 240)

    def test_goals_text_short(self) -> None:
        self.assertLessEqual(len(dm.goals_text("довго " * 100)), 96)

    def test_empty_goal(self) -> None:
        self.assertEqual(dm.goal_from("   "), "")


class TestPlanTask(unittest.TestCase):
    """Складання плану моделлю."""

    def test_empty_goal_returns_error(self) -> None:
        steps, error = dm.plan_tasks("", None)
        self.assertEqual(steps, [])
        self.assertTrue(error)

    def test_model_error_is_reported(self) -> None:
        from blackchpok_ide.llm_client import LLMError

        class FakeClient:
            def __init__(self, *_a, **_k) -> None:
                pass

            def chat(self, *_a, **_k):
                raise LLMError("немає зв'язку")

        with mock.patch("blackchpok_ide.llm_client.LLMClient", FakeClient):
            steps, error = dm.plan_tasks("зроби сайт", mock.Mock(base_url="u", model="m",
                                                                api_key="k"))
        self.assertEqual(steps, [])
        self.assertIn("зв'язку", error)

    def test_successful_plan(self) -> None:
        class FakeResult:
            content = '["перший крок", "другий крок"]'

        class FakeClient:
            def __init__(self, *_a, **_k) -> None:
                pass

            def chat(self, *_a, **_k):
                return FakeResult()

        with mock.patch("blackchpok_ide.llm_client.LLMClient", FakeClient):
            steps, error = dm.plan_tasks("зроби сайт", mock.Mock(base_url="u", model="m",
                                                                api_key="k"))
        self.assertEqual(steps, ["перший крок", "другий крок"])
        self.assertEqual(error, "")

    def test_unexpected_exception_is_contained(self) -> None:
        class FakeClient:
            def __init__(self, *_a, **_k) -> None:
                raise RuntimeError("навмисно")

        with mock.patch("blackchpok_ide.llm_client.LLMClient", FakeClient):
            steps, error = dm.plan_tasks("зроби сайт", mock.Mock())
        self.assertEqual(steps, [])
        self.assertIn("навмисно", error)


class TestProjectContext(unittest.TestCase):
    """Контекст проєкту для плану.

    Регресія з живого прогону: без контексту Qwen2.5-Coder 14B склала план
    «додати HTML-структуру, CSS-стилі, JavaScript-код» для Python/Tkinter
    проєкту. З контекстом план став про реальні файли.
    """

    def test_context_mentions_language(self) -> None:
        context = dm.project_context(ROOT)
        self.assertIn("Python", context)

    def test_context_lists_real_files(self) -> None:
        context = dm.project_context(ROOT)
        self.assertIn("chat_panel.py", context)

    def test_context_skips_dependencies(self) -> None:
        context = dm.project_context(ROOT)
        self.assertNotIn(".venv/", context)
        self.assertNotIn("node_modules/", context)

    def test_context_none_is_empty(self) -> None:
        self.assertEqual(dm.project_context(None), "")

    def test_context_missing_folder_is_empty(self) -> None:
        self.assertEqual(dm.project_context(ROOT / "немає-такої"), "")

    def test_prompt_head_forbids_other_stack(self) -> None:
        self.assertIn("Python", dm.PLAN_CONTEXT_HEAD)
        self.assertIn("HTML/CSS/JS", dm.PLAN_CONTEXT_HEAD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
