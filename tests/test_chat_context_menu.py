"""Контекстне меню правої кнопки в чаті: вставка й копіювання.

Вимога користувача (21.11.2026): «додай вже нарешті контекстне меню в чаті
для вставки тексту і копіювання на праву кнопку миші».

Що було не так. Гарячі клавіші (Ctrl+V/C/X) працювали, але ПРАВИЙ КЛІК не
робив нічого: у полі вводу меню не було зовсім, а на картці повідомлення
меню з'являлось лише над блоком коду. Людина, яка звикла до правої кнопки,
не могла ні вставити текст, ні скопіювати відповідь.

Запуск: python -m unittest tests.test_chat_context_menu -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestMenuMethodsExist(unittest.TestCase):
    """Методи меню є й прив'язані до правої кнопки."""

    def test_input_methods(self) -> None:
        from blackchpok_ide.chat_panel import ChatPanel

        for name in ("_input_menu", "_clip_copy", "_clip_paste", "_clip_cut",
                     "_clear_input", "_select_all", "_has_selection"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(ChatPanel, name), f"немає {name}")

    def test_text_menu_methods(self) -> None:
        from blackchpok_ide.chat_panel import ChatPanel

        for name in ("_text_menu", "_paste_into_input", "_select_widget"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(ChatPanel, name), f"немає {name}")

    def test_input_right_click_is_bound(self) -> None:
        """Права кнопка в полі вводу прив'язана до меню."""
        import inspect

        from blackchpok_ide import chat_panel

        # Метод побудови поля вводу називається інакше — шукаємо прив'язку по
        # всьому класу, а не за вигаданою назвою (помилка попередньої версії
        # цього тесту: ``_build_input`` не існує).
        source = inspect.getsource(chat_panel.ChatPanel)
        self.assertIn('input_box.bind("<Button-3>"', source,
                      "права кнопка в полі вводу не прив'язана")
        self.assertIn("_input_menu", source)

    def test_message_text_right_click_is_bound(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        source = inspect.getsource(chat_panel.ChatPanel._render_markdown)
        self.assertIn("_text_menu", source,
                      "права кнопка на тексті повідомлення не прив'язана")


class TestMenuItems(unittest.TestCase):
    """Склад меню: потрібні пункти справді є."""

    def _menu_source(self, name: str) -> str:
        import inspect
        import re

        from blackchpok_ide import chat_panel

        source = inspect.getsource(getattr(chat_panel.ChatPanel, name))
        # Без докстрінга: у ньому згадано назви пунктів у лапках.
        return re.sub(r'"""[\s\S]*?"""', "", source, count=1)

    def test_input_menu_has_paste_and_copy(self) -> None:
        source = self._menu_source("_input_menu")
        for label in ("Вставити", "Копіювати", "Виділити все", "Очистити поле"):
            with self.subTest(label=label):
                self.assertIn(label, source)

    def test_input_menu_hides_copy_without_selection(self) -> None:
        """Без виділення «Копіювати» не показуємо — воно мовчки не працює."""
        source = self._menu_source("_input_menu")
        self.assertIn("_has_selection", source)

    def test_text_menu_has_copy_answer(self) -> None:
        source = self._menu_source("_text_menu")
        self.assertIn("Копіювати цю відповідь", source)
        self.assertIn("Виділити все", source)
        self.assertIn("Вставити в поле вводу", source)

    def test_selective_copy_uses_selection(self) -> None:
        """«Копіювати виділене» бере саме виділення, а не всю відповідь."""
        source = self._menu_source("_text_menu")
        self.assertIn("Копіювати виділене", source)
        self.assertIn("selection_get", source)


class TestLiveWidgets(unittest.TestCase):
    """Живі віджети: поле вводу й меню справді працюють."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _panel(self):
        import tkinter as tk

        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        host = tk.Frame(self.root)
        host.pack(fill="both", expand=True)
        panel = ChatPanel(host, self.fonts, Settings(), ToolRegistry(ROOT),
                          composer_parent=host)
        panel.pack(fill="both", expand=True)
        self.root.update()
        return panel, host

    def test_paste_into_input_works(self) -> None:
        panel, host = self._panel()
        try:
            panel.clipboard_clear()
            panel.clipboard_append("текст із буфера")
            panel._paste_into_input()
            self.assertEqual(panel.input_box.get("1.0", "end-1c"),
                             "текст із буфера")
        finally:
            host.destroy()

    def test_clear_input_works(self) -> None:
        panel, host = self._panel()
        try:
            panel.input_box.insert("1.0", "щось написано")
            panel._clear_input()
            self.assertEqual(panel.input_box.get("1.0", "end-1c").strip(), "")
        finally:
            host.destroy()

    def test_has_selection_detects_selection(self) -> None:
        panel, host = self._panel()
        try:
            panel.input_box.insert("1.0", "перевірка виділення")
            self.root.update()
            self.assertFalse(panel._has_selection())
            panel.input_box.tag_add("sel", "1.0", "1.8")
            self.root.update()
            self.assertTrue(panel._has_selection())
        finally:
            host.destroy()

    def test_clip_copy_puts_selection(self) -> None:
        panel, host = self._panel()
        try:
            panel.input_box.insert("1.0", "скопіюй мене")
            self.root.update()
            panel.input_box.tag_add("sel", "1.0", "1.8")
            panel._clip_copy()
            self.root.update()
            self.assertIn("скопіюй", str(panel.clipboard_get()))
        finally:
            host.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
