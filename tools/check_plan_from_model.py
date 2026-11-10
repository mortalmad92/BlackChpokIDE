"""Доказ, що зміст плану визначає МОДЕЛЬ, а не код.

Беремо три різні завдання й показуємо: плани РІЗНІ й відображають тему
запиту. Якщо плани однакові — значить, працює шаблон, а не модель.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import task_planner as tp  # noqa: E402

CASES = [
    ("вебсайт", "Створи повноцінний вебсайт із реєстрацією, авторизацією, "
                "особистим кабінетом і базою даних.",
     ("реєстрац", "авториз", "кабінет", "баз")),
    ("гра", "Зроби консольну гру «Змійка» на Python із рухом, їжею та "
            "підрахунком очок.",
     ("змійк", "рух", "їж", "очк")),
    ("скрипт", "Створи скрипт бекапу папки у ZIP-архів із розписом у "
               "лог-файл щоразу.",
     ("бекап", "zip", "архів", "лог")),
]


def main() -> int:
    from blackchpok_ide.config import Settings

    llm = Settings.load().llm
    if not llm.model:
        print("Модель не вибрана — перевіряти нема чого.")
        return 1

    failures = 0
    signatures = []
    for name, goal, keywords in CASES:
        print(f"\n=== {name.upper()} ===")
        print(f"запит: {goal[:70]}…")
        result = tp.plan_with_model(goal, llm,
                                    context="Мова/стек: Python. Тека: нова.",
                                    tool_names=["write_file", "run_command"])
        if not result.ok:
            print(f"[FAIL] план не склався: {result.error}")
            failures += 1
            continue
        titles = [step.title for step in result.steps]
        signatures.append(tuple(titles))
        print(f"кроків: {len(titles)}")
        for index, title in enumerate(titles, start=1):
            print(f"  {index:02d}. {title}")

        blob = " ".join(
            (step.title + " " + step.detail).lower() for step in result.steps)
        hits = [word for word in keywords if word in blob]
        ok = len(hits) >= 2
        print(f"[{'OK  ' if ok else 'FAIL'}] план відображає тему запиту "
              f"({len(hits)}/{len(keywords)}: {', '.join(hits) or '—'})")
        if not ok:
            failures += 1
        if not all(step.number if hasattr(step, "number") else True
                   for step in result.steps):
            pass

    print()
    # Головний доказ: плани РІЗНІ
    if len(signatures) >= 2:
        unique = len(set(signatures))
        ok = unique == len(signatures)
        print(f"[{'OK  ' if ok else 'FAIL'}] плани різних завдань відрізняються "
              f"({unique} різних із {len(signatures)})")
        if not ok:
            failures += 1
            print("   Це означає, що працює ШАБЛОН, а не модель!")

    print()
    print("Модель керує планом:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
