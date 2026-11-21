"""Вкладки редактора: смуга вкладок із кнопками закриття, збереження, контекст.

Замість ``ttk.Notebook`` використовується власна смуга: у сучасному дизайні
вкладка має закриватись хрестиком, підсвічуватись і мати контекстне меню, а
``Notebook`` цього не дає.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

# ── ПРЯМИЙ ЗАПУСК ФАЙЛУ (виправлено після збою) ───────────────────────────
# Відносні імпорти працюють лише всередині пакета: коли файл запускають як
# скрипт (``python blackchpok_ide/tabs.py``), ``__package__`` порожній, і
# Python падає з
#     ImportError: attempted relative import with no known parent package
# Це не помилка логіки, а спосіб запуску. Тому для прямого запуску додаємо
# корінь проєкту в ``sys.path`` і беремо ТІ САМІ модулі абсолютними іменами.
# Усередині пакета (звичайний шлях — ``main.py``) працює гілка ``else``,
# тобто поведінка не змінюється.
if __package__ in (None, ""):                        # pragma: no cover
    import sys as _sys
    from pathlib import Path as _Path

    _root = _Path(__file__).resolve().parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from blackchpok_ide import theme, widgets
    from blackchpok_ide import workspace as ws
    from blackchpok_ide.editor import CodeEditor
else:
    from . import theme, widgets, workspace as ws
    from .editor import CodeEditor

MODIFIED_DOT = "●"


def _char_index(text: str, offset: int) -> str:
    """Позиція символу ``offset`` у тексті як індекс ``tk.Text``."""
    if offset <= 0 or not text:
        return "1.0"
    if offset >= len(text):
        return "end"
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset if last_nl < 0 else offset - last_nl - 1
    return f"{line}.{col}"


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
                                    font=theme.font(9), bd=0, cursor="hand2")
        self.title_label.pack(side="left")

        self.close_label = tk.Label(self.inner, text="✕", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=theme.font(8), bd=0, padx=4, cursor="hand2")
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
        #: Ідентифікатор відкладеного автозбереження (``None`` — не заплановано).
        #:
        #: Один таймер на всі вкладки, а не по одному на кожну: правка агента
        #: чіпає десятки файлів підряд, і окремі таймери дали б сотні
        #: одночасних записів на диск.
        self._autosave_job: Optional[str] = None
        #: Скільки разів автозбереження вже спрацювало (для тестів і статусу).
        self.autosave_runs: int = 0
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
                                              fg=theme.FG_FAINT, font=theme.font(11),
                                              tooltip="Новий файл (Ctrl+N)")
        self.new_tab_btn.grid(row=0, column=1, padx=(4, 8))

        self.content = tk.Frame(self, bg=theme.BG_EDITOR, bd=0, highlightthickness=0)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.empty_hint = tk.Label(
            self.content,
            text="Немає відкритих файлів\n\nCtrl+P — швидке відкриття · Ctrl+Shift+P — палітра команд",
            bg=theme.BG_EDITOR, fg=theme.FG_FAINT, font=theme.font(10), justify="center",
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
    def open_file(self, path: Path, *, line: int = 0, focus: bool = True) -> bool:
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
            if focus:
                self.editors[existing].text.focus_set()
            return True
        try:
            content, encoding = ws.read_text_file(path)
        except ws.WorkspaceError as exc:
            # ── БЕЗ МОДАЛЬНОГО ВІКНА ───────────────────────────────────────
            # Раніше тут з'являвся ``showwarning`` — і кожна невдача відкриття
            # (бінарний файл, файл зайнятий іншим процесом) зупиняла роботу
            # діалогом, який треба було закрити руками. Тепер причина йде в
            # рядок стану: інформації достатньо, а робота не спиняється.
            if self.on_status:
                self.on_status(f"Не вдалось відкрити {path.name}: {exc}")
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
        if focus:
            editor.text.focus_set()
        if line:
            editor.goto_line(line)
        if self.on_status:
            self.on_status(f"Відкрито {path.name} · {len(content.splitlines())} рядків · {encoding}")
        return True

    def show_model_text(self, path: Path, content: str, *, typewrite: bool = False) -> bool:
        """Відкрити файл і показати текст моделі у вкладці.

        ``typewrite`` набирає змінену частину видимими шматками, щоб у
        відкритому чаті було видно, як файл змінюється. Великий файл
        з'являється одразу: інакше набір на тисячі символів лише заважав би.
        """
        path = Path(path)
        self._type_token = int(getattr(self, "_type_token", 0)) + 1
        token = self._type_token
        editor = self.by_path(path)
        if editor is None:
            frame_id, editor = self._new_editor(path.name, path.name)
            editor.path = path
            editor.filename = path.name
            editor.set_text("")
            self.editors[frame_id] = editor
            self.paths[frame_id] = path
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            self._by_path[key] = frame_id
            self.select(frame_id)
        else:
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            frame_id = self._by_path.get(key, "")
            if frame_id:
                self.select(frame_id)
        current = editor.get_text()
        if current == content:
            editor.schedule_analysis()
            return True
        if not typewrite or len(content) > 8000:
            editor.set_text(content)
            editor.modified = False
            return True
        self._type_change(editor, current, content, token)
        return True

    def _type_change(self, editor: CodeEditor, old: str, new: str, token: int) -> None:
        """Замінити відмінну середину тексту короткими вставками."""
        prefix = 0
        limit = min(len(old), len(new))
        while prefix < limit and old[prefix] == new[prefix]:
            prefix += 1
        suffix = 0
        room = limit - prefix
        while suffix < room and old[-1 - suffix] == new[-1 - suffix]:
            suffix += 1
        middle = new[prefix:len(new) - suffix] if suffix else new[prefix:]
        if len(middle) > 2400:
            editor.set_text(new)
            editor.modified = False
            return
        start = _char_index(old, prefix)
        end = _char_index(old, len(old) - suffix if suffix else len(old))
        try:
            editor.text.configure(state="normal")
            if start != end:
                editor.text.delete(start, end)
            editor.text.mark_set("insert", start)
            editor.text.see("insert")
        except tk.TclError:
            editor.set_text(new)
            return
        pieces = [middle[index:index + 64] for index in range(0, len(middle), 64)]

        def step(index: int = 0) -> None:
            if token != getattr(self, "_type_token", token):
                return
            try:
                if index >= len(pieces):
                    editor.modified = False
                    editor.text.edit_modified(False)
                    editor._refresh_gutter(force=True)
                    editor.schedule_analysis()
                    return
                editor.text.insert("insert", pieces[index])
                editor.text.see("insert")
                editor.modified = True
                editor._refresh_gutter()
                editor.after(12, lambda i=index + 1: step(i))
            except tk.TclError:
                return

        step()

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

    def select(self, frame_id: str | int) -> None:
        """Активувати вкладку.

        Приймає АБО ідентифікатор вкладки (``str``, внутрішній ключ), АБО
        її номер у смузі (``int``). Номер — те, чим природно користується
        виклик на кшталт «перемкнутись на другу вкладку»; раніше ``select(0)``
        мовчки нічого не робив, бо ``0`` не збігався з жодним ключем, і
        здавалося, що перемикання вкладок не працює.
        """
        if isinstance(frame_id, int) and not isinstance(frame_id, bool):
            order = list(self.editors)
            if not order or not -len(order) <= frame_id < len(order):
                return
            frame_id = order[frame_id]
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
        # Кожна зміна (і ручна, і правка агента) планує запис на диск.
        # Раніше файл лишався зміненим у пам'яті до Ctrl+S.
        if getattr(editor, "modified", False):
            self.schedule_autosave()

    def rename_tab(self, editor: CodeEditor, title: str) -> None:
        tab = self._tabs.get(str(editor.master))
        if tab is not None:
            tab.set_title(title, bool(editor.modified))

    # ── збереження ─────────────────────────────────────────────────────────
    def _tab_key(self, frame_id: str | int) -> str:
        """Перетворити номер вкладки на внутрішній ключ (або повернути як є).

        Публічні методи приймають і ключ, і номер: виклик із номера —
        природний для «закрий першу вкладку», і без цього перетворення
        ``close_tab(0)`` мовчки нічого не робив.
        """
        if isinstance(frame_id, int) and not isinstance(frame_id, bool):
            order = list(self.editors)
            if not order or not -len(order) <= frame_id < len(order):
                return ""
            return order[frame_id]
        return str(frame_id)

    def save_tab(self, frame_id: str | int, *, force_as: bool = False) -> bool:
        frame_id = self._tab_key(frame_id)
        editor = self.editors.get(frame_id)
        if editor is None:
            return False
        path = self.paths.get(frame_id)
        if force_as or path is None:
            return self._save_as(frame_id, editor)
        try:
            ws.write_text_file(path, editor.get_text())
        except ws.WorkspaceError as exc:
            # Без діалогу: причина у рядку стану (див. open_file).
            if self.on_status:
                self.on_status(f"Не вдалось зберегти {path.name}: {exc}")
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
            if self.on_status:
                self.on_status(f"Не вдалось зберегти {path.name}: {exc}")
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

    # ── автозбереження ─────────────────────────────────────────────────────
    @property
    def _autosave_enabled(self) -> bool:
        ui = getattr(self.settings, "ui", None)
        return bool(getattr(ui, "auto_save", True))

    def schedule_autosave(self) -> None:
        """Запланувати запис змінених файлів на диск.

        Вимога користувача (21.11.2026): «всі файли мають автоматично
        зберігатися». Раніше зміни жили лише в пам'яті до Ctrl+S: правка
        агента показувалась у редакторі (``modified = True``), а на диску
        лишався старий вміст. Після аварійного закриття робота зникала.

        Чому відкладено, а не одразу. Під час стріму правка приходить
        десятками шматків, і запис на кожен — це сотні операцій із диском
        на один файл. Таймер скидається на кожну зміну, тож файл пишеться
        один раз — після паузи в наборі.
        """
        if not self._autosave_enabled:
            return
        delay_ms = int(max(0.2, float(
            getattr(getattr(self.settings, "ui", None), "auto_save_delay", 2.0)
            or 2.0)) * 1000)
        # Попередній таймер знімаємо: інакше запис спрацює посеред стріму
        # й запише НЕДОписану правку — саме так на диску опинявся
        # напівфайл, який потім дописувався ще раз.
        job = self._autosave_job
        self._autosave_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        try:
            self._autosave_job = self.after(delay_ms, self._run_autosave)
        except tk.TclError:
            self._autosave_job = None

    def _run_autosave(self) -> None:
        """Записати всі змінені вкладки (виклик таймера)."""
        self._autosave_job = None
        if not self._autosave_enabled:
            return
        saved = self.flush_modified()
        if saved:
            self.autosave_runs += 1
            if self.on_status:
                self.on_status(f"Автозбережено файлів: {saved}")

    def flush_modified(self) -> int:
        """Негайно зберегти всі змінені файли; повертає кількість.

        Окремий метод (а не лише таймер), бо його ж кличуть у критичні
        моменти — перед закриттям вікна, перед стартом правки агента й
        перед читанням файлу з диска. Там чекати на таймер не можна.
        """
        count = 0
        for frame_id in list(self._order):
            editor = self.editors.get(frame_id)
            path = self.paths.get(frame_id)
            if editor is None or path is None:
                continue
            if not getattr(editor, "modified", False):
                continue
            # ── ПРАВКА АГЕНТА В ПРОЦЕСІ — НЕ ЗБЕРІГАЄМО ────────────────────
            # Під час живої правки в буфері лежать ОБИДВІ версії: старий
            # текст (червоний) і новий (зелений). Запис такого буфера на
            # диск і був причиною дублів у файлах — саме так у
            # ``main_window.py``, ``live_edit.py`` і ``night_shift.py``
            # з'явились копії функцій і блоків. Чекаємо, доки правка
            # застосується (``accept`` прибере стару версію).
            if getattr(editor, "live_edit_active", False):
                continue
            try:
                ws.write_text_file(path, editor.get_text())
            except (ws.WorkspaceError, OSError):
                continue
            editor.modified = False
            tab = self._tabs.get(frame_id)
            if tab is not None:
                tab.set_title(path.name, False)
            count += 1
        if count:
            self._notify_changed()
        return count

    def cancel_autosave(self) -> None:
        """Зупинити відкладений запис (вікно закривається)."""
        job = self._autosave_job
        self._autosave_job = None
        if job is None:
            return
        try:
            self.after_cancel(job)
        except (tk.TclError, ValueError):
            pass

    # ── закриття ───────────────────────────────────────────────────────────
    def close_current(self) -> bool:
        if not self._active:
            return False
        return self.close_tab(self._active)

    def close_tab(self, frame_id: str | int) -> bool:
        frame_id = self._tab_key(frame_id)
        if not frame_id:
            return False
        editor = self.editors.get(frame_id)
        if editor is None:
            return False
        if editor.modified:
            # ── БЕЗ ПИТАННЯ «ЗБЕРЕГТИ?» (вимога користувача) ───────────────
            # Раніше тут був ``askyesnocancel``: закриття вкладки посеред
            # роботи зупиняло все модальним вікном, і агент чекав, поки
            # людина натисне кнопку. Тепер файл із шляхом зберігається
            # МОВЧКИ (це те саме, що зробила б людина), і вкладка закривається.
            #
            # Для файлу без імені зберегти нікуди — тоді вкладку лишаємо
            # відкритою й пишемо підказку в рядок стану: жодного діалогу,
            # жодної втраченої роботи.
            path = self.paths.get(frame_id)
            if path is None:
                if self.on_status:
                    self.on_status("Файл без імені — збережи його (Ctrl+S) "
                                    "або закрий після цього.")
                return False
            if not self.save_tab(frame_id):
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
    def reload_from_disk(self, *, force: bool = False) -> int:
        """Перечитати відкриті файли з диска. Повертає кількість оновлених.

        Потрібно після дій, що змінюють файли ПОВЗ редактор: відкат чи
        прийняття змін у панелі «Зміни», ``git checkout``, робота агента в
        іншій копії. Без цього вкладка показувала старий текст, і наступне
        збереження повертало б скасовану зміну назад.

        Вкладки з незбереженими правками пропускаємо (``force=True``
        перезаписує і їх): мовчки викидати текст користувача не можна.
        """
        updated = 0
        for frame_id, path in list(self.paths.items()):
            editor = self.editors.get(frame_id)
            if editor is None or path is None:
                continue
            try:
                if not path.exists():
                    continue
                if not force and editor.modified:
                    continue
                content, encoding = ws.read_text_file(path)
            except (ws.WorkspaceError, OSError):
                continue
            current = editor.text.get("1.0", "end-1c")
            if current == content:
                continue
            editor.set_text(content)
            editor.encoding = encoding  # type: ignore[attr-defined]
            self._notify_changed()
            updated += 1
        return updated

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

    def close_others(self, frame_id: str | int) -> None:
        frame_id = self._tab_key(frame_id)
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

    def reveal_in_explorer(self, frame_id: str | int) -> None:
        path = self.paths.get(self._tab_key(frame_id))
        if path is None:
            return
        import subprocess

        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as exc:
            if self.on_status:
                self.on_status(f"Не вдалось відкрити провідник: {exc}")

    def copy_path(self, frame_id: str | int) -> None:
        path = self.paths.get(self._tab_key(frame_id))
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
            # Без діалогу: людина бачить причину в рядку стану, редактор
            # лишається з попереднім вмістом — нічого не втрачено.
            if self.on_status:
                self.on_status(f"{path.name}: не читається як {encoding} — "
                                "вибери інше кодування.")
            return
        editor.set_text(content.replace("\r\n", "\n"))
        editor.encoding = encoding  # type: ignore[attr-defined]
        if self.on_status:
            self.on_status(f"{path.name}: перечитано як {encoding}")
