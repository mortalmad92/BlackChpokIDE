"""Самонавчання на трьох джерелах: модель + інтернет + користувач.

Вимога (21.11.2026): «І на таких запитах модель + інтернет + користувач має
агент самонавчатися!»

Що це означає на практиці. Хід агента має ТРИ джерела знання, і кожне
мусить лишати слід у довгостроковій пам'яті:

* **модель** — її власні висновки (уже було: помилки, повтори, синтаксис);
* **інтернет** — свіжі дані за запитом людини (додано);
* **користувач** — його ПОПРАВКА, найцінніший сигнал: він знає свій проєкт.

Запуск: python -m unittest tests.test_learning_sources -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import selflearning  # noqa: E402


class TestCorrectionDetection(unittest.TestCase):
    """Що вважаємо поправкою користувача, а що ні."""

    def test_direct_disagreement_is_correction(self) -> None:
        for phrase in ("ні, це неправильно", "ти помиляєшся",
                       "я не це просив", "треба було інакше",
                       "насправді ціна інша"):
            with self.subTest(phrase=phrase):
                self.assertTrue(selflearning.looks_like_correction(phrase))

    def test_restriction_is_not_correction(self) -> None:
        """«Не чіпай» — це обмеження, а не поправка до відповіді."""
        for phrase in ("не чіпай цей файл", "не треба цього робити",
                       "не змінюй конфіг"):
            with self.subTest(phrase=phrase):
                self.assertFalse(selflearning.looks_like_correction(phrase))

    def test_question_is_not_correction(self) -> None:
        for phrase in ("чому ти так зробив", "навіщо це"):
            with self.subTest(phrase=phrase):
                self.assertFalse(selflearning.looks_like_correction(phrase))

    def test_normal_request_is_not_correction(self) -> None:
        for phrase in ("покажи файли", "зроби сайт", "запусти тести"):
            with self.subTest(phrase=phrase):
                self.assertFalse(selflearning.looks_like_correction(phrase))

    def test_empty_is_not_correction(self) -> None:
        self.assertFalse(selflearning.looks_like_correction(""))
        self.assertFalse(selflearning.looks_like_correction("   "))


class TestCorrectionBecomesLesson(unittest.TestCase):
    """Поправка людини стає ПЕРШИМ уроком ходу."""

    def test_correction_lesson_is_first(self) -> None:
        facts = selflearning.TurnFacts(
            user_corrected=True,
            user_words="ні, правильно брати ціну з CoinGecko",
            goal="дізнатись ціну SOL", ok=True, steps=1, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(lessons)
        self.assertIn("CoinGecko", lessons[0].content())
        self.assertGreaterEqual(lessons[0].confidence, 0.8,
                                "поправка людини має високу впевненість")

    def test_correction_without_words_still_teaches(self) -> None:
        facts = selflearning.TurnFacts(user_corrected=True, ok=True)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(lessons)
        self.assertIn("поправив", lessons[0].content())

    def test_no_correction_no_lesson(self) -> None:
        facts = selflearning.TurnFacts(ok=True, steps=1, max_steps=10)
        self.assertEqual(selflearning.extract_lessons(facts), [])


class TestWebKnowledgeBecomesLesson(unittest.TestCase):
    """Знайдене в інтернеті стає уроком «це питання вирішує пошук»."""

    def test_web_digest_becomes_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            web_query="ціна SOL",
            web_digest="1 Solana = 70.7 USD, CoinGecko",
            web_facts=2,
            goal="дізнатись ціну SOL", ok=True, steps=1, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(lessons)
        text = " ".join(lesson.advice for lesson in lessons)
        self.assertIn("інтернету", text)
        self.assertIn("70.7", text)

    def test_empty_digest_no_lesson(self) -> None:
        facts = selflearning.TurnFacts(web_query="щось", ok=True)
        self.assertEqual(selflearning.extract_lessons(facts), [])


class TestThreeSourcesTogether(unittest.TestCase):
    """Модель + інтернет + користувач — усі три в одному ході."""

    def test_both_sources_produce_lessons(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("write_file", False, "Помилка: немає теки"),
                   ("write_file", True, "Записано a.py")],
            changed_files=["a.py"],
            web_query="ціна SOL", web_digest="70.7 USD", web_facts=1,
            user_corrected=True, user_words="неправильно, бери з CoinGecko",
            goal="оновити ціни", ok=True, steps=2, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertGreaterEqual(len(lessons), 2,
                                f"мало бути кілька уроків: "
                                f"{[l.advice[:40] for l in lessons]}")
        joined = " ".join(lesson.advice for lesson in lessons)
        self.assertIn("CoinGecko", joined)
        self.assertIn("інтернету", joined)

    def test_limit_still_respected(self) -> None:
        """Нові правила не ламають обмеження кількості уроків."""
        facts = selflearning.TurnFacts(
            calls=[("run_command", True, "Ran 0 tests")] * 3
                  + [("write_file", True, "Записано f.py")] * 4,
            changed_files=["f.py"] * 4, syntax_repairs=2,
            asked_permission=True, web_digest="щось знайдено", web_facts=1,
            user_corrected=True, user_words="неправильно",
            goal="зробити все", ok=False, steps=10, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertLessEqual(len(lessons), selflearning.WRITE_LIMIT)


class TestAgentWiring(unittest.TestCase):
    """Агент справді передає ці дані у факти ходу."""

    def test_agent_reads_correction(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._run)
        self.assertIn("looks_like_correction", source,
                      "агент не розпізнає поправку користувача")
        self.assertIn("_user_corrected", source)

    def test_agent_passes_web_data(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._learn_from_turn)
        for name in ("web_query", "web_digest", "web_facts",
                     "user_corrected", "user_words"):
            with self.subTest(field=name):
                self.assertIn(name, source,
                              f"агент не передає {name} в уроки")

    def test_web_block_records_digest(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._web_context_for)
        self.assertIn("_web_digest", source,
                      "знайдене в мережі не запам'ятовується для уроку")


if __name__ == "__main__":
    unittest.main(verbosity=2)
