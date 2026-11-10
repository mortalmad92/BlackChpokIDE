"""Регресії модальних вікон і спливних карток.

Знайдено зі скріншота користувача: картка «Модель» лишалась на екрані,
коли зверху відкривався діалог «Налаштування». Два вікна одночасно,
введення губилось — програма виглядала завислою.

Причини, які тут зафіксовані:

1. попапи не закривались перед відкриттям модального діалогу;
2. реєстр попапів очищався сам: ``<Destroy>`` приходить і від дочірніх
   віджетів, тож картка вилучала себе з реєстру одразу після побудови;
3. діалоги позиціювались без перевірки меж екрана й виїжджали за край;
4. два модальні вікна могли захопити введення одночасно.

Запуск: python -m unittest tests.test_modal_windows -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _tk_or_skip(case: unittest.TestCase):
    import tkinter as tk

    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError as exc:  # pragma: no cover - без дисплея
        raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc


class TestClampToScreen(unittest.TestCase):
    """Позиція вікна завжди лишається в межах екрана."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _tk_or_skip(cls)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _clamp(self, x, y, width=400, height=300):
        from blackchpok_ide import widgets

        return widgets.clamp_to_screen(self.root, x, y, width, height)

    def test_negative_position_is_moved_inside(self) -> None:
        x, y = self._clamp(-500, -300)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)

    def test_huge_position_is_pulled_back(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x, y = self._clamp(screen_w + 900, screen_h + 900)
        self.assertLessEqual(x + 400, screen_w + 8)
        self.assertLessEqual(y + 300, screen_h + 8)

    def test_normal_position_kept(self) -> None:
        x, y = self._clamp(120, 90)
        self.assertEqual((x, y), (120, 90))

    def test_window_fits_right_edge(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x, y = self._clamp(screen_w - 50, screen_h - 50, width=800, height=600)
        self.assertLessEqual(x + 800, screen_w + 8)
        self.assertLessEqual(y + 600, screen_h + 8)


class TestPopoverRegistry(unittest.TestCase):
    """Реєстр спливних карток працює й не очищається сам."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _tk_or_skip(cls)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_registered_popover_survives_children_destroy(self) -> None:
        import tkinter as tk

        from blackchpok_ide import widgets

        window = tk.Toplevel(self.root)
        child = tk.Label(window, text="всередині")
        child.pack()
        widgets.register_popover(window)
        try:
            self.assertIn(window, widgets._POPOVERS)
            # Знищення ДОЧІРНЬОГО віджета не має вилучати картку з реєстру:
            # саме через це модальні діалоги не закривали картку.
            child.destroy()
            self.root.update()
            self.assertIn(window, widgets._POPOVERS,
                          "картка вилучилась із реєстру через дочірній <Destroy>")
        finally:
            widgets.unregister_popover(window)
            try:
                window.destroy()
            except tk.TclError:
                pass

    def test_close_popovers_closes_registered(self) -> None:
        import tkinter as tk

        from blackchpok_ide import widgets

        window = tk.Toplevel(self.root)
        window.deiconify()
        widgets.register_popover(window)
        closed = widgets.close_popovers()
        try:
            self.assertGreaterEqual(closed, 1)
            self.assertEqual(window.state(), "withdrawn")
        finally:
            widgets.unregister_popover(window)
            try:
                window.destroy()
            except tk.TclError:
                pass

    def test_is_popover_widget_detects_child(self) -> None:
        import tkinter as tk

        from blackchpok_ide import widgets

        window = tk.Toplevel(self.root)
        child = tk.Label(window, text="дочірній")
        child.pack()
        widgets.register_popover(window)
        try:
            self.assertTrue(widgets.is_popover_widget(child))
            self.assertFalse(widgets.is_popover_widget(self.root))
        finally:
            widgets.unregister_popover(window)
            try:
                window.destroy()
            except tk.TclError:
                pass


class TestModalExclusivity(unittest.TestCase):
    """Лише одне модальне вікно може тримати введення."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _tk_or_skip(cls)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_second_modal_is_rejected(self) -> None:
        import tkinter as tk

        from blackchpok_ide import widgets

        first = tk.Toplevel(self.root)
        second = tk.Toplevel(self.root)
        try:
            self.assertTrue(widgets.open_only_modal(first))
            self.assertIs(widgets.active_modal(), first)
            self.assertFalse(widgets.open_only_modal(second),
                             "друге модальне вікно не має захоплювати введення")
        finally:
            widgets.release_modal(first)
            for window in (first, second):
                try:
                    window.destroy()
                except tk.TclError:
                    pass

    def test_release_allows_next_modal(self) -> None:
        import tkinter as tk

        from blackchpok_ide import widgets

        first = tk.Toplevel(self.root)
        second = tk.Toplevel(self.root)
        try:
            widgets.open_only_modal(first)
            widgets.release_modal(first)
            self.assertIsNone(widgets.active_modal())
            self.assertTrue(widgets.open_only_modal(second))
        finally:
            widgets.release_modal(second)
            for window in (first, second):
                try:
                    window.destroy()
                except tk.TclError:
                    pass


class TestDialogsUseHelpers(unittest.TestCase):
    """Діалоги мають використовувати спільні помічники, а не ``geometry``."""

    def _source(self, name: str) -> str:
        return (ROOT / "blackchpok_ide" / name).read_text(encoding="utf-8")

    def test_settings_dialog_uses_open_only_modal(self) -> None:
        source = self._source("settings_dialog.py")
        self.assertIn("open_only_modal", source)
        self.assertNotIn("self.grab_set()", source)

    def test_settings_dialog_positions_window(self) -> None:
        source = self._source("settings_dialog.py")
        self.assertIn("place_window", source)

    def test_palette_uses_helpers(self) -> None:
        source = self._source("palette.py")
        self.assertIn("open_only_modal", source)
        self.assertIn("place_window", source)

    def test_first_run_centres_on_screen(self) -> None:
        source = self._source("first_run.py")
        self.assertIn("place_window", source)

    def test_popovers_register_themselves(self) -> None:
        for name in ("model_selector.py", "model_menu.py", "modes_menu.py",
                     "command_menu.py", "context_popover.py"):
            source = self._source(name)
            self.assertIn("register_popover", source, f"{name} не реєструє попап")

    def test_window_generators_clamp_position(self) -> None:
        for name in ("model_selector.py", "model_menu.py", "modes_menu.py",
                     "command_menu.py", "context_popover.py"):
            source = self._source(name)
            self.assertIn("clamp_to_screen", source, f"{name} не обмежує позицію")


if __name__ == "__main__":
    unittest.main(verbosity=2)
