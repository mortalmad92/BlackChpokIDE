"""Адаптивні розміри чату й відповідей агента під реальний екран.

Проблема, яку це вирішує: ширина колонки діалогу й «комфортна» кількість
рядків у картці відповіді були сталими числами. На ноутбуці 1366×768 чат
виходив надто широким і водночас надто низьким, а на 4K-моніторі — навпаки,
відповідь губилась у вузькій смужці.

Модуль не тягне tkinter: він рахує числа з розмірів екрана й вікна, тому
його легко перевірити тестами без вікна.

    екран 1920×1080, вікно 1560×940
      ширина колонки діалогу  → 820 px   (комфортне читання)
      висота одного повідомлення  → до 30 рядків

Кількість рядків обмежується не «на око», а часткою видимої висоти стрічки:
одна відповідь не має забирати весь екран, але й не має обрізатись до
трьох рядків на маленькому екрані.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Абсолютні межі ширини колонки діалогу (px).
MIN_CHAT_WIDTH = 320
MAX_CHAT_WIDTH = 1180
#: Комфортна довжина рядка для читання тексту (символів) — основа вибору ширини.
COMFORT_LINE_CHARS = 92
#: Скільки пікселів орієнтовно займає один символ UI-шрифту.
CHAR_PX = 8
#: Межі для кількості видимих рядків однієї відповіді.
MIN_BODY_LINES = 12
MAX_BODY_LINES = 70
#: Частка видимої висоти стрічки, яку може зайняти одна відповідь.
BODY_HEIGHT_SHARE = 0.58
#: Висота одного екранного рядка тексту (px) для оцінки бюджету.
LINE_HEIGHT = 22
#: Пороги «вузького» й «широкого» вікна для режимів панелей.
COMPACT_WIDTH = 900
ROOMY_WIDTH = 1400


@dataclass(frozen=True)
class ChatMetrics:
    """Розраховані розміри для колонки діалогу."""

    chat_width: int
    composer_width: int
    body_lines: int
    feed_height: int
    compact: bool
    roomy: bool

    def describe(self) -> str:
        return (f"колонка {self.chat_width}px · рядків до {self.body_lines} · "
                f"{'вузько' if self.compact else ('широко' if self.roomy else 'норма')}")


def _clamp(value: int, low: int, high: int) -> int:
    if high < low:
        high = low
    return max(low, min(int(value), high))


def screen_size(widget=None) -> tuple[int, int]:
    """Розмір доступного екрана (ширина, висота).

    Береться робоча область вікна, а якщо вікно ще не з'явилось — весь
    екран. Помилки tkinter тут не кидаємо: модуль має пережити будь-який
    стан віджетів, зокрема знищені.
    """
    fallback = (1920, 1080)
    if widget is None:
        return fallback
    try:
        width = int(widget.winfo_screenwidth())
        height = int(widget.winfo_screenheight())
    except Exception:  # noqa: BLE001 - віджет може бути вже знищений
        return fallback
    if width <= 0 or height <= 0:
        return fallback
    return width, height


def chat_width_for(available_width: int, *, sidebar: int = 0, min_width: int = 0,
                   max_width: int = 0) -> int:
    """Ширина колонки діалогу під доступне місце.

    ``available_width`` — це ширина екрана АБО вікна; ``sidebar``
    віднімається лише тоді, коли передано ширину екрана (вікно вже не
    містить навігаційної колонки, і подвійне віднімання робило чат надто
    вузьким — 474 px там, де мало бути ~600).

    Орієнтир — комфортна довжина рядка (``COMFORT_LINE_CHARS`` символів),
    але не менше частки доступної ширини: інакше на маленькому екрані чат
    перетворюється на вузьку шпальту, а редактор забирає все.
    """
    available = max(MIN_CHAT_WIDTH, int(available_width) - int(sidebar or 0))
    comfort = COMFORT_LINE_CHARS * CHAR_PX
    wanted = _clamp(comfort, MIN_CHAT_WIDTH, MAX_CHAT_WIDTH)
    # На вузькому екрані комфортна ширина недосяжна — беремо частку місця.
    share = int(available * 0.46)
    width = min(wanted, max(share, int(available * 0.34)))
    low = max(MIN_CHAT_WIDTH, int(min_width or 0))
    high = int(max_width or 0) or MAX_CHAT_WIDTH
    return _clamp(width, low, max(low, high))


def body_lines_for(view_height: int) -> int:
    """Скільки рядків максимум показувати в одній відповіді."""
    height = max(0, int(view_height or 0))
    if height <= 0:
        return MIN_BODY_LINES * 2
    budget = int(height * BODY_HEIGHT_SHARE)
    return _clamp(budget // LINE_HEIGHT, MIN_BODY_LINES, MAX_BODY_LINES)


def metrics_for(
    *,
    screen: tuple[int, int] = (1920, 1080),
    window: tuple[int, int] = (1560, 940),
    feed_height: int = 0,
    sidebar: int = 264,
    min_width: int = 0,
    max_width: int = 0,
) -> ChatMetrics:
    """Порахувати всі розміри діалогу за екраном, вікном і стрічкою."""
    screen_w, screen_h = screen
    win_w, win_h = window
    effective_w = min(screen_w, win_w) if win_w > 1 else screen_w
    # ``window`` — це ширина робочої області (без навігації), тож sidebar
    # віднімаємо лише коли вікна ще немає й рахуємо від екрана.
    from_window = win_w > 1
    chat_w = chat_width_for(effective_w, sidebar=0 if from_window else sidebar,
                            min_width=min_width, max_width=max_width)
    # Композер трохи вужчий за стрічку, щоб поле вводу не «злипалось» з краєм.
    composer_w = max(MIN_CHAT_WIDTH, chat_w - 24) if chat_w > 520 else chat_w
    height = feed_height if feed_height > 40 else max(0, (min(screen_h, win_h) or screen_h) - 300)
    return ChatMetrics(
        chat_width=chat_w,
        composer_width=composer_w,
        body_lines=body_lines_for(height),
        feed_height=max(0, height),
        compact=effective_w < COMPACT_WIDTH,
        roomy=effective_w >= ROOMY_WIDTH,
    )


def sidebar_width_for(screen_width: int, *, current: int = 264) -> int:
    """Ширина бічної панелі: на вузькому екрані вона має бути меншою."""
    width = int(screen_width or 0)
    if width <= 0:
        return current
    if width < 1280:
        return _clamp(min(current, 220), 180, 320)
    if width >= 2200:
        return _clamp(max(current, 300), 240, 380)
    return _clamp(current or 264, 200, 340)


__all__ = [
    "BODY_HEIGHT_SHARE",
    "COMPACT_WIDTH",
    "ChatMetrics",
    "LINE_HEIGHT",
    "MAX_BODY_LINES",
    "MAX_CHAT_WIDTH",
    "MIN_BODY_LINES",
    "MIN_CHAT_WIDTH",
    "ROOMY_WIDTH",
    "body_lines_for",
    "chat_width_for",
    "metrics_for",
    "screen_size",
    "sidebar_width_for",
]
