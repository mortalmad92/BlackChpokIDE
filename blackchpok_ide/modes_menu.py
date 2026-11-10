"""Спливне меню режимів роботи агента.

Компактна картка під кнопкою режиму в заголовку сесії:

    ┌──────────────────────────────────────────────┐
    │ РЕЖИМ РОБОТИ                                 │
    │ ◌  Чат        Звичайний діалог, файли не…  ✓ │
    │ ◈  Агент      Автономне виконання…           │
    │ ⟨⟩ Код        Правки коду й перевірка…       │
    │ ☰  План       Спершу план, файли не змі…     │
    │ ⌘  Інструменти MCP, пошук, команди, RAG      │
    └──────────────────────────────────────────────┘

Кожен пункт справді змінює те, що робить агент (див. :mod:`modes`).
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import modes, permissions, theme, widgets

ROW_HEIGHT = 46


class ModeMenu(tk.Toplevel):
    """Меню режимів роботи агента."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme,
                 on_pick: Optional[Callable[[str], None]] = None, *,
                 current: str = modes.DEFAULT_MODE) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.on_pick = on_pick
        self.current = modes.normalise(current)
        self._rows: list[tk.Frame] = []
        self._anchor: Optional[tk.Misc] = None
        self.withdraw()
        self.overrideredirect(True)
        widgets.register_popover(self)
        self.configure(bg=theme.BORDER_SOFT)
        self._build()

    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ELEVATED, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        tk.Label(body, text="РЕЖИМ РОБОТИ", bg=theme.BG_ELEVATED, fg=theme.FG_FAINT,
                 font=self.fonts.ui_tiny, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(8, 4))

        host = tk.Frame(body, bg=theme.BG_ELEVATED)
        host.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        host.columnconfigure(0, weight=1)

        for mode in modes.MODES:
            self._row(host, mode)

        footer = tk.Label(body, text="режим змінює дозволи й ліміт кроків агента",
                          bg=theme.BG_ELEVATED, fg=theme.FG_FAINT, font=("Segoe UI", 7),
                          anchor="w")
        footer.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))

    def _row(self, host: tk.Misc, mode: modes.AgentMode) -> None:
        active = mode.key == self.current
        bg = theme.BG_ACTIVE if active else theme.BG_ELEVATED
        row = tk.Frame(host, bg=bg, cursor="hand2", height=ROW_HEIGHT)
        row.pack(fill="x", pady=1)
        row.columnconfigure(1, weight=1)

        icon = tk.Label(row, text=mode.icon, bg=bg,
                        fg=theme.ACCENT if active else theme.FG_DIM,
                        font=("Segoe UI", 12), width=2, anchor="center")
        icon.grid(row=0, column=0, rowspan=2, padx=(8, 4), pady=6)

        title = tk.Label(row, text=mode.label, bg=bg,
                         fg=theme.FG_BRIGHT if active else theme.FG,
                         font=("Segoe UI", 9, "bold"), anchor="w")
        title.grid(row=0, column=1, sticky="ew", pady=(6, 0))

        hint = tk.Label(row, text=mode.hint, bg=bg, fg=theme.FG_FAINT,
                        font=("Segoe UI", 7), anchor="w", justify="left",
                        wraplength=330)
        hint.grid(row=1, column=1, sticky="ew", pady=(0, 6))

        if active:
            tk.Label(row, text="✓", bg=bg, fg=theme.ACCENT,
                     font=("Segoe UI", 9)).grid(row=0, column=2, padx=(4, 10))

        labels = (icon, title, hint)
        for widget in (row, *labels):
            widget.bind("<Enter>", lambda _e, r=row, ls=labels: self._hover(r, ls, True))
            widget.bind("<Leave>", lambda _e, r=row, ls=labels: self._hover(r, ls, False))
            widget.bind("<Button-1>", lambda _e, k=mode.key: self._pick(k))
        self._rows.append(row)

    def _hover(self, row: tk.Frame, labels, enter: bool) -> None:
        colour = theme.BG_HOVER if enter else theme.BG_ELEVATED
        try:
            row.configure(bg=colour)
            for label in labels:
                label.configure(bg=colour)
        except tk.TclError:
            pass

    def _pick(self, key: str) -> None:
        self.current = modes.normalise(key)
        if self.on_pick is not None:
            self.on_pick(self.current)
        self.close()

    # ── геометрія ──────────────────────────────────────────────────────────
    def show_below(self, widget: tk.Misc) -> None:
        self._anchor = widget
        try:
            self.deiconify()
            self.update_idletasks()
            self._place()
            self.after_idle(self._place)
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.lift()
        except tk.TclError:
            return

    def _place(self) -> None:
        """Розмір і позиція під якорем, гарантовано в межах екрана."""
        anchor = self._anchor
        if anchor is None or not anchor.winfo_exists():
            return
        try:
            self.update_idletasks()
            width = 420
            height = max(140, self.winfo_reqheight())
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 6
            # Спершу тримаємось вікна застосунку (меню не має вилазити за
            # оболонку), потім — екрана: якщо IDE стоїть біля краю або на
            # другому моніторі, картка все одно лишиться досяжною.
            root = anchor.winfo_toplevel()
            try:
                left = root.winfo_rootx()
                top = root.winfo_rooty()
                right = left + root.winfo_width()
                bottom = top + root.winfo_height()
                if x + width > right - 8:
                    x = max(left + 8, right - width - 8)
                if y + height > bottom - 8:
                    y = max(top + 8, anchor.winfo_rooty() - height - 6)
            except tk.TclError:
                pass
            x, y = widgets.clamp_to_screen(self, x, y, width, height)
            self.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
        except tk.TclError:
            return

    def close(self) -> None:
        try:
            self.withdraw()
        except tk.TclError:
            pass

    @property
    def visible(self) -> bool:
        try:
            return bool(self.winfo_viewable())
        except tk.TclError:
            return False


__all__ = ["ModeMenu"]
