"""Тести рендерера Markdown для панелі чату (blackchpok_ide/markdown_view.py).

Запуск:  python tests/test_markdown_view.py
Повертає 0, якщо всі перевірки пройшли. Потрібен дисплей (Tk), бо
перевіряється реальний tk.Text.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Консоль Windows за замовчуванням не в UTF-8 — інакше кирилиця падає.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def section(title: str) -> None:
    print()
    print(f"== {title} ==")


DOC = """# Заголовок H1

Текст абзацу з **жирним** словом, *курсивом* та `inline_code()`.
Другий рядок того ж абзацу з [посиланням](https://example.com).

## Список
- перший пункт
- другий пункт з **акцентом**
* зірочка
+ плюс
1. нумерований

> цитата перша
> цитата друга

| Мова | Рівень |
|------|--------|
| Python | високий |

---

```python
def hello():
    return "привіт"

print(hello())
```

Хвіст документа.

```js
const x = 1;
```
"""


def build_fonts(root):
    """Мінімальний «об'єкт шрифтів» із реальних tkinter.font.Font."""
    import tkinter.font as tkfont

    class Fonts:
        pass

    fonts = Fonts()
    fonts.chat = tkfont.Font(root=root, family="Consolas", size=10)
    fonts.chat_code = tkfont.Font(root=root, family="Consolas", size=9)
    fonts.ui_bold = tkfont.Font(root=root, family="Consolas", size=10, weight="bold")
    fonts.ui_small = tkfont.Font(root=root, family="Consolas", size=8)
    return fonts


def main() -> int:
    from blackchpok_ide.markdown_view import (
        ChatPalette,
        MarkdownRenderer,
        Segment,
        parse_inline,
        parse_markdown,
        plain_text,
    )

    # ── 1. Блоки коду ──────────────────────────────────────────────────────
    section("1. Блоки коду")
    md = "Опис:\n\n```python\nprint('a')\n    print('b')\n```\n\nкінець"
    segments = parse_markdown(md)
    codes = [s for s in segments if s.kind == "code"]
    check("знайдено один блок коду", len(codes) == 1, f"{len(codes)}")
    if codes:
        code = codes[0]
        check("мова блоку — python", code.language == "python", code.language)
        check(
            "тіло блоку точне (з відступами)",
            code.text == "print('a')\n    print('b')",
            repr(code.text),
        )
        check("індекс блоку — 0", code.index == 0, str(code.index))

    unclosed = parse_markdown("початок\n\n```python\nx = 1\ny = 2")
    unclosed_codes = [s for s in unclosed if s.kind == "code"]
    check("незакритий блок рахується кодом", len(unclosed_codes) == 1, f"{len(unclosed_codes)}")
    if unclosed_codes:
        check(
            "тіло незакритого блоку",
            unclosed_codes[0].text == "x = 1\ny = 2",
            repr(unclosed_codes[0].text),
        )
        check("мова незакритого блоку — python", unclosed_codes[0].language == "python")

    multi = [s for s in parse_markdown(DOC) if s.kind == "code"]
    check("два блоки коду мають індекси 0 і 1", [s.index for s in multi] == [0, 1],
          str([s.index for s in multi]))

    # ── 2. Класифікація сегментів ──────────────────────────────────────────
    section("2. Класифікація сегментів")
    kinds = [s.kind for s in parse_markdown(DOC)]
    check("є заголовок", "heading" in kinds)
    check("є пункти списку", kinds.count("bullet") >= 5, str(kinds.count("bullet")))
    check("є цитата", "quote" in kinds)
    check("є таблиця", "table" in kinds)
    check("є горизонтальна лінія", "hr" in kinds)

    parsed = parse_markdown(DOC)
    headings = [s for s in parsed if s.kind == "heading"]
    check("H1 має рівень 1", headings and headings[0].level == 1,
          str(headings[0].level) if headings else "немає")
    check("H1 має текст без решіток", headings and headings[0].text == "Заголовок H1",
          headings[0].text if headings else "немає")

    rules = {kind: [s for s in parsed if s.kind == kind] for kind in ("bullet", "table", "hr", "quote")}
    check(
        "розпізнані різні маркери списку",
        len(rules["bullet"]) >= 5,
        str([s.text for s in rules["bullet"]]),
    )
    check(
        "таблиця — один сегмент із сирими рядками",
        rules["table"] and len(rules["table"][0].text.split("\n")) == 3,
        repr(rules["table"][0].text) if rules["table"] else "немає",
    )
    check("--- це hr, а не список", rules["hr"] and rules["hr"][0].text.startswith("---"))
    check(
        "рядки цитати склеєні",
        rules["quote"] and rules["quote"][0].text == "цитата перша\nцитата друга",
        repr(rules["quote"][0].text) if rules["quote"] else "немає",
    )
    texts = [s for s in parsed if s.kind == "text"]
    check(
        "два рядки абзацу — один сегмент з \\n",
        any("\n" in s.text for s in texts),
        str([s.text for s in texts][:2]),
    )
    check("Segment має типізовані поля", Segment("text", "x").index == -1)
    check("ChatPalette: темний фон за замовчуванням", ChatPalette().bg == "#0e0e10", ChatPalette().bg)

    # ── 3. parse_inline ────────────────────────────────────────────────────
    section("3. parse_inline")
    inline = parse_inline("a **bold** *ital* `code` [label](http://x.y) _under_")
    styles = [style for style, _text in inline]
    check("жирний розпізнано", ("bold", "bold") in inline, str(inline))
    check("курсив зірочками", ("italic", "ital") in inline, str(inline))
    check("курсив підкресленнями", ("italic", "under") in inline, str(inline))
    check("інлайн-код", ("code", "code") in inline, str(inline))
    check(
        "посилання містить підпис і адресу",
        any(style == "link" and "label" in text and "http://x.y" in text for style, text in inline),
        str(inline),
    )
    check("стилі лише з відомого набору",
          set(styles) <= {"text", "bold", "italic", "code", "link"}, str(set(styles)))
    check("маркери не потрапляють у видимий текст",
          "**" not in "".join(text for _s, text in inline),
          repr("".join(text for _s, text in inline)))

    # ── Tk ─────────────────────────────────────────────────────────────────
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        fonts = build_fonts(root)
        widget = tk.Text(root, wrap="word", state="normal")
        renderer = MarkdownRenderer(widget, fonts, ChatPalette())

        renderer.configure_tags()
        renderer.configure_tags()  # повторний виклик має бути безпечним
        tags = set(widget.tag_names())
        expected_tags = {
            "md_text", "md_bold", "md_italic", "md_inline_code",
            "md_h1", "md_h2", "md_h3", "md_bullet", "md_quote", "md_rule",
            "md_table", "md_link", "md_code_header", "md_code_body", "md_code_footer",
        }
        section("4. Теги")
        check("усі очікувані теги створені", expected_tags <= tags, str(sorted(expected_tags - tags)))
        inline_code_bg = str(widget.tag_cget("md_inline_code", "background")).lower()
        check("md_inline_code має фон code_bg", inline_code_bg == "#141416", inline_code_bg)

        # ── 4-5. Рендер ────────────────────────────────────────────────────
        section("5. Рендер у віджет")
        blocks = renderer.render(DOC)
        content = widget.get("1.0", "end-1c")
        check("render повернув два блоки коду", len(blocks) == 2, str(len(blocks)))
        check(
            "перший блок збігається з тілом фенсу",
            blocks and blocks[0] == 'def hello():\n    return "привіт"\n\nprint(hello())',
            repr(blocks[0]) if blocks else "немає",
        )
        check("code_blocks повторює результат render", renderer.code_blocks == blocks)
        check("у віджеті присутній рядок коду", "def hello():" in content)
        check("відступ коду збережено", '    return "привіт"' in content)
        check("присутній текст заголовка", "Заголовок H1" in content)
        check("шапка блоку коду з мовою", "python" in content and "копіювати" in content)
        check(
            "усі блоки коду є в тексті віджета",
            all(block.split("\n")[0] in content for block in blocks),
            str([block.split("\n")[0] for block in blocks]),
        )
        check(
            "code_blocks збігається з тілом у віджеті",
            all(block + "\n" in content for block in blocks),
            str([(_block + "\n") in content for _block in blocks]),
        )
        check("таблиця відрендерена як текст", "│" in content and "Python" in content)
        check("пункт списку має маркер •", "•" in content)
        check("цитата має вертикальну риску", "│" in content and "цитата перша" in content)

        inline_ranges = widget.tag_ranges("md_inline_code")
        check("тег md_inline_code застосовано", len(inline_ranges) > 0, f"{len(inline_ranges)}")
        body_ranges = widget.tag_ranges("md_code_body")
        check("тег md_code_body застосовано", len(body_ranges) > 0, f"{len(body_ranges)}")
        bold_ranges = widget.tag_ranges("md_bold")
        check("тег md_bold застосовано", len(bold_ranges) > 0, f"{len(bold_ranges)}")

        # ── 6. Стан віджета ────────────────────────────────────────────────
        section("6. Стан віджета")
        widget.configure(state="disabled")
        renderer.render("```python\nx = 1\n```")
        check("стан відновлено на disabled", str(widget.cget("state")) == "disabled",
              str(widget.cget("state")))
        check("вміст замінено під час disabled", "x = 1" in widget.get("1.0", "end-1c"))
        widget.configure(state="normal")
        renderer.render("просто текст")
        check("стан normal не зіпсовано", str(widget.cget("state")) == "normal",
              str(widget.cget("state")))
        check("порожній markdown дає порожній список кодів", renderer.render("") == [])

        # ── 7. plain_text ──────────────────────────────────────────────────
        section("7. plain_text")
        stripped = plain_text("## Заголовок\n\nТекст із **жирним**, `кодом` та [лінк](http://a.b).")
        check("немає решіток заголовка", "##" not in stripped, repr(stripped))
        check("немає зірочок", "**" not in stripped, repr(stripped))
        check("немає бектиків", "`" not in stripped, repr(stripped))
        check("видимий текст збережено", "Заголовок" in stripped and "жирним" in stripped, repr(stripped))
        check("адреса посилання видима", "http://a.b" in stripped, repr(stripped))
        check("plain_text('') == ''", plain_text("") == "")
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Markdown-рендерер:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_markdown_view.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
