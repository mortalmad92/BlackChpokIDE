"""Тести redesign-у: статуси сесій, diff-картка, live-інструменти, тема.

Запуск: python -m unittest tests.test_redesign -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import theme  # noqa: E402
from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry  # noqa: E402
from blackchpok_ide.chat_panel import make_diff_lines  # noqa: E402
from blackchpok_ide.chat_store import (  # noqa: E402
    STATUS_DONE,
    STATUS_IDLE,
    STATUS_QUEUED,
    STATUS_WORKING,
    Chat,
    ChatStore,
    normalise_status,
)


class TestChatStatus(unittest.TestCase):
    """Статуси сесій агентів у сховищі чатів."""

    def setUp(self) -> None:
        self.store = ChatStore(Path(tempfile.mkdtemp()) / "chats.json")

    def test_default_status_is_idle(self) -> None:
        chat = self.store.create("тест")
        self.assertEqual(chat.status, STATUS_IDLE)

    def test_status_roundtrip(self) -> None:
        chat = self.store.create("тест")
        self.assertTrue(self.store.set_status(chat.id, STATUS_WORKING))
        self.assertEqual(self.store.get(chat.id).status, STATUS_WORKING)
        self.assertTrue(self.store.set_status(chat.id, STATUS_DONE))
        self.assertEqual(self.store.get(chat.id).status, STATUS_DONE)
        # Серіалізація зберігає статус.
        data = self.store.get(chat.id).to_dict()
        self.assertEqual(data["status"], STATUS_DONE)
        restored = Chat.from_dict(data)
        self.assertEqual(restored.status, STATUS_DONE)

    def test_unknown_status_falls_back(self) -> None:
        self.assertEqual(normalise_status("сміття"), STATUS_IDLE)
        self.assertEqual(normalise_status(None), STATUS_IDLE)
        self.assertEqual(normalise_status("queued"), STATUS_QUEUED)
        self.assertEqual(normalise_status("WORKING"), STATUS_WORKING)

    def test_missing_chat_returns_false(self) -> None:
        self.assertFalse(self.store.set_status("немає", STATUS_WORKING))


class TestDiffLines(unittest.TestCase):
    """Рядки diff для картки змін."""

    def test_add_and_del(self) -> None:
        rows = make_diff_lines("a\nb\nc\n", "a\nd\nc\n")
        kinds = {kind for kind, _text in rows}
        self.assertIn("add", kinds)
        self.assertIn("del", kinds)
        dels = [text for kind, text in rows if kind == "del"]
        adds = [text for kind, text in rows if kind == "add"]
        self.assertIn("b", dels)
        self.assertIn("d", adds)

    def test_no_change_gives_empty(self) -> None:
        self.assertEqual(make_diff_lines("однаково\n", "однаково\n"), [])

    def test_empty_inputs(self) -> None:
        rows = make_diff_lines("", "новий файл\n")
        self.assertTrue(any(kind == "add" and "новий файл" in text
                            for kind, text in rows))


class TestLiveTools(unittest.TestCase):
    """Live-інструменти агента: схеми, відмова без контролера, запуск."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.registry = ToolRegistry(self.tmp)

    def test_schemas_present(self) -> None:
        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        for required in ("app_start", "app_stop", "app_restart", "app_status",
                         "app_screenshot", "app_click", "app_type", "app_key"):
            self.assertIn(required, names)

    def test_without_controller_rejects(self) -> None:
        result = self.registry.call("app_start", {})
        self.assertFalse(result.ok)
        self.assertIn("не підключене", result.output)

    def test_start_stop_static_site(self) -> None:
        site = self.tmp / "site"
        site.mkdir()
        (site / "index.html").write_text("<h1>тест</h1>", encoding="utf-8")
        from blackchpok_ide.app_control import AppController

        controller = AppController(lambda: site)
        self.registry.attach_app_controller(controller)
        started = self.registry.call("app_start", {})
        self.assertTrue(started.ok, started.output)
        self.assertIn("http://127.0.0.1:", started.output)
        status = self.registry.call("app_status", {})
        self.assertTrue(status.ok)
        self.assertIn("запущено", status.output)
        stopped = self.registry.call("app_stop", {})
        self.assertTrue(stopped.ok)
        self.assertFalse(controller.running)

    def test_screenshot_saves_png(self) -> None:
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow не встановлено")
        from blackchpok_ide.app_control import take_screenshot

        target = self.tmp / "shot.png"
        answer = take_screenshot(path=str(target))
        self.assertIn("Скріншот", answer)
        self.assertTrue(target.exists())


class TestThemeModes(unittest.TestCase):
    """Дві палітри теми."""

    def test_light_palette(self) -> None:
        theme.set_mode("light")
        self.assertEqual(theme.BG, "#f7f6f2")
        self.assertEqual(theme.FG, "#26251e")
        self.assertTrue(theme.DIFF_ADD_FG and theme.DIFF_DEL_FG)
        self.assertEqual(theme.current_mode(), "light")

    def test_dark_palette(self) -> None:
        theme.set_mode("dark")
        self.assertEqual(theme.BG, "#17171a")
        self.assertEqual(theme.current_mode(), "dark")
        theme.set_mode("light")

    def test_palette_keys_complete(self) -> None:
        for mode, palette in theme.PALETTES.items():
            for key in ("BG", "FG", "ACCENT", "BTN_BG", "STATUS_WORKING",
                        "DIFF_ADD_BG", "CHAT_OK"):
                self.assertIn(key, palette, f"{mode}/{key}")

    def test_role_roundtrip(self) -> None:
        """role_of/value_of: колір → роль → колір нової теми."""
        theme.set_mode("light")
        self.assertEqual(theme.role_of("#f7f6f2"), "BG")
        self.assertEqual(theme.role_of("#ffffff"), "BG_INPUT")
        self.assertEqual(theme.role_of("#немає-такого"), "")
        self.assertEqual(theme.value_of("BG_INPUT", "x"), "#ffffff")
        theme.set_mode("dark")
        self.assertEqual(theme.value_of("BG_INPUT", "x"), "#1e1e22")
        self.assertEqual(theme.value_of("", "запас"), "запас")
        theme.set_mode("light")

    def test_hover_resolves_after_theme_switch(self) -> None:
        """Наведення після перемикання теми не повертає світлих плашок."""
        import tkinter as tk

        from blackchpok_ide.nav_sidebar import NavButton
        from blackchpok_ide.widgets import Chip

        root = tk.Tk()
        root.withdraw()
        fonts = theme.Theme(root)
        fonts.apply()
        try:
            chip = Chip(root, "кнопка")
            nav = NavButton(root, "◍", "розділ")
            root.update()
            theme.switch_mode("dark", root=root, theme_obj=fonts)
            root.update()
            chip._on_enter()
            self.assertEqual(chip.cget("background"), theme.BG_HOVER)
            chip._on_leave()
            self.assertEqual(chip.cget("background"), theme.BG_INPUT)
            nav._on_enter()
            self.assertEqual(nav.cget("background"), theme.BG_HOVER)
            nav._on_leave()
            # Зворотний хід: темна → світла.
            theme.switch_mode("light", root=root, theme_obj=fonts)
            root.update()
            chip._on_enter()
            self.assertEqual(chip.cget("background"), theme.BG_HOVER)
            chip._on_leave()
        finally:
            theme.set_mode("light")
            root.destroy()


if __name__ == "__main__":
    unittest.main()
