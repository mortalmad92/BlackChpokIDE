"""Перевірка механічного виправлення апострофів у лапках."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent import _fix_apostrophes, _line_breaks_quotes  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    # 1. Класичний випадок: апостроф усередині одинарних лапок
    bad = "name = input('Введіть ім'я: ')\n"
    check("рядок розпізнано як зламаний", _line_breaks_quotes(bad.rstrip()))
    fixed = _fix_apostrophes(bad)
    check("лапки замінено на подвійні", '"' in fixed, fixed.strip())
    try:
        compile(fixed, "<t>", "exec", dont_inherit=True)
        check("виправлений код компілюється", True, fixed.strip())
    except SyntaxError as exc:
        check("виправлений код компілюється", False, str(exc))

    # 2. Коректний код НЕ чіпаємо
    good = 'name = input("Введіть ім\'я: ")\n'
    check("коректний рядок не вважається зламаним",
          not _line_breaks_quotes(good.rstrip()))
    check("коректний код лишається без змін",
          _fix_apostrophes(good) == good, _fix_apostrophes(good).strip())

    # 3. Простий рядок без апострофа — без змін
    simple = "print('привіт')\n"
    check("простий рядок не змінюється",
          _fix_apostrophes(simple) == simple)

    # 4. Два рядки: ламається лише один
    mixed = ("print('ок')\n"
             "name = input('Ваше ім'я: ')\n"
             "print(name)\n")
    healed = _fix_apostrophes(mixed)
    try:
        compile(healed, "<t>", "exec", dont_inherit=True)
        check("суміш рядків виправлено повністю", True, healed.splitlines()[1])
    except SyntaxError as exc:
        check("суміш рядків виправлено повністю", False, str(exc))

    # 5. Виправлення не чіпає вже правильний f-рядок
    fstring = "print(f'Привіт, {name}!')\n"
    check("f-рядок без апострофа не змінюється",
          _fix_apostrophes(fstring) == fstring)

    print()
    print("Виправлення лапок:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
