"""Селектор моделей і провайдерів — спливна картка над композером.

Показує те, чого немає в жодному іншому місці: **звідки** береться модель.

    ┌──────────────────────────────────────────────────────┐
    │ ⟳ Перевірити   Локальні · Ollama · 3 моделі          │
    │ ┌ пошук ───────────────────────────────────────────┐ │
    │ └──────────────────────────────────────────────────┘ │
    │ ЛОКАЛЬНІ                                             │
    │ ● qwen2.5-coder-7b   Ollama · локально · 7B · 32K ✓  │
    │ ○ llama-3.2-3b       LM Studio · офлайн · 3B · —     │
    │ ХМАРНІ · необов'язково                               │
    │ ○ deepseek-reasoner  DeepSeek · хмара · 64K          │
    └──────────────────────────────────────────────────────┘

Статус доступності — це реальний результат ``GET /models`` відповідного
сервера, а не припущення. Невідомі характеристики показуються як «—».
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Optional

from . import providers, theme, widgets

ROW_PAD_X = 10
ROW_PAD_Y = 5
MAX_VISIBLE_ROWS = 11

# ── Розміри тексту в списку моделей ────────────────────────────────────────
#
# Було 7–9 pt: назву моделі й підпис провайдера доводилось роздивлятись.
# Користувач просив «хаб моделей має бути видно велика іконка, і там де
# вибираю моделі теж». Тепер назва 12 pt, метадані 9 pt.
ROW_FONT = "Segoe UI"
ROW_NAME_SIZE = 12
ROW_META_SIZE = 9
ROW_DOT_SIZE = 11


class ModelSelector(tk.Toplevel):
    """Спливна картка вибору провайдера та моделі."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        settings: Any,
        *,
        on_pick: Optional[Callable[[providers.ModelEntry], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_manage: Optional[Callable[[], None]] = None,
        on_delete: Optional[Callable[[providers.ModelEntry], None]] = None,
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.settings = settings
        self.on_pick = on_pick
        self.on_refresh = on_refresh
        self.on_manage = on_manage
        self.on_delete = on_delete
        self.entries: list[providers.ModelEntry] = []
        self.query = ""
        self._rows: list[tk.Frame] = []
        self._anchor: Optional[tk.Misc] = None
        self._selected = -1
        #: True, поки картка має бути на екрані (гасить відкладені перерахунки).
        self._open = False
        self._resize_job: Optional[str] = None
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=theme.BORDER_SOFT)
        self._build()
        # Реєструємо як спливне вікно: модальний діалог закриє його сам,
        # інакше картка лишається поверх «Налаштувань».
        widgets.register_popover(self)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ELEVATED, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        self.body = body

        head = tk.Frame(body, bg=theme.BG_ELEVATED)
        head.grid(row=0, column=0, sticky="ew", padx=(ROW_PAD_X, 6), pady=(8, 4))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="Модель", bg=theme.BG_ELEVATED, fg=theme.FG_BRIGHT,
                 font=self.fonts.ui_bold, anchor="w").grid(row=0, column=0, sticky="w")

        self.summary = tk.Label(head, text="", bg=theme.BG_ELEVATED, fg=theme.FG_FAINT,
                                font=("Segoe UI", 8), anchor="e")
        self.summary.grid(row=0, column=1, sticky="e", padx=(8, 6))

        widgets.IconButton(head, "⟳", self._refresh, bg=theme.BG_ELEVATED, fg=theme.FG_DIM,
                           font=("Segoe UI", 10), tooltip="Перевірити сервери").grid(row=0, column=2)
        widgets.IconButton(head, "⚙", self._manage, bg=theme.BG_ELEVATED, fg=theme.FG_DIM,
                           font=("Segoe UI", 10), tooltip="Провайдери й ключі").grid(
            row=0, column=3, padx=(2, 0))

        # пошук
        search = tk.Frame(body, bg=theme.BG_INPUT)
        search.grid(row=1, column=0, sticky="ew", padx=ROW_PAD_X, pady=(0, 6))
        search.columnconfigure(0, weight=1)
        self.search = tk.Entry(
            search, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 9),
        )
        self.search.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=4)
        self.search.bind("<KeyRelease>", self._on_search)
        self.search.bind("<Return>", lambda _e: self.choose())
        self.search.bind("<Down>", lambda _e: self.move(1))
        self.search.bind("<Up>", lambda _e: self.move(-1))
        self.search.bind("<Escape>", lambda _e: self.close())

        holder = tk.Frame(body, bg=theme.BG_ELEVATED)
        holder.grid(row=2, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        self.scroll = widgets.ScrollFrame(holder, bg=theme.BG_ELEVATED)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.rows_host = self.scroll.inner
        self.rows_host.columnconfigure(0, weight=1)

        footer = tk.Frame(body, bg=theme.BG_ELEVATED)
        footer.grid(row=3, column=0, sticky="ew", padx=ROW_PAD_X, pady=(4, 8))
        tk.Label(footer, text="локальні моделі працюють без API-ключа",
                 bg=theme.BG_ELEVATED, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                 anchor="w").pack(side="left")

    # ── дані ───────────────────────────────────────────────────────────────
    def set_entries(self, entries: list[providers.ModelEntry], *, summary: str = "") -> None:
        self.entries = list(entries)
        if summary:
            self.summary.configure(text=summary)
        self.render()

    def _on_search(self, _event=None) -> None:
        try:
            self.query = self.search.get().strip()
        except tk.TclError:
            return
        self.render(reset_selection=True)

    def render(self, *, reset_selection: bool = False) -> None:
        for row in self._rows:
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()
        if reset_selection:
            self._selected = -1

        visible = [entry for entry in self.entries if entry.matches(self.query)]
        if not visible:
            tk.Label(self.rows_host, text="Нічого не знайдено.\n"
                                          "Перевір сервери (⟳) або обери локальний GGUF у хабі.",
                     bg=theme.BG_ELEVATED, fg=theme.FG_FAINT, font=("Segoe UI", 9),
                     justify="left", anchor="w").pack(fill="x", padx=ROW_PAD_X, pady=12)
            self._resize()
            return

        current_name = (getattr(self.settings.llm, "model", "") or "").strip()
        groups: dict[str, list[providers.ModelEntry]] = {}
        for entry in visible:
            title = "ЛОКАЛЬНІ" if entry.is_local else "ХМАРНІ · необов'язково"
            groups.setdefault(title, []).append(entry)

        for title, items in groups.items():
            head = widgets.SectionTitle(self.rows_host, f"{title} · {len(items)}",
                                        bg=theme.BG_ELEVATED, fg=theme.FG_FAINT,
                                        font=self.fonts.ui_tiny)
            head.pack(fill="x")
            self._rows.append(head)
            for entry in items:
                self._row(entry, active=entry.name == current_name)

        if 0 <= self._selected < len(self._rows):
            self._paint_selection()
        self._resize()

    def _row(self, entry: providers.ModelEntry, *, active: bool) -> None:
        bg = theme.BG_ACTIVE if active else theme.BG_ELEVATED
        row = tk.Frame(self.rows_host, bg=bg, cursor="hand2", bd=0, highlightthickness=0)
        row.pack(fill="x", padx=4, pady=2)
        row.columnconfigure(1, weight=1)

        dot_colour = theme.SUCCESS if entry.online else (
            theme.FG_FAINT if not entry.is_local else theme.ERROR)
        # Розміри збільшено: користувач скаржився, що «поки знайду модель,
        # це займає багато часу» — дрібний текст 7–9 pt цьому й заважав.
        dot = tk.Label(row, text="●", bg=bg, fg=dot_colour,
                       font=(ROW_FONT, ROW_DOT_SIZE))
        dot.grid(row=0, column=0, rowspan=2, padx=(8, 8), pady=(ROW_PAD_Y, ROW_PAD_Y))

        name = tk.Label(row, text=entry.name, bg=bg,
                        fg=theme.FG_BRIGHT if active else theme.FG,
                        font=(ROW_FONT, ROW_NAME_SIZE), anchor="w")
        name.grid(row=0, column=1, sticky="ew", pady=(ROW_PAD_Y, 0))

        if active:
            tk.Label(row, text="✓", bg=bg, fg=theme.ACCENT,
                     font=(ROW_FONT, ROW_NAME_SIZE, "bold")).grid(
                row=0, column=2, padx=(4, 4))

        forget = None
        if entry.path and str(entry.path).lower().endswith(".gguf"):
            forget = tk.Label(row, text="×", bg=bg, fg=theme.FG_FAINT,
                              font=(ROW_FONT, ROW_NAME_SIZE), cursor="hand2")
            forget.grid(row=0, column=3, padx=(0, 8))
            widgets.Tip(forget, "Видалити зі списку і з диска")
            forget.bind("<Button-1>", lambda _event, item=entry: self._delete(item))

        meta = tk.Label(row, text=entry.meta_text, bg=bg, fg=theme.FG_DIM,
                        font=(ROW_FONT, ROW_META_SIZE), anchor="w")
        meta.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(0, ROW_PAD_Y))

        labels = (dot, name, meta)
        for widget in (row, *labels):
            widget.bind("<Enter>", lambda _e, r=row: self._hover(r, True))
            widget.bind("<Leave>", lambda _e, r=row: self._hover(r, False))
            widget.bind("<Button-1>", lambda _e, item=entry: self._pick(item))
        row.entry = entry  # type: ignore[attr-defined]
        self._rows.append(row)

    def _hover(self, row: tk.Frame, enter: bool) -> None:
        if not hasattr(row, "entry"):
            return
        colour = theme.BG_HOVER if enter else theme.BG_ELEVATED
        try:
            row.configure(bg=colour)
            for child in row.winfo_children():
                if isinstance(child, tk.Label) and child.cget("fg") != theme.ACCENT:
                    child.configure(bg=colour)
        except tk.TclError:
            pass

    # ── вибір ──────────────────────────────────────────────────────────────
    def _pick(self, entry: providers.ModelEntry) -> None:
        if self.on_pick is not None:
            self.on_pick(entry)
        self.close()

    def _delete(self, entry: providers.ModelEntry) -> None:
        """Хрестик не вибирає модель: лише просить оболонку її видалити."""
        if self.on_delete is not None:
            self.on_delete(entry)

    def _refresh(self) -> None:
        if self.on_refresh is not None:
            self.on_refresh()

    def _manage(self) -> None:
        self.close()
        if self.on_manage is not None:
            self.on_manage()

    def move(self, step: int) -> str:
        selectable = [row for row in self._rows if hasattr(row, "entry")]
        if not selectable:
            return "break"
        self._selected = (self._selected + step) % len(selectable)
        self._paint_selection()
        return "break"

    def _paint_selection(self) -> None:
        selectable = [row for row in self._rows if hasattr(row, "entry")]
        for index, row in enumerate(selectable):
            self._hover(row, index == self._selected)

    def choose(self) -> str:
        selectable = [row for row in self._rows if hasattr(row, "entry")]
        if 0 <= self._selected < len(selectable):
            self._pick(selectable[self._selected].entry)  # type: ignore[attr-defined]
        return "break"

    # ── геометрія ──────────────────────────────────────────────────────────
    def _resize(self) -> None:
        """Підігнати розмір і позицію під вміст, не виходячи за екран."""
        self._resize_job = None
        if not getattr(self, "_open", False):
            return          # картку закрили — не повертаємо її на екран
        try:
            self.update_idletasks()
            rows = len([row for row in self._rows if hasattr(row, "entry")])
            heads = len(self._rows) - rows
            content = 150 + heads * 24 + rows * 44
            anchor = self._anchor
            width = 460
            if anchor is not None and anchor.winfo_exists():
                width = max(440, min(560, anchor.winfo_width() or 440))
            screen_h = self.winfo_screenheight()
            height = max(170, min(content, int(screen_h * 0.62)))
            if anchor is not None and anchor.winfo_exists():
                x = anchor.winfo_rootx()
                y = anchor.winfo_rooty() - height - 8
                if y < 20:
                    y = anchor.winfo_rooty() + anchor.winfo_height() + 8
                # Межі екрана, а не лише вікна IDE: інакше картка виїжджає
                # за край монітора й кнопки стають недосяжними.
                x, y = widgets.clamp_to_screen(self, x, y, width, height)
                self.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
            else:
                x, y = widgets.clamp_to_screen(
                    self,
                    (self.winfo_screenwidth() - width) // 2,
                    (self.winfo_screenheight() - height) // 2,
                    width, height)
                self.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            return

    def show_above(self, widget: tk.Misc) -> None:
        """Показати картку над віджетом-якорем."""
        self._anchor = widget
        self._open = True
        try:
            self.deiconify()
            self.update_idletasks()
            # Геометрію задаємо ПІСЛЯ того, як вікно з'явилось: до першого
            # мапінгу Tk перезаписує позицію своїм типовим місцем (0,0).
            self._resize()
            self._resize_job = self.after(30, self._resize)
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.lift()
            self.search.focus_set()
        except tk.TclError:
            return

    def close(self) -> None:
        """Сховати картку й скасувати відкладені перерахунки.

        Без скасування ``after_idle(self._resize)`` повертав вікно на екран
        ПІСЛЯ закриття: картка «Модель» знову з'являлась поверх діалогу
        «Налаштування» — саме те, що видно на скріншоті.
        """
        self._open = False
        self._anchor = None
        try:
            self.withdraw()
        except tk.TclError:
            return
        try:
            self.after_cancel(self._resize_job) if getattr(self, "_resize_job", None) else None
        except (tk.TclError, ValueError):
            pass
        self._resize_job = None

    @property
    def visible(self) -> bool:
        try:
            return bool(self.winfo_viewable())
        except tk.TclError:
            return False


__all__ = ["ModelSelector"]
