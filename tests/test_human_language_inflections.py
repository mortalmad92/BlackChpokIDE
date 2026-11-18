"""Людська мова: відмінки не мусять вибивати агента з робочого шляху.

Заміряно на живій фразі: «чому не працює запуск тестів» не мала ЖОДНОГО
маркера правила доказів — «тестів» ≠ «тест», «запуск» ≠ «запусти». Агент
вважав це розмовою й відповідав словами замість того, щоб перевірити
проєкт. Тобто на природній людській мові правило не діяло.

Друга половина тесту — ЗАХИСТ від хибних спрацьовувань. Наївне стебло
«порт» ловить «портал» і «портфоліо», а «тек» — «текст» і «течу»: агент
біг перевіряти проєкт на прохання «створи портал новин».

Запуск:  python -m unittest tests.test_human_language_inflections -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import evidence, intent_engine  # noqa: E402

#: Фрази, на яких правило доказів МУСИТЬ спрацьовувати (є факти).
NEEDS_FACTS = (
    "чому не працює запуск тестів",
    "які тести пройшли",
    "запусти тести",
    "тести падають",
    "покажи конфігурацію",
    "що в налаштуваннях",
    "перевір вміст файлу",
    "перелічи файли",
    "який стан сервера",
    "на якому порту сервер",
    "скільки файлів у теці",
    "що в папці",
    "покажи теку",
    "скільки файлів у проєкті",
    "прочитай main.py",
    "глянь які файли в проєкті",
)

#: Фрази, на яких НЕ МУСИТЬ (це прохання або розмова, не перевірка).
NEEDS_NO_FACTS = (
    "привіт",
    "дякую",
    "як справи?",
    "хто ти?",
    "розкажи про себе",
    "зроби мені спорт-сайт",
    "створи портал новин",
    "портал-блок з іграми",
    "напиши текст пісні",
    "текст пісні про літо",
    "напиши вірш про течу",
    "зроби мені портфоліо-сайт",
    "зроби красивий дизайн",
)


class TestInflectionsNeedFacts(unittest.TestCase):
    """Відмінки мусять вмикати правило доказів."""

    def test_inflected_forms_ask_for_facts(self) -> None:
        for text in NEEDS_FACTS:
            with self.subTest(text=text):
                self.assertTrue(evidence.needs_tools_for(text),
                                f"«{text}» не вимагає фактів — агент "
                                f"відповість словами замість перевірки")


class TestNoFalsePositives(unittest.TestCase):
    """Виправлення не мусить перетворювати розмову на перевірку."""

    def test_talk_and_requests_stay_out(self) -> None:
        for text in NEEDS_NO_FACTS:
            with self.subTest(text=text):
                self.assertFalse(evidence.needs_tools_for(text),
                                 f"«{text}» помилково вимагає фактів")

    def test_false_friend_words_are_guarded(self) -> None:
        """«портал», «портфоліо», «текст», «теча» — не «порт» і не «тека»."""
        for word in ("портал", "портфоліо", "текст", "теча", "течу"):
            with self.subTest(word=word):
                self.assertFalse(evidence.needs_tools_for(f"зроби {word}"))

    def test_exact_forms_still_work(self) -> None:
        """А справжні «порту»/«теці» мусять працювати."""
        for text in ("на якому порту сервер", "що в теці"):
            with self.subTest(text=text):
                self.assertTrue(evidence.needs_tools_for(text))


class TestAgentTakesTheWorkingPath(unittest.TestCase):
    """Той самий критерій, що й у ``AgentRunner.run``.

    1. факти → робочий шлях;
    2. інакше розмова (converse/explain без дії, файлів і примусових фактів);
    3. інакше — робота.
    """

    def _path(self, text: str) -> str:
        frame = intent_engine.frame(text)
        kind = str(getattr(frame, "intent_type", "") or "")
        forced = evidence.needs_tools_for(text)
        small_talk = (
            kind in ("converse", "explain")
            and not bool(getattr(frame, "actionable", False))
            and not list(getattr(frame, "referenced_files", ()) or ())
            and len(text) <= 200
            and not forced
        )
        return "talk" if (small_talk and not forced) else "work"

    def test_requests_go_the_working_path(self) -> None:
        for text in ("глянь які файли в проєкті", "покажи що в теці",
                     "прочитай main.py", "створи файл app.py",
                     "додай у calc.py множення", "виправ помилку в server.py",
                     "чому не працює запуск тестів", "запусти тести",
                     "зроби сайт-блог на Flask", "перейменуй функцію foo на bar",
                     "видали файл old.py", "порахуй скільки файлів .py"):
            with self.subTest(text=text):
                self.assertEqual(self._path(text), "work")

    def test_chat_stays_a_conversation(self) -> None:
        for text in ("привіт", "дякую", "як справи?", "хто ти?",
                     "розкажи про себе"):
            with self.subTest(text=text):
                self.assertEqual(self._path(text), "talk")


if __name__ == "__main__":
    unittest.main()
