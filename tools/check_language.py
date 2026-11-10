"""Перевірка розуміння простих людських фраз (офлайн, без моделі).

Кожна фраза — так, як каже замовник: без назв інструментів, без шляхів,
часто з помилками й у різних відмінках. Перевіряємо, що шар розуміння
визначає правильний намір.

Запуск:  .venv\\Scripts\\python.exe tools\\check_language.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import task_plan, tool_router  # noqa: E402

#: (фраза, очікуваний намір, коментар)
CASES: list[tuple[str, str, str]] = [
    # ── створення
    ("зроби мені калькулятор", task_plan.CREATE, "без слова «файл»"),
    ("напиши програму яка рахує площу кола", task_plan.CREATE, "«програму»"),
    ("треба щоб був сайт з меню", task_plan.CREATE, "побажання, не наказ"),
    ("зроби так, щоб програма віталась", task_plan.CREATE, "«зроби так щоб»"),
    ("створи простий бот для телеграма", task_plan.CREATE, "«простий бот»"),
    ("мені потрібен скрипт для бекапу", task_plan.CREATE, "«мені потрібен»"),
    ("хочу гру змійку", task_plan.CREATE, "«хочу»"),
    ("додай кнопку збереження", task_plan.CREATE, "«додай»"),
    # ── правка
    ("поміняй колір фону на темний", task_plan.EDIT, "«поміняй»"),
    ("перероби меню під мобільні", task_plan.EDIT, "«перероби»"),
    ("зроби шрифт більшим", task_plan.EDIT, "порівняльний ступінь"),
    ("прибери зайвий рядок", task_plan.EDIT, "«прибери»"),
    # ── помилки
    ("воно не працює, допоможи", task_plan.DEBUG, "«не працює»"),
    ("програма падає при запуску", task_plan.DEBUG, "«падає»"),
    ("вилітає помилка коли натискаю", task_plan.DEBUG, "«вилітає помилка»"),
    ("чомусь нічого не відображається", task_plan.DEBUG, "скарга без слова «помилка»"),
    ("зламалось після моїх змін", task_plan.DEBUG, "«зламалось»"),
    # ── запуск і перевірка
    ("запусти", task_plan.RUN, "одне слово"),
    # «покажи як виглядає» — це про вигляд і показ, тож UI/READ доречні:
    # людина хоче побачити результат, а не прочитати файл мовчки.
    ("а ну покажи як воно виглядає", task_plan.UI, "розмовна форма"),
    ("перевір чи все добре", task_plan.TEST, "«перевір»"),
    ("прожени тести", task_plan.TEST, "«прожени»"),
    # ── читання й пошук
    ("що в цьому файлі", task_plan.READ, "«що в файлі»"),
    ("поясни що робить ця функція", task_plan.READ, "«поясни»"),
    ("де використовується ця змінна", task_plan.SEARCH, "«де використовується»"),
    ("знайди всі місця де згадується пароль", task_plan.SEARCH, "«знайди»"),
    # ── складніше
    ("зроби сайт з реєстрацією і базою даних", task_plan.CREATE, "кілька робіт"),
    ("гра падає, виправ і запусти знову", task_plan.DEBUG, "кілька намірів"),
    ("онови документацію", task_plan.EDIT, "«онови»"),
    ("збери exe файл", task_plan.DEPLOY, "«збери»"),
]

#: Фрази, які НЕ є дорученням — на них не можна запускати інструменти.
TALK_CASES: list[tuple[str, str]] = [
    ("привіт, як справи", "вітання"),
    ("як зробити чай", "питання про світ"),
    ("що таке рекурсія", "питання про теорію"),
    ("дякую", "подяка"),
    ("як справи у тебе", "розмова"),
    ("скажи щось цікаве", "розмова без дії"),
]


def main() -> int:
    failures = 0
    print("=" * 78)
    print("НАМІРИ: чи правильно зрозуміло, ЩО людина просить")
    print("=" * 78)
    for phrase, expected, comment in CASES:
        info = task_plan.understand(phrase)
        ok = expected in info.intents
        status = "OK  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{status}] «{phrase}»")
        print(f"        очікували {expected:<9} отримали "
              f"{','.join(info.intents):<22} ({comment})")

    print()
    print("=" * 78)
    print("НЕ-ДОРУЧЕННЯ: на ці фрази агент НЕ має запускати інструменти")
    print("=" * 78)
    for phrase, comment in TALK_CASES:
        info = task_plan.understand(phrase)
        ok = not info.is_action
        status = "OK  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{status}] «{phrase}» → {info.primary:<8} ({comment})")

    print()
    print("=" * 78)
    print("ІНСТРУМЕНТИ: чи отримує агент доречний набір")
    print("=" * 78)
    tool_cases = [
        ("зроби калькулятор", ("write_file",)),
        ("запусти", ("run_command",)),
        ("що в цьому файлі", ("read_file",)),
        ("де використовується пароль", ("search_text",)),
    ]
    for phrase, needed in tool_cases:
        tools = task_plan.tools_for_stage(phrase)
        ok = all(item in tools for item in needed)
        status = "OK  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{status}] «{phrase}» → {', '.join(tools) or '—'}")

    print()
    print("=" * 78)
    print("РОУТЕР: чи розпізнає наказ упевнено")
    print("=" * 78)
    route_cases = [
        "покажи файли",
        "запусти тести",
        "що в цьому файлі",
        "створи файл app.py",
        "запусти команду python --version",
    ]
    for phrase in route_cases:
        hints = tool_router.confident(phrase)
        ok = bool(hints)
        status = "OK  " if ok else "FAIL"
        if not ok:
            failures += 1
        names = ", ".join(hint.tool for hint in hints) or "—"
        print(f"[{status}] «{phrase}» → {names}")

    print()
    print("=" * 78)
    total = len(CASES) + len(TALK_CASES) + len(tool_cases) + len(route_cases)
    print(f"Усього перевірок: {total} · провалено: {failures}")
    print("Розуміння мови:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
