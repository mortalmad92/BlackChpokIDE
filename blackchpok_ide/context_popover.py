"""Спливне вікно використання контексту.

Числа беруться з відповіді локальної моделі (``prompt_tokens``) і з
реального вікна (``n_ctx``). Частини — системний промпт, схеми
інструментів і повідомлення — це те, що справді пішло в останній запит.
Окремих «правил», «скілів» чи «субагентів» тут немає: модель їх не
рахує окремо, тож вигадувати рядки не можна.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from . import context_stats, theme, widgets

BAR_WIDTH = 360
BAR_HEIGHT = 10


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
        used = int(stats.last_prompt_tokens or 0)
        real = used > 0
        fill = stats.fill_percent if (self.limit and real) else 0.0
        breakdown = stats.breakdown if real else context_stats.ContextBreakdown()

        tk.Label(body, text="ВИКОРИСТАННЯ КОНТЕКСТУ", bg=theme.BG_CARD,
                 fg=theme.FG_FAINT, font=theme.font(8, "bold"),
                 anchor="w").grid(row=0, column=0, columnspan=3, sticky="ew",
                                  padx=16, pady=(14, 0))

        head = tk.Frame(body, bg=theme.BG_CARD)
        head.grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(6, 0))
        head.columnconfigure(1, weight=1)

        self.percent_label = tk.Label(
            head, text=(f"{fill:.0f}% заповнено" if real else "немає даних"),
            bg=theme.BG_CARD, fg=theme.FG_BRIGHT,
            font=theme.font(16, "bold"),
        )
        self.percent_label.grid(row=0, column=0, sticky="w")

        self.total_label = tk.Label(
            head, text=self._total_text() if real else "—",
            bg=theme.BG_CARD, fg=theme.FG, font=theme.font(10), anchor="e",
        )
        self.total_label.grid(row=0, column=1, sticky="e")

        canvas = tk.Canvas(body, width=BAR_WIDTH, height=BAR_HEIGHT,
                           bg=theme.BG_CARD, bd=0, highlightthickness=0)
        canvas.grid(row=2, column=0, columnspan=3, sticky="ew",
                    padx=16, pady=(12, 8))
        self.canvas = canvas
        self._draw_bar(canvas, breakdown, used=used)

        colours = {
            "Системна підказка": theme.FG_DIM,
            "Опис інструментів": theme.PURPLE,
            "Повідомлення": theme.ACCENT,
        }
        row_index = 3
        if real:
            for label, tokens in breakdown.parts:
                if tokens <= 0:
                    continue
                self._part_row(body, row_index, label, tokens,
                               colours.get(label, theme.FG))
                row_index += 1
            note = "Число зліва — prompt_tokens останньої відповіді моделі."
            if self.limit:
                note += " Смуга — частка її вікна."
            tk.Label(body, text=note, bg=theme.BG_CARD, fg=theme.FG_FAINT,
                     font=theme.font(8), anchor="w", wraplength=BAR_WIDTH,
                     justify="left").grid(
                row=row_index, column=0, columnspan=3, sticky="ew",
                padx=16, pady=(8, 4))
            self._extra_rows(body, row_index + 1)
        else:
            tk.Label(
                body,
                text="Модель ще не відповіла. Тут з’являться токени з її "
                     "відповіді, а не оцінка навмання.",
                bg=theme.BG_CARD, fg=theme.FG_FAINT, font=theme.font(8),
                anchor="w", justify="left", wraplength=BAR_WIDTH,
            ).grid(row=row_index, column=0, columnspan=3, sticky="ew",
                   padx=16, pady=(4, 14))

    def _part_row(self, body: tk.Frame, row: int, label: str, tokens: int,
                  colour: str) -> None:
        square = tk.Label(body, text="■", bg=theme.BG_CARD, fg=colour,
                          font=theme.font(8))
        square.grid(row=row, column=0, padx=(14, 6), pady=1, sticky="w")

        pair_label = tk.Label(
            body, text=label, bg=theme.BG_CARD, fg=theme.FG,
            font=theme.font(9), anchor="w",
        )
        pair_label.grid(row=row, column=1, sticky="ew", pady=1)

        tk.Label(body, text=self._short_tokens(tokens), bg=theme.BG_CARD, fg=theme.FG_DIM,
                 font=theme.font(9), anchor="e").grid(
            row=row, column=2, sticky="e", padx=(8, 14), pady=1)

    def _extra_rows(self, body: tk.Frame, row: int) -> None:
        stats = self.stats
        total_used = int(getattr(stats, "total_session_tokens", 0) or 0)
        if total_used > 0:
            tk.Label(
                body,
                text=f"\u0412\u0438\u043a\u043e\u0440\u0438\u0441\u0442\u0430\u043d\u043e \u0437\u0430 \u0441\u0435\u0441\u0456\u044e: {self._short_tokens(total_used)} \u0442\u043e\u043a\u0435\u043d\u0456\u0432",
                bg=theme.BG_CARD, fg=theme.FG, font=theme.font(8, "bold"), anchor="w",
            ).grid(row=row, column=0, columnspan=3, sticky="w", padx=16, pady=(4, 0))
            row += 1
        ev_cnt = int(getattr(stats, "evictions_count", 0) or 0)
        ev_tok = int(getattr(stats, "evicted_tokens", 0) or 0)
        ev_txt = (
            f"\u0417\u0432\u0456\u043b\u044c\u043d\u0435\u043d\u044c \u0443 \u043f\u0430\u043c'\u044f\u0442\u044c: {ev_cnt} (\u043f\u0435\u0440\u0435\u043d\u0435\u0441\u0435\u043d\u043e {self._short_tokens(ev_tok)} \u0442\u043e\u043a.)"
            if ev_cnt
            else "\u0417\u0432\u0456\u043b\u044c\u043d\u0435\u043d\u044c \u0443 \u043f\u0430\u043c'\u044f\u0442\u044c: 0"
        )
        tk.Label(
            body, text=ev_txt, bg=theme.BG_CARD,
            fg=(theme.ACCENT if ev_cnt else theme.FG_FAINT),
            font=theme.font(8), anchor="w",
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=16, pady=(2, 0))
        row += 1
        if stats.prompt_tokens:
            tk.Label(
                body, text=f"\u0412\u043b\u0443\u0447\u0430\u043d\u043d\u044f \u0432 \u043a\u0435\u0448: {stats.cache_hit_percent:.0f}%",
                bg=theme.BG_CARD, fg=theme.FG_FAINT, font=theme.font(8), anchor="w",
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 0))
            row += 1
        if stats.step_count:
            tk.Label(
                body, text=f"\u041a\u0440\u043e\u043a\u0456\u0432: {stats.step_count} | {stats.speed_text()} | {stats.elapsed_text}",
                bg=theme.BG_CARD, fg=theme.FG_FAINT, font=theme.font(8), anchor="w",
            ).grid(row=row, column=0, columnspan=3, sticky="w", padx=16, pady=(2, 12))
        else:
            tk.Frame(body, bg=theme.BG_CARD, height=10).grid(row=row, column=0)

    def _total_text(self) -> str:
        used = int(self.stats.last_prompt_tokens or 0)
        if self.limit:
            return f"{self._short_tokens(used)} / {self._short_tokens(self.limit)} токенів"
        return f"{self._short_tokens(used)} токенів"

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

    def _draw_bar(self, canvas: tk.Canvas, breakdown: context_stats.ContextBreakdown,
                  *, used: int) -> None:
        """Смуга вікна: кольори частин і сірий хвіст, якого модель не зайняла."""
        canvas.create_rectangle(0, 0, BAR_WIDTH, BAR_HEIGHT,
                                fill=theme.BG_INPUT, outline="")
        if used <= 0:
            return
        span = self.limit if self.limit > 0 else used
        x = 0.0
        colours = (theme.FG_DIM, theme.PURPLE, theme.ACCENT)
        for index, (_label, tokens) in enumerate(breakdown.parts):
            width = BAR_WIDTH * (max(0, tokens) / span)
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
