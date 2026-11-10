"""Ліва панель — тільки чати; решта розділів живе в налаштуваннях.

Раніше ліворуч стояло меню з п'яти пунктів: «Чати й агенти», «MCP Tools»,
«Проєкти», «База знань», «Налаштування». Колонка існує для розмов, а ці
пункти забирали в неї місце й збивали з пантелику: «Проєкти» й «База
знань» виглядали як чати, хоч це панелі.

Тепер:

* ліворуч — «Новий чат», пошук і список розмов;
* усі панелі програми — у діалозі налаштувань, вкладка **«Розділи»**;
* у меню «Вигляд» лишились ті самі дії з гарячими клавішами.

Запуск: python -m unittest tests.test_sidebar_chats_only -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestSidebarHasNoSectionMenu(unittest.TestCase):
    """Меню розділів прибрано з лівої панелі."""

    def test_no_nav_buttons_in_sidebar(self) -> None:
        """У вікні не має лишатись жодної кнопки розділу."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_sidebar)
        self.assertNotIn("NAV_ITEMS", source,
                         "ліва панель не має будувати меню розділів")
        self.assertIn("self._nav_buttons: dict[str, nav_sidebar.NavButton] = {}",
                      source,
                      "словник кнопок має лишитись (порожній) для сумісності")

    def test_sidebar_keeps_new_chat_and_list(self) -> None:
        """Головне, що має лишитись: кнопка нового чату й список сесій."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_sidebar)
        self.assertIn("new_session_btn", source)
        self.assertIn("ChatListPanel", source)

    def test_panel_titles_are_not_drawn_for_chats(self) -> None:
        """Заголовок панелі не дублює вкладку «ЧАТИ Й АГЕНТИ»."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._paint_panel_title)
        self.assertIn('key == "chats"', source,
                      "для чатів заголовок має бути порожній")

    def test_panel_home_returns_to_chats(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._panel_home)
        self.assertIn('"chats"', source)

    def test_sync_rail_state_survives_no_buttons(self) -> None:
        """Без кнопок підсвітка не має падати."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._sync_rail_state)
        self.assertNotIn("_nav_buttons", source)


class TestSettingsSectionsTab(unittest.TestCase):
    """Вкладка «Розділи» в налаштуваннях містить усі панелі."""

    def _sections(self) -> dict[str, str]:
        from blackchpok_ide.settings_dialog import SettingsDialog

        return {key: label for key, label, _tip in SettingsDialog.SECTIONS}

    def test_sections_cover_all_panels(self) -> None:
        sections = self._sections()
        for key in ("mcp", "tools", "explorer", "changes", "rag", "queue",
                    "skills", "autonomous", "cases", "outline"):
            self.assertIn(key, sections, f"немає розділу «{key}»")

    def test_every_section_has_label_and_tip(self) -> None:
        from blackchpok_ide.settings_dialog import SettingsDialog

        for key, label, tip in SettingsDialog.SECTIONS:
            self.assertTrue(label.strip(), key)
            self.assertTrue(tip.strip(), key)

    def test_tab_is_built(self) -> None:
        import inspect

        from blackchpok_ide.settings_dialog import SettingsDialog

        source = inspect.getsource(SettingsDialog._build)
        self.assertIn("_sections_tab", source)
        self.assertIn("Розділи", source)

    def test_panel_callback_is_wired(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE.open_settings)
        self.assertIn("on_open_panel", source,
                      "діалог має вміти відкривати панелі")
        self.assertIn("on_first_run", source)

    def test_open_panel_shows_side(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._open_panel_from_settings)
        self.assertIn("show_side", source)

    def test_dialog_closes_before_opening_panel(self) -> None:
        """Інакше панель відкриється під модальним діалогом."""
        import ast
        import inspect
        import textwrap

        from blackchpok_ide.settings_dialog import SettingsDialog

        tree = ast.parse(textwrap.dedent(inspect.getsource(SettingsDialog._open_panel)))
        order: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            order.setdefault(name, node.lineno)
        self.assertIn("destroy", order)
        self.assertIn("callback", order)
        self.assertLess(order["destroy"], order["callback"],
                        "спершу закрити діалог, потім відкривати панель")


class TestMenuStillProvidesSections(unittest.TestCase):
    """Меню «Вигляд» лишається шляхом до тих самих панелей."""

    def test_view_menu_has_panels(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_menu)
        for panel in ("mcp", "rag", "queue", "skills", "cases", "tools"):
            self.assertIn(f'show_side("{panel}")', source, panel)

    def test_settings_in_view_menu(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_menu)
        self.assertIn("open_settings", source)


class TestPanelsStillReachable(unittest.TestCase):
    """Жодна панель не загубилась: усі є в стеці сайдбара."""

    def test_side_widgets_cover_sections(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_sidebar)
        for key in ("chats", "mcp", "tools", "explorer", "changes", "rag",
                    "queue", "skills", "autonomous", "cases", "outline"):
            self.assertIn(f'"{key}":', source, key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
