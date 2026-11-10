"""BlackChpok IDE — локальна IDE з агентом у стилі сучасної IDE.

Публічний API пакета: налаштування, запуск вікна, версія.
"""

from __future__ import annotations

from .config import APP_NAME, APP_VERSION, Settings, setup_logging

__all__ = ["APP_NAME", "APP_VERSION", "Settings", "setup_logging", "run"]


def run(workspace: str = "") -> int:
    """Запустити IDE. Використовується з main.py і з .exe."""
    from .main_window import launch

    setup_logging()
    settings = Settings.load()
    if workspace:
        settings.remember_workspace(workspace)
    return launch(settings)
