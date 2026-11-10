"""Розбиття великого промту на чергу задач силами локальної моделі.

Ідея: користувач пише одне велике завдання («зроби онлайн-журнал з форумом,
аналітикою й мобільною версією»). Модель сама розкладає його на послідовні
дрібні кроки, кожен з яких вона здатна виконати за один підхід, і ці кроки
йдуть у чергу IDE — по одному, з автозапуском.

Це дає те, чого бракувало: велике завдання не впирається в ліміт кроків і
не губиться в контексті, бо кожен етап — окремий запит зі своїм фокусом.

Модуль не тягне tkinter: його можна перевіряти тестами.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional

LOG = logging.getLogger("blackchpok.planner")

#: Скільки кроків вважати нормою (більше — модель занадто дробить).
DEFAULT_MAX_STEPS = 12
#: Скільки символів вважати «великим» завданням.
#: Калібровано на реальному брифі: справжнє ТЗ сайту — 2726 символів,
#: 23 рядки, 16 речень. Поріг 180 не пропускає короткі доручення
#: («запусти тести» — 13 символів) і ловить справжні багатовимірні задачі.
BIG_TASK_CHARS = 180

PLAN_PROMPT = (
    "Розклади це завдання на послідовні кроки для себе ж. "
    "Кожен крок має бути такий, який можна виконати за один підхід: "
    "створити кілька файлів, запустити перевірку, виправити помилку. "
    "Кроки мають бути конкретні й у правильному порядку — так, щоб кожен "
    "наступний спирався на результат попереднього.\n\n"
    "Поверни ЛИШЕ JSON-масив рядків, без пояснень і без markdown:\n"
    '["перший крок", "другий крок", "..."]\n\n'
    "У кроках пиши, ЩО зробити, а не як. Не додавай кроків про план чи "
    "уточнення — тільки реальні дії з файлами й перевірками.\n\n"
    "Завдання:\n"
)


def is_big_task(text: str) -> bool:
    """Чи це велике завдання, яке варто розбити на кроки."""
    clean = (text or "").strip()
    if len(clean) < BIG_TASK_CHARS:
        return False
    # Ознаки справжнього великого завдання: кілька вимог або абзаців.
    signals = (
        clean.count("\n") >= 3,
        clean.count(". ") >= 4,
        bool(re.search(r"\b(потрібн\w*|хочу|зроби|створи|додай)\b", clean, re.I)),
    )
    return sum(bool(item) for item in signals) >= 2


def parse_steps(raw: str, *, limit: int = DEFAULT_MAX_STEPS) -> list[str]:
    """Витягти список кроків із відповіді моделі.

    Терпимо до будь-якого формату: JSON-масив, список з маркерами, нумерація
    або просто рядки. Модель не завжди слухається інструкції «лише JSON».
    """
    text = (raw or "").strip()
    if not text:
        return []

    # 1. JSON-масив десь у тексті.
    for match in re.finditer(r"\[(?:.|\n)*?\]", text):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            steps = [_clean_step(item) for item in data if isinstance(item, str)]
            steps = [step for step in steps if step]
            if steps:
                return steps[:limit]

    # 2. Нумерований список або маркери.
    steps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\d+[.)]\s+", stripped):
            steps.append(_clean_step(re.sub(r"^\d+[.)]\s+", "", stripped)))
        elif stripped.startswith(("- ", "* ", "• ")):
            steps.append(_clean_step(stripped[2:]))
        elif stripped.startswith("[") or stripped.startswith("]"):
            continue
    steps = [step for step in steps if step]
    if steps:
        return steps[:limit]

    # 3. Останній шанс: рядки, що схожі на дію.
    for line in text.splitlines():
        stripped = _clean_step(line)
        if len(stripped) > 15 and not stripped.startswith("```"):
            steps.append(stripped)
    return steps[:limit]


def _clean_step(value: str) -> str:
    text = (value or "").strip()
    text = text.strip("\"'")
    text = re.sub(r"^[*\-•]\s*", "", text)
    text = re.sub(r"^\d+[.)]\s*", "", text)
    text = text.replace("```json", "").replace("```", "").strip()
    # Хвіст-коментар у дужках моделі часто зайвий.
    return text.rstrip(",").strip()


def wants_split(text: str) -> bool:
    """Чи користувач явно просить розбити завдання."""
    low = (text or "").lower()
    markers = ("/розбий", "/split", "розбий на задачі", "розбий на кроки",
               "по частинах", "частинами")
    return any(marker in low for marker in markers)


def build_follow_up(step: str, index: int, total: int, *, brief: str = "") -> str:
    """Текст задачі черги для одного кроку.

    Крок показуємо САМИМ ТЕКСТОМ, без префікса «Крок 1 з 12». Раніше
    префікс був у тексті задачі, і черга в бічній панелі виглядала як
    дванадцять однакових рядків «Крок 1 з 12: …», «Крок 2 з 12: …» —
    користувач не бачив, ЩО саме робитиметься. Номер і місце в плані й
    так відомі з порядку рядків і з підпису «1/12» біля кожного.

    Контекст загальної мети лишаємо: без нього агент на пізніх кроках
    забуває, для чого все робиться.
    """
    body = (step or "").strip()
    if brief:
        return f"{body}\n\nЗагальна мета (для контексту): {brief.strip()}"
    return body


def steps_from_answer(raw: str, *, limit: int = DEFAULT_MAX_STEPS) -> list[str]:
    """Публічна обгортка для розбору відповіді моделі."""
    return parse_steps(raw, limit=limit)


__all__ = [
    "BIG_TASK_CHARS",
    "DEFAULT_MAX_STEPS",
    "PLAN_PROMPT",
    "build_follow_up",
    "is_big_task",
    "parse_steps",
    "steps_from_answer",
    "wants_split",
]
