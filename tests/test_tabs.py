"""Тести вкладок редактора: відкриття, збереження, закриття, перевідкриття.

``tabs`` — 535 рядків і доти жодного тесту, хоч саме тут живе робота з
файлами користувача: відкриття, зміни, збереження, закриті вкладки.
Помилка тут коштує втрачених правок, тому перевіряємо реальні файли.

Запуск: python -m unittest tests.test_tabs -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_tabs(case: unittest.TestCase, folder: Path):
    """Створити EditorTabs у справжньому (прихованому) вікні."""
    import tkinter as tk
    import tkinter.filedialog as filedialog
    import tkinter.messagebox as messagebox

    from blackchpok_ide import tabs as tabs_mod, theme
    from blackchpok_ide.config import Settings

    # Модальні діалоги блокують тест: підміняємо на передбачувані відповіді.
    case.addCleanup(setattr, messagebox, "askyesno", messagebox.askyesno)
    case.addCleanup(setattr, messagebox, "showwarning", messagebox.showwarning)
    case.addCleanup(setattr, filedialog, "asksaveasfilename",
                    filedialog.asksaveasfilename)
    messagebox.askyesno = lambda *a, **k: True
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    filedialog.asksaveasfilename = lambda *a, **k: ""

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:  # pragma: no cover - без дисплея
        raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
    fonts = theme.Theme(root)
    fonts.apply()
    settings = Settings()
    settings.workspace = str(folder)
    widget = tabs_mod.EditorTabs(root, fonts, settings)
    widget.pack(fill="both", expand=True)
    root.update()

    def cleanup() -> None:
        try:
            widget.close_all(force=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    case.addCleanup(cleanup)
    return widget, root, folder


class TabsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.widget, self.root, _ = _make_tabs(self, self.folder)

    def write(self, name: str, text: str) -> Path:
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def pump(self) -> None:
        self.root.update()


class TestOpenFiles(TabsTestBase):
    """Відкриття файлів."""

    def test_open_file_creates_tab(self) -> None:
        path = self.write("a.py", "print(1)\n")
        self.assertTrue(self.widget.open_file(path))
        self.pump()
        self.assertEqual(self.widget.count(), 1)

    def test_opened_content_matches_disk(self) -> None:
        path = self.write("b.py", "x = 42\n")
        self.widget.open_file(path)
        self.pump()
        editor = self.widget.current()
        self.assertIsNotNone(editor)
        self.assertIn("x = 42", editor.get_text())

    def test_open_same_file_twice_keeps_one_tab(self) -> None:
        path = self.write("c.py", "y = 1\n")
        self.widget.open_file(path)
        self.widget.open_file(path)
        self.pump()
        self.assertEqual(self.widget.count(), 1,
                         "повторне відкриття не має створювати другу вкладку")

    def test_open_missing_file_returns_false(self) -> None:
        missing = self.folder / "немає.py"
        self.assertFalse(self.widget.open_file(missing))

    def test_current_path_matches_opened(self) -> None:
        path = self.write("d.py", "")
        self.widget.open_file(path)
        self.pump()
        self.assertEqual(Path(self.widget.current_path()).name, "d.py")

    def test_new_file_is_untitled(self) -> None:
        editor = self.widget.new_file()
        self.pump()
        self.assertIsNotNone(editor)
        self.assertIsNone(self.widget.current_path(),
                          "новий файл ще не має шляху на диску")

    def test_open_with_line_moves_cursor(self) -> None:
        path = self.write("e.py", "\n".join(f"рядок {i}" for i in range(1, 40)))
        self.widget.open_file(path, line=25)
        self.pump()
        editor = self.widget.current()
        self.assertEqual(editor.current_line(), 25)


class TestSave(TabsTestBase):
    """Збереження змін."""

    def test_save_writes_changes_to_disk(self) -> None:
        path = self.write("s.py", "old\n")
        self.widget.open_file(path)
        self.pump()
        editor = self.widget.current()
        editor.set_text("new content\n")
        editor.modified = True
        self.assertTrue(self.widget.save_current())
        self.pump()
        self.assertIn("new content", path.read_text(encoding="utf-8"))

    def test_save_clears_modified_flag(self) -> None:
        path = self.write("t.py", "a\n")
        self.widget.open_file(path)
        self.pump()
        editor = self.widget.current()
        editor.set_text("b\n")
        editor.modified = True
        self.widget.save_current()
        self.pump()
        self.assertFalse(getattr(editor, "modified", False))

    def test_save_all_saves_every_changed_tab(self) -> None:
        first = self.write("m1.py", "1\n")
        second = self.write("m2.py", "2\n")
        self.widget.open_file(first)
        self.widget.open_file(second)
        self.pump()
        for key, editor in list(self.widget.editors.items()):
            editor.set_text(f"змінено {key[-4:]}\n")
            editor.modified = True
        self.widget.save_all()
        self.pump()
        self.assertIn("змінено", first.read_text(encoding="utf-8"))
        self.assertIn("змінено", second.read_text(encoding="utf-8"))


class TestClose(TabsTestBase):
    """Закриття вкладок."""

    def test_close_clean_tab(self) -> None:
        path = self.write("cl.py", "x\n")
        self.widget.open_file(path)
        self.pump()
        key = self.widget.current_key()
        self.assertTrue(self.widget.close_tab(key))
        self.pump()
        self.assertEqual(self.widget.count(), 0)

    def test_closed_path_is_remembered_for_reopen(self) -> None:
        path = self.write("rp.py", "z\n")
        self.widget.open_file(path)
        self.pump()
        self.widget.close_tab(self.widget.current_key())
        self.pump()
        closed = [Path(p).name for p in self.widget.closed_paths()]
        self.assertIn("rp.py", closed)

    def test_reopen_last_closed(self) -> None:
        path = self.write("ro.py", "value = 7\n")
        self.widget.open_file(path)
        self.pump()
        self.widget.close_tab(self.widget.current_key())
        self.pump()
        self.assertTrue(self.widget.reopen_last_closed())
        self.pump()
        self.assertEqual(self.widget.count(), 1)
        self.assertIn("value = 7", self.widget.current().get_text())

    def test_close_all_returns_true(self) -> None:
        self.widget.open_file(self.write("k1.py", ""))
        self.widget.open_file(self.write("k2.py", ""))
        self.pump()
        self.assertTrue(self.widget.close_all(force=True))
        self.pump()
        self.assertEqual(self.widget.count(), 0)


class TestTitlesAndPaths(TabsTestBase):
    """Заголовки вкладок і список шляхів."""

    def test_tab_titles_reflect_files(self) -> None:
        self.widget.open_file(self.write("one.py", ""))
        self.widget.open_file(self.write("two.py", ""))
        self.pump()
        # Формат: (frame_id, назва, чи є незбережені зміни).
        titles = [name for _fid, name, _mod in self.widget.tab_titles()]
        self.assertIn("one.py", titles)
        self.assertIn("two.py", titles)

    def test_all_paths_lists_open_files(self) -> None:
        self.widget.open_file(self.write("p1.py", ""))
        self.widget.open_file(self.write("p2.py", ""))
        self.pump()
        names = {Path(p).name for p in self.widget.all_paths()}
        self.assertEqual(names, {"p1.py", "p2.py"})

    def test_rename_tab_changes_title(self) -> None:
        self.widget.open_file(self.write("old.py", ""))
        self.pump()
        editor = self.widget.current()
        self.widget.rename_tab(editor, "Нова назва")
        self.pump()
        # rename_tab змінює підпис самої вкладки, а не ім'я файлу на диску.
        tab = self.widget._tabs.get(self.widget.current_key())
        self.assertIsNotNone(tab)
        label_text = str(tab.title_label.cget("text"))
        self.assertIn("Нова назва", label_text, label_text)

    def test_by_path_finds_open_editor(self) -> None:
        path = self.write("find.py", "")
        self.widget.open_file(path)
        self.pump()
        self.assertIsNotNone(self.widget.by_path(path))

    def test_by_path_unknown_returns_none(self) -> None:
        self.assertIsNone(self.widget.by_path(self.folder / "absent.py"))


class TestSelectAndCount(TabsTestBase):
    """Перемикання вкладок."""

    def test_select_switches_current(self) -> None:
        first = self.write("s1.py", "first\n")
        second = self.write("s2.py", "second\n")
        self.widget.open_file(first)
        self.widget.open_file(second)
        self.pump()
        keys = list(self.widget.editors.keys())
        self.widget.select(keys[0])
        self.pump()
        self.assertIn("first", self.widget.current().get_text())

    def test_count_grows_with_tabs(self) -> None:
        self.assertEqual(self.widget.count(), 0)
        self.widget.open_file(self.write("n1.py", ""))
        self.widget.open_file(self.write("n2.py", ""))
        self.pump()
        self.assertEqual(self.widget.count(), 2)


class TestApplySettings(TabsTestBase):
    """Застосування налаштувань до відкритих редакторів."""

    def test_apply_settings_does_not_raise(self) -> None:
        self.widget.open_file(self.write("cfg.py", "x = 1\n"))
        self.pump()
        self.widget.apply_settings()
        self.pump()
        self.assertEqual(self.widget.count(), 1)

    def test_reopen_with_encoding_keeps_tab(self) -> None:
        path = self.folder / "enc.py"
        path.write_text("привіт", encoding="utf-8")
        self.widget.open_file(path)
        self.pump()
        self.widget.reopen_with_encoding("utf-8")
        self.pump()
        self.assertEqual(self.widget.count(), 1)
        self.assertIn("привіт", self.widget.current().get_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
