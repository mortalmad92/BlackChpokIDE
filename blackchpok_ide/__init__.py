"""BlackChpok IDE — локальна IDE з агентом у стилі сучасної IDE.

Публічний API пакета: налаштування, запуск вікна, версія.
"""

from __future__ import annotations

import sys

from .config import APP_NAME, APP_VERSION, Settings, setup_logging

__all__ = ["APP_NAME", "APP_VERSION", "Settings", "setup_logging", "run"]


def run(workspace: str = "") -> int:
    """Запустити IDE. Використовується з main.py і з .exe.

    Другий запуск не піднімає другий рушій: файл-замок
    (:mod:`blackchpok_ide.lockfile`) не дає двом копіям ділити VRAM.
    """
    from .main_window import launch

    setup_logging()

    from . import lockfile

    lock = lockfile.Lock(workspace)
    if not lock.acquire():
        other = lock.other
        detail = other.describe() if other is not None else "інший процес"
        print(
            f"{APP_NAME}: уже запущено ({detail}). "
            "Закрий попереднє вікно — друга копія забрала б VRAM у першої.",
            file=sys.stderr,
        )
        return 2
    try:
        settings = Settings.load()
        if workspace:
            settings.remember_workspace(workspace)
        return launch(settings)
    finally:
        lock.release()
