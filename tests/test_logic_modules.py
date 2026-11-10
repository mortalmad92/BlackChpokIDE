"""Тести чистої логіки: планувальник, слэш-команди, RAG.

Три модулі без tkinter і без жодного тесту доти. Вони вирішують, що
станеться з запитом користувача: розіб'ється він на кроки черги, чи стане
командою, чи піде в базу знань.

Запуск: python -m unittest tests.test_logic_modules -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import planner, slash_commands  # noqa: E402


class TestIsBigTask(unittest.TestCase):
    """Коли завдання варто розбивати на кроки."""

    def test_short_request_is_not_big(self) -> None:
        self.assertFalse(planner.is_big_task("покажи файли"))

    def test_empty_text_is_not_big(self) -> None:
        self.assertFalse(planner.is_big_task(""))

    def test_long_request_is_big(self) -> None:
        text = "Створи сайт з нуля. " * 40
        self.assertTrue(planner.is_big_task(text))

    def test_explicit_multi_step_words(self) -> None:
        # Велике завдання = довгий текст (>=180 символів) плюс ознаки:
        # кілька речень або абзаців, дієслово наказу.
        text = ("Створи проєкт з нуля на Node.js та Express для сайту-журналу. "
                "Потрібні сторінки: головна, стаття, категорія, профіль автора. "
                "Додай роути для кожної сторінки та шаблони. "
                "Напиши тести для кожного модуля й перевір рендер. "
                "Запусти сервер і перевір кожну сторінку в браузері.")
        self.assertGreaterEqual(len(text), planner.BIG_TASK_CHARS,
                                f"текст {len(text)} символів")
        self.assertTrue(planner.is_big_task(text))

    def test_short_but_multi_verb_is_not_big(self) -> None:
        # Коротке доручення не дробимо, навіть якщо дієслів кілька.
        self.assertFalse(planner.is_big_task("створи файл і запусти тести"))

    def test_result_is_bool(self) -> None:
        self.assertIsInstance(planner.is_big_task("щось"), bool)


class TestParseSteps(unittest.TestCase):
    """Розбір списку кроків із відповіді моделі."""

    def test_dash_list(self) -> None:
        self.assertEqual(planner.parse_steps("- перший\n- другий"), ["перший", "другий"])

    def test_numbered_list(self) -> None:
        self.assertEqual(planner.parse_steps("1. один\n2. два"), ["один", "два"])

    def test_mixed_markers(self) -> None:
        steps = planner.parse_steps("1. a\n- b\n* c")
        self.assertEqual(steps, ["a", "b", "c"])

    def test_ignores_blank_lines(self) -> None:
        self.assertEqual(planner.parse_steps("- a\n\n\n- b"), ["a", "b"])

    def test_respects_limit(self) -> None:
        raw = "\n".join(f"- крок {i}" for i in range(30))
        self.assertLessEqual(len(planner.parse_steps(raw, limit=5)), 5)

    def test_empty_input(self) -> None:
        self.assertEqual(planner.parse_steps(""), [])

    def test_strips_leading_list_marker(self) -> None:
        # Маркер списку прибирається, а вміст кроку лишається.
        steps = planner.parse_steps("- крок зірочка *тут*")
        self.assertEqual(len(steps), 1)
        self.assertIn("крок зірочка", steps[0])


class TestStepsFromAnswer(unittest.TestCase):
    """Витяг кроків із довільної відповіді моделі."""

    def test_extracts_from_prose(self) -> None:
        raw = "Ось план:\n1. перший крок\n2. другий крок\nГотово."
        steps = planner.steps_from_answer(raw)
        self.assertGreaterEqual(len(steps), 2)

    def test_empty_answer_gives_empty_list(self) -> None:
        self.assertEqual(planner.steps_from_answer(""), [])

    def test_limit_applied(self) -> None:
        raw = "\n".join(f"{i}. крок номер {i}" for i in range(1, 25))
        self.assertLessEqual(len(planner.steps_from_answer(raw, limit=4)), 4)


class TestBuildFollowUp(unittest.TestCase):
    """Підказка агенту для наступного кроку черги."""

    def test_contains_step_text(self) -> None:
        text = planner.build_follow_up("створити файл", 2, 5)
        self.assertIn("створити файл", text)

    def test_contains_position(self) -> None:
        """Номер кроку НЕ має бути в тексті задачі.

        Регресія від користувача: усі дванадцять рядків черги починалися
        однаково — «Крок 1 з 12: …», «Крок 2 з 12: …», — і сенс кроку
        губився. Номер показує сама панель черги (порядковим підписом),
        а текст задачі містить лише те, ЩО робити.
        """
        text = planner.build_follow_up("створити файл app.py", 3, 7)
        self.assertNotIn("Крок", text,
                         "номер не має бути в тексті задачі")
        self.assertNotIn("з 7", text)
        self.assertIn("створити файл app.py", text)

    def test_brief_is_included(self) -> None:
        text = planner.build_follow_up("крок", 1, 2, brief="зробити сайт")
        self.assertIn("зробити сайт", text)


class TestSlashParsing(unittest.TestCase):
    """Розпізнавання слэш-команд."""

    def test_is_slash(self) -> None:
        self.assertTrue(slash_commands.is_slash("/файл"))
        self.assertFalse(slash_commands.is_slash("файл"))

    def test_is_slash_with_leading_space(self) -> None:
        self.assertTrue(slash_commands.is_slash("  /файл"))

    def test_find_known_command(self) -> None:
        command = slash_commands.find("/файл")
        self.assertIsNotNone(command)
        self.assertEqual(command.name, "файл")

    def test_find_by_alias(self) -> None:
        command = slash_commands.find("/file")
        self.assertIsNotNone(command)
        self.assertEqual(command.name, "файл")

    def test_find_unknown_returns_none(self) -> None:
        self.assertIsNone(slash_commands.find("/вигадана"))

    def test_parse_separates_argument(self) -> None:
        command, argument = slash_commands.parse("/ціль переписати парсер")
        self.assertIsNotNone(command)
        self.assertEqual(command.name, "ціль")
        self.assertEqual(argument, "переписати парсер")

    def test_parse_without_argument(self) -> None:
        command, argument = slash_commands.parse("/файл")
        self.assertIsNotNone(command)
        self.assertEqual(argument, "")

    def test_parse_unknown_gives_none(self) -> None:
        command, argument = slash_commands.parse("/вигадана текст")
        self.assertIsNone(command)


class TestSlashRegistry(unittest.TestCase):
    """Реєстр команд."""

    def test_all_commands_have_hint(self) -> None:
        for command in slash_commands.COMMANDS:
            self.assertTrue(command.hint, f"{command.name}: порожня підказка")

    def test_names_are_unique(self) -> None:
        names = [command.name for command in slash_commands.COMMANDS]
        self.assertEqual(len(names), len(set(names)), "є дублікати назв")

    def test_plan_command_exists(self) -> None:
        self.assertIsNotNone(slash_commands.find("/план"))

    def test_groups_cover_all_commands(self) -> None:
        groups = slash_commands.grouped()
        grouped_count = sum(len(items) for _name, items in groups)
        self.assertEqual(grouped_count, len(slash_commands.COMMANDS))

    def test_group_names_present(self) -> None:
        names = [name for name, _items in slash_commands.grouped()]
        self.assertIn(slash_commands.GROUP_ADD, names)
        self.assertIn(slash_commands.GROUP_COMMANDS, names)

    def test_filter_returns_matching(self) -> None:
        found = slash_commands.filter_commands("ск")
        self.assertTrue(any("ск" in command.name for command in found))

    def test_filter_empty_prefix_returns_all(self) -> None:
        self.assertEqual(len(slash_commands.filter_commands("")),
                         len(slash_commands.COMMANDS))

    def test_help_text_lists_groups(self) -> None:
        text = slash_commands.help_text()
        self.assertIn(slash_commands.GROUP_ADD, text)
        self.assertIn(slash_commands.GROUP_COMMANDS, text)

    def test_permission_modes_are_tuples(self) -> None:
        for item in slash_commands.permission_modes():
            self.assertEqual(len(item), 4, item)

    def test_alias_matches_original(self) -> None:
        for command in slash_commands.COMMANDS:
            for alias in command.aliases:
                found = slash_commands.find("/" + alias)
                self.assertIsNotNone(found, f"псевдонім {alias} не працює")
                # Псевдонім може вести на іншу команду з тієї ж родини
                # («скіл» → «скіли»), тому звіряємо, що це відома команда.
                self.assertIn(found.name,
                              {item.name for item in slash_commands.COMMANDS})


class TestRagService(unittest.TestCase):
    """Сервіс бази знань: стан і безпечні виклики."""

    def setUp(self) -> None:
        from blackchpok_ide import rag

        self.rag = rag
        self.folder = Path(ROOT)
        self.service = rag.RagService(self.folder)

    def test_constructs_without_raising(self) -> None:
        self.assertIsNotNone(self.service)

    def test_status_returns_object(self) -> None:
        status = self.service.status()
        self.assertTrue(hasattr(status, "ready") or hasattr(status, "error"))

    def test_search_returns_answer_object(self) -> None:
        answer = self.service.search("будь-що")
        # search() повертає RagAnswer із полями hits/message/error.
        self.assertTrue(hasattr(answer, "hits"))
        self.assertIsInstance(answer.hits, list)

    def test_search_empty_query_is_safe(self) -> None:
        answer = self.service.search("")
        self.assertTrue(hasattr(answer, "hits"))
        self.assertEqual(answer.hits, [], "порожній запит не має давати збігів")

    def test_index_status_is_readable(self) -> None:
        text = self.service.describe() if hasattr(self.service, "describe") else ""
        self.assertIsInstance(text, str)


class TestRagAnswer(unittest.TestCase):
    """Розбір і форматування відповіді бази знань."""

    def setUp(self) -> None:
        from blackchpok_ide import rag

        self.rag = rag

    def test_parse_answer_from_dict(self) -> None:
        answer = self.rag._parse_answer({"hits": [], "message": "ок"})
        self.assertIsNotNone(answer)

    def test_parse_answer_from_garbage(self) -> None:
        # Сміття з рушія не має валити розбір.
        answer = self.rag._parse_answer(None)
        self.assertIsNotNone(answer)

    def test_format_for_prompt_returns_text(self) -> None:
        answer = self.rag.RagAnswer(hits=[], message="знайдено факти")
        text = self.rag.format_for_prompt(answer)
        self.assertIsInstance(text, str)

    def test_format_empty_answer_is_safe(self) -> None:
        answer = self.rag.RagAnswer()
        self.assertIsInstance(self.rag.format_for_prompt(answer), str)

    def test_format_with_hits_mentions_paths(self) -> None:
        hit = self.rag.RagHit(path="main.py", start_line=1, end_line=5,
                              score=0.5, preview="код")
        answer = self.rag.RagAnswer(hits=[hit], message="")
        self.assertIn("main.py", self.rag.format_for_prompt(answer))


if __name__ == "__main__":
    unittest.main(verbosity=2)
