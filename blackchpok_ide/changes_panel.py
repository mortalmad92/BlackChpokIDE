"""Панель «Зміни»: файли зі статистикою ``+додано -видалено`` та підсвіткою.

Показує те саме, що сучасні агентні редактори: загальний підсумок і список
змінених файлів. Клік по файлу відкриває його; контекстне меню дає diff.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import browser_panel, diff_stats, theme, widgets

MAX_ROWS = 200


class ChangesPanel(tk.Frame):
    """Список змінених файлів із підсумком."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        root_provider: Callable[[], Optional[Path]],
        *,
        on_open_path: Optional[Callable[[Path], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_show_diff: Optional[Callable[[Path], None]] = None,
        synchronous: Optional[bool] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.root_provider = root_provider
        self.on_open_path = on_open_path
        self.on_status = on_status
        self.on_show_diff = on_show_diff
        #: Синхронний перший скан. ``None`` = вирішити самому: у прихованому
        #: вікні (тести, скриншоти) фоновий скан не встигає до першого
        #: `update()`, тож панель показувала б «Обчислюю…» замість даних.
        self.synchronous = bool(synchronous) if synchronous is not None else \
            self._starts_hidden(master)
        self.changeset = diff_stats.ChangeSet(files=[])
        self._rows: list[tk.Frame] = []
        #: True, поки фоновий скан іде — щоб не запускати другий.
        self._scanning = False
        #: Номер останнього запиту скану: результати старих ігноруємо.
        self._scan_token = 0
        self._build()
        # Стан показуємо одразу, але БЕЗ синхронного обходу диска.
        #
        # Раніше тут стояв `self.refresh()`, який у конструкторі обходив
        # усі `.bak`-файли й рахував порядковий diff: 311 файлів = 4.8 с,
        # тобто 85% часу запуску застосунку — до першої появи вікна.
        # Тепер перший скан іде у фоні, а панель одразу каже «обчислюю».
        if self.synchronous:
            # Тести й скрипти можуть попросити синхронний режим: тоді
            # панель готова одразу після конструктора.
            self._scan_blocking()
        else:
            self._empty("Обчислюю зміни…")
            self.after(80, self.refresh)

    @staticmethod
    def _starts_hidden(master: tk.Misc) -> bool:
        """Чи вікно на момент побудови приховане (тестовий контекст).

        У тестах і скриншот-скриптах вікно створюють через ``withdraw()``:
        фоновий потік не встигає завершитись до першого ``update()``, і
        панель показувала б «Обчислюю…» замість справжніх даних.
        """
        try:
            top = master.winfo_toplevel()
            return not bool(top.winfo_viewable())
        except (tk.TclError, AttributeError):
            return False

    def _scan_blocking(self) -> None:
        """Синхронний скан (тести, скриншоти). Не використовується у вікні."""
        root = self.root_provider() if self.root_provider else None
        self._clear_rows()
        if not root or not Path(root).is_dir():
            self.summary.configure(text="")
            self.source_label.configure(text="")
            self._empty("Спочатку відкрий теку проєкту")
            return
        try:
            changeset = diff_stats.detect_changes(Path(root))
        except Exception as exc:  # noqa: BLE001 - панель не має ламати вікно
            self._empty(f"Не вдалось прочитати зміни: {exc}")
            return
        self._paint(changeset)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="ЗМІНИ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")

        self.summary = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                font=self.fonts.mono_small, anchor="e")
        self.summary.grid(row=0, column=1, sticky="e", padx=(6, 0))

        bar = tk.Frame(self, bg=theme.BG_ALT)
        bar.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(2, 6))
        widgets.Chip(bar, "⟳ Оновити", self.refresh, font=("Segoe UI", 8)).pack(
            side="left", padx=(0, 4))
        self.source_label = tk.Label(bar, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                     font=("Segoe UI", 8))
        self.source_label.pack(side="left")

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.host = self.scroll.inner

    # ── дані ───────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Перерахувати зміни у ФОНІ й показати, коли готово.

        Обхід диска й порядковий diff — найдорожча операція застосунку.
        Виконувати її в головному потоці не можна: вікно «замерзає».
        Тому скан іде в окремому потоці, а результат повертається через
        ``after`` у головний потік (tkinter не потокобезпечний).
        """
        root = self.root_provider() if self.root_provider else None
        if not root or not Path(root).is_dir():
            self._clear_rows()
            self.summary.configure(text="")
            self.source_label.configure(text="")
            self._empty("Спочатку відкрий теку проєкту")
            return
        if self._scanning:
            return          # попередній скан ще не завершився
        self._scanning = True
        self._scan_token += 1
        token = self._scan_token
        if not self._rows:
            self._empty("Обчислюю зміни…")

        def work() -> None:
            changeset: Optional[diff_stats.ChangeSet]
            error = ""
            try:
                changeset = diff_stats.detect_changes(Path(root))
            except Exception as exc:  # noqa: BLE001 - панель не має ламати вікно
                changeset = None
                error = str(exc)
            self._scanned(token, changeset, error)

        threading.Thread(target=work, daemon=True).start()

    def _scanned(self, token: int, changeset, error: str) -> None:
        """Результат фонового скану — у головному потоці."""
        try:
            if not self.winfo_exists():
                return
            self.after(0, lambda: self._apply_scan(token, changeset, error))
        except (tk.TclError, RuntimeError):
            # Віджет уже знищено або вікно закривається — тихо виходимо.
            self._scanning = False

    def _apply_scan(self, token: int, changeset, error: str) -> None:
        """Показати результат, якщо він ще актуальний."""
        self._scanning = False
        if token != self._scan_token:
            return          # надійшов новіший запит — цей застарілий
        self._clear_rows()
        if changeset is None:
            self.changeset = diff_stats.ChangeSet(files=[])
            self._empty(f"Не вдалось прочитати зміни: {error}")
            return
        self._paint(changeset)

    def _paint(self, changeset) -> None:
        """Намалювати готовий набір змін (спільне для обох режимів)."""
        self.changeset = changeset
        # Без git панель усе одно показує зміни (порівнює .bak із диском),
        # але користувач має розуміти, чому немає історії комітів.
        if not diff_stats.git_available():
            self._git_hint()

        cs = self.changeset
        if cs.is_empty:
            self.summary.configure(text="")
            self.source_label.configure(text="")
            self._empty("Змін немає")
            return

        self.summary.configure(text=cs.summary_text)
        source_text = {
            "git": "git",
            "backup": "резервні копії",
        }.get(cs.source, cs.source)
        self.source_label.configure(text=f"· {source_text} · {len(cs.files)} файлів")

        for change in cs.top(MAX_ROWS):
            self._row(change)

        if len(cs.files) > MAX_ROWS:
            tk.Label(self.host, text=f"… ще {len(cs.files) - MAX_ROWS}", bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w").pack(
                fill="x", padx=(8, 0), pady=2)

    def _clear_rows(self) -> None:
        for child in self.host.winfo_children():
            child.destroy()
        self._rows.clear()

    def _empty(self, text: str) -> None:
        tk.Label(self.host, text=text, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 9), justify="left", anchor="w",
                 wraplength=230).pack(fill="x", padx=(6, 4), pady=8)

    def _git_hint(self) -> None:
        """Підказка, що робити без git, з кнопками дії.

        Панель показує зміни й без git (порівнюючи резервні копії), але
        користувач має знати, чому немає історії комітів, і мати швидкий
        шлях це виправити.
        """
        card = tk.Frame(self.host, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                        highlightbackground=theme.BORDER)
        card.pack(fill="x", padx=(4, 2), pady=(4, 6))

        tk.Label(card, text="git не встановлено",
                 bg=theme.BG_CARD, fg=theme.WARN,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(
            fill="x", padx=8, pady=(6, 0))
        tk.Label(card,
                 text="Історія комітів і точний diff недоступні. "
                      "Зміни показуються порівнянням резервних копій.",
                 bg=theme.BG_CARD, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                 anchor="w", justify="left", wraplength=210).pack(
            fill="x", padx=8, pady=(2, 4))

        actions = tk.Frame(card, bg=theme.BG_CARD)
        actions.pack(fill="x", padx=6, pady=(0, 6))
        widgets.Chip(actions, "↓ Встановити git", self._install_git,
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        widgets.Chip(actions, "Перевірити", self.refresh,
                     font=("Segoe UI", 8)).pack(side="left")

    def _install_git(self) -> None:
        """Показати сторінку завантаження git у вбудованому браузері IDE.

        Раніше тут викликався ``webbrowser.open``: користувача викидало з
        IDE в Chrome, і повертатись доводилось вручну. Тепер сторінка
        відкривається поруч, у колонці Live Preview.
        """
        url = "https://git-scm.com/download/win"
        opened = browser_panel.open_url(url)
        if opened:
            message = ("Сторінку завантаження git відкрито у вбудованому браузері. "
                       "Після встановлення натисни «Перевірити».")
        else:
            message = f"Відкрий вручну: {url}"
        if self.on_status:
            self.on_status(message)
        self._empty(message)

    def _row(self, change: diff_stats.FileChange) -> None:
        row = tk.Frame(self.host, bg=theme.BG_ALT, cursor="hand2")
        row.pack(fill="x", padx=(0, 2), pady=1)
        row.columnconfigure(0, weight=1)

        path_label = tk.Label(row, text=change.path, bg=theme.BG_ALT, fg=theme.FG_DIM,
                              font=("Segoe UI", 8), anchor="w", justify="left")
        path_label.grid(row=0, column=0, sticky="ew", padx=(6, 6), pady=2)

        stat = tk.Label(row, text=change.stat_text, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                        font=self.fonts.mono_small, anchor="e")
        stat.grid(row=0, column=1, sticky="e", padx=(0, 6), pady=2)

        # Зелений/червоний як у звичайному diff-огляді.
        colour = {
            "added": theme.SUCCESS,
            "deleted": theme.ERROR,
            "modified": theme.WARN,
            "renamed": theme.ACCENT,
        }.get(change.status, theme.FG_FAINT)
        path_label.configure(fg=colour)

        def enter(_e=None):
            for widget in (row, path_label, stat):
                widget.configure(bg=theme.BG_HOVER)
            path_label.configure(fg=theme.FG_BRIGHT)

        def leave(_e=None):
            for widget in (row, path_label, stat):
                widget.configure(bg=theme.BG_ALT)
            path_label.configure(fg=colour)

        def open_file(_e=None):
            root = self.root_provider() if self.root_provider else None
            if not root or not self.on_open_path:
                return
            target = Path(root) / change.path
            if target.exists():
                self.on_open_path(target)
            elif self.on_status:
                self.on_status(f"Файл не існує: {change.path}")

        for widget in (row, path_label, stat):
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
            widget.bind("<Button-1>", open_file)
            widget.bind("<Button-3>", lambda e, c=change: self._menu(c, e))

        self._rows.append(row)

    def _menu(self, change: diff_stats.FileChange, event) -> None:
        root = self.root_provider() if self.root_provider else None
        target = (Path(root) / change.path) if root else None
        items: list[tuple[str, Optional[Callable[[], None]]]] = [
            ("Відкрити", lambda: target and target.exists() and self.on_open_path
             and self.on_open_path(target)),
            ("Показати diff", lambda: self.on_show_diff and target and self.on_show_diff(target)),
            ("", None),
            ("Копіювати шлях", lambda: self._copy(change.path)),
        ]
        widgets.context_menu(self, items, event)

    def _copy(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            if self.on_status:
                self.on_status(f"Скопійовано: {text}")
        except tk.TclError:
            pass
