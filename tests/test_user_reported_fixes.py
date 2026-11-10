"""Тести виправлень з реального логу й скарг користувача.

Кожен тест тут — конкретний дефект, який користувач бачив на екрані:

1. **дублювання моделей** — та сама модель стояла тричі під різними
   провайдерами (скріншот 83);
2. **вставка в пошук хаба** — «навіть через Ctrl+V не можу вставити»,
   правого меню немає (скріншот 86);
3. **панель не розтягується** — «та панель не розтягується за допомогою
   миші» (скріншот 85).

Запуск: python -m unittest tests.test_user_reported_fixes -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import providers, widgets  # noqa: E402


def _entry(name: str, *, provider: str = "lmstudio", online: bool = False,
           path: str = "", label: str = "LM Studio") -> providers.ModelEntry:
    return providers.ModelEntry(
        name=name, provider_key=provider, provider_label=label,
        kind=providers.LOCAL, online=online, path=path)


class TestModelDuplication(unittest.TestCase):
    """Одна модель — один рядок у списку вибору."""

    def test_same_name_from_two_servers_is_one_entry(self) -> None:
        name = "qwen2.5-coder-14b-instruct-q4_k_m"
        entries = [
            _entry(name, provider="lmstudio", online=True),
            _entry(name, provider="llamacpp", label="llama.cpp"),
        ]
        unique = providers._dedupe(entries)          # noqa: SLF001 - прямий тест
        self.assertEqual(len(unique), 1, [item.provider_label for item in unique])

    def test_online_entry_wins(self) -> None:
        name = "model-x"
        entries = [
            _entry(name, provider="llamacpp", online=False),
            _entry(name, provider="lmstudio", online=True),
        ]
        unique = providers._dedupe(entries)          # noqa: SLF001
        self.assertTrue(unique[0].online)
        self.assertEqual(unique[0].provider_key, "lmstudio")

    def test_path_is_merged_from_disk_entry(self) -> None:
        """Онлайн-запис не має шляху, дисковий має — після злиття є обидва."""
        name = "model-y"
        entries = [
            _entry(name, online=True),
            _entry(name, path=r"C:\models\model-y.gguf"),
        ]
        unique = providers._dedupe(entries)          # noqa: SLF001
        self.assertEqual(len(unique), 1)
        self.assertTrue(unique[0].online)
        self.assertTrue(unique[0].path, "шлях мав перейти від дискового запису")

    def test_separators_do_not_make_new_model(self) -> None:
        first = _entry("Qwen2.5-Coder-7B")
        second = _entry("qwen2.5_coder_7b")
        self.assertEqual(providers.model_key(first), providers.model_key(second))

    def test_different_quant_is_a_different_model(self) -> None:
        first = _entry("model-q4_k_m")
        second = _entry("model-q8_0")
        self.assertNotEqual(providers.model_key(first), providers.model_key(second))

    def test_projectors_are_not_models(self) -> None:
        entries = [
            _entry("qwen2.5-vl-3b"),
            _entry("mmproj-qwen2.5-vl-3b-f16"),
        ]
        kept = [item for item in providers._dedupe(entries)  # noqa: SLF001
                if not providers.is_projector(item)]
        self.assertEqual([item.name for item in kept], ["qwen2.5-vl-3b"])

    def test_is_projector_marker(self) -> None:
        self.assertTrue(providers.is_projector(_entry("mmproj-model-f16")))
        self.assertFalse(providers.is_projector(_entry("qwen2.5-coder-7b")))


class TestClipboardActions(unittest.TestCase):
    """Ctrl+C/V/X/A і праве меню працюють у полях введення.

    Один корінь Tk на весь клас: створювати й знищувати ``tk.Tk()`` на
    кожен тест на Windows небезпечно — процес падає з access violation
    під час збирання сміття, і весь прогін обривається.
    """

    root = None

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except Exception as exc:                 # noqa: BLE001
            raise unittest.SkipTest(f"немає дисплея: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        root = cls.root
        cls.root = None
        if root is not None:
            try:
                root.destroy()
            except Exception:                    # noqa: BLE001
                pass

    def _entry_widget(self):
        import tkinter as tk

        entry = tk.Entry(self.root)
        entry.pack()
        widgets.attach_edit_actions(entry)
        self.root.update()
        self.addCleanup(entry.destroy)
        return entry

    def test_paste_works(self) -> None:
        entry = self._entry_widget()
        self.root.clipboard_clear()
        self.root.clipboard_append("Ministral 3B")
        self.root.update()
        self.assertTrue(widgets.clipboard_paste(entry))
        self.assertEqual(entry.get(), "Ministral 3B")

    def test_copy_works(self) -> None:
        entry = self._entry_widget()
        entry.insert(0, "текст")
        entry.selection_range(0, "end")
        self.assertEqual(widgets.clipboard_copy(entry), "текст")

    def test_cut_clears_field(self) -> None:
        entry = self._entry_widget()
        entry.insert(0, "вирізати")
        widgets.clipboard_select_all(entry)
        self.root.update()
        self.assertEqual(widgets.clipboard_cut(entry), "вирізати")
        self.assertEqual(entry.get(), "")

    def test_select_all(self) -> None:
        entry = self._entry_widget()
        entry.insert(0, "abc")
        widgets.clipboard_select_all(entry)
        self.root.update()
        self.assertEqual(entry.selection_get(), "abc")

    def test_readonly_field_ignores_paste(self) -> None:
        import tkinter as tk

        entry = tk.Entry(self.root)
        entry.insert(0, "фіксований")
        widgets.attach_edit_actions(entry, readonly=True)
        self.root.clipboard_clear()
        self.root.clipboard_append("зайве")
        self.root.update()
        self.assertFalse(widgets.clipboard_paste(entry))
        self.assertEqual(entry.get(), "фіксований")

    def test_bindings_installed(self) -> None:
        entry = self._entry_widget()
        bindings = " ".join(item.lower() for item in entry.bind())
        for sequence in ("control-key-v", "control-key-c", "control-key-x",
                         "control-key-a", "button-3"):
            self.assertIn(sequence, bindings, f"немає прив'язки {sequence}")

    def test_empty_clipboard_returns_false(self) -> None:
        import tkinter as tk

        entry = tk.Entry(self.root)
        widgets.attach_edit_actions(entry)

        class NoClipboard:
            def clipboard_get(self, *_args, **_kwargs):
                raise tk.TclError("порожній")

        self.assertFalse(widgets.clipboard_paste(NoClipboard()))


class TestBottomPanelSizing(unittest.TestCase):
    """Нижня панель має перетягувану межу й зберігає висоту."""

    def _window(self):
        from blackchpok_ide.main_window import BlackChpokIDE

        return BlackChpokIDE

    def test_sash_has_drag_cursor(self) -> None:
        import inspect

        source = inspect.getsource(self._window()._bottom_sash_press)
        self.assertIn("_sash_drag_height", source)

    def test_drag_clamps_height(self) -> None:
        import inspect

        source = inspect.getsource(self._window()._bottom_sash_drag)
        self.assertIn("clamp", source)
        self.assertIn("_bottom_height", source)

    def test_release_remembers_layout(self) -> None:
        import inspect

        source = inspect.getsource(self._window()._bottom_sash_release)
        self.assertIn("_remember_layout", source)


class TestHeaderSizes(unittest.TestCase):
    """Іконки шапки достатньо великі, а висота не стискається."""

    def test_icon_size_is_readable(self) -> None:
        from blackchpok_ide import header_bar

        self.assertGreaterEqual(header_bar.ICON_SIZE, 14,
                                "іконки менші за 14 pt незручні для мишки")
        self.assertGreaterEqual(header_bar.TEXT_SIZE, 11)
        self.assertGreaterEqual(header_bar.HEADER_HEIGHT, 44)

    def test_no_tiny_fonts_left_in_header(self) -> None:
        source = (ROOT / "blackchpok_ide" / "header_bar.py").read_text(
            encoding="utf-8")
        self.assertNotIn('("Segoe UI", 8)', source,
                         "8 pt у шапці — замало для іконок")
        self.assertNotIn('("Segoe UI", 9)', source)

    def test_header_pins_row_height(self) -> None:
        """Рядок шапки має minsize, інакше grid стискає його до вмісту."""
        source = (ROOT / "blackchpok_ide" / "header_bar.py").read_text(
            encoding="utf-8")
        self.assertIn("rowconfigure(0, minsize=HEADER_HEIGHT)", source,
                      "без цього grid стискає шапку й обрізає іконки")

    def test_no_duplicate_menu_row(self) -> None:
        """Другого рядка меню немає: у вікна вже є нативне меню."""
        source = (ROOT / "blackchpok_ide" / "header_bar.py").read_text(
            encoding="utf-8")
        self.assertNotIn("menu_row", source,
                         "рядок меню в шапці дублював нативне меню вікна")


if __name__ == "__main__":
    unittest.main(verbosity=2)
