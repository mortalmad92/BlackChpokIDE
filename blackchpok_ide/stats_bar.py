"""Смуга статистики під полем введення: кроки, токени, кеш і заповнення.

Виглядає як у сучасних агентних редакторах: тонкий рядок під композером із
живими метриками діалогу. Усі числа — справжні, з відповідей сервера моделі
(``usage``/``timings``), а не вигадані.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from . import context_stats, theme, widgets


class StatsBar(tk.Frame):
    """Рядок статистики: ● кроків · швидкість · токени · кеш · заповнення."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, *, bg: str = theme.BG_ALT) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.fonts = fonts
        self._bg = bg
        self.stats = context_stats.ContextStats()
        self._limit = 0
        self._build()
        self.render()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(1, weight=1)

        self.steps_icon = tk.Label(self, text="⟳", bg=self._bg, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8))
        self.steps_icon.grid(row=0, column=0, padx=(12, 4), pady=3)

        self.steps_label = tk.Label(self, text="0 кроків", bg=self._bg, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="w")
        self.steps_label.grid(row=0, column=1, sticky="w", pady=3)

        right = tk.Frame(self, bg=self._bg)
        right.grid(row=0, column=2, sticky="e", padx=(6, 12), pady=3)

        self.tokens_label = tk.Label(right, text="", bg=self._bg, fg=theme.FG_FAINT,
                                     font=("Segoe UI", 8))
        self.tokens_label.pack(side="left", padx=(0, 10))

        self.cache_label = tk.Label(right, text="", bg=self._bg, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8))
        self.cache_label.pack(side="left", padx=(0, 10))

        self.gauge = tk.Canvas(right, width=15, height=15, bg=self._bg, bd=0,
                               highlightthickness=0, cursor="hand2")
        self.gauge.pack(side="left", padx=(0, 4))
        self.gauge_arc = self.gauge.create_arc(1, 1, 14, 14, start=90, extent=0,
                                               style="arc", outline=theme.ACCENT, width=2)
        self.gauge.create_oval(5, 5, 10, 10, outline=theme.BORDER_SOFT, width=1)

        self.fill_label = tk.Label(right, text="0%", bg=self._bg, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8), cursor="hand2")
        self.fill_label.pack(side="left")

        # Клік або наведення на індикатор показує розбивку контексту.
        for widget in (self.gauge, self.fill_label, self.tokens_label):
            widget.bind("<Button-1>", lambda _e: self.toggle_popover())
            widget.bind("<Enter>", lambda _e: self._schedule_popover())
            widget.bind("<Leave>", lambda _e: self._cancel_popover())
        self.fill_label.configure(cursor="hand2")
        self.tokens_label.configure(cursor="hand2")

        # Підказка з деталями по наведенню на весь рядок.
        self._tip = widgets.Tip(self, "Ще немає даних від моделі.")
        self._popover = None
        self._popover_after = None

    # ── дані ───────────────────────────────────────────────────────────────
    def set_stats(self, stats: context_stats.ContextStats) -> None:
        # Ліміт контексту задається окремо (з плану запуску моделі), тому при
        # заміні об'єкта статистики переносимо його, інакше заповнення
        # показувало б «—».
        #
        # ── ПРІОРИТЕТ ЛІМІТУ ──────────────────────────────────────────────
        # Раніше брався ``stats.context_limit`` (число з об'єкта, який щойно
        # прийшов), і це ПЕРЕБИВАЛО правильний ліміт, уже застосований через
        # ``set_limit``: шкала показувала «0 / 8K», хоч модель працює з 16K.
        # Тепер головним є ліміт, ЯКИЙ ЗНАНЬ ЗАСТОСОВАНО (``self._limit``),
        # бо він приходить із РЕАЛЬНО завантаженої моделі.
        incoming = int(getattr(stats, "context_limit", 0) or 0)
        applied = int(getattr(self, "_limit", 0) or 0)
        limit = applied or incoming
        self.stats = stats
        if limit:
            self._limit = limit
            self.stats.set_limit(limit)
        self.render()
        self._refresh_popover()

    def _refresh_popover(self) -> None:
        """Оновити відкриту картку, щоб числа не «застигали»."""
        if self._popover is None:
            return
        self.hide_popover()
        self.show_popover()

    def set_limit(self, limit: int) -> None:
        self._limit = max(0, int(limit))
        self.stats.set_limit(self._limit)
        self.render()

    def reset(self) -> None:
        limit = getattr(self, "_limit", 0) or self.stats.context_limit
        self.stats.reset()
        if limit:
            self.stats.set_limit(limit)
        self.render()

    def set_model(self, label: str) -> None:
        self.model_text = label
        self.render()

    # ── спливне вікно з розбивкою ──────────────────────────────────────────
    def _schedule_popover(self) -> None:
        self._cancel_popover()
        try:
            self._popover_after = self.after(280, self.show_popover)
        except tk.TclError:
            self._popover_after = None

    def _cancel_popover(self) -> None:
        if self._popover_after is not None:
            try:
                self.after_cancel(self._popover_after)
            except (tk.TclError, ValueError):
                pass
            self._popover_after = None

    def show_popover(self) -> None:
        """Показати картку «використано контексту» зі складовими."""
        from . import context_popover

        self.hide_popover()
        try:
            self._popover = context_popover.ContextPopover(
                self, self.fonts, self.stats, limit=self._limit,
            )
            self._popover.show_at(self.gauge)
        except tk.TclError:
            self._popover = None

    def hide_popover(self) -> None:
        if self._popover is not None:
            try:
                self._popover.close()
            except tk.TclError:
                pass
            self._popover = None

    def toggle_popover(self) -> None:
        if self._popover is not None:
            self.hide_popover()
        else:
            self.show_popover()

    # ── малювання ──────────────────────────────────────────────────────────
    def render(self) -> None:
        stats = self.stats
        try:
            steps = stats.step_count
            word = _plural_steps(steps)
            self.steps_label.configure(text=f"Кроків: {steps} · {stats.speed_text()}")

            if stats.total_tokens:
                self.tokens_label.configure(text=f"⛁ {stats.tokens_text()}")
            else:
                self.tokens_label.configure(text="⛁ — ток")

            if stats.prompt_tokens:
                self.cache_label.configure(text=f"↺ {stats.cache_text()}")
            else:
                self.cache_label.configure(text="↺ кеш: —")

            fill = stats.fill_percent
            self.fill_label.configure(text=stats.fill_text())
            # Дуга заповнення: -90°, щоб ріст ішов за годинниковою стрілкою.
            extent = -max(0.0, min(360.0, fill * 3.6))
            self.gauge.itemconfigure(self.gauge_arc, extent=extent,
                                     outline=self._fill_colour(fill))
            self._tip.text = stats.detail_tooltip()
            self._tip_colour(fill, word)
        except tk.TclError:
            return

    def _fill_colour(self, fill: float) -> str:
        """Зелений → жовтий → червоний у міру заповнення контексту."""
        if fill >= 90:
            return theme.ERROR
        if fill >= 70:
            return theme.WARN
        if fill > 0:
            return theme.SUCCESS
        return theme.BORDER_SOFT

    def _tip_colour(self, fill: float, word: str) -> None:
        colour = theme.FG_FAINT
        if fill >= 90:
            colour = theme.ERROR
        elif fill >= 70:
            colour = theme.WARN
        elif self.stats.step_count:
            colour = theme.FG_DIM
        try:
            self.steps_label.configure(fg=colour)
            self.fill_label.configure(
                fg=colour if fill else theme.FG_FAINT,
                text=self.stats.fill_text() if self.stats.context_limit else "—",
            )
        except tk.TclError:
            pass


def _plural_steps(count: int) -> str:
    """Українське відмінювання: 1 крок · 2 кроки · 5 кроків."""
    if count % 10 == 1 and count % 100 != 11:
        return "крок"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "кроки"
    return "кроків"


def plural_steps(count: int) -> str:
    """Публічна форма для тестів: «3 кроки»."""
    return f"{count} {_plural_steps(count)}"
