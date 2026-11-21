"""Інтернет на КОЖЕН запит + розпізнавання свіжих даних у роутері.

Вимога користувача (21.11.2026): «я взагалі просив, щоб до кожного запиту в
локальній моделі додавався запит до інтернету. Користувач запитує — пошук в
інтернеті + дані від моделі = загальна відповідь агента».

Реальний дефект, який це закриває. На запит «Використай інтернет і знайди
актуальну ціну на SOL, біткоїн та ETH» агент викликав ``search_text`` —
пошук ПО ФАЙЛАХ ПРОЄКТУ — і відзвітував «Нічого не знайдено», хоч
``search_web`` працював і повертав справжню ціну.

Причини (заміряно):

* список у роутері знав ``"в інтернеті"`` (з прийменником), але не
  ``"інтернет"``;
* знав ``"ціна"``, але не ``"ціну"`` (знахідний відмінок);
* ``search_text`` мав ``HIGH``-упевненість і перебивав мережу.

Запуск: python -m unittest tests.test_web_every_turn -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import config, tool_router  # noqa: E402


class TestAsksWeb(unittest.TestCase):
    """Розпізнавання «це питання до мережі»."""

    def test_explicit_internet_word(self) -> None:
        self.assertTrue(tool_router._asks_web(
            "використай інтернет і знайди ціну"))

    def test_internet_without_preposition(self) -> None:
        """«Використай інтернет» — без «в» перед словом."""
        self.assertTrue(tool_router._asks_web("використай інтернет"))

    def test_price_in_accusative(self) -> None:
        """«ціну» (знахідний), а не лише «ціна»."""
        self.assertTrue(tool_router._asks_web("знайди актуальну ціну на SOL"))

    def test_price_nominative_still_works(self) -> None:
        self.assertTrue(tool_router._asks_web("яка ціна біткоїна"))

    def test_crypto_and_currency(self) -> None:
        for word in ("біткоїн", "bitcoin", "курс валют", "ефір eth"):
            with self.subTest(word=word):
                self.assertTrue(tool_router._asks_web(f"скільки коштує {word}"))

    def test_weather_and_news(self) -> None:
        for query in ("яка погода в Києві", "останні новини", "актуальні новини"):
            with self.subTest(query=query):
                self.assertTrue(tool_router._asks_web(query))

    def test_version_question(self) -> None:
        self.assertTrue(tool_router._asks_web("яка зараз версія FastAPI"))

    def test_code_task_is_not_web(self) -> None:
        for query in ("напиши функцію додавання", "зроби сайт",
                      "виправ баг у agent.py"):
            with self.subTest(query=query):
                self.assertFalse(tool_router._asks_web(query))

    def test_greeting_is_not_web(self) -> None:
        self.assertFalse(tool_router._asks_web("привіт, як справи"))


class TestRouterPrefersWeb(unittest.TestCase):
    """Живий запит про ціну йде в мережу, а не в пошук по файлах."""

    def test_price_query_routes_to_search_web(self) -> None:
        phrase = ("Використай інтернет і знайди актуальну ціну на SOL солану, "
                  "біткоїн та ефір ETH.")
        hints = tool_router.confident(phrase)
        tools = [hint.tool for hint in hints]
        self.assertIn("search_web", tools,
                      f"мережа не обрана: {tools}")
        self.assertNotIn("search_text", tools,
                         f"пошук по файлах перебив мережу: {tools}")


class TestEveryTurnSetting(unittest.TestCase):
    """Налаштування «інтернет на кожен запит»."""

    def test_default_is_on(self) -> None:
        self.assertTrue(config.AgentSettings().web_every_turn)


class TestWebContextBlock(unittest.TestCase):
    """Блок знань з мережі для промпту."""

    def _runner(self, **overrides):
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry

        settings = config.AgentSettings(**overrides)
        runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                             settings, ROOT)
        runner.tools_enabled = True
        return runner

    def test_block_is_built(self) -> None:
        """Живий пошук: блок мусить містити справжні результати."""
        runner = self._runner()
        block = runner._web_context_for("яка ціна біткоїна")
        self.assertTrue(block, "блок не побудовано")
        # Блок переписано 21.11.2026 під схему «дані вже зібрані»:
        # замість заголовка «Що зараз є в ІНТЕРНЕТІ» тепер «ДАНІ З
        # ІНТЕРНЕТУ (уже зібрані для тебе…)».
        self.assertIn("ІНТЕРНЕТУ", block)
        self.assertIn("http", block, "у блоці немає джерел")
        self.assertLessEqual(len(block), 2700,
                             "блок завеликий для промпту")

    def test_disabled_gives_nothing(self) -> None:
        runner = self._runner(web_every_turn=False)
        self.assertEqual(runner._web_context_for("яка ціна біткоїна"), "")

    def test_private_mode_gives_nothing(self) -> None:
        runner = self._runner()
        runner.state.private = True
        self.assertEqual(runner._web_context_for("яка ціна біткоїна"), "")

    def test_tools_off_gives_nothing(self) -> None:
        runner = self._runner()
        runner.tools_enabled = False
        self.assertEqual(runner._web_context_for("яка ціна біткоїна"), "")

    def test_service_message_is_not_searched(self) -> None:
        runner = self._runner()
        self.assertEqual(
            runner._web_context_for("Ти вже викликав «read_file» 3 рази"), "")

    def test_cache_prevents_second_search(self) -> None:
        """Повторний той самий запит не ходить у мережу вдруге."""
        runner = self._runner()
        first = runner._web_context_for("яка ціна біткоїна")
        second = runner._web_context_for("яка ціна біткоїна")
        self.assertEqual(first, second)
        self.assertTrue(runner._web_context_cache)


class TestSchemeContract(unittest.TestCase):
    """СХЕМА, яку описав користувач (21.11.2026).

        запит користувача → агент шукає в інтернеті (у фоні) →
        модель отримує дані + свої знання → ГОТОВА об'єднана відповідь

    Три вимоги до блоку, який бачить модель:

    1. вона НЕ має сама викликати пошук (дані вже зібрані);
    2. має відповідати ОДРАЗУ готовим текстом;
    3. має НЕ переказувати інструкцію замість відповіді.

    Пункт 3 — реальний дефект: у живому чаті агент відповів
    «Знайди актуальну ціну… Дай цього етапу доречні інструменти: search_web…»
    — тобто переказав службову підказку замість відповіді.
    """

    def _block(self) -> str:
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry

        runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                             config.AgentSettings(), ROOT)
        runner.tools_enabled = True
        return runner._web_context_for("яка ціна біткоїна сьогодні")

    def test_model_is_told_not_to_search(self) -> None:
        self.assertIn("не викликай пошук сам", self._block().lower())

    def test_model_is_told_to_answer_now(self) -> None:
        self.assertIn("відповідай одразу", self._block().lower())

    def test_model_is_told_not_to_echo_instruction(self) -> None:
        self.assertIn("не переказуй", self._block().lower())

    def test_data_comes_with_sources(self) -> None:
        self.assertIn("http", self._block())

    def test_advice_says_do_not_echo(self) -> None:
        """Порада роутера теж не має потрапляти у відповідь."""
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry

        runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                             config.AgentSettings(), ROOT)
        runner.tools_enabled = False
        runner._pending_hint = tool_router.confident("покажи файли")
        self.assertIn("НЕ переказуй", runner._hint_advice())


if __name__ == "__main__":
    unittest.main(verbosity=2)
