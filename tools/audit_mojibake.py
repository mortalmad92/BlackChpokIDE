"""Точний детектор cp1251-побиття в .py файлах.

Побиття виникає, коли UTF-8 байти українського тексту прочитано як cp1251
і знову збережено як UTF-8: «Файл» -> «Р¤Р°Р№Р»». Кожен кириличний символ
перетворюється на 2 символи, перший з яких майже завжди Р або С.
Надійна ознака — наявність символів, яких в українській мові не буває,
але які є в cp1251 (Ђ, Ѓ, Ѕ, Ј, Љ, Њ, Ћ, Ќ, Ў, Џ, ђ, ѓ, ѕ, ј, љ, њ, ћ, ќ, ў, џ),
або пар «С–», «С‚», «Сѓ» (ен-дефіс замість і, кома-замість т тощо).
"""
from __future__ import annotations

import pathlib
import sys

SKIP_DIRS = {".venv", "userdata", ".git", "node_modules", ".buildtmp", ".quarantine",
             "__pycache__", "dist", "build", ".mypy_cache", ".pytest_cache"}

# Символи cp1251, яких немає в українській мові.
# Ё ё Є Ї навмисно НЕ входять: вони нормальні в українських текстах, і
# додавання їх давало хибні сигнали на кожному «Є» в реченні.
IMPOSSIBLE = ("\u0402\u0403\u0405\u0408\u0409\u040a\u040b\u040c\u040e\u040f"
              "\u0452\u0453\u0455\u0458\u0459\u045a\u045b\u045c\u045e\u045f")

# Пари, що виникають лише з побиття: С + пунктуація/знак.
MOJI_PAIRS = ("\u0421\u2013", "\u0421\u201a", "\u0421\u0453", "\u0421\u0402",
              "\u0420\u00b0", "\u0420\u00b5", "\u0420\u0451", "\u0420\u0405")


def score(text: str) -> tuple[int, int]:
    """Повертає (кількість неможливих символів, кількість побитих пар)."""
    imp = sum(1 for ch in text if ch in IMPOSSIBLE)
    pairs = sum(text.count(p) for p in MOJI_PAIRS)
    return imp, pairs


def main() -> int:
    root = pathlib.Path(".")
    # Цей файл МІСТИТЬ неможливі символи навмисно — у власному переліку й
    # у прикладах документації. Без винятку детектор знаходив би самого
    # себе й показував хибний «підозрілий файл».
    itself = pathlib.Path(__file__).resolve()
    rows = []
    for path in sorted(root.rglob("*.py")):
        parts = set(path.parts)
        if parts & SKIP_DIRS:
            continue
        try:
            if path.resolve() == itself:
                continue
        except OSError:
            pass
        try:
            text = path.read_text("utf-8")
        except OSError as exc:
            print(f"READFAIL {path}: {exc}")
            continue
        imp, pairs = score(text)
        if imp or pairs:
            rows.append((imp + pairs, imp, pairs, str(path), len(text)))
    rows.sort(reverse=True)
    print(f"підозрілих файлів: {len(rows)}")
    for total, imp, pairs, name, length in rows:
        print(f"{total:7d} (imp={imp:5d} pairs={pairs:5d}) {length:8d}B  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
