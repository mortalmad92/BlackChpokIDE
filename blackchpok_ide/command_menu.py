"""Спливне меню композера: слэш-команди й вибір режиму дозволів.

Малюється як окреме вікно поверх вікна IDE над полем введення — так само,
як у сучасних агентних редакторах. Керується клавіатурою (↑ ↓ Enter Esc)
і мишею.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import permissions, slash_commands, theme, widgets

ROW_HEIGHT = 26
MAX_ROWS = 10


class CommandMenu(tk.Toplevel):
    """Меню над композером: список команд або режимів дозволів."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_choose: Optional[Callable[[object], None]] = None,
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.on_choose = on_choose
        self.items: list[tuple[str, str, str, object]] = []   # (підпис, підказка, іконка, payload)
        self.selected = 0
        self._rows: list[tk.Frame] = []
        self._min_width = 420
        self._outside_bid: Optional[str] = None
        self.withdraw()
        self.overrideredirect(True)
        widgets.register_popover(self)
        self.configure(bg=theme.BORDER_SOFT)
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.body = tk.Frame(self, bg=theme.BG_INPUT)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self.body.columnconfigure(1, weight=1)
        self.rows_host = tk.Frame(self.body, bg=theme.BG_INPUT)
        self.rows_host.grid(row=0, column=0, columnspan=3, sticky="nsew")
        self.rows_host.columnconfigure(0, weight=1)
        self.header = tk.Label(self.body, text="", bg=theme.BG_INPUT, fg=theme.FG_FAINT,
                               font=("Segoe UI", 8), anchor="w")
        self.header.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(2, 6))

    # ── наповнення ─────────────────────────────────────────────────────────
    def show_permissions(self, current: str = permissions.WORKSPACE) -> None:
        """Показати варіанти режиму дозволів."""
        active = permissions.normalise_mode(current)
        items: list[tuple[str, str, str, object]] = []
        for mode, label, hint, icon in slash_commands.permission_modes():
            mark = "  ✓" if mode == active else ""
            items.append((f"{label}{mark}", hint, icon, mode))
        self._fill(items, "Режим дозволів — ↑↓ вибір, Enter застосувати")
        # Підказки тут довгі, тож меню має бути ширшим за список команд.
        self._min_width = 620

    def show_commands(self, prefix: str = "") -> None:
        """Показати слэш-команди (можна з фільтром)."""
        self._min_width = 420
        commands = slash_commands.filter_commands(prefix)
        items: list[tuple[str, str, str, object]] = []
        for group, members in slash_commands.grouped(commands):
            for command in members:
                label = f"/{command.name}"
                if command.aliases:
                    label += f"  ({command.aliases[0]})"
                items.append((label, command.hint, command.icon, command))
        self._fill(items, "Команди — ↑↓ вибір, Enter вставити, Esc закрити")

    def _fill(self, items: list[tuple[str, str, str, object]], header: str) -> None:
        for row in self._rows:
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()
        self.items = items[:MAX_ROWS]
        self.selected = 0
        for index, (label, hint, icon, _payload) in enumerate(self.items):
            self._rows.append(self._row(index, label, hint, icon))
        self.header.configure(text=header)

    def _row(self, index: int, label: str, hint: str, icon: str) -> tk.Frame:
        row = tk.Frame(self.rows_host, bg=theme.BG_INPUT, height=ROW_HEIGHT, cursor="hand2")
        row.pack(fill="x", padx=4, pady=1)
        row.columnconfigure(1, weight=1)

        icon_label = tk.Label(row, text=icon, bg=theme.BG_INPUT, fg=theme.FG_DIM,
                              font=("Segoe UI", 9), width=2)
        icon_label.grid(row=0, column=0, padx=(6, 4), pady=3)

        name_label = tk.Label(row, text=label, bg=theme.BG_INPUT, fg=theme.FG,
                              font=("Segoe UI", 9), anchor="w")
        name_label.grid(row=0, column=1, sticky="ew", pady=3)

        hint_label = tk.Label(row, text=hint, bg=theme.BG_INPUT, fg=theme.FG_FAINT,
                              font=("Segoe UI", 8), anchor="e")
        hint_label.grid(row=0, column=2, sticky="e", padx=(8, 8), pady=3)

        for widget in (row, icon_label, name_label, hint_label):
            widget.bind("<Enter>", lambda _e, i=index: self._hover(i))
            widget.bind("<Button-1>", lambda _e, i=index: self._click(i))
        return row

    def _paint(self) -> None:
        for index, row in enumerate(self._rows):
            active = index == self.selected
            bg = theme.BG_ACTIVE if active else theme.BG_INPUT
            fg = theme.FG_BRIGHT if active else theme.FG
            for widget in row.winfo_children():
                widget.configure(bg=bg)
                if isinstance(widget, tk.Label):
                    widget.configure(fg=fg if widget is not row.winfo_children()[2]
                                     else theme.FG_FAINT)
            row.configure(bg=bg)
            try:
                row.winfo_children()[1].configure(fg=fg)
            except (IndexError, tk.TclError):
                pass

    def _hover(self, index: int) -> None:
        self.selected = max(0, min(index, len(self.items) - 1))
        self._paint()

    def _click(self, index: int) -> None:
        self.selected = index
        self.choose()

    # ── клавіатура ─────────────────────────────────────────────────────────
    def move(self, step: int) -> str:
        if not self.items:
            return "break"
        self.selected = (self.selected + step) % len(self.items)
        self._paint()
        return "break"

    def choose(self) -> str:
        if not self.items:
            self.close()
            return "break"
        payload = self.items[self.selected][3]
        on_choose = self.on_choose
        self.close()
        if on_choose is not None:
            on_choose(payload)
        return "break"

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

    # ── позиція ────────────────────────────────────────────────────────────
    def place_above(self, widget: tk.Misc) -> None:
        """Показати меню над віджетом (полем введення)."""
        try:
            # Спершу показуємо, потім міряємо: у прихованого вікна
            # winfo_reqheight() може бути некоректним, і меню виходило
            # порожнім.
            self.deiconify()
            self.update_idletasks()
            width = max(self._min_width, widget.winfo_width())
            height = max(120, self.winfo_reqheight())
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() - height - 4
            if y < 0:
                y = widget.winfo_rooty() + widget.winfo_height() + 4
            # Тримаємо меню в межах екрана: інакше на краю монітора воно
            # виїжджає за межі й частина пунктів недосяжна.
            x, y = widgets.clamp_to_screen(self, x, y, width, height)
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.update_idletasks()
            # Головне вікно буває -topmost (напр. після фокусу) — тоді меню
            # опиняється під ним. Піднімаємо й себе поверх.
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.lift()
            self._paint()
            # Клік поза меню має його закривати: інакше картка лишається
            # висіти поверх чату й перекриває транскрипт.
            self._bind_outside_close()
        except tk.TclError:
            return

    # ── закриття кліком поза меню ──────────────────────────────────────────
    def _bind_outside_close(self) -> None:
        if self._outside_bid is not None:
            return
        try:
            self._outside_bid = self.winfo_toplevel().bind(
                "<Button-1>", self._on_any_click, add="+")
        except tk.TclError:
            self._outside_bid = None

    def _on_any_click(self, event: tk.Event) -> None:
        if not self.visible:
            return
        try:
            under = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            under = None
        if under is None:
            self.close()
            return
        widget = under
        while widget is not None:
            if widget is self:
                return
            widget = getattr(widget, "master", None)
        self.close()

    def _unbind_outside_close(self) -> None:
        if self._outside_bid is None:
            return
        try:
            self.winfo_toplevel().unbind("<Button-1>", self._outside_bid)
        except tk.TclError:
            pass
        self._outside_bid = None


def attach_keys(menu: CommandMenu, text_widget: tk.Text) -> None:
    """Прокинути стрілки/Enter/Esc у меню, коли воно відкрите.

    Повертає ``"break"`` лише тоді, коли меню справді обробило клавішу —
    інакше поле введення працює як звичайно.
    """

    def _guard(handler):
        def inner(event=None):
            if not menu.visible:
                return None
            return handler(event)

        return inner

    text_widget.bind("<Up>", _guard(lambda _e: menu.move(-1)), add="+")
    text_widget.bind("<Down>", _guard(lambda _e: menu.move(1)), add="+")
    text_widget.bind("<Escape>", _guard(lambda _e: (menu.close(), "break")[1]), add="+")
    text_widget.bind("<Tab>", _guard(lambda _e: menu.move(1)), add="+")


__all__ = ["CommandMenu", "attach_keys"]
