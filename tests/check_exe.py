"""Перевірити, що зібраний BlackChpok.exe відкриває вікно.

Запуск: python tests/check_exe.py dist\\BlackChpok.exe [скриншот.png]

Скрипт сам підбирає робочу тимчасову теку. Однофайловий .exe розпаковує
вміст у %TEMP%\\_MEI* ще до старту Python, тому якщо теку заборонено
(антивірус, політика ярликів цілісності, чужий профіль), PyInstaller показує
«Could not create temporary directory!» і вікно IDE не з'являється.
Тут такий випадок розпізнається й повторюється з резервною текою.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FALLBACK_TEMP = ROOT / ".buildtmp" / "exe_temp"

# Вікно-помилка PyInstaller, яке треба відрізняти від вікна IDE
ERROR_TITLES = ("Error", "Помилка", "Fatal error")


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


_ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _windows_of(pid: int) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """Повертає [(клас, заголовок, (x, y, ширина, висота))] для видимих вікон процесу."""
    user32 = ctypes.windll.user32
    found: list[tuple[str, str, tuple[int, int, int, int]]] = []

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        rect = _RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        box = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        found.append((cls.value, title.value, box))
        return True

    user32.EnumWindows(_ENUM_PROC(callback), 0)
    return found


def _child_pid_of(pid: int) -> int:
    """Однофайловий .exe запускає дочірній процес — вікно IDE малює саме він."""
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"Name='{Path(sys.argv[1] if len(sys.argv) > 1 else 'BlackChpok.exe').name}' AND ParentProcessId={pid}\").ProcessId",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        ).stdout.strip()
        return int(out.splitlines()[0]) if out else pid
    except Exception:  # noqa: BLE001
        return pid


def _launch(exe: Path, temp_dir: str | None) -> subprocess.Popen:
    env = dict(os.environ)
    env["BLACKCHPOK_HOME"] = str(ROOT / ".buildtmp" / "exe_home")
    if temp_dir:
        env["TEMP"] = temp_dir
        env["TMP"] = temp_dir
    return subprocess.Popen([str(exe), str(ROOT)], env=env)


def _wait_for_window(proc: subprocess.Popen, seconds: float = 20.0):
    """Чекає на вікно IDE. Повертає (вікно | None, діагноз)."""
    deadline = time.time() + seconds
    diagnosis = "вікно не з'явилося"
    while time.time() < deadline:
        if proc.poll() is not None:
            return None, f"процес завершився з кодом {proc.returncode}"
        for pid in {proc.pid, _child_pid_of(proc.pid)}:
            for cls, title, box in _windows_of(pid):
                if cls == "TkTopLevel" and title:
                    return (title, box), ""
                if title in ERROR_TITLES:
                    return None, f"вікно-помилка «{title}» замість IDE"
        time.sleep(0.5)
    return None, diagnosis


def _shots(shot: Path, box: tuple[int, int, int, int]) -> bool:
    try:
        from PIL import ImageGrab

        x, y, width, height = box
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        shot.parent.mkdir(parents=True, exist_ok=True)
        image.save(shot)
        print(f"скриншот: {shot} {image.size}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"скриншот не вдався: {exc}")
        return False


def _stop(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        proc.kill()


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "BlackChpok.exe"
    shot = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".buildtmp" / "exe.png"
    if not exe.exists():
        print(f"немає файлу {exe}")
        return 1

    attempts: list[tuple[str, str | None]] = [("типова %TEMP%", None)]
    try:
        FALLBACK_TEMP.mkdir(parents=True, exist_ok=True)
        attempts.append((f"резервна тека {FALLBACK_TEMP}", str(FALLBACK_TEMP)))
    except OSError as exc:
        print(f"резервну теку створити не вдалося: {exc}")

    for label, temp_dir in attempts:
        print(f"\nспроба: {label}")
        proc = _launch(exe, temp_dir)
        try:
            window, why = _wait_for_window(proc)
            if window is None:
                print(f"  невдача: {why}")
                continue
            title, box = window
            print(f"  вікно IDE: «{title}» {box[2]}x{box[3]}")
            _shots(shot, box)
            print("  результат: .exe працює")
            return 0
        finally:
            _stop(proc)

    print(
        "\nОднофайловий .exe не зміг розпакуватися в тимчасову теку.\n"
        "Це середовище (права на теку), а не помилка IDE. Варіанти:\n"
        "  1) додати теку проєкту в дозволи антивіруса/політики;\n"
        "  2) зібрати варіант без розпакування: pyinstaller --onedir ...;\n"
        "  3) задати робочу теку вручн��:  $env:TEMP='<тека>'; $env:TMP=$env:TEMP"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
