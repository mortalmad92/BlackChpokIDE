"""Тести рендерера чату: підсвітка, згортання довгого коду, живий стрім.

Рендерер перевіряється ОКРЕМО від моделі — саме так вимагав користувач:
«навіть правильно згенерований Markdown виглядає погано, якщо frontend
склеює текст, JSON і виклики інструментів в один рядок».

Частина тестів потребує дисплея (Tk). Якщо його немає, вони чесно
пропускаються, а чисті перевірки виконуються завжди.

Запуск: python -m unittest tests.test_chat_renderer -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import markdown_view  # noqa: E402

FENCE = "`" * 3


def _tk_available() -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.destroy()
        return True
    except Exception:                      # noqa: BLE001
        return False


TK_OK = _tk_available()


class TestLanguageMapping(unittest.TestCase):
    """Мова у шапці блоку мусить перетворюватись на справжню підсвітку."""

    def test_common_aliases(self) -> None:
        cases = {
            "python": "py", "py": "py", "Python3": "py",
            "js": "js", "javascript": "js", "ts": "ts", "typescript": "ts",
            "bash": "bash", "shell": "bash", "sh": "sh",
            "powershell": "ps1", "ps1": "ps1",
            "json": "json", "yaml": "yaml", "yml": "yaml",
            "html": "html", "css": "css", "sql": "sql",
            "rust": "rs", "rs": "rs", "go": "go", "php": "php",
        }
        for language, expected in cases.items():
            with self.subTest(language=language):
                self.assertEqual(markdown_view._syntax_ext(language), expected)

    def test_unknown_language_is_not_a_crash(self) -> None:
        self.assertEqual(markdown_view._syntax_ext("вигаданамова"), "вигаданамова")
        self.assertEqual(markdown_view._syntax_ext(""), "")

    def test_language_from_block_info(self) -> None:
        """У шапці буває «python title=calc.py» — беремо перше слово."""
        self.assertEqual(markdown_view._syntax_ext("python title=calc.py"), "py")
        self.assertEqual(markdown_view._syntax_ext("js {.numberLines}"), "js")

    def test_code_language_from_filename(self) -> None:
        self.assertEqual(markdown_view.code_language("main.py"), "python")
        self.assertEqual(markdown_view.code_language("app.ts"), "typescript")


class TestParsing(unittest.TestCase):
    """Розбір не залежить від Tk — його перевіряємо завжди."""

    def test_fenced_block_language(self) -> None:
        segments = markdown_view.parse_markdown(
            f"{FENCE}python\ndef add(a, b):\n    return a + b\n{FENCE}")
        codes = [item for item in segments if item.kind == "code"]
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0].language, "python")

    def test_unclosed_fence_is_code(self) -> None:
        """Незакритий блок під час стріму — це вже код, а не текст."""
        segments = markdown_view.parse_markdown(
            f"Ось функція:\n\n{FENCE}python\ndef add(a, b):")
        codes = [item for item in segments if item.kind == "code"]
        self.assertEqual(len(codes), 1)
        self.assertIn("def add", codes[0].text)

    def test_table_is_one_segment(self) -> None:
        text = "| a | b |\n|---|---|\n| 1 | 2 |"
        segments = markdown_view.parse_markdown(text)
        self.assertEqual([item.kind for item in segments], ["table"])

    def test_inline_code_is_not_emphasis(self) -> None:
        chunks = markdown_view.parse_inline("текст `__init__` далі")
        styles = [style for style, _text in chunks]
        self.assertIn("code", styles)
        self.assertIn("__init__", "".join(text for _s, text in chunks))

    def test_plain_text_strips_markers(self) -> None:
        plain = markdown_view.plain_text("**Жирний** і `код`")
        self.assertNotIn("**", plain)
        self.assertNotIn("`", plain)


@unittest.skipUnless(TK_OK, "немає дисплея для Tk")
class TestRendering(unittest.TestCase):
    """Те, що бачить користувач: підсвітка, шапка, згортання."""

    def setUp(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        self.root = tk.Tk()
        self.fonts = theme.Theme(self.root)
        self.fonts.apply()
        self.widget = tk.Text(self.root)

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:                  # noqa: BLE001
            pass

    def test_code_is_highlighted(self) -> None:
        renderer = markdown_view.MarkdownRenderer(self.widget, self.fonts)
        renderer.render(f"{FENCE}python\ndef add(a, b):\n    return a + b\n{FENCE}")
        self.assertGreater(len(self.widget.tag_ranges("syn_keyword")), 0,
                           "ключові слова мають бути підсвічені")
        self.assertGreater(len(self.widget.tag_ranges("syn_function")), 0)

    def test_header_shows_language(self) -> None:
        renderer = markdown_view.MarkdownRenderer(self.widget, self.fonts)
        renderer.render(f"{FENCE}python\nx = 1\n{FENCE}")
        visible = self.widget.get("1.0", "end")
        self.assertIn("python", visible)
        self.assertIn("копіювати", visible)

    def test_long_code_is_collapsed(self) -> None:
        body = "\n".join(f"line_{index} = {index}" for index in range(120))
        renderer = markdown_view.MarkdownRenderer(
            self.widget, self.fonts, collapse_after=40)
        renderer.render(f"{FENCE}python\n{body}\n{FENCE}")
        visible = self.widget.get("1.0", "end")
        self.assertIn("ще 80 рядків", visible)
        self.assertNotIn("line_100", visible)
        # Повний код усе одно доступний для «копіювати».
        self.assertEqual(len(renderer.code_blocks), 1)
        self.assertIn("line_119", renderer.code_blocks[0])

    def test_collapse_can_be_disabled(self) -> None:
        body = "\n".join(f"line_{index} = {index}" for index in range(120))
        renderer = markdown_view.MarkdownRenderer(
            self.widget, self.fonts, collapse_after=0)
        renderer.render(f"{FENCE}python\n{body}\n{FENCE}")
        self.assertIn("line_119", self.widget.get("1.0", "end"))

    def test_highlight_can_be_disabled(self) -> None:
        renderer = markdown_view.MarkdownRenderer(
            self.widget, self.fonts, highlight=False)
        renderer.render(f"{FENCE}python\ndef add(a, b):\n    return a + b\n{FENCE}")
        self.assertEqual(len(self.widget.tag_ranges("syn_keyword")), 0)

    def test_markdown_structure_survives(self) -> None:
        renderer = markdown_view.MarkdownRenderer(self.widget, self.fonts)
        renderer.render("# Заголовок\n\n- пункт\n> цитата")
        visible = self.widget.get("1.0", "end")
        self.assertIn("Заголовок", visible)
        self.assertIn("•", visible)
        self.assertIn("│", visible)
        self.assertNotIn("# ", visible)

    def test_unknown_language_renders_plain(self) -> None:
        renderer = markdown_view.MarkdownRenderer(self.widget, self.fonts)
        renderer.render(f"{FENCE}вигаданамова\nщось\n{FENCE}")
        self.assertIn("щось", self.widget.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
