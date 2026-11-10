"""Панель «Знання» (RAG): індексація проєкту, статус, пошук, джерела.

Працює поверх наявного ``rag_engine.LocalRAG`` через :class:`RagService`.
Панель нічого не вигадує: усі числа приходять із реального SQLite-індексу
(``.mcp_rag/index.sqlite3``), а результати пошуку — це справжні фрагменти
файлів із номерами рядків.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import rag, theme, widgets


class RagPanel(tk.Frame):
    """Статус індексу, поле пошуку й список знайдених фрагментів."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        service: rag.RagService,
        *,
        on_open_path: Optional[Callable[[Path, int], None]] = None,
        on_insert_context: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.service = service
        self.on_open_path = on_open_path
        self.on_insert_context = on_insert_context
        self.on_status = on_status
        self._busy = False
        self._results: list[rag.RagHit] = []
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._after: Optional[str] = None
        self._build()
        # Таймер насоса має зніматись разом із панеллю: інакше запланований
        # ``after`` лишається в Tcl, його команда зникає — і Tk друкує
        # «invalid command name ..._pump», а закриття застосунку падає з
        # «application has been destroyed».
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh_status()

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        self.cancel()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="ЗНАННЯ ПРО ПРОЄКТ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e")

        self.status_label = tk.Label(
            self, text="Перевіряю індекс…", bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 8), justify="left", anchor="w", wraplength=210,
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=(12, 8), pady=(0, 6))

        search = tk.Frame(self, bg=theme.BG_ALT)
        search.grid(row=2, column=0, sticky="ew", padx=(10, 8), pady=(0, 4))
        search.columnconfigure(0, weight=1)

        self.entry = tk.Entry(
            search, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=("Segoe UI", 9), bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT,
        )
        self.entry.grid(row=0, column=0, sticky="ew", ipady=4)
        self.entry.bind("<Return>", lambda _e: self.run_search())
        widgets.IconButton(search, "⌕", self.run_search, bg=theme.BG_INPUT,
                           fg=theme.FG_DIM, font=("Segoe UI", 10),
                           tooltip="Шукати в індексі").grid(row=0, column=1, padx=(4, 0))

        actions = tk.Frame(self, bg=theme.BG_ALT)
        actions.grid(row=3, column=0, sticky="ew", padx=(10, 8), pady=(0, 6))
        self.index_btn = widgets.Chip(actions, "⟳ Індексувати", self.run_index,
                                       font=("Segoe UI", 8))
        self.index_btn.pack(side="left", padx=(0, 4))
        self.reindex_btn = widgets.Chip(actions, "Переіндексувати", self.run_reindex,
                                         font=("Segoe UI", 8))
        self.reindex_btn.pack(side="left")

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=4, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.host = self.scroll.inner

        self.hint = tk.Label(
            self.host,
            text=("Індекс ще не створено.\nНатисни «Індексувати», щоб агент міг "
                  "шукати по всьому проєкту."),
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 9), justify="left",
            wraplength=210,
        )
        self.hint.pack(anchor="w", padx=6, pady=8)

    # ── службове ───────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _pump(self) -> None:
        """Забрати результат фонової роботи (з головного потоку)."""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "status":
                    self._apply_status(payload)
                elif kind == "search":
                    self._apply_search(payload)
                elif kind == "index":
                    self._apply_index(str(payload))
        except queue.Empty:
            pass
        finally:
            try:
                if self.winfo_exists():
                    self._after = self.after(120, self._pump)
            except tk.TclError:
                self._after = None

    def _start(self) -> None:
        if self._after is None:
            self._pump()

    def cancel(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None

    # ── стан ───────────────────────────────────────────────────────────────
    def refresh_status(self) -> None:
        """Оновити стан індексу у фоні (відкриття панелі не має гальмувати)."""
        if self._busy:
            return
        self._start()

        def work() -> None:
            self._queue.put(("status", self.service.status()))

        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, status: object) -> None:
        if not isinstance(status, rag.RagStatus):
            return
        try:
            if status.error:
                self.status_label.configure(text=status.error, fg=theme.ERROR)
                self.count_label.configure(text="")
                return
            self.status_label.configure(
                text=f"{status.summary}\n{status.mode}" if status.mode else status.summary,
                fg=theme.SUCCESS if status.ready else theme.FG_FAINT,
            )
            self.count_label.configure(text=f"{status.chunks}")
            if status.ready:
                self.hint.pack_forget()
            elif not self._results and not self.hint.winfo_ismapped():
                self.hint.pack(anchor="w", padx=6, pady=8)
        except tk.TclError:
            pass

    # ── індексація ─────────────────────────────────────────────────────────
    def run_index(self, force: bool = False) -> None:
        if self._busy:
            self._notify("Індексація вже виконується.")
            return
        self._busy = True
        self._start()
        self.status_label.configure(text="Індексую проєкт…", fg=theme.ACCENT)
        self._notify("Індексую проєкт — це може зайняти час.")
        service = self.service

        def work() -> None:
            try:
                report = service.index(force=force)
            except Exception as exc:  # noqa: BLE001 - безпечно для потоку
                report = f"Помилка: {exc}"
            self._busy = False
            self._queue.put(("index", report))
            self._queue.put(("status", service.status()))

        threading.Thread(target=work, daemon=True).start()

    def run_reindex(self) -> None:
        self.run_index(force=True)

    def _apply_index(self, report: str) -> None:
        text = (report or "").strip()
        # Рушій віддає JSON — показуємо коротший підсумок, якщо він є.
        short = _summarise(report)
        try:
            self.status_label.configure(text=short or "Індексацію завершено.",
                                        fg=theme.SUCCESS)
        except tk.TclError:
            pass
        self._notify(short or "Індексацію завершено.")
        if text and len(text) < 400:
            self.set_results([], message=text)

    # ── пошук ──────────────────────────────────────────────────────────────
    def run_search(self) -> None:
        query = self.entry.get().strip()
        if not query:
            self.entry.focus_set()
            return
        self._start()
        self.set_results([], message="Шукаю…")
        service = self.service

        def work() -> None:
            self._queue.put(("search", service.search(query, top_k=10)))

        threading.Thread(target=work, daemon=True).start()

    def _apply_search(self, answer: object) -> None:
        if not isinstance(answer, rag.RagAnswer):
            return
        if answer.error:
            self.set_results([], message=answer.error, error=True)
            return
        message = answer.message or ("Нічого не знайдено." if not answer.hits else "")
        self.set_results(answer.hits, message=message)
        self._notify(f"Знайдено фрагментів: {len(answer.hits)}")

    def set_results(self, hits: list[rag.RagHit], *, message: str = "",
                    error: bool = False) -> None:
        self._results = list(hits)
        for child in self.host.winfo_children():
            child.destroy()
        if not hits:
            if message:
                tk.Label(self.host, text=message, bg=theme.BG_ALT,
                         fg=theme.ERROR if error else theme.FG_FAINT,
                         font=("Segoe UI", 9), justify="left",
                         wraplength=210).pack(anchor="w", padx=6, pady=8)
            return
        for hit in hits:
            self._hit_row(hit)

    def _hit_row(self, hit: rag.RagHit) -> None:
        row = tk.Frame(self.host, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                       highlightbackground=theme.BORDER)
        row.pack(fill="x", padx=2, pady=(0, 4))

        head = tk.Frame(row, bg=theme.BG_CARD)
        head.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(head, text=hit.path or "файл", bg=theme.BG_CARD, fg=theme.ACCENT,
                 font=("Segoe UI", 8), anchor="w", justify="left",
                 wraplength=180).pack(side="left")
        if hit.start_line:
            tk.Label(head, text=f":{hit.start_line}", bg=theme.BG_CARD,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8)).pack(side="left")

        preview = " ".join((hit.preview or "").split())
        if preview:
            tk.Label(row, text=preview[:180], bg=theme.BG_CARD, fg=theme.FG_DIM,
                     font=("Segoe UI", 8), justify="left", anchor="w",
                     wraplength=200).pack(fill="x", padx=8, pady=(0, 4))

        actions = tk.Frame(row, bg=theme.BG_CARD)
        actions.pack(fill="x", padx=8, pady=(0, 6))
        widgets.Chip(actions, "Відкрити", lambda h=hit: self._open(h),
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        widgets.Chip(actions, "У контекст", lambda h=hit: self._insert(h),
                     font=("Segoe UI", 8)).pack(side="left")

    def _open(self, hit: rag.RagHit) -> None:
        if not self.on_open_path or not hit.path:
            return
        try:
            base = Path(self.service.root)
            self.on_open_path(base / hit.path, hit.start_line)
        except Exception as exc:  # noqa: BLE001 - відкриття не має валити панель
            # Клік по джерелу не має зникати безслідно: користувач мусить
            # знати, чому файл не відкрився.
            self._notify(f"Не вдалось відкрити {hit.path}: {exc}")

    def _insert(self, hit: rag.RagHit) -> None:
        if not self.on_insert_context:
            return
        body = f"### {hit.location}\n{hit.preview.strip()}"
        self.on_insert_context(body)

    def apply_font(self) -> None:
        """Панель не має власних шрифтів-констант, окрім підписів."""
        return None


def _summarise(report: str) -> str:
    """Короткий підсумок індексації з JSON-звіту рушія."""
    import json

    text = (report or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text[:200]
    if not isinstance(data, dict):
        return text[:200]
    if data.get("error"):
        return str(data["error"])[:200]
    indexed = data.get("indexed_files") or data.get("documents") or data.get("indexed")
    chunks = data.get("chunks") or data.get("chunks_total")
    parts = []
    if indexed is not None:
        parts.append(f"проіндексовано файлів: {indexed}")
    if chunks is not None:
        parts.append(f"фрагментів: {chunks}")
    if data.get("skipped"):
        parts.append(f"пропущено: {data['skipped']}")
    return " · ".join(parts) if parts else str(data.get("message") or "Готово")[:200]


__all__ = ["RagPanel"]
