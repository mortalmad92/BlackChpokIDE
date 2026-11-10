"""Навігаційна колонка: компактна, з групами й живою історією сесій.

Композиція свідомо повторює структуру професійної агентної оболонки:

    ┌─ BLACKCHOP ──────────┐
    │  ＋ Нова сесія       │   ← головна дія
    │  Чати                │
    │  Агенти              │
    │  Автоматизації       │
    │  MCP Tools           │
    │  Проєкти             │
    │  База знань / RAG    │
    │  Налаштування        │
    │ ─────────────────────│
    │  РОБОЧІ ПРОЄКТИ      │   ← поточна тека проєкту
    │  ІСТОРІЯ             │   ← живі сесії зі сховища чатів
    └──────────────────────┘

Кнопки — не «частокіл із символів»: у кожної є підпис, іконка й активний
стан. Панель згортається до рейки, і тоді лишаються самі іконки.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import theme, widgets

#: Каталог панелей програми: (ключ, іконка, підпис, підказка).
#:
#: РАНІШЕ це було меню лівої колонки. Тепер меню немає: ліва панель показує
#: лише чати, а ці панелі відкриваються з діалогу налаштувань (вкладка
#: «Розділи»). Каталог лишено як довідник для тих, кому потрібні підписи
#: й підказки панелей.
NAV_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    ("chats", "◍", "Чати й агенти", "Історія розмов і живі сесії агента"),
    ("mcp", "⌘", "MCP Tools", "Підключені MCP-сервери та їхні інструменти"),
    ("projects", "🗂", "Проєкти", "Файли, пошук по проєкту, зміни"),
    ("knowledge", "◫", "База знань", "RAG: індексація й семантичний пошук"),
    ("settings", "⚙", "Налаштування", "Провайдери, моделі, редактор, агент"),
)

#: Додаткові панелі (для довідників і тестів).
SUB_ITEMS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "chats": (
        ("cases", "◎", "Кроки агента", "Що агент робить зараз — кроки поточної сесії"),
        ("queue", "≡", "Черга чату", "Задачі, прив'язані до поточного чату"),
        ("autonomous", "∞", "Автономний", "Безперервний режим для поточного проєкту"),
        ("skills", "✦", "Скіли", "Скіли агента"),
    ),
    "projects": (
        ("explorer", "▤", "Файли", "Дерево файлів проєкту"),
        ("search", "⌕", "Пошук", "Пошук по проєкту"),
        ("changes", "±", "Зміни", "Змінені файли"),
        ("outline", "◧", "Структура", "Структура поточного файлу"),
    ),
    "knowledge": (
        ("rag", "◫", "Індекс", "Індексація й пошук RAG"),
        ("cases", "◎", "Контекст", "Джерела контексту"),
    ),
    "mcp": (
        ("tools", "⚒", "Інструменти", "Вбудовані інструменти агента"),
    ),
}


class NavButton(tk.Frame):
    """Пункт навігації: іконка + підпис, з наведенням і активним станом."""

    def __init__(self, master: tk.Misc, icon: str, label: str,
                 command: Optional[Callable[[], None]] = None, *,
                 bg: str = theme.BG_ALT, bold: bool = False,
                 font_size: int = 9) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0, cursor="hand2")
        self._bg = bg
        self._command = command
        self._active = False
        self.columnconfigure(1, weight=1)

        self.icon_label = tk.Label(self, text=icon, bg=bg, fg=theme.FG_DIM,
                                   font=("Segoe UI", 13), width=2, anchor="center",
                                   bd=0, highlightthickness=0)
        self.icon_label.grid(row=0, column=0, padx=(theme.SPACE_MD, 0), pady=6, sticky="w")

        self.text_label = tk.Label(self, text=label, bg=bg, fg=theme.FG_DIM,
                                   font=("Segoe UI", font_size, "bold" if bold else "normal"),
                                   anchor="w", bd=0, highlightthickness=0)
        self.text_label.grid(row=0, column=1, sticky="ew", padx=(theme.SPACE_SM, theme.SPACE_MD),
                             pady=6)

        for widget in (self, self.icon_label, self.text_label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_press)
            widget.bind("<ButtonRelease-1>", self._on_release)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._paint()

    def _paint(self, hover: bool = False) -> None:
        # Кольори читаються з теми на кожне перемалювання: після
        # перемикання light/dark наведення не залишає старих світлих плашок.
        if self._active:
            bg, icon_fg, text_fg = theme.BG_ACTIVE, theme.FG_BRIGHT, theme.FG_BRIGHT
        elif hover:
            bg, icon_fg, text_fg = theme.BG_HOVER, theme.FG_BRIGHT, theme.FG
        else:
            bg, icon_fg, text_fg = theme.BG_ALT, theme.FG_DIM, theme.FG_DIM
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
        try:
            self.configure(bg=theme.BG_HOVER)
        except tk.TclError:
            pass

    def _on_release(self, _event=None) -> None:
        self._paint(hover=True)
        if self._command is not None:
            self._command()


class NavSidebar(tk.Frame):
    """Ліва колонка навігації з історією сесій і робочими проєктами."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_navigate: Optional[Callable[[str], None]] = None,
        on_new_session: Optional[Callable[[], None]] = None,
        on_open_chat: Optional[Callable[[str], None]] = None,
        on_open_project: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        chat_store=None,
        width: int = theme.SIDEBAR_WIDTH,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, width=width, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.on_navigate = on_navigate
        self.on_new_session = on_new_session
        self.on_open_chat = on_open_chat
        self.on_open_project = on_open_project
        self.on_settings = on_settings
        self.chat_store = chat_store
        self._buttons: dict[str, NavButton] = {}
        self._sub_buttons: dict[str, NavButton] = {}
        self._active = ""
        self._collapsed = False
        self._width = width
        self.pack_propagate(False)
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        # 1. Бренд
        brand = tk.Frame(self, bg=theme.BG_ALT)
        brand.pack(fill="x", padx=theme.SPACE_LG, pady=(theme.SPACE_LG, theme.SPACE_MD))
        self.brand = brand

        self.logo = tk.Label(brand, text="◤", bg=theme.BG_ALT, fg=theme.ACCENT,
                             font=("Segoe UI", 13, "bold"))
        self.logo.pack(side="left")

        self.brand_label = tk.Label(brand, text="BlackChpok", bg=theme.BG_ALT,
                                    fg=theme.FG_BRIGHT, font=self.fonts.ui_h2, anchor="w")
        self.brand_label.pack(side="left", padx=(theme.SPACE_SM, 0))

        self.collapse_btn = widgets.IconButton(
            brand, "«", self.toggle_collapsed, bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 9), tooltip="Згорнути панель (Ctrl+B)")
        self.collapse_btn.pack(side="right")

        # 2. Головна дія
        new_btn = widgets.HoverLabel(
            self, text="  ＋  Нова сесія", command=self._new_session,
            bg=theme.BG_INPUT, fg=theme.FG_BRIGHT, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=("Segoe UI", 9, "bold"),
            padx=theme.SPACE_MD, pady=6, anchor="w",
        )
        new_btn.pack(fill="x", padx=theme.SPACE_MD, pady=(0, theme.SPACE_MD))
        self.new_session_btn = new_btn

        # 3. Розділи
        self.items_host = tk.Frame(self, bg=theme.BG_ALT)
        self.items_host.pack(fill="x", padx=theme.SPACE_SM)
        for key, icon, label, tip in NAV_ITEMS:
            button = NavButton(self.items_host, icon, label,
                               lambda k=key: self._navigate(k), bg=theme.BG_ALT)
            button.pack(fill="x", pady=0)
            widgets.Tip(button, tip)
            self._buttons[key] = button

        # 4. Робочі простори
        self.workspace_host = tk.Frame(self, bg=theme.BG_ALT)
        self.workspace_host.pack(fill="x", padx=theme.SPACE_SM, pady=(theme.SPACE_MD, 0))
        self.workspace_title = tk.Label(
            self.workspace_host, text="РОБОЧИЙ ПРОЄКТ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=self.fonts.ui_tiny, anchor="w",
        )
        self.workspace_title.pack(fill="x", padx=theme.SPACE_MD, pady=(0, 2))

        self.project_row = tk.Frame(self.workspace_host, bg=theme.BG_ALT, cursor="hand2")
        self.project_row.pack(fill="x")
        self.project_icon = tk.Label(self.project_row, text="🗂", bg=theme.BG_ALT,
                                     fg=theme.FG_DIM, font=("Segoe UI", 9))
        self.project_icon.pack(side="left", padx=(theme.SPACE_MD, theme.SPACE_SM))
        self.project_label = tk.Label(self.project_row, text="не обрано", bg=theme.BG_ALT,
                                      fg=theme.FG, font=("Segoe UI", 9), anchor="w")
        self.project_label.pack(side="left", fill="x", expand=True, pady=3)
        for widget in (self.project_row, self.project_icon, self.project_label):
            widget.bind("<Button-1>", lambda _e: self._open_project())
        widgets.Tip(self.project_row, "Змінити робочу теку проєкту")

        # 5. Історія сесій
        self.history_title = tk.Label(
            self, text="ІСТОРІЯ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=self.fonts.ui_tiny, anchor="w",
        )
        self.history_title.pack(fill="x", padx=theme.SPACE_LG, pady=(theme.SPACE_MD, 2))

        self.history_scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.history_scroll.pack(fill="both", expand=True, padx=theme.SPACE_SM,
                                 pady=(0, theme.SPACE_SM))
        self.history_host = self.history_scroll.inner

        # 6. Підвал
        footer = tk.Frame(self, bg=theme.BG_ALT)
        footer.pack(fill="x", side="bottom", padx=theme.SPACE_SM, pady=(0, theme.SPACE_SM))
        self.footer = footer

        self.user_label = tk.Label(footer, text="● локально", bg=theme.BG_ALT,
                                   fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w")
        self.user_label.pack(side="left", padx=(theme.SPACE_SM, 0))
        widgets.Tip(self.user_label, "Local-first: дані не покидають ваш комп'ютер")

        widgets.IconButton(footer, "◔", self._open_settings, bg=theme.BG_ALT,
                           fg=theme.FG_FAINT, font=("Segoe UI", 10),
                           tooltip="Налаштування (Ctrl+,)").pack(side="right")

    # ── дії ────────────────────────────────────────────────────────────────
    def _navigate(self, key: str) -> None:
        if self.on_navigate is not None:
            self.on_navigate(key)

    def _new_session(self) -> None:
        if self.on_new_session is not None:
            self.on_new_session()

    def _open_project(self) -> None:
        if self.on_open_project is not None:
            self.on_open_project()

    def _open_settings(self) -> None:
        if self.on_settings is not None:
            self.on_settings()

    def set_active(self, key: str) -> None:
        """Підсвітити активний розділ (і показати його підпункти)."""
        self._active = key
        for name, button in self._buttons.items():
            button.set_active(name == key)
        self._rebuild_sub_items()

    def _rebuild_sub_items(self) -> None:
        """Показати швидкі підпункти активного розділу."""
        existing = getattr(self, "sub_host", None)
        if existing is not None:
            existing.destroy()
        self._sub_buttons.clear()
        entries = SUB_ITEMS.get(self._active, ())
        if not entries:
            self.sub_host = None
            return
        self.sub_host = tk.Frame(self, bg=theme.BG_ALT)
        self.sub_host.pack(fill="x", padx=(theme.SPACE_XL, theme.SPACE_SM),
                           after=self.items_host)
        for key, icon, label, tip in entries:
            button = NavButton(self.sub_host, icon, label,
                               lambda k=key: self._navigate(k), bg=theme.BG_ALT,
                               font_size=8)
            button.pack(fill="x")
            widgets.Tip(button, tip)
            self._sub_buttons[key] = button

    def set_sub_active(self, key: str) -> None:
        for name, button in self._sub_buttons.items():
            button.set_active(name == key)

    # ── вміст ──────────────────────────────────────────────────────────────
    def set_project(self, path: str) -> None:
        name = Path(path).name if path else "не обрано"
        try:
            self.project_label.configure(text=name or path)
        except tk.TclError:
            pass

    def set_local_state(self, text: str, ok: bool = True) -> None:
        try:
            self.user_label.configure(text=text,
                                      fg=theme.SUCCESS if ok else theme.FG_FAINT)
        except tk.TclError:
            pass

    def refresh_history(self, active_id: str = "") -> None:
        """Перемалювати список сесій зі сховища чатів."""
        for child in self.history_host.winfo_children():
            child.destroy()
        store = self.chat_store
        if store is None:
            return
        try:
            chats = store.visible(archived=False)
        except Exception:  # noqa: BLE001 - сховище може бути недоступне
            return
        if not chats:
            tk.Label(self.history_host, text="Сесій ще немає", bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w").pack(
                fill="x", padx=theme.SPACE_MD, pady=theme.SPACE_SM)
            return
        for chat in chats[:40]:
            self._history_row(chat, active=chat.id == active_id)

    def _history_row(self, chat, *, active: bool) -> None:
        bg = theme.BG_ACTIVE if active else theme.BG_ALT
        row = tk.Frame(self.history_host, bg=bg, cursor="hand2")
        row.pack(fill="x", pady=1)
        title = chat.title or "Без назви"
        if chat.pinned:
            title = "★ " + title
        label = tk.Label(row, text=title, bg=bg,
                         fg=theme.FG_BRIGHT if active else theme.FG_DIM,
                         font=("Segoe UI", 9), anchor="w")
        label.pack(fill="x", padx=(theme.SPACE_MD, theme.SPACE_SM), pady=(3, 0))
        meta = tk.Label(row, text=f"{chat.message_count} повід. · {chat.age_text}", bg=bg,
                        fg=theme.FG_FAINT, font=("Segoe UI", 7), anchor="w")
        meta.pack(fill="x", padx=(theme.SPACE_MD, theme.SPACE_SM), pady=(0, 3))

        def open_chat(_e=None, cid=chat.id):
            if self.on_open_chat is not None:
                self.on_open_chat(cid)

        def hover(enter: bool) -> None:
            colour = theme.BG_HOVER if enter else bg
            for widget in (row, label, meta):
                try:
                    widget.configure(bg=colour)
                except tk.TclError:
                    pass

        for widget in (row, label, meta):
            widget.bind("<Button-1>", open_chat)
            widget.bind("<Enter>", lambda _e: hover(True))
            widget.bind("<Leave>", lambda _e: hover(False))

    # ── згортання ──────────────────────────────────────────────────────────
    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self, collapsed: Optional[bool] = None) -> bool:
        """Згорнути панель до вузької рейки (лишаються самі іконки)."""
        target = (not self._collapsed) if collapsed is None else bool(collapsed)
        if target == self._collapsed:
            return self._collapsed
        self._collapsed = target
        if target:
            self.configure(width=theme.RAIL_COLLAPSED_WIDTH)
            for child in (self.brand_label, self.workspace_host, self.history_title,
                          self.history_scroll, self.user_label):
                try:
                    child.pack_forget()
                except (tk.TclError, AttributeError):
                    pass
            try:
                self.new_session_btn.configure(text="  ＋")
            except tk.TclError:
                pass
            for button in self._buttons.values():
                button.text_label.grid_remove()
            if getattr(self, "sub_host", None) is not None:
                self.sub_host.pack_forget()
            try:
                self.collapse_btn.configure(text="»")
            except tk.TclError:
                pass
        else:
            self.configure(width=self._width)
            self.brand_label.pack(side="left", padx=(theme.SPACE_SM, 0), after=self.logo)
            self.workspace_host.pack(fill="x", padx=theme.SPACE_SM,
                                    pady=(theme.SPACE_MD, 0), after=self.items_host)
            self.history_title.pack(fill="x", padx=theme.SPACE_LG,
                                    pady=(theme.SPACE_MD, 2), after=self.workspace_host)
            self.history_scroll.pack(fill="both", expand=True, padx=theme.SPACE_SM,
                                     pady=(0, theme.SPACE_SM))
            self.user_label.pack(side="left", padx=(theme.SPACE_SM, 0))
            try:
                self.new_session_btn.configure(text="  ＋  Нова сесія")
            except tk.TclError:
                pass
            for button in self._buttons.values():
                button.text_label.grid()
            self._rebuild_sub_items()
            try:
                self.collapse_btn.configure(text="«")
            except tk.TclError:
                pass
        return self._collapsed


__all__ = ["NAV_ITEMS", "SUB_ITEMS", "NavButton", "NavSidebar"]
