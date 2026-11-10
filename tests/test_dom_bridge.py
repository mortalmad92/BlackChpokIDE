"""Тести DOM-мосту Live Preview.

Фіксують вимоги:
* структура сторінки як дані (селектори, координати, текст);
* обчислені стилі елемента;
* пошук за текстом;
* чесна відмова, коли Live Preview не запущено;
* міст працює ЛИШЕ через передану сесію (жодних «магічних» з'єднань).

Реальність перевірена окремо на headless Chrome (див. docs/DOM_BRIDGE.md).

Запуск:
    python -m unittest tests.test_dom_bridge -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-dom-"))
os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import dom_bridge  # noqa: E402


class FakeSession:
    """Підміна CDP-сесії: віддає заздалегідь задані значення."""

    def __init__(self, *, tree=None, styles=None, errors=None,
                 title="Демо", url="http://localhost:3000/",
                 fail=False) -> None:
        self.tree = tree if tree is not None else [
            {"tag": "body", "selector": "html > body", "text": "Головна",
             "x": 0, "y": 0, "w": 800, "h": 600, "role": "", "children": 1},
            {"tag": "button", "selector": "button.primary", "text": "Зберегти",
             "x": 40, "y": 20, "w": 120, "h": 40, "role": "button",
             "children": 0},
        ]
        self.styles = styles if styles is not None else {
            "selector": "button.primary", "tag": "button", "text": "Зберегти",
            "box": {"x": 40, "y": 20, "width": 120, "height": 40},
            "styles": {"display": "inline-block",
                       "background-color": "rgb(0, 170, 0)",
                       "font-size": "14px"},
            "attributes": {"class": "primary"},
        }
        self.errors = errors if errors is not None else {"count": 0, "items": []}
        self.title = title
        self.url = url
        self.fail = fail
        self.expressions: list[str] = []

    def evaluate(self, expression):
        self.expressions.append(expression)
        if self.fail:
            return None
        if "location.href" in expression:
            return self.url
        if "document.title" in expression:
            return self.title
        return None

    def evaluate_json(self, expression):
        self.expressions.append(expression)
        if self.fail:
            return None
        if "getComputedStyle" in expression:
            return self.styles
        if "__blackchpok_errors" in expression:
            return self.errors
        return self.tree


class TestAvailability(unittest.TestCase):
    def test_no_client_is_not_available(self) -> None:
        self.assertFalse(dom_bridge.available(None))

    def test_client_without_evaluate_is_not_available(self) -> None:
        self.assertFalse(dom_bridge.available(object()))

    def test_fake_session_is_available(self) -> None:
        self.assertTrue(dom_bridge.available(FakeSession()))


class TestDomTree(unittest.TestCase):
    def test_tree_is_parsed(self) -> None:
        nodes, note = dom_bridge.dom_tree(FakeSession())
        self.assertEqual(len(nodes), 2)
        self.assertIn("DOM", note)
        button = nodes[1]
        self.assertEqual(button.tag, "button")
        self.assertEqual(button.selector, "button.primary")
        self.assertEqual(button.box, (40, 20, 120, 40))
        self.assertEqual(button.role, "button")

    def test_node_line_contains_coordinates(self) -> None:
        nodes, _ = dom_bridge.dom_tree(FakeSession())
        line = nodes[1].line()
        self.assertIn("button", line)
        self.assertIn("(40,20)", line)
        self.assertIn("120×40", line)

    def test_unavailable_page_gives_honest_note(self) -> None:
        nodes, note = dom_bridge.dom_tree(FakeSession(fail=True))
        self.assertEqual(nodes, [])
        self.assertIn("не прочитано", note)
        self.assertNotIn("елементів 0", note)

    def test_no_client_note_mentions_preview(self) -> None:
        nodes, note = dom_bridge.dom_tree(None)
        self.assertEqual(nodes, [])
        self.assertIn("Live Preview", note)


class TestStyles(unittest.TestCase):
    def test_styles_are_returned(self) -> None:
        data, note = dom_bridge.element_styles(FakeSession(), "button.primary")
        self.assertIsNotNone(data)
        self.assertEqual(data["tag"], "button")
        self.assertIn("background-color", note)
        self.assertIn("rgb(0, 170, 0)", note)

    def test_missing_element(self) -> None:
        session = FakeSession(styles=None)
        session.evaluate_json = lambda expression: None
        data, note = dom_bridge.element_styles(session, ".nope")
        self.assertIsNone(data)
        self.assertIn("не знайдено", note)

    def test_empty_selector_rejected(self) -> None:
        data, note = dom_bridge.element_styles(FakeSession(), "")
        self.assertIsNone(data)
        self.assertIn("Порожній", note)

    def test_describe_styles_shows_box(self) -> None:
        data, _ = dom_bridge.element_styles(FakeSession(), "button.primary")
        text = dom_bridge.describe_styles(data)
        self.assertIn("(40,20)", text)
        self.assertIn("120×40", text)


class TestTextSearch(unittest.TestCase):
    def test_find_by_text(self) -> None:
        # Уважно з підрядком: у фразі «Зберегти» літера «г», а не «ж».
        found = dom_bridge.by_text(FakeSession(), "Зберег")
        self.assertTrue(found)
        self.assertEqual(found[0].tag, "button")

    def test_find_is_case_insensitive(self) -> None:
        found = dom_bridge.by_text(FakeSession(), "зберег")
        self.assertTrue(found)

    def test_find_by_full_text(self) -> None:
        found = dom_bridge.by_text(FakeSession(), "Зберегти")
        self.assertTrue(found)

    def test_empty_fragment_returns_nothing(self) -> None:
        self.assertEqual(dom_bridge.by_text(FakeSession(), "   "), [])

    def test_missing_text_returns_nothing(self) -> None:
        self.assertEqual(dom_bridge.by_text(FakeSession(), "невідомо-таке"), [])


class TestConsole(unittest.TestCase):
    def test_no_errors(self) -> None:
        items, note = dom_bridge.console_errors(FakeSession())
        self.assertEqual(items, [])
        self.assertIn("не зібрано", note)

    def test_errors_are_returned(self) -> None:
        session = FakeSession(errors={"count": 2, "items": [
            {"text": "ReferenceError: x is not defined"},
            {"text": "404 /api/data"}]})
        items, note = dom_bridge.console_errors(session)
        self.assertEqual(len(items), 2)
        self.assertIn("2", note)


class TestPageState(unittest.TestCase):
    def test_state_without_client(self) -> None:
        self.assertIn("не запущено", dom_bridge.page_state(None))

    def test_state_with_client(self) -> None:
        text = dom_bridge.page_state(FakeSession())
        self.assertIn("Демо", text)
        self.assertIn("localhost:3000", text)


class TestSecurity(unittest.TestCase):
    """Міст не має ходити в мережу самостійно."""

    def test_no_network_imports(self) -> None:
        source = (ROOT / "blackchpok_ide" / "dom_bridge.py").read_text(encoding="utf-8")
        for module in ("urllib.request", "socket", "requests", "http.client"):
            self.assertNotIn(f"import {module}", source,
                             "DOM-міст мусить працювати лише через передану "
                             "CDP-сесію, без власних мережевих з'єднань")

    def test_uses_only_readonly_js(self) -> None:
        """Скрипти мосту не мають змінювати сторінку."""
        source = (ROOT / "blackchpok_ide" / "dom_bridge.py").read_text(encoding="utf-8")
        for write in ("innerHTML =", "appendChild(", ".remove(", "setAttribute("):
            self.assertNotIn(write, source,
                             f"DOM-міст не має змінювати сторінку ({write})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
