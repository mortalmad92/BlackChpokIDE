"""Перевірити, що кожне ім'я з ``__all__`` справді існує в модулі.

``__all__`` — це обіцянка назовні (``from module import *``, документація,
реекспорт у ``__init__``). Якщо імені немає, імпорт падає з ``ImportError``
у користувача, а не в розробника: модуль імпортується нормально, доки ніхто
не звернеться до цього імені.

Запуск: ``python tools/audit_exports.py`` — код виходу 1, якщо є розбіжності.
"""

from __future__ import annotations

import importlib
import pathlib
import pkgutil
import sys

# ── Корінь проєкту в ``sys.path`` ─────────────────────────────────────────
# Без цього скрипт працює ЛИШЕ коли його запускають з кореня проєкту:
# ``ModuleNotFoundError: No module named 'blackchpok_ide'``. Перевірено —
# саме так він і падав. Інші інструменти теки це вже роблять; тут рядок
# був пропущений.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import blackchpok_ide as package  # noqa: E402

ROOT_MODULES = ("main", "agent_tools", "rag_engine", "vibe_router", "night_shift")


def main() -> int:
    problems = 0
    checked = 0
    names = [info.name for info in pkgutil.walk_packages(
        package.__path__, package.__name__ + ".")]
    names += [name for name in ROOT_MODULES if _importable(name)]
    for name in names:
        try:
            module = importlib.import_module(name)
        except Exception:                                    # noqa: BLE001
            print(f"НЕ ІМПОРТУЄТЬСЯ: {name}")
            problems += 1
            continue
        exported = getattr(module, "__all__", None)
        if not exported:
            continue
        checked += 1
        for item in exported:
            if not hasattr(module, item):
                print(f"{name}: __all__ обіцяє «{item}», а такого імені немає")
                problems += 1
    print(f"Модулів із __all__: {checked}, розбіжностей: {problems}")
    return 1 if problems else 0


def _importable(name: str) -> bool:
    return (ROOT / f"{name}.py").is_file()


if __name__ == "__main__":
    raise SystemExit(main())
