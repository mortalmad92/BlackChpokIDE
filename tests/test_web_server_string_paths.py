"""Функції ``web_server`` мусять приймати теку й рядком, і ``Path``.

Причина появи. ``settings.workspace`` — це РЯДОК. Перевірено наживо:

    web_server._read('README_UK.md')
    → AttributeError: 'str' object has no attribute 'read_text'
    web_server.find_entry('.', ['main.py'])
    → TypeError: unsupported operand type(s) for /: 'str' and 'str'
    web_server._find_html('.')
    → AttributeError: 'str' object has no attribute 'iterdir'

Гірше за сам виняток те, що ``_read`` ловить ЛИШЕ ``OSError``: для рядка
вилітає ``AttributeError``, який ``except`` не перехоплює. Тобто «файл
недоступний» перетворювалось на аварію викликача замість порожнього рядка.

``detect()`` нормалізує теку сам, тож через нього дефект не проявлявся —
саме тому його не бачили. Але ``find_entry`` — публічна функція без
підкреслення, і викликати її рядком цілком природно.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import web_server  # noqa: E402


class TestAcceptsStringAndPath(TestCase):
    """Обидва типи теки дають однаковий результат."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="ws-probe-"))
        (self.folder / "index.html").write_text("<html><body>ok</body></html>",
                                                encoding="utf-8")
        (self.folder / "app.js").write_text("console.log(1)\n", encoding="utf-8")

    def test_read_accepts_string(self) -> None:
        text = web_server._read(str(self.folder / "index.html"), 100)
        self.assertIn("ok", text,
                      "``_read`` з рядком мусить читати файл, а не падати")

    def test_read_missing_file_returns_empty(self) -> None:
        self.assertEqual(web_server._read(str(self.folder / "nope.html")), "",
                         "відсутній файл — порожній рядок, не виняток")

    def test_read_invalid_type_does_not_raise(self) -> None:
        """Навіть безглуздий вхід не має валити викликача."""
        self.assertEqual(web_server._read(None), "")

    def test_find_entry_accepts_string(self) -> None:
        found = web_server.find_entry(str(self.folder), ["index.html"])
        self.assertIsNotNone(found, "``find_entry`` з рядком мусить працювати")
        self.assertEqual(found.name, "index.html")

    def test_exists_accepts_string(self) -> None:
        found = web_server._exists(str(self.folder), "app.js")
        self.assertIsNotNone(found, "``_exists`` з рядком мусить працювати")

    def test_find_html_accepts_string(self) -> None:
        names = [path.name for path in
                 web_server._find_html(str(self.folder), limit=2)]
        self.assertIn("index.html", names,
                      "``_find_html`` з рядком мусить працювати")

    def test_detect_accepts_string(self) -> None:
        recipe = web_server.detect(str(self.folder))
        self.assertEqual(recipe.kind, web_server.STATIC,
                         f"очікували static, отримали {recipe.kind}")

    def test_string_and_path_agree(self) -> None:
        """Результат не залежить від типу аргументу."""
        as_path = web_server.detect(self.folder)
        as_text = web_server.detect(str(self.folder))
        self.assertEqual(as_path.kind, as_text.kind)
        self.assertEqual(as_path.port, as_text.port)


if __name__ == "__main__":
    main()
