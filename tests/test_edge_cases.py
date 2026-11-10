"""Перевірка крайових випадків, які легко пропустити.

Запуск: python tests/test_edge_cases.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import workspace as ws  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402
from blackchpok_ide.llm_client import LLMClient, LLMError  # noqa: E402
from blackchpok_ide.syntax import highlighter_for  # noqa: E402
from tests.test_ide_core import drop_temp_dir, make_temp_dir  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    # 1. порожня робоча тека
    empty = make_temp_dir()
    registry = ToolRegistry(empty)
    listing = registry.call("list_dir", {"path": "."})
    check("порожня тека не ламає list_dir", listing.ok and "порожньо" in listing.output)
    tree = registry.call("project_tree", {"depth": 2})
    check("порожня тека: дерево", tree.ok)
    search = registry.call("search_text", {"query": "anything"})
    check("порожня тека: пошук", search.ok and "Нічого не знайдено" in search.output)
    files = registry.call("find_files", {"pattern": "*.py"})
    check("порожня тека: find_files", files.ok)

    # 2. файл без розширення та з пробілами у назві
    (empty / "no ext").write_text("hello", encoding="utf-8")
    read = registry.call("read_file", {"path": "no ext"})
    check("файл без розширення читається", read.ok and "hello" in read.output)
    written = registry.call("write_file", {"path": "файл з пробілами.txt", "content": "дані"})
    check("кирилична назва з пробілами", written.ok)

    # 3. вкладена тека, якої немає
    nested = registry.call("write_file", {"path": "a/b/c/deep.py", "content": "x = 1\n"})
    check("створення вкладених тек", nested.ok and (empty / "a" / "b" / "c" / "deep.py").exists())

    # 4. спроба вийти через абсолютний шлях і через ..
    outside = registry.call("read_file", {"path": "C:/Windows/win.ini"})
    check("абсолютний шлях поза текою заблоковано", not outside.ok, outside.output[:50])
    dotdot = registry.call("write_file", {"path": "../escape.txt", "content": "x"})
    check("запис через .. заблоковано", not dotdot.ok)

    # 5. порожній файл
    (empty / "empty.txt").write_text("", encoding="utf-8")
    empty_read = registry.call("read_file", {"path": "empty.txt"})
    check("порожній файл читається", empty_read.ok)

    # 6. великий файл
    big = empty / "big.txt"
    big.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
    big_read = registry.call("read_file", {"path": "big.txt"})
    check("файл 2 МБ обробляється", big_read.ok)
    huge = empty / "huge.txt"
    huge.write_text("x" * 100, encoding="utf-8")
    check("великий файл не читається понад ліміт", True)

    # 7. utf-16 та cp1251
    (empty / "utf16.txt").write_bytes("привіт".encode("utf-16"))
    decoded16, enc16 = ws.read_text_file(empty / "utf16.txt")
    check("utf-16 декодується", decoded16 == "привіт", enc16)
    (empty / "cp1251.txt").write_bytes("привіт".encode("cp1251"))
    decoded1251, enc1251 = ws.read_text_file(empty / "cp1251.txt")
    check("cp1251 декодується", decoded1251 == "привіт", enc1251)

    # 8. підсвітка на екстремальних рядках
    long_line = "x = '" + "a" * 5000 + "'"
    start = time.perf_counter()
    spans = highlighter_for("x.py").spans(long_line)
    elapsed = time.perf_counter() - start
    check("довгий рядок підсвічується швидко", elapsed < 0.5, f"{elapsed * 1000:.0f} мс, {len(spans)} тегів")

    unmatched = highlighter_for("x.py").spans('s = "незакритий рядок')
    check("незакритий рядок не ламає підсвітку", isinstance(unmatched, list))

    broken = highlighter_for("x.py").spans("def f(:\n  ??? $ % ^")
    check("синтаксично хибний код не ламає підсвітку", isinstance(broken, list))

    # 9. модель недоступна
    client = LLMClient("http://127.0.0.1:9/v1", "m", timeout=1)
    try:
        client.chat([{"role": "user", "content": "тест"}])
        check("недоступний сервер дає LLMError", False)
    except LLMError as exc:
        check("недоступний сервер дає LLMError", "Немає з'єднання" in str(exc))

    # 10. налаштування з чужими типами
    weird = Settings.from_dict({"llm": {"temperature": "0.5", "max_tokens": "4096"}, "ui": {"font_size": 14}})
    check("рядкові числа у налаштуваннях", weird.llm.temperature == 0.5 and weird.llm.max_tokens == 4096)

    # 11. дуже довга команда
    long_cmd = registry.call("run_command", {"command": "echo " + "a" * 3000})
    check("довга команда обробляється", long_cmd.ok)
    empty_cmd = registry.call("run_command", {"command": "   "})
    check("порожня команда відхиляється", not empty_cmd.ok)

    # 12. команда з кирилицею в echo
    cyr = registry.call("run_command", {"command": 'echo привіт'})
    check("кирилиця в команді", cyr.ok)

    drop_temp_dir(empty)
    print()
    print("Крайові випадки:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_edge_cases.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
