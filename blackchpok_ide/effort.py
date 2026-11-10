"""Рівні зусилля для reasoning-моделей і список моделей для вибору в чаті.

Сучасні хмарні агенти (DeepSeek, OpenAI o-серія) мають параметр «наскільки
сильно думати». Модуль зводить його до трьох зрозумілих рівнів і вміє
перетворити на поля конкретного API.

Модуль не тягне tkinter і не робить мережевих запитів.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EffortLevel:
    """Один рівень зусилля."""

    key: str
    label: str
    hint: str
    budget_tokens: int = 0     # для Anthropic thinking / reasoning budget
    reasoning_effort: str = "" # для OpenAI o-серії: low | medium | high
    temperature: float | None = None
    order: int = 100

    @property
    def is_default(self) -> bool:
        return self.key == DEFAULT_EFFORT


DEFAULT_EFFORT = "default"

EFFORTS: tuple[EffortLevel, ...] = (
    EffortLevel(DEFAULT_EFFORT, "За замовчуванням", "Як вирішує сама модель",
                order=10),
    EffortLevel("low", "Швидко", "Мінімум міркувань, найшвидша відповідь",
                budget_tokens=1024, reasoning_effort="low", temperature=0.3, order=20),
    EffortLevel("medium", "Збалансовано", "Помірні міркування",
                budget_tokens=4096, reasoning_effort="medium", temperature=0.4, order=30),
    EffortLevel("high", "Ретельно", "Максимум міркувань, повільніше",
                budget_tokens=16384, reasoning_effort="high", temperature=0.6, order=40),
    EffortLevel("max", "Максимум", "Найглибші міркування (Deploy, GLM)",
                budget_tokens=32768, reasoning_effort="max", temperature=0.7, order=50),
    EffortLevel("none", "Без міркувань", "Вимкнути thinking — як звичайний чат",
                reasoning_effort="none", temperature=0.3, order=60),
)

_BY_KEY: dict[str, EffortLevel] = {level.key: level for level in EFFORTS}


def get(key: str) -> EffortLevel:
    """Рівень за ключем (типовий, якщо невідомий)."""
    return _BY_KEY.get((key or "").strip().lower(), _BY_KEY[DEFAULT_EFFORT])


def labels() -> list[str]:
    """Підписи для меню (у порядку показу)."""
    return [level.label for level in sorted(EFFORTS, key=lambda level: level.order)]


def label_for(key: str) -> str:
    return get(key).label


def key_for_label(label: str) -> str:
    """Зворотний пошук: підпис → ключ."""
    clean = (label or "").strip()
    for level in EFFORTS:
        if level.label == clean:
            return level.key
    return DEFAULT_EFFORT


def normalise(key: str) -> str:
    return get(key).key


def payload_for(key: str, *, provider: str = "", model: str = "") -> dict[str, Any]:
    """Поля запиту для конкретного API.

    Різні провайдери називають це по-різному, тому повертаємо словник, який
    клієнт вставляє у payload:
    * ``reasoning_effort`` — OpenAI o-серія;
    * ``thinking_budget`` — Anthropic/Gemini-подібні;
    * ``temperature`` — підказка для звичайних моделей.
    """
    level = get(key)
    payload: dict[str, Any] = {}
    if level.is_default:
        return payload
    if level.reasoning_effort:
        payload["reasoning_effort"] = level.reasoning_effort
    if level.budget_tokens:
        payload["thinking_budget"] = level.budget_tokens
    if level.temperature is not None:
        payload["temperature"] = level.temperature
    return payload


def describe(key: str) -> str:
    level = get(key)
    return f"{level.label} — {level.hint}"


def is_reasoning_provider(provider: str) -> bool:
    """Чи має провайдер сенс від «зусилля»."""
    return (provider or "").lower() in {"deepseek", "openai", "anthropic", "gemini",
                                        "openrouter", "custom"}


def menu_rows(current_model: str, current_effort: str,
              models: list[str] | None = None) -> list[tuple[str, str, str]]:
    """Рядки для меню: [(підпис, значення, позначка)].

    Використовується вікном, щоб показати «Модель … ›» і «Зусилля … ›»
    так само, як у сучасних агентних редакторах.
    """
    effort = get(current_effort)
    return [
        ("Модель", current_model or "не вибрана", "›"),
        ("Зусилля", effort.label, "›"),
    ]


__all__ = [
    "DEFAULT_EFFORT",
    "EFFORTS",
    "EffortLevel",
    "describe",
    "get",
    "is_reasoning_provider",
    "key_for_label",
    "label_for",
    "labels",
    "menu_rows",
    "normalise",
    "payload_for",
]
