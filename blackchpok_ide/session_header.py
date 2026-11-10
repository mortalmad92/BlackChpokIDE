"""Заголовок робочої області: сесія, режим, модель, завдання, вид.

Це «верхня смуга» центральної області — те місце, де користувач бачить
контекст своєї роботи, не читаючи діалог:

    ┌─────────────────────────────────────────────────────────────────┐
    │ ● Записи при відкритті вкладок…   ● Снапшот режим  ◈ Агент ▾    │
    │ Чат   Робоча область   ⚙         GPT…           ⊞ 3 файли      │
    └─────────────────────────────────────────────────────────────────┘

Смуга нічого не виконує сама: усі дії вона віддає колбеками оболонці, а
стан показує з того, що їй передали (реальні події агента й сховища).
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import modes, permissions, providers, theme, widgets


class SessionHeader(tk.Frame):
    """Верхня смуга: назва сесії, режим роботи, модель, завдання, вид."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_modes: Optional[Callable[[], None]] = None,
        on_model: Optional[Callable[[], None]] = None,
        on_view: Optional[Callable[[str], None]] = None,
        on_workspace: Optional[Callable[[], None]] = None,
        on_context: Optional[Callable[[], None]] = None,
        on_chat_mode: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.on_modes = on_modes
        self.on_model = on_model
        self.on_view = on_view
        self.on_workspace = on_workspace
        self.on_context = on_context
        self.on_chat_mode = on_chat_mode
        self._view = "chat"
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(1, weight=1)

        # Рядок 1: статус, назва сесії, режим, модель
        top = tk.Frame(self, bg=theme.BG)
        top.grid(row=0, column=0, columnspan=3, sticky="ew",
                 padx=(theme.SPACE_XL, theme.SPACE_SM), pady=(theme.SPACE_MD, 0))
        top.columnconfigure(1, weight=1)

        self.status_dot = widgets.StatusDot(top, bg=theme.BG, size=9, state="idle")
        self.status_dot.grid(row=0, column=0, padx=(0, theme.SPACE_SM))
        widgets.Tip(self.status_dot, "Стан агента")

        self.title_label = tk.Label(top, text="Нова сесія", bg=theme.BG, fg=theme.FG_BRIGHT,
                                    font=self.fonts.ui_h2, anchor="w")
        self.title_label.grid(row=0, column=1, sticky="ew")

        # Режим роботи: РУЧКА замість видимої кнопки.
        #
        # Чому. Режим агента показує шапка вікна («◈ Агент ▾» у лівому
        # ряду керування) — і поруч, у рядку сесії, стояла ДРУГА така сама
        # кнопка. На скріншоті користувача це виглядало як подвоєні
        # пункти: «Агент · Модель» ліворуч і «◈ Агент · ⊟ Модель»
        # праворуч.
        #
        # Лишаємо ЛИШЕ ручку: її читають тести, ``_paint`` і
        # ``show_mode_menu`` як якір меню, тож логіка не ламається, а на
        # екрані дубля немає.
        self.mode_label = tk.Label(self, text="", bg=theme.BG)

        # Режим ЧАТУ: автономний і автоматизації належать сесії, а не меню.
        # Раніше вони були пунктами лівого меню й ні до чого не прив'язувались.
        self.chat_mode_label = widgets.HoverLabel(
            top, text="◎ Чат ▾", command=self._pick_chat_mode, bg=theme.BG,
            fg=theme.FG_DIM, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT,
            font=("Segoe UI", 8), padx=theme.SPACE_MD, pady=3, anchor="center",
        )
        self.chat_mode_label.grid(row=0, column=3, padx=(0, theme.SPACE_SM))
        widgets.Tip(self.chat_mode_label,
                    "Автономний режим і автоматизації цього чату й проєкту")

        # Модель показує ШАПКА ВІКНА (``header_bar``) — там вона поруч із
        # статусом сервера й селектором. Тут, у рядку сесії, вона була
        # ДРУГИМ підписом тієї самої моделі: на скріншоті користувача
        # «⊟ Ministral-3-14B · локальна▾» стояло ліворуч у шапці й поряд,
        # у рядку сесії — і це виглядало як «вибрані дві різні моделі».
        #
        # Лишаємо ЛИШЕ невидиму ручку ``model_label``: її читають тести й
        # ``_sync_model_labels`` тримає в ній той самий підпис, тож
        # інформація доступна, але на екрані немає дубля.
        self.model_label = tk.Label(self, text="", bg=theme.BG)

        widgets.IconButton(top, "⋯", self._more_menu, bg=theme.BG, fg=theme.FG_FAINT,
                           font=("Segoe UI", 11), tooltip="Більше дій").grid(row=0, column=5)

        # Рядок 2: перемикач виду, завдання, метрики
        bottom = tk.Frame(self, bg=theme.BG)
        bottom.grid(row=1, column=0, columnspan=3, sticky="ew",
                    padx=(theme.SPACE_XL, theme.SPACE_SM), pady=(theme.SPACE_XS, theme.SPACE_MD))
        bottom.columnconfigure(2, weight=1)

        self.view_switch = widgets.Segmented(bottom, bg=theme.BG)
        self.view_switch.pack(side="left")
        self.view_switch.add("chat", "Чат", lambda: self._set_view("chat"))
        self.view_switch.add("workspace", "Робоча область", lambda: self._set_view("workspace"))
        self.view_switch.select("chat")

        self.task_label = tk.Label(bottom, text="", bg=theme.BG, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8), anchor="w")
        self.task_label.pack(side="left", padx=(theme.SPACE_LG, 0))

        self.context_btn = widgets.HoverLabel(
            bottom, text="", command=self._toggle_context, bg=theme.BG,
            fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT,
            font=("Segoe UI", 8), padx=theme.SPACE_SM, pady=2, anchor="e",
        )
        self.context_btn.pack(side="right")
        widgets.Tip(self.context_btn, "Колонка контексту: файли, вкладки, зміни")

        self.workspace_btn = widgets.HoverLabel(
            bottom, text="", command=self._workspace_action, bg=theme.BG,
            fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT,
            font=("Segoe UI", 8), padx=theme.SPACE_SM, pady=2, anchor="e",
        )
        self.workspace_btn.pack(side="right")
        widgets.Tip(self.workspace_btn, "Файли робочого проєкту")

        widgets.Divider(self, colour=theme.BORDER, autopack=False).grid(
            row=2, column=0, columnspan=3, sticky="ew")

    # ── дії ────────────────────────────────────────────────────────────────
    def _pick_mode(self) -> None:
        if self.on_modes is not None:
            self.on_modes()

    def _pick_model(self) -> None:
        if self.on_model is not None:
            self.on_model()

    def _pick_chat_mode(self) -> None:
        if self.on_chat_mode is not None:
            self.on_chat_mode()

    def _more_menu(self) -> None:
        items: list[tuple[str, Optional[Callable[[], None]]]] = [
            ("Перевірити моделі", self._pick_model),
            ("Режим роботи", self._pick_mode),
            ("", None),
            ("Показати файли проєкту", self._workspace_action),
            ("Колонка контексту", self._toggle_context),
        ]
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()

            class _Event:
                x_root = x
                y_root = y

            widgets.context_menu(self, items, _Event())
        except tk.TclError:
            return

    def _toggle_context(self) -> None:
        if self.on_context is not None:
            self.on_context()

    def _workspace_action(self) -> None:
        if self.on_workspace is not None:
            self.on_workspace()

    def _set_view(self, view: str) -> None:
        self._view = view
        self.view_switch.select(view)
        if self.on_view is not None:
            self.on_view(view)

    def set_view(self, view: str) -> None:
        """Показати активний вид, не викликаючи колбека."""
        self._view = view
        self.view_switch.select(view)

    # ── стан ───────────────────────────────────────────────────────────────
    def set_title(self, title: str) -> None:
        try:
            self.title_label.configure(text=(title or "Нова сесія")[:64])
        except tk.TclError:
            pass

    def set_status(self, state: str, tooltip: str = "") -> None:
        self.status_dot.set_state(state)
        if tooltip:
            self.task_label.configure(text=tooltip)
            self.task_label.configure(fg=theme.FG_DIM if state != "error" else theme.ERROR)

    def set_mode(self, key: str) -> None:
        mode = modes.get(key)
        try:
            self.mode_label.configure(text=f"{mode.icon} {mode.label} ▾",
                                      fg=theme.FG if key != modes.CHAT else theme.FG_DIM)
        except tk.TclError:
            pass

    def set_chat_mode(self, *, autonomous: bool = False, queue_count: int = 0) -> None:
        """Показати стан автономного режиму й черги на кнопці чату.

        Кнопка — єдине місце, де видно, що цей чат зараз робить у фоні:
        раніше про це можна було дізнатись лише з окремого пункту меню.
        """
        parts: list[str] = []
        if autonomous:
            parts.append("∞ автономно")
        if queue_count > 0:
            parts.append(f"≡ {queue_count}")
        text = "  ".join(parts) if parts else "◎ Чат"
        try:
            self.chat_mode_label.configure(
                text=f"{text} ▾",
                fg=theme.SUCCESS if autonomous else theme.FG_DIM)
        except tk.TclError:
            pass

    def set_model(self, entry: providers.ModelEntry) -> None:
        kind = "локальна" if entry.is_local else "хмара"
        name = entry.name
        if len(name) > 30:
            name = name[:29] + "…"
        colour = theme.WARN if not entry.online else theme.FG_DIM
        try:
            self.model_label.configure(text=f"⊟ {name} · {kind}", fg=colour)
        except tk.TclError:
            pass

    def set_permission(self, mode: str) -> None:
        try:
            self.mode_label.configure(
                fg=theme.WARN if mode == permissions.FULL else theme.FG_DIM)
        except tk.TclError:
            pass

    def set_workspace(self, name: str) -> None:
        try:
            self.workspace_btn.configure(text=f"🗂 {name}" if name else "")
        except tk.TclError:
            pass

    def set_context_count(self, files: int, tabs: int) -> None:
        parts: list[str] = []
        if tabs:
            parts.append(f"{tabs} вкладок")
        if files:
            parts.append(f"{files} файлів")
        try:
            self.context_btn.configure(text=" · ".join(parts))
        except tk.TclError:
            pass

    def set_task(self, text: str) -> None:
        try:
            self.task_label.configure(text=text[:96])
        except tk.TclError:
            pass


__all__ = ["SessionHeader"]
