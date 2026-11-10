"""Тести видимості помилок: збій не зникає безслідно.

Розділ 5 плану: раніше 285 місць ковтали виняток через
``except Exception: pass``. Користувач бачив «нічого не сталося», а
причини не було ні в інтерфейсі, ні в журналі.

``safe.call`` ловить збій, пише його в журнал і (за бажанням) показує
короткий текст у статусбарі.

Запуск: python -m unittest tests.test_safe_calls -v
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import safe  # noqa: E402


class TestSafeCall(unittest.TestCase):
    """``safe.call`` не пропускає виняток назовні, але й не ховає його."""

    def test_returns_value_on_success(self) -> None:
        self.assertEqual(safe.call(lambda a, b: a + b, 2, 3), 5)

    def test_passes_kwargs(self) -> None:
        self.assertEqual(safe.call(lambda *, x=0: x, x=7), 7)

    def test_returns_default_on_failure(self) -> None:
        def boom() -> None:
            raise RuntimeError("збій")

        self.assertEqual(safe.call(boom, default="запас"), "запас")

    def test_failure_is_logged(self) -> None:
        def boom() -> None:
            raise ValueError("конкретна причина")

        with self.assertLogs("blackchpok.ui", level="WARNING") as captured:
            safe.call(boom, where="тестова дія")
        text = "\n".join(captured.output)
        self.assertIn("тестова дія", text)
        self.assertIn("конкретна причина", text)

    def test_on_error_receives_readable_text(self) -> None:
        shown: list[str] = []

        def boom() -> None:
            raise KeyError("немає")

        safe.call(boom, where="збереження", on_error=shown.append)
        self.assertEqual(len(shown), 1)
        self.assertIn("збереження", shown[0])
        self.assertIn("KeyError", shown[0])

    def test_none_callback_is_silent(self) -> None:
        self.assertIsNone(safe.call(None))
        self.assertEqual(safe.call(None, default=1), 1)

    def test_broken_on_error_does_not_raise(self) -> None:
        def boom() -> None:
            raise RuntimeError("перше")

        def bad_handler(_text: str) -> None:
            raise RuntimeError("друге")

        # Обробник помилки, що сам падає, не має валити виклик.
        self.assertIsNone(safe.call(boom, on_error=bad_handler))

    def test_call_quiet_logs_without_user_message(self) -> None:
        shown: list[str] = []

        def boom() -> None:
            raise RuntimeError("тихо")

        with self.assertLogs("blackchpok.ui", level="WARNING"):
            safe.call_quiet(boom, where="оновлення підпису", on_error=shown.append)
        self.assertEqual(shown, [], "call_quiet не має показувати повідомлення")


class TestNoCriticalSilentHandlers(unittest.TestCase):
    """Критичні колбеки чату більше не ковтають помилки мовчки."""

    def _source(self, name: str) -> str:
        return (ROOT / "blackchpok_ide" / name).read_text(encoding="utf-8")

    def test_chat_panel_uses_safe_for_history(self) -> None:
        source = self._source("chat_panel.py")
        self.assertIn("safe.call(self.on_message", source,
                      "збій збереження історії має бути видно")

    def test_chat_panel_uses_safe_for_events(self) -> None:
        source = self._source("chat_panel.py")
        self.assertIn("safe.call_quiet(self.on_event", source)

    def test_editor_uses_safe(self) -> None:
        source = self._source("editor.py")
        self.assertIn("from . import safe", source)
        self.assertIn("safe.call_quiet(self.on_analysis", source)

    def test_shell_session_has_logger(self) -> None:
        source = self._source("shell_session.py")
        self.assertIn("LOG = logging.getLogger", source)

    def test_no_bare_except_pass_in_agent(self) -> None:
        import ast

        source = self._source("agent.py")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is not None and not (
                    isinstance(node.type, ast.Name) and node.type.id == "Exception"):
                continue
            body = [item for item in node.body if not isinstance(item, ast.Pass)]
            if not body:
                offenders.append(node.lineno)
        # Агент — серце застосунку: там не має бути повністю німих обробників.
        self.assertEqual(offenders, [], f"agent.py: німі обробники в рядках {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
