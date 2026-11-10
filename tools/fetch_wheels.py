"""Завантажити чисті wheel-файли з PyPI і розпакувати у site-packages.

Потрібно, коли ``pip install`` недоступний (наприклад, пісочниця забороняє
запис у тимчасові каталоги pip). Скрипт не запускає setup.py і не виконує
жодного коду з пакетів: лише розпаковує wheel як zip.

Приклад:
    python tools/fetch_wheels.py pyinstaller altgraph pefile pywin32-ctypes
"""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

PYPI_JSON = "https://pypi.org/pypi/{name}/json"
SITE_PACKAGES = Path(sys.prefix) / "Lib" / "site-packages"


def _target_wheel(urls: list[dict]) -> dict | None:
    """Вибрати wheel для поточної платформи: win_amd64, потім any, потім win32."""
    def score(item: dict) -> int:
        name = item.get("filename", "")
        if not name.endswith(".whl"):
            return -1
        if "py3-none-any" in name:
            return 3
        if "win_amd64" in name:
            return 2
        if "win32" in name:
            return 1
        return -1

    best = max(urls, key=score, default=None)
    if best is None or score(best) < 0:
        return None
    return best


def fetch(name: str, dest: Path) -> Path | None:
    with urllib.request.urlopen(PYPI_JSON.format(name=name), timeout=60) as resp:
        payload = json.load(resp)
    wheel = _target_wheel(payload.get("urls", []))
    if wheel is None:
        print(f"Немає wheel для {name}", file=sys.stderr)
        return None
    path = dest / wheel["filename"]
    if not path.exists():
        with urllib.request.urlopen(wheel["url"], timeout=180) as resp:
            path.write_bytes(resp.read())
    return path


def unpack(wheel: Path, site: Path) -> int:
    count = 0
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename.startswith(".dist-info/RECORD"):
                continue
            target = site / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            count += 1
    return count


def main(argv: list[str]) -> int:
    names = argv or ["pyinstaller"]
    cache = Path(__file__).resolve().parent.parent / ".buildtmp" / "wheels"
    cache.mkdir(parents=True, exist_ok=True)
    SITE_PACKAGES.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name in names:
        try:
            wheel = fetch(name, cache)
            if wheel is None:
                failures += 1
                continue
            count = unpack(wheel, SITE_PACKAGES)
            print(f"{name}: {wheel.name} -> {count} файлів")
        except Exception as exc:  # noqa: BLE001 - діагностика для користувача
            failures += 1
            print(f"{name}: помилка {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
