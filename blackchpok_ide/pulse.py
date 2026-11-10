"""Анімовані індикатори для списку справ: крапки й пульсуючі кільця.

Агент описує свою роботу крок за кроком, і користувач має бачити, що саме
зараз виконується. Статична позначка тут не працює: потрібен живий рух —
зелена крапка з кільцем, що розходиться, поки крок триває, і спокійна галочка,
коли він завершився.

Щоб не плодити десятки таймерів ``after()``, усі крапки одного вікна
обслуговує один спільний тікер: він цокає лише тоді, коли є що анімувати.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import theme

#: Період кадру анімації (мс). 60 мс — плавно й майже не їсть процесор.
FRAME_MS = 60


def blend(first: str, second: str, ratio: float) -> str:
    """Змішати два кольори ``#rrggbb``: ``ratio=0`` — перший, ``1`` — другий."""
    ratio = max(0.0, min(1.0, float(ratio)))
    try:
        a = first.lstrip("#")
        b = second.lstrip("#")
        if len(a) != 6 or len(b) != 6:
            return first
        parts = []
        for index in (0, 2, 4):
            left = int(a[index:index + 2], 16)
            right = int(b[index:index + 2], 16)
            parts.append(int(round(left + (right - left) * ratio)))
        return "#{:02x}{:02x}{:02x}".format(*parts)
    except (ValueError, IndexError):
        return first


class _Ticker:
    """Один таймер на вікно: роздає «кадри» всім підписаним індикаторам."""

    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self._subscribers: list[Callable[[float], None]] = []
        self._job: Optional[str] = None
        self._phase = 0.0

    @property
    def empty(self) -> bool:
        return not self._subscribers

    def add(self, callback: Callable[[float], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)
        self.start()

    def remove(self, callback: Callable[[float], None]) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def start(self) -> None:
        if self._job is None:
            self._schedule()

    def stop(self) -> None:
        if self._job is not None:
            try:
                self.master.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None

    def _schedule(self) -> None:
        try:
            self._job = self.master.after(FRAME_MS, self._tick)
        except tk.TclError:
            self._job = None

    def _tick(self) -> None:
        self._job = None
        self._phase = (self._phase + 0.09) % 1.0
        for callback in list(self._subscribers):
            try:
                callback(self._phase)
            except tk.TclError:
                # Віджет знищено — тихо знімаємо його з обліку.
                self._subscribers.remove(callback)
        if self._subscribers:
            self._schedule()
        else:
            self._phase = 0.0


#: Тікери за ключем вікна: одне вікно — один таймер.
_TICKERS: dict[str, _Ticker] = {}


def ticker_for(master: tk.Misc) -> Optional[_Ticker]:
    """Спільний тікер для вікна, у якому живе віджет."""
    try:
        root = master.winfo_toplevel()
        if not root.winfo_exists():
            return None
        key = str(root)
    except (tk.TclError, AttributeError):
        return None
    existing = _TICKERS.get(key)
    if existing is not None and existing.master is root:
        return existing
    ticker = _Ticker(root)
    _TICKERS[key] = ticker

    # Вікно можуть закрити, не викликавши forget_ticker(). Тоді запланований
    # ``after`` лишається в інтерпретаторі, а його команда зникає разом із
    # вікном — Tcl друкує в stderr «invalid command name ..._tick». Знімаємо
    # тікер на самому знищенні вікна. Ключ беремо захопленим: під час
    # знищення ``winfo_toplevel()`` уже може не відповісти.
    def _on_root_destroy(event) -> None:
        if getattr(event, "widget", None) is not root:
            return
        gone = _TICKERS.pop(key, None)
        if gone is not None:
            gone.stop()

    try:
        root.bind("<Destroy>", _on_root_destroy, add="+")
    except tk.TclError:  # pragma: no cover - вікно вже недоступне
        pass
    return ticker


def forget_ticker(master: tk.Misc) -> None:
    """Прибрати тікер вікна (виклик при закритті)."""
    try:
        key = str(master.winfo_toplevel())
    except (tk.TclError, AttributeError):
        return
    ticker = _TICKERS.pop(key, None)
    if ticker is not None:
        ticker.stop()


class PulseDot(tk.Canvas):
    """Крапка стану: спокійна, пульсує, завершена або з помилкою.

    Стани навмисно названі так само, як у списку справ, щоб панель не
    перекладала їх у власні константи.
    """

    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    #: Кольори для кожного стану (``None`` — прозорий/порожній).
    _COLOURS = {
        IDLE: theme.BORDER_SOFT,
        RUNNING: theme.SUCCESS,
        DONE: theme.SUCCESS,
        FAILED: theme.ERROR,
    }

    def __init__(
        self,
        master: tk.Misc,
        *,
        size: int = 14,
        bg: str = theme.BG_CARD,
        state: str = IDLE,
        colour: str = "",
        **kwargs,
    ) -> None:
        super().__init__(master, width=size, height=size, bg=bg, bd=0,
                         highlightthickness=0, takefocus=0, **kwargs)
        self._size = max(8, int(size))
        self._bg = bg
        self._colour = colour or self._COLOURS.get(state, theme.SUCCESS)
        #: Копія кольорів на екземпляр: ``set_colour`` переписує її, і без
        #: копії змінений колір однієї крапки змінював би ВСІ крапки
        #: застосунку (словник оголошено на класі).
        self._COLOURS = dict(type(self)._COLOURS)
        self._state = state
        self._ring = self.create_oval(0, 0, 0, 0, outline=self._colour, width=1,
                                      state="hidden")
        self._core = self.create_oval(0, 0, 0, 0, outline="", fill=self._colour,
                                      width=0)
        self._ticker: Optional[_Ticker] = None
        self._paint(0.0)
        self._sync()
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ── стан ───────────────────────────────────────────────────────────────
    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state not in self._COLOURS:
            state = self.IDLE
        if state == self._state:
            return
        self._state = state
        self._colour = self._COLOURS[state]
        self._paint_(0.0)
        self._sync()

    def set_colour(self, colour: str) -> None:
        """Замінити зелений на інший (для особливих випадків)."""
        if not colour:
            return
        self._colour = colour
        self._COLOURS = {**self._COLOURS, self._state: colour}
        self._paint_(0.0)

    def set_bg(self, bg: str) -> None:
        self._bg = bg
        try:
            self.configure(bg=bg)
        except tk.TclError:
            return
        self._paint_(0.0)

    # ── малювання ──────────────────────────────────────────────────────────
    def _paint_(self, phase: float) -> None:
        try:
            self._paint(phase)
        except tk.TclError:
            pass

    def _paint(self, phase: float) -> None:
        size = self._size
        centre = size / 2.0
        half = centre - 1.0
        if self._state == self.RUNNING:
            core_r = max(2.0, size * 0.19)
            ring_r = core_r + (half - core_r) * phase
            fade = blend(self._colour, self._bg, min(1.0, phase ** 0.75))
            self.itemconfigure(self._ring, state="normal",
                               outline=fade, width=1)
            self.coords(self._ring, centre - ring_r, centre - ring_r,
                        centre + ring_r, centre + ring_r)
            core_colour = blend(self._colour, self._bg, phase * 0.25)
            self.itemconfigure(self._core, fill=core_colour)
            self.coords(self._core, centre - core_r, centre - core_r,
                        centre + core_r, centre + core_r)
            return

        self.itemconfigure(self._ring, state="hidden")
        if self._state == self.DONE:
            core_r = max(2.5, size * 0.24)
            self.itemconfigure(self._core, fill=self._colour)
            self.coords(self._core, centre - core_r, centre - core_r,
                        centre + core_r, centre + core_r)
            return
        if self._state == self.FAILED:
            core_r = max(2.5, size * 0.26)
            self.itemconfigure(self._core, fill=self._colour)
            self.coords(self._core, centre - core_r, centre - core_r,
                        centre + core_r, centre + core_r)
            return
        # IDLE: порожнє кільце — «ще не почато».
        self.itemconfigure(self._core, fill=self._bg, outline=self._colour, width=1)
        core_r = max(3.0, size * 0.30)
        self.coords(self._core, centre - core_r, centre - core_r,
                    centre + core_r, centre + core_r)

    # ── анімація ───────────────────────────────────────────────────────────
    def _sync(self) -> None:
        if self._state == self.RUNNING:
            if self._ticker is None:
                self._ticker = ticker_for(self)
                if self._ticker is not None:
                    self._ticker.add(self._on_frame)
            return
        self._detach()

    def _detach(self) -> None:
        if self._ticker is not None:
            self._ticker.remove(self._on_frame)
            self._ticker = None

    def _on_frame(self, phase: float) -> None:
        if self._state != self.RUNNING:
            self._detach()
            return
        self._paint_(phase)

    def _on_destroy(self, _event=None) -> None:
        self._detach()


__all__ = [
    "FRAME_MS",
    "PulseDot",
    "_Ticker",
    "blend",
    "forget_ticker",
    "ticker_for",
]
