"""Палітра команд (Ctrl+Shift+P), швидке відкриття файлів (Ctrl+P), пошук (Ctrl+F)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from . import theme, widgets, workspace as ws


class Palette(tk.Toplevel):
    """Універсальне вікно з полем фільтра і списком результатів."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        title: str,
        items: list[tuple[str, str, Callable[[], None]]],
        *,
        placeholder: str = "Фільтр…",
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.items = items
        self.filtered = items[:]
        self._placeholder = placeholder
        self._build(title, placeholder)
        self.transient(master)
        # Одне модальне вікно за раз і без спливних карток під ним.
        if not widgets.open_only_modal(self):
            existing = widgets.active_modal()
            self.destroy()
            if existing is not None:
                widgets.lift_modal(existing)
            return
        self._center()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _build(self, title: str, placeholder: str) -> None:
        self.configure(bg=theme.BG_INPUT)
        self.overrideredirect(True)
        wrapper = tk.Frame(self, bg=theme.BORDER_SOFT, padx=1, pady=1)
        wrapper.pack(fill="both", expand=True)
        body = tk.Frame(wrapper, bg=theme.BG_INPUT)
        body.pack(fill="both", expand=True)

        self.title_label = tk.Label(body, text=title, bg=theme.BG_INPUT, fg=theme.FG_DIM,
                                    font=self.fonts.ui_small, anchor="w")
        self.title_label.pack(fill="x", padx=12, pady=(8, 0))

        self.entry = tk.Entry(body, bg=theme.BG_INPUT, fg=theme.FG_BRIGHT,
                              insertbackground=theme.FG_BRIGHT, relief="flat",
                              font=self.fonts.ui, width=60)
        self.entry.pack(fill="x", padx=12, pady=(4, 8), ipady=4)
        self.entry.insert(0, "")
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<Return>", lambda _e: self._choose())
        self.entry.bind("<Down>", lambda _e: self._move(1))
        self.entry.bind("<Up>", lambda _e: self._move(-1))
        self.entry.bind("<Escape>", lambda _e: self.destroy())

        ttk.Separator(body).pack(fill="x", pady=(0, 4))

        self.listbox = tk.Listbox(
            body, bg=theme.BG_INPUT, fg=theme.FG, selectbackground=theme.ACCENT_SOFT,
            selectforeground=theme.FG_BRIGHT, relief="flat", highlightthickness=0,
            font=self.fonts.ui, height=12, activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.listbox.bind("<Double-1>", lambda _e: self._choose())
        self.listbox.bind("<Return>", lambda _e: self._choose())
        self._render()
        self.after(50, lambda: (self.entry.focus_set(), self.geometry("")))

    def _center(self) -> None:
        """Розмістити палітру по центру батька, не виходячи за екран."""
        widgets.place_window(self, width=640, height=380, center_on=self.master)

    def _render(self, query: str = "") -> None:
        query = query.strip().lower()
        if query:
            tokens = query.split()
            self.filtered = [
                item for item in self.items
                if all(token in (item[0] + " " + item[1]).lower() for token in tokens)
            ]
        else:
            self.filtered = self.items[:]
        self.listbox.delete(0, "end")
        for label, hint, _action in self.filtered[:200]:
            text = f"{label}" + (f"    {hint}" if hint else "")
            self.listbox.insert("end", text)
        if self.filtered:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _on_key(self, _event) -> None:
        self._render(self.entry.get())

    def _move(self, step: int) -> str:
        if not self.filtered:
            return "break"
        current = self.listbox.curselection()
        index = (current[0] if current else 0) + step
        index = max(0, min(len(self.filtered) - 1, index))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)
        return "break"

    def _choose(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            if not self.filtered:
                self.destroy()
                return
            index = 0
        else:
            index = selection[0]
        _label, _hint, action = self.filtered[index]
        self.destroy()
        action()


class SearchDialog(tk.Toplevel):
    """Діалог пошуку/заміни в поточному файлі."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, editor) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.editor = editor
        self.title("Пошук у файлі")
        self.configure(bg=theme.BG_INPUT)
        self.resizable(False, False)
        self.transient(master)
        self._build()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Return>", lambda _e: self.find_next())
        self.bind("<Shift-Return>", lambda _e: self.find_prev())
        self.update_idletasks()
        x = master.winfo_rootx() + master.winfo_width() - 420
        y = master.winfo_rooty() + 20
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build(self) -> None:
        frame = tk.Frame(self, bg=theme.BG_INPUT, padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Знайти", bg=theme.BG_INPUT, fg=theme.FG_DIM, font=self.fonts.ui_small).grid(row=0, column=0, sticky="w")
        self.find_entry = tk.Entry(frame, bg=theme.BG, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
                                   relief="flat", font=self.fonts.mono_small, width=34)
        self.find_entry.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, 6), ipady=3)
        self.find_entry.focus_set()
        self.find_entry.bind("<KeyRelease>", lambda _e: self._live_highlight())

        tk.Label(frame, text="Замінити на", bg=theme.BG_INPUT, fg=theme.FG_DIM, font=self.fonts.ui_small).grid(row=2, column=0, sticky="w")
        self.replace_entry = tk.Entry(frame, bg=theme.BG, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
                                      relief="flat", font=self.fonts.mono_small, width=34)
        self.replace_entry.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(2, 8), ipady=3)

        self.case_var = tk.BooleanVar(value=False)
        self.regex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Врахувати регістр", variable=self.case_var,
                        command=self._live_highlight).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(frame, text="Regex", variable=self.regex_var,
                        command=self._live_highlight).grid(row=4, column=1, sticky="w")

        ttk.Button(frame, text="←", width=3, style="Icon.TButton",
                   command=self.find_prev).grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Button(frame, text="→", width=3, style="Icon.TButton",
                   command=self.find_next).grid(row=5, column=1, sticky="w", pady=(8, 0))
        ttk.Button(frame, text="Замінити", style="Flat.TButton",
                   command=self.replace_one).grid(row=5, column=2, sticky="e", pady=(8, 0))
        ttk.Button(frame, text="Усе", style="Accent.TButton",
                   command=self.replace_all).grid(row=5, column=3, sticky="e", pady=(8, 0))

        self.info = tk.Label(frame, text="", bg=theme.BG_INPUT, fg=theme.FG_DIM, font=self.fonts.ui_small)
        self.info.grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _options(self) -> tuple[str, bool, bool]:
        return self.find_entry.get(), self.regex_var.get(), self.case_var.get()

    def _live_highlight(self) -> None:
        needle, regex, case = self._options()
        if not self.editor:
            return
        count = self.editor.highlight_all_matches(needle, regex=regex, case=case)
        self.info.configure(text=f"Збігів: {count}" if needle else "")

    def find_next(self) -> None:
        needle, regex, case = self._options()
        if not needle:
            return
        if not self.editor.search(needle, regex=regex, case=case):
            self.info.configure(text="Більше збігів немає")
        self._live_highlight()

    def find_prev(self) -> None:
        needle, regex, case = self._options()
        if not needle:
            return
        self.editor.search(needle, backwards=True, regex=regex, case=case)
        self._live_highlight()

    def replace_one(self) -> None:
        if not self.editor:
            return
        selected = self.editor.selected_text()
        needle = self.find_entry.get()
        if selected and (selected == needle or selected.lower() == needle.lower()):
            self.editor.text.delete("sel.first", "sel.last")
            self.editor.text.insert("insert", self.replace_entry.get())
        self.find_next()

    def replace_all(self) -> None:
        if not self.editor:
            return
        needle = self.find_entry.get()
        replacement = self.replace_entry.get()
        if not needle:
            return
        content = self.editor.get_text()
        if self.regex_var.get():
            import re

            flags = 0 if self.case_var.get() else re.IGNORECASE
            try:
                updated, count = re.subn(needle, replacement, content, flags=flags)
            except re.error as exc:
                self.info.configure(text=f"Regex: {exc}")
                return
        else:
            if self.case_var.get():
                count = content.count(needle)
                updated = content.replace(needle, replacement)
            else:
                import re

                count = len(re.findall(re.escape(needle), content, re.IGNORECASE))
                updated = re.sub(re.escape(needle), replacement.replace("\\", "\\\\"), content, flags=re.IGNORECASE)
        self.editor.set_text(updated)
        self.info.configure(text=f"Замінено: {count}")


class ProjectSearch(ttk.Frame):
    """Результати пошуку по проєкту (нижня панель)."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, root_provider: Callable[[], Optional[Path]]) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.fonts = fonts
        self.root_provider = root_provider
        self.on_open: Optional[Callable[[Path, int], None]] = None
        self._hits: list[ws.FileHit] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        bar.columnconfigure(0, weight=1)

        ttk.Label(bar, text="ПОШУК У ПРОЄКТІ", style="Header.TLabel").grid(row=0, column=0, sticky="w")

        self.query_entry = tk.Entry(bar, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
                                    relief="flat", font=self.fonts.mono_small, width=28)
        self.query_entry.grid(row=0, column=1, padx=6, ipady=3)
        self.query_entry.bind("<Return>", lambda _e: self.run_search())

        self.glob_entry = tk.Entry(bar, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
                                   relief="flat", font=self.fonts.mono_small, width=14)
        self.glob_entry.grid(row=0, column=2, padx=4, ipady=3)
        self.glob_entry.bind("<Return>", lambda _e: self.run_search())

        self.regex_var = tk.BooleanVar(value=False)
        regex_check = ttk.Checkbutton(bar, text="Regex", variable=self.regex_var,
                                      style="Panel.TCheckbutton")
        regex_check.grid(row=0, column=3, padx=4)
        widgets.Tip(regex_check,
                    "Шукати за регулярним виразом Python, а не за звичайним текстом")

        find_btn = ttk.Button(bar, text="Знайти", style="Icon.TButton",
                              command=self.run_search)
        find_btn.grid(row=0, column=4, padx=(4, 0))
        widgets.Tip(find_btn,
                    "Знайти збіги в усіх файлах проєкту (Enter у полі запиту). "
                    "Подвійний клік у результаті відкриває файл на цьому рядку")

        self.results = ttk.Treeview(self, columns=("file", "line", "text"), show="headings", height=6)
        self.results.heading("file", text="Файл")
        self.results.heading("line", text="Рядок")
        self.results.heading("text", text="Текст")
        self.results.column("file", width=220, stretch=False)
        self.results.column("line", width=60, stretch=False, anchor="e")
        self.results.column("text", width=800, stretch=True)
        self.results.grid(row=1, column=0, sticky="nsew", padx=(8, 0))
        self.results.bind("<Double-1>", self._open_selected)
        self.results.bind("<Return>", self._open_selected)

        scroll = ttk.Scrollbar(self, orient="vertical", command=self.results.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)

        self.summary = ttk.Label(self, text="", style="Panel.TLabel")
        self.summary.grid(row=2, column=0, sticky="w", padx=8, pady=4)

    def run_search(self) -> None:
        needle = (self.query_entry.get() or "").strip()
        if not needle:
            self.query_entry.focus_set()
            return
        self.search_for(needle)

    def search_for(self, needle: str) -> None:
        root = self.root_provider()
        if not root or not needle:
            return
        try:
            hits = ws.search_text(root, needle, glob=self.glob_entry.get().strip(),
                                  regex=self.regex_var.get())
        except ws.WorkspaceError as exc:
            self.summary.configure(text=str(exc))
            return
        self._hits = hits
        self.results.delete(*self.results.get_children(""))
        for hit in hits:
            self.results.insert("", "end", values=(
                ws.relative_to_root(root, hit.path), hit.line, hit.text,
            ))
        self.summary.configure(text=f"Знайдено {len(hits)} збігів за «{needle}»")

    def _open_selected(self, _event=None) -> None:
        selection = self.results.selection()
        if not selection or not self.on_open:
            return
        index = self.results.index(selection[0])
        hit = self._hits[index]
        self.on_open(hit.path, hit.line)
