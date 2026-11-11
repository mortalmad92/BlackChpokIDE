"""Збережувана розкладка панелей: позиції сашів і видимість.

Користувач може рухати межі панелей і ховати їх — програма запам'ятовує це
між запусками. Модуль не тягне tkinter: він лише зберігає й віддає числа,
а вікно застосовує їх до ``PanedWindow``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .config import app_data_dir

LOG = logging.getLogger("blackchpok.layout")

#: Ключі панелей, які запам'ятовуємо.
KEYS: tuple[str, ...] = (
    "sidebar",       # ширина лівої колонки (список чатів)
    "sidebar_width",  # ширина лівої панелі після перетягування мишею
    "main_v",        # висота редактора над нижньою панеллю
    "main_h",        # ширина центральної колонки
    "chat_split",    # ширина розмови всередині правої колонки
    "chat_row",      # висота розмови над полем вводу
    "context_width",  # ширина колонки контексту
    "preview_width",  # ширина колонки живого прев'ю (вбудований браузер)
    "composer_height",  # висота композера
    "bottom_height",    # висота нижньої панелі
    "window_size",      # розмір вікна "1560x940" після ручного розтягування
)


def layout_path() -> Path:
    return app_data_dir() / "layout.json"


@dataclass
class Layout:
    """Числа розкладки (у пікселях)."""

    values: dict[str, int] = field(default_factory=dict)
    visible: dict[str, bool] = field(default_factory=dict)

    # ── числа ──────────────────────────────────────────────────────────────
    def get(self, key: str, default: int = 0) -> int:
        try:
            return max(0, int(self.values.get(key, default)))
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value: Any) -> None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return
        # 0 для sidebar_width — це теж осмислене «згорнуто», але ширина
        # панелі завжди > 0; зберігаємо лише додатні значення.
        if number > 0:
            self.values[key] = number

    def is_visible(self, key: str, default: bool = True) -> bool:
        return bool(self.visible.get(key, default))

    def set_visible(self, key: str, value: bool) -> None:
        self.visible[key] = bool(value)

    # ── серіалізація ───────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {"values": dict(self.values), "visible": dict(self.visible)}

    @classmethod
    def from_dict(cls, data: Any) -> "Layout":
        if not isinstance(data, dict):
            return cls()
        values = data.get("values")
        visible = data.get("visible")
        clean_values: dict[str, int] = {}
        if isinstance(values, dict):
            for key, value in values.items():
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if number > 0:
                    clean_values[str(key)] = number
        clean_visible: dict[str, bool] = {}
        if isinstance(visible, dict):
            for key, value in visible.items():
                clean_visible[str(key)] = bool(value)
        return cls(values=clean_values, visible=clean_visible)


def load(path: Path | None = None) -> Layout:
    """Прочитати збережену розкладку (порожня, якщо файла немає).

    ``path`` приймає й рядок: його передають тести й палітра команд, а
    ``target.read_text()`` на рядку падає ``AttributeError``, і розкладка
    мовчки «не знаходилась» (перевірено ``tools/probe_module_str_args.py``).
    """
    target = Path(path) if path else layout_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Layout()
    return Layout.from_dict(data)


def save(layout: Layout, path: Path | None = None) -> None:
    """Записати розкладку (тихо, без падіння на помилках диска)."""
    target = Path(path) if path else layout_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(layout.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        temp.replace(target)
    except OSError as exc:
        LOG.warning("Не вдалось зберегти розкладку: %s", exc)


def clamp(value: int, low: int, high: int) -> int:
    """Обмежити число розумними межами."""
    if high < low:
        high = low
    return max(low, min(int(value), high))


def sash_pos(fraction: float, total: int) -> int:
    """Перевести частку (0..1) у позицію саша для заданої довжини."""
    if total <= 0:
        return 0
    return clamp(int(total * max(0.0, min(1.0, fraction))), 60, max(60, total - 60))


def fraction_of(position: int, total: int) -> float:
    """Зворотне: позиція саша → частка (для збереження відносних величин)."""
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, position / total))


__all__ = [
    "KEYS",
    "Layout",
    "clamp",
    "fraction_of",
    "layout_path",
    "load",
    "sash_pos",
    "save",
]
