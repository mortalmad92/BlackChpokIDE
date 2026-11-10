"""Тести панелі структури файлу й керування застосунком.

Два модулі без тестів:

* ``outline_panel`` — символи поточного файлу з живого AST;
* ``app_control`` — запуск/зупинка застосунку проєкту, скріншоти, кліки.

``app_control`` перевіряємо обережно: реальні кліки й скріншоти робимо
лише там, де це безпечно, решту — на рівні «виклик не падає й повертає
зрозумілий текст».

Запуск: python -m unittest tests.test_outline_and_control -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestOutlinePanel(unittest.TestCase):
    """Структура файлу: символи з AST."""

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

    def _panel(self):
        from blackchpok_ide import outline_panel

        panel = outline_panel.OutlinePanel(self.root, self.fonts)
        panel.pack(fill="both", expand=True)
        self.root.update()
        return panel

    def test_creates(self) -> None:
        panel = self._panel()
        self.assertTrue(panel.winfo_exists())

    def test_update_without_editor_is_safe(self) -> None:
        panel = self._panel()
        # Панель має пережити виклик без відкритого редактора.
        if hasattr(panel, "update_for"):
            panel.update_for(None)
            self.root.update()
        self.assertTrue(panel.winfo_exists())

    def test_update_with_real_editor(self) -> None:
        from blackchpok_ide import outline_panel
        from blackchpok_ide.config import Settings
        from blackchpok_ide.tabs import EditorTabs

        settings = Settings()
        settings.workspace = str(ROOT)
        tabs = EditorTabs(self.root, self.fonts, settings)
        tabs.pack(fill="both", expand=True)
        self.root.update()
        path = ROOT / "blackchpok_ide" / "chat_store.py"
        tabs.open_file(path)
        self.root.update()

        panel = self._panel()
        panel.update_for(tabs.current())
        self.root.update()
        self.assertTrue(panel.winfo_exists())

    def test_on_goto_callback_is_stored(self) -> None:
        from blackchpok_ide import outline_panel

        seen: list[int] = []
        panel = outline_panel.OutlinePanel(self.root, self.fonts, on_goto=seen.append)
        panel.pack(fill="both", expand=True)
        self.root.update()
        self.assertIsNotNone(panel.on_goto)

    def test_filter_query_is_safe(self) -> None:
        from blackchpok_ide import outline_panel

        panel = self._panel()
        if hasattr(panel, "_on_query"):
            panel.query = "def"
            panel._on_query()
            self.root.update()
        self.assertTrue(panel.winfo_exists())


class TestAppControlBasics(unittest.TestCase):
    """Керування застосунком: безпечні операції."""

    def setUp(self) -> None:
        from blackchpok_ide import app_control

        self.mod = app_control
        self.folder = Path(tempfile.mkdtemp())
        self.controller = app_control.AppController(lambda: self.folder)

    def tearDown(self) -> None:
        try:
            self.controller.on_close()
        except Exception:  # noqa: BLE001
            pass

    def test_controller_starts_stopped(self) -> None:
        self.assertFalse(self.controller.running)

    def test_url_empty_when_stopped(self) -> None:
        self.assertEqual(self.controller.url, "")

    def test_describe_returns_text(self) -> None:
        text = self.controller.describe()
        self.assertIsInstance(text, str)
        self.assertTrue(text)

    def test_detect_without_project_returns_none_or_recipe(self) -> None:
        # Порожня тека: рецепт може бути None або невдалим — головне без винятку.
        recipe = self.controller.detect()
        self.assertTrue(recipe is None or hasattr(recipe, "ok"))

    def test_detect_finds_static_site(self) -> None:
        (self.folder / "index.html").write_text("<h1>тест</h1>", encoding="utf-8")
        recipe = self.controller.detect()
        self.assertIsNotNone(recipe)
        self.assertTrue(recipe.ok, getattr(recipe, "reason", ""))

    def test_logs_without_server(self) -> None:
        self.assertTrue(self.controller.logs())

    def test_stop_when_not_running_is_safe(self) -> None:
        self.assertTrue(self.controller.stop())

    def test_missing_root_provider_is_safe(self) -> None:
        controller = self.mod.AppController(lambda: None)
        try:
            recipe = controller.detect()
            self.assertIsNone(recipe)
        finally:
            controller.on_close()

    def test_start_on_empty_folder_fails_gracefully(self) -> None:
        ok, detail = self.controller.start()
        self.assertFalse(ok)
        self.assertTrue(detail, "має бути причина відмови")


class TestAppControlScreenshot(unittest.TestCase):
    """Скріншоти й пошук вікна."""

    def setUp(self) -> None:
        from blackchpok_ide import app_control

        self.mod = app_control

    def test_find_window_returns_int(self) -> None:
        self.assertIsInstance(self.mod.find_window("вигадане вікно 12345"), int)

    def test_find_window_missing_returns_zero(self) -> None:
        self.assertEqual(self.mod.find_window("вигадане вікно 12345"), 0)

    def test_window_rect_of_missing_is_zeros(self) -> None:
        self.assertEqual(self.mod.window_rect(0), (0, 0, 0, 0))

    def test_screenshot_of_missing_window_reports_error(self) -> None:
        text = self.mod.take_screenshot("вигадане вікно 12345")
        self.assertIn("✗", text)

    def test_click_outside_windows_reports(self) -> None:
        # На не-Windows має бути відмова; на Windows — спроба без винятку.
        text = self.mod.click_at(0, 0)
        self.assertIsInstance(text, str)
        self.assertTrue(text)

    def test_press_key_unknown_reports(self) -> None:
        text = self.mod.press_key("неіснуюча-клавіша")
        self.assertIn("✗", text)

    def test_type_empty_text_reports(self) -> None:
        text = self.mod.type_text("")
        self.assertIn("✗", text)


class TestScreenshotToFile(unittest.TestCase):
    """Скріншот у вказаний файл."""

    def test_saves_png_to_given_path(self) -> None:
        from blackchpok_ide import app_control

        target = Path(tempfile.mkdtemp()) / "shot.png"
        try:
            text = app_control.take_screenshot("", str(target))
        except Exception as exc:  # noqa: BLE001 - без дисплея можливо
            self.skipTest(f"скріншот недоступний: {exc}")
        if "✗" in text:
            self.skipTest(f"скріншот недоступний: {text[:60]}")
        self.assertTrue(target.exists(), text)
        self.assertGreater(target.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
