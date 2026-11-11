"""Широкий прогін реальних фраз: чи роутер дає ДІЮ на кожну.

Мета — знайти фрази, де користувач явно просить щось зробити, а роутер
мовчить (агент відповість словами замість роботи).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import intent_engine, tool_router  # noqa: E402

PHRASES = [
    # створення
    "створи файл main.py", "створи папку src", "створи новий проєкт",
    "створи сайт-візитку", "створи телеграм бота", "створи гру змійку",
    "зроби калькулятор", "зроби todo список", "напиши функцію сортування",
    "згенеруй README", "створи тести для calc.py",
    # правка
    "виправ помилку в main.py", "додай коментарі", "видали зайвий код",
    "перейменуй функцію greet", "заміни print на logging", "відформатуй файл",
    "додай обробку помилок", "оптимізуй цю функцію", "перепиши цей цикл",
    # читання
    "покажи файл main.py", "прочитай config.py", "що в цьому файлі",
    "покажи структуру проєкту", "де оголошена функція main",
    "знайди всі TODO", "покажи список файлів", "скільки рядків у файлі",
    # запуск
    "запусти програму", "зупини програму", "запусти тести", "перезапусти програму",
    "запусти сервер", "зупини сервер", "виконай pytest", "запусти python main.py",
    # git
    "зроби коміт", "покажи зміни", "зроби push", "відкоти останню зміну",
    "створи гілку feature", "покажи історію",
    # пояснення
    "поясни цей код", "що робить функція greеt", "навіщо цей import",
    "поясни помилку", "чому не працює",
    # розмова
    "привіт", "дякую", "як справи", "що ти вмієш", "хто ти",
    # інше
    "встанови requests", "онови залежності", "перевір синтаксис",
    "покажи логи", "відкрий браузер", "зроби скріншот",
]


def main() -> int:
    silent: list[str] = []
    converse_but_action: list[str] = []
    for phrase in PHRASES:
        route = tool_router.route(phrase)
        frame = intent_engine.frame(phrase)
        tools = [getattr(h, "tool", str(h)) for h in route]
        actionable = bool(frame.actionable)
        if actionable and not tools:
            silent.append(f"{phrase}  [intent={frame.intent_type}]")
        if tools and not actionable:
            converse_but_action.append(f"{phrase} -> {tools[:2]}")
        mark = "ДІЯ " if tools else ("--- " if not actionable else "ТИШ")
        print(f"{mark} {phrase[:36]:38} {tools[:3]}")

    print(f"\nпросить дію, але роутер мовчить: {len(silent)}")
    for item in silent:
        print("  " + item)
    print(f"\nроутер дає дію, а intent каже 'розмова': {len(converse_but_action)}")
    for item in converse_but_action:
        print("  " + item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
