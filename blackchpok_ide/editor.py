"""Редактор коду на базі tkinter.Text: номери рядків, підсвітка, авто-відступ.

Віджет самостійно синхронізує жолобок (gutter) з прокруткою, підсвічує
видимий діапазон і повідомляє назовні про зміни через колбеки.
"""

from __future__ import annotations

import logging
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from . import safe, syntax, theme

LOG = logging.getLogger("blackchpok.editor")

INDENT_UNIT = " "


class CodeEditor(tk.Frame):
    """Один документ: Text + номери рядків + горизонтальна прокрутка."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        filename: str = "",
        *,
        tab_size: int = 4,
        show_line_numbers: bool = True,
        word_wrap: bool = False,
        highlight_current: bool = True,
        on_change: Optional[Callable[["CodeEditor"], None]] = None,
        on_cursor: Optional[Callable[["CodeEditor"], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_EDITOR, highlightthickness=0, bd=0)
        self.fonts = fonts
        self.filename = filename or "untitled.txt"
        self.tab_size = tab_size
        self.show_line_numbers = show_line_numbers
        self.highlight_current = highlight_current
        self.word_wrap = word_wrap
        self.on_change = on_change
        self.on_cursor = on_cursor
        self.path: Optional[Path] = None
        self.modified = False
        self._highlight_job: Optional[str] = None
        self._last_line_count = -1
        self._readonly = False
        self._original_lines: Optional[list[str]] = None
        self._show_changes = False
        # AST-аналіз у реальному часі
        self._ast_job: Optional[str] = None
        self.analysis = None
        self.on_analysis: Optional[Callable[[object], None]] = None
        self.on_problem: Optional[Callable[[object], None]] = None
        self._build()
        self._bind()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.gutter = tk.Text(
            self,
            width=5,
            padx=8,
            pady=6,
            takefocus=0,
            border=0,
            highlightthickness=0,
            background=theme.BG_EDITOR,
            foreground=theme.GUTTER_FG,
            font=self.fonts.mono_small,
            state="disabled",
            cursor="arrow",
            wrap="none",
        )
        self.gutter.grid(row=0, column=0, sticky="ns")
        if not self.show_line_numbers:
            self.gutter.grid_remove()

        self.text = tk.Text(
            self,
            undo=True,
            maxundo=-1,
            autoseparators=True,
            width=24,
            height=8,
            wrap="char" if self.word_wrap else "none",
            border=0,
            highlightthickness=0,
            background=theme.BG_EDITOR,
            foreground=theme.FG,
            insertbackground=theme.FG_BRIGHT,
            insertwidth=2,
            selectbackground=theme.SELECTION,
            selectforeground=theme.FG_BRIGHT,
            font=self.fonts.mono,
            padx=10,
            pady=6,
            spacing1=1,
            spacing3=1,
            tabs=(self.tab_size * self.fonts.mono.measure(" "),),
            state="normal",
        )
        self.text.grid(row=0, column=1, sticky="nsew")

        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.vbar.grid(row=0, column=2, sticky="ns")
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.hbar.grid(row=1, column=1, sticky="ew")
        if not self.word_wrap:
            self.text.configure(xscrollcommand=self.hbar.set)
        else:
            self.hbar.grid_remove()

        self.text.configure(yscrollcommand=self._on_yscroll)
        syntax.configure_tags(self.text, self.fonts.mono, self.fonts.mono_bold)
        self.apply_settings()

    def _bind(self) -> None:
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<KeyRelease>", self._on_key_release, add="+")
        self.text.bind("<ButtonRelease-1>", self._on_click, add="+")
        self.text.bind("<Configure>", lambda _e: self._schedule_highlight(), add="+")
        self.text.bind("<MouseWheel>", self._on_wheel, add="+")
        self.gutter.bind("<Button-1>", self._on_gutter_click)
        self.gutter.bind("<B1-Motion>", self._on_gutter_drag)

        # відступи та автозакриття дужок
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<Tab>", self._on_tab)
        self.text.bind("<Shift-Tab>", self._on_shift_tab)
        self.text.bind("<BackSpace>", self._on_backspace)
        for open_ch, close_ch in (("(", ")"), ("[", "]"), ("{", "}"), ('"', '"'), ("'", "'")):
            self.text.bind(open_ch, lambda event, o=open_ch, c=close_ch: self._on_autoclose(event, o, c))
        self.text.bind("<Control-d>", self._duplicate_line)
        self.text.bind("<Control-slash>", self._toggle_comment)
        self.text.bind("<Control-Key-/>", self._toggle_comment)
        self.text.bind("<Control-g>", lambda _e: self.focus_goto())

    # ── налаштування ───────────────────────────────────────────────────────
    def apply_settings(self) -> None:
        self.text.configure(
            wrap="char" if self.word_wrap else "none",
            tabs=(self.tab_size * self.fonts.mono.measure(" "),),
            font=self.fonts.mono,
        )
        self.gutter.configure(font=self.fonts.mono_small)
        if self.word_wrap:
            self.hbar.grid_remove()
            self.text.configure(xscrollcommand="")
        else:
            self.hbar.grid(row=1, column=1, sticky="ew")
            self.text.configure(xscrollcommand=self.hbar.set)
        if self.show_line_numbers:
            self.gutter.grid(row=0, column=0, sticky="ns")
        else:
            self.gutter.grid_remove()
        syntax.configure_tags(self.text, self.fonts.mono, self.fonts.mono_bold)
        self._refresh_gutter(force=True)
        self._schedule_highlight()

    def set_readonly(self, value: bool) -> None:
        self._readonly = value
        self.text.configure(state="disabled" if value else "normal")

    # ── прокрутка та жолобок ───────────────────────────────────────────────
    def _on_yscroll(self, first: str, last: str) -> None:
        self.vbar.set(first, last)
        self.gutter.yview_moveto(first)
        self._schedule_highlight()

    def _yview(self, *args) -> None:
        self.text.yview(*args)
        self.gutter.yview(*args)

    def _on_wheel(self, event) -> str:
        if event.num == 4:
            self._yview("scroll", -3, "units")
        elif event.num == 5:
            self._yview("scroll", 3, "units")
        else:
            delta = -1 * int(event.delta / 120) if event.delta else 0
            if delta:
                self._yview("scroll", delta * 3, "units")
        self._refresh_gutter()
        return "break"

    def _refresh_gutter(self, force: bool = False) -> None:
        total = int(self.text.index("end-1c").split(".")[0])
        if total == self._last_line_count and not force:
            return
        self._last_line_count = total
        self.gutter.configure(state="normal")
        self.gutter.delete("1.0", "end")
        self.gutter.insert("1.0", "\n".join(str(n) for n in range(1, total + 1)))
        self.gutter.tag_configure("current", foreground=theme.FG_BRIGHT)
        self.gutter.configure(state="disabled")

    def _mark_current_line(self) -> None:
        self.text.tag_remove("current_line", "1.0", "end")
        if not self.highlight_current:
            return
        start = self.text.index("insert linestart")
        end = self.text.index("insert lineend+1c")
        self.text.tag_add("current_line", start, end)
        self.text.tag_lower("current_line")

    # ── AST-аналіз у реальному часі ────────────────────────────────────────
    def schedule_analysis(self, delay: int = 220) -> None:
        """Запланувати розбір AST (з невеликою паузою після набору)."""
        if not self.filename.endswith(".py"):
            return
        if self._ast_job is not None:
            try:
                self.after_cancel(self._ast_job)
            except (tk.TclError, ValueError):
                pass
        try:
            self._ast_job = self.after(delay, self._run_analysis)
        except tk.TclError:
            self._ast_job = None

    def _run_analysis(self) -> None:
        """Розібрати поточний текст і повідомити назовні."""
        self._ast_job = None
        if not self.filename.endswith(".py"):
            return
        try:
            from . import ast_index

            result = ast_index.analyse(self.get_text())
        except Exception:  # noqa: BLE001 - аналіз не має ламати редактор
            return
        self.analysis = result
        self._mark_problem(result.problem)
        safe.call_quiet(self.on_analysis, result, where="оновлення структури файлу")
        if result.problem is not None:
            safe.call_quiet(self.on_problem, result.problem,
                            where="позначення помилки синтаксису")

    def _mark_problem(self, problem) -> None:
        """Підсвітити рядок із синтаксичною помилкою."""
        self.text.tag_remove("syntax_error", "1.0", "end")
        if problem is None or not getattr(problem, "line", 0):
            return
        line = max(1, int(problem.line))
        try:
            self.text.tag_add("syntax_error", f"{line}.0", f"{line}.end+1c")
            self.text.tag_configure("syntax_error", background="#3a1d1d",
                                    underline=True)
            self.text.tag_raise("syntax_error")
        except tk.TclError:
            return

    def analysis_line(self) -> int:
        """Рядок, який зараз у фокусі (для показу символу)."""
        return self.current_line()

    # ── підсвітка ──────────────────────────────────────────────────────────
    def _schedule_highlight(self) -> None:
        if self._highlight_job is not None:
            try:
                self.after_cancel(self._highlight_job)
            except tk.TclError:
                pass
        self._highlight_job = self.after(40, self._do_highlight)

    def _do_highlight(self) -> None:
        self._highlight_job = None
        try:
            first_visible = int(self.text.index("@0,0").split(".")[0])
            last_visible = int(self.text.index(f"@0,{self.text.winfo_height()}").split(".")[0]) + 1
        except (tk.TclError, ValueError):
            return
        buffer = 120
        first = max(1, first_visible - buffer)
        last = last_visible + buffer
        syntax.apply_highlight(self.text, self.filename, f"{first}.0", f"{last}.0")
        self._mark_current_line()
        self._refresh_gutter()

    def refresh_all(self) -> None:
        self._refresh_gutter(force=True)
        self._schedule_highlight()

    # ── підсвітка змін (як у diff-огляді) ──────────────────────────────────
    def mark_original(self) -> None:
        """Запам'ятати поточний вміст як «збережену» версію для diff-підсвітки."""
        self._original_lines = self.get_text().splitlines()

    def show_changes(self, enabled: bool = True) -> None:
        """Підсвітити рядки, додані після останнього збереження.

        Зеленуватий фон позначає щойно введені рядки — це той самий
        «інлайн-диф», що й у сучасних редакторах, і він допомагає побачити,
        що саме зробив агент.
        """
        self._show_changes = bool(enabled)
        self._refresh_change_tags()

    def _refresh_change_tags(self) -> None:
        for tag in ("line_added", "line_removed_hint"):
            self.text.tag_remove(tag, "1.0", "end")
        if not getattr(self, "_show_changes", False):
            return
        original = getattr(self, "_original_lines", None)
        if original is None:
            return
        try:
            import difflib

            current = self.get_text().splitlines()
            matcher = difflib.SequenceMatcher(a=original, b=current, autojunk=False)
            for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
                if tag in ("insert", "replace"):
                    start = max(1, j1 + 1)
                    end = max(start, j2)
                    self.text.tag_add("line_added", f"{start}.0", f"{end}.0 lineend+1c")
            self.text.tag_raise("line_added")
            self.text.tag_lower("line_added", "sel")
        except (ValueError, tk.TclError):
            return

    def change_summary(self) -> tuple[int, int]:
        """(додано, видалено) відносно збереженої версії."""
        original = getattr(self, "_original_lines", None)
        if original is None:
            return (0, 0)
        try:
            import difflib

            added = removed = 0
            matcher = difflib.SequenceMatcher(a=original, b=self.get_text().splitlines(),
                                              autojunk=False)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag in ("replace", "insert"):
                    added += max(0, j2 - j1)
                if tag in ("replace", "delete"):
                    removed += max(0, i2 - i1)
            return (added, removed)
        except (ValueError, tk.TclError):
            return (0, 0)

    # ── події ──────────────────────────────────────────────────────────────
    def _on_modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if not self._readonly:
                self.modified = True
                if self.on_change:
                    self.on_change(self)
        self._schedule_highlight()
        if self._show_changes:
            self._refresh_change_tags()
        self.schedule_analysis()

    def _on_key_release(self, _event=None) -> None:
        self._mark_current_line()
        if self.on_cursor:
            self.on_cursor(self)
        self._schedule_highlight()

    def _on_click(self, _event=None) -> None:
        self._mark_current_line()
        if self.on_cursor:
            self.on_cursor(self)

    def _on_gutter_click(self, event) -> None:
        line = self.gutter.index(f"@{event.x},{event.y}").split(".")[0]
        self.text.mark_set("insert", f"{line}.0")
        self.text.see(f"{line}.0")
        self._mark_current_line()

    def _on_gutter_drag(self, event) -> None:
        line = self.gutter.index(f"@{event.x},{event.y}").split(".")[0]
        self.text.tag_remove("sel", "1.0", "end")
        if not hasattr(self, "_drag_anchor"):
            self._drag_anchor = self.text.index("insert")
        self.text.tag_add("sel", self._drag_anchor, f"{line}.end")
        self.text.mark_set("insert", f"{line}.end")

    # ── автовідступи ───────────────────────────────────────────────────────
    def _current_line_text(self) -> str:
        return self.text.get("insert linestart", "insert")

    def _indent_of(self, text: str) -> str:
        match = re.match(r"[ \t]*", text)
        return match.group(0) if match else ""

    def _on_return(self, _event=None) -> str:
        line = self._current_line_text()
        indent = self._indent_of(line)
        stripped = line.rstrip()
        extra = ""
        if stripped.endswith(":"):
            extra = INDENT_UNIT * self.tab_size
        elif stripped.endswith(("{", "[", "(")):
            extra = INDENT_UNIT * self.tab_size
        before = self.text.get("insert linestart", "insert lineend")
        insert_col = int(self.text.index("insert").split(".")[1])
        after = before[insert_col:].strip()
        self.text.insert("insert", "\n" + indent + extra)
        if extra and after[:1] in {")", "]", "}"}:
            self.text.insert("insert", "\n" + indent)
            self.text.mark_set("insert", f"insert-1l lineend")
        self.text.see("insert")
        return "break"

    def _on_tab(self, event=None) -> str:
        try:
            sel_first = self.text.index("sel.first")
            sel_last = self.text.index("sel.last")
        except tk.TclError:
            sel_first = sel_last = ""
        if sel_first:
            self._indent_selection(sel_first, sel_last, add=True)
            return "break"
        self.text.insert("insert", " " * self.tab_size)
        return "break"

    def _on_shift_tab(self, event=None) -> str:
        try:
            sel_first = self.text.index("sel.first")
            sel_last = self.text.index("sel.last")
        except tk.TclError:
            first = self.text.index("insert linestart")
            last = self.text.index("insert lineend")
            self._indent_selection(first, last, add=False)
            return "break"
        self._indent_selection(sel_first, sel_last, add=False)
        return "break"

    def _indent_selection(self, first: str, last: str, add: bool) -> None:
        start_line = int(first.split(".")[0])
        end_line = int(last.split(".")[0])
        self.text.edit_separator()
        for line in range(start_line, end_line + 1):
            line_text = self.text.get(f"{line}.0", f"{line}.end")
            if add:
                if line_text.strip():
                    self.text.insert(f"{line}.0", " " * self.tab_size)
            else:
                remove = 0
                while remove < self.tab_size and remove < len(line_text) and line_text[remove] == " ":
                    remove += 1
                if remove:
                    self.text.delete(f"{line}.0", f"{line}.{remove}")
        self.text.edit_separator()

    def _on_backspace(self, _event=None) -> Optional[str]:
        line = self._current_line_text()
        col = self.text.index("insert")
        if line and line.strip() == "" and len(line) % self.tab_size == 0 and int(col.split(".")[1]) == len(line):
            self.text.delete(f"insert-{self.tab_size}c", "insert")
            return "break"
        return None

    def _on_autoclose(self, _event, open_ch: str, close_ch: str) -> Optional[str]:
        try:
            if self.text.index("sel.first"):
                return None
        except tk.TclError:
            pass
        before = self.text.get("insert-1c", "insert")
        if open_ch in {'"', "'"} and before == "\\":
            return None
        self.text.insert("insert", open_ch + close_ch)
        self.text.mark_set("insert", "insert-1c")
        return "break"

    def _duplicate_line(self, _event=None) -> str:
        line = self.text.index("insert linestart")
        content = self.text.get(line, f"{line} lineend")
        self.text.insert(f"{line} lineend", "\n" + content)
        return "break"

    def _toggle_comment(self, _event=None) -> str:
        token = syntax.comment_token(self.filename)
        try:
            first = self.text.index("sel.first")
            last = self.text.index("sel.last")
        except tk.TclError:
            first = self.text.index("insert linestart")
            last = self.text.index("insert lineend")
        start_line = int(first.split(".")[0])
        end_line = int(last.split(".")[0])
        lines = [self.text.get(f"{n}.0", f"{n}.end") for n in range(start_line, end_line + 1)]
        all_commented = all(line.lstrip().startswith(token.strip()) for line in lines if line.strip())
        self.text.edit_separator()
        for offset, line in enumerate(lines):
            number = start_line + offset
            if not line.strip():
                continue
            if all_commented:
                stripped = line.lstrip()
                indent = line[: len(line) - len(stripped)]
                body = stripped[len(token.strip()):]
                if body.startswith(" "):
                    body = body[1:]
                self.text.delete(f"{number}.0", f"{number}.end")
                self.text.insert(f"{number}.0", indent + body)
            else:
                indent = self._indent_of(line)
                self.text.insert(f"{number}.{len(indent)}", token)
        self.text.edit_separator()
        return "break"

    # ── API ────────────────────────────────────────────────────────────────
    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set_text(self, content: str, *, keep_undo: bool = False) -> None:
        state = self.text.cget("state")
        self.text.configure(state="normal")
        if not keep_undo:
            self.text.edit_reset()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_modified(False)
        if not keep_undo:
            self.text.edit_reset()
        self.text.configure(state=state)
        self.modified = False
        self._refresh_gutter(force=True)
        self._schedule_highlight()
        self.schedule_analysis()

    def insert_text(self, content: str, at: str = "insert") -> None:
        state = self.text.cget("state")
        self.text.configure(state="normal")
        self.text.insert(at, content)
        self.text.configure(state=state)
        self._schedule_highlight()

    def goto_line(self, line: int, column: int = 0) -> None:
        line = max(1, line)
        self.text.mark_set("insert", f"{line}.{column}")
        self.text.see(f"{line}.{column}")
        self.text.focus_set()
        self._mark_current_line()
        if self.on_cursor:
            self.on_cursor(self)

    def current_line(self) -> int:
        return int(self.text.index("insert").split(".")[0])

    def current_column(self) -> int:
        return int(self.text.index("insert").split(".")[1]) + 1

    def selected_text(self) -> str:
        try:
            return self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return ""

    def focus_goto(self) -> None:
        from tkinter import simpledialog

        line = simpledialog.askinteger("Перехід", "Номер рядка:", parent=self, minvalue=1)
        if line:
            self.goto_line(line)

    def search(self, needle: str, *, backwards: bool = False, regex: bool = False, case: bool = False) -> bool:
        self.text.tag_remove("search_current", "1.0", "end")
        if not needle:
            self.text.tag_remove("search_hit", "1.0", "end")
            return False
        start = "insert" if backwards else "insert"
        stopindex = "1.0" if backwards else "end"
        try:
            if regex:
                hits = []
                for match in re.finditer(needle, self.get_text(), 0 if case else re.IGNORECASE):
                    hits.append((match.start(), match.end()))
                index = self._find_index(hits, backwards)
                if index is None:
                    return False
                self._select_offsets(*hits[index])
                return True
            index = self.text.search(
                needle, start, stopindex=stopindex, backwards=backwards,
                nocase=not case, regexp=False,
            )
        except tk.TclError:
            return False
        if not index:
            index = self.text.search(
                needle, "1.0" if backwards else "1.0", stopindex="end",
                backwards=backwards, nocase=not case,
            )
        if not index:
            return False
        end = f"{index}+{len(needle)}c"
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", index, end)
        self.text.tag_add("search_current", index, end)
        self.text.mark_set("insert", index)
        self.text.see(index)
        return True

    def highlight_all_matches(self, needle: str, regex: bool = False, case: bool = False) -> int:
        self.text.tag_remove("search_hit", "1.0", "end")
        if not needle:
            return 0
        count = 0
        if regex:
            for match in re.finditer(needle, self.get_text(), 0 if case else re.IGNORECASE):
                self._tag_offsets("search_hit", match.start(), match.end())
                count += 1
            return count
        start = "1.0"
        while True:
            index = self.text.search(needle, start, stopindex="end", nocase=not case)
            if not index:
                break
            end = f"{index}+{len(needle)}c"
            self.text.tag_add("search_hit", index, end)
            start = end
            count += 1
        return count

    def _tag_offsets(self, tag: str, start_offset: int, end_offset: int) -> None:
        start = self.text.index(f"1.0+{start_offset}c")
        end = self.text.index(f"1.0+{end_offset}c")
        self.text.tag_add(tag, start, end)

    def _select_offsets(self, start_offset: int, end_offset: int) -> None:
        start = self.text.index(f"1.0+{start_offset}c")
        end = self.text.index(f"1.0+{end_offset}c")
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", start, end)
        self.text.tag_add("search_current", start, end)
        self.text.mark_set("insert", end)
        self.text.see(start)

    def _find_index(self, hits: list[tuple[int, int]], backwards: bool) -> Optional[int]:
        if not hits:
            return None
        cursor = self.text.count("1.0", "insert")
        offset = cursor[0] if cursor else 0
        if backwards:
            previous = [i for i, (start, _end) in enumerate(hits) if start < offset]
            return previous[-1] if previous else len(hits) - 1
        upcoming = [i for i, (start, _end) in enumerate(hits) if start > offset]
        return upcoming[0] if upcoming else 0
