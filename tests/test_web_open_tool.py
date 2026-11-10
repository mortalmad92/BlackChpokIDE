"""Тести інструмента ``web_open``: показати сторінку ЛЮДИНІ.

Користувач просив: «щоб агент сам міг мені відкрити посилання і показати,
де він знайшов інформацію». ``fetch_url`` лише читає сторінку для моделі —
людина її не бачить. ``web_open`` відкриває її в панелі «Сайт».

Запуск: python -m unittest tests.test_web_open_tool -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolError, ToolRegistry  # noqa: E402


class TestWebOpenTool(unittest.TestCase):
    """Інструмент показує сторінку й чесно каже, коли не може."""

    def setUp(self) -> None:
        self.registry = ToolRegistry(Path(tempfile.mkdtemp()))
        self.opened: list[str] = []

    def _attach(self, *, result: bool = True) -> None:
        self.registry.attach_page_opener(
            lambda url: (self.opened.append(url), result)[1])

    def test_registered(self) -> None:
        self.assertIn("web_open", self.registry.handled_names())

    def test_schema_exists(self) -> None:
        names = {item["function"]["name"] for item in TOOL_SCHEMAS}
        self.assertIn("web_open", names)

    def test_schema_describes_when_to_use(self) -> None:
        """Опис має відрізняти його від fetch_url — інакше модель плутає."""
        schema = next(item for item in TOOL_SCHEMAS
                      if item["function"]["name"] == "web_open")
        description = schema["function"]["description"].lower()
        self.assertIn("користувачу", description)
        self.assertIn("fetch_url", description)

    def test_opens_full_url(self) -> None:
        self._attach()
        text = self.registry.web_open("https://example.com/page")
        self.assertEqual(self.opened, ["https://example.com/page"])
        self.assertIn("відкрито", text.lower())

    def test_adds_scheme(self) -> None:
        self._attach()
        self.registry.web_open("github.com")
        self.assertEqual(self.opened, ["https://github.com"])

    def test_words_become_search(self) -> None:
        self._attach()
        self.registry.web_open("погода київ")
        self.assertIn("google.com.ua/search", self.opened[0])

    def test_strips_quotes(self) -> None:
        """Модель часто передає адресу в лапках."""
        self._attach()
        self.registry.web_open('"https://example.com"')
        self.assertEqual(self.opened, ["https://example.com"])

    def test_empty_url_is_error(self) -> None:
        self._attach()
        with self.assertRaises(ToolError):
            self.registry.web_open("")

    def test_no_window_is_honest(self) -> None:
        """Без підключеного вікна — помилка, а не вигаданий успіх."""
        with self.assertRaises(ToolError) as caught:
            self.registry.web_open("https://example.com")
        message = str(caught.exception)
        self.assertIn("недоступний", message)
        self.assertIn("fetch_url", message)

    def test_browser_refusal_is_reported(self) -> None:
        self._attach(result=False)
        with self.assertRaises(ToolError) as caught:
            self.registry.web_open("https://example.com")
        self.assertIn("не відкрив", str(caught.exception))

    def test_opener_exception_is_wrapped(self) -> None:
        def boom(_url):
            raise RuntimeError("браузер закрито")

        self.registry.attach_page_opener(boom)
        with self.assertRaises(ToolError) as caught:
            self.registry.web_open("https://example.com")
        self.assertIn("браузер закрито", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
