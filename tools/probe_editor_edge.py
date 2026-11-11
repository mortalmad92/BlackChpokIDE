"""Редактор на складних файлах: великий розмір, кодування, крайні випадки.

Перевіряє відкриття/правку/збереження реальних проблемних файлів:
BOM, CRLF, дуже довгі рядки, не-UTF8, порожні файли.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_edit_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import workspace as ws  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_edit_ws_"))

    # 1. UTF-8 з BOM: BOM не має потрапляти у вміст.
    bom = work / "bom.py"
    bom.write_bytes("\ufeffx = 1\n".encode("utf-8"))
    content, encoding = ws.read_text_file(bom)
    check("BOM не потрапляє у вміст", not content.startswith("\ufeff"),
          repr(content[:10]))
    check("кодування визначено", bool(encoding), encoding)

    # 2. CP1251: читається без винятку.
    legacy = work / "legacy.txt"
    legacy.write_bytes("Привіт, світ\n".encode("cp1251"))
    try:
        content, encoding = ws.read_text_file(legacy)
        check("cp1251 читається", "Привіт" in content, content[:40])
    except Exception as exc:  # noqa: BLE001
        check("cp1251 читається", False, f"{type(exc).__name__}: {exc}")

    # 3. CRLF не ламає рядки.
    crlf = work / "crlf.py"
    crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
    content, _ = ws.read_text_file(crlf)
    check("CRLF дає два рядки", len(content.splitlines()) == 2,
          str(content.splitlines()))

    # 4. Дуже довгий рядок.
    long_line = work / "long.py"
    long_line.write_text("x = '" + "а" * 100_000 + "'\n", "utf-8")
    try:
        content, _ = ws.read_text_file(long_line)
        check("довгий рядок читається", len(content) > 99_000, f"{len(content)}")
    except Exception as exc:  # noqa: BLE001
        check("довгий рядок читається", False, f"{type(exc).__name__}")

    # 5. Порожній файл не падає.
    empty = work / "empty.py"
    empty.write_text("", "utf-8")
    try:
        content, _ = ws.read_text_file(empty)
        check("порожній файл читається", content == "", repr(content))
    except Exception as exc:  # noqa: BLE001
        check("порожній файл читається", False, f"{type(exc).__name__}")

    # 6. Бінарний файл не відкривається як текст.
    binary = work / "img.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    check("бінарний розпізнано", not ws.is_text_file(binary))

    # 7. Запис не ламає кодування.
    target = work / "write.py"
    ws.write_text_file(target, "def привіт():\n    return 'світ'\n")
    back, _ = ws.read_text_file(target)
    check("запис і читання зберігають текст", "привіт" in back, back[:40])

    # 8. Вихід за межі теки блокується на РІВНІ, призначеному для цього.
    # ``write_text_file`` — низькорівневий хелпер запису (ним користуються
    # для шляхів, які вже перевірені); межа теки тримається на ``safe_join``
    # і ``ToolRegistry.resolve``. Перевіряємо саме їх.
    for raw in ("..", "../вихід.py", "sub/../../вихід.py"):
        try:
            ws.safe_join(work, raw)
            check(f"вихід «{raw}» заблоковано", False, "дозволено")
        except Exception:  # noqa: BLE001
            check(f"вихід «{raw}» заблоковано", True)
    # А дозволений шлях — проходить і записується.
    inside = ws.safe_join(work, "sub/дозволено.py")
    ws.write_text_file(inside, "x = 1\n")
    check("дозволений шлях записується", inside.exists(), str(inside))

    # 9. Швидкість на великому файлі.
    big = work / "big.py"
    big.write_text("x = 1\n" * 100_000, "utf-8")
    import time
    started = time.monotonic()
    content, _ = ws.read_text_file(big)
    took = time.monotonic() - started
    check("великий файл (1.2 МБ) швидко", took < 3.0, f"{took:.2f} с")
    check("великий файл прочитано повністю", len(content.splitlines()) == 100_000,
          str(len(content.splitlines())))

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
