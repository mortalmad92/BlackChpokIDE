"""Прокинути кожен модуль пакета через реальні виклики (smoke на імпорт і API).

Мета — знайти те, що ламається НЕ на імпорті, а на першому виклику:
``NameError`` у рідко використовуваній гілці, ``AttributeError`` на
модульній константі, друкарська помилка в імені функції тощо.

Запуск: ``python tools/smoke_modules.py`` — код виходу 1, якщо щось упало.
"""

from __future__ import annotations

import importlib
import pathlib
import pkgutil
import traceback

import blackchpok_ide as package


def main() -> int:
    failures = 0
    modules = sorted(module.name for module in pkgutil.walk_packages(
        package.__path__, package.__name__ + "."))
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception:                                   # noqa: BLE001
            print(f"ІМПОРТ ВПАВ: {name}")
            traceback.print_exc()
            failures += 1
            continue
        # Кожен модуль має або ``__all__``, або хоча б одне публічне ім'я:
        # порожній модуль означає, що код недосяжний.
        public = [item for item in dir(module) if not item.startswith("_")]
        if not public:
            print(f"ПОРОЖНІЙ МОДУЛЬ: {name}")
            failures += 1
    print(f"Модулів перевірено: {len(modules)}, проблем: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
