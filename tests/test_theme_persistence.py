"""Тести теми: типова темна, збереження вибору, перефарбування синтаксису.

Запуск: python -m unittest tests.test_theme_persistence -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import theme  # noqa: E402
from blackchpok_ide.config import Settings, UISettings  # noqa: E402


class TestDefaultTheme(unittest.TestCase):
    """Тема за замовчуванням — темна."""

    def tearDown(self) -> None:
        theme.set_mode(theme.DEFAULT_MODE)

    def test_theme_module_default_is_dark(self) -> None:
        self.assertEqual(theme.DEFAULT_MODE, "dark")

    def test_ui_settings_default_is_dark(self) -> None:
        self.assertEqual(UISettings().theme, "dark")

    def test_new_settings_load_as_dark(self) -> None:
        folder = Path(tempfile.mkdtemp())
        target = folder / "settings.json"
        # Файлу ще немає — беремо типові значення.
        settings = Settings.load(target)
        self.assertEqual(settings.ui.theme, "dark")

    def test_default_mode_matches_palette(self) -> None:
        theme.set_mode(theme.DEFAULT_MODE)
        self.assertEqual(theme.current_mode(), "dark")
        self.assertEqual(theme.BG, theme.PALETTES["dark"]["BG"])


class TestThemePersistence(unittest.TestCase):
    """Вибір теми переживає перезапуск."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.path = self.folder / "settings.json"

    def tearDown(self) -> None:
        theme.set_mode(theme.DEFAULT_MODE)

    def test_dark_survives_save_and_load(self) -> None:
        settings = Settings()
        settings.ui.theme = "dark"
        settings.save(self.path)
        self.assertEqual(Settings.load(self.path).ui.theme, "dark")

    def test_light_survives_save_and_load(self) -> None:
        settings = Settings()
        settings.ui.theme = "light"
        settings.save(self.path)
        self.assertEqual(Settings.load(self.path).ui.theme, "light")

    def test_theme_written_to_json(self) -> None:
        settings = Settings()
        settings.ui.theme = "light"
        settings.save(self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["ui"]["theme"], "light")

    def test_broken_theme_falls_back_to_dark(self) -> None:
        settings = Settings()
        settings.save(self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["ui"]["theme"] = "невідома-тема"
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(Settings.load(self.path).ui.theme, "dark")

    def test_missing_theme_key_falls_back_to_dark(self) -> None:
        settings = Settings()
        settings.save(self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["ui"].pop("theme", None)
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(Settings.load(self.path).ui.theme, "dark")


class TestSyntaxColoursFollowTheme(unittest.TestCase):
    """Підсвітка синтаксису оновлюється разом із темою."""

    def tearDown(self) -> None:
        theme.set_mode(theme.DEFAULT_MODE)

    def test_syntax_switches_with_mode(self) -> None:
        theme.set_mode("light")
        light_keyword = theme.SYNTAX_COLORS["keyword"]
        theme.set_mode("dark")
        dark_keyword = theme.SYNTAX_COLORS["keyword"]
        self.assertNotEqual(light_keyword, dark_keyword,
                            "кольори синтаксису мають змінюватись разом із темою")
        self.assertEqual(dark_keyword, theme.SYNTAX_DARK["keyword"])
        theme.set_mode("light")
        self.assertEqual(theme.SYNTAX_COLORS["keyword"], theme.SYNTAX_LIGHT["keyword"])

    def test_switch_mode_updates_syntax(self) -> None:
        theme.set_mode("light")
        theme.switch_mode("dark")
        self.assertEqual(theme.SYNTAX_COLORS["keyword"], theme.SYNTAX_DARK["keyword"])
        theme.switch_mode("light")
        self.assertEqual(theme.SYNTAX_COLORS["keyword"], theme.SYNTAX_LIGHT["keyword"])

    def test_all_syntax_keys_present_in_both_modes(self) -> None:
        self.assertEqual(set(theme.SYNTAX_LIGHT), set(theme.SYNTAX_DARK))


class TestCanvasHeightBudget(unittest.TestCase):
    """Стрічка не перевищує межу координат Canvas у Tk."""

    def test_budget_is_below_tk_limit(self) -> None:
        from blackchpok_ide.widgets import ScrollFrame

        # Tk не малює вміст нижче ~32767 px; тримаємось із запасом.
        self.assertLessEqual(ScrollFrame.MAX_CANVAS_HEIGHT, 24000)
        self.assertGreaterEqual(ScrollFrame.MAX_CANVAS_HEIGHT, 8000)

    def test_chat_panel_trims_to_budget(self) -> None:
        source = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        self.assertIn("_trim_to_height", source)
        self.assertIn("MAX_CANVAS_HEIGHT", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
