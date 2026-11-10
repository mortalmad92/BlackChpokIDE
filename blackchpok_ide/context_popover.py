"""Спливне вікно з розбивкою контексту по складових.

Показує те саме, що сучасні агентні редактори: скільки контексту займає
системна підказка, описи інструментів і повідомлення, із відсотками та
смугою розподілу.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from . import context_stats, theme, widgets

BAR_WIDTH = 250
BAR_HEIGHT = 5


class ContextPopover(tk.Toplevel):
    """Картка «Використано контексту» зі складовими."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        stats: context_stats.ContextStats,
        *,
        limit: int = 0,
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.stats = stats
        self.limit = int(limit or stats.context_limit or 0)
        self.withdraw()
        self.overrideredirect(True)
        widgets.register_popover(self)
        self.configure(bg=theme.BORDER_SOFT)
        self._build()
        self.transient(master.winfo_toplevel())

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_CARD)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(1, weight=1)

        stats = self.stats
        breakdown = stats.breakdown
        fill = stats.fill_percent if self.limit else 0.0

        # ── заголовок: відсоток і «~N / M»
        head = tk.Frame(body, bg=theme.BG_CARD)
        head.grid(row=0, column=0, columnspan=3, sticky="ew", padx=14, pady=(12, 0))
        head.columnconfigure(1, weight=1)

        self.percent_label = tk.Label(
            head, text=f"{fill:.0f}%", bg=theme.BG_CARD, fg=theme.FG_BRIGHT,
            font=("Segoe UI", 17, "bold"),
        )
        self.percent_label.grid(row=0, column=0, rowspan=2, sticky="w")

        tk.Label(head, text="використано", bg=theme.BG_CARD, fg=theme.FG_DIM,
                 font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(10, 0))

        self.total_label = tk.Label(
            head, text=self._total_text(), bg=theme.BG_CARD, fg=theme.FG,
            font=("Segoe UI", 9, "bold"), anchor="e",
        )
        self.total_label.grid(row=0, column=2, sticky="e")
        tk.Label(head, text="контексту", bg=theme.BG_CARD, fg=theme.FG_DIM,
                 font=("Segoe UI", 8), anchor="e").grid(
            row=1, column=2, sticky="e")

        # ── смуга розподілу
        canvas = tk.Canvas(body, width=BAR_WIDTH, height=BAR_HEIGHT,
                           bg=theme.BG_CARD, bd=0, highlightthickness=0)
        canvas.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(10, 4))
        self.canvas = canvas
        self._draw_bar(canvas, breakdown)

        tk.Frame(body, bg=theme.BORDER, height=1).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(8, 6))

        # ── складові
        colours = {
            "Системна підказка": theme.FG_DIM,
            "Опис інструментів": theme.PURPLE,
            "Повідомлення": theme.ACCENT,
        }
        row_index = 3
        for label, tokens in breakdown.parts:
            self._part_row(body, row_index, label, tokens, colours.get(label, theme.FG))
            row_index += 1

        if not breakdown.estimated_total and not stats.last_prompt_tokens:
            tk.Label(body, text="Даних ще немає — надішли запит агенту.",
                     bg=theme.BG_CARD, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                     anchor="w", justify="left").grid(
                row=row_index, column=0, columnspan=3, sticky="ew", padx=14, pady=(2, 10))
        else:
            self._extra_rows(body, row_index)

    def _part_row(self, body: tk.Frame, row: int, label: str, tokens: int,
                  colour: str) -> None:
        square = tk.Label(body, text="■", bg=theme.BG_CARD, fg=colour,
                          font=("Segoe UI", 8))
        square.grid(row=row, column=0, padx=(14, 6), pady=1, sticky="w")

        pair_label = tk.Label(
            body, text=label, bg=theme.BG_CARD, fg=theme.FG,
            font=("Segoe UI", 9), anchor="w",
        )
        pair_label.grid(row=row, column=1, sticky="ew", pady=1)

        tk.Label(body, text=self._short_tokens(tokens), bg=theme.BG_CARD, fg=theme.FG_DIM,
                 font=("Segoe UI", 9), anchor="e").grid(
            row=row, column=2, sticky="e", padx=(8, 14), pady=1)

    def _extra_rows(self, body: tk.Frame, row: int) -> None:
        """Додаткові рядки: влучання в кеш і швидкість."""
        stats = self.stats
        if stats.prompt_tokens:
            text = f"Влучання в кеш: {stats.cache_hit_percent:.0f}%"
            tk.Label(body, text=text, bg=theme.BG_CARD, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w").grid(
                row=row, column=0, columnspan=2, sticky="w", padx=14, pady=(6, 0))
            row += 1
        if stats.step_count:
            text = f"Кроків: {stats.step_count} · {stats.speed_text()} · {stats.elapsed_text}"
            tk.Label(body, text=text, bg=theme.BG_CARD, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w").grid(
                row=row, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 10))
        else:
            tk.Frame(body, bg=theme.BG_CARD, height=8).grid(row=row, column=0)

    # ── розрахунки й малювання ─────────────────────────────────────────────
    def _total_text(self) -> str:
        used = self.stats.last_prompt_tokens or self.stats.breakdown.estimated_total
        if self.limit:
            return f"{self._short_tokens(used)} / {self._short_tokens(self.limit)}"
        return self._short_tokens(used)

    @staticmethod
    def _short_tokens(tokens: int) -> str:
        """Компактно: 390 → «390», 1500 → «~1,5K», 16384 → «~16,4K».

        Тильда додається лише до округлених значень — інакше в підписі
        «~N / M» вона подвоювалась би.
        """
        tokens = max(0, int(tokens))
        if tokens < 1000:
            return str(tokens)
        value = tokens / 1000
        text = f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"~{text}K"

    def _draw_bar(self, canvas: tk.Canvas, breakdown: context_stats.ContextBreakdown) -> None:
        """Смуга: тонкі поділки + заповнена частина трьома кольорами."""
        limit = self.limit or 1
        total = breakdown.total_tokens or breakdown.estimated_total
        if not total:
            canvas.create_rectangle(0, 0, BAR_WIDTH, BAR_HEIGHT,
                                    fill=theme.BG_INPUT, outline="")
            return

        canvas.create_rectangle(0, 0, BAR_WIDTH, BAR_HEIGHT, fill=theme.BG_INPUT, outline="")
        x = 0.0
        colours = (theme.FG_DIM, theme.PURPLE, theme.ACCENT)
        for index, (_label, tokens) in enumerate(breakdown.parts):
            width = BAR_WIDTH * (tokens / limit)
            if width <= 0:
                continue
            x2 = min(BAR_WIDTH, x + width)
            canvas.create_rectangle(x, 0, x2, BAR_HEIGHT,
                                    fill=colours[index], outline="")
            x = x2
            if x >= BAR_WIDTH:
                break

    # ── показ ──────────────────────────────────────────────────────────────
    def show_at(self, widget: tk.Misc) -> None:
        """Показати картку над віджетом (як спливне вікно)."""
        try:
            self.update_idletasks()
            width = max(self.winfo_reqwidth(), BAR_WIDTH + 28)
            height = self.winfo_reqheight()
            x = widget.winfo_rootx() + widget.winfo_width() - width
            y = widget.winfo_rooty() - height - 6
            if y < 0:
                y = widget.winfo_rooty() + widget.winfo_height() + 6
            # Межі екрана: картка не має виїжджати за край монітора.
            x, y = widgets.clamp_to_screen(self, x, y, width, height)
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.deiconify()
            self.lift()
        except tk.TclError:
            return

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


__all__ = ["ContextPopover", "BAR_WIDTH", "BAR_HEIGHT"]
