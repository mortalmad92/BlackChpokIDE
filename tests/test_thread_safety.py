"""Регресії потокобезпеки інтерфейсу (Етап 6, 10.11.2026).

Tkinter не потокобезпечний. У проєкті вже є правильний механізм —
``main_window._ui_call`` (черга + ``_drain_ui`` у головному потоці) — але
три місця його обходили.

Перевірки нижче дивляться на КОД, а не на поведінку: відтворити падіння
Tk у тесті можна лише нестабільно, а от перевірити, що небезпечний виклик
не повернувся, — можна надійно.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import chat_panel, main_window, settings_dialog  # noqa: E402


class TestSettingsDialogUiText(unittest.TestCase):
    """``_ui_text`` кличеться з ``work()`` — тобто з фонового потоку."""

    def test_ui_text_does_not_call_after_directly(self) -> None:
        source = inspect.getsource(settings_dialog.SettingsDialog._ui_text)
        body = source.split('"""')[-1]        # без докстрінга
        self.assertNotIn(
            "self.after(", body,
            "after() з фонового потоку дає 'main thread is not in main loop'")

    def test_ui_text_uses_queue(self) -> None:
        source = inspect.getsource(settings_dialog.SettingsDialog._ui_text)
        self.assertIn("_text_queue", source)

    def test_pump_runs_in_main_thread(self) -> None:
        """Читання черги має плануватись через ``after`` — у UI-потоці."""
        source = inspect.getsource(settings_dialog.SettingsDialog._pump_text_queue)
        self.assertIn("self.after(", source)

    def test_queue_helpers_exist(self) -> None:
        for name in ("_ensure_text_queue", "_pump_text_queue"):
            self.assertTrue(hasattr(settings_dialog.SettingsDialog, name),
                            f"немає {name}")


class TestExecutorCallbacksAreMarshalled(unittest.TestCase):
    """Колбеки ``QueueExecutor`` чіпають віджети — мають іти через чергу."""

    def test_executor_uses_ui_call(self) -> None:
        source = inspect.getsource(main_window.BlackChpokIDE.__init__)
        start = source.find("task_executor.QueueExecutor(")
        self.assertGreater(start, -1)
        block = source[start:start + 900]
        self.assertIn("_ui_call(self.set_status", block,
                      "on_status іде з потоку агента прямо у віджет")
        self.assertIn("_ui_call(self._update_queue_badge", block,
                      "on_change іде з потоку агента прямо у віджет")


class TestCancelProbeResolution(unittest.TestCase):
    """``cancel_probe`` живе в ``ModelBar``, а не в ``ChatPanel``."""

    def test_chat_panel_has_no_cancel_probe(self) -> None:
        """Документує причину: прямий getattr на ChatPanel був no-op."""
        self.assertFalse(hasattr(chat_panel.ChatPanel, "cancel_probe"))

    def test_model_bar_has_cancel_probe(self) -> None:
        self.assertTrue(hasattr(chat_panel.ModelBar, "cancel_probe"))

    def test_on_close_searches_multiple_owners(self) -> None:
        source = inspect.getsource(main_window.BlackChpokIDE.on_close)
        self.assertIn("cancel_probe", source)
        # Має шукати більше ніж в одному місці.
        self.assertIn("model_bar", source,
                      "без пошуку в model_bar виклик лишається no-op")


if __name__ == "__main__":
    unittest.main(verbosity=2)
