"""Панель «MCP-сервери»: перелік підключених серверів, їхні інструменти.

MCP (Model Context Protocol) дає агенту додаткові інструменти із зовнішніх
процесів. Панель показує, що саме підключено, і дозволяє перезапустити
сервер або додати новий із конфігурації робочої теки.
"""

from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import mcp_client, theme, widgets

CONFIG_CANDIDATES = (
    ".mcp.json",
    ".cursor/mcp.json",
    "mcp.json",
    ".vscode/mcp.json",
)


def workspace_config_paths(root: Path) -> list[Path]:
    """Усі файли конфігурації MCP у робочій теці."""
    root = Path(root)
    return [root / name for name in CONFIG_CANDIDATES if (root / name).is_file()]


class McpPanel(tk.Frame):
    """Список MCP-серверів і їхніх інструментів."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        manager: mcp_client.McpManager,
        root_provider: Callable[[], Optional[Path]],
        *,
        on_status: Optional[Callable[[str], None]] = None,
        on_restart: Optional[Callable[[], None]] = None,
        watcher: Optional[object] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.manager = manager
        self.root_provider = root_provider
        self.on_status = on_status
        self.on_restart = on_restart
        #: Наглядач MCP. Потрібен для двох речей, яких раніше не було:
        #: кнопки «Діагностика» (стан серверів із наглядача) і того, щоб
        #: сервери, підняті З ЦІЄЇ панелі, теж ним контролювались.
        self.watcher = watcher
        #: Результати з фонових потоків → головний потік (безпечно для Tk).
        self._ui_queue: "queue.Queue[dict[str, str]]" = queue.Queue()
        self._drain_job: Optional[str] = None
        self._build()
        # Таймер опитування має зніматись разом із панеллю: інакше
        # запланований ``after`` лишається в Tcl і Tk скаржиться
        # «invalid command name ..._drain_results» після знищення.
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        job = self._drain_job
        self._drain_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        head = tk.Frame(self, bg=theme.BG)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(8, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="MCP-СЕРВЕРИ", bg=theme.BG, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.summary = tk.Label(head, text="не підключено", bg=theme.BG, fg=theme.FG_FAINT,
                                font=("Segoe UI", 8), anchor="e")
        self.summary.grid(row=0, column=1, sticky="e", padx=(6, 0))

        actions = tk.Frame(self, bg=theme.BG)
        actions.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(2, 4))
        widgets.Chip(actions, "⟳ Перезапустити", self.restart, font=("Segoe UI", 8)).pack(
            side="left", padx=(0, 4))
        widgets.Chip(actions, "＋ З конфігурації", self.load_from_workspace,
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        # Діагностика наглядача: до цього ``Watcher.diagnostics()`` був
        # недосяжний із інтерфейсу — код існував, а побачити його було ніде.
        widgets.Chip(actions, "🩺 Діагностика", self.show_diagnostics,
                     font=("Segoe UI", 8)).pack(side="left")

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.host = self.scroll.inner

    # ── дії ────────────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def restart(self) -> None:
        if self.on_restart:
            self.on_restart()
        self.refresh()
        self._notify("MCP-сервери перезапущено.")

    def load_from_workspace(self) -> None:
        root = self.root_provider() if self.root_provider else None
        if not root:
            self._notify("Спочатку відкрий теку проєкту.")
            return
        paths = workspace_config_paths(Path(root))
        if not paths:
            self._notify("У теці немає .mcp.json або .cursor/mcp.json.")
            return
        configs = mcp_client.McpManager.load_configs(paths)
        if not configs:
            self._notify("Конфігурація MCP порожня.")
            return
        import threading

        # Сервери, підняті звідси, мусять бути ПІД НАГЛЯДОМ: раніше цей
        # шлях запускав їх напряму, без ``watchdog.remember`` і без старту
        # наглядача — і померлий сервер лишався зі статусом «працює».
        if self.watcher is not None:
            try:
                self.watcher.remember(configs)
            except Exception:  # noqa: BLE001 - наглядач необов'язковий
                pass

        # Результат із фонового потоку повертаємо через чергу: викликати
        # ``after()`` поза головним циклом Tk небезпечно (а в Release-збірці
        # це падає з «main thread is not in main loop»).
        def work() -> None:
            statuses = self.manager.start_all(configs)
            self._ui_queue.put(statuses)

        self._notify(f"Запускаю MCP-сервери: {len(configs)}…")
        threading.Thread(target=work, daemon=True).start()
        self._schedule_drain()

    def show_diagnostics(self) -> None:
        """Показати стан серверів із наглядача (він знає більше за статус)."""
        watcher = self.watcher
        if watcher is None:
            self._notify("Наглядач MCP не підключений до панелі.")
            return
        try:
            text = watcher.diagnostics()
        except Exception as exc:  # noqa: BLE001 - діагностика не має падати
            self._notify(f"Діагностика недоступна: {exc}")
            return
        # Показуємо в самій панелі, а не в модальному вікні: користувач
        # має бачити список серверів і результат одночасно.
        for child in self.host.winfo_children():
            child.destroy()
        tk.Label(self.host, text="ДІАГНОСТИКА НАГЛЯДАЧА", bg=theme.BG,
                 fg=theme.FG_BRIGHT, font=("Segoe UI", 9, "bold"),
                 anchor="w").pack(fill="x", padx=6, pady=(8, 4))
        tk.Label(self.host, text=text, bg=theme.BG, fg=theme.FG_DIM,
                 font=self.fonts.mono_small, anchor="w", justify="left",
                 wraplength=430).pack(fill="x", padx=6, pady=(0, 10))
        widgets.Chip(self.host, "← Назад до серверів", self.refresh,
                     font=("Segoe UI", 8)).pack(anchor="w", padx=6, pady=(0, 10))

    def _schedule_drain(self) -> None:
        """Головний потік: перевірити чергу результатів."""
        self._drain_job = None
        try:
            if not self.winfo_exists():
                return
            self._drain_job = self.after(80, self._drain_results)
        except tk.TclError:
            self._drain_job = None

    def _drain_results(self) -> None:
        self._drain_job = None
        got = None
        try:
            got = self._ui_queue.get_nowait()
        except queue.Empty:
            got = None
        if got is not None:
            self._after_start(got)
            return
        self._schedule_drain()

    def _after_start(self, statuses: dict[str, str]) -> None:
        self.refresh()
        # Сервери піднято — вмикаємо наглядач, якщо він ще не працює.
        if statuses and self.watcher is not None:
            try:
                if not getattr(self.watcher, "running", False):
                    self.watcher.start()
            except Exception:  # noqa: BLE001 - наглядач необов'язковий
                pass
        if statuses:
            parts = [f"{name}: {status}" for name, status in statuses.items()]
            self._notify("MCP · " + "; ".join(parts)[:220])
        else:
            self._notify("MCP-серверів у конфігурації немає.")

    # ── малювання ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        for child in self.host.winfo_children():
            child.destroy()
        status = self.manager.status
        catalog = self.manager.tool_catalog()
        running = sum(1 for value in status.values() if value == "працює")
        self.summary.configure(
            text=f"працює {running} з {len(status)} · інструментів {len(catalog)}"
            if status else "не підключено"
        )

        if not status:
            tk.Label(self.host, text="MCP-сервери не підключені.\n"
                                     "Додай .mcp.json у теку проєкту або натисни "
                                     "«З конфігурації».",
                     bg=theme.BG, fg=theme.FG_FAINT, font=("Segoe UI", 9), justify="left",
                     anchor="w").pack(fill="x", padx=6, pady=10)
            return

        for name, state in status.items():
            self._server_card(name, state)

    def _server_card(self, name: str, state: str) -> None:
        ok = state == "працює"
        card = tk.Frame(self.host, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                        highlightbackground=theme.BORDER)
        card.pack(fill="x", padx=2, pady=(0, 4))
        card.columnconfigure(1, weight=1)

        dot = tk.Label(card, text="●", bg=theme.BG_CARD, fg=theme.SUCCESS if ok else theme.ERROR,
                       font=("Segoe UI", 9))
        dot.grid(row=0, column=0, padx=(8, 6), pady=(6, 0), sticky="n")

        tk.Label(card, text=name, bg=theme.BG_CARD, fg=theme.FG_BRIGHT,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(
            row=0, column=1, sticky="ew", pady=(6, 0))

        tk.Label(card, text=state, bg=theme.BG_CARD, fg=theme.FG_DIM, font=("Segoe UI", 8),
                 anchor="w", justify="left", wraplength=420).grid(
            row=1, column=1, sticky="ew", pady=(0, 6), padx=(0, 6))

        client = self.manager.get(name)
        if client is not None and ok:
            tools = client.tools
            names = ", ".join(str(tool.get("name") or "?") for tool in tools[:12]) or "без інструментів"
            tk.Label(card, text=f"інструменти: {names}", bg=theme.BG_CARD, fg=theme.FG_FAINT,
                     font=self.fonts.mono_small, anchor="w", justify="left",
                     wraplength=420).grid(row=2, column=1, sticky="ew", pady=(0, 6), padx=(0, 6))
