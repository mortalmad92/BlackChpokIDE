"""Панель «Черга завдань»: список задач агента й керування виконанням.

Задачі виконуються послідовно тим самим агентом. Панель нічого не знає про
модель — вона лише показує ``TaskQueue`` і просить власника вікна запустити
наступну задачу, коли попередня завершилась.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import queue_engine, theme, widgets
from .queue_engine import CANCELLED, DONE, FAILED, PENDING, RUNNING, STATUS_MARKS


class QueuePanel(tk.Frame):
    """Список задач із кнопками керування."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        queue: queue_engine.TaskQueue,
        *,
        on_run_next: Optional[Callable[[], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_show_task: Optional[Callable[[queue_engine.QueueTask], None]] = None,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.queue = queue
        self.on_run_next = on_run_next
        self.on_status = on_status
        self.on_show_task = on_show_task
        self.on_changed = on_changed
        #: Звідки брати активний чат для прив'язки задач (ставиться вікном).
        self.chat_id_provider: Optional[Callable[[], str]] = None
        self._rows: dict[str, tk.Frame] = {}
        self._build()
        self.queue.on_change = self.refresh
        self.refresh()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="ЧЕРГА ЗАВДАНЬ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e", padx=(6, 0))

        # Поле додавання
        add_row = tk.Frame(self, bg=theme.BG_ALT)
        add_row.grid(row=1, column=0, sticky="ew", padx=(10, 8), pady=(2, 6))
        add_row.columnconfigure(0, weight=1)

        self.entry = tk.Entry(add_row, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
                              relief="flat", font=self.fonts.ui_small, bd=0, highlightthickness=1,
                              highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT)
        self.entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self.entry.bind("<Return>", lambda _e: self._add())
        self.entry.bind("<Shift-Return>", lambda _e: self._add())

        widgets.IconButton(add_row, "＋", self._add, bg=theme.BG_INPUT, fg=theme.FG_DIM,
                           font=("Segoe UI", 10), tooltip="Додати задачу").grid(row=0, column=1, padx=(4, 0))

        # Список
        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 6))
        self.list_host = self.scroll.inner
        self.empty = tk.Label(self.list_host, text="Черга порожня.\nДодай задачу — агент виконає її після поточної.",
                              bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 9),
                              justify="left")
        self.empty.pack(anchor="w", padx=6, pady=10)

        # Керування
        footer = tk.Frame(self, bg=theme.BG_ALT)
        footer.grid(row=3, column=0, sticky="ew", padx=(8, 4), pady=(0, 10))
        self.pause_btn = widgets.Chip(footer, "⏸ Пауза", self._toggle_pause,
                                      font=("Segoe UI", 9))
        self.pause_btn.pack(side="left", padx=(0, 4))
        self.run_btn = widgets.Chip(footer, "▶ Запустити", self._run_next, font=("Segoe UI", 9))
        self.run_btn.pack(side="left", padx=(0, 4))
        widgets.Chip(footer, "Очистити", self._clear_done, font=("Segoe UI", 9)).pack(side="left")

    # ── дії ────────────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _add(self) -> None:
        text = self.entry.get().strip()
        if not text:
            self.entry.focus_set()
            return
        self.entry.delete(0, "end")
        tasks = queue_engine.split_batch(text)
        added = 0
        chat_id = self._chat_id()
        for item in tasks:
            if self.queue.add(item, chat_id=chat_id):
                added += 1
        self._notify(f"Додано в чергу: {added}")
        self.refresh()
        # Бейдж у композері має оновитись одразу, інакше показує старе число.
        if self.on_changed:
            try:
                self.on_changed()
            except Exception as exc:  # noqa: BLE001 - інтерфейс не має ламати чергу
                self._notify(f"Бейдж черги не оновився: {exc}")
        self._maybe_autorun()

    def _chat_id(self) -> str:
        """Активний чат — до нього прив'язується нова задача."""
        provider = getattr(self, "chat_id_provider", None)
        if provider is None:
            return ""
        try:
            return str(provider() or "")
        except Exception:  # noqa: BLE001 - прив'язка не має ламати чергу
            return ""

    def add_text(self, text: str, *, skill: str = "", chat_id: str = "") -> int:
        """Додати задачу ззовні (з чату або скіла)."""
        added = 0
        target = str(chat_id or self._chat_id())
        for item in queue_engine.split_batch(text):
            if self.queue.add(item, skill=skill, chat_id=target):
                added += 1
        self.refresh()
        self._maybe_autorun()
        return added

    def _maybe_autorun(self) -> None:
        if self.queue.paused or self.queue.running_id:
            return
        if self.on_run_next:
            self.on_run_next()

    def _run_next(self) -> None:
        if self.queue.paused:
            self.queue.set_paused(False)
            self.refresh()
        if self.on_run_next:
            self.on_run_next()
        else:
            self._notify("Запуск черги не підключений.")

    def _toggle_pause(self) -> None:
        paused = self.queue.toggle_paused()
        self._notify("Чергу поставлено на паузу." if paused else "Чергу продовжено.")
        self.refresh()
        if not paused:
            self._maybe_autorun()

    def _clear_done(self) -> None:
        removed = self.queue.clear_finished()
        self._notify(f"Прибрано завершених задач: {removed}")
        self.refresh()

    def _task_menu(self, task: queue_engine.QueueTask, event) -> None:
        items: list[tuple[str, Optional[Callable[[], None]]]] = []
        if task.status in {DONE, FAILED, CANCELLED}:
            items.append(("Повторити", lambda: (self.queue.retry(task.id), self._maybe_autorun())))
        if task.status == PENDING:
            items.append(("Скасувати", lambda: self.queue.cancel(task.id)))
            items.append(("Вгору", lambda: self.queue.move(task.id, -1)))
            items.append(("Вниз", lambda: self.queue.move(task.id, 1)))
        items.append(("Відкрити результат", lambda: self.on_show_task and self.on_show_task(task)))
        items.append(("", None))
        items.append(("Видалити", lambda: self.queue.remove(task.id)))
        widgets.context_menu(self, items, event)

    # ── малювання ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        for row in self._rows.values():
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()

        counts = self.queue.counts()
        self.count_label.configure(
            text=f"{len(self.queue.tasks)} задач · готово {counts[DONE]} · чекає {counts[PENDING]}")
        self.pause_btn.configure(text="▶ Продовжити" if self.queue.paused else "⏸ Пауза")
        # Порожня підказка має зникати, щойно є задачі. Раніше умова
        # перевіряла ``winfo_ismapped()``: у прихованому вікні (і під час
        # роботи, коли панель перемальовується) воно завжди 0, тож
        # ``pack_forget`` не викликався — і підказка «Черга порожня»
        # лишалась зверху списку з 24 задач. Перевіряємо стан пакування,
        # а не видимість на екрані.
        try:
            packed = bool(self.empty.winfo_manager())
        except tk.TclError:
            packed = False
        if self.queue.tasks and packed:
            self.empty.pack_forget()
        elif not self.queue.tasks and not packed:
            self.empty.pack(anchor="w", padx=6, pady=10)

        for index, task in enumerate(self.queue.tasks):
            self._rows[task.id] = self._row(task, index)

    def _row(self, task: queue_engine.QueueTask, index: int) -> tk.Frame:
        colour = {
            PENDING: theme.FG,
            RUNNING: theme.ACCENT,
            DONE: theme.SUCCESS,
            FAILED: theme.ERROR,
            CANCELLED: theme.FG_FAINT,
        }.get(task.status, theme.FG)

        row = tk.Frame(self.list_host, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                       highlightbackground=theme.BORDER)
        row.pack(fill="x", padx=2, pady=(0, 4))
        row.columnconfigure(1, weight=1)

        mark = tk.Label(row, text=STATUS_MARKS.get(task.status, "•"), bg=theme.BG_CARD, fg=colour,
                        font=("Segoe UI", 9))
        mark.grid(row=0, column=0, padx=(8, 6), pady=(6, 0), sticky="n")

        # Текст кроку — САМЕ те, що робити. Номер показуємо окремим
        # маленьким підписом: раніше «Крок 1 з 12:» стояв у тексті задачі,
        # і всі дванадцять рядків починалися однаково, тож сенс кроку
        # губився («Модель має сама розбивати чергу на кроки а не писати
        # Крок 1 з 12»).
        text = task.text if len(task.text) <= 160 else task.text[:157] + "…"
        head = f"{index + 1}. " if index >= 0 else ""
        label = tk.Label(row, text=head + text, bg=theme.BG_CARD, fg=colour,
                         font=("Segoe UI", 9), justify="left", anchor="w",
                         wraplength=240)
        label.grid(row=0, column=1, sticky="ew", pady=(6, 0), padx=(0, 6))

        meta_bits = [task.status]
        if task.skill:
            meta_bits.append(f"скіл: {task.skill}")
        if task.elapsed_text:
            meta_bits.append(task.elapsed_text)
        meta = tk.Label(row, text=" · ".join(meta_bits), bg=theme.BG_CARD, fg=theme.FG_FAINT,
                        font=("Segoe UI", 8), anchor="w")
        meta.grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(1, 6))

        for widget in (row, mark, label, meta):
            widget.bind("<Button-3>", lambda e, t=task: self._task_menu(t, e))
        label.bind("<Double-1>", lambda _e, t=task: self.on_show_task and self.on_show_task(t))
        return row

    # ── інтеграція ─────────────────────────────────────────────────────────
    def select_task(self, task: queue_engine.QueueTask) -> None:
        """Прокрутити до задачі й підсвітити її."""
        row = self._rows.get(task.id)
        if row is not None:
            try:
                row.configure(highlightbackground=theme.ACCENT_SOFT)
            except tk.TclError:
                pass
