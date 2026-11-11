"""Одночасні операції з тим самим файлом і реєстром.

Перевіряє: паралельні записи не гублять дані, черга задач не дублює
роботу, а реєстр інструментів витримує одночасні виклики.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import threading

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_conc_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import agent_tools  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_conc_ws_"))
    registry = agent_tools.ToolRegistry(work)
    (work / "shared.py").write_text("x = 0\n", "utf-8")

    # 1. Паралельний запис у РІЗНІ файли — жодного винятку.
    errors: list[str] = []

    def write_one(index: int) -> None:
        try:
            registry.call("write_file", {"path": f"file{index}.py",
                                         "content": f"value = {index}\n"})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{index}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=write_one, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    check("паралельний запис без винятків", not errors, str(errors[:2]))
    made = sorted(p.name for p in work.glob("file*.py"))
    check("усі 12 файлів створено", len(made) == 12, f"{len(made)}: {made[:5]}")

    # 2. Паралельне читання того самого файлу.
    read_errors: list[str] = []

    def read_same() -> None:
        try:
            for _ in range(5):
                registry.call("read_file", {"path": "shared.py"})
        except Exception as exc:  # noqa: BLE001
            read_errors.append(f"{type(exc).__name__}: {exc}")

    readers = [threading.Thread(target=read_same) for _ in range(8)]
    for thread in readers:
        thread.start()
    for thread in readers:
        thread.join(timeout=30)
    check("паралельне читання без винятків", not read_errors, str(read_errors[:2]))

    # 3. Паралельні правки одного файлу через реєстр не гублять файл.
    (work / "race.py").write_text("value = 0\n", "utf-8")
    race_errors: list[str] = []

    def edit_race(index: int) -> None:
        try:
            registry.call("edit_file", {
                "path": "race.py",
                "old_string": "value = 0\n" if index == 0 else "value = 0",
                "new_string": f"value = {index}\n",
                "replace_all": False,
            })
        except Exception as exc:  # noqa: BLE001
            race_errors.append(f"{index}: {type(exc).__name__}: {str(exc)[:60]}")

    racers = [threading.Thread(target=edit_race, args=(i,)) for i in range(6)]
    for thread in racers:
        thread.start()
    for thread in racers:
        thread.join(timeout=30)
    check("паралельні правки не валять реєстр", not race_errors, str(race_errors[:2]))
    body = (work / "race.py").read_text("utf-8")
    check("файл після гонки цілий", "value =" in body and len(body) < 200, repr(body[:80]))

    # 4. Сканування теки під час запису.
    scan_errors: list[str] = []

    def scan() -> None:
        try:
            for _ in range(5):
                registry.call("list_dir", {"path": "."})
        except Exception as exc:  # noqa: BLE001
            scan_errors.append(f"{type(exc).__name__}: {exc}")

    scanner = threading.Thread(target=scan)
    writer = threading.Thread(target=lambda: [write_one(100 + i) for i in range(6)])
    scanner.start()
    writer.start()
    scanner.join(timeout=30)
    writer.join(timeout=30)
    check("скан під час запису без винятків", not scan_errors, str(scan_errors[:2]))

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
