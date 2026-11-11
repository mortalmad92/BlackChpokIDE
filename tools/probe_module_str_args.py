"""Прогін публічних функцій пакета з РЯДКОВИМИ шляхами.

Панелі, JSON-аргументи інструментів і команди передають шляхи рядками.
Функція, що заявлена як ``path: Path``, але робить ``path.exists()``,
падає ``AttributeError`` — і дія тихо не виконується.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\AI\blackchpock_ai")
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_str_"))

ROOT = Path(r"C:\AI\blackchpock_ai")

#: (модуль, функція, аргументи-рядки)
CASES: list[tuple[str, str, tuple]] = [
    ("imaging", "image_info", ("sample.png",)),
    ("skills", "load_skill", ("SKILL.md",)),
    # hmr.update_for_file першим бере СЕСІЮ, тому шлях другим аргументом.
    ("bench", "save", ({"a": 1}, "bench.json")),
    ("diff_stats", "read_text_safe", ("a.py",)),
    ("diff_stats", "diff_file_pair", ("a.py", "b.py")),
    ("file_tree", "icon_for", ("a.py",)),
    ("file_tree", "is_binary", ("a.py",)),
    ("config", "load", ("settings.json",)),
    ("layout", "load", ("layout.json",)),

    ("hardware", "detect", (".",)),
    ("auto_setup", "profile_project", (".",)),
    ("auto_setup", "existing_skill_names", (".",)),
    ("autonomous", "analyse_project", (".",)),
    ("diff_stats", "git_changes", (".",)),
    ("diff_stats", "git_branch", (".",)),
    ("diff_stats", "detect_changes", (".",)),
]


def build_workspace() -> Path:
    work = Path(tempfile.mkdtemp(prefix="bchk_str_ws_"))
    (work / "a.py").write_text("x = 1\n", "utf-8")
    (work / "b.py").write_text("x = 2\n", "utf-8")
    (work / "index.html").write_text("<html></html>\n", "utf-8")
    (work / "SKILL.md").write_text("---\nname: test\n---\nТіло.\n", "utf-8")
    # Мінімальний PNG 1×1.
    (work / "sample.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    return work


def main() -> int:
    work = build_workspace()
    cwd = os.getcwd()
    problems = 0
    for module_name, func_name, args in CASES:
        module = __import__(f"blackchpok_ide.{module_name}", fromlist=[func_name])
        func = getattr(module, func_name, None)
        if func is None:
            print(f"SKIP {module_name}.{func_name} — немає функції")
            continue
        os.chdir(work)
        try:
            func(*args)
            print(f"OK   {module_name}.{func_name}(рядок)")
        except (AttributeError, TypeError) as exc:
            print(f"FAIL {module_name}.{func_name}(рядок) — "
                  f"{type(exc).__name__}: {str(exc)[:110]}")
            problems += 1
        except Exception as exc:  # noqa: BLE001 - інші помилки теж показуємо
            print(f"WARN {module_name}.{func_name}(рядок) — "
                  f"{type(exc).__name__}: {str(exc)[:110]}")
            traceback.print_exc(limit=1)
        finally:
            os.chdir(cwd)
    print(f"\nпроблем: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
