"""Тести потокового застосування правок: парсер стріму й живий редактор.

Перевіряють те, що не видно з коду: маркер може прийти РОЗІРВАНИМ між
шматками, старий фрагмент знаходиться навіть після зміни лапок моделлю,
``Ctrl+Z`` скасовує правку агента ОДНІЄЮ дією, а не по символу.

Запуск: python -m unittest tests.test_stream_apply -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Тести не мають чіпати справжні налаштування користувача.
os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import live_edit, stream_apply  # noqa: E402


class TestStreamParser(unittest.TestCase):
    """Автомат, що витягає блоки SEARCH/REPLACE зі стріму."""

    def test_whole_block_in_one_piece(self) -> None:
        text = (
            "Ось правка.\n"
            "<<<<<<< SEARCH\n"
            "def f(x):\n"
            "    return x\n"
            "=======\n"
            "def f(x):\n"
            "    return x + 1\n"
            ">>>>>>> REPLACE\n"
            "Готово.\n"
        )
        blocks = stream_apply.parse_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].search, "def f(x):\n    return x")
        self.assertEqual(blocks[0].replace, "def f(x):\n    return x + 1")
        self.assertTrue(blocks[0].complete)

    def test_text_outside_blocks_is_kept(self) -> None:
        parser = stream_apply.StreamParser()
        parser.feed("Пояснення до правки.\n")
        parser.flush()
        self.assertIn("Пояснення", parser.text)
        self.assertFalse(parser.saw_marker)

    def test_marker_split_between_pieces(self) -> None:
        """Найважливіше: маркер приходить шматками по 3 символи."""
        text = (
            "текст\n"
            "<<<<<<< SEARCH\nстарий\n=======\nновий\n>>>>>>> REPLACE\n"
        )
        parser = stream_apply.StreamParser()
        for index in range(0, len(text), 3):
            parser.feed(text[index:index + 3])
        parser.flush()
        self.assertEqual(len(parser.blocks), 1)
        block = parser.blocks[0]
        self.assertEqual(block.search, "старий")
        self.assertEqual(block.replace, "новий")
        self.assertTrue(block.complete, "розірваний маркер не розпізнано")
        # Службові маркери НЕ мають потрапити в текст відповіді.
        self.assertNotIn("SEARCH", parser.text)
        self.assertNotIn("REPLACE", parser.text)

    def test_feed_reports_only_changed_block(self) -> None:
        parser = stream_apply.StreamParser()
        first = parser.feed("<<<<<<< SEARCH\nold\n=======\n")
        self.assertEqual(len(first), 1)
        second = parser.feed("new\n")
        self.assertEqual(len(second), 1, "змінений блок має прийти знову")
        done = parser.feed(">>>>>>> REPLACE\n")
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0].complete)

    def test_unclosed_block_is_not_complete(self) -> None:
        """Стрім обірвався посеред правки — блок незакінчений."""
        parser = stream_apply.StreamParser()
        parser.feed("<<<<<<< SEARCH\nold\n=======\nnew line")
        parser.flush()
        self.assertEqual(len(parser.blocks), 1)
        self.assertFalse(parser.blocks[0].complete,
                         "обірвану правку не можна вважати готовою")

    def test_two_blocks_in_a_row(self) -> None:
        text = (
            "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\nc\n=======\nd\n>>>>>>> REPLACE\n"
        )
        blocks = stream_apply.parse_blocks(text)
        self.assertEqual(len(blocks), 2)
        self.assertEqual((blocks[0].search, blocks[0].replace), ("a", "b"))
        self.assertEqual((blocks[1].search, blocks[1].replace), ("c", "d"))

    def test_missing_divider_does_not_lose_block(self) -> None:
        """Модель забула «=======» — блок усе одно має бути."""
        text = "<<<<<<< SEARCH\nold\n>>>>>>> REPLACE\n"
        blocks = stream_apply.parse_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].complete)


class TestLocate(unittest.TestCase):
    """Пошук фрагмента у файлі."""

    def test_exact_match(self) -> None:
        content = "a = 1\nb = 2\nc = 3\n"
        begin, end, actual = stream_apply.locate(content, "b = 2")
        self.assertGreaterEqual(begin, 0)
        self.assertEqual(actual, "b = 2")
        self.assertEqual(content[begin:end], "b = 2")

    def test_missing_fragment(self) -> None:
        begin, end, actual = stream_apply.locate("a = 1\n", "zzz = 9")
        self.assertEqual(begin, -1)
        self.assertEqual(end, -1)
        self.assertEqual(actual, "")

    def test_quote_difference_is_forgiven(self) -> None:
        """Модель поміняла лапки — фрагмент усе одно знаходиться."""
        content = 'msg = "привіт"\n'
        begin, _end, actual = stream_apply.locate(content, "msg = 'привіт'")
        self.assertGreaterEqual(begin, 0, "лапки завадили знайти фрагмент")
        self.assertEqual(actual, 'msg = "привіт"')

    def test_indent_difference_is_forgiven(self) -> None:
        content = "def f():\n    return 42\n"
        begin, _end, actual = stream_apply.locate(content, "def f():\nreturn 42")
        self.assertGreaterEqual(begin, 0)
        self.assertIn("return 42", actual)

    def test_crlf_content(self) -> None:
        content = "a = 1\r\nb = 2\r\n"
        begin, end, actual = stream_apply.locate(content, "a = 1\nb = 2")
        self.assertGreaterEqual(begin, 0, "CRLF завадив знайти фрагмент")
        self.assertEqual(content[begin:end], actual)

    def test_empty_search_is_not_located(self) -> None:
        self.assertEqual(stream_apply.locate("abc", ""), (-1, -1, ""))


class TestEditStream(unittest.TestCase):
    """Порційна віддача тексту (щоб вставка була плавною)."""

    def test_takes_small_pieces_first(self) -> None:
        stream = stream_apply.EditStream()
        stream.push("abcdefghij")
        first = stream.take()
        self.assertTrue(first)
        self.assertLess(len(first), 10, "перша порція має бути дрібною")

    def test_all_text_is_returned(self) -> None:
        stream = stream_apply.EditStream()
        payload = "x" * 500
        stream.push(payload)
        parts = []
        while True:
            piece = stream.take()
            if not piece:
                break
            parts.append(piece)
        self.assertEqual("".join(parts), payload)

    def test_grows_with_buffer(self) -> None:
        """Великий буфер віддається більшими порціями, щоб не відставати."""
        small = stream_apply.EditStream()
        small.push("a" * 8)
        big = stream_apply.EditStream()
        big.push("a" * 400)
        self.assertGreater(len(big.take()), len(small.take()))


class TestToolArgsWatcher(unittest.TestCase):
    """Розбір аргументів інструмента наживо (під час стріму)."""

    def test_only_edit_tools_are_watched(self) -> None:
        self.assertIsNone(stream_apply.ToolArgsWatcher.for_tool("read_file"))
        self.assertIsNone(stream_apply.ToolArgsWatcher.for_tool("list_dir"))
        self.assertIsNotNone(stream_apply.ToolArgsWatcher.for_tool("write_file"))
        self.assertIsNotNone(stream_apply.ToolArgsWatcher.for_tool("edit_file"))

    def test_partial_string_field(self) -> None:
        raw = '{"path": "a.py", "content": "line 1\\nline 2'
        value, complete = stream_apply.partial_string_field(raw, "content")
        self.assertEqual(value, "line 1\nline 2")
        self.assertFalse(complete)

    def test_complete_field(self) -> None:
        raw = '{"content": "x = 1"}'
        value, complete = stream_apply.partial_string_field(raw, "content")
        self.assertEqual(value, "x = 1")
        self.assertTrue(complete)

    def test_watcher_builds_growing_content(self) -> None:
        """Код має накопичуватись, а не приходити лише в кінці."""
        watcher = stream_apply.ToolArgsWatcher.for_tool("write_file")
        assert watcher is not None
        pieces = ['{"path": "calc.py", ', '"content": "def add(a, b):\\n',
                  '    return a + b\\n"', '}']
        seen = []
        for piece in pieces:
            watcher.feed(piece)
            if watcher.ready():
                seen.append(watcher.shown)
        self.assertGreaterEqual(len(seen), 2, "код не показувався частинами")
        self.assertIn("def add", seen[0])
        self.assertIn("return a + b", seen[-1])
        self.assertTrue(watcher.finished)

    def test_edit_file_needs_old_string_before_showing(self) -> None:
        """Для ``edit_file`` показуємо лише коли відомий фрагмент заміни.

        Порядок полів у справжньому стрімі може бути будь-який, тому
        перевіряємо обидва: доки ``old_string`` немає, показувати нічого.
        """
        watcher = stream_apply.ToolArgsWatcher.for_tool("edit_file")
        assert watcher is not None
        watcher.feed('{"path": "a.py", "new_string": "new code", ')
        self.assertFalse(watcher.ready(),
                         "без old_string невідомо, що замінювати")
        watcher.feed('"old_string": "old code"}')
        self.assertTrue(watcher.ready())
        self.assertEqual(watcher.search, "old code")
        self.assertTrue(watcher.finished)

    def test_old_string_first_order(self) -> None:
        """Зворотний порядок полів теж має працювати."""
        watcher = stream_apply.ToolArgsWatcher.for_tool("edit_file")
        assert watcher is not None
        watcher.feed('{"path": "a.py", "old_string": "old code", ')
        self.assertFalse(watcher.ready(), "коду заміни ще немає")
        watcher.feed('"new_string": "new code"}')
        self.assertTrue(watcher.ready())
        self.assertEqual(watcher.shown, "new code")


class TestLiveEditInEditor(unittest.TestCase):
    """Жива правка у справжньому віджеті редактора."""

    def setUp(self) -> None:
        from blackchpok_ide import editor, theme

        self.root = tk.Tk()
        self.root.withdraw()
        fonts = theme.Theme(self.root)
        fonts.apply()
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-live-"))
        self.target = self.folder / "app.py"
        self.target.write_text("def f(x):\n    return x\n", encoding="utf-8")
        self.editor = editor.CodeEditor(self.root, fonts, "app.py")
        self.editor.set_text(self.target.read_text(encoding="utf-8"))
        self.editor.pack()

    def tearDown(self) -> None:
        # Зупиняємо відкладені задачі редактора: інакше після ``destroy``
        # Tk друкує «invalid command name …_run_analysis» у stderr, і прогін
        # виглядає зламаним, хоч тести пройшли.
        for name in ("_ast_job", "_highlight_job"):
            job = getattr(self.editor, name, None)
            if job is None:
                continue
            try:
                self.editor.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            setattr(self.editor, name, None)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _pump(self, seconds: float = 0.6) -> None:
        import time

        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                self.root.update()
            except tk.TclError:
                return
            time.sleep(0.01)

    def _start(self, search: str, replace: str) -> live_edit.LiveEdit:
        block = stream_apply.EditBlock(search=search, replace=replace,
                                       complete=True)
        live = live_edit.feed_block(self.editor, block)
        assert live is not None
        return live

    def test_old_text_is_marked_before_accept(self) -> None:
        """Старий фрагмент НЕ зникає одразу — він підсвічений червоним."""
        live = self._start("    return x", "    return x + 1")
        self._pump(0.3)
        ranges = self.editor.text.tag_ranges(live_edit.TAG_OLD)
        self.assertGreaterEqual(len(ranges), 2, "старий фрагмент не підсвічено")
        self.assertIn("return x", self.editor.get_text(),
                      "старий код зник до підтвердження")

    def test_new_text_appears_green(self) -> None:
        live = self._start("    return x", "    return x + 1")
        self._pump(0.4)
        ranges = self.editor.text.tag_ranges(live_edit.TAG_NEW)
        self.assertGreaterEqual(len(ranges), 2, "новий текст не підсвічено")
        self.assertIn("return x + 1", self.editor.get_text())

    def test_accept_removes_old_keeps_new(self) -> None:
        live = self._start("    return x", "    return x + 1")
        self._pump(0.4)
        live.accept()
        self._pump(0.1)
        text = self.editor.get_text()
        self.assertIn("return x + 1", text)
        self.assertEqual(text.count("return x"), 1,
                         "старий рядок лишився після «Прийняти»")

    def test_reject_removes_new_restores_old(self) -> None:
        live = self._start("    return x", "    return something else")
        self._pump(0.4)
        live.reject()
        self._pump(0.1)
        text = self.editor.get_text()
        self.assertIn("    return x", text, "старий код втрачено")
        self.assertNotIn("something else", text, "новий код лишився")

    def test_missing_fragment_does_not_mark_wrong_text(self) -> None:
        """Фрагмента немає — червоного підсвічування бути НЕ має."""
        live = self._start("def no_such_function():", "def other():")
        self._pump(0.3)
        self.assertFalse(live.located)
        self.assertEqual(len(self.editor.text.tag_ranges(live_edit.TAG_OLD)), 0,
                         "підсвічено чужий текст замість відсутнього фрагмента")

    def test_whole_edit_is_one_undo_step(self) -> None:
        """Ctrl+Z скасовує ВСЮ правку агента, а не один символ."""
        before = self.editor.get_text()
        live = self._start("    return x", "    return " + "y + " * 40 + "x")
        self._pump(0.8)
        live.accept()
        self._pump(0.1)
        after = self.editor.get_text()
        self.assertNotEqual(before, after)
        try:
            self.editor.text.edit_undo()
        except tk.TclError:
            self.fail("історія скасування порожня — правка не потрапила в undo")
        self._pump(0.05)
        self.assertEqual(self.editor.get_text(), before,
                         "один Ctrl+Z не повернув файл до правки")

    def test_append_extends_without_duplicating(self) -> None:
        """Шматки стріму дописуються, а не дублюють уже показане."""
        block = stream_apply.EditBlock(search="    return x", replace="    ret",
                                       complete=False)
        live = live_edit.feed_block(self.editor, block)
        assert live is not None
        self._pump(0.2)
        live.append("    return x + 1", final=True)
        self._pump(0.4)
        text = self.editor.get_text()
        self.assertEqual(text.count("return x + 1"), 1,
                         "приріст продубльовано")
        self.assertIn("return x + 1", text)

    def test_cancel_stops_timer(self) -> None:
        live = self._start("    return x", "    return " + "z" * 400)
        live.cancel_timer()
        self.assertTrue(live.settled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
