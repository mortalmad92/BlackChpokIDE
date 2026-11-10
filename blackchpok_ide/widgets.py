"""Дрібні віджети сучасного інтерфейсу: пігулки, картки, прокрутка, меню.

Усе зібрано в одному місці, щоб панелі не дублювали однакові конструкції
й поводились з наведенням, фокусом і прокруткою однаково.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, Optional

from . import theme


# ─────────────────────────────────────────────────────────────────────────────
# Кнопки
# ─────────────────────────────────────────────────────────────────────────────

class HoverLabel(tk.Label):
    """Підпис, який підсвічується під курсором і вміє «натискатись».

    tk.Label обрано навмисно: ttk-кнопки на Windows малюють зайвий бордюр і
    не дозволяють вільно керувати фоном, а пігулки в дизайні — плоскі.
    """

    def __init__(
        self,
        master: tk.Misc,
        text: str = "",
        command: Optional[Callable[[], None]] = None,
        *,
        bg: str = theme.BG_ALT,
        fg: str = theme.FG_DIM,
        hover_bg: str = theme.BG_HOVER,
        hover_fg: str = theme.FG_BRIGHT,
        active_bg: str = "",
        active_fg: str = "",
        font=None,
        padx: int = 8,
        pady: int = 3,
        anchor: str = "w",
        **kwargs,
    ) -> None:
        if font is None:
            font = ("Segoe UI", 9)
        super().__init__(master, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady,
                         anchor=anchor, bd=0, highlightthickness=0, cursor="hand2", **kwargs)
        # Кольори кешуються як РОЛІ палітри (ключі теми), а не лише значення:
        # після перемикання light/dark наведення бере актуальний колір теми,
        # і світла плашка в темному режимі не спливає.
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._hover_fg = hover_fg
        self._active_bg = active_bg
        self._active_fg = active_fg
        self._role_bg = theme.role_of(bg)
        self._role_fg = theme.role_of(fg)
        self._role_hover_bg = theme.role_of(hover_bg)
        self._role_hover_fg = theme.role_of(hover_fg)
        self._role_active_bg = theme.role_of(active_bg)
        self._role_active_fg = theme.role_of(active_fg)
        self._command = command
        self._active = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ── актуальні кольори ──────────────────────────────────────────────────
    def _colours(self) -> tuple[str, str, str, str, str, str]:
        """(bg, fg, hover_bg, hover_fg, active_bg, active_fg) з поточної теми.

        Колір, переданий конструктору, запам'ятовується роллю (ключем
        палітри, напр. ``BG_INPUT``) і розв'язується в актуальне значення
        щоразу під час наведення. Невідомі кольори лишаються як є.
        """
        bg = theme.value_of(self._role_bg, self._bg)
        fg = theme.value_of(self._role_fg, self._fg)
        hover_bg = theme.value_of(self._role_hover_bg, self._hover_bg)
        hover_fg = theme.value_of(self._role_hover_fg, self._hover_fg)
        active_bg = theme.value_of(self._role_active_bg, self._active_bg)
        active_fg = theme.value_of(self._role_active_fg, self._active_fg)
        return bg, fg, hover_bg, hover_fg, active_bg, active_fg

    def set_command(self, command: Optional[Callable[[], None]]) -> None:
        self._command = command

    def set_active(self, active: bool) -> None:
        self._active = active
        bg, fg, _hover_bg, _hover_fg, active_bg, active_fg = self._colours()
        super().configure(bg=active_bg if active else bg,
                          fg=active_fg if active else fg)

    def _on_enter(self, _event=None) -> None:
        if not self._active:
            _bg, _fg, hover_bg, hover_fg, _a_bg, _a_fg = self._colours()
            super().configure(bg=hover_bg, fg=hover_fg)

    def _on_leave(self, _event=None) -> None:
        if not self._active:
            bg, fg, _hover_bg, _hover_fg, _a_bg, _a_fg = self._colours()
            super().configure(bg=bg, fg=fg)

    def _on_press(self, _event=None) -> None:
        if not self._active:
            _bg, _fg, hover_bg, _hover_fg, _a_bg, _a_fg = self._colours()
            super().configure(bg=hover_bg)

    def _on_release(self, _event=None) -> None:
        self._on_leave()
        if self._command is not None:
            self._command()


FG_ACTIVE_FG = theme.FG_BRIGHT


class Chip(HoverLabel):
    """Компактна пігулка дії (як «Send follow-up» у композері)."""

    def __init__(self, master: tk.Misc, text: str, command=None, *, font=None, **kwargs) -> None:
        super().__init__(
            master, text=text, command=command,
            bg=theme.BG_INPUT, fg=theme.FG, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT,
            font=font, padx=10, pady=4, anchor="center", **kwargs,
        )
        self.configure(relief="flat")


class IconButton(HoverLabel):
    """Квадратна кнопка-іконка (закрити вкладку, оновити, меню).

    Розмір типово 12 pt і ширина 3 символи: дрібні іконки 10 pt на
    високому екрані (150–200 % масштаб Windows) було важко націлити
    мишею — особливо «×» закриття чату й «🗑» видалення.
    """

    def __init__(self, master: tk.Misc, text: str, command=None, *, bg: str = theme.BG_ALT,
                 fg: str = theme.FG_DIM, size: int = 22, font=None, tooltip: str = "") -> None:
        super().__init__(master, text=text, command=command, bg=bg, fg=fg,
                         hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT,
                         font=font or ("Segoe UI", 12), padx=1, pady=1, anchor="center",
                         width=3, height=1)
        self._size = size
        self._tip = tooltip
        if tooltip:
            Tip(self, tooltip)


class Pill(tk.Frame):
    """Група кнопок-«сегментів» (наприклад Термінал / Пошук / Хаб)."""

    def __init__(self, master: tk.Misc, items: Iterable[tuple[str, Callable[[], None]]] = (),
                 *, bg: str = theme.BG_ALT) -> None:
        super().__init__(master, bg=bg)
        self._bg = bg
        self._buttons: dict[str, HoverLabel] = {}
        for text, command in items:
            self.add(text, command)

    def add(self, text: str, command: Callable[[], None]) -> HoverLabel:
        button = HoverLabel(self, text=text, command=command, bg=self._bg,
                            fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
                            active_bg=theme.BG_ACTIVE, active_fg=theme.FG_BRIGHT,
                            font=("Segoe UI", 9), padx=10, pady=4)
        button.pack(side="left", padx=(0, 2))
        self._buttons[text] = button
        return button

    def select(self, text: str) -> None:
        for key, button in self._buttons.items():
            button.set_active(key == text)


class Tip:
    """Підказка до віджета без зовнішніх бібліотек."""

    def __init__(self, widget: tk.Misc, text: str, delay: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after: Optional[str] = None
        self._win: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._after = None

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None

    def _show(self) -> None:
        if self._win is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 6
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        win = tk.Toplevel(self.widget)
        win.wm_overrideredirect(True)
        win.configure(bg=theme.BORDER_SOFT)
        label = tk.Label(win, text=self.text, bg=theme.BG_INPUT, fg=theme.FG,
                         font=("Segoe UI", 8), padx=8, pady=3, justify="left")
        label.pack(padx=1, pady=1)
        win.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        self._win = win

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None


# ─────────────────────────────────────────────────────────────────────────────
# Контейнери
# ─────────────────────────────────────────────────────────────────────────────

class Card(tk.Frame):
    """Блок із тонкою рамкою — основа карток повідомлень і панелей."""

    def __init__(self, master: tk.Misc, *, bg: str = theme.BG_CARD, border: str = theme.BORDER,
                 padding: int = 0, **kwargs) -> None:
        super().__init__(master, bg=border, bd=0, highlightthickness=0, **kwargs)
        self.body = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        if padding:
            self.inner = tk.Frame(self.body, bg=bg)
            self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)
        else:
            self.inner = self.body


class SectionHeader(tk.Frame):
    """Заголовок секції бічної панелі: підпис і дії праворуч."""

    def __init__(self, master: tk.Misc, text: str, *, bg: str = theme.BG_ALT, font=None) -> None:
        super().__init__(master, bg=bg)
        self.label = tk.Label(self, text=text.upper(), bg=bg, fg=theme.FG_FAINT,
                              font=font or ("Segoe UI", 8, "bold"), anchor="w")
        self.label.pack(side="left", padx=(12, 4), pady=(10, 4))
        self.actions = tk.Frame(self, bg=bg)
        self.actions.pack(side="right", padx=(0, 8), pady=(8, 2))

    def add_action(self, text: str, command: Callable[[], None], tooltip: str = "") -> IconButton:
        button = IconButton(self.actions, text, command, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                            font=("Segoe UI", 10), tooltip=tooltip)
        button.pack(side="right")
        return button


class Divider(tk.Frame):
    """Лінія на 1 px (горизонтальна або вертикальна).

    Віджет НЕ розміщує себе сам: батько вирішує, яким менеджером його
    поставити (``pack`` чи ``grid``), інакше всередині grid-контейнера
    ``pack`` падає з «grid is already managing its content windows».
    Виняток — зручний режим ``autopack=True`` для простих випадків.
    """

    def __init__(self, master: tk.Misc, *, colour: str = theme.BORDER, padx: int = 0,
                 orient: str = "horizontal", autopack: bool = True) -> None:
        if orient == "vertical":
            super().__init__(master, bg=colour, width=1, bd=0, highlightthickness=0)
            if autopack:
                self.pack(side="left", fill="y")
        else:
            super().__init__(master, bg=colour, height=1, bd=0, highlightthickness=0)
            if autopack:
                self.pack(fill="x", padx=padx)


class CenteredColumn(tk.Frame):
    """Колонка з максимальною шириною, відцентрована в батькові.

    Це ключовий примітив композиції: стрічка діалогу й композер живуть у
    колонці сталої комфортної ширини (``max_width``), а не розтягуються на
    весь екран. На вузькому вікні колонка просто займає всю ширину.

        host ┌──────────────────────────────┐
             │      ┌────────────────┐      │
             │      │    вміст       │      │  ← max_width
             │      └────────────────┘      │
             └──────────────────────────────┘
    """

    def __init__(self, master: tk.Misc, *, bg: str = theme.BG, max_width: int = 920,
                 gutter: int = 16, anchor: str = "center") -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self._bg = bg
        self.max_width = int(max_width or 0)
        self.gutter = int(gutter or 0)
        self.anchor = anchor
        self.columnconfigure(0, weight=1)
        #: Внутрішній контейнер — саме в ньому живе вміст.
        self.inner = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        self.inner.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._layout_after: Optional[str] = None
        self.bind("<Configure>", self._on_configure)

    def set_max_width(self, width: int) -> None:
        self.max_width = int(width or 0)
        self._relayout()

    def _on_configure(self, _event=None) -> None:
        # Перерахунок відкладений: під час ресайзу Tk сипле десятки подій.
        if self._layout_after is not None:
            return
        try:
            self._layout_after = self.after_idle(self._relayout)
        except tk.TclError:
            self._layout_after = None

    def _relayout(self) -> None:
        self._layout_after = None
        try:
            available = self.winfo_width()
        except tk.TclError:
            return
        if available <= 1 or self._layout_after is not None:
            return
        width = max(0, available - 2 * self.gutter)
        if self.max_width > 0:
            width = min(width, self.max_width)
        if self.anchor == "left":
            left = self.gutter
            right = max(self.gutter, available - width - self.gutter)
        else:
            left = right = max(self.gutter, (available - width) // 2)
        try:
            self.columnconfigure(0, weight=0, minsize=left)
            self.columnconfigure(1, weight=1)
            self.columnconfigure(2, weight=0, minsize=right)
            self.inner.grid_configure(row=0, column=1, rowspan=3, sticky="nsew")
        except tk.TclError:
            return


class SectionTitle(tk.Frame):
    """Заголовок групи в списку (селектор моделей, MCP, RAG)."""

    def __init__(self, master: tk.Misc, text: str, *, bg: str = theme.BG_CARD,
                 fg: str = theme.FG_FAINT, font=None) -> None:
        super().__init__(master, bg=bg)
        self.label = tk.Label(self, text=text.upper(), bg=bg, fg=fg,
                              font=font or ("Segoe UI", 8, "bold"), anchor="w")
        self.label.pack(side="left", padx=(10, 6), pady=(8, 4))
        self.actions = tk.Frame(self, bg=bg)
        self.actions.pack(side="right", padx=(0, 8), pady=(6, 2))


class ScrollFrame(ttk.Frame):
    """Прокручуваний контейнер: усередині звичайний Frame для вмісту.

    ``max_content_width`` обмежує ширину вмісту й центрує його: саме так
    довга розмова не розповзається на весь широкий монітор. Коли межа не
    задана (0), вміст займає всю ширину полотна.
    """

    #: Межа координат Canvas у Tk. Понад неї вміст НЕ малюється — полотно
    #: лишається порожнім, хоч ``scrollregion`` і ``bbox`` рапортують вміст.
    #: Саме це робило довгу історію чату «зникаючою» внизу.
    MAX_CANVAS_HEIGHT = 20000

    def __init__(self, master: tk.Misc, *, bg: str = theme.BG_ALT,
                 max_content_width: int = 0, gutter: int = 0, **kwargs) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._bg = bg
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0, takefocus=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self._bind_wheel(True))
        self.canvas.bind("<Leave>", lambda _e: self._bind_wheel(False))
        self.hide_scrollbar_when_needed = True
        #: 0 = без обмеження; інакше максимальна ширина вмісту в пікселях.
        self.max_content_width = int(max_content_width or 0)
        #: Мінімальні поля з боків, коли вміст уже вужчий за полотно.
        self.gutter = int(gutter or 0)

    def _bind_wheel(self, active: bool) -> None:
        if active:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        try:
            if self.inner.winfo_height() <= self.canvas.winfo_height():
                return
            self.canvas.yview_scroll(int(-event.delta / 120) or -1, "units")
        except tk.TclError:
            return

    def _on_inner_configure(self, _event=None) -> None:
        """Вміст змінив розмір — перерахувати область прокрутки.

        ВАЖЛИВО про «зависання». ``sync_scrollregion`` робить
        ``update_idletasks()`` — повний перерахунок розкладки Tk. На старті
        вікна подія ``<Configure>`` приходить десятки разів (кожна картка,
        кожен підпис), і кожна тягнула повний перерахунок: заміряно
        профілером — 47 викликів і 0.5 с застигання інтерфейсу.

        Тепер перерахунок ЗЛИВАЄТЬСЯ: скільки б подій не прийшло, робота
        виконується один раз, коли Tk відпочине.
        """
        if getattr(self, "_scroll_sync_pending", False):
            return
        self._scroll_sync_pending = True
        try:
            self.after_idle(self._do_sync_scrollregion)
        except tk.TclError:
            self._scroll_sync_pending = False

    def _do_sync_scrollregion(self) -> None:
        """Один відкладений перерахунок області прокрутки."""
        self._scroll_sync_pending = False
        self.sync_scrollregion()

    def sync_scrollregion(self) -> None:
        """Перерахувати область прокрутки під поточний вміст.

        Полотно тримає висоту вікна-елемента з моменту, коли вміст був
        найдовшим: після ``destroy()`` дочірніх карток ``bbox("all")`` уже
        менший, але сам елемент лишається високим. Якщо вірити лише
        ``bbox``, область прокрутки лишається завеликою — і коротка
        розмова, відкрита після довгої, показує порожній екран. Тому
        висоту елемента вирівнюємо за ``winfo_reqheight()`` вмісту.
        """
        try:
            self.inner.update_idletasks()
            wanted = self.inner.winfo_reqheight()
            if wanted > 0 and self.canvas.itemcget(self._window, "height") != str(wanted):
                self.canvas.itemconfigure(self._window, height=wanted)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            return

    def content_width(self, available: int) -> int:
        """Ширина вмісту для заданої ширини полотна (з урахуванням межі)."""
        width = max(0, int(available) - 2 * self.gutter)
        if self.max_content_width > 0:
            width = min(width, self.max_content_width)
        return max(0, width)

    def _on_canvas_configure(self, event) -> None:
        width = self.content_width(event.width)
        if self.max_content_width > 0:
            x = max(0, (event.width - width) // 2)
            self.canvas.coords(self._window, x, 0)
            self.canvas.itemconfigure(self._window, width=width)
        else:
            self.canvas.coords(self._window, 0, 0)
            self.canvas.itemconfigure(self._window, width=event.width)

    def _on_scroll(self, first: str, last: str) -> None:
        if self.hide_scrollbar_when_needed:
            empty = float(first) <= 0.0 and float(last) >= 1.0
            if empty:
                self.scroll.grid_remove()
            else:
                self.scroll.grid()
            # Коли смуга з'являється або зникає, ширина полотна міняється —
            # без перерахунку вмісту лишалась «мертва» смуга праворуч:
            # canvas 1047, а вміст 776 px (перевірено).
            try:
                self.canvas.update_idletasks()
                self._on_canvas_configure(
                    type("_E", (), {"width": self.canvas.winfo_width()})())
            except (tk.TclError, AttributeError):
                pass
        self.scroll.set(first, last)

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self.sync_scrollregion()

    def scroll_to_end(self) -> None:
        try:
            self.sync_scrollregion()
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1.0)
        except tk.TclError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Меню
# ─────────────────────────────────────────────────────────────────────────────

def context_menu(master: tk.Misc, items: Iterable[tuple[str, Optional[Callable[[], None]]]],
                 event) -> None:
    """Показати контекстне меню; пункт із command=None стає розділювачем."""
    menu = tk.Menu(master, tearoff=0, bg=theme.BG_ELEVATED, fg=theme.FG,
                   activebackground=theme.BG_ACTIVE, activeforeground=theme.FG_BRIGHT,
                   bd=0, font=("Segoe UI", 9))
    for label, command in items:
        if command is None:
            menu.add_separator()
        else:
            menu.add_command(label=label, command=command)
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


# ── Буфер обміну для полів введення й текстових областей ────────────────────
#
# Навіщо власні функції, а не вбудовані ``<<Paste>>``/``<<Copy>>``:
# у ttk.Entry на Windows ці віртуальні події не завжди доїжджають (зокрема
# коли фокус переходить із списку), і Ctrl+V у полі пошуку хаба моделей
# просто нічого не робив — «навіть через Ctrl+V не можу вставити». Тут
# операція виконується напряму через буфер Tk, тож працює завжди.

def _selection(widget) -> str:
    """Виділений текст віджета (порожній рядок, якщо виділення немає)."""
    try:
        return str(widget.selection_get() or "")
    except Exception:                            # noqa: BLE001 - немає виділення
        return ""


def _replace_selection(widget, text: str) -> None:
    """Вставити текст, замінивши виділення (для Entry і Text)."""
    try:
        widget.delete("sel.first", "sel.last")
    except Exception:                            # noqa: BLE001 - виділення немає
        pass
    try:
        widget.insert("insert", text)
    except Exception:                            # noqa: BLE001 - віджет лише для читання
        pass


def clipboard_copy(widget) -> str:
    """Скопіювати виділення у буфер. Повертає скопійоване."""
    text = _selection(widget)
    if not text:
        return ""
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
    except Exception:                            # noqa: BLE001 - буфер недоступний
        return ""
    return text


def clipboard_cut(widget) -> str:
    """Вирізати виділення у буфер (лише для редагованих віджетів)."""
    text = clipboard_copy(widget)
    if not text:
        return ""
    try:
        widget.delete("sel.first", "sel.last")
    except Exception:                            # noqa: BLE001
        pass
    return text


def clipboard_paste(widget) -> bool:
    """Вставити з буфера у позицію курсора. ``False`` — буфер порожній.

    Для віджетів, прив'язаних як «лише читання» (:func:`attach_edit_actions`
    з ``readonly=True``), вставка НЕ виконується: інакше поле, яке мало
    лишатись незмінним, тихо дописувало текст.
    """
    if getattr(widget, "_bchpok_readonly", False):
        return False
    try:
        text = str(widget.clipboard_get() or "")
    except Exception:                            # noqa: BLE001 - буфер порожній
        return False
    if not text:
        return False
    _replace_selection(widget, text)
    return True


def clipboard_select_all(widget) -> None:
    """Виділити весь вміст поля."""
    try:
        widget.selection_range(0, "end")
        widget.icursor("end")
    except Exception:                            # noqa: BLE001 - Text не має selection_range
        try:
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
        except Exception:                        # noqa: BLE001
            pass


def attach_edit_actions(widget, *, readonly: bool = False) -> None:
    """Підключити Ctrl+C/X/V/A і праве меню до поля введення.

    ``readonly=True`` для полів, де редагування заборонене: лишаються
    лише «Копіювати» й «Виділити все».
    """
    try:
        widget._bchpok_readonly = bool(readonly)     # type: ignore[attr-defined]
    except Exception:                            # noqa: BLE001 - буває read-only віджет
        pass
    widget.bind("<Control-v>", lambda _e: (clipboard_paste(widget), "break")[1])
    widget.bind("<Control-V>", lambda _e: (clipboard_paste(widget), "break")[1])
    widget.bind("<Shift-Insert>", lambda _e: (clipboard_paste(widget), "break")[1])
    widget.bind("<Control-c>", lambda _e: (clipboard_copy(widget), "break")[1])
    widget.bind("<Control-C>", lambda _e: (clipboard_copy(widget), "break")[1])
    widget.bind("<Control-a>", lambda _e: (clipboard_select_all(widget), "break")[1])
    widget.bind("<Control-A>", lambda _e: (clipboard_select_all(widget), "break")[1])
    if not readonly:
        widget.bind("<Control-x>", lambda _e: (clipboard_cut(widget), "break")[1])
        widget.bind("<Control-X>", lambda _e: (clipboard_cut(widget), "break")[1])

    def show_menu(event):
        items: list[tuple[str, Optional[Callable[[], None]]]] = [
            ("Копіювати", lambda: clipboard_copy(widget)),
        ]
        if not readonly:
            items = [
                ("Вирізати", lambda: clipboard_cut(widget)),
                ("Копіювати", lambda: clipboard_copy(widget)),
                ("Вставити", lambda: clipboard_paste(widget)),
            ]
        items.append(("Виділити все", lambda: clipboard_select_all(widget)))
        context_menu(widget, items, event)

    widget.bind("<Button-3>", show_menu)


def clamp_to_screen(window: tk.Misc, x: float, y: float,
                    width: int, height: int, *, margin: int = 8) -> tuple[int, int]:
    """Вписати позицію вікна в межі екрана.

    Вікна IDE (налаштування, вибір моделі, майстер) раніше ставились за
    координатами батьківського вікна без перевірки меж. Якщо головне вікно
    стоїть біля краю екрана або на другому моніторі, діалог виїжджав за
    екран — кнопки ставали недосяжними, а інтерфейс «зависав» на очікуванні.
    Повертає безпечні ``(x, y)``.
    """
    try:
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
    except tk.TclError:
        return int(max(0, x)), int(max(0, y))
    # Тримаємо вікно цілком на екрані, лишаючи невеликий відступ.
    max_x = max(0, screen_w - int(width) - margin)
    max_y = max(0, screen_h - int(height) - margin)
    safe_x = int(max(margin, min(float(x), max_x)))
    safe_y = int(max(margin, min(float(y), max_y)))
    return safe_x, safe_y


def place_window(window: tk.Misc, *, width: int = 0, height: int = 0,
                 anchor: Optional[tk.Misc] = None, above: bool = False,
                 center_on: Optional[tk.Misc] = None) -> None:
    """Розмістити вікно так, щоб воно гарантовано було в межах екрана.

    Три режими (у порядку пріоритету):

    * ``anchor`` — біля віджета-якоря (вище або нижче нього);
    * ``center_on`` — по центру батьківського вікна;
    * без параметрів — по центру екрана.

    Розміри ``width``/``height`` беруться з ``winfo_req*``, якщо не задані.
    """
    try:
        window.update_idletasks()
        width = int(width or window.winfo_reqwidth())
        height = int(height or window.winfo_reqheight())
        if anchor is not None and anchor.winfo_exists():
            ax, ay = anchor.winfo_rootx(), anchor.winfo_rooty()
            aw, ah = anchor.winfo_width(), anchor.winfo_height()
            x = ax
            y = ay - height - 8 if above else ay + ah + 8
            screen_h = window.winfo_screenheight()
            if y < 20 or y + height > screen_h - 8:
                y = ay + ah + 8 if above else ay - height - 8
        elif center_on is not None and center_on.winfo_exists():
            parent = center_on.winfo_toplevel()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 3)
        else:
            x = (window.winfo_screenwidth() - width) // 2
            y = (window.winfo_screenheight() - height) // 2
        safe_x, safe_y = clamp_to_screen(window, x, y, width, height)
        window.geometry(f"{width}x{height}+{safe_x}+{safe_y}")
    except tk.TclError:
        return


# ─────────────────────────────────────────────────────────────────────────────
# Модальні вікна
# ─────────────────────────────────────────────────────────────────────────────

#: Вікно, яке зараз тримає введення (``grab``). Лише одне за раз.
_ACTIVE_MODAL: Optional[tk.Misc] = None


def acquire_modal(window: tk.Misc) -> bool:
    """Зробити вікно модальним, якщо інше модальне вже не відкрите.

    Раніше два діалоги могли відкритись одночасно (наприклад «Налаштування»
    і «Вибір моделі»): обидва викликали ``grab_set()``, введення ділилось
    між ними, і застосунок зависав. Повертає True, якщо вдалось захопити
    введення.
    """
    global _ACTIVE_MODAL
    existing = _ACTIVE_MODAL
    if existing is not None and existing is not window:
        try:
            if existing.winfo_exists():
                return False
        except tk.TclError:
            pass
    try:
        window.grab_set()
    except tk.TclError:
        return False
    _ACTIVE_MODAL = window
    try:
        window.bind("<Destroy>", lambda _e: release_modal(window), add="+")
    except tk.TclError:
        pass
    return True


def release_modal(window: tk.Misc) -> None:
    """Звільнити введення (виклик при закритті вікна)."""
    global _ACTIVE_MODAL
    if _ACTIVE_MODAL is window:
        _ACTIVE_MODAL = None
    try:
        window.grab_release()
    except tk.TclError:
        pass


def active_modal() -> Optional[tk.Misc]:
    """Вікно, що зараз тримає введення (або ``None``)."""
    window = _ACTIVE_MODAL
    if window is None:
        return None
    try:
        if window.winfo_exists():
            return window
    except tk.TclError:
        pass
    return None


def lift_modal(window: tk.Misc) -> None:
    """Підняти модальне вікно поверх решти (не захоплюючи введення)."""
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
    except tk.TclError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Спливні вікна (попапи)
# ─────────────────────────────────────────────────────────────────────────────

#: Зареєстровані спливні вікна: картки моделі, режимів, контексту, меню.
_POPOVERS: list = []


def cancel_after(widget: tk.Misc, *names: str) -> int:
    """Скасувати збережені ``after``-таймери віджета. Повертає кількість.

    Навіщо помічник. Панелі ставлять повторювані ``after(120, self._pump)``
    і зберігають id у власних полях (``_after``, ``_drain_job``,
    ``_poll_job``…). Назви полів різні, і при закритті вікна їх легко
    пропустити: тоді запланований виклик лишається в Tcl, його команда
    зникає разом із віджетом — і Tk друкує «invalid command name
    ..._pump», а закриття застосунку падає з «application has been
    destroyed».

    Виклик::

        cancel_after(panel, "_after")            # одне поле
        cancel_after(panel)                       # усі відомі назви

    Збій одного скасування не заважає решті.
    """
    #: Назви полів, у яких панелі тримають id таймера.
    default = (
        "_after", "_timer_job", "_drain_job", "_drain_after", "_poll_after",
        "_poll_job", "_pump_job", "_spin_job", "_search_after",
        "_watcher_after", "_timer_after", "_resize_job", "_sync_after",
        "_reload_after", "_events_after", "_probe_after",
        # Панелі власного рушія й пам'яті: постійний тік і черга оновлень.
        "_live_after",
    )
    cancelled = 0
    for name in (names or default):
        job = getattr(widget, name, None)
        if not job:
            continue
        try:
            widget.after_cancel(job)
            cancelled += 1
        except (tk.TclError, ValueError):
            pass
        try:
            setattr(widget, name, None)
        except Exception:  # noqa: BLE001 - поле могло бути властивістю
            pass
    return cancelled


def register_popover(window: tk.Misc) -> None:
    """Запам'ятати спливне вікно, щоб його можна було закрити гуртом."""
    try:
        if window not in _POPOVERS:
            _POPOVERS.append(window)

        # Подія <Destroy> приходить і від ДОЧІРНІХ віджетів (кожен Label,
        # Frame усередині картки), тож без перевірки ``event.widget is
        # window`` картка вилучала себе з реєстру одразу після побудови —
        # і модальні діалоги більше її не закривали.
        def on_destroy(event) -> None:
            if getattr(event, "widget", None) is window:
                unregister_popover(window)

        window.bind("<Destroy>", on_destroy, add="+")
    except tk.TclError:
        pass


def unregister_popover(window: tk.Misc) -> None:
    """Прибрати вікно з реєстру спливних."""
    try:
        _POPOVERS.remove(window)
    except ValueError:
        pass


def is_popover_widget(widget) -> bool:
    """Чи належить віджет зареєстрованому спливному вікну.

    Потрібно, щоб відрізнити «фокус пішов у нашу картку» (нормально) від
    «фокус пішов в інше вікно» (тоді картку треба закрити).
    """
    node = widget
    depth = 0
    while node is not None and depth < 12:
        if node in _POPOVERS:
            return True
        node = getattr(node, "master", None)
        depth += 1
    return False


def close_popovers(*, keep: Optional[tk.Misc] = None) -> int:
    """Закрити всі зареєстровані спливні вікна.

    Навіщо: картка «Модель» має прапорець ``-topmost`` і лишалась поверх
    модального діалогу («Налаштування»). Користувач бачив два вікна
    одночасно й не міг зрозуміти, яке з них активне — інтерфейс виглядав
    завішеним. Повертає кількість закритих.
    """
    closed = 0
    for window in list(_POPOVERS):
        if window is keep:
            continue
        try:
            if not window.winfo_exists():
                unregister_popover(window)
                continue
            closer = getattr(window, "close", None)
            if callable(closer):
                closer()
            else:
                window.withdraw()
            closed += 1
        except (tk.TclError, AttributeError):
            unregister_popover(window)
    return closed


def open_only_modal(window: tk.Misc) -> bool:
    """Підготувати модальне вікно: закрити попапи й захопити введення.

    Один виклик замість трьох кроків у кожному діалозі — так жоден новий
    діалог не забуде прибрати картки під собою.
    """
    close_popovers()
    return acquire_modal(window)


class StatusDot(tk.Label):
    """Кружечок стану: зелений / жовтий / червоний / сірий."""

    STATES = {
        "ok": theme.SUCCESS,
        "busy": theme.WARN,
        "error": theme.ERROR,
        "idle": theme.FG_FAINT,
    }

    def __init__(self, master: tk.Misc, *, bg: str = theme.BG, size: int = 8,
                 state: str = "idle") -> None:
        super().__init__(master, text="●", bg=bg, fg=self.STATES.get(state, theme.FG_FAINT),
                         font=("Segoe UI", size), bd=0, highlightthickness=0)
        self._bg = bg
        self.state = state

    def set_state(self, state: str, tooltip: str = "") -> None:
        self.state = state
        try:
            self.configure(fg=self.STATES.get(state, theme.FG_FAINT))
        except tk.TclError:
            pass
        if tooltip:
            self.text = tooltip


class IconRailButton(tk.Frame):
    """Кнопка рейки навігації: іконка зверху, короткий підпис знизу.

    Панель навігації не має бути «частоколом із символів»: користувач має
    розуміти, куди веде кнопка, не наводячи мишу.
    """

    def __init__(self, master: tk.Misc, icon: str, label: str,
                 command: Optional[Callable[[], None]] = None, *,
                 width: int = theme.RAIL_WIDTH, bg: str = theme.RAIL_BG) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0, cursor="hand2",
                         width=width)
        self._bg = bg
        self._command = command
        self._active = False
        self.icon_label = tk.Label(self, text=icon, bg=bg, fg=theme.FG_DIM,
                                   font=("Segoe UI", 12), bd=0, highlightthickness=0)
        self.icon_label.pack(pady=(6, 0))
        self.text_label = tk.Label(self, text=label, bg=bg, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 7), bd=0, highlightthickness=0)
        self.text_label.pack(pady=(1, 6))
        for widget in (self, self.icon_label, self.text_label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_press)
            widget.bind("<ButtonRelease-1>", self._on_release)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._paint()

    def set_label(self, label: str) -> None:
        try:
            self.text_label.configure(text=label)
        except tk.TclError:
            pass

    def set_command(self, command: Optional[Callable[[], None]]) -> None:
        self._command = command

    def _paint(self, hover: bool = False) -> None:
        if self._active:
            bg, icon_fg, text_fg = theme.BG_ACTIVE, theme.FG_BRIGHT, theme.FG
        elif hover:
            bg, icon_fg, text_fg = theme.BG_HOVER, theme.FG_BRIGHT, theme.FG_DIM
        else:
            bg, icon_fg, text_fg = self._bg, theme.FG_DIM, theme.FG_FAINT
        try:
            self.configure(bg=bg)
            self.icon_label.configure(bg=bg, fg=icon_fg)
            self.text_label.configure(bg=bg, fg=text_fg)
        except tk.TclError:
            pass

    def _on_enter(self, _event=None) -> None:
        self._paint(hover=True)

    def _on_leave(self, _event=None) -> None:
        self._paint()

    def _on_press(self, _event=None) -> None:
        self.configure(bg=theme.BG_HOVER)

    def _on_release(self, _event=None) -> None:
        self._paint(hover=True)
        if self._command is not None:
            self._command()


class Segmented(tk.Frame):
    """Сегментований перемикач (режими, вкладки робочої області)."""

    def __init__(self, master: tk.Misc, items: Iterable[tuple[str, str, Callable[[], None]]] = (),
                 *, bg: str = theme.BG_ALT) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self._bg = bg
        self._buttons: dict[str, HoverLabel] = {}
        for key, label, command in items:
            self.add(key, label, command)
        self._current = ""

    def add(self, key: str, label: str, command: Callable[[], None]) -> HoverLabel:
        button = HoverLabel(self, text=label, command=command, bg=self._bg,
                            fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
                            active_bg=theme.BG_ACTIVE, active_fg=theme.FG_BRIGHT,
                            font=("Segoe UI", 9), padx=10, pady=3, anchor="center")
        button.pack(side="left", padx=(0, 2))
        self._buttons[key] = button
        return button

    def set_label(self, key: str, label: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            try:
                button.configure(text=label)
            except tk.TclError:
                pass

    def select(self, key: str) -> None:
        self._current = key
        for name, button in self._buttons.items():
            button.set_active(name == key)

    @property
    def current(self) -> str:
        return self._current
