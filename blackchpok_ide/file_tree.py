"""Файлове дерево робочої теки (ліва панель сучасної IDE)."""

from __future__ import annotations

import logging
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from . import theme, widgets

LOG = logging.getLogger("blackchpok.filetree")

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".idea", ".vscode",
    ".mcp_rag", ".buildtmp", ".ruff_cache", ".tox", "target", ".next",
}

FILE_ICONS = {
    ".py": "🐍", ".pyi": "🐍", ".js": "🟨", ".ts": "🟦", ".tsx": "🟦", ".jsx": "🟨",
    ".json": "🧾", ".md": "📘", ".txt": "📄", ".html": "🌐", ".css": "🎨",
    ".bat": "⚙", ".cmd": "⚙", ".ps1": "⚙", ".sh": "⚙", ".yml": "🧾", ".yaml": "🧾",
    ".toml": "🧾", ".ini": "🧾", ".sql": "🗃", ".db": "🗃", ".sqlite3": "🗃",
    ".png": "🖼", ".jpg": "🖼", ".svg": "🖼", ".ico": "🖼", ".pdf": "📕",
    ".exe": "🚀", ".dll": "🧩", ".zip": "📦",
}

BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".exe", ".dll", ".pyc", ".pdf",
              ".zip", ".7z", ".rar", ".db", ".sqlite3", ".woff", ".woff2", ".ttf", ".mp4", ".mp3"}


def icon_for(path: Path) -> str:
    if path.is_dir():
        return "📂"
    return FILE_ICONS.get(path.suffix.lower(), "📄")


def is_binary(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXT


class FileTree(ttk.Frame):
    """Дерево файлів з ленивим розкриттям тек."""

    def __init__(
        self,
        master: tk.Misc,
        on_open: Callable[[Path], None],
        *,
        root_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.on_open = on_open
        self.root_dir = root_dir
        self._nodes: dict[str, Path] = {}
        self._build()
        if root_dir:
            self.set_root(root_dir)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=(10, 6), pady=(8, 4))
        header.columnconfigure(0, weight=1)
        self.title = ttk.Label(header, text="ПРОВІДНИК", style="Header.TLabel")
        self.title.grid(row=0, column=0, sticky="w")

        self.btn_new = ttk.Button(header, text="＋", width=3, style="Icon.TButton",
                                  command=lambda: self._ask_create("file"))
        self.btn_new.grid(row=0, column=1, padx=(0, 2))
        self.btn_folder = ttk.Button(header, text="🗀", width=3, style="Icon.TButton",
                                     command=lambda: self._ask_create("dir"))
        self.btn_folder.grid(row=0, column=2, padx=(0, 2))
        self.btn_refresh = ttk.Button(header, text="↻", width=3, style="Icon.TButton", command=self.refresh)
        self.btn_refresh.grid(row=0, column=3)
        # Підказки: самі іконки без тексту не кажуть нічого ні новому
        # користувачу, ні скрін-рідеру.
        for button, tip in (
            (self.btn_new, "Створити файл у вибраній теці (або в корені проєкту)"),
            (self.btn_folder, "Створити теку у вибраному місці"),
            (self.btn_refresh, "Оновити дерево файлів (F5)"),
        ):
            try:
                widgets.Tip(button, tip)
            except (tk.TclError, AttributeError):
                LOG.debug("Підказку не додано", exc_info=True)

        style = ttk.Style(self)
        style.configure("Tree.Frame", background=theme.BG_ALT)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(0, 2))
        self.tree.column("#0", width=180, minwidth=90, stretch=True)
        self.tree.tag_configure("dir", foreground=theme.FG)
        self.tree.tag_configure("file", foreground=theme.FG)
        self.tree.tag_configure("py", foreground=theme.SYNTAX_COLORS.get("function", theme.ACCENT))

        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.scroll.set)

        self.tree.bind("<<TreeviewOpen>>", self._on_expand)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_context)

        self.menu = tk.Menu(self, tearoff=0, bg=theme.BG_INPUT, fg=theme.FG,
                            activebackground=theme.ACCENT, activeforeground=theme.FG_BRIGHT,
                            bd=0)
        self.menu.add_command(label="Відкрити", command=self._open_selected)
        self.menu.add_command(label="Відкрити в терміналі", command=self._open_terminal_here)
        self.menu.add_separator()
        self.menu.add_command(label="Новий файл", command=lambda: self._ask_create("file"))
        self.menu.add_command(label="Нова папка", command=lambda: self._ask_create("dir"))
        self.menu.add_command(label="Перейменувати", command=self._rename_selected)
        self.menu.add_command(label="Видалити", command=self._delete_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Копіювати шлях", command=self._copy_path)
        self.menu.add_command(label="Оновити", command=self.refresh)

        self.on_terminal: Optional[Callable[[Path], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None

    # ── корінь ─────────────────────────────────────────────────────────────
    def set_root(self, folder: Path) -> None:
        self.root_dir = folder
        self.title.configure(text=f"ПРОВІДНИК · {folder.name.upper() or folder}")
        self.refresh()

    def refresh(self) -> None:
        if not self.root_dir or not self.root_dir.exists():
            return
        selected = self.tree.selection()
        open_paths = [self._nodes[item] for item in selected if item in self._nodes]
        self.tree.delete(*self.tree.get_children(""))
        self._nodes.clear()
        self._insert_children("", self.root_dir)
        if open_paths:
            for item, path in list(self._nodes.items()):
                if path in open_paths:
                    self.tree.selection_set(item)
                    break

    def _insert_children(self, parent: str, folder: Path) -> None:
        try:
            entries = sorted(
                folder.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return
        for entry in entries:
            if entry.name in SKIP_DIRS and entry.is_dir():
                continue
            if entry.name.startswith(".") and entry.is_dir() and entry.name not in {".agents", ".cursor"}:
                continue
            item = self.tree.insert(parent, "end", text=f"  {icon_for(entry)}  {entry.name}",
                                    open=False, tags=("dir" if entry.is_dir() else "file",))
            self._nodes[item] = entry
            if entry.is_dir():
                self.tree.insert(item, "end", text="…", tags=("placeholder",))

    def _on_expand(self, _event=None) -> None:
        item = self.tree.focus()
        if not item or item not in self._nodes:
            return
        path = self._nodes[item]
        if not path.is_dir():
            return
        children = self.tree.get_children(item)
        if len(children) == 1 and self.tree.item(children[0], "text") == "…":
            self.tree.delete(children[0])
            self._insert_children(item, path)

    def _on_double_click(self, _event=None) -> None:
        item = self.tree.focus()
        if not item or item not in self._nodes:
            return
        path = self._nodes[item]
        if path.is_dir():
            self.tree.item(item, open=not self.tree.item(item, "open"))
            self._on_expand()
            return
        self.open_path(path)

    def open_path(self, path: Path) -> None:
        if is_binary(path):
            self._notify(f"Бінарний файл не відкриваю: {path.name}")
            return
        self.on_open(path)

    def reveal(self, path: Path | str) -> None:
        """Розкрити папку і виділити файл."""
        if not self.root_dir:
            return
        try:
            path = Path(path)
            relative = path.resolve().relative_to(self.root_dir.resolve())
        except (ValueError, TypeError, OSError):
            return
        parent_item = ""
        current = self.root_dir
        for part in relative.parts:
            current = current / part
            found = None
            for child in self.tree.get_children(parent_item):
                if self._nodes.get(child) == current:
                    found = child
                    break
            if found is None:
                self.tree.item(parent_item, open=True)
                self._on_expand()
                for child in self.tree.get_children(parent_item):
                    if self._nodes.get(child) == current:
                        found = child
                        break
            if found is None:
                return
            parent_item = found
            self.tree.item(found, open=current.is_dir())
        if parent_item:
            self.tree.selection_set(parent_item)
            self.tree.see(parent_item)

    # ── дії ────────────────────────────────────────────────────────────────
    def selected_path(self) -> Optional[Path]:
        item = self.tree.focus()
        return self._nodes.get(item) if item else None

    def _open_selected(self) -> None:
        path = self.selected_path()
        if path and path.is_file():
            self.open_path(path)

    def _open_terminal_here(self) -> None:
        path = self.selected_path()
        if path and self.on_terminal:
            self.on_terminal(path if path.is_dir() else path.parent)

    def _copy_path(self) -> None:
        path = self.selected_path()
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(str(path))
        self._notify(f"Скопійовано шлях: {path}")

    def _target_folder(self) -> Optional[Path]:
        path = self.selected_path()
        if path is None:
            return self.root_dir
        return path if path.is_dir() else path.parent

    def _ask_create(self, kind: str) -> None:
        from tkinter import simpledialog

        folder = self._target_folder()
        if folder is None:
            return
        label = "Ім'я файлу (можна з текою через /):" if kind == "file" else "Ім'я папки:"
        name = simpledialog.askstring("Створити", label, parent=self)
        if not name:
            return
        target = folder / name.strip().replace("\\", "/")
        try:
            if kind == "dir" or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_text("", encoding="utf-8")
            self.refresh()
            self.reveal(target)
            if target.is_file():
                self.on_open(target)
            self._notify(f"Створено: {target.name}")
        except OSError as exc:
            self._notify(f"Не вдалось створити: {exc}")

    def _rename_selected(self) -> None:
        from tkinter import simpledialog

        path = self.selected_path()
        if not path:
            return
        new_name = simpledialog.askstring("Перейменувати", "Нове ім'я:", initialvalue=path.name, parent=self)
        if not new_name or new_name == path.name:
            return
        try:
            path.rename(path.parent / new_name)
            self.refresh()
            self._notify(f"Перейменовано: {new_name}")
        except OSError as exc:
            self._notify(f"Не вдалось перейменувати: {exc}")

    def _delete_selected(self) -> None:
        from tkinter import messagebox

        path = self.selected_path()
        if not path:
            return
        if not messagebox.askyesno("Видалити", f"Видалити «{path.name}»?\n\nЦе незворотно.", parent=self):
            return
        try:
            if path.is_dir():
                import shutil

                shutil.rmtree(path)
            else:
                path.unlink()
            self.refresh()
            self._notify(f"Видалено: {path.name}")
        except OSError as exc:
            self._notify(f"Не вдалось видалити: {exc}")

    def _on_context(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _notify(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)
