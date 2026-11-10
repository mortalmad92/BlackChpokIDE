"""Готові профілі робочого простору.

Профіль — це набір чисел для панелей (ширини, висоти) плюс те, які панелі
видимі. Користувач обирає профіль, тягне межі далі як хоче — програма
запам'ятовує його власне компонування окремо від профілю.

Навіщо профілі, якщо є перетягування: під час переходу між роботами
(«пишу код» → «питаю агента» → «дивлюсь сайт») тягнути чотири межі щоразу
дорого. Профіль ставить одразу весь робочий простір.

Модуль не тягне tkinter: лише числа й застосування до об'єктів, які їх
приймають. Це дозволяє тестувати профілі без дисплея.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LayoutProfile:
    """Один набір розмірів і видимості панелей."""

    key: str
    label: str
    tip: str
    sidebar_width: int = 300
    chat_width: int = 520
    context_width: int = 212
    preview_width: int = 520
    bottom_height: int = 200
    chat_visible: bool = True
    context_visible: bool = True
    preview_visible: bool = False
    bottom_visible: bool = False
    #: Частка ширини, яку займає колонка діалогу в горизонтальному поділі.
    chat_share: float = 0.5

    def as_settings(self) -> dict[str, Any]:
        """Значення, які треба записати в ``settings.ui``."""
        return {
            "sidebar_width": self.sidebar_width,
            "chat_width": self.chat_width,
            "context_width": self.context_width,
            "bottom_height": self.bottom_height,
            "chat_visible": self.chat_visible,
            "context_visible": self.context_visible,
            "bottom_visible": self.bottom_visible,
        }


AI_AGENT = LayoutProfile(
    key="ai-agent",
    label="AI Agent",
    tip="Широкий діалог з агентом, контекст проєкту праворуч, термінал знизу",
    sidebar_width=300,
    chat_width=640,
    context_width=236,
    bottom_height=220,
    chat_visible=True,
    context_visible=True,
    preview_visible=False,
    bottom_visible=True,
    chat_share=0.56,
)

CODE_EDITOR = LayoutProfile(
    key="code",
    label="Code Editor",
    tip="Редактор на весь екран, діалог вузькою колонкою",
    sidebar_width=260,
    chat_width=420,
    context_width=212,
    bottom_height=180,
    chat_visible=True,
    context_visible=False,
    preview_visible=False,
    bottom_visible=False,
    chat_share=0.34,
)

WEB_DEV = LayoutProfile(
    key="web",
    label="Web Development",
    tip="Код ліворуч, сайт у Live Browser праворуч, термінал знизу",
    sidebar_width=250,
    chat_width=400,
    context_width=200,
    preview_width=620,
    bottom_height=200,
    chat_visible=True,
    context_visible=False,
    preview_visible=True,
    bottom_visible=True,
    chat_share=0.32,
)

DEBUGGING = LayoutProfile(
    key="debug",
    label="Debugging",
    tip="Термінал і журнал широко, контекст проєкту праворуч",
    sidebar_width=280,
    chat_width=460,
    context_width=240,
    bottom_height=340,
    chat_visible=True,
    context_visible=True,
    preview_visible=False,
    bottom_visible=True,
    chat_share=0.42,
)

MINIMAL = LayoutProfile(
    key="minimal",
    label="Minimal Workspace",
    tip="Тільки діалог: жодних бічних панелей",
    sidebar_width=0,
    chat_width=900,
    context_width=0,
    bottom_height=0,
    chat_visible=True,
    context_visible=False,
    preview_visible=False,
    bottom_visible=False,
    chat_share=1.0,
)

PROFILES: tuple[LayoutProfile, ...] = (
    AI_AGENT,
    CODE_EDITOR,
    WEB_DEV,
    DEBUGGING,
    MINIMAL,
)

_BY_KEY = {profile.key: profile for profile in PROFILES}


def get(key: str) -> LayoutProfile | None:
    """Профіль за ключем (або ``None``)."""
    return _BY_KEY.get((key or "").strip().lower())


def for_window(width: int, height: int) -> LayoutProfile:
    """Доречний профіль для розміру вікна.

    Невеликий ноутбук (1366×768) не має місця на три колонки: там краще
    «Code Editor». Широкий монітор (3440+) дозволяє «Web Development».
    """
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return AI_AGENT
    if width >= 2400 and height >= 1200:
        return WEB_DEV
    # Поріг беремо з урахуванням того, що вікно IDE вміщає три колонки
    # починаючи приблизно з 1440 px. Менше — дві колонки («Code Editor»).
    if width < 1440 or height < 760:
        return CODE_EDITOR
    return AI_AGENT


def labels() -> list[tuple[str, str]]:
    """(ключ, підпис) для меню. Порядок — як у :data:`PROFILES`."""
    return [(profile.key, profile.label) for profile in PROFILES]


__all__ = [
    "AI_AGENT",
    "CODE_EDITOR",
    "DEBUGGING",
    "LayoutProfile",
    "MINIMAL",
    "PROFILES",
    "WEB_DEV",
    "for_window",
    "get",
    "labels",
]
