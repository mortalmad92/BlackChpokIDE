"""Відповідь — ТЕКСТ із обробкою моделлю, а не сирий вивід інструмента.

Вимога користувача (21.11.2026): «мені потрібно відповідь не кодом а текстом
з реальною обробкою моделью перед видачею користувачу!».

Реальний дефект. На «Яка ціна солани зараз?» агент відповідав:

    Готово. Результат:
    search_web
    ```json
    Результати з інтернету для «актуальна ціна на SOL солану»: …
    ```

Тобто людина отримувала машинний вивід (JSON, URL, нумерацію) замість
речення «Солана коштує 70.66 USD, +2.9% за добу». Модель у цьому не брала
участі взагалі — хоч саме вона має переказати дані.

Запуск: python -m unittest tests.test_narrated_answer -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import config  # noqa: E402

RAW_SEARCH = (
    "Результати з інтернету для «актуальна ціна на SOL солану»:\n"
    "1. Ціна Solana (CoinGecko)\n"
    "   https://www.coingecko.com/en/coins/solana\n"
    "   1 Solana = 70.66 USD, ≈ 3167.89 UAH, за 24 год: +2.92%"
)

NARRATED = ("Солана зараз коштує близько 70.66 USD (≈3167 грн) — "
            "за добу вона додала 2.92%. Дані з CoinGecko.")


def make_runner():
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry

    runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                         config.AgentSettings(), ROOT)
    runner.tools_enabled = False
    runner.session.messages = [{"role": "user",
                                "content": "Яка ціна солани зараз?"}]
    return runner


class StubClient:
    """Підроблена модель: повертає заданий текст і рахує виклики."""

    def __init__(self, content: str = NARRATED) -> None:
        self.content = content
        self.calls = 0
        self.last_prompt = ""

    def chat(self, messages, **_kwargs):
        self.calls += 1
        self.last_prompt = str(messages[0].get("content") or "")

        class Result:
            content = self.content

        return Result()


class TestNarration(unittest.TestCase):
    """Дані стають прозою."""

    def test_raw_data_becomes_text(self) -> None:
        runner = make_runner()
        client = StubClient()
        runner._last_client = client
        text = runner._narrate_results([RAW_SEARCH])
        self.assertEqual(client.calls, 1, "модель має бути викликана рівно раз")
        self.assertEqual(text, NARRATED)
        self.assertNotIn("http", text, "у відповіді лишився URL-код")
        self.assertNotIn("```", text, "у відповіді лишився блок коду")

    def test_prompt_contains_data_and_task(self) -> None:
        runner = make_runner()
        client = StubClient()
        runner._last_client = client
        runner._narrate_results([RAW_SEARCH])
        self.assertIn("70.66", client.last_prompt, "дані не передано моделі")
        self.assertIn("солани", client.last_prompt, "завдання не передано")
        self.assertIn("своїми словами", client.last_prompt)

    def test_no_data_no_call(self) -> None:
        runner = make_runner()
        client = StubClient()
        runner._last_client = client
        self.assertEqual(runner._narrate_results([]), "")
        self.assertEqual(runner._narrate_results(["", "   "]), "")
        self.assertEqual(client.calls, 0, "модель не мала викликатись")

    def test_broken_model_gives_empty(self) -> None:
        """Модель недоступна — лишається структурований звіт."""
        runner = make_runner()

        class Broken:
            def chat(self, *_a, **_kw):
                raise RuntimeError("модель недоступна")

        runner._last_client = Broken()
        self.assertEqual(runner._narrate_results([RAW_SEARCH]), "")

    def test_empty_model_answer_is_not_answer(self) -> None:
        runner = make_runner()
        runner._last_client = StubClient("")
        self.assertEqual(runner._narrate_results([RAW_SEARCH]), "")

    def test_echoed_instruction_is_not_answer(self) -> None:
        """Модель не має відповідати переказом інструкції."""
        runner = make_runner()
        runner._last_client = StubClient(
            "Ось дані, які я щойно зібрав інструментами: …")
        self.assertEqual(runner._narrate_results([RAW_SEARCH]), "")

    def test_too_short_answer_is_rejected(self) -> None:
        runner = make_runner()
        runner._last_client = StubClient("ок")
        self.assertEqual(runner._narrate_results([RAW_SEARCH]), "")

    def test_no_client_gives_empty(self) -> None:
        runner = make_runner()
        runner._last_client = None
        self.assertEqual(runner._narrate_results([RAW_SEARCH]), "")


class TestWiring(unittest.TestCase):
    """Переказ справді вставлено в шлях відповіді."""

    def test_hints_path_uses_narration(self) -> None:
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._run_hints)
        self.assertIn("_narrate_results", source,
                      "шлях роутера віддає сирі дані замість переказу")

    def test_fallback_kept(self) -> None:
        """Якщо переказ не вдався — лишається структурований звіт."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._run_hints)
        self.assertIn("or raw_answer", source,
                      "немає запасного шляху — відповідь може стати порожньою")


if __name__ == "__main__":
    unittest.main(verbosity=2)
