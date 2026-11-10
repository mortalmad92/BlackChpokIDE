"""Тести AST-редактора: розбір, символи, помилки, живе оновлення.

Запуск:  python tests/test_ast_editor.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import ast_index  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


SAMPLE = '''"""Модуль-приклад."""
import os
from pathlib import Path

LIMIT = 10


class Box:
    """Коробка з речами."""

    def __init__(self):
        self.items = []

    @property
    def size(self):
        return len(self.items)

    async def load(self, path, *, force=False):
        """Завантажити вміст."""
        if path:
            for line in path:
                yield line

    class Inner:
        def deep(self):
            return 1


def top(a, b=2, *args, **kwargs):
    """Верхня функція."""
    return a + b
'''


# ─────────────────────────────────────────────────────────────────────────────
# Розбір
# ─────────────────────────────────────────────────────────────────────────────

def test_parse() -> None:
    result = ast_index.analyse(SAMPLE)
    check("файл розбирається", result.ok, str(result.problem))
    check("дерево побудовано", result.tree is not None)

    names = [sym.name for sym in result.symbols]
    for expected in ("Box", "top", "__init__", "size", "load", "Inner", "deep"):
        check(f"знайдено «{expected}»", expected in names, ",".join(names))

    box = next(sym for sym in result.symbols if sym.name == "Box")
    check("Box — клас", box.kind == ast_index.CLASS, box.kind)
    check("у класу є docstring", "Коробка" in box.docstring, box.docstring)

    load = next(sym for sym in result.symbols if sym.name == "load")
    check("load — асинхронний", load.kind == ast_index.ASYNC, load.kind)
    check("підпис load зібрано", "path" in load.signature, load.signature)
    check("декоратор не заважає", load.signature.startswith("("), load.signature)

    size = next(sym for sym in result.symbols if sym.name == "size")
    check("size — властивість", size.is_property, size.kind)
    check("позначка властивості", size.icon == ast_index.ICONS[ast_index.PROPERTY],
          size.icon)

    inner = next(sym for sym in result.symbols if sym.name == "Inner")
    check("вкладений клас знайдено", inner.depth >= 1, str(inner.depth))
    deep = next(sym for sym in result.symbols if sym.name == "deep")
    check("метод вкладеного класу", deep.depth >= 2, str(deep.depth))

    top = next(sym for sym in result.symbols if sym.name == "top")
    check("підпис top з параметрами",
          "a" in top.signature and "b" in top.signature, top.signature)
    check("top — функція", top.kind == ast_index.FUNCTION, top.kind)
    check("docstring top", "Верхня" in top.docstring, top.docstring)

    check("імпорти зібрано", len(result.imports) == 2,
          ",".join(s.name for s in result.imports))
    check("імпорт із модуля", any("pathlib.Path" in s.name for s in result.imports),
          ",".join(s.name for s in result.imports))
    check("змінні зібрано", any(s.name == "LIMIT" for s in result.variables),
          ",".join(s.name for s in result.variables))


def test_metrics() -> None:
    result = ast_index.analyse(SAMPLE)
    metrics = result.metrics
    check("рядки пораховано", metrics.lines > 20, str(metrics.lines))
    check("функції пораховано", metrics.functions >= 5, str(metrics.functions))
    check("класи пораховано", metrics.classes >= 2, str(metrics.classes))
    check("імпорти пораховано", metrics.imports == 2, str(metrics.imports))
    check("гілки пораховано", metrics.branches >= 2, str(metrics.branches))
    check("підсумок не порожній", "функцій" in metrics.summary, metrics.summary)

    with_comments = ast_index.analyse("# коментар\nx = 1\n\n")
    check("коментарі відділено", with_comments.metrics.comment_lines == 1,
          str(with_comments.metrics.comment_lines))
    check("порожні рядки відділено", with_comments.metrics.blank_lines == 1,
          str(with_comments.metrics.blank_lines))


def test_errors() -> None:
    cases = (
        ("def f(:\n    pass\n", 1),
        ("class A\n    pass\n", 1),
        ("x = 1\ny = 2\n  z = 3\n", 3),
    )
    for code, expected_line in cases:
        result = ast_index.analyse(code)
        check(f"помилка знайдена (рядок {expected_line})",
              not result.ok and result.problem is not None)
        if result.problem is not None:
            check(f"номер рядка правильний ({expected_line})",
                  result.problem.line == expected_line,
                  f"{result.problem.line} vs {expected_line}")
            check("короткий опис не порожній", bool(result.problem.short.strip()),
                  result.problem.short[:60])

    good = ast_index.analyse("x = 1\n")
    check("коректний код без помилки", good.ok and good.problem is None)

    check("порожній текст не ламає", ast_index.analyse("").metrics.lines == 0)


def test_lookup() -> None:
    result = ast_index.analyse(SAMPLE)

    size = next(sym for sym in result.symbols if sym.name == "size")
    inside = result.at_line(size.line + 1)
    check("at_line знаходить символ у тілі",
          inside is not None and inside.name == "size",
          inside.name if inside else "None")

    found = result.find("lo")
    check("пошук за частиною назви", any(s.name == "load" for s in found),
          ",".join(s.name for s in found))

    check("порожній пошук дає все", len(result.find("")) == len(result.symbols))

    outline = result.outline
    check("структура без змінних",
          all(s.kind != ast_index.VARIABLE for s in outline))
    check("структура має функції", len(outline) >= 5, str(len(outline)))


def test_cache() -> None:
    ast_index.clear_cache()
    first = ast_index.analyse(SAMPLE)
    second = ast_index.analyse(SAMPLE)
    check("повторний розбір із кешу", first is second, "той самий об'єкт")

    other = ast_index.analyse(SAMPLE + "\n")
    check("інший текст — новий розбір", other is not first)

    check("хеш різний для різного тексту",
          ast_index.digest("a") != ast_index.digest("b"))


def test_tree_rows() -> None:
    result = ast_index.analyse(SAMPLE)
    rows = ast_index.tree_rows(result.tree)
    check("вузли дерева є", len(rows) > 10, str(len(rows)))
    kinds = {name for _depth, name, _snippet in rows}
    check("є Module", "Module" in kinds, ",".join(sorted(kinds)[:5]))
    check("є FunctionDef", "FunctionDef" in kinds)
    check("є ClassDef", "ClassDef" in kinds)
    check("вкладеність показано", max(depth for depth, _n, _s in rows) >= 2)

    limited = ast_index.tree_rows(result.tree, limit=5)
    check("ліміт працює", len(limited) == 5, str(len(limited)))


def test_describe_line() -> None:
    result = ast_index.analyse(SAMPLE)
    box = next(sym for sym in result.symbols if sym.name == "Box")
    text = ast_index.describe_line(SAMPLE, box.line)
    check("опис рядка містить символ", "Box" in text, text)
    # Рядок із присвоєнням — це змінна, тому опис є.
    check("змінна на рядку описана",
          "x" in ast_index.describe_line("x = 1\n", 1),
          ast_index.describe_line("x = 1\n", 1))
    check("порожній рядок без символу",
          ast_index.describe_line("\n\n", 1) == "")


# ─────────────────────────────────────────────────────────────────────────────
# Живий редактор
# ─────────────────────────────────────────────────────────────────────────────

def test_live_editor() -> None:
    import tkinter as tk

    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None

    from blackchpok_ide import theme
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.chat_panel import ChatPanel  # noqa: F401 - перевірка імпорту
    from blackchpok_ide.config import Settings
    from blackchpok_ide.editor import CodeEditor
    from blackchpok_ide.outline_panel import OutlinePanel

    root = tk.Tk()
    root.geometry("800x700")
    fonts = theme.Theme(root)
    fonts.apply()

    results: list = []
    editor = CodeEditor(root, fonts, "demo.py")
    editor.on_analysis = lambda result: results.append(result)
    editor.pack(fill="both", expand=True)
    panel = OutlinePanel(root, fonts)
    panel.pack(fill="both", expand=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    pump(0.3)

    # Набираємо код поступово — панель має оновлюватись
    steps = [
        ("class Box:\n    pass\n", 1),
        ("\ndef top(a, b):\n    return a + b\n", 2),
        ("\nasync def fetch(url):\n    return url\n", 3),
    ]
    for code, expected_min in steps:
        editor.text.insert("end", code)
        editor.text.edit_modified(True)
        pump(0.45)
        count = len(results[-1].symbols) if results else 0
        check(f"живий AST після кроку ({expected_min} символи)",
              count >= expected_min, f"{count} символів")
        panel.update_for(editor)
        pump(0.1)

    check("панель показує рядки", len(panel._rows) >= 3, str(len(panel._rows)))
    check("лічильник заповнено", "ƒ" in panel.count_label.cget("text"),
          panel.count_label.cget("text"))

    # Помилка — має з'явитись у панелі й підсвітитись
    editor.text.insert("end", "\ndef broken(:\n")
    editor.text.edit_modified(True)
    pump(0.6)
    latest = results[-1] if results else None
    check("помилку знайдено в реальному часі",
          latest is not None and latest.problem is not None)
    check("тег помилки стоїть", bool(editor.text.tag_ranges("syntax_error")))
    panel.update_for(editor)
    pump(0.2)
    check("панель показує помилку", "Рядок" in panel.problem_label.cget("text"),
          panel.problem_label.cget("text")[:50])

    # Пошук у структурі
    panel.search_entry.insert(0, "top")
    panel._on_search()
    pump(0.2)
    check("пошук фільтрує структуру", len(panel._rows) <= 2, str(len(panel._rows)))

    root.destroy()


def test_real_file() -> None:
    """Розбір справжнього великого файлу проєкту — швидкість і повнота."""
    target = ROOT / "blackchpok_ide" / "main_window.py"
    if not target.exists():
        check("файл проєкту для перевірки", False, "немає main_window.py")
        return
    text = target.read_text(encoding="utf-8")
    started = time.perf_counter()
    result = ast_index.analyse(text)
    elapsed = (time.perf_counter() - started) * 1000
    check("великий файл розбирається", result.ok, str(result.problem))
    check("розбір швидкий", elapsed < 900, f"{elapsed:.0f} мс")
    check("багато символів знайдено", len(result.symbols) > 30,
          str(len(result.symbols)))
    check("класи знайдено", result.metrics.classes >= 1, str(result.metrics.classes))
    check("методи класів мають вкладеність",
          any(sym.depth >= 1 for sym in result.symbols))


def main() -> int:
    test_parse()
    test_metrics()
    test_errors()
    test_lookup()
    test_cache()
    test_tree_rows()
    test_describe_line()
    test_live_editor()
    test_real_file()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("AST-редактор:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_ast_editor.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
