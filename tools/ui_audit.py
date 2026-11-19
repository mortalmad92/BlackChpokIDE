"""Аудит інтерфейсу BlackChpok IDE: контраст палітр і «хардкоди» в панелях.

Навіщо. Покращення інтерфейсу легко перетворити на смак: «здається, сірого
забагато». Цей скрипт дає числа, з якими можна сперечатись:

1. **Контраст** пар «текст / тло» за формулою WCAG 2.1 (відношення
   яскравостей, 1..21). Пороги: 4.5:1 — звичайний текст, 3.0:1 — великий
   текст і рамки/іконки. Нижче 3.0 — читати важко.
2. **Хардкоди** в панелях: ``("Segoe UI", N)`` і ``#rrggbb`` замість
   ``theme.*`` та ``fonts.*``. Через них масштабування шрифту й зміна теми
   не діють на частину віджетів.

Запуск::

    python tools/ui_audit.py            # звіт людині
    python tools/ui_audit.py --strict   # exit 1, якщо є порушення (для CI)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDE = ROOT / "blackchpok_ide"
sys.path.insert(0, str(ROOT))

from blackchpok_ide import theme  # noqa: E402  - після правки sys.path

#: Пари «текст на тлі», які реально зустрічаються в інтерфейсі.
#: (текст, тло, мінімальний контраст, де це видно)
PAIRS: tuple[tuple[str, str, float, str], ...] = (
    ("FG", "BG", 4.5, "основний текст на тлі робочої області"),
    ("FG", "BG_CARD", 4.5, "текст картки повідомлення"),
    ("FG", "BG_INPUT", 4.5, "текст у полі вводу"),
    ("FG", "BG_ALT", 4.5, "текст у бічній панелі"),
    ("FG_DIM", "BG", 4.5, "другорядний текст"),
    ("FG_DIM", "BG_CARD", 4.5, "підписи в картці"),
    ("FG_FAINT", "BG", 3.0, "підказки, службові рядки"),
    ("FG_FAINT", "BG_CARD", 3.0, "час і підписи ролі"),
    ("FG_FAINT", "BG_INPUT", 3.0, "підказка під полем вводу"),
    ("FG_FAINT", "BG_ALT", 3.0, "лічильники в панелях"),
    ("ACCENT", "BG", 3.0, "акцентні підписи"),
    ("ACCENT", "BG_CARD", 3.0, "акцент у картці"),
    ("ON_ACCENT", "ACCENT", 3.0, "текст на акцентній кнопці"),
    ("BTN_FG", "BTN_BG", 4.5, "текст на головній кнопці"),
    ("CHAT_USER", "BG_CARD", 2.5, "підпис ролі ВИ"),
    ("CHAT_OK", "BG_CARD", 2.5, "підпис ролі АГЕНТ"),
    ("DIFF_ADD_FG", "DIFF_ADD_BG", 4.5, "доданий рядок у diff"),
    ("DIFF_DEL_FG", "DIFF_DEL_BG", 4.5, "видалений рядок у diff"),
)

#: Пороги, які вважаємо порушенням (WCAG 2.1 AA для тексту).
HARD_FAIL = 3.0


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Відносна яскравість кольору ``#rrggbb`` (0..1)."""
    clean = colour.lstrip("#")
    red, green, blue = (int(clean[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _channel(red) + 0.7152 * _channel(green)
            + 0.0722 * _channel(blue))


def contrast(a: str, b: str) -> float:
    """Відношення контрасту двох кольорів (1..21)."""
    first, second = luminance(a), luminance(b)
    high, low = max(first, second), min(first, second)
    return round((high + 0.05) / (low + 0.05), 2)


def contrast_report() -> list[tuple[str, str, str, float, float, str, bool]]:
    """Рядки звіту: (тема, текст, тло, контраст, потрібно, опис, ок?)."""
    rows = []
    for mode in theme.MODES:
        palette = theme.PALETTES[mode]
        for fg, bg, need, where in PAIRS:
            value = contrast(palette[fg], palette[bg])
            rows.append((mode, fg, bg, value, need, where, value >= need))
    return rows


def literal_report() -> list[tuple[str, int, int, int]]:
    """Хардкоди в панелях: (файл, шрифтів, кольорів, рядків усього)."""
    font_re = re.compile(r"\(\s*[\"']Segoe UI[\"']\s*,\s*\d+")
    colour_re = re.compile(r"#[0-9a-fA-F]{6}\b")
    rows = []
    for path in sorted(IDE.glob("*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        fonts = len(font_re.findall(source))
        colours = len(colour_re.findall(source))
        if fonts or colours:
            rows.append((path.name, fonts, colours, source.count("\n") + 1))
    rows.sort(key=lambda row: (row[1] + row[2]), reverse=True)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Аудит інтерфейсу IDE")
    parser.add_argument("--strict", action="store_true",
                        help="повернути 1, якщо є хоч одне порушення")
    args = parser.parse_args(argv)

    rows = contrast_report()
    fails = [row for row in rows if not row[6]]
    print("── Контраст (WCAG 2.1) ──────────────────────────────────────────")
    current = ""
    for mode, fg, bg, value, need, where, ok in rows:
        if mode != current:
            current = mode
            print(f"\n[{mode}]")
        mark = "ok  " if ok else ("УВАГА" if value >= HARD_FAIL else "ЗБІЙ ")
        print(f"  {mark} {value:5.2f} (треба {need:.1f})  {fg:11} на {bg:10} — {where}")

    literals = literal_report()
    print("\n── Хардкоди шрифтів і кольорів ──────────────────────────────────")
    if not literals:
        print("  немає")
    for name, fonts, colours, lines in literals[:20]:
        print(f"  {name:32} шрифтів={fonts:3} кольорів={colours:3} (рядків {lines})")
    total_fonts = sum(row[1] for row in literals)
    total_colours = sum(row[2] for row in literals)
    print(f"\n  усього: шрифтів={total_fonts}, кольорів={total_colours}, "
          f"файлів={len(literals)}")

    print(f"\nПідсумок: пар з низьким контрастом — {len(fails)} із {len(rows)}.")
    if args.strict and (fails or total_fonts or total_colours):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
