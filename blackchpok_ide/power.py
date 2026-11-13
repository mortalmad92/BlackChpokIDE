"""Керування ресурсами моделі: зупинка агента й вивантаження з відеокарти.

Дві різні речі, які легко переплутати:

* **Зупинка агента** — припинити поточний запит. Модель лишається в пам'яті.
* **Вивантаження з відеокарти** — зупинити сам ``llama-server``, щоб він
  віддав VRAM. Потрібне, коли користувач пішов (грає в гру, рендерить
  відео), а модель тримає гігабайти даремно.

Правило, яке тут реалізовано: **в автономному режимі модель не вивантажуємо**
— інакше агент прокидається, знаходить «мертвий» сервер і вся нічна робота
зупиняється. Тихий простій враховується лише тоді, коли режим вимкнено.

Модуль не тягне tkinter і не запускає потоків: рішення «чи час вивантажувати»
повертається як проста відповідь, а саму зупинку робить ведучий.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

LOG = logging.getLogger("blackchpok.power")

#: Скільки секунд простою вважати «користувач не працює» за замовчуванням.
DEFAULT_IDLE_SECONDS = 300
#: Найкоротший дозволений поріг: часті перезапуски моделі дорожчі за простій.
MIN_IDLE_SECONDS = 60
#: Найдовший поріг — пів години: далі модель майже напевно не потрібна.
MAX_IDLE_SECONDS = 1800

STATE_LOADED = "завантажена"
STATE_UNLOADED = "вивантажена"
STATE_UNKNOWN = "невідомо"


@dataclass
class IdlePolicy:
    """Налаштування політики простою."""

    #: Вивантажувати модель, коли користувач не працює.
    enabled: bool = True
    #: Поріг простою в секундах.
    idle_seconds: int = DEFAULT_IDLE_SECONDS
    #: Чи можна вивантажувати навіть коли агент зайнятий (майже завжди ні).
    unload_while_busy: bool = False

    def normalise(self) -> "IdlePolicy":
        try:
            seconds = int(self.idle_seconds)
        except (TypeError, ValueError):
            seconds = DEFAULT_IDLE_SECONDS
        self.idle_seconds = max(MIN_IDLE_SECONDS, min(MAX_IDLE_SECONDS, seconds))
        self.enabled = bool(self.enabled)
        self.unload_while_busy = bool(self.unload_while_busy)
        return self


@dataclass
class IdleTracker:
    """Лічить, скільки користувач не торкався агента.

    ``touch()`` кличеться на кожну справжню дію користувача: надісланий
    запит, натиснута кнопка, перемикання панелі. Таймер сам по собі не
    «скидається» від фонового оновлення інтерфейсу — інакше він ніколи б
    не спрацював.
    """

    policy: IdlePolicy = field(default_factory=IdlePolicy)
    last_touch: float = field(default_factory=time.time)
    unloaded_at: float = 0.0
    unload_count: int = 0

    def touch(self) -> None:
        self.last_touch = time.time()

    @property
    def idle_seconds(self) -> float:
        return max(0.0, time.time() - self.last_touch)

    @property
    def idle_text(self) -> str:
        seconds = int(self.idle_seconds)
        if seconds < 60:
            return f"{seconds} с"
        return f"{seconds // 60} хв"

    def should_unload(self, *, busy: bool, autonomous: bool, loaded: bool) -> bool:
        """Чи час вивантажити модель.

        Умови всі разом:

        1. політика ввімкнена;
        2. модель справді завантажена;
        3. автономний режим вимкнено (він працює безперервно);
        4. агент не виконує запит (або це явно дозволено);
        5. простій перевищив поріг.
        """
        if not self.policy.enabled or not loaded:
            return False
        if autonomous:
            return False
        if busy and not self.policy.unload_while_busy:
            return False
        return self.idle_seconds >= self.policy.idle_seconds

    def mark_unloaded(self) -> None:
        self.unloaded_at = time.time()
        self.unload_count += 1
        # Після вивантаження таймер стартує заново, інакше наступний тік
        # знову «хоче» вивантажити щойно вивантажене.
        self.touch()


class ModelKeeper:
    """Тримає посилання на керований сервер і вміє його підняти назад.

    ``server_provider`` повертає об'єкт із ``running``/``stop()`` (це
    :class:`blackchpok_ide.runtime.LocalServer`), ``start_provider`` —
    функцію повторного запуску (зазвичай метод вікна IDE).
    """

    def __init__(
        self,
        *,
        server_provider: Optional[Callable[[], object]] = None,
        start_provider: Optional[Callable[[], object]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        native_provider: Optional[Callable[[], object]] = None,
        native_start_provider: Optional[Callable[[], object]] = None,
    ) -> None:
        self.server_provider = server_provider
        self.start_provider = start_provider
        self.on_status = on_status
        #: Вбудований рушій (``NativeRuntime``): у нього немає ``running``, але
        #: є ``loaded``/``unload_model()``. Без цих провайдерів політика
        #: простою не бачила власний рушій і ніколи його не вивантажувала.
        self.native_provider = native_provider
        self.native_start_provider = native_start_provider
        self.tracker = IdleTracker()

    # ── стан ───────────────────────────────────────────────────────────────
    def _server(self):
        if self.server_provider is None:
            return None
        try:
            return self.server_provider()
        except Exception:  # noqa: BLE001 - провайдер не має ламати тік
            LOG.debug("Провайдер сервера впав", exc_info=True)
            return None

    def _native(self):
        if self.native_provider is None:
            return None
        try:
            return self.native_provider()
        except Exception:  # noqa: BLE001
            LOG.debug("Провайдер рушія впав", exc_info=True)
            return None

    @property
    def loaded(self) -> bool:
        native = self._native()
        if native is not None:
            try:
                if bool(getattr(native, "loaded", False)):
                    return True
            except Exception:  # noqa: BLE001
                pass
        server = self._server()
        if server is None:
            return False
        try:
            return bool(getattr(server, "running", False))
        except Exception:  # noqa: BLE001
            return False

    @property
    def state_text(self) -> str:
        if self.server_provider is None:
            return STATE_UNKNOWN
        return STATE_LOADED if self.loaded else STATE_UNLOADED

    @property
    def idle_text(self) -> str:
        return self.tracker.idle_text

    # ── дії ────────────────────────────────────────────────────────────────
    def touch(self) -> None:
        self.tracker.touch()

    def _status(self, text: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                LOG.debug("on_status моделі впав", exc_info=True)

    def should_unload(self, *, busy: bool, autonomous: bool) -> bool:
        """Чи ЧАС вивантажувати — БЕЗ самого вивантаження.

        Навіщо окремо від :meth:`poll`. Вивантаження рушія бере замки
        контексту й ЧЕКАЄ завершення поточного ``llama_decode`` (див.
        докстрінг ``Engine.unload``); для llama-server там узагалі
        ``process.wait(timeout=10)``. Викликати це з головного потоку —
        вікно «не відповідає» кілька секунд, саме як у скаргах
        «інколи зависає».

        Тепер тік простою лише ПИТАЄ (дешева арифметика над часом), а
        вивантаження виконує фоновий потік. Правило простою не змінилось.
        """
        return bool(self.tracker.should_unload(busy=busy, autonomous=autonomous,
                                               loaded=self.loaded))

    def poll(self, *, busy: bool, autonomous: bool) -> bool:
        """Перевірити простій і, якщо час, вивантажити. True — вивантажили."""
        if not self.should_unload(busy=busy, autonomous=autonomous):
            return False
        return self.unload()

    def unload(self) -> bool:
        """Звільнити пам'ять відеокарти: вивантажити рушій або зупинити сервер."""
        native = self._native()
        if native is not None:
            try:
                result = native.unload_model()
                if isinstance(result, dict) and result.get("unloaded"):
                    self.tracker.mark_unloaded()
                    self._status("Модель вивантажено з відеокарти — пам'ять вільна.")
                    LOG.info("Власний рушій вивантажено після %s простою",
                             self.tracker.idle_text)
                    return True
            except Exception as exc:  # noqa: BLE001 - показуємо причину
                LOG.warning("Власний рушій не вивантажився: %s", exc, exc_info=True)
                self._status(f"Не вдалось вивантажити модель: {exc}")
                return False
        server = self._server()
        if server is None:
            return False
        try:
            stop = getattr(server, "stop", None)
            if callable(stop):
                stop()
        except Exception as exc:  # noqa: BLE001 - показуємо причину
            LOG.warning("Не вдалось вивантажити модель: %s", exc, exc_info=True)
            self._status(f"Не вдалось вивантажити модель: {exc}")
            return False
        self.tracker.mark_unloaded()
        self._status("Модель вивантажено з відеокарти — пам'ять вільна.")
        LOG.info("Модель вивантажено після %s простою", self.tracker.idle_text)
        return True

    def reload(self) -> bool:
        """Підняти модель назад (наприклад, користувач повернувся)."""
        if self.loaded:
            return True
        if self.native_start_provider is not None:
            try:
                self.native_start_provider()
                if self.loaded:
                    self.tracker.touch()
                    self._status("Модель знову завантажена.")
                    return True
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Власний рушій не піднявся: %s", exc, exc_info=True)
        if self.start_provider is None:
            return False
        try:
            self.start_provider()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Не вдалось підняти модель: %s", exc, exc_info=True)
            self._status(f"Не вдалось підняти модель: {exc}")
            return False
        self.tracker.touch()
        self._status("Модель знову завантажена.")
        return True


__all__ = [
    "DEFAULT_IDLE_SECONDS",
    "IdlePolicy",
    "IdleTracker",
    "MAX_IDLE_SECONDS",
    "MIN_IDLE_SECONDS",
    "ModelKeeper",
    "STATE_LOADED",
    "STATE_UNKNOWN",
    "STATE_UNLOADED",
]
