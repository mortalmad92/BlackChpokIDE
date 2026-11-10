"""Спливне меню «режим чату»: автономний і автоматизації — належать сесії.

Раніше «Автономний» і «Автоматизації» стояли окремими пунктами лівого меню.
Через це виникало дві проблеми:

* **немає власника.** Режим і черга живуть у проєкті й чаті, а пункт меню
  ні до чого не прив'язаний — тому задачі лишались «сиротами» після
  видалення чату;
* **немає теки.** Автономний режим для проєкту показувався поруч зі
  звичайними розділами, хоч він потребує вибраного проєкту.

Тепер це одна кнопка в заголовку сесії — вона й показує, до якого чату й
якої теки належать режим і черга:

    ┌──────────────────────────────────────────────────────┐
    │ РЕЖИМ ЧАТУ                                           │
    │ ∞  Автономний                вимкнено           ›    │
    │ ≡  Автоматизації             3 задачі           ›    │
    │ ───────────────────────────────────────────────────  │
    │ ◎  Чат        Новий чат                              │
    │ 🗂  Проєкт     blackchpock_ai                        │
    └──────────────────────────────────────────────────────┘

Пункт «Автономний» відкриває підменю зі станом і кнопкою старту/зупинки;
«Автоматизації» — панель черги й скілів. Усе інше (що саме робити) робить
оболонка через колбеки — цей модуль нічого не вирішує сам.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import theme, widgets

ROW_HEIGHT = 46


class ChatModeMenu(tk.Toplevel):
    """Меню режимів, прив'язаних до поточного чату й проєкту."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        chat_title: str = "",
        project: str = "",
        autonomous_on: bool = False,
        autonomous_state: str = "",
        queue_count: int = 0,
        on_autonomous: Optional[Callable[[], None]] = None,
        on_automations: Optional[Callable[[], None]] = None,
        on_pick_project: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.chat_title = chat_title
        self.project = project
        self.autonomous_on = bool(autonomous_on)
        self.autonomous_state = autonomous_state or ""
        self.queue_count = int(queue_count or 0)
        self.on_autonomous = on_autonomous
        self.on_automations = on_automations
        self.on_pick_project = on_pick_project
        self._rows: list[tk.Frame] = []

        self.withdraw()
        self.overrideredirect(True)
        widgets.register_popover(self)
        self.configure(bg=theme.BORDER_SOFT)
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ELEVATED, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        tk.Label(body, text="РЕЖИМ ЧАТУ", bg=theme.BG_ELEVATED, fg=theme.FG_FAINT,
                 font=self.fonts.ui_tiny, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(8, 4))

        host = tk.Frame(body, bg=theme.BG_ELEVATED)
        host.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        host.columnconfigure(0, weight=1)

        self._row(host, "∞", "Автономний",
                  self._autonomous_note(), self._autonomous,
                  accent=self.autonomous_on)
        self._row(host, "≡", "Автоматизації",
                  self._automations_note(), self._automations)

        tk.Frame(body, bg=theme.BORDER, height=1).grid(
            row=2, column=0, sticky="ew", padx=10, pady=4)

        # Підпис контексту: до чого саме належать режими вище.
        context = tk.Frame(body, bg=theme.BG_ELEVATED)
        context.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        context.columnconfigure(1, weight=1)

        tk.Label(context, text="◎", bg=theme.BG_ELEVATED, fg=theme.FG_FAINT,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        tk.Label(context, text=self.chat_title or "Новий чат",
                 bg=theme.BG_ELEVATED, fg=theme.FG_DIM, font=("Segoe UI", 8),
                 anchor="w").grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.project_label = widgets.HoverLabel(
            context, text=self._project_text(), command=self._pick_project,
            bg=theme.BG_ELEVATED, fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=("Segoe UI", 8), padx=0, pady=0,
            anchor="w")
        self.project_label.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(2, 0))
        widgets.Tip(self.project_label, "Тека проєкту: режим і черга працюють лише в ній")

    def _project_text(self) -> str:
        return f"🗂 {self.project}" if self.project else "🗂 теку не обрано"

    def _autonomous_note(self) -> str:
        if self.autonomous_on:
            return "працює" + (f" · {self.autonomous_state}" if self.autonomous_state else "")
        return "вимкнено"

    def _automations_note(self) -> str:
        if self.queue_count == 1:
            return "1 задача в черзі"
        if self.queue_count > 1:
            return f"{self.queue_count} задач у черзі"
        return "черга порожня"

    def _row(self, host: tk.Misc, icon: str, title: str, note: str,
             command: Callable[[], None], *, accent: bool = False) -> tk.Frame:
        bg = theme.BG_ELEVATED
        row = tk.Frame(host, bg=bg, cursor="hand2", height=ROW_HEIGHT)
        row.pack(fill="x", pady=1)
        row.columnconfigure(1, weight=1)

        icon_label = tk.Label(row, text=icon, bg=bg,
                              fg=theme.SUCCESS if accent else theme.FG_DIM,
                              font=("Segoe UI", 12), width=2, anchor="center")
        icon_label.grid(row=0, column=0, rowspan=2, padx=(8, 4), pady=6)

        title_label = tk.Label(row, text=title, bg=bg,
                               fg=theme.FG_BRIGHT if accent else theme.FG,
                               font=("Segoe UI", 9, "bold"), anchor="w")
        title_label.grid(row=0, column=1, sticky="ew", pady=(6, 0))

        note_label = tk.Label(row, text=note, bg=bg, fg=theme.FG_FAINT,
                              font=("Segoe UI", 8), anchor="w")
        note_label.grid(row=1, column=1, sticky="ew", pady=(0, 6))

        arrow = tk.Label(row, text="›", bg=bg, fg=theme.FG_FAINT,
                         font=("Segoe UI", 11))
        arrow.grid(row=0, column=2, rowspan=2, padx=(4, 10))

        self._rows.append(row)

        def enter(_e=None) -> None:
            for widget in (row, icon_label, title_label, note_label, arrow):
                widget.configure(bg=theme.BG_HOVER)

        def leave(_e=None) -> None:
            for widget in (row, icon_label, title_label, note_label, arrow):
                widget.configure(bg=bg)

        def click(_e=None) -> None:
            self.hide()
            command()

        for widget in (row, icon_label, title_label, note_label, arrow):
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
            widget.bind("<Button-1>", click)
        return row

    # ── дії ────────────────────────────────────────────────────────────────
    def _autonomous(self) -> None:
        if self.on_autonomous is not None:
            self.on_autonomous()

    def _automations(self) -> None:
        if self.on_automations is not None:
            self.on_automations()

    def _pick_project(self) -> None:
        if self.on_pick_project is not None:
            self.on_pick_project()

    # ── показ ──────────────────────────────────────────────────────────────
    def show_at(self, anchor: tk.Misc) -> None:
        """Показати під віджетом (кнопкою в заголовку сесії)."""
        try:
            # Спершу показуємо, щоб Tk обчислив СПРАВЖНЮ ширину картки:
            # інакше береться оцінка, і меню виходить за правий край екрана
            # (на скріншоті обрізались підписи «Автоматизації»).
            self.deiconify()
            self.update_idletasks()
            width = max(280, self.winfo_reqwidth())
            height = max(80, self.winfo_reqheight())
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 4
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            # Притискаємо до екрана з обох боків.
            if x + width > screen_w - 8:
                x = max(8, screen_w - width - 8)
            x = max(8, x)
            # І не даємо вийти за нижній край.
            if y + height > screen_h - 8:
                y = max(8, screen_h - height - 8)
            self.wm_geometry(f"{width}x{height}+{x}+{y}")
            self.lift()
        except tk.TclError:
            return

    def hide(self) -> None:
        try:
            self.withdraw()
        except tk.TclError:
            pass


__all__ = ["ChatModeMenu"]
