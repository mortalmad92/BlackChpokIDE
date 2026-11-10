"""Меню вибору моделі для поточного чату.

Виглядає як у сучасних агентних редакторах: компактна картка над композером
із двома рядками — «Модель …›» і «Зусилля …›», кожен відкриває свій список.

Модель зберігається **за чатом**, тож різні розмови можуть працювати з
різними моделями.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import effort, theme, widgets

ROW_HEIGHT = 30


class ModelMenu(tk.Toplevel):
    """Картка вибору моделі й рівня зусилля."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_pick_model: Optional[Callable[[str], None]] = None,
        on_pick_effort: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.on_pick_model = on_pick_model
        self.on_pick_effort = on_pick_effort
        self.current_model = ""
        self.current_effort = effort.DEFAULT_EFFORT
        self.models: list[str] = []
        self.page = "root"          # root | models | efforts
        self._rows: list[tk.Frame] = []
        self.withdraw()
        self.overrideredirect(True)
        widgets.register_popover(self)
        self.configure(bg=theme.BORDER_SOFT)
        self.body = tk.Frame(self, bg=theme.BG_CARD)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self.body.columnconfigure(0, weight=1)
        self.rows_host = tk.Frame(self.body, bg=theme.BG_CARD)
        self.rows_host.grid(row=0, column=0, sticky="nsew")
        self.rows_host.columnconfigure(0, weight=1)
        self.header = tk.Label(self.body, text="", bg=theme.BG_CARD,
                               fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w")
        self.header.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 8))
        self._tip_rows: list[tuple[tk.Label, str, str]] = []
        self._anchor: Optional[tk.Misc] = None
        self._outside_bid: Optional[str] = None

    # ── сторінки ───────────────────────────────────────────────────────────
    def show_root(self, model: str, effort_key: str, models: list[str] | None = None) -> None:
        """Головна картка: модель і зусилля."""
        self.page = "root"
        self.current_model = model or ""
        self.current_effort = effort.normalise(effort_key)
        if models:
            self.models = list(models)
        self._clear()
        self._add_row("Модель", self.current_model or "не вибрана", "›",
                      lambda: self.show_models())
        # Зусилля показуємо завжди: рівень «Без міркувань» має сенс і для
        # моделей без reasoning — він вимикає зайві міркування, якщо вони є.
        # Раніше тут стояло ``effort.is_reasoning_provider("") or True`` —
        # умова завжди істинна, тобто від моделі нічого не залежало.
        self._add_row("Зусилля", effort.label_for(self.current_effort), "›",
                      lambda: self.show_efforts())
        self.header.configure(text="Модель застосовується лише до цієї розмови")

    def show_models(self) -> None:
        """Список моделей."""
        self.page = "models"
        self._clear()
        if not self.models:
            self._add_row("Немає доступних моделей", "перевір ключ", "",
                          lambda: None)
            self.header.configure(text="Натисни ⟳ у рядку моделі, щоб оновити список")
            return
        for name in self.models:
            mark = "✓" if name == self.current_model else ""
            self._add_row(name, "", mark, lambda n=name: self._pick_model(n))
        self.header.configure(text="↑↓ вибір, Enter застосувати, Esc назад")

    def show_efforts(self) -> None:
        """Список рівнів зусилля."""
        self.page = "efforts"
        self._clear()
        for level in sorted(effort.EFFORTS, key=lambda item: item.order):
            mark = "✓" if level.key == self.current_effort else ""
            self._add_row(level.label, level.hint, mark,
                          lambda k=level.key: self._pick_effort(k))
        self.header.configure(text="Зусилля діє для reasoning-моделей")

    # ── вибір ──────────────────────────────────────────────────────────────
    def _pick_model(self, name: str) -> None:
        self.current_model = name
        if self.on_pick_model is not None:
            self.on_pick_model(name)
        self.show_root(self.current_model, self.current_effort, self.models)
        self._maybe_close_after_pick()

    def _pick_effort(self, key: str) -> None:
        self.current_effort = effort.normalise(key)
        if self.on_pick_effort is not None:
            self.on_pick_effort(self.current_effort)
        self.show_root(self.current_model, self.current_effort, self.models)
        self._maybe_close_after_pick()

    def _maybe_close_after_pick(self) -> None:
        # Повертаємось на головну картку — користувач бачить результат.
        try:
            self.place_above(self._anchor)  # type: ignore[attr-defined]
        except (tk.TclError, AttributeError):
            pass

    # ── малювання ──────────────────────────────────────────────────────────
    def _clear(self) -> None:
        for row in self._rows:
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()
        self._tip_rows.clear()

    def _add_row(self, title: str, value: str, mark: str,
                 command: Callable[[], None]) -> None:
        row = tk.Frame(self.rows_host, bg=theme.BG_CARD, height=ROW_HEIGHT, cursor="hand2")
        row.pack(fill="x", padx=6, pady=1)
        row.columnconfigure(0, weight=1)

        name = tk.Label(row, text=title, bg=theme.BG_CARD, fg=theme.FG,
                        font=("Segoe UI", 9, "bold"), anchor="w")
        name.grid(row=0, column=0, sticky="w", padx=(8, 6), pady=6)

        value_label = tk.Label(row, text=value, bg=theme.BG_CARD, fg=theme.FG_DIM,
                               font=("Segoe UI", 9), anchor="e")
        value_label.grid(row=0, column=1, sticky="e", padx=(0, 6))

        mark_label = tk.Label(row, text=mark, bg=theme.BG_CARD, fg=theme.FG_FAINT,
                              font=("Segoe UI", 9), width=2)
        mark_label.grid(row=0, column=2, sticky="e", padx=(0, 6))

        labels = (name, value_label, mark_label)

        def enter(_e=None):
            for widget in (row, *labels):
                widget.configure(bg=theme.BG_HOVER)
            name.configure(fg=theme.FG_BRIGHT)

        def leave(_e=None):
            for widget in (row, *labels):
                widget.configure(bg=theme.BG_CARD)
            name.configure(fg=theme.FG)

        for widget in (row, *labels):
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
            widget.bind("<Button-1>", lambda _e: command())
        self._rows.append(row)
        self._tip_rows.append((name, title, value))

    # ── клавіатура ─────────────────────────────────────────────────────────
    def move(self, step: int) -> str:
        if not self._rows:
            return "break"
        self._selected = (getattr(self, "_selected", -1) + step) % len(self._rows)
        for index, row in enumerate(self._rows):
            bg = theme.BG_ACTIVE if index == self._selected else theme.BG_CARD
            row.configure(bg=bg)
            for widget in row.winfo_children():
                widget.configure(bg=bg)
        return "break"

    def choose(self) -> str:
        index = getattr(self, "_selected", -1)
        if 0 <= index < len(self._rows):
            row = self._rows[index]
            for widget in row.winfo_children():
                if widget.winfo_class() == "Label" and widget.bind("<Button-1>"):
                    break
            # Викликаємо прив'язану дію через подію рядка.
            row.event_generate("<Button-1>")
        return "break"

    def back(self) -> str:
        if self.page == "root":
            self.close()
        else:
            self.show_root(self.current_model, self.current_effort, self.models)
            self._maybe_close_after_pick()
        return "break"

    def close(self) -> None:
        self._unbind_outside_close()
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
        self._anchor = widget
        try:
            self.deiconify()
            self.update_idletasks()
            width = max(320, widget.winfo_width())
            height = max(90, self.winfo_reqheight())
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() - height - 6
            if y < 0:
                y = widget.winfo_rooty() + widget.winfo_height() + 6
            # Не даємо картці виїхати за межі екрана (другий монітор, край).
            x, y = widgets.clamp_to_screen(self, x, y, width, height)
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.update_idletasks()
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.lift()
            # Клік поза карткою має її закривати. Без цього вона лишалась
            # висіти поверх чату й перекривала текст (перевірено на вікні
            # 1600x1000: картка «Модель/Зусилля» затуляла транскрипт).
            self._bind_outside_close()
        except tk.TclError:
            return

    # ── закриття кліком поза карткою ───────────────────────────────────────
    def _bind_outside_close(self) -> None:
        """Слухати кліки в застосунку й закривати картку при кліку ззовні."""
        if self._outside_bid is not None:
            return
        root = self.winfo_toplevel()
        try:
            self._outside_bid = root.bind("<Button-1>", self._on_any_click, add="+")
        except tk.TclError:
            self._outside_bid = None

    def _on_any_click(self, event: tk.Event) -> None:
        """Клік поза межами картки закриває її."""
        if not self.visible:
            return
        try:
            under = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            under = None
        if under is None:
            self.close()
            return
        # Клік усередині самої картки (або її нащадка) не закриває.
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


__all__ = ["ModelMenu"]
