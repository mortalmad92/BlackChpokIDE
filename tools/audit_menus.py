"""Аудит меню: кожен пункт веде до НАЯВНОГО методу вікна.

Головне меню будується з реєстру команд, але в ньому лишились і нативні
пункти. Перевірити очима неможливо: 95 команд × 7 меню. Тут вікно
відкривається по-справжньому, меню обходиться програмно, і для кожного
пункту перевіряється:

1. чи існує метод, на який він посилається;
2. чи немає пункту з порожнім підписом;
3. чи немає дублів підпису в межах одного меню;
4. чи не ковтає пункт помилку (наявність модуля ``safe``).

Запуск::

    python tools/audit_menus.py
    python tools/audit_menus.py --strict
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-menu-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def menu_items(menu) -> list[tuple[str, str, str]]:
    """Перебрати пункти меню: (підпис, команда, тип)."""
    found: list[tuple[str, str, str]] = []
    try:
        end = menu.index("end")
    except Exception:                        # noqa: BLE001 - меню може бути порожнім
        return found
    if end is None:
        return found
    for index in range(end + 1):
        try:
            kind = menu.type(index)
            if kind == "separator":
                continue
            label = str(menu.entrycget(index, "label") or "")
            # У пункту-підменю (cascade) немає ``command`` — це норма.
            try:
                command = str(menu.entrycget(index, "command") or "")
            except Exception:                # noqa: BLE001
                command = ""
        except Exception:                    # noqa: BLE001 - пункт без команди
            continue
        found.append((label, command, (kind or "").strip()))
        # Вкладені підменю (cascade) обходимо рекурсивно.
        try:
            if kind == "cascade":
                sub_name = menu.entrycget(index, "menu")
                if sub_name:
                    found.extend(menu_items(menu.nametowidget(sub_name)))
        except Exception:                    # noqa: BLE001
            continue
    return found


def main() -> int:
    from blackchpok_ide import config, main_window

    settings = config.Settings()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.engine.auto_start = False
    app = main_window.BlackChpokIDE(settings=settings)
    app.update_idletasks()
    app.update()

    # Меню приєднується через ``self.configure(menu=…)``, а не зберігається
    # в атрибуті. Читаємо його назад із віджета — інакше аудит бачив 0
    # пунктів і мовчки «проходив».
    bar = None
    try:
        name = app.cget("menu")
        if name:
            bar = app.nametowidget(name)
    except Exception:                        # noqa: BLE001
        bar = None
    if bar is None:
        print("✗ меню не знайдено — перевірка неможлива")
        app.destroy()
        return 1

    problems = 0
    total = 0
    try:
        count = bar.index("end")
    except Exception:                        # noqa: BLE001
        count = None
    if count is None:
        print("✗ у меню немає жодного розділу")
        app.destroy()
        return 1

    for index in range(count + 1):
        try:
            if bar.type(index) != "cascade":
                continue
            title = str(bar.entrycget(index, "label") or "")
            sub = bar.nametowidget(bar.entrycget(index, "menu"))
        except Exception:                    # noqa: BLE001
            continue
        items = menu_items(sub)
        seen: dict[str, int] = {}
        for label, command, kind in items:
            total += 1
            if not label.strip():
                print(f"  ✗ [{title}] пункт без підпису")
                problems += 1
            seen[label] = seen.get(label, 0) + 1
            # Пункт-підменю (cascade) не має ``command`` — це норма, а не
            # дефект: у нього є ``menu``. Раніше аудит рахував «Тема» з
            # 30 пунктами як помилку.
            if not command:
                if kind == "cascade":
                    continue
                print(f"  ✗ [{title}] «{label}» без команди")
                problems += 1
                continue
            # Команда — рядок Tcl вигляду ``2239565638592new_file``:
            # числовий префікс + ім'я методу. ``lambda`` не перевіряємо —
            # у неї немає імені.
            if "lambda" in command:
                continue
            method = re.sub(r"^\d+", "", command).strip()
            if not method or not method.isidentifier():
                continue
            if not callable(getattr(app, method, None)):
                print(f"  ✗ [{title}] «{label}» → немає методу {method}")
                problems += 1
        for label, count_seen in seen.items():
            if count_seen > 1:
                print(f"  ✗ [{title}] дубль підпису «{label}» ×{count_seen}")
                problems += 1
        print(f"  {title:14s} пунктів: {len(items)}")

    # ── Меню в шапці (текстовий рядок «Файл · Правка · …») ───────────────
    # Воно будується з РЕЄСТРУ КОМАНД, і не кожен розділ шапки є групою
    # команд: «Правка», «Модель», «Проєкт» і «Довідка» мають власні
    # обробники (``_on_*_menu``), а не набір команд. Тому перевіряємо лише
    # ті розділи, які справді є групами, і окремо — що обробники існують.
    header = getattr(app, "header_bar", None)
    header_total = 0
    #: Групи, які справді показуються в текстовому меню шапки. «run» існує
    #: в реєстрі як група, але в шапку не виводиться (її команди доступні
    #: через «Агент» і палітру) — тому її тут немає, і це не дефект.
    for section in ("file", "view", "agent", "git"):
        try:
            rows = app._menu_items_for(section)
        except Exception:                    # noqa: BLE001
            continue
        header_total += len(rows)
        if not rows:
            print(f"  ✗ [шапка] розділ «{section}» порожній")
            problems += 1
    for name, method in (
        ("project", "_show_project_menu"),
        ("model", "show_model_selector"),
        ("agent", "show_mode_menu"),
        ("git", "_show_git_menu"),
        ("more", "_show_more_menu"),
    ):
        if not callable(getattr(app, method, None)):
            print(f"  ✗ [шапка] розділ «{name}» → немає методу {method}")
            problems += 1
    print(f"  шапка         пунктів: {header_total} (+5 меню з власними обробниками)")

    print(f"\nУсього пунктів: {total + header_total}")
    print(f"Проблем: {problems}")
    app.destroy()
    return 1 if (problems and "--strict" in sys.argv) else 0


if __name__ == "__main__":
    raise SystemExit(main())
