"""Панель «Структура файлу»: живе дерево AST із пошуком і помилками.

Показує все, що знайшов AST-аналіз: класи, методи, функції (разом з
асинхронними й властивостями), імпорти та змінні. Оновлюється в реальному
часі під час набору, а синтаксичні помилки видно одразу з номером рядка.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import ast_index, theme, widgets
from .editor import CodeEditor

MAX_ROWS = 300


class OutlinePanel(tk.Frame):
    """Символи поточного файлу з живого AST."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme,
                 *, on_goto: Optional[Callable[[int], None]] = None,
                 bg: str = theme.BG_ALT) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.bg = bg
        self.on_goto = on_goto
        self.query = ""
        self.show_imports = True
        self.show_variables = False
        self._rows: list[tk.Frame] = []
        self._lines: dict[tk.Frame, int] = {}
        self._active_line = 0
        self._editor = None
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        head = tk.Frame(self, bg=self.bg)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(0, weight=1)

        self.title = tk.Label(head, text="СТРУКТУРА", bg=self.bg, fg=theme.FG_FAINT,
                              font=("Segoe UI", 8, "bold"), anchor="w")
        self.title.grid(row=0, column=0, sticky="w")

        self.count_label = tk.Label(head, text="", bg=self.bg, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8))
        self.count_label.grid(row=0, column=1, sticky="e")

        # пошук по символах
        search_row = tk.Frame(self, bg=self.bg)
        search_row.grid(row=1, column=0, sticky="ew", padx=(10, 8), pady=(2, 4))
        search_row.columnconfigure(0, weight=1)

        self.search_entry = tk.Entry(
            search_row, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=("Segoe UI", 8), bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT,
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", ipady=3)
        self.search_entry.bind("<KeyRelease>", self._on_search)
        self.search_entry.bind("<Escape>", lambda _e: (self.search_entry.delete(0, "end"),
                                                       self._on_search(None)))

        widgets.IconButton(search_row, "⇢", self._toggle_imports, bg=theme.BG_INPUT,
                           fg=theme.FG_DIM, font=("Segoe UI", 8),
                           tooltip="Показати/сховати імпорти").grid(row=0, column=1, padx=(3, 0))
        widgets.IconButton(search_row, "▪", self._toggle_variables, bg=theme.BG_INPUT,
                           fg=theme.FG_DIM, font=("Segoe UI", 8),
                           tooltip="Показати/сховати змінні").grid(row=0, column=2, padx=(3, 0))

        self.scroll = widgets.ScrollFrame(self, bg=self.bg)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 6))
        self.list_host = self.scroll.inner

        # смуга помилки
        self.problem_bar = tk.Frame(self, bg=self.bg)
        self.problem_label = tk.Label(self.problem_bar, text="", bg=self.bg, fg=theme.ERROR,
                                      font=("Segoe UI", 8), anchor="w", justify="left",
                                      wraplength=210)
        self.problem_label.pack(fill="x", padx=(12, 8), pady=(0, 6))

    # ── керування ──────────────────────────────────────────────────────────
    def _on_search(self, _event=None) -> None:
        self.query = self.search_entry.get().strip()
        self.refresh()

    def _toggle_imports(self) -> None:
        self.show_imports = not self.show_imports
        self.refresh()

    def _toggle_variables(self) -> None:
        self.show_variables = not self.show_variables
        self.refresh()

    # ── наповнення ─────────────────────────────────────────────────────────
    def update_for(self, editor: Optional[CodeEditor]) -> None:
        """Перебудувати панель за редактором."""
        if editor is None or not editor.filename.endswith(".py"):
            self._clear()
            self._hint("Структура доступна для Python-файлів.")
            self.count_label.configure(text="")
            return
        result = getattr(editor, "analysis", None)
        if result is None:
            from . import ast_index as index

            result = index.analyse(editor.get_text())
            editor.analysis = result
        self._editor = editor
        self.show_analysis(result, editor.current_line())

    def refresh(self) -> None:
        """Перемалювати поточний результат (пошук, фільтри)."""
        editor = getattr(self, "_editor", None)
        result = getattr(editor, "analysis", None) if editor is not None else None
        if result is None:
            self._clear()
            self._hint("Відкрий .py файл, щоб побачити структуру.")
            return
        line = editor.current_line() if editor is not None else 0
        self.show_analysis(result, line)

    def show_analysis(self, result, active_line: int = 0) -> None:
        """Показати готовий результат AST-аналізу."""
        self._clear()
        self._active_line = active_line
        self._result = result
        if result is None:
            self._hint("Немає даних аналізу.")
            return

        # ── синтаксична помилка
        if getattr(result, "problem", None) is not None:
            problem = result.problem
            self.problem_label.configure(
                text=f"Рядок {problem.line}: {problem.short}")
            self.problem_bar.grid(row=3, column=0, sticky="ew")
        else:
            self.problem_bar.grid_remove()

        symbols = list(result.outline or [])
        if self.show_imports:
            for imported in getattr(result, "imports", []):
                symbols.append(imported)
        if self.show_variables:
            symbols.extend(getattr(result, "variables", []))

        if self.query:
            symbols = [sym for sym in symbols if sym.matches(self.query)]

        metrics = result.metrics
        self.count_label.configure(
            text=f"{metrics.functions}ƒ · {metrics.classes}◈ · {metrics.imports}⇢")

        if not symbols:
            self._hint("Нічого не знайдено" if self.query
                       else "У файлі немає функцій чи класів.")
            return

        symbols.sort(key=lambda sym: (sym.line, sym.depth))
        for symbol in symbols[:MAX_ROWS]:
            self._row(symbol)
        if len(symbols) > MAX_ROWS:
            tk.Label(self.list_host, text=f"… ще {len(symbols) - MAX_ROWS}",
                     bg=self.bg, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                     anchor="w").pack(fill="x", padx=(12, 8))

    def highlight_line(self, line: int) -> None:
        """Підсвітити рядок, у якому зараз курсор."""
        self._active_line = line
        for row in self._rows:
            row_line = self._lines.get(row, 0)
            symbol = getattr(row, "_symbol", None)
            inside = symbol is not None and symbol.line <= line <= (symbol.end_line or symbol.line)
            try:
                row.configure(bg=theme.BG_ACTIVE if inside else self.bg)
                for child in row.winfo_children():
                    child.configure(bg=theme.BG_ACTIVE if inside else self.bg)
            except tk.TclError:
                continue

    def _clear(self) -> None:
        for child in self.list_host.winfo_children():
            child.destroy()
        self._rows.clear()
        self._lines.clear()

    def _hint(self, text: str) -> None:
        import tkinter as tk_local

        tk_local.Label(self.list_host, text=text, bg=self.bg, fg=theme.FG_FAINT,
                       font=("Segoe UI", 8), justify="left", anchor="w",
                       wraplength=210).pack(fill="x", padx=(6, 4), pady=6)

    def _row(self, symbol) -> None:
        """Один рядок дерева."""
        indent = 6 + symbol.depth * 12
        row = tk.Frame(self.list_host, bg=self.bg, cursor="hand2")
        row.pack(fill="x", padx=(0, 2))
        row.columnconfigure(0, weight=1)
        row._symbol = symbol  # type: ignore[attr-defined]

        label = tk.Label(row, text=symbol.label, bg=self.bg,
                         fg=theme.color_for(symbol.colour_key), font=("Segoe UI", 9),
                         anchor="w", justify="left")
        label.grid(row=0, column=0, sticky="ew", padx=(indent, 4), pady=1)

        line_label = tk.Label(row, text=str(symbol.line), bg=self.bg,
                              fg=theme.FG_FAINT, font=("Segoe UI", 7))
        line_label.grid(row=0, column=1, sticky="e", padx=(0, 6))

        tip_parts = [f"{symbol.kind} · рядок {symbol.line}"]
        if symbol.signature:
            tip_parts.append(f"підпис: {symbol.name}{symbol.signature}")
        if symbol.decorators:
            tip_parts.append("декоратори: " + ", ".join(symbol.decorators))
        if symbol.docstring:
            tip_parts.append(symbol.docstring)
        tip_parts.append(f"рядків: {symbol.span}")
        widgets.Tip(label, "\n".join(tip_parts))

        in_body = symbol.line <= self._active_line <= (symbol.end_line or symbol.line)
        if in_body:
            for widget in (row, label, line_label):
                widget.configure(bg=theme.BG_ACTIVE)

        def open_symbol(_e=None):
            if self.on_goto:
                self.on_goto(symbol.line)

        for widget in (row, label, line_label):
            widget.bind("<Button-1>", open_symbol)

        self._rows.append(row)
        self._lines[row] = symbol.line
