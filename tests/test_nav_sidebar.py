"""Тести навігаційної панелі: пункти, підпункти, історія, згортання.

``nav_sidebar`` — 421 рядок без жодного тесту. Модуль малює ліву колонку
навігації: розділи, підпункти, робочий проєкт і список сесій. Хоч у
поточному вікні використовується власна панель (``main_window``), модуль
лишається робочим API й має бути перевіреним.

Запуск: python -m unittest tests.test_nav_sidebar -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class NavTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)
        cls.fonts.apply()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def pump(self) -> None:
        self.root.update()

    def make(self, **kwargs):
        from blackchpok_ide import nav_sidebar

        panel = nav_sidebar.NavSidebar(self.root, self.fonts, **kwargs)
        panel.pack(fill="both", expand=True)
        self.pump()
        return panel


class TestConstants(unittest.TestCase):
    """Опис розділів і підпунктів."""

    def test_nav_items_present(self) -> None:
        from blackchpok_ide import nav_sidebar

        self.assertGreaterEqual(len(nav_sidebar.NAV_ITEMS), 5)

    def test_every_nav_item_is_complete(self) -> None:
        from blackchpok_ide import nav_sidebar

        for item in nav_sidebar.NAV_ITEMS:
            self.assertEqual(len(item), 4, item)
            key, icon, label, tip = item
            self.assertTrue(key, item)
            self.assertTrue(icon, item)
            self.assertTrue(label, item)
            self.assertTrue(tip, item)

    def test_nav_keys_are_unique(self) -> None:
        from blackchpok_ide import nav_sidebar

        keys = [item[0] for item in nav_sidebar.NAV_ITEMS]
        self.assertEqual(len(keys), len(set(keys)), "є дублікати ключів")

    def test_expected_sections_exist(self) -> None:
        from blackchpok_ide import nav_sidebar

        keys = {item[0] for item in nav_sidebar.NAV_ITEMS}
        for expected in ("chats", "mcp", "projects", "knowledge", "settings"):
            self.assertIn(expected, keys, f"немає розділу «{expected}»")

    def test_chat_scoped_modes_are_not_in_sidebar(self) -> None:
        """«Автономний» і «Автоматизації» не мають бути пунктами меню.

        Вони стосуються конкретного ЧАТУ й ПРОЄКТУ, а не всього застосунку.
        Як пункти меню вони виглядали глобальними перемикачами — і задачі
        лишались «сиротами» після видалення чату, бо ні до чого не були
        прив'язані. Тепер вони живуть у кнопці режиму чату
        (``chat_mode_menu``) і доступні як підпункти розділу «Чати».
        """
        from blackchpok_ide import nav_sidebar

        keys = {item[0] for item in nav_sidebar.NAV_ITEMS}
        self.assertNotIn("autonomous", keys,
                         "автономний режим належить чату, а не боковому меню")
        self.assertNotIn("automations", keys,
                         "автоматизації належать чату, а не боковому меню")

    def test_chat_modes_reachable_as_subitems(self) -> None:
        """Прибрані з меню режими лишаються доступними у розділі «Чати»."""
        from blackchpok_ide import nav_sidebar

        keys = {item[0] for item in nav_sidebar.SUB_ITEMS.get("chats", ())}
        for expected in ("cases", "queue", "autonomous", "skills"):
            self.assertIn(expected, keys,
                          f"підпункт «{expected}» має лишитись у розділі «Чати»")

    def test_chats_and_agents_are_one_section(self) -> None:
        """«Чати» й «Агенти» об'єднані: окремого розділу «agents» немає.

        Кожна розмова — це сесія агента, тож два пункти меню лише змушували
        перемикатись між двома списками того самого. Кроки агента живуть
        підпунктом розділу «Чати».
        """
        from blackchpok_ide import nav_sidebar

        keys = [item[0] for item in nav_sidebar.NAV_ITEMS]
        self.assertNotIn("agents", keys, "розділ «agents» має бути об'єднаний із «chats»")
        sub_keys = [entry[0] for entry in nav_sidebar.SUB_ITEMS.get("chats", ())]
        self.assertIn("cases", sub_keys,
                      "кроки агента мають бути підпунктом розділу «Чати»")

    def test_sub_items_reference_known_sections(self) -> None:
        from blackchpok_ide import nav_sidebar

        sections = {item[0] for item in nav_sidebar.NAV_ITEMS}
        for section, entries in nav_sidebar.SUB_ITEMS.items():
            self.assertIn(section, sections,
                          f"підпункти для невідомого розділу «{section}»")
            for entry in entries:
                self.assertEqual(len(entry), 4, entry)


class TestConstruction(NavTestBase):
    """Створення панелі."""

    def test_creates(self) -> None:
        panel = self.make()
        self.assertTrue(panel.winfo_exists())

    def test_brand_visible(self) -> None:
        panel = self.make()
        self.assertTrue(panel.brand_label.cget("text"))

    def test_new_session_button_present(self) -> None:
        panel = self.make()
        self.assertTrue(panel.new_session_btn.winfo_exists())

    def test_history_label_present(self) -> None:
        panel = self.make()
        self.assertIn("ІСТОРІЯ", str(panel.history_title.cget("text")).upper())

    def test_project_defaults_to_not_chosen(self) -> None:
        panel = self.make()
        self.assertIn("не обрано", str(panel.project_label.cget("text")).lower())


class TestNavigation(NavTestBase):
    """Кліки по розділах."""

    def test_navigate_calls_callback(self) -> None:
        seen: list[str] = []
        panel = self.make(on_navigate=seen.append)
        panel._navigate("chats")
        self.assertEqual(seen, ["chats"])

    def test_every_nav_button_exists(self) -> None:
        from blackchpok_ide import nav_sidebar

        panel = self.make()
        for key, _icon, _label, _tip in nav_sidebar.NAV_ITEMS:
            self.assertIn(key, panel._buttons, f"немає кнопки «{key}»")

    def test_new_session_callback(self) -> None:
        called: list[bool] = []
        panel = self.make(on_new_session=lambda: called.append(True))
        panel._new_session()
        self.assertTrue(called)

    def test_settings_callback(self) -> None:
        called: list[bool] = []
        panel = self.make(on_settings=lambda: called.append(True))
        panel._open_settings()
        self.assertTrue(called)

    def test_project_callback(self) -> None:
        called: list[bool] = []
        panel = self.make(on_open_project=lambda: called.append(True))
        panel._open_project()
        self.assertTrue(called)


class TestSetActive(NavTestBase):
    """Підсвітка активного розділу й підпунктів."""

    def test_set_active_marks_button(self) -> None:
        panel = self.make()
        panel.set_active("chats")
        self.assertEqual(panel._active, "chats")
        self.assertTrue(panel._buttons["chats"]._active)

    def test_set_active_shows_sub_items(self) -> None:
        from blackchpok_ide import nav_sidebar

        panel = self.make()
        panel.set_active("projects")
        self.pump()
        expected = {entry[0] for entry in nav_sidebar.SUB_ITEMS.get("projects", ())}
        self.assertEqual(set(panel._sub_buttons), expected)

    def test_set_active_without_sub_items(self) -> None:
        from blackchpok_ide import nav_sidebar

        panel = self.make()
        # «Автономний» — розділ без підпунктів: він не має нічого розгортати.
        self.assertEqual(nav_sidebar.SUB_ITEMS.get("autonomous", ()), ())
        panel.set_active("autonomous")
        self.pump()
        self.assertEqual(panel._sub_buttons, {})

    def test_switching_section_rebuilds_sub_items(self) -> None:
        panel = self.make()
        panel.set_active("projects")
        self.pump()
        first = set(panel._sub_buttons)
        panel.set_active("knowledge")
        self.pump()
        second = set(panel._sub_buttons)
        self.assertNotEqual(first, second)

    def test_set_sub_active(self) -> None:
        panel = self.make()
        panel.set_active("projects")
        self.pump()
        keys = list(panel._sub_buttons)
        if keys:
            panel.set_sub_active(keys[0])
            self.assertTrue(panel._sub_buttons[keys[0]]._active)


class TestProject(NavTestBase):
    """Робочий проєкт у підвалі."""

    def test_set_project_shows_folder_name(self) -> None:
        panel = self.make()
        panel.set_project(str(ROOT))
        self.assertEqual(str(panel.project_label.cget("text")), ROOT.name)

    def test_set_project_empty_shows_placeholder(self) -> None:
        panel = self.make()
        panel.set_project("")
        self.assertIn("не обрано", str(panel.project_label.cget("text")).lower())


class TestLocalState(NavTestBase):
    """Індикатор локального стану."""

    def test_set_local_state(self) -> None:
        panel = self.make()
        panel.set_local_state("працює локально", ok=True)
        self.assertIn("працює", str(panel.user_label.cget("text")))

    def test_set_local_state_error(self) -> None:
        panel = self.make()
        panel.set_local_state("немає зв'язку", ok=False)
        self.assertIn("немає", str(panel.user_label.cget("text")))


class TestHistory(NavTestBase):
    """Історія сесій."""

    def _store(self):
        import tempfile

        from blackchpok_ide.chat_store import ChatStore

        return ChatStore(Path(tempfile.mkdtemp()) / "chats.json")

    def test_empty_history_shows_message(self) -> None:
        panel = self.make(chat_store=self._store())
        panel.refresh_history()
        self.pump()
        texts = [str(child.cget("text")) for child in panel.history_host.winfo_children()
                 if child.winfo_class() == "Label"]
        self.assertTrue(any("немає" in text.lower() for text in texts), texts)

    def test_history_lists_sessions(self) -> None:
        store = self._store()
        store.create(title="Перша сесія")
        store.create(title="Друга сесія")
        panel = self.make(chat_store=store)
        panel.refresh_history()
        self.pump()
        rows = [child for child in panel.history_host.winfo_children()
                if child.winfo_class() == "Frame"]
        self.assertEqual(len(rows), 2)

    def test_history_click_opens_chat(self) -> None:
        store = self._store()
        chat = store.create(title="Клік")
        seen: list[str] = []
        panel = self.make(chat_store=store, on_open_chat=seen.append)
        panel.refresh_history(chat.id)
        self.pump()
        rows = [child for child in panel.history_host.winfo_children()
                if child.winfo_class() == "Frame"]
        self.assertTrue(rows)
        rows[0].event_generate("<Button-1>")
        self.pump()
        self.assertEqual(seen, [chat.id])

    def test_history_without_store_is_safe(self) -> None:
        panel = self.make()
        panel.refresh_history()
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_history_limits_to_forty(self) -> None:
        store = self._store()
        for index in range(50):
            store.create(title=f"Сесія {index}")
        panel = self.make(chat_store=store)
        panel.refresh_history()
        self.pump()
        rows = [child for child in panel.history_host.winfo_children()
                if child.winfo_class() == "Frame"]
        self.assertEqual(len(rows), 40)


class TestCollapse(NavTestBase):
    """Згортання до рейки."""

    def test_starts_expanded(self) -> None:
        panel = self.make()
        self.assertFalse(panel.collapsed)

    def test_toggle_collapses(self) -> None:
        panel = self.make()
        panel.toggle_collapsed(True)
        self.pump()
        self.assertTrue(panel.collapsed)

    def test_toggle_expands_back(self) -> None:
        panel = self.make()
        panel.toggle_collapsed(True)
        self.pump()
        panel.toggle_collapsed(False)
        self.pump()
        self.assertFalse(panel.collapsed)

    def test_collapsed_hides_history(self) -> None:
        panel = self.make()
        panel.toggle_collapsed(True)
        self.pump()
        # Вікно тесту приховане (withdraw), тому winfo_ismapped() завжди 0 —
        # перевіряємо, чи віджет справді знято з менеджера пакування.
        self.assertFalse(bool(panel.history_scroll.winfo_manager()))

    def test_expanded_restores_history(self) -> None:
        panel = self.make()
        panel.toggle_collapsed(True)
        self.pump()
        self.assertFalse(bool(panel.history_scroll.winfo_manager()))
        panel.toggle_collapsed(False)
        self.pump()
        self.assertEqual(panel.history_scroll.winfo_manager(), "pack",
                         "після розгортання історія має повернутись")

    def test_collapsed_keeps_new_session_button(self) -> None:
        panel = self.make()
        panel.toggle_collapsed(True)
        self.pump()
        self.assertTrue(panel.new_session_btn.winfo_exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
