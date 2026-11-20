"""Чіткий рендер на HiDPI у Windows.

Проблема, яку це вирішує. Tk за замовчуванням не оголошує себе
DPI-обізнаним, тому Windows масштабує намальоване вікно як картинку: при
масштабі 125/150 % текст стає розмитим, а дрібні підписи (розміри файлів,
лічильники токенів, назви кнопок) перетворюються на сірі плями. Один
виклик :func:`enable` перед створенням ``tk.Tk()`` прибирає і розмитість,
і «дрібноту»: Tk починає малювати в реальних пікселях екрана.

Другий бік — масштаб шрифтів. Після оголошення обізнаності ``tk scaling``
треба виставити з реального DPI (``GetDpiForWindow``), інакше Tk лишається
з припущенням 96 DPI і пункти рахуються неправильно.

Модуль не тягне tkinter: його можна викликати до створення вікна й
перевіряти тестами без дисплея.
"""

from __future__ import annotations

import sys

#: Типове припущення Tk, коли DPI невідомий.
BASE_DPI = 96.0

__all__ = ["BASE_DPI", "enable", "scale_for", "apply_scaling"]

_enabled = False


def enable() -> bool:
    """Оголосити процес DPI-обізнаним. Повертає ``True``, якщо вдалося.

    Порядок спроб: per-monitor (найкращий, Windows 8.1+) → system-aware
    (Windows Vista+) → нічого. Помилки ковтаємо: на не-Windows або в
    середовищі без user32 це просто означає «лишилось як було».
    """
    global _enabled
    if _enabled:
        return True
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        try:
            # PROCESS_PER_MONITOR_DPI_AWARE = 2 — вікно чітке на кожному
            # моніторі окремо, зокрема при переміщенні між ними.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _enabled = True
            return True
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _enabled = True
            return True
        except (AttributeError, OSError):
            return False
    except Exception:  # noqa: BLE001 - відсутність ctypes не має ламати старт
        return False


def scale_for(dpi: float) -> float:
    """Множник масштабу Tk для DPI (96 → 1.0, 144 → 1.5)."""
    try:
        value = float(dpi)
    except (TypeError, ValueError):
        return 1.0
    if value <= 0:
        return 1.0
    return value / BASE_DPI


def apply_scaling(root) -> float:
    """Виставити ``tk scaling`` за реальним DPI вікна. Повертає множник.

    ``tk scaling`` — це кількість пікселів на пункт, тому для 96 DPI вона
    дорівнює 96/72 ≈ 1.333. Без цього виклику після оголошення обізнаності
    шрифти лишаються дрібними: Tk рахує пункти за старим припущенням.
    """
    dpi = BASE_DPI
    if sys.platform.startswith("win"):
        try:
            import ctypes

            hwnd = root.winfo_id() if root is not None else 0
            if hwnd:
                dpi = float(ctypes.windll.user32.GetDpiForWindow(hwnd)) or BASE_DPI
            else:
                dpi = float(ctypes.windll.user32.GetDpiForSystem()) or BASE_DPI
        except Exception:  # noqa: BLE001 - лишаємось на 96 DPI
            dpi = BASE_DPI
    points_per_pixel = dpi / 72.0
    try:
        root.tk.call("tk", "scaling", points_per_pixel)
    except Exception:  # noqa: BLE001 - вікно може бути вже знищене
        pass
    return scale_for(dpi)
