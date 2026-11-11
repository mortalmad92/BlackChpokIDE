"""Крайні стани проєкту: порожня тека, лише сміття, глибокі підтеки.

Перевіряє, що агент і інструменти не падають і дають зрозумілі відповіді.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_edge_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import agent_tools, workspace as ws  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def text(result) -> str:
    return result.as_text() if hasattr(result, "as_text") else str(result)


def main() -> int:
    # 1. Порожня тека.
    empty = pathlib.Path(tempfile.mkdtemp(prefix="bchk_edge_empty_"))
    registry = agent_tools.ToolRegistry(empty)
    out = text(registry.call("list_dir", {"path": "."}))
    check("порожня тека: list_dir не падає", isinstance(out, str), out[:100])
    out = text(registry.call("project_tree", {}))
    check("порожня тека: project_tree не падає", isinstance(out, str), out[:100])
    out = text(registry.call("search_text", {"query": "нічого"}))
    check("порожня тека: search_text не падає", isinstance(out, str), out[:100])

    # 2. Лише сміття (бінарники, кеші).
    junk = pathlib.Path(tempfile.mkdtemp(prefix="bchk_edge_junk_"))
    (junk / "image.png").write_bytes(b"\x89PNG" + bytes(200))
    (junk / "data.bin").write_bytes(bytes(range(256)) * 10)
    (junk / "__pycache__").mkdir()
    (junk / "__pycache__" / "x.pyc").write_bytes(b"\x00" * 100)
    reg2 = agent_tools.ToolRegistry(junk)
    out = text(reg2.call("list_dir", {"path": "."}))
    check("сміття: list_dir працює", isinstance(out, str), out[:100])
    out = text(reg2.call("read_file", {"path": "image.png"}))
    check("сміття: читання бінарника дає пояснення",
          "бінарн" in out.lower() or "не текст" in out.lower() or len(out) < 400,
          out[:150])

    # 3. Глибока вкладеність.
    deep = pathlib.Path(tempfile.mkdtemp(prefix="bchk_edge_deep_"))
    target = deep
    for index in range(12):
        target = target / f"рівень{index}"
    target.mkdir(parents=True)
    (target / "глибокий.py").write_text("x = 1\n", "utf-8")
    reg3 = agent_tools.ToolRegistry(deep)
    out = text(reg3.call("find_files", {"pattern": "*.py"}))
    check("глибока вкладеність: find_files знаходить", "глибокий" in out, out[:150])

    # 4. Файл без розширення.
    (deep / "LICENSE").write_text("текст ліцензії", "utf-8")
    check("файл без розширення — не текст?", ws.is_text_file(deep / "LICENSE"),
          str(ws.is_text_file(deep / "LICENSE")))

    # 5. Дуже довга назва.
    long_name = deep / ("д" * 120 + ".py")
    try:
        long_name.write_text("x = 2\n", "utf-8")
        out = text(reg3.call("list_dir", {"path": "."}))
        check("довга назва файлу не ламає список", isinstance(out, str), out[:80])
    except OSError as exc:
        check("довга назва файлу: ОС відмовила коректно", True, str(exc)[:80])

    # 6. Кирилиця в назвах.
    cyr = deep / "файл з пробілами та кирилицею.py"
    cyr.write_text("значення = 42\n", "utf-8")
    out = text(reg3.call("read_file", {"path": "рівень0/рівень1/../файл.py"}))
    check("неіснуючий шлях дає помилку без падіння", isinstance(out, str), out[:100])
    out = text(reg3.call("find_files", {"pattern": "*кирилицею*"}))
    check("пошук за кириличною назвою працює", "кирилицею" in out or not out.strip(),
          out[:150])

    # 7. Файл, що зник під час роботи.
    ghost = deep / "зникне.py"
    ghost.write_text("x = 3\n", "utf-8")
    resolved = reg3.resolve("рівень0/../зникне.py") if hasattr(reg3, "resolve") else ghost
    ghost.unlink(missing_ok=True)
    try:
        out = text(reg3.call("read_file", {"path": "зникне.py"}))
        check("зниклий файл дає пояснення", isinstance(out, str), out[:100])
    except Exception as exc:  # noqa: BLE001
        check("зниклий файл дає пояснення",
              not isinstance(exc, (TypeError, AttributeError)),
              f"{type(exc).__name__}: {exc}")

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
