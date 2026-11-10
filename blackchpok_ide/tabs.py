"""Вкладки редактора: смуга вкладок із кнопками закриття, збереження, контекст.

Замість ``ttk.Notebook`` використовується власна смуга: у сучасному дизайні
вкладка має закриватись хрестиком, підсвічуватись і мати контекстне меню, а
``Notebook`` цього не дає.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Optional

from . import theme, widgets, workspace as ws
from .editor import CodeEditor

MODIFIED_DOT = "●"


class _TabLabel(tk.Frame):
    """Одна вкладка в смузі: назва, крапка змін, хрестик закриття."""

    def __init__(self, master: tk.Misc, owner: "EditorTabs", frame_id: str, title: str) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.owner = owner
        self.frame_id = frame_id
        self.active = False
        self.modified = False

        self.inner = tk.Frame(self, bg=theme.BG_ALT)
        self.inner.pack(padx=(11, 4), pady=4)

        self.title_label = tk.Label(self.inner, text=title, bg=theme.BG_ALT, fg=theme.FG_DIM,
                                    font=("Segoe UI", 9), bd=0, cursor="hand2")
        self.title_label.pack(side="left")

        self.close_label = tk.Label(self.inner, text="✕", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), bd=0, padx=4, cursor="hand2")
        self.close_label.pack(side="left", padx=(4, 0))

        for widget in (self, self.inner, self.title_label):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
        self.close_label.bind("<Button-1>", self._on_close)
        self.close_label.bind("<Enter>", lambda _e: self.close_label.configure(fg=theme.ERROR))
        self.close_label.bind("<Leave>", lambda _e: self.close_label.configure(fg=theme.FG_FAINT))
        self.bind("<Button-2>", self._on_middle)
        self.bind("<Button-3>", self._on_context)

    # ── стан ───────────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        self.active = active
        colour = theme.BG_EDITOR if active else theme.BG_ALT
        for widget in (self, self.inner, self.title_label, self.close_label):
            widget.configure(bg=colour)
        self.title_label.configure(fg=theme.FG_BRIGHT if active else theme.FG_DIM)

    def set_title(self, title: str, modified: bool) -> None:
        self.modified = modified
        text = f"{MODIFIED_DOT} {title}" if modified else title
        if modified and self.active:
            self.title_label.configure(text=text, fg=theme.FG_BRIGHT)
        else:
            self.title_label.configure(text=text, fg=theme.FG_BRIGHT if self.active else theme.FG_DIM)

    # ── події ──────────────────────────────────────────────────────────────
    def _on_click(self, _event=None) -> None:
        self.owner.select(self.frame_id)

    def _on_close(self, _event=None) -> str:
        self.owner.close_tab(self.frame_id)
        return "break"

    def _on_middle(self, _event=None) -> str:
        self.owner.close_tab(self.frame_id)
        return "break"

    def _on_enter(self, _event=None) -> None:
        if not self.active:
            for widget in (self, self.inner, self.title_label):
                widget.configure(bg=theme.BG_HOVER)
            self.close_label.configure(bg=theme.BG_HOVER)

    def _on_leave(self, _event=None) -> None:
        if not self.active:
            colour = theme.BG_ALT
            for widget in (self, self.inner, self.title_label, self.close_label):
                widget.configure(bg=colour)

    def _on_context(self, event) -> None:
        widgets.context_menu(self, (
            ("Закрити", lambda: self.owner.close_tab(self.frame_id)),
            ("Закрити інші", lambda: self.owner.close_others(self.frame_id)),
            ("Закрити всі", lambda: self.owner.close_all()),
            None,
            ("Зберегти", lambda: self.owner.save_tab(self.frame_id)),
            ("Зберегти як…", lambda: self.owner.save_tab(self.frame_id, force_as=True)),
            None,
            ("Показати в провіднику", lambda: self.owner.reveal_in_explorer(self.frame_id)),
            ("Копіювати шлях", lambda: self.owner.copy_path(self.frame_id)),
        ), event)


class EditorTabs(tk.Frame):
    """Смуга вкладок + стек редакторів."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        settings,
        *,
        on_status: Optional[Callable[[str], None]] = None,
        on_cursor: Optional[Callable[[CodeEditor], None]] = None,
        on_saved: Optional[Callable[[Path], None]] = None,
        on_changed: Optional[Callable[[], None]] = None,
        on_new_tab: Optional[Callable[[], None]] = None,
        on_analysis: Optional[Callable[[object, object], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_EDITOR, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.settings = settings
        self.on_status = on_status
        self.on_cursor_cb = on_cursor
        self.on_saved = on_saved
        self.on_changed = on_changed
        self.on_new_tab = on_new_tab
        self.on_analysis = on_analysis
        self.editors: dict[str, CodeEditor] = {}
        self.paths: dict[str, Path] = {}
        self._by_path: dict[str, str] = {}
        self._tabs: dict[str, _TabLabel] = {}
        self._order: list[str] = []
        self._active: str = ""
        self._closed: list[Path] = []
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        strip = tk.Frame(self, bg=theme.BG_EDITOR, height=34)
        strip.grid(row=0, column=0, sticky="ew")
        strip.grid_propagate(False)
        strip.columnconfigure(0, weight=1)
        self.strip = strip

        self._canvas = tk.Canvas(strip, bg=theme.BG_EDITOR, bd=0, highlightthickness=0,
                                 height=34, takefocus=0)
        self._canvas.grid(row=0, column=0, sticky="ew")
        self._tab_host = tk.Frame(self._canvas, bg=theme.BG_EDITOR)
        self._window = self._canvas.create_window((0, 0), window=self._tab_host, anchor="nw")
        self._tab_host.bind("<Configure>", self._sync_scrollregion)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_wheel)

        self.new_tab_btn = widgets.IconButton(strip, "＋", self._request_new_tab, bg=theme.BG_EDITOR,
                                              fg=theme.FG_FAINT, font=("Segoe UI", 11),
                                              tooltip="Новий файл (Ctrl+N)")
        self.new_tab_btn.grid(row=0, column=1, padx=(4, 8))

        self.content = tk.Frame(self, bg=theme.BG_EDITOR, bd=0, highlightthickness=0)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.empty_hint = tk.Label(
            self.content,
            text="Немає відкритих файлів\n\nCtrl+P — швидке відкриття · Ctrl+Shift+P — палітра команд",
            bg=theme.BG_EDITOR, fg=theme.FG_FAINT, font=("Segoe UI", 10), justify="center",
        )
        self.empty_hint.place(relx=0.5, rely=0.42, anchor="center")

    def _request_new_tab(self) -> None:
        if self.on_new_tab:
            self.on_new_tab()
        else:
            self.new_file()

    def _sync_scrollregion(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._window, height=event.height)

    def _on_wheel(self, event) -> None:
        if self._canvas.bbox("all") is None:
            return
        total = self._tab_host.winfo_reqwidth()
        if total <= self._canvas.winfo_width():
            return
        self._canvas.xview_scroll(int(-event.delta / 120) or -1, "units")

    # ── створення ──────────────────────────────────────────────────────────
    def _new_editor(self, title: str, filename: str) -> tuple[str, CodeEditor]:
        frame = tk.Frame(self.content, bg=theme.BG_EDITOR, bd=0, highlightthickness=0)
        editor = CodeEditor(
            frame,
            self.fonts,
            filename,
            tab_size=self.settings.ui.tab_size,
            show_line_numbers=self.settings.ui.show_line_numbers,
            word_wrap=self.settings.ui.word_wrap,
            highlight_current=self.settings.ui.highlight_current_line,
            on_change=self._on_editor_change,
            on_cursor=lambda ed: self.on_cursor_cb(ed) if self.on_cursor_cb else None,
        )
        # Живий AST: редактор сам розбирає код і повідомляє результат.
        if self.on_analysis is not None:
            editor.on_analysis = lambda result, ed=editor: self.on_analysis(ed, result)
        editor.pack(fill="both", expand=True)
        frame_id = str(frame)
        tab = _TabLabel(self._tab_host, self, frame_id, title)
        tab.pack(side="left", padx=(0, 1), pady=(4, 0))
        self._tabs[frame_id] = tab
        self._order.append(frame_id)
        return frame_id, editor

    # ── відкриття ──────────────────────────────────────────────────────────
    def open_file(self, path: Path, *, line: int = 0) -> bool:
        path = Path(path)
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        existing = self._by_path.get(key)
        if existing and existing in self.editors:
            self.select(existing)
            if line:
                self.editors[existing].goto_line(line)
            self.editors[existing].text.focus_set()
            return True
        try:
            content, encoding = ws.read_text_file(path)
        except ws.WorkspaceError as exc:
            if self.on_status:
                self.on_status(str(exc))
            messagebox.showwarning("Не вдалось відкрити", str(exc), parent=self)
            return False
        frame_id, editor = self._new_editor(path.name, path.name)
        editor.set_text(content)
        editor.path = path
        editor.filename = path.name
        editor.encoding = encoding  # type: ignore[attr-defined]
        self.editors[frame_id] = editor
        self.paths[frame_id] = path
        self._by_path[key] = frame_id
        self.select(frame_id)
        editor.text.focus_set()
        if line:
            editor.goto_line(line)
        if self.on_status:
            self.on_status(f"Відкрито {path.name} · {len(content.splitlines())} рядків · {encoding}")
        return True

    def new_file(self) -> CodeEditor:
        frame_id, editor = self._new_editor("Без назви", "untitled.txt")
        self.editors[frame_id] = editor
        self.select(frame_id)
        editor.text.focus_set()
        return editor

    # ── доступ ─────────────────────────────────────────────────────────────
    def current(self) -> Optional[CodeEditor]:
        return self.editors.get(self._active)

    def current_path(self) -> Optional[Path]:
        if not self._active:
            return None
        return self.paths.get(self._active)

    def current_key(self) -> str:
        return self._active

    def by_path(self, path: Path) -> Optional[CodeEditor]:
        try:
            key = str(Path(path).resolve())
        except OSError:
            return None
        frame_id = self._by_path.get(key)
        return self.editors.get(frame_id) if frame_id else None

    def all_paths(self) -> list[Path]:
        return [self.paths[key] for key in self._order if key in self.paths]

    def tab_titles(self) -> list[tuple[str, str, bool]]:
        """(frame_id, назва, чи є незбережені зміни) — для панелі контексту."""
        rows = []
        for frame_id in self._order:
            editor = self.editors.get(frame_id)
            if editor is None:
                continue
            name = editor.path.name if editor.path else editor.filename or "Без назви"
            rows.append((frame_id, name, bool(editor.modified)))
        return rows

    def count(self) -> int:
        return len(self.editors)

    def select(self, frame_id: str) -> None:
        if frame_id not in self.editors:
            return
        if self._active and self._active in self.editors:
            self.editors[self._active].master.grid_remove()
        self._active = frame_id
        self.editors[frame_id].master.grid(row=0, column=0, sticky="nsew")
        for key, tab in self._tabs.items():
            tab.set_active(key == frame_id)
        if self.empty_hint.winfo_ismapped():
            self.empty_hint.place_forget()
        self._notify_changed()

    def _notify_changed(self) -> None:
        if self.on_changed:
            try:
                self.on_changed()
            except Exception:  # noqa: BLE001 - панель не має ламати редактор
                pass

    # ── зміни ──────────────────────────────────────────────────────────────
    def _on_editor_change(self, editor: CodeEditor) -> None:
        frame_id = str(editor.master)
        tab = self._tabs.get(frame_id)
        if tab is not None:
            base = editor.path.name if editor.path else "Без назви"
            tab.set_title(base, bool(editor.modified))
        self._notify_changed()

    def rename_tab(self, editor: CodeEditor, title: str) -> None:
        tab = self._tabs.get(str(editor.master))
        if tab is not None:
            tab.set_title(title, bool(editor.modified))

    # ── збереження ─────────────────────────────────────────────────────────
    def save_tab(self, frame_id: str, *, force_as: bool = False) -> bool:
        editor = self.editors.get(frame_id)
        if editor is None:
            return False
        path = self.paths.get(frame_id)
        if force_as or path is None:
            return self._save_as(frame_id, editor)
        try:
            ws.write_text_file(path, editor.get_text())
        except ws.WorkspaceError as exc:
            messagebox.showerror("Помилка запису", str(exc), parent=self)
            return False
        editor.modified = False
        tab = self._tabs.get(frame_id)
        if tab is not None:
            tab.set_title(path.name, False)
        if self.on_saved:
            self.on_saved(path)
        if self.on_status:
            self.on_status(f"Збережено {path.name}")
        self._notify_changed()
        return True

    def save_current(self) -> bool:
        if not self._active:
            return False
        return self.save_tab(self._active)

    def _save_as(self, frame_id: str, editor: CodeEditor) -> bool:
        initial = str(editor.path) if editor.path else "untitled.py"
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Зберегти як", initialfile=Path(initial).name,
            defaultextension=".py",
        )
        if not chosen:
            return False
        path = Path(chosen)
        try:
            ws.write_text_file(path, editor.get_text())
        except ws.WorkspaceError as exc:
            messagebox.showerror("Помилка запису", str(exc), parent=self)
            return False
        self.paths[frame_id] = path
        self._by_path[str(path.resolve())] = frame_id
        editor.path = path
        editor.filename = path.name
        editor.modified = False
        tab = self._tabs.get(frame_id)
        if tab is not None:
            tab.set_title(path.name, False)
        editor.refresh_all()
        if self.on_saved:
            self.on_saved(path)
        self._notify_changed()
        return True

    def save_as(self) -> bool:
        if not self._active:
            return False
        return self._save_as(self._active, self.editors[self._active])

    def save_all(self) -> None:
        for frame_id in list(self._order):
            editor = self.editors.get(frame_id)
            if editor is None or not editor.modified or frame_id not in self.paths:
                continue
            try:
                ws.write_text_file(self.paths[frame_id], editor.get_text())
                editor.modified = False
                tab = self._tabs.get(frame_id)
                if tab is not None:
                    tab.set_title(Path(self.paths[frame_id]).name, False)
            except ws.WorkspaceError:
                continue
        self._notify_changed()

    # ── закриття ───────────────────────────────────────────────────────────
    def close_current(self) -> bool:
        if not self._active:
            return False
        return self.close_tab(self._active)

    def close_tab(self, frame_id: str) -> bool:
        editor = self.editors.get(frame_id)
        if editor is None:
            return False
        if editor.modified:
            name = editor.path.name if editor.path else "Без назви"
            answer = messagebox.askyesnocancel(
                "Незбережені зміни",
                f"Зберегти зміни у «{name}» перед закриттям?",
                parent=self,
            )
            if answer is None:
                return False
            if answer and not self.save_tab(frame_id):
                return False
        self._forget_tab(frame_id)
        return True

    def _forget_tab(self, frame_id: str) -> None:
        editor = self.editors.pop(frame_id, None)
        removed = self.paths.pop(frame_id, None)
        if removed is not None:
            self._by_path.pop(str(removed.resolve()), None)
            # Запам'ятовуємо закритий шлях, щоб вкладку можна було відкрити знову.
            self._closed.append(Path(removed))
            del self._closed[:-40]
        tab = self._tabs.pop(frame_id, None)
        if tab is not None:
            tab.destroy()
        if frame_id in self._order:
            self._order.remove(frame_id)
        if editor is not None:
            editor.master.destroy()
        if self._active == frame_id:
            self._active = ""
            if self._order:
                self.select(self._order[min(len(self._order) - 1, 0)])
        if not self.editors and not self.empty_hint.winfo_ismapped():
            self.empty_hint.place(relx=0.5, rely=0.42, anchor="center")
        self._notify_changed()

    # ── відновлення закритих вкладок ──────────────────────────────────────
    def reopen_last_closed(self) -> bool:
        """Відкрити останню закриту вкладку (Ctrl+Shift+T)."""
        while self._closed:
            path = self._closed.pop()
            if path.exists():
                return self.open_file(path)
        if self.on_status:
            self.on_status("Немає закритих вкладок для відновлення.")
        return False

    def closed_paths(self) -> list[Path]:
        """Закриті вкладки, які ще існують на диску (для меню)."""
        return [path for path in reversed(self._closed) if path.exists()]

    def reopen_path(self, path: Path) -> bool:
        if path in self._closed:
            self._closed.remove(path)
        return self.open_file(path)

    def close_others(self, frame_id: str) -> None:
        for key in [k for k in self._order if k != frame_id]:
            saved = self.close_tab(key)
            if not saved:
                return

    def close_all(self, *, force: bool = False) -> bool:
        for frame_id in list(self._order):
            if force:
                self._forget_tab(frame_id)
            elif not self.close_tab(frame_id):
                return False
        return True

    def reveal_in_explorer(self, frame_id: str) -> None:
        path = self.paths.get(frame_id)
        if path is None:
            return
        import subprocess

        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as exc:
            if self.on_status:
                self.on_status(f"Не вдалось відкрити провідник: {exc}")

    def copy_path(self, frame_id: str) -> None:
        path = self.paths.get(frame_id)
        if path is None:
            return
        self.clipboard_clear()
        self.clipboard_append(str(path))
        if self.on_status:
            self.on_status(f"Скопійовано шлях: {path}")

    # ── налаштування ───────────────────────────────────────────────────────
    def apply_settings(self) -> None:
        for editor in self.editors.values():
            editor.apply_settings()

    def reopen_with_encoding(self, encoding: str) -> None:
        editor = self.current()
        path = self.current_path()
        if not editor or not path:
            return
        raw = path.read_bytes()
        try:
            content = raw.decode(encoding)
        except UnicodeDecodeError:
            messagebox.showerror("Кодування", f"Файл не читається як {encoding}", parent=self)
            return
        editor.set_text(content.replace("\r\n", "\n"))
        editor.encoding = encoding  # type: ignore[attr-defined]
        if self.on_status:
            self.on_status(f"{path.name}: перечитано як {encoding}")
