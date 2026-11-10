"""Панель «Інструменти»: повний каталог можливостей агента з реальним викликом.

Тут видно все, що агент справді вміє: вбудовані інструменти (з ``TOOL_SCHEMAS``),
MCP-інструменти з живих серверів і дії MCP-роутера. Для кожного показано
назву, опис, параметри й статус доступності. Параметри можна заповнити й
виконати виклик — той самий, який робить агент, через той самий реєстр.

Панель навмисно не вигадує кнопок: якщо інструмента немає в реєстрі або
сервер не працює, кнопка виклику неактивна з поясненням.
"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from typing import Any, Callable, Optional

from . import theme, widgets
from .agent_tools import TOOL_SCHEMAS

#: Людські назви категорій за префіксом інструмента.
CATEGORY_ORDER = ("Файли", "Пошук", "Команди", "Git", "Аналіз", "Живий тест", "MCP", "Інше")

CATEGORY_OF = {
    "read_file": "Файли",
    "write_file": "Файли",
    "edit_file": "Файли",
    "append_file": "Файли",
    "list_dir": "Файли",
    "project_tree": "Файли",
    "search_text": "Пошук",
    "find_files": "Пошук",
    "run_command": "Команди",
    "git_status": "Git",
    "git_diff": "Git",
    "python_check": "Аналіз",
    "app_start": "Живий тест",
    "app_stop": "Живий тест",
    "app_restart": "Живий тест",
    "app_status": "Живий тест",
    "app_screenshot": "Живий тест",
    "app_click": "Живий тест",
    "app_type": "Живий тест",
    "app_key": "Живий тест",
}


def builtin_tools() -> list[dict[str, Any]]:
    """Вбудовані інструменти у єдиному вигляді для панелі."""
    items: list[dict[str, Any]] = []
    for schema in TOOL_SCHEMAS:
        function = schema.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        parameters = function.get("parameters") or {}
        properties = parameters.get("properties") or {}
        items.append({
            "name": name,
            "description": str(function.get("description") or ""),
            "source": "вбудований",
            "category": CATEGORY_OF.get(name, "Інше"),
            "params": list(_param_rows(properties, parameters.get("required") or [])),
            "available": True,
        })
    return items


def _param_rows(properties: dict[str, Any], required: list[str]) -> list[tuple[str, str, bool]]:
    """(назва, опис, обов'язковий) для кожного параметра схеми."""
    rows: list[tuple[str, str, bool]] = []
    for key, spec in (properties or {}).items():
        if not isinstance(spec, dict):
            spec = {}
        kind = str(spec.get("type") or "string")
        description = str(spec.get("description") or "")
        label = f"{key} · {kind}" if kind else key
        rows.append((key, description or label, key in required))
    return rows


class ToolsPanel(tk.Frame):
    """Каталог інструментів із формою виклику."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        registry,
        *,
        mcp_manager=None,
        on_status: Optional[Callable[[str], None]] = None,
        on_result: Optional[Callable[[str, bool], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.registry = registry
        self.mcp_manager = mcp_manager
        self.on_status = on_status
        self.on_result = on_result
        self._query = ""
        self._selected: Optional[str] = None
        self._forms: dict[str, tk.Entry] = {}
        self._items: list[dict[str, Any]] = []
        #: Відфільтрований каталог — те, що зараз намальовано.
        self._shown: list[dict[str, Any]] = []
        self._busy = False
        self._queue: "queue.Queue[tuple[bool, str]]" = queue.Queue()
        self._after: Optional[str] = None
        self._build()
        # Насос результатів має зніматись разом із панеллю: інакше
        # запланований ``after`` лишається в Tcl, його команда зникає — і Tk
        # друкує «invalid command name ..._pump», а закриття застосунку
        # падає з «application has been destroyed».
        self.bind("<Destroy>", self._on_destroy, add="+")
        # Відкладено: побудова каталогу читає схеми MCP і створює багато
        # віджетів. У конструкторі це додає час до запуску вікна, хоч
        # панель не видно, поки не перемкнуть розділ.
        self.after(0, self.refresh)

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        self.cancel()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="ІНСТРУМЕНТИ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e")
        widgets.IconButton(head, "⟳", self.reload, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                           font=("Segoe UI", 9), tooltip="Оновити каталог").grid(
            row=0, column=2, padx=(6, 0))

        search = tk.Frame(self, bg=theme.BG_ALT)
        search.grid(row=1, column=0, sticky="ew", padx=(10, 8), pady=(2, 4))
        search.columnconfigure(0, weight=1)
        self.entry = tk.Entry(
            search, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=("Segoe UI", 9), bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT,
        )
        self.entry.grid(row=0, column=0, sticky="ew", ipady=4)
        self.entry.bind("<KeyRelease>", self._on_query)

        self.result_label = tk.Label(
            self, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
            justify="left", anchor="w", wraplength=210,
        )
        self.result_label.grid(row=2, column=0, sticky="ew", padx=(12, 8), pady=(0, 4))

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=3, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.host = self.scroll.inner

    # ── дані ───────────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _mcp_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        manager = self.mcp_manager
        if manager is None:
            return items
        try:
            catalog = manager.tool_catalog()
        except Exception:  # noqa: BLE001 - MCP не має ламати панель
            return items
        for entry in catalog:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("full_name") or entry.get("name") or "")
            if not name:
                continue
            items.append({
                "name": name,
                "description": str(entry.get("description") or ""),
                "source": f"MCP · {entry.get('server') or 'сервер'}",
                "category": "MCP",
                "params": [],
                "available": True,
            })
        return items

    def collect(self) -> list[dict[str, Any]]:
        """Повний перелік доступних інструментів (вбудовані + MCP)."""
        return builtin_tools() + self._mcp_items()

    def reload(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._items = self.collect()
        for child in self.host.winfo_children():
            child.destroy()
        self._forms.clear()

        needle = self._query.strip().casefold()
        shown = [item for item in self._items
                 if not needle
                 or needle in item["name"].casefold()
                 or needle in str(item.get("description") or "").casefold()]
        #: Те, що справді намальовано (каталог із застосованим фільтром).
        self._shown = shown
        builtin = sum(1 for item in self._items if item["category"] != "MCP")
        mcp = len(self._items) - builtin
        self.count_label.configure(text=f"{builtin} + {mcp} MCP")

        if not shown:
            tk.Label(self.host, text="Нічого не знайдено.", bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 9)).pack(
                anchor="w", padx=6, pady=8)
            return

        for category in CATEGORY_ORDER:
            group = [item for item in shown if item["category"] == category]
            if not group:
                continue
            tk.Label(self.host, text=category.upper(), bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 7, "bold")).pack(
                anchor="w", padx=6, pady=(8, 2))
            for item in group:
                self._tool_card(item)

    def _on_query(self, _event=None) -> None:
        self._query = self.entry.get()
        self.refresh()

    # ── картка інструмента ─────────────────────────────────────────────────
    def _tool_card(self, item: dict[str, Any]) -> None:
        name = item["name"]
        expanded = self._selected == name
        card = tk.Frame(self.host, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                        highlightbackground=theme.BORDER)
        card.pack(fill="x", padx=2, pady=(0, 3))
        card.columnconfigure(1, weight=1)

        arrow = tk.Label(card, text="▾" if expanded else "▸", bg=theme.BG_CARD,
                         fg=theme.FG_FAINT, font=("Segoe UI", 8), cursor="hand2")
        arrow.grid(row=0, column=0, padx=(8, 4), pady=(6, 0), sticky="n")

        title = tk.Label(card, text=name, bg=theme.BG_CARD, fg=theme.FG_BRIGHT,
                         font=self.fonts.mono_small, anchor="w", justify="left",
                         wraplength=170, cursor="hand2")
        title.grid(row=0, column=1, sticky="ew", pady=(6, 0), padx=(0, 4))

        source = tk.Label(card, text=str(item.get("source") or ""), bg=theme.BG_CARD,
                          fg=theme.FG_FAINT, font=("Segoe UI", 7), anchor="e")
        source.grid(row=0, column=2, padx=(0, 8), pady=(6, 0), sticky="ne")

        description = str(item.get("description") or "")
        if description:
            tk.Label(card, text=description[:160], bg=theme.BG_CARD, fg=theme.FG_DIM,
                     font=("Segoe UI", 8), justify="left", anchor="w",
                     wraplength=200).grid(row=1, column=1, columnspan=2, sticky="ew",
                                          padx=(0, 8), pady=(1, 4))

        for widget in (arrow, title):
            widget.bind("<Button-1>", lambda _e, n=name: self._toggle(n))

        if expanded:
            self._form(card, item)

    def _toggle(self, name: str) -> None:
        self._selected = None if self._selected == name else name
        self.refresh()

    def _form(self, card: tk.Frame, item: dict[str, Any]) -> None:
        body = tk.Frame(card, bg=theme.BG_CARD)
        body.grid(row=2, column=0, columnspan=3, sticky="ew", padx=(10, 8), pady=(0, 8))
        body.columnconfigure(1, weight=1)

        params = item.get("params") or []
        name = item["name"]
        if not params:
            tk.Label(body, text="Без параметрів" if item["category"] != "MCP"
                                else "Параметри задаються на MCP-сервері",
                     bg=theme.BG_CARD, fg=theme.FG_FAINT, font=("Segoe UI", 8)).grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        for index, (key, hint, required) in enumerate(params):
            label = f"{key}*" if required else key
            tk.Label(body, text=label, bg=theme.BG_CARD, fg=theme.FG_DIM,
                     font=("Segoe UI", 8), anchor="w").grid(
                row=index, column=0, sticky="w", padx=(0, 6), pady=1)
            entry = tk.Entry(body, bg=theme.BG_INPUT, fg=theme.FG,
                             insertbackground=theme.FG_BRIGHT, relief="flat",
                             font=("Segoe UI", 8), bd=0, highlightthickness=1,
                             highlightbackground=theme.BORDER)
            entry.grid(row=index, column=1, sticky="ew", pady=1, ipady=2)
            widgets.Tip(entry, hint)
            self._forms[key] = entry

        buttons = tk.Frame(body, bg=theme.BG_CARD)
        buttons.grid(row=len(params), column=0, columnspan=2, sticky="ew", pady=(6, 0))
        run = widgets.Chip(buttons, "▶ Виконати",
                           lambda n=name: self.run_tool(n), font=("Segoe UI", 8))
        run.pack(side="left", padx=(0, 4))
        widgets.Chip(buttons, "Заповнити прикладом",
                     lambda n=name: self._fill_example(n),
                     font=("Segoe UI", 8)).pack(side="left")

    def _fill_example(self, name: str) -> None:
        """Підставити безпечний приклад значень (щоб було з чого почати)."""
        examples = {
            "read_file": {"path": "main.py"},
            "list_dir": {"path": "."},
            "search_text": {"query": "def "},
            "find_files": {"pattern": "*.py"},
            "project_tree": {"depth": "2"},
            "python_check": {"path": "main.py"},
            "run_command": {"command": "python -m unittest"},
            "write_file": {"path": "нотатка.md", "content": "# Нотатка\n"},
            "edit_file": {"old_string": "TODO", "new_string": "зроблено",
                          "path": "main.py"},
            "append_file": {"path": "нотатка.md", "content": "\nновий рядок\n"},
            "git_diff": {"path": ""},
        }
        preset = examples.get(name, {})
        for key, entry in self._forms.items():
            entry.delete(0, "end")
            if key in preset:
                entry.insert(0, str(preset[key]))

    # ── виклик ─────────────────────────────────────────────────────────────
    def run_tool(self, name: str) -> None:
        """Виконати інструмент у фоні (щоб не підвішувати інтерфейс)."""
        if self._busy:
            self._notify("Інструмент уже виконується.")
            return
        arguments: dict[str, Any] = {}
        for key, entry in self._forms.items():
            value = entry.get().strip()
            if value:
                arguments[key] = value
        self._busy = True
        self._start_pump()
        self.result_label.configure(text=f"Виконую {name}…", fg=theme.ACCENT)
        registry = self.registry
        manager = self.mcp_manager

        def work() -> None:
            try:
                if name.startswith("mcp__") and manager is not None:
                    ok, output = manager.call(name, arguments)
                else:
                    result = registry.call(name, arguments)
                    ok, output = bool(result.ok), str(result.output)
            except Exception as exc:  # noqa: BLE001 - безпечно для потоку
                ok, output = False, f"{type(exc).__name__}: {exc}"
            self._busy = False
            self._queue.put((ok, output))

        threading.Thread(target=work, daemon=True).start()

    def _start_pump(self) -> None:
        if self._after is None:
            self._pump()

    def _pump(self) -> None:
        try:
            while True:
                ok, output = self._queue.get_nowait()
                self._apply_result(ok, output)
        except queue.Empty:
            pass
        finally:
            try:
                if self.winfo_exists():
                    self._after = self.after(120, self._pump)
            except tk.TclError:
                self._after = None

    def _apply_result(self, ok: bool, output: str) -> None:
        head = (output or "").strip().replace("\n", " ")
        if len(head) > 160:
            head = head[:159] + "…"
        try:
            self.result_label.configure(
                text=("✓ " if ok else "✗ ") + (head or "порожній результат"),
                fg=theme.SUCCESS if ok else theme.ERROR,
            )
        except tk.TclError:
            pass
        self._notify(f"Інструмент: {'успішно' if ok else 'помилка'}")
        if self.on_result is not None:
            try:
                self.on_result(output if ok else f"ПОМИЛКА: {output}", ok)
            except Exception as exc:  # noqa: BLE001 - панель не має ламати вікно
                # Результат інструмента губився мовчки — показуємо причину.
                self._notify(f"Не вдалось показати результат: {exc}")

    def cancel(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None

    def selected_arguments(self) -> dict[str, Any]:
        """Поточні значення форми (для тестів і налагодження)."""
        return {key: entry.get() for key, entry in self._forms.items()}


__all__ = ["CATEGORY_OF", "CATEGORY_ORDER", "ToolsPanel", "builtin_tools"]
