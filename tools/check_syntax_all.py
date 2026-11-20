"""Швидка перевірка синтаксису всіх Python-файлів проєкту (крок 1 тест-плану)."""
from __future__ import annotations

import pathlib
import py_compile

SKIP_PARTS = {".venv", "build", "dist", "__pycache__", ".git", ".quarantine", ".ruff_cache"}
SKIP_DIRS = {".pytest_cache", ".mypy_cache", "node_modules"}


def main() -> int:
    root = pathlib.Path(".")
    files: list[pathlib.Path] = []
    for p in root.rglob("*.py"):
        parts = set(p.parts)
        if parts & SKIP_PARTS or parts & SKIP_DIRS:
            continue
        files.append(p)

    bad: list[tuple[str, str]] = []
    for p in files:
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:  # noqa: BLE001
            bad.append((str(p), f"{type(e).__name__}: {str(e)[:160]}"))

    print(f"FILES {len(files)}")
    print(f"BAD {len(bad)}")
    for path, err in bad:
        print(f"{path} -> {err}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
