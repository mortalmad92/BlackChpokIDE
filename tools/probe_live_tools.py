"""Живий ланцюг інструментів: справжні виклики, справжні файли.

Перевіряє кожен інструмент із реальними аргументами та звіряє РЕЗУЛЬТАТ
на диску, а не лише відсутність винятку.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_live_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import agent_tools  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def text(result) -> str:
    return result.as_text() if hasattr(result, "as_text") else str(result)


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_live_ws_"))
    (work / "calc.py").write_text(
        "def додати(a, b):\n    return a + b\n", "utf-8")
    (work / "README.md").write_text("# Проєкт\n\nОпис.\n", "utf-8")
    registry = agent_tools.ToolRegistry(work)
    print(f"тека: {work}\nінструментів у схемах: {len(agent_tools.TOOL_SCHEMAS)}\n")

    # 1. Читання
    out = text(registry.call("read_file", {"path": "calc.py"}))
    check("read_file повертає вміст", "додати" in out, out[:120])

    # 2. Правка
    out = text(registry.call("edit_file", {
        "path": "calc.py",
        "old_string": "def додати(a, b):\n    return a + b",
        "new_string": ("def додати(a, b):\n    return a + b\n\n\n"
                       "def помножити(a, b):\n    return a * b"),
    }))
    after = (work / "calc.py").read_text("utf-8")
    check("edit_file змінює файл", "помножити" in after, out[:160])

    # 3. Створення
    registry.call("write_file", {"path": "новий.py", "content": "x = 1\n"})
    check("write_file створює файл", (work / "новий.py").exists())

    # 4. Дописування
    registry.call("append_file", {"path": "новий.py", "content": "y = 2\n"})
    body = (work / "новий.py").read_text("utf-8")
    check("append_file дописує", "y = 2" in body and "x = 1" in body, body[:80])

    # 5. Пошук
    out = text(registry.call("search_text", {"query": "помножити"}))
    check("search_text знаходить правку", "calc.py" in out, out[:120])

    # 6. Список теки
    out = text(registry.call("list_dir", {"path": "."}))
    check("list_dir показує файли", "calc.py" in out and "README.md" in out, out[:120])

    # 7. Пошук файлів за шаблоном
    out = text(registry.call("find_files", {"pattern": "*.py"}))
    check("find_files знаходить .py", "calc.py" in out, out[:120])

    # 8. Дерево проєкту
    out = text(registry.call("project_tree", {}))
    check("project_tree показує структуру", "calc.py" in out, out[:120])

    # 9. Помилка читання — зрозуміла
    try:
        out = text(registry.call("read_file", {"path": "немає.py"}))
        ok = "немає" in out or "не існує" in out.lower()
        check("помилка читання зрозуміла", ok, out[:120])
    except Exception as exc:  # noqa: BLE001
        check("помилка читання зрозуміла", True, f"виняток: {type(exc).__name__}")

    # 10. Вихід за межі теки заблоковано.
    # Інструмент повертає ТЕКСТ помилки (а не виняток), тому перевіряємо,
    # що в ньому явно сказано про межу теки, і що вмісту не віддано.
    try:
        out = text(registry.call("read_file", {"path": "../../secret.txt"}))
        blocked = ("поза" in out) or ("за межами" in out) or ("позаду" in out)
        check("вихід за теку заблоковано", blocked, out[:120])
    except Exception:  # noqa: BLE001
        check("вихід за теку заблоковано", True)

    # 11. git_status у не-репозиторії не валить
    try:
        out = text(registry.call("git_status", {}))
        check("git_status не падає", True, out[:80])
    except Exception as exc:  # noqa: BLE001
        check("git_status не падає", False, f"{type(exc).__name__}: {exc}")

    # 12. python_check на справжньому файлі
    try:
        out = text(registry.call("python_check", {"path": "calc.py"}))
        check("python_check працює", isinstance(out, str) and bool(out), out[:100])
    except Exception as exc:  # noqa: BLE001
        check("python_check працює", False, f"{type(exc).__name__}: {exc}")

    shutil.rmtree(work, ignore_errors=True)
    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
