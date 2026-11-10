"""Тести розуміння людської мови простою мовою.

Головна вимога: агент має розуміти фрази так, як їх каже замовник —
без назв інструментів, шляхів і команд, часто з іншими дієсловами й
відмінками. І НЕ має вважати дією звичайну балачку.

Запуск: python -m unittest tests.test_plain_language -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import task_plan as tp  # noqa: E402
from blackchpok_ide import tool_router  # noqa: E402


class TestDesirePlusArtifact(unittest.TestCase):
    """«Хочу», «потрібен», «треба» + предмет розробки = завдання.

    Людина не каже «створи файл». Вона каже «мені потрібен калькулятор».
    Без цього правила такі фрази вважались балачкою.
    """

    def test_want_object(self) -> None:
        for phrase in ("хочу гру змійку",
                       "мені потрібен скрипт для бекапу",
                       "треба щоб був сайт з меню",
                       "потрібна програма для обліку"):
            info = tp.understand(phrase)
            self.assertTrue(info.is_action, phrase)
            self.assertIn(tp.CREATE, info.intents, phrase)

    def test_no_verb_at_all(self) -> None:
        """Навіть без дієслова: лише бажання й предмет."""
        info = tp.understand("мені калькулятор")
        self.assertTrue(info.is_action, info.intents)

    def test_talk_stays_talk(self) -> None:
        """Балачка без предмета розробки не стає завданням."""
        for phrase in ("привіт, як справи", "дякую за допомогу",
                       "як зробити чай", "що таке рекурсія",
                       "скажи щось цікаве"):
            info = tp.understand(phrase)
            self.assertFalse(info.is_action, f"{phrase} → {info.intents}")


class TestHouseholdVerbs(unittest.TestCase):
    """Побутові дієслова правки й створення."""

    def test_edit_verbs(self) -> None:
        for phrase in ("поміняй колір фону на темний",
                       "перероби меню під мобільні",
                       "прибери зайвий рядок",
                       "збільш шрифт"):
            info = tp.understand(phrase)
            self.assertIn(tp.EDIT, info.intents, f"{phrase} → {info.intents}")

    def test_create_verbs(self) -> None:
        for phrase in ("зроби мені калькулятор",
                       "напиши програму яка рахує площу",
                       "накидай простий бот",
                       "згенеруй скрипт"):
            info = tp.understand(phrase)
            self.assertIn(tp.CREATE, info.intents, f"{phrase} → {info.intents}")

    def test_comparative_is_edit_not_create(self) -> None:
        """«Зроби шрифт більшим» — правка, а не створення файлу."""
        info = tp.understand("зроби шрифт більшим")
        self.assertIn(tp.EDIT, info.intents, info.intents)
        self.assertEqual(info.primary, tp.EDIT, info.intents)


class TestComplaints(unittest.TestCase):
    """Скарга на несправність — це завдання «полагодь»."""

    def test_complaint_is_debug(self) -> None:
        for phrase in ("воно не працює, допоможи",
                       "програма падає при запуску",
                       "вилітає помилка коли натискаю",
                       "чомусь нічого не відображається",
                       "зламалось після моїх змін",
                       "глючить кнопка"):
            info = tp.understand(phrase)
            self.assertIn(tp.DEBUG, info.intents, f"{phrase} → {info.intents}")

    def test_complaint_has_tools(self) -> None:
        tools = tp.tools_for_stage("воно не працює")
        self.assertIn("read_file", tools)
        self.assertIn("run_command", tools)


class TestCodeQuestions(unittest.TestCase):
    """Питання про КОД — це доручення подивитись проєкт."""

    def test_code_question_is_action(self) -> None:
        for phrase in ("що в цьому файлі",
                       "де використовується ця змінна",
                       "що робить ця функція"):
            info = tp.understand(phrase)
            self.assertTrue(info.is_action, f"{phrase} → {info.intents}")

    def test_world_question_is_not_action(self) -> None:
        """Питання про світ — балачка, а не читання проєкту."""
        for phrase in ("як зробити чай", "що таке рекурсія"):
            self.assertFalse(tp.understand(phrase).is_action, phrase)

    def test_router_reads_open_file(self) -> None:
        """«Що в цьому файлі» — роутер має дати читання без шляху."""
        hints = tool_router.confident("що в цьому файлі")
        self.assertTrue(hints, "роутер не розпізнав намір")
        self.assertEqual(hints[0].tool, "read_file")
        self.assertTrue(hints[0].is_confident)


class TestMultipleWorks(unittest.TestCase):
    """Кілька робіт в одному реченні — виконуються всі."""

    def test_two_intents(self) -> None:
        info = tp.understand("гра падає, виправ і запусти знову")
        self.assertIn(tp.DEBUG, info.intents)

    def test_bigger_task_detected(self) -> None:
        brief = ("зроби сайт з реєстрацією і базою даних, додай особистий "
                 "кабінет і перевір що все зберігається")
        info = tp.understand(brief)
        self.assertTrue(info.is_big, f"вага {info.weight}")


class TestToolsMatchIntent(unittest.TestCase):
    """Кожен простий намір дає доречні інструменти."""

    def test_tools(self) -> None:
        cases = {
            "зроби калькулятор": "write_file",
            "запусти": "run_command",
            "що в цьому файлі": "read_file",
            "де використовується пароль": "search_text",
            "перевір чи все добре": "run_command",
        }
        for phrase, tool in cases.items():
            tools = tp.tools_for_stage(phrase)
            self.assertIn(tool, tools, f"{phrase} → {tools}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
