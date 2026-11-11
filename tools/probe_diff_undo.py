"""Панель змін і відкат: правка → diff → повернення старого вмісту.

Перевіряє, що користувач справді бачить різницю й може відкотити зміну.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_diff_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import agent_tools, diff_stats  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_diff_ws_"))
    db = pathlib.Path(tempfile.mkdtemp(prefix="bchk_diff_db_")) / "state.sqlite"
    registry = agent_tools.ToolRegistry(work)

    target = work / "код.py"
    target.write_text("def f():\n    return 1\n", "utf-8")

    # 1. Правка створює резервну копію.
    registry.call("edit_file", {
        "path": "код.py",
        "old_string": "    return 1",
        "new_string": "    return 2",
    })
    changed = target.read_text("utf-8")
    check("правка застосована", "return 2" in changed, changed)
    backup = pathlib.Path(str(target) + ".bak")
    check("резервна копія створена", backup.exists(), str(backup))
    if backup.exists():
        check("резервна копія містить старий вміст",
              "return 1" in backup.read_text("utf-8"),
              backup.read_text("utf-8"))

    # 2. Diff показує різницю.
    try:
        old_text = backup.read_text("utf-8")
        diff = diff_stats.make_unified_diff(old_text, changed, "код.py")
        check("diff знаходить зміну", "-    return 1" in diff and "+    return 2" in diff,
              diff[:160])
        counts = diff_stats.count_line_diff(old_text, changed)
        check("diff рахує рядки", bool(counts), str(counts))
    except Exception as exc:  # noqa: BLE001
        check("diff працює", False, f"{type(exc).__name__}: {exc}")

    # 3. Відкат через резервну копію повертає старий вміст.
    import shutil
    shutil.copy2(backup, target)
    check("відкат із .bak повертає старий вміст",
          "return 1" in target.read_text("utf-8"), target.read_text("utf-8")[:60])

    # 4. Diff між двома довільними текстами не падає.
    try:
        left = "a\nb\nc\n"
        right = "a\nB\nc\nd\n"
        result = diff_stats.make_unified_diff(left, right, "x.txt")
        check("diff між текстами працює", bool(result) and "+" in result, result[:100])
    except Exception as exc:  # noqa: BLE001
        check("diff між текстами працює", False, f"{type(exc).__name__}: {exc}")

    # 5. Порожній файл у diff.
    try:
        empty = work / "порожній.py"
        empty.write_text("", "utf-8")
        registry.call("read_file", {"path": "порожній.py"})
        check("порожній файл у реєстрі не падає", True)
    except Exception as exc:  # noqa: BLE001
        check("порожній файл у реєстрі не падає", False,
              f"{type(exc).__name__}: {exc}")

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
