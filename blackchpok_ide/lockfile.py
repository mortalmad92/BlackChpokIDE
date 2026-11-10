"""Захист від двох копій IDE (файл-замок).

``AUTOMATIC_RUNTIME.md`` §7: «Захист від двох копій IDE. Немає файлу-замка:
два запуски можуть підняти два сервери на різних портах».

Навіщо це критично саме тут: кожен запуск піднімає ``llama-server`` і бере
під модель кілька гігабайт VRAM. На RTX 3060 (12 ГБ) друга копія або не
стартує взагалі, або вибиває першу — і користувач бачить «модель зникла»
без причини.

Як працює:

* ``acquire()`` створює ``<app_data_dir>/ide.lock`` і пише туди PID, час і
  робочу теку.
* Якщо файл уже є, перевіряємо, чи живий записаний процес. Мертвий PID —
  це залишок після аварійного закриття, такий замок перебираємо на себе.
* ``release()`` прибирає файл, але **лише якщо він наш** (той самий PID).
  Інакше можна знести замок живої копії.

Свідомо НЕ використовуємо ``msvcrt.locking``/``fcntl.flock``: на Windows
ексклюзивне блокування файлу лишається за процесом навіть після падіння
інтерпретатора, і «вічно зайнятий» замок довелося б прибирати вручну.
Перевірка живого PID простіша й самолікується.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

LOG = logging.getLogger("blackchpok.lockfile")

#: Ім'я файлу замка в ``app_data_dir()``.
LOCK_NAME = "ide.lock"


def lock_path() -> Path:
    """Шлях до файлу замка (у теці даних застосунку, не в робочій теці)."""
    from .config import app_data_dir

    return app_data_dir() / LOCK_NAME


def _pid_alive(pid: int) -> bool:
    """Чи існує процес із таким PID.

    На Windows ``os.kill(pid, 0)`` не працює як перевірка — він справді
    надсилає сигнал. Тому використовуємо ``OpenProcess`` через ctypes,
    а поза Windows — звичайний ``os.kill`` із сигналом 0.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            # Доступу немає — найчастіше це чужий процес, який ЖИВИЙ.
            # Помилку 87 (неприпустимий параметр) трактуємо як «немає такого».
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class LockInfo:
    """Що записано у файлі замка."""

    pid: int = 0
    started: float = 0.0
    workspace: str = ""
    exe: str = ""

    def describe(self) -> str:
        when = ""
        if self.started:
            when = time.strftime("%H:%M:%S", time.localtime(self.started))
        parts = [f"PID {self.pid}"]
        if when:
            parts.append(f"з {when}")
        if self.workspace:
            parts.append(self.workspace)
        return " · ".join(parts)


def read() -> Optional[LockInfo]:
    """Прочитати замок (``None``, якщо файлу немає або він зіпсований)."""
    path = lock_path()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return LockInfo(
            pid=int(data.get("pid") or 0),
            started=float(data.get("started") or 0.0),
            workspace=str(data.get("workspace") or ""),
            exe=str(data.get("exe") or ""),
        )
    except (TypeError, ValueError):
        return None


def is_held_by_other() -> Optional[LockInfo]:
    """Замок тримає ІНШИЙ живий процес? Повертає інформацію про нього."""
    info = read()
    if info is None or info.pid <= 0:
        return None
    if info.pid == os.getpid():
        return None
    return info if _pid_alive(info.pid) else None


class Lock:
    """Контекстний менеджер замка.

    ::

        with Lock() as held:
            if not held:
                ...   # інша копія вже працює
    """

    def __init__(self, workspace: str = "") -> None:
        self.workspace = workspace
        self.info: Optional[LockInfo] = None
        self.other: Optional[LockInfo] = None
        self.error = ""

    # ── дії ──────────────────────────────────────────────────────────────
    def acquire(self) -> bool:
        """Взяти замок. ``False`` — його тримає інша жива копія."""
        path = lock_path()
        other = is_held_by_other()
        if other is not None:
            self.other = other
            self.error = (
                f"IDE уже запущено (PID {other.pid}"
                + (f", тека {other.workspace}" if other.workspace else "")
                + "). Друга копія підняла б другий рушій і забрала VRAM."
            )
            LOG.warning("%s", self.error)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            info = LockInfo(
                pid=os.getpid(),
                started=time.time(),
                workspace=str(self.workspace or ""),
                exe=str(sys.executable or ""),
            )
            path.write_text(
                json.dumps(
                    {"pid": info.pid, "started": info.started,
                     "workspace": info.workspace, "exe": info.exe},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            # Немає доступу до теки даних — це не причина не запускати IDE.
            self.error = f"Замок не створено ({exc}); працюю без захисту."
            LOG.warning("%s", self.error)
            self.info = None
            return True
        self.info = info
        LOG.info("Замок IDE взято: %s", path)
        return True

    def release(self) -> None:
        """Відпустити замок, якщо він наш."""
        path = lock_path()
        info = read()
        if info is None or info.pid != os.getpid():
            return                 # чужий або вже прибраний — не чіпаємо
        try:
            path.unlink()
            LOG.info("Замок IDE відпущено")
        except OSError:
            LOG.debug("Замок не прибрано", exc_info=True)
        self.info = None

    # ── контекстний менеджер ─────────────────────────────────────────────
    def __enter__(self) -> "Lock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.release()


def clear_stale(on_status: Optional[Callable[[str], None]] = None) -> bool:
    """Прибрати замок мертвого процесу. ``True`` — щось прибрали."""
    info = read()
    if info is None:
        return False
    if info.pid > 0 and _pid_alive(info.pid) and info.pid != os.getpid():
        return False
    try:
        lock_path().unlink()
    except OSError:
        return False
    text = f"Прибрано залишок замка від PID {info.pid}"
    LOG.info("%s", text)
    if on_status:
        try:
            on_status(text)
        except Exception:  # noqa: BLE001 - звіт не має ламати запуск
            LOG.debug("on_status впав", exc_info=True)
    return True


__all__ = [
    "LOCK_NAME",
    "Lock",
    "LockInfo",
    "clear_stale",
    "is_held_by_other",
    "lock_path",
    "read",
]
