"""Регресії відображення історії чатів: оверлей, прокрутка, висота карток.

Три вади, які робили історію невидимою, хоч дані були на диску:

1. порожній стартовий оверлей ``workspace_host`` лишався поверх колонки
   діалогу, коли сесія вже мала повідомлення (welcome не показувався);
2. ``ScrollFrame`` не стискав полотно після очищення стрічки, тож коротка
   розмова, відкрита після довгої, показувала порожній екран;
3. ``_fit_text`` міряв рядки при ``width=1``, і картка відповіді
   розтягувалась до ліміту в 60–80 рядків — текст опинявся за межами
   екрана.

Запуск: python -m unittest tests.test_chat_history_view -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestEstimateLines(unittest.TestCase):
    """Оцінка кількості екранних рядків без layout."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.theme = theme.Theme(cls.root, "Segoe UI", 10)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001 - закриття не має валити тест
            pass

    def _panel(self, width: int = 400):
        """Мінімальний носій методів оцінки (без будівництва всього чату)."""
        from blackchpok_ide.chat_panel import ChatPanel

        class _Stub:
            fonts = self.theme

            def _wrap_width(self) -> int:
                return width

            _measure_width = ChatPanel._measure_width
            _estimate_lines = ChatPanel._estimate_lines

        panel = _Stub()
        return panel

    def test_short_text_is_one_or_two_lines(self) -> None:
        panel = self._panel(400)
        # Короткий текст не має «роздуватись» до ліміту рядків.
        self.assertLessEqual(panel._estimate_lines("Привіт", 400), 2)

    def test_missing_layout_width_falls_back_to_feed(self) -> None:
        panel = self._panel(360)
        # Віджет без layout має ширину 1 px — беремо ширину стрічки.
        self.assertEqual(panel._measure_width(None), 360)

    def test_long_text_scales_with_width(self) -> None:
        panel = self._panel(400)
        text = "слово " * 200
        narrow = panel._estimate_lines(text, 200)
        wide = panel._estimate_lines(text, 800)
        self.assertGreater(narrow, wide)
        self.assertGreater(wide, 1)

    def test_long_word_wraps_by_character(self) -> None:
        panel = self._panel(400)
        # Довге «слово» без пробілів Tk переносить по символах.
        path = "C:/very/long/path/" + "segment" * 40
        self.assertGreater(panel._estimate_lines(path, 200), 1)

    def test_empty_text_is_one_line(self) -> None:
        panel = self._panel(400)
        self.assertEqual(panel._estimate_lines("", 400), 1)


class TestWelcomeOverlay(unittest.TestCase):
    """Оверлей стартового екрана не має лишатись поверх стрічки діалогу."""

    def test_workspace_host_is_not_placed_in_build(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
        marker = "self.workspace_host = tk.Frame(self.conversation_host"
        start = source.index(marker)
        # Беремо кілька рядків після створення віджета.
        tail = source[start:start + 700]
        placement = [line.strip() for line in tail.splitlines()
                     if "workspace_host.place(" in line]
        self.assertEqual(placement, [],
                         "workspace_host не має розміщуватись одразу — "
                         "інакше порожній оверлей перекриває історію")

    def _stub(self, shown: bool):
        """Мінімальний об'єкт із поведінкою _hide_welcome."""
        from blackchpok_ide.main_window import BlackChpokIDE

        calls = {"forget": 0, "pack_forget": 0}

        class _Host:
            def place_forget(self) -> None:
                calls["forget"] += 1

        class _Welcome:
            def pack_forget(self) -> None:
                calls["pack_forget"] += 1

        class _Stub:
            workspace_host = _Host()
            welcome = _Welcome()
            _welcome_shown = shown
            _hide_welcome = BlackChpokIDE._hide_welcome

        return _Stub(), calls

    def test_hide_welcome_clears_overlay_when_flag_set(self) -> None:
        stub, calls = self._stub(True)
        stub._hide_welcome()
        self.assertEqual(calls["forget"], 1)
        self.assertEqual(calls["pack_forget"], 1)
        self.assertFalse(stub._welcome_shown)

    def test_hide_welcome_clears_overlay_even_when_flag_cleared(self) -> None:
        # Оверлей міг лишитись від попереднього показу — знімаємо завжди.
        stub, calls = self._stub(False)
        stub._hide_welcome()
        self.assertEqual(calls["forget"], 1)
        self.assertEqual(calls["pack_forget"], 0)
        self.assertFalse(stub._welcome_shown)


class TestSessionStatusLabel(unittest.TestCase):
    """Підпис статусу в списку сесій має оновлюватись разом зі станом."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.theme = theme.Theme(cls.root, "Segoe UI", 10)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_status_label_changes_after_finish(self) -> None:
        from blackchpok_ide import chat_list_panel
        from blackchpok_ide.chat_store import Chat, STATUS_DONE, STATUS_WORKING

        chat = Chat(title="тест")
        chat.status = STATUS_WORKING
        row = chat_list_panel._SessionRow(
            self.root, chat, active=False, fonts=self.theme,
            on_open=lambda: None, on_menu=lambda c, e: None)
        try:
            text_working = row.status_label.cget("text")
            self.assertIn("Working", str(text_working))

            chat.status = STATUS_DONE
            row.refresh_status()
            text_done = row.status_label.cget("text")
            self.assertNotIn("Working", str(text_done),
                             "завершена сесія не має лишатись «Working»")
            self.assertIn("Completed", str(text_done))
        finally:
            row.destroy()


class TestScrollFrameSource(unittest.TestCase):
    """ScrollFrame перераховує область прокрутки під новий вміст."""

    def test_sync_scrollregion_exists(self) -> None:
        source = (ROOT / "blackchpok_ide" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("def sync_scrollregion", source)
        # Висота вікна-елемента має вирівнюватись за вмістом.
        self.assertIn("winfo_reqheight", source)

    def test_clear_and_scroll_to_end_sync(self) -> None:
        source = (ROOT / "blackchpok_ide" / "widgets.py").read_text(encoding="utf-8")
        start = source.index("def clear(self)")
        block = source[start:start + 600]
        self.assertIn("sync_scrollregion", block)

    def test_chat_reset_syncs_scrollregion(self) -> None:
        source = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        start = source.index("def reset(self)")
        block = source[start:start + 1600]
        self.assertIn("sync_scrollregion", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
