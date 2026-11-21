"""Тести безкоштовних ШІ через браузер: опитування та об'єднання відповідей.

Що охороняється:

* модуль не вигадує відповідь, якщо браузер її не дав — повертає причину;
* відповідь читається з ОСТАННЬОГО блоку (поточний запит, а не історія);
* об'єднання не «бере першу»: розбіжність у числах позначається явно;
* збій одного провайдера не зриває решту;
* та сама відповідь не стає джерелом вигадок у пам'яті.

Модуль перевіряється підробленою CDP-сесією: без вікна, без мережі й без
реального очікування 90 секунд.

Запуск: python -m unittest tests.test_web_ai -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import web_ai  # noqa: E402


class FakeSession:
    """Підроблена CDP-сесія: віддає заздалегідь задані відповіді."""

    def __init__(self, answers: list[str] | None = None, *,
                 click: bool = True, type_ok: bool = True,
                 press: bool = True) -> None:
        self.answers = list(answers or [])
        self.click = click
        self.type_ok = type_ok
        self.press = press
        self.typed: list[str] = []
        self.clicks: list[str] = []
        self.scripts: list[str] = []

    def click_selector(self, selector: str) -> bool:
        self.clicks.append(selector)
        return self.click

    def type_text(self, text: str) -> bool:
        self.typed.append(text)
        return self.type_ok

    def press_key(self, key: str) -> bool:
        return self.press and key == "Enter"

    def evaluate(self, script: str) -> Any:
        self.scripts.append(script)
        if not self.answers:
            return ""
        # Останній виклик повертає останню відповідь — так поводиться
        # стрімінг: текст «дозріває» з кожним опитуванням.
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def no_sleep(_seconds: float) -> None:
    """Не чекати в тестах."""


class TestProviderRegistry(unittest.TestCase):
    """Реєстр провайдерів."""

    def test_providers_have_selectors(self) -> None:
        for spec in web_ai.PROVIDERS:
            with self.subTest(provider=spec.key):
                self.assertTrue(spec.url.startswith("https://"))
                self.assertTrue(spec.input_selector)
                self.assertTrue(spec.answer_selector)

    def test_lookup_by_key(self) -> None:
        self.assertIsNotNone(web_ai.provider("duckduckgo"))
        self.assertIsNone(web_ai.provider("немає-такого"))

    def test_names_are_unique(self) -> None:
        names = web_ai.provider_names()
        self.assertEqual(len(names), len(set(names)))

    def test_describe_mentions_login(self) -> None:
        self.assertIn("без входу", web_ai.provider("duckduckgo").describe())


class TestReadAnswer(unittest.TestCase):
    """Читання відповіді зі сторінки."""

    def test_reads_last_block(self) -> None:
        session = FakeSession(["  Відповідь із пробілами  "])
        spec = web_ai.provider("duckduckgo")
        self.assertEqual(web_ai.read_answer(session, spec),
                         "Відповідь із пробілами")

    def test_script_uses_selector(self) -> None:
        session = FakeSession([""])
        spec = web_ai.provider("duckduckgo")
        web_ai.read_answer(session, spec)
        self.assertIn("querySelectorAll", session.scripts[0])

    def test_broken_session_is_harmless(self) -> None:
        class Broken:
            def evaluate(self, _script: str) -> Any:
                raise RuntimeError("навмисно")

        self.assertEqual(web_ai.read_answer(Broken(),
                                            web_ai.provider("duckduckgo")), "")


class TestSubmitPrompt(unittest.TestCase):
    """Введення запиту."""

    def test_types_and_presses_enter(self) -> None:
        session = FakeSession()
        spec = web_ai.provider("duckduckgo")
        self.assertTrue(web_ai.submit_prompt(session, spec, "привіт"))
        self.assertEqual(session.typed, ["привіт"])

    def test_missing_input_is_reported(self) -> None:
        session = FakeSession(click=False)
        self.assertFalse(web_ai.submit_prompt(session,
                                              web_ai.provider("duckduckgo"), "x"))

    def test_empty_prompt_is_refused(self) -> None:
        session = FakeSession()
        self.assertFalse(web_ai.submit_prompt(session,
                                              web_ai.provider("duckduckgo"), "  "))
        self.assertEqual(session.typed, [])


class TestPollAnswer(unittest.TestCase):
    """Очікування відповіді."""

    def test_waits_until_text_stops_changing(self) -> None:
        spec = web_ai.provider("duckduckgo")
        text = "Біткоїн сьогодні коштує 67432 долари за монету, це зростання."
        session = FakeSession(["Біткоїн", "Біткоїн сьогодні", text, text, text])
        answer = web_ai.poll_answer(session, spec, timeout=5, sleep=no_sleep)
        self.assertTrue(answer.ok, answer.error)
        self.assertEqual(answer.text, text)

    def test_timeout_without_text_reports_reason(self) -> None:
        spec = web_ai.provider("duckduckgo")
        session = FakeSession([""])
        answer = web_ai.poll_answer(session, spec, timeout=0.01, sleep=no_sleep)
        self.assertFalse(answer.ok)
        self.assertIn("не дочекались", answer.error)

    def test_timeout_with_partial_text_still_returns_it(self) -> None:
        """Текст, що досі «друкується», не має губитись на таймауті."""
        spec = web_ai.provider("duckduckgo")

        class Streaming:
            """Кожне опитування дає довший текст — стабілізації не буде."""

            def __init__(self) -> None:
                self.calls = 0

            def evaluate(self, _script: str) -> Any:
                self.calls += 1
                return "Часткова відповідь " + "далі " * self.calls

        answer = web_ai.poll_answer(Streaming(), spec, timeout=0.05,
                                    sleep=no_sleep)
        self.assertTrue(answer.ok)
        self.assertIn("неповною", answer.error)
        self.assertIn("Часткова", answer.text)


class TestAsk(unittest.TestCase):
    """Повний цикл «відкрити → спитати → дочекатись»."""

    def test_navigates_and_asks(self) -> None:
        spec = web_ai.provider("duckduckgo")
        text = "Відповідь достатньої довжини, щоб вважати її корисною тут."
        session = FakeSession([text, text, text])
        opened: list[str] = []
        answer = web_ai.ask(session, spec, "питання",
                            navigate=lambda url: opened.append(url) or True,
                            timeout=5, sleep=no_sleep)
        self.assertTrue(answer.ok, answer.error)
        self.assertEqual(opened, [spec.url])
        self.assertEqual(session.typed, ["питання"])

    def test_navigation_failure_is_reported(self) -> None:
        def boom(_url: str) -> bool:
            raise RuntimeError("навмисно")

        answer = web_ai.ask(FakeSession(), web_ai.provider("duckduckgo"), "x",
                            navigate=boom, sleep=no_sleep)
        self.assertFalse(answer.ok)
        self.assertIn("не відкрито", answer.error)


class TestCombine(unittest.TestCase):
    """Об'єднання відповідей — головна мета модуля."""

    def test_single_answer_passes_through(self) -> None:
        one = web_ai.Answer("duckduckgo", "Єдина відповідь із достатньою "
                                         "довжиною для перевірки.")
        result = web_ai.combine([one])
        self.assertEqual(result.used, ["duckduckgo"])
        self.assertIn("Єдина відповідь", result.text)
        self.assertFalse(result.disagreement)

    def test_disagreement_in_numbers_is_flagged(self) -> None:
        first = web_ai.Answer("duckduckgo", "Біткоїн коштує 67432 долари "
                                           "за одну монету сьогодні вранці.")
        second = web_ai.Answer("perplexity", "Біткоїн коштує 61000 доларів "
                                             "за одну монету сьогодні вранці.")
        result = web_ai.combine([first, second])
        self.assertTrue(result.disagreement)
        self.assertIn("розходяться", result.text)
        self.assertEqual(len(result.used), 2)

    def test_failed_provider_does_not_break_result(self) -> None:
        good = web_ai.Answer("duckduckgo", "Робоча відповідь із достатньою "
                                           "довжиною для перевірки.")
        bad = web_ai.Answer("chatgpt", ok=False, error="потрібен вхід")
        result = web_ai.combine([good, bad])
        self.assertEqual(result.used, ["duckduckgo"])
        self.assertTrue(result.failed)
        self.assertIn("chatgpt", result.failed[0])

    def test_all_failed_gives_empty_text(self) -> None:
        result = web_ai.combine([web_ai.Answer("chatgpt", ok=False,
                                               error="потрібен вхід")])
        self.assertEqual(result.text, "")
        self.assertTrue(result.failed)

    def test_short_answer_is_not_useful(self) -> None:
        self.assertFalse(web_ai.Answer("x", "ок").is_useful())

    def test_describe_is_human(self) -> None:
        result = web_ai.combine([web_ai.Answer(
            "duckduckgo", "Достатньо довга відповідь для перевірки опису.")])
        self.assertIn("відповідей", result.describe())


class TestMemories(unittest.TestCase):
    """Що з відповіді йде в довгострокову пам'ять."""

    def test_memory_mentions_providers(self) -> None:
        result = web_ai.combine([web_ai.Answer(
            "duckduckgo", "Корисна відповідь достатньої довжини для перевірки.")])
        items = web_ai.memories_for(result)
        self.assertTrue(items)
        self.assertIn("duckduckgo", items[0])

    def test_empty_consensus_gives_nothing(self) -> None:
        self.assertEqual(web_ai.memories_for(web_ai.Consensus()), [])

    def test_memory_is_capped(self) -> None:
        long = "Дуже довга відповідь " * 200
        result = web_ai.combine([web_ai.Answer("duckduckgo", long)])
        items = web_ai.memories_for(result)
        self.assertLessEqual(len(items[0]), 1300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
