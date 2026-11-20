"""Разовa міграція хардкод-шрифтів на theme.font().

Замінює ``("Segoe UI", 8)`` → ``theme.font(8)``, ``("Segoe UI", 8, "bold")``
→ ``theme.font(8, "bold")`` у модулях пакета. Файли без імпорту ``theme``
не чіпає: там заміна зламала б імпорт.

Запуск:  python tools/migrate_fonts.py [--check]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "blackchpok_ide"

PATTERN = re.compile(
    r'\(\s*"Segoe UI"\s*,\s*(?P<size>\d+)(?P<rest>(?:\s*,\s*"(?:bold|italic|normal)"[^)]*)?)\s*\)'
)


def convert(text: str) -> tuple[str, int]:
    """Замінити всі входження; повернути (новий текст, кількість)."""
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        size = match.group("size")
        rest = (match.group("rest") or "").strip()
        count += 1
        if not rest:
            return f"theme.font({size})"
        # ``, "bold"`` або ``,"italic"`` чи вираз на кшталт
        # ``"bold" if active else "normal"`` — переносимо як є.
        rest = rest.lstrip(",").strip()
        return f"theme.font({size}, {rest})"

    return PATTERN.sub(repl, text), count


def has_theme(text: str) -> bool:
    """Чи імпортує файл ``theme`` (зокрема багаторядковим ``from . import (…)``)."""
    return bool(re.search(r"from\s+\.\s+import\s*\(?[^)]*\btheme\b", text, re.DOTALL))


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    total = 0
    touched: list[tuple[str, int]] = []
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name == "theme.py":
            continue                      # тут самі означення, не вживання
        source = path.read_text(encoding="utf-8")
        if '"Segoe UI"' not in source:
            continue
        if not has_theme(source):
            print(f"skip (без імпорту theme): {path.name}")
            continue
        new, count = convert(source)
        if not count:
            continue
        total += count
        touched.append((path.name, count))
        if not check_only:
            path.write_text(new, encoding="utf-8")
    for name, count in touched:
        print(f"{'[check] ' if check_only else ''}{name}: {count}")
    print(f"усього: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
