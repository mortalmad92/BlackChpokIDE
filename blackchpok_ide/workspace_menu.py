"""Спливне меню робочого простору (теки проєкту) у композері чату.

Це той самий вибір, що й у шапці, але **там, де користувач пише**: у
сучасних агентних редакторах тека проєкту й режим стоять пігулками поруч із
полем вводу, і перемкнути їх можна, не йдучи в інше меню:

    ┌──────────────────────────────────────────────┐
    │ 🗂 blackchpock_ai ▾   ◈ Агент ▾              │
    └──────────────────────────────────────────────┘
            │
            ▼
    ┌──────────────────────────────────────────────┐
    │ РОБОЧИЙ ПРОСТІР                              │
    │ 🗂 blackchpock_ai                        ✓   │
    │ ──────────────────────────────────────────── │
    │ 🗂 ai-sandbox                                │
    │ 🗂 site-build                                │
    │ ──────────────────────────────────────────── │
    │ ＋ Додати робочий простір…                    │
    └──────────────────────────────────────────────┘

Модуль показує лише **реальні** теки: поточну й ті, що справді є в списку
останніх. Неіснуючі пункти не малюються, бо вибір «мертвої» теки раніше
виглядав як поломка кнопки.

Нічого не вирішує сам: вибір віддається колбеками оболонці
(``on_pick`` / ``on_add``), яка й застосовує теку через ``set_workspace``.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import theme, widgets

ROW_HEIGHT = 34


class WorkspaceMenu(tk.Toplevel):
    """Меню робочого простору: поточна тека, останні, «додати»."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        current: str = "",
        recent: Iterable[str] = (),
        on_pick: Optional[Callable[[str], None]] = None,
        on_add: Optional[Callable[[], None]] = None,
        on_forget: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.current = str(current or "")
        self.on_pick = on_pick
        self.on_add = on_add
        self.on_forget = on_forget
        self._rows: list[tk.Frame] = []
        self._anchor: Optional[tk.Misc] = None
        self._outside_bid: Optional[str] = None
        #: Скільки останніх тек показуємо (решта лишається в шапці).
        self.recent = self._existing_recent(recent)
        self.withdraw()
        self.overrideredirect(True)
        widgets.register_popover(self)
        self.configure(bg=theme.BORDER_SOFT)
        self._build()

    # ── дані ───────────────────────────────────────────────────────────────
    def _existing_recent(self, recent: Iterable[str]) -> list[str]:
        """Лише ті теки, що справді існують і не дублюють поточну."""
        result: list[str] = []
        current = self._norm(self.current)
        for raw in recent:
            text = str(raw or "").strip()
            if not text:
                continue
            if self._norm(text) == current:
                continue
            if not Path(text).is_dir():
                continue
            if any(self._norm(text) == self._norm(item) for item in result):
                continue
            result.append(text)
            if len(result) >= 8:
                break
        return result

    @staticmethod
    def _name_of(path: str) -> str:
        """Назва теки для підпису; корінь диска лишається як є."""
        text = str(path or "").strip()
        if not text:
            return ""
        name = Path(text).name
        return name or text

    @staticmethod
    def _norm(path: str) -> str:
        text = str(path or "").strip().rstrip("\\/")
        try:
            return str(Path(text).resolve()).lower()
        except (OSError, ValueError):
            return text.lower()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ELEVATED, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        tk.Label(body, text="РОБОЧИЙ ПРОСТІР", bg=theme.BG_ELEVATED, fg=theme.FG_FAINT,
                 font=self.fonts.ui_tiny, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(8, 4))

        host = tk.Frame(body, bg=theme.BG_ELEVATED)
        host.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))
        host.columnconfigure(0, weight=1)

        self._row(host, self._name_of(self.current) or "теку не обрано",
                  self.current, active=True,
                  command=lambda: self._pick(self.current))
        if self.recent:
            tk.Frame(body, bg=theme.BORDER, height=1).grid(
                row=2, column=0, sticky="ew", padx=10, pady=4)
            other = tk.Frame(body, bg=theme.BG_ELEVATED)
            other.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 2))
            other.columnconfigure(0, weight=1)
            for path in self.recent:
                self._row(other, self._name_of(path) or path, path,
                          command=lambda p=path: self._pick(p),
                          forgettable=True)

        tk.Frame(body, bg=theme.BORDER, height=1).grid(
            row=4, column=0, sticky="ew", padx=10, pady=4)

        add = tk.Frame(body, bg=theme.BG_ELEVATED, cursor="hand2", height=ROW_HEIGHT)
        add.grid(row=5, column=0, sticky="ew", padx=4, pady=(0, 6))
        add.columnconfigure(1, weight=1)
        self._add_icon = tk.Label(add, text="＋", bg=theme.BG_ELEVATED, fg=theme.ACCENT,
                                  font=("Segoe UI", 10), anchor="center")
        self._add_icon.grid(row=0, column=0, padx=(8, 6), pady=6)
        self._add_label = tk.Label(add, text="Додати робочий простір…",
                                   bg=theme.BG_ELEVATED, fg=theme.FG,
                                   font=("Segoe UI", 9), anchor="w")
        self._add_label.grid(row=0, column=1, sticky="ew", pady=6)
        self._hover_bind(add, [self._add_icon, self._add_label],
                         theme.BG_ELEVATED, self._add)

    def _row(self, host: tk.Misc, title: str, path: str, *, active: bool = False,
             command: Optional[Callable[[], None]] = None,
             forgettable: bool = False) -> tk.Frame:
        bg = theme.BG_ACTIVE if active else theme.BG_ELEVATED
        row = tk.Frame(host, bg=bg, cursor="hand2", height=ROW_HEIGHT)
        row.pack(fill="x", pady=1)
        row.columnconfigure(1, weight=1)

        icon = tk.Label(row, text="🗂", bg=bg,
                        fg=theme.ACCENT if active else theme.FG_DIM,
                        font=("Segoe UI", 10), anchor="center")
        icon.grid(row=0, column=0, padx=(8, 6), pady=6)

        name = tk.Label(row, text=title, bg=bg,
                        fg=theme.FG_BRIGHT if active else theme.FG,
                        font=("Segoe UI", 9, "bold" if active else "normal"), anchor="w")
        name.grid(row=0, column=1, sticky="ew", pady=6)

        mark = tk.Label(row, text="✓" if active else "", bg=bg, fg=theme.ACCENT,
                        font=("Segoe UI", 9), width=2, anchor="center")
        mark.grid(row=0, column=2, padx=(4, 4 if forgettable else 8), pady=6)

        forget = None
        if forgettable:
            forget = tk.Label(row, text="×", bg=bg, fg=theme.FG_FAINT,
                              font=("Segoe UI", 11), width=2, anchor="center",
                              cursor="hand2")
            forget.grid(row=0, column=3, padx=(0, 6), pady=6)
            widgets.Tip(forget, "Прибрати зі списку. Папку на диску не чіпає.")
            forget.bind("<Button-1>", lambda _event, p=path: self._forget(p))

        widgets.Tip(icon, path or "теку не обрано")
        self._rows.append(row)
        self._hover_bind(row, [icon, name, mark], bg,
                         command or (lambda: self._pick(path)),
                         extra=[forget] if forget is not None else ())
        return row

    def _hover_bind(self, row: tk.Misc, labels: list[tk.Misc], bg: str,
                    command: Callable[[], None],
                    extra: tuple = ()) -> None:
        painted = [item for item in (*labels, *extra) if item is not None]

        def enter(_e=None) -> None:
            try:
                row.configure(bg=theme.BG_HOVER)
                for label in painted:
                    label.configure(bg=theme.BG_HOVER)
            except tk.TclError:
                pass

        def leave(_e=None) -> None:
            # Базовий фон приходить із рядка: у активного пункту він інший,
            # і без цього після наведення позначка «✓» гасла.
            try:
                row.configure(bg=bg)
                for label in painted:
                    label.configure(bg=bg)
            except tk.TclError:
                pass

        def click(_e=None) -> None:
            self.hide()
            command()

        for widget in (row, *labels):
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
            widget.bind("<Button-1>", click)
        for widget in extra:
            if widget is None:
                continue
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)

    # ── дії ────────────────────────────────────────────────────────────────
    def _pick(self, path: str) -> None:
        if not path:
            if self.on_add is not None:
                self.on_add()
            return
        if not Path(path).is_dir():
            return
        if self.on_pick is not None:
            self.on_pick(path)

    def _add(self) -> None:
        if self.on_add is not None:
            self.on_add()

    def _forget(self, path: str) -> None:
        """Прибрати теку зі списку недавніх. Саму папку не видаляє."""
        self.hide()
        if self.on_forget is not None:
            self.on_forget(path)

    # ── показ ──────────────────────────────────────────────────────────────
    def show_at(self, anchor: tk.Misc) -> None:
        """Показати під кнопкою-пігулкою (у композері)."""
        self._anchor = anchor
        try:
            self.deiconify()
            self.update_idletasks()
            width = max(300, anchor.winfo_width())
            height = max(80, self.winfo_reqheight())
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() - height - 6
            if y < 0:
                y = anchor.winfo_rooty() + anchor.winfo_height() + 6
            x, y = widgets.clamp_to_screen(self, x, y, width, height)
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.update_idletasks()
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.lift()
            self._bind_outside_close()
        except tk.TclError:
            return

    def hide(self) -> None:
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
            self.hide()
            return
        widget = under
        while widget is not None:
            if widget is self:
                return
            widget = getattr(widget, "master", None)
        self.hide()

    def _unbind_outside_close(self) -> None:
        if self._outside_bid is None:
            return
        try:
            self.winfo_toplevel().unbind("<Button-1>", self._outside_bid)
        except tk.TclError:
            pass
        self._outside_bid = None


__all__ = ["WorkspaceMenu"]
