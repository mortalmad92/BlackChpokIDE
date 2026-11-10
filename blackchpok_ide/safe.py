"""Безпечний виклик зворотних викликів: падає — але лишає слід.

Проблема, яку лікує модуль. Панелі IDE викликають колбеки оболонки
(``on_message``, ``on_busy_change``, ``on_case_start`` тощо) у
``try/except Exception: pass``. Якщо такий колбек падає, користувач бачить
«нічого не сталося»: повідомлення не збереглось, справа не почалась,
статус не оновився — і жодного сліду в журналі.

:func:`call` робить те саме, але:

* пише попередження в журнал ``blackchpok.ui`` з назвою колбека;
* за бажанням показує короткий текст у статусбарі, щоб збій було видно.

Виняток назовні не виходить: одна зламана підписка не має ламати
інтерфейс. Але й безслідно не зникає.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

LOG = logging.getLogger("blackchpok.ui")


def call(
    func: Optional[Callable[..., Any]],
    *args: Any,
    where: str = "",
    on_error: Optional[Callable[[str], None]] = None,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Викликати ``func`` так, щоб збій не ламав викликача, але був у журналі.

    :param func: що викликати; ``None`` — тихо повернути ``default``.
    :param where: людська назва дії для журналу й статусбара.
    :param on_error: отримує короткий текст помилки (напр. ``set_status``).
    :param default: значення, яке повертається при збої.
    """
    if func is None:
        return default
    try:
        return func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - навмисно ловимо все
        label = where or getattr(func, "__name__", "зворотний виклик")
        LOG.warning("Збій у «%s»: %s", label, exc, exc_info=True)
        record_failure(label, exc)
        if on_error is not None:
            try:
                on_error(f"Не вдалось: {label} ({type(exc).__name__})")
            except Exception:  # noqa: BLE001 - сама обробка не має падати
                pass
        return default


def call_quiet(func: Optional[Callable[..., Any]], *args: Any,
               where: str = "", **kwargs: Any) -> Any:
    """Як :func:`call`, але без повідомлення користувачу (лише журнал).

    Для внутрішніх зворотних викликів, збій яких не варто показувати
    (перемальовування підпису, оновлення лічильника).
    """
    # on_error навмисно ВІДКИДАЄТЬСЯ: «тихий» виклик не має показувати
    # повідомлення, навіть якщо хтось передав обробник.
    kwargs.pop("on_error", None)
    return call(func, *args, where=where, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Реєстр прихованих помилок: скільки збоїв «зникло»
# ─────────────────────────────────────────────────────────────────────────────

#: Скільки останніх збоїв тримаємо в пам'яті (для вікна перегляду).
MAX_REMEMBERED = 200

#: (коли, де, клас винятку, текст) — найновіші в кінці.
_FAILURES: list[tuple[float, str, str, str]] = []
#: Скільком підписникам уже сказали про збій.
_LISTENERS: list[Callable[[int], None]] = []


def record_failure(where: str, exc: BaseException) -> None:
    """Записати прихований збій і повідомити підписників.

    Навіщо: у коді 389 місць ``except …: pass``. Кожен збій там — це дія
    користувача, яка «нічого не зробила»: кнопка натиснулась, але стан не
    змінився. Без лічильника такі випадки невидимі, і причину доводиться
    шукати вручну.
    """
    import time

    label = " ".join((where or "невідома дія").split())[:120]
    kind = type(exc).__name__
    text = " ".join(str(exc).split())[:200]
    _FAILURES.append((time.time(), label, kind, text))
    del _FAILURES[:-MAX_REMEMBERED]
    count = len(_FAILURES)
    for listener in list(_LISTENERS):
        try:
            listener(count)
        except Exception:  # noqa: BLE001 - підписник не має ламати облік
            LOG.debug("Підписник реєстру збоїв упав", exc_info=True)


def failures() -> list[tuple[float, str, str, str]]:
    """Останні приховані збої (найновіші в кінці)."""
    return list(_FAILURES)


def failure_count() -> int:
    """Скільки прихованих збоїв сталося від старту."""
    return len(_FAILURES)


def clear_failures() -> None:
    """Скинути реєстр (кнопка «Очистити» у вікні збоїв)."""
    _FAILURES.clear()


def on_failure(listener: Callable[[int], None]) -> None:
    """Підписатись на збої: слухач отримує нову кількість."""
    _LISTENERS.append(listener)


def forget_listener(listener: Callable[[int], None]) -> None:
    """Відписатись (при закритті вікна)."""
    try:
        _LISTENERS.remove(listener)
    except ValueError:
        pass


__all__ = [
    "LOG",
    "MAX_REMEMBERED",
    "call",
    "call_quiet",
    "clear_failures",
    "failure_count",
    "failures",
    "forget_listener",
    "on_failure",
    "record_failure",
]
