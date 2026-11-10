"""Стартовий екран: велике поле запиту, вибір теки й швидкі підказки.

Це те, що користувач бачить одразу після запуску — як у сучасних агентних
редакторах: спершу запит або тека, а вже потім повний інтерфейс.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import theme, widgets


class WelcomeScreen(tk.Frame):
    """Стартовий екран із великим композером і списком підказок."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_submit: Optional[Callable[[str], None]] = None,
        on_open_folder: Optional[Callable[[], None]] = None,
        on_hint: Optional[Callable[[str, str], None]] = None,
        workspace: str = "",
        model_label: str = "",
    ) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.on_submit = on_submit
        self.on_open_folder = on_open_folder
        self.on_hint = on_hint
        self.workspace = workspace
        self.model_label = model_label
        self._build()
        self._set_placeholder(True)
        self.after(80, self._focus_box)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        # Верх і низ — «пружини» однакової ваги: вміст стоїть по центру, як на
        # макеті, а не тулиться до верхнього краю.
        self.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        holder = tk.Frame(self, bg=theme.BG)
        holder.grid(row=1, column=0, sticky="ew", padx=36)
        holder.columnconfigure(0, weight=1)

        inner = tk.Frame(holder, bg=theme.BG)
        inner.grid(row=0, column=0, sticky="ew")
        inner.columnconfigure(0, weight=1)

        # ── рядок теки + моделі
        top = tk.Frame(inner, bg=theme.BG)
        top.grid(row=0, column=0, sticky="ew", padx=2, pady=(0, 10))
        top.columnconfigure(1, weight=1)

        self.folder_chip = widgets.Chip(
            top,
            self._folder_text(),
            self.on_open_folder,
            font=("Segoe UI", 9),
        )
        self.folder_chip.pack(side="left")

        self.model_chip = tk.Label(
            top, text=self.model_label or "модель: автоматично",
            bg=theme.BG, fg=theme.FG_FAINT, font=("Segoe UI", 9),
        )
        self.model_chip.pack(side="right")

        # ── композер
        card = tk.Frame(inner, bg=theme.BORDER_SOFT, bd=0, highlightthickness=0)
        card.grid(row=1, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)
        self.card = card

        body = tk.Frame(card, bg=theme.BG_INPUT)
        body.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        self.placeholder = "Сплануй, збери або / для скілів, @ для контексту"
        self.box = tk.Text(
            body, height=3, wrap="word", bd=0, highlightthickness=0,
            background=theme.BG_INPUT, foreground=theme.FG_BRIGHT,
            insertbackground=theme.FG_BRIGHT, font=("Segoe UI", 12),
            padx=14, pady=12, spacing1=2, spacing3=3,
        )
        self.box.grid(row=0, column=0, sticky="ew")
        self.box.bind("<Return>", self._on_return)
        self.box.bind("<Shift-Return>", lambda _e: None)
        self.box.bind("<FocusIn>", self._on_focus_in)
        self.box.bind("<FocusOut>", self._on_focus_out)
        self.box.bind("<KeyRelease>", self._on_key)
        # Перше натискання клавіші (не службової) прибирає плейсхолдер.
        for sequence in ("<Key>", "<Button-1>", "<Control-v>"):
            self.box.bind(sequence, self._on_first_input, add="+")

        footer = tk.Frame(body, bg=theme.BG_INPUT)
        footer.grid(row=1, column=0, sticky="ew", padx=(10, 10), pady=(0, 10))
        footer.columnconfigure(1, weight=1)

        widgets.IconButton(footer, "＋", self._add_context, bg=theme.BG_INPUT,
                           fg=theme.FG_DIM, font=("Segoe UI", 13),
                           tooltip="Додати файл до запиту").grid(row=0, column=0, sticky="w")

        right = tk.Frame(footer, bg=theme.BG_INPUT)
        right.grid(row=0, column=2, sticky="e")

        self.hint_label = tk.Label(
            right, text=("Enter — надіслати · Shift+Enter — новий рядок"
                         if not self._has_box_text() else ""),
            bg=theme.BG_INPUT, fg=theme.FG_FAINT, font=("Segoe UI", 9),
        )
        self.hint_label.pack(side="left", padx=(0, 10))

        self.send_btn = widgets.IconButton(
            right, "▲", self._submit, bg=theme.ACCENT, fg=theme.ON_ACCENT,
            font=("Segoe UI", 11), tooltip="Надіслати (Enter)",
        )
        self.send_btn.pack(side="left")

        # ── підказки
        hints = tk.Frame(inner, bg=theme.BG)
        hints.grid(row=2, column=0, sticky="ew", pady=(14, 0))

        for icon, title, subtitle, prompt in (
            ("🎨", "Збери з дизайну", "Перетвори макет на робочий інтерфейс",
             "Перетвори цей макет на робочий інтерфейс у цьому проєкті."),
            ("🚀", "Розгорни прототип", "Підніми проєкт, щоб його можна було відкрити",
             "Запусти проєкт локально й покажи, як його відкрити."),
            ("📋", "Почни з плану", "Узгодь підхід, перш ніж писати код",
             "Склади план реалізації задачі й узгодь його зі мною перед кодом."),
            ("🐞", "Розбери помилку", "Знайди першопричину й виправ",
             "Знайди першопричину цієї помилки й виправ її."),
        ):
            self._hint_row(hints, icon, title, subtitle, prompt)

    def _hint_row(self, parent: tk.Misc, icon: str, title: str, subtitle: str,
                  prompt: str) -> None:
        row = tk.Frame(parent, bg=theme.BG, cursor="hand2")
        row.pack(fill="x", pady=1)

        icon_label = tk.Label(row, text=icon, bg=theme.BG, fg=theme.FG,
                              font=("Segoe UI", 11), width=3, anchor="w")
        icon_label.pack(side="left", padx=(4, 0))

        text = tk.Frame(row, bg=theme.BG)
        text.pack(side="left", fill="x", expand=True)
        title_label = tk.Label(text, text=title, bg=theme.BG, fg=theme.FG_BRIGHT,
                               font=("Segoe UI", 10, "bold"), anchor="w")
        title_label.pack(side="left")
        sub_label = tk.Label(text, text="   " + subtitle, bg=theme.BG, fg=theme.FG_FAINT,
                             font=("Segoe UI", 9), anchor="w")
        sub_label.pack(side="left")

        def enter(_e=None):
            for widget in (row, icon_label, text, title_label, sub_label):
                widget.configure(bg=theme.BG_HOVER)

        def leave(_e=None):
            for widget in (row, icon_label, text, title_label, sub_label):
                widget.configure(bg=theme.BG)

        def click(_e=None):
            if self.on_hint is not None:
                self.on_hint(title, prompt)
            self.set_text(prompt)

        for widget in (row, icon_label, text, title_label, sub_label):
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
            widget.bind("<Button-1>", click)

    # ── ввід ───────────────────────────────────────────────────────────────
    def _folder_text(self) -> str:
        if not self.workspace:
            return "📁 Обрати папку проєкту"
        name = Path(self.workspace).name or self.workspace
        return f"📁 {name}"

    def set_workspace(self, path: str) -> None:
        self.workspace = path
        self.folder_chip.configure(text=self._folder_text())

    def set_model(self, label: str) -> None:
        self.model_label = label
        self.model_chip.configure(
            text=label or "модель: автоматично",
            fg=theme.FG_DIM if label else theme.FG_FAINT,
        )

    def _has_box_text(self) -> bool:
        return bool(self.box.get("1.0", "end-1c").strip())

    def _on_focus_in(self, _event=None) -> None:
        # Плейсхолдер лишається видимим і у фокусі — як на макеті; він
        # зникає лише тоді, коли користувач справді почне друкувати.
        return None

    def _on_focus_out(self, _event=None) -> None:
        if not self._has_text():
            self._set_placeholder(True)

    def _has_text(self) -> bool:
        return not getattr(self, "_placeholder_on", False) and self._has_box_text()

    def _set_placeholder(self, show: bool) -> None:
        self.box.configure(state="normal")
        if show:
            self.box.delete("1.0", "end")
            self.box.insert("1.0", self.placeholder)
            self.box.configure(fg=theme.FG_FAINT)
            self._placeholder_on = True
        else:
            if getattr(self, "_placeholder_on", False):
                self.box.delete("1.0", "end")
            self._placeholder_on = False
            self.box.configure(fg=theme.FG_BRIGHT)

    _placeholder_on = False

    def _on_first_input(self, event=None) -> None:
        """Прибрати плейсхолдер щойно користувач почав щось вводити."""
        if not getattr(self, "_placeholder_on", False):
            return
        keysym = getattr(event, "keysym", "") if event is not None else ""
        # Службові клавіші не мають стирати підказку.
        if keysym in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                      "Caps_Lock", "Tab", "Left", "Right", "Up", "Down", "Home", "End",
                      "Escape", "Super_L", "Super_R", "Insert", "Delete"}:
            return
        self._placeholder_on = False
        self.box.delete("1.0", "end")
        self.box.configure(fg=theme.FG_BRIGHT)

    def _on_key(self, _event=None) -> None:
        has = self._has_text()
        self.hint_label.configure(
            text="" if has else "Enter — надіслати · Shift+Enter — новий рядок")

    def _on_return(self, event) -> str:
        if event.state & 0x0001:
            return ""
        self._submit()
        return "break"

    def get_text(self) -> str:
        if getattr(self, "_placeholder_on", False):
            return ""
        return self.box.get("1.0", "end-1c").strip()

    def set_text(self, text: str) -> None:
        self._placeholder_on = False
        self.box.configure(fg=theme.FG_BRIGHT)
        self.box.delete("1.0", "end")
        self.box.insert("1.0", text)
        self.box.focus_set()
        self._on_key()

    def clear(self) -> None:
        self._placeholder_on = False
        self.box.delete("1.0", "end")
        self._set_placeholder(True)

    def _submit(self) -> None:
        text = self.get_text()
        if not text:
            self._focus_box()
            return
        if self.on_submit is not None:
            self.on_submit(text)

    def _focus_box(self) -> None:
        try:
            self.box.focus_set()
        except tk.TclError:
            return
        if not self._has_box_text():
            self._set_placeholder(True)

    def _add_context(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(parent=self, title="Додати файл до запиту")
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")[:6000]
        except OSError as exc:
            self.set_text(f"[не вдалось прочитати {Path(path).name}: {exc}]")
            return
        self.set_text(f"{self.get_text()}\n\n```{Path(path).name}\n{content}\n```".strip())
