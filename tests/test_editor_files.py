"""Перевірка редактора на реальних файлах різних типів.

Відкриває кожен файл проєкту через CodeEditor, прокручує, шукає та
перевіряє, що підсвітка не падає і не гальмує.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import theme, workspace as ws  # noqa: E402
from blackchpok_ide.editor import CodeEditor  # noqa: E402

failures = 0
SAMPLES = [
    "main.py", "server.py", "agent_tools.py", "vibe_router.py", "rag_engine.py",
    "blackchpok_ide/editor.py", "blackchpok_ide/syntax.py", "blackchpok_ide/main_window.py",
    # README перенесено в docs/ під час наведення порядку в корені проєкту.
    # Раніше вони лежали в корені, тому цей тест падав ще до поточного етапу.
    # Деталі: research/KNOWN_BASELINE_FAILURES.md.
    "docs/README_UK.md", "docs/IDE_README_UK.md", "requirements.txt", ".gitignore",
    "install.bat", "build_exe.bat", "tests/test_ide_core.py",
]


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    fonts = theme.Theme(root)
    fonts.apply()

    total_time = 0.0
    for relative in SAMPLES:
        path = ROOT / relative
        if not path.exists():
            check(f"{relative}: існує", False)
            continue
        content, encoding = ws.read_text_file(path)
        editor = CodeEditor(root, fonts, path.name, on_change=None)
        start = time.perf_counter()
        editor.set_text(content)
        editor.refresh_all()
        editor.text.see("end")
        editor._do_highlight()
        elapsed = time.perf_counter() - start
        total_time += elapsed
        lines = len(content.splitlines())
        check(
            f"{relative}: {lines} рядків, {elapsed * 1000:.0f} мс",
            editor.get_text() == content and elapsed < 2.0,
            encoding,
        )
        # пошук першого слова
        word = next((w for w in content.split() if len(w) > 3), "")
        if word:
            found = editor.search(word[:12])
            check(f"{relative}: пошук «{word[:12]}»", found)
        editor.text.destroy()
        editor.destroy()

    check("середній час відкриття", total_time / len(SAMPLES) < 1.0,
          f"{total_time / len(SAMPLES) * 1000:.0f} мс на файл")

    # редактор без номера рядків і з переносом
    plain = CodeEditor(root, fonts, "x.txt", show_line_numbers=False, word_wrap=True)
    plain.set_text("довгий рядок " * 200)
    plain.refresh_all()
    check("без номерів рядків і з переносом", plain.get_text().startswith("довгий"))
    plain.destroy()

    # коментування та дублювання
    code = CodeEditor(root, fonts, "sample.py")
    code.set_text("x = 1\ny = 2\n")
    code.text.mark_set("insert", "1.0")
    code._toggle_comment()
    first = code.text.get("1.0", "1.end")
    check("коментування додає #", first.startswith("#"), first)
    code._toggle_comment()
    check("коментування знімає #", not code.text.get("1.0", "1.end").startswith("#"))
    code.text.mark_set("insert", "1.0")
    code._duplicate_line()
    check("дублювання рядка", code.text.get("1.0", "end-1c").count("x = 1") == 2)
    code.destroy()

    root.destroy()
    print()
    print("Редактор на реальних файлах:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
