"""Панель NEUROMESH MEMORY: стан пам'яті, пошук, прогноз, обслуговування.

Кожен елемент керування підключений до реального backend'а
(:class:`blackchpok_ide.pcmm.service.Neuromesh`): жодних кнопок, які
«нічого не роблять». Числа беруться з SQLite, точність прогнозу — з
таблиці ``predictions``, токени — з реального tokenizer моделі (або
чесно позначаються як оцінка).

Панель не блокує інтерфейс: важкі операції (консолідація, бекап,
перенесення зі старого RAG, перерахунок векторів) виконуються у
фоновому потоці, а результат повертається через ``queue`` + ``after``.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from typing import Any, Callable, Optional

from . import theme, widgets

#: Скільки останніх спогадів показуємо у списку.
RECENT_LIMIT = 12
#: Скільки рядків історії подій.
EVENT_LIMIT = 6


class NeuromeshPanel(tk.Frame):
    """Стан і керування пам'яттю NEUROMESH."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        service_provider: Callable[[], Any],
        *,
        on_open_memory: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self._service_provider = service_provider
        self.on_open_memory = on_open_memory
        self.on_status = on_status
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._after: Optional[str] = None
        self._busy = False
        self._status: dict[str, Any] = {}
        self._hits: list[dict[str, Any]] = []
        #: Час останнього повідомлення дії: фонове оновлення не має його
        #: перетирати одразу після натискання кнопки.
        self._last_message_at = 0.0
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh()

    # ── життєвий цикл ──────────────────────────────────────────────────────
    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    @property
    def service(self):
        return self._service_provider()

    def _say(self, text: str) -> None:
        if self.on_status is not None:
            self.on_status(text)

    def _message(self, text: str) -> None:
        """Показати повідомлення дії, не даючи фоновому оновленню його стерти."""
        self._last_message_at = time.time()
        self.status_line.configure(text=str(text)[:400])
        self._say(text)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        header = tk.Frame(self, bg=theme.BG_ALT)
        header.grid(row=0, column=0, sticky="ew", padx=theme.SPACE_MD,
                    pady=(theme.SPACE_MD, 2))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="NEUROMESH Ω · ПАМ'ЯТЬ", bg=theme.BG_ALT,
                 fg=theme.FG_DIM, font=self.fonts.ui_tiny, anchor="w").grid(
            row=0, column=0, sticky="w")
        self.summary_label = tk.Label(header, text="", bg=theme.BG_ALT,
                                      fg=theme.FG_FAINT, font=("Segoe UI", 8),
                                      anchor="w", justify="left", wraplength=260)
        self.summary_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        widgets.IconButton(header, "⟳", self.refresh, bg=theme.BG_ALT,
                           fg=theme.FG_FAINT, font=("Segoe UI", 10),
                           tooltip="Оновити стан пам'яті").grid(row=0, column=1, rowspan=2)

        # Пошук
        search_row = tk.Frame(self, bg=theme.BG_ALT)
        search_row.grid(row=1, column=0, sticky="ew", padx=theme.SPACE_MD, pady=(4, 2))
        search_row.columnconfigure(0, weight=1)
        self.query_var = tk.StringVar()
        entry = tk.Entry(search_row, textvariable=self.query_var, bg=theme.BG_INPUT,
                         fg=theme.FG, insertbackground=theme.FG, relief="flat",
                         font=("Segoe UI", 9), bd=0)
        entry.grid(row=0, column=0, sticky="ew", ipady=4, padx=(0, 4))
        entry.bind("<Return>", lambda _e: self.run_search())
        widgets.IconButton(search_row, "⌕", self.run_search, bg=theme.BG_INPUT,
                           fg=theme.FG_DIM, font=("Segoe UI", 10),
                           tooltip="Шукати в пам'яті").grid(row=0, column=1)

        # Дії
        actions = tk.Frame(self, bg=theme.BG_ALT)
        actions.grid(row=2, column=0, sticky="ew", padx=theme.SPACE_MD, pady=(2, 2))
        for column, (label, command, tip) in enumerate((
            ("Прогноз", self.run_predict, "Спрогнозувати потрібний контекст"),
            ("Консолідація", self.run_consolidate, "Злити дублікати й знайти конфлікти"),
            ("Бекап", self.run_backup, "Створити резервну копію через SQLite Backup API"),
            ("Зі старого RAG", self.run_migrate, "Перенести спогади з rag_memory"),
        )):
            chip = widgets.Chip(actions, label, command=command)
            chip.grid(row=0, column=column, padx=(0, 4), pady=2, sticky="w")
            widgets.Tip(chip, tip)

        self.status_line = tk.Label(self, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="w", justify="left",
                                    wraplength=270)
        self.status_line.grid(row=3, column=0, sticky="ew", padx=theme.SPACE_MD)

        self.list_scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.list_scroll.grid(row=4, column=0, sticky="nsew", padx=theme.SPACE_MD,
                              pady=(4, theme.SPACE_SM))
        self.list_host = self.list_scroll.inner

    # ── оновлення ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        service = self.service
        if service is None:
            self.summary_label.configure(text="Пам'ять недоступна.")
            return
        if self._busy:
            return
        self._busy = True

        def work() -> None:
            try:
                self._queue.put(("status", service.status()))
            except Exception as exc:             # noqa: BLE001 - панель не має падати
                self._queue.put(("error", str(exc)))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True, name="neuromesh-status").start()
        self._schedule_pump()

    def _schedule_pump(self) -> None:
        if self._after is None:
            self._after = self.after(80, self._pump)

    def _pump(self) -> None:
        self._after = None
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "status":
                    self._apply_status(payload)          # type: ignore[arg-type]
                elif kind == "hits":
                    self._apply_hits(payload)            # type: ignore[arg-type]
                elif kind == "message":
                    self._message(str(payload))
                elif kind == "error":
                    self._message(f"✗ {payload}")
                elif kind == "reload":
                    self.refresh()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._after = self.after(120, self._pump)

    def _apply_status(self, status: dict[str, Any]) -> None:
        self._status = status or {}
        counts = self._status.get("counts") or {}
        prediction = self._status.get("prediction") or {}
        tokens = self._status.get("tokens") or {}
        vectors = self._status.get("vectors") or {}
        lines = [
            f"{counts.get('memories', 0)} спогадів · {counts.get('links', 0)} зв'язків",
            f"конфліктів: {counts.get('conflicts', 0)} · з векторами: "
            f"{counts.get('with_vectors', 0)}",
            f"точність прогнозу: {prediction.get('precision', 0)} "
            f"({prediction.get('samples', 0)} вимірів)",
            f"токени: {'точні' if tokens.get('exact') else 'оцінка'} · "
            f"вектори: {'готові' if vectors.get('ready') else 'немає'}",
        ]
        self.summary_label.configure(text="\n".join(lines))
        self._render_recent(self._status.get("recent") or [])
        events = self._status.get("events") or []
        # Повідомлення дії (пошук, бекап, консолідація) важливіше за
        # «останню подію» й має жити хоча б кілька секунд.
        if events and (time.time() - self._last_message_at) > 5.0:
            last = events[0]
            self.status_line.configure(
                text=f"остання подія: {last.get('action')} — "
                     f"{str(last.get('detail'))[:120]}")

    def _render_recent(self, memories: list[dict[str, Any]]) -> None:
        for child in self.list_host.winfo_children():
            child.destroy()
        if not memories:
            tk.Label(self.list_host, text="Спогадів ще немає.", bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w").pack(
                fill="x", padx=theme.SPACE_SM, pady=theme.SPACE_SM)
            return
        for memory in memories[:RECENT_LIMIT]:
            self._memory_card(memory)

    def _memory_card(self, memory: dict[str, Any]) -> None:
        card = tk.Frame(self.list_host, bg=theme.BG_CARD, bd=0, highlightthickness=0)
        card.pack(fill="x", pady=2, padx=1)
        title = (f"{memory.get('kind')} · {memory.get('confidence')} · "
                 f"{str(memory.get('id'))[-6:]}")
        tk.Label(card, text=title, bg=theme.BG_CARD, fg=theme.ACCENT,
                 font=("Segoe UI", 7, "bold"), anchor="w").pack(
            fill="x", padx=theme.SPACE_SM, pady=(3, 0))
        text = str(memory.get("content") or "")
        body = text if len(text) <= 220 else text[:220] + "…"
        label = tk.Label(card, text=body, bg=theme.BG_CARD, fg=theme.FG,
                         font=("Segoe UI", 8), anchor="w", justify="left",
                         wraplength=250)
        label.pack(fill="x", padx=theme.SPACE_SM, pady=(0, 3))
        if self.on_open_memory is not None:
            target_id = str(memory.get("id") or "")
            for widget in (card, label):
                widget.bind("<Button-1>", lambda _e, mid=target_id:
                            self.on_open_memory(mid))
                try:
                    widget.configure(cursor="hand2")
                except tk.TclError:
                    pass

    def _apply_hits(self, payload: dict[str, Any]) -> None:
        self._hits = payload.get("hits") or []
        policy = payload.get("policy") or ""
        for child in self.list_host.winfo_children():
            child.destroy()
        if not self._hits:
            tk.Label(self.list_host, text="Нічого не знайдено.", bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w").pack(
                fill="x", padx=theme.SPACE_SM, pady=theme.SPACE_SM)
            return
        tk.Label(self.list_host, text=f"політика: {policy}", bg=theme.BG_ALT,
                 fg=theme.FG_FAINT, font=("Segoe UI", 7), anchor="w").pack(
            fill="x", padx=theme.SPACE_SM)
        for hit in self._hits[:RECENT_LIMIT]:
            memory = dict(hit.get("memory") or {})
            memory["confidence"] = memory.get("confidence", 0)
            self._memory_card(memory)
            reason = tk.Label(self.list_host, text=f"↳ {hit.get('explanation')}",
                              bg=theme.BG_ALT, fg=theme.FG_FAINT,
                              font=("Segoe UI", 7), anchor="w", justify="left",
                              wraplength=250)
            reason.pack(fill="x", padx=theme.SPACE_SM)

    # ── дії ────────────────────────────────────────────────────────────────
    def run_search(self) -> None:
        service = self.service
        query = self.query_var.get().strip()
        if service is None or not query:
            return
        self._say(f"Пошук у пам'яті: {query}")

        def work() -> None:
            try:
                self._queue.put(("hits", service.search(query, limit=RECENT_LIMIT)))
            except Exception as exc:             # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="neuromesh-search").start()
        self._schedule_pump()

    def run_predict(self) -> None:
        service = self.service
        if service is None:
            return
        query = self.query_var.get().strip()
        self._say("Прогнозую потрібний контекст…")

        def work() -> None:
            try:
                data = service.predict(query=query, limit=8)
                reason = data.get("reason") or "сигналів мало"
                files = ", ".join(data.get("files") or []) or "—"
                self._queue.put(("hits", {
                    "policy": f"прогноз ({data.get('confidence', 0)}): {reason}",
                    "hits": data.get("memories") or [],
                }))
                self._queue.put(("message", f"Прогноз: {reason}; файли: {files}"))
            except Exception as exc:             # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="neuromesh-predict").start()
        self._schedule_pump()

    def run_consolidate(self) -> None:
        service = self.service
        if service is None:
            return
        self._say("Консолідую пам'ять…")

        def work() -> None:
            try:
                report = service.consolidate()
                self._queue.put(("message",
                                 "Консолідація: злито "
                                 f"{len(report.get('merged') or [])}, застарілих "
                                 f"{len(report.get('superseded') or [])}, конфліктів "
                                 f"{report.get('contradictions', 0)}."))
                self._queue.put(("reload", None))
            except Exception as exc:             # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="neuromesh-consolidate").start()
        self._schedule_pump()

    def run_backup(self) -> None:
        service = self.service
        if service is None:
            return
        self._say("Створюю бекап пам'яті…")

        def work() -> None:
            try:
                data = service.backup()
                self._queue.put(("message", f"Бекап: {data['path']} "
                                            f"({data['size_bytes']} байт)"))
                self._queue.put(("reload", None))
            except Exception as exc:             # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="neuromesh-backup").start()
        self._schedule_pump()

    def run_migrate(self) -> None:
        service = self.service
        if service is None:
            return
        self._say("Переношу спогади зі старого RAG…")

        def work() -> None:
            try:
                data = service.migrate_legacy_rag()
                self._queue.put(("message",
                                 f"Перенесено {data['imported']} (дублів "
                                 f"{data['skipped']}) з "
                                 f"{', '.join(data.get('sources') or []) or 'нічого'}"))
                self._queue.put(("reload", None))
            except Exception as exc:             # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="neuromesh-migrate").start()
        self._schedule_pump()


__all__ = ["NeuromeshPanel", "RECENT_LIMIT"]
