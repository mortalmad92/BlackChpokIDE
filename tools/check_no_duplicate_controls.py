"""Перевірка: у вікні НЕМАЄ дублів керування (модель, режим).

Питання користувача: «навіщо ці всі пункти дублюються?». Скрипт будує
справжнє вікно й шукає повторювані підписи керування з їхнім походженням.

Запуск: python tools/check_no_duplicate_controls.py
"""

from __future__ import annotations
# ── ІЗОЛЯЦІЯ ДАНИХ ───────────────────────────────────────────────────────
# Інструмент будує СПРАВЖНЄ вікно IDE. Без власного ``BLACKCHPOK_HOME``
# вікно читає ``<app_data>/chats.json`` і відновлює активний чат
# КОРИСТУВАЧА — з ЙОГО текою. Наслідок заміряно: тестовий агент писав
# файли в проєкт користувача, а перевірка дивилась у пісочницю.
# Ставимо ДО звернення до пакета: ``config`` рахує шляхи під час імпорту.
import os as _os
import tempfile as _tempfile

_os.environ.setdefault("BLACKCHPOK_HOME",
                       _tempfile.mkdtemp(prefix="tool-home-"))
_os.environ["BLACKCHPOK_NO_SAVE"] = "1"


import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

#: Підписи, які НЕ мають повторюватись у різних частинах вікна.
WATCHED = ("◈ Агент ▾", "◎ Чат ▾")


def ancestry(widget) -> str:
    names: list[str] = []
    parent = widget
    for _ in range(5):
        parent = parent.master
        if parent is None:
            break
        names.append(type(parent).__name__)
    return " < ".join(names)


def walk(widget, found: list[tuple[str, str]], depth: int = 0) -> None:
    if depth > 12:
        return
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except Exception:  # noqa: BLE001
            text = ""
        # ВАЖЛИВО: рахуємо ЛИШЕ ті віджети, які справді показані.
        # ``winfo_children`` віддає й ті, що існують, але не розміщені
        # (наприклад, ручки для сумісності) — вони не видно користувачу.
        try:
            mapped = bool(child.winfo_ismapped())
        except Exception:  # noqa: BLE001
            mapped = False
        if mapped and (text in WATCHED or text.startswith("⊟ ")):
            found.append((text, ancestry(child)))
        walk(child, found, depth + 1)


def main() -> int:
    import time

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.first_run_done = True
    settings.engine.auto_start = False

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    # ОБОВ'ЯЗКОВО: дати вікну реально домалюватись. Один ``update()``
    # лишає частину віджетів «не показаними», і перевірка хибно каже, що
    # дублів немає (перевірено: скріншот показував дублі, а check — «OK»).
    deadline = time.time() + 2.5
    while time.time() < deadline:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.05)

    found: list[tuple[str, str]] = []
    walk(app, found)
    print("=== Показані підписи керування у вікні ===")
    for text, where in found:
        print(f"  {text[:50]!r:54s} <- {where}")

    failures = 0
    # 1. Режим агента — рівно ОДИН видимий підпис.
    mode_hits = [item for item in found if item[0] == "◈ Агент ▾"]
    if len(mode_hits) == 1:
        print(f"[OK  ] режим агента показано один раз ({mode_hits[0][1]})")
    else:
        print(f"[FAIL] режим агента показано {len(mode_hits)} разів: "
              f"{[w for _t, w in mode_hits]}")
        failures += 1

    # 2. Модель — один підпис у шапці; у композері це ІНШИЙ, менший
    #    підпис (кнопка вибору), і він не дублює шапку повністю.
    model_hits = [item for item in found if item[0].startswith("⊟ ")]
    header_models = [item for item in model_hits if "HeaderBar" in item[1]]
    if len(header_models) <= 1:
        print(f"[OK  ] модель у шапці одна ({len(header_models)})")
    else:
        print(f"[FAIL] модель у шапці {len(header_models)} разів")
        failures += 1

    # 3. Пігулка сесії не має окремого підпису моделі (він у шапці).
    session_models = [item for item in model_hits if "SessionHeader" in item[1]]
    if not session_models:
        print("[OK  ] у рядку сесії немає другого підпису моделі")
    else:
        print(f"[FAIL] рядок сесії дублює модель: {session_models}")
        failures += 1

    app.destroy()
    print()
    print("Дубли керування: " + ("НЕМАЄ" if not failures else f"Є ({failures})"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
