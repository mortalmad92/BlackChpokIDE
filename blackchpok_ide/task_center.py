"""Центр завдань: нижня панель керування чергою локального агента.

Це не «список задач», а робочий інструмент керування роботою:

    ┌───────────────────────────────────────────────────────────────────────┐
    │ ЧЕРГА ЗАВДАНЬ ЛОКАЛЬНОГО АГЕНТА          4/9 · 44%  ● 2 у роботі      │
    │ ████████████░░░░░░░░░░░░░░  аналізую структуру проєкту                │
    ├──────────────────────────────┬────────────────────────────────────────┤
    │ 01 ✓ Аналіз структури проєкту│  ЩО ПОТРІБНО ЗРОБИТИ                   │
    │ 02 ◐ Створити backend API    │  Створити backend API                  │
    │ 03 ○ Створення frontend      │  Створити серверні маршрути…           │
    │ 04 ○ Інтеграція компонентів  │                                        │
    │                              │  ЩО ЗРОБИЛА МОДЕЛЬ                     │
    │                              │  12:01 write_file(app.py)              │
    │                              │  12:01 ✓ файл створено                 │
    ├──────────────────────────────┴────────────────────────────────────────┤
    │ ⏸ Пауза  ▶ Продовжити  ■ Зупинити  ↻ Повторити  ⌫ Очистити  ☰ Журнал │
    └───────────────────────────────────────────────────────────────────────┘

Кожне число й кожен статус беруться зі справжнього стану
:class:`queue_engine.TaskQueue`; кнопки викликають справжні дії виконавця.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import pulse, queue_engine, task_executor, theme, widgets

#: Кольори статусів: читаються одним поглядом.
STATUS_COLOURS = {
    queue_engine.PENDING: theme.FG_DIM,
    queue_engine.ANALYZING: theme.ACCENT,
    queue_engine.RUNNING: theme.ACCENT,
    queue_engine.VERIFYING: theme.PURPLE,
    queue_engine.DONE: theme.SUCCESS,
    queue_engine.FAILED: theme.ERROR,
    queue_engine.PAUSED: theme.WARN,
    queue_engine.CANCELLED: theme.FG_FAINT,
}

#: Людські підписи статусу у верхньому регістрі (як у макеті).
STATUS_BADGES = {
    queue_engine.PENDING: "ОЧІКУЄ",
    queue_engine.ANALYZING: "АНАЛІЗ",
    queue_engine.RUNNING: "ВИКОНУЄТЬСЯ",
    queue_engine.VERIFYING: "ПЕРЕВІРКА",
    queue_engine.DONE: "ЗАВЕРШЕНО",
    queue_engine.FAILED: "ПОМИЛКА",
    queue_engine.PAUSED: "ПРИЗУПИНЕНО",
    queue_engine.CANCELLED: "СКАСОВАНО",
}


class TaskCenter(tk.Frame):
    """Панель керування чергою: шапка, список кроків, деталі, дії."""

    #: Скільки рядків журналу показуємо в деталях.
    MAX_LOG_ROWS = 40

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        queue: queue_engine.TaskQueue,
        *,
        executor: Optional[task_executor.QueueExecutor] = None,
        on_pause: Optional[Callable[[], None]] = None,
        on_resume: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_retry: Optional[Callable[[str], None]] = None,
        on_clear: Optional[Callable[[], None]] = None,
        on_run_next: Optional[Callable[[], None]] = None,
        on_add_task: Optional[Callable[[str], None]] = None,
        on_open_file: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        chat_id_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.queue = queue
        self.executor = executor
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_stop = on_stop
        self.on_retry = on_retry
        self.on_clear = on_clear
        self.on_run_next = on_run_next
        self.on_add_task = on_add_task
        self.on_open_file = on_open_file
        self.on_status = on_status
        self.chat_id_provider = chat_id_provider
        #: Обраний крок (для панелі деталей).
        self.selected_id: str = ""
        self._rows: dict[str, tk.Frame] = {}
        self._dots: dict[str, pulse.PulseDot] = {}
        self._signature: tuple = ()
        self._last_selected: str = ""
        self._detail_signature: tuple = ()
        self._build()
        self.refresh()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── шапка: назва, лічильники, смуга прогресу
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)

        title_row = tk.Frame(head, bg=theme.BG_ALT)
        title_row.grid(row=0, column=0, columnspan=2, sticky="ew",
                       padx=(theme.SPACE_LG, theme.SPACE_MD),
                       pady=(theme.SPACE_MD, 2))
        title_row.columnconfigure(1, weight=1)

        self.title_label = tk.Label(
            title_row, text="ЧЕРГА ЗАВДАНЬ ЛОКАЛЬНОГО АГЕНТА",
            bg=theme.BG_ALT, fg=theme.FG_DIM, font=("Segoe UI", 9, "bold"),
            anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.stage_label = tk.Label(title_row, text="", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=("Segoe UI", 8),
                                    anchor="e")
        self.stage_label.grid(row=0, column=1, sticky="e", padx=(theme.SPACE_MD, 0))

        counters = tk.Frame(head, bg=theme.BG_ALT)
        counters.grid(row=1, column=0, columnspan=2, sticky="ew",
                      padx=(theme.SPACE_LG, theme.SPACE_MD), pady=(0, theme.SPACE_SM))

        self.count_labels: dict[str, tk.Label] = {}
        for key, caption in (("total", "усього"), ("done", "завершено"),
                             ("pending", "у черзі"), ("errors", "помилки")):
            cell = tk.Frame(counters, bg=theme.BG_ALT)
            cell.pack(side="left", padx=(0, theme.SPACE_XL))
            value = tk.Label(cell, text="0", bg=theme.BG_ALT, fg=theme.FG_BRIGHT,
                             font=("Segoe UI", 12, "bold"), anchor="w")
            value.pack(side="left")
            tk.Label(cell, text=caption, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w").pack(
                side="left", padx=(theme.SPACE_XS, 0), pady=(4, 0))
            self.count_labels[key] = value

        # Кнопка «додати крок» у шапці: чергу наповнює й людина.
        self.add_btn = widgets.HoverLabel(
            counters, text="＋ крок", command=self._add_dialog, bg=theme.BG_ALT,
            fg=theme.FG_DIM, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT,
            font=("Segoe UI", 8), padx=theme.SPACE_MD, pady=2, anchor="center")
        self.add_btn.pack(side="right")
        widgets.Tip(self.add_btn, "Додати власний крок у чергу")

        # Смуга прогресу малюється вручну: ttk.Progressbar на темному тлі
        # дає світлу рамку, яка вибивається з дизайну.
        self.progress = tk.Canvas(head, height=4, bg=theme.BG_ALT, bd=0,
                                  highlightthickness=0, takefocus=0)
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew",
                           padx=(theme.SPACE_LG, theme.SPACE_MD),
                           pady=(0, theme.SPACE_SM))
        self._progress_bar = self.progress.create_rectangle(
            0, 0, 0, 4, outline="", fill=theme.ACCENT)
        self.progress.bind("<Configure>", lambda _e: self._paint_progress())

        widgets.Divider(self, colour=theme.BORDER, autopack=False).grid(
            row=0, column=0, sticky="sew")

        # ── тіло: список кроків │ межа │ деталі
        # Вага — ЛИШЕ в списку й деталях. Роздільник стоїть у власній
        # колонці без ваги: раніше вагу 2 отримувала саме колонка межі, і
        # панель деталей з'їжджала в куток шириною в кілька символів.
        body = tk.Frame(self, bg=theme.BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, minsize=240)
        body.columnconfigure(1, weight=0)
        body.columnconfigure(2, weight=2, minsize=220)
        body.rowconfigure(0, weight=1)

        self.list_view = widgets.ScrollFrame(body, bg=theme.BG)
        self.list_view.grid(row=0, column=0, sticky="nsew")
        self.list_host = self.list_view.inner

        self.empty_label = tk.Label(
            self.list_host,
            text=("Черга порожня.\n\n"
                  "Напиши велике завдання в чаті — локальна модель сама\n"
                  "розкладе його на кроки й почне виконувати."),
            bg=theme.BG, fg=theme.FG_FAINT, font=("Segoe UI", 9),
            justify="left", anchor="w")
        self.empty_label.pack(anchor="w", padx=theme.SPACE_LG, pady=theme.SPACE_XL)

        # Вертикальна межа між списком і деталями — окремою колонкою,
        # щоб вона не залежала від висоти вмісту.
        widgets.Divider(body, colour=theme.BORDER, orient="vertical",
                        autopack=False).grid(row=0, column=1, sticky="ns")

        self.detail_host = tk.Frame(body, bg=theme.BG_ALT)
        self.detail_host.grid(row=0, column=2, sticky="nsew")
        self.detail_host.columnconfigure(0, weight=1)
        self.detail_host.rowconfigure(1, weight=1)
        self._build_details()

        widgets.Divider(self, colour=theme.BORDER, autopack=False).grid(
            row=2, column=0, sticky="ew")

        # ── кнопки керування
        foot = tk.Frame(self, bg=theme.BG_ALT)
        foot.grid(row=3, column=0, sticky="ew")
        self.footer = foot

        self.pause_btn = widgets.Chip(foot, "⏸ Пауза", self._pause, font=("Segoe UI", 9))
        self.pause_btn.pack(side="left", padx=(theme.SPACE_LG, theme.SPACE_SM),
                            pady=theme.SPACE_SM)
        self.resume_btn = widgets.Chip(foot, "▶ Продовжити", self._resume,
                                       font=("Segoe UI", 9))
        self.resume_btn.pack(side="left", padx=(0, theme.SPACE_SM),
                             pady=theme.SPACE_SM)
        self.stop_btn = widgets.Chip(foot, "■ Зупинити", self._stop, font=("Segoe UI", 9))
        self.stop_btn.pack(side="left", padx=(0, theme.SPACE_SM), pady=theme.SPACE_SM)
        self.retry_btn = widgets.Chip(foot, "↻ Повторити", self._retry_selected,
                                      font=("Segoe UI", 9))
        self.retry_btn.pack(side="left", padx=(0, theme.SPACE_SM), pady=theme.SPACE_SM)
        self.clear_btn = widgets.Chip(foot, "⌫ Очистити", self._clear, font=("Segoe UI", 9))
        self.clear_btn.pack(side="left", padx=(0, theme.SPACE_SM), pady=theme.SPACE_SM)
        self.log_btn = widgets.Chip(foot, "☰ Журнал", self._open_log, font=("Segoe UI", 9))
        self.log_btn.pack(side="left", padx=(0, theme.SPACE_SM), pady=theme.SPACE_SM)

        self.hint_label = tk.Label(
            foot, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 8), anchor="e")
        self.hint_label.pack(side="right", padx=(theme.SPACE_SM, theme.SPACE_LG))

    def _build_details(self) -> None:
        """Права колонка: що мало бути зроблено й що зробила модель."""
        head = tk.Frame(self.detail_host, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=theme.SPACE_MD,
                  pady=(theme.SPACE_MD, theme.SPACE_SM))
        head.columnconfigure(0, weight=1)

        self.detail_title = tk.Label(head, text="ВИБЕРИ КРОК", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=("Segoe UI", 8, "bold"),
                                     anchor="w")
        self.detail_title.grid(row=0, column=0, sticky="w")

        self.detail_view = widgets.ScrollFrame(self.detail_host, bg=theme.BG_ALT)
        self.detail_view.grid(row=1, column=0, sticky="nsew", padx=(theme.SPACE_SM, 0))
        self.detail_body = self.detail_view.inner

    # ── дрібні дії ─────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _chat_id(self) -> str:
        if self.chat_id_provider is None:
            return ""
        try:
            return str(self.chat_id_provider() or "")
        except Exception:  # noqa: BLE001
            return ""

    def _selected(self) -> Optional[queue_engine.QueueTask]:
        if not self.selected_id:
            return None
        return self.queue.get(self.selected_id)

    def select(self, task_id: str) -> None:
        self.selected_id = task_id
        task = self.queue.get(task_id)
        if task is not None:
            task.add_history("view", "крок відкрито в панелі")
        self._detail_signature = ()
        self.refresh()

    # ── кнопки ─────────────────────────────────────────────────────────────
    def _pause(self) -> None:
        if self.on_pause is not None:
            self.on_pause()
            return
        self.queue.set_paused(True)
        self._notify("Чергу поставлено на паузу.")

    def _resume(self) -> None:
        if self.on_resume is not None:
            self.on_resume()
            return
        self.queue.set_paused(False)
        self._notify("Чергу продовжено.")

    def _stop(self) -> None:
        if self.on_stop is not None:
            self.on_stop()
            return
        active = next((task for task in self.queue.tasks if task.active), None)
        if active is not None:
            self.queue.mark_paused(active.id, "зупинено користувачем")
        self.queue.set_paused(True)
        self._notify("Виконання зупинено.")

    def _retry_selected(self) -> None:
        task = self._selected()
        if task is None:
            self._notify("Спершу вибери крок у списку.")
            return
        if self.on_retry is not None:
            self.on_retry(task.id)
        elif self.queue.retry(task.id):
            self._notify(f"Крок {self._number(task)} повернуто в чергу.")
            self.refresh()

    def _clear(self) -> None:
        if self.on_clear is not None:
            self.on_clear()
            return
        removed = self.queue.clear_finished()
        self._notify(f"Прибрано завершених кроків: {removed}")
        self.refresh()

    def _open_log(self) -> None:
        """Показати журнал виконання обраного кроку (або останнього)."""
        task = self._selected() or self._latest()
        if task is None:
            self._notify("Журнал порожній — черга не має кроків.")
            return
        self.select(task.id)
        self._notify(f"Журнал кроку {self._number(task)} — у правій колонці.")

    def _add_dialog(self) -> None:
        """Додати крок у чергу вручну (простий рядок вводу)."""
        window = tk.Toplevel(self)
        window.title("Новий крок черги")
        window.configure(bg=theme.BG)
        window.transient(self.winfo_toplevel())
        window.columnconfigure(0, weight=1)

        tk.Label(window, text="Що зробити?", bg=theme.BG, fg=theme.FG_DIM,
                 font=("Segoe UI", 9), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=theme.SPACE_MD,
            pady=(theme.SPACE_MD, 2))
        entry = tk.Entry(window, bg=theme.BG_INPUT, fg=theme.FG,
                         insertbackground=theme.FG_BRIGHT, relief="flat",
                         font=self.fonts.ui_small, width=46,
                         highlightthickness=1, highlightbackground=theme.BORDER,
                         highlightcolor=theme.ACCENT_SOFT)
        entry.grid(row=1, column=0, sticky="ew", padx=theme.SPACE_MD, ipady=5)
        entry.focus_set()

        def submit(_event=None) -> None:
            text = entry.get().strip()
            if not text:
                return
            if self.on_add_task is not None:
                self.on_add_task(text)
            else:
                self.queue.add(text, chat_id=self._chat_id())
            window.destroy()
            self.refresh()

        entry.bind("<Return>", submit)
        window.bind("<Escape>", lambda _e: window.destroy())

        row = tk.Frame(window, bg=theme.BG)
        row.grid(row=2, column=0, sticky="ew", padx=theme.SPACE_MD,
                 pady=theme.SPACE_MD)
        widgets.Chip(row, "Додати", submit).pack(side="right")
        widgets.Chip(row, "Скасувати", window.destroy).pack(
            side="right", padx=(0, theme.SPACE_SM))
        try:
            widgets.place_window(window, anchor=self, width=380, height=0)
        except Exception:  # noqa: BLE001 - позиція не критична
            pass

    @staticmethod
    def _number(task: queue_engine.QueueTask) -> str:
        return f"{task.number:02d}" if task.number else "—"

    def _latest(self) -> Optional[queue_engine.QueueTask]:
        tasks = self.queue.tasks
        return tasks[-1] if tasks else None

    # ── малювання ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Оновити панель зі справжнього стану черги."""
        progress = self.queue.progress()
        for key in ("total", "done", "pending", "errors"):
            label = self.count_labels.get(key)
            if label is not None:
                try:
                    value = int(progress.get(key, 0))
                    label.configure(text=str(value),
                                    fg=(theme.ERROR if key == "errors" and value
                                        else theme.SUCCESS if key == "done" and value
                                        else theme.FG_BRIGHT))
                except tk.TclError:
                    return
        self._paint_stage(progress)
        self._paint_progress()
        self._paint_buttons(progress)
        self._paint_rows()
        self._paint_details()

    def _paint_stage(self, progress: dict[str, int]) -> None:
        """Короткий підпис того, що зараз відбувається."""
        active = next((t for t in self.queue.tasks if t.active), None)
        if active is not None:
            text = task_executor.describe_status(active)
            head = f"{self._number(active)} · {text}"
            colour = theme.ACCENT
        elif progress["paused"]:
            head, colour = "виконання призупинено", theme.WARN
        elif progress["errors"]:
            head = f"є помилки: {progress['errors']}"
            colour = theme.ERROR
        elif progress["total"] and progress["done"] == progress["total"]:
            head, colour = "усі кроки завершено", theme.SUCCESS
        elif self.queue.paused:
            head, colour = "черга на паузі", theme.WARN
        elif progress["pending"]:
            waiting = self.queue.waiting_on_dependencies(chat_id=self._chat_id())
            head = (f"чекають на попередні кроки: {len(waiting)}"
                    if waiting and len(waiting) == progress["pending"]
                    else "готово до запуску")
            colour = theme.FG_FAINT
        else:
            head, colour = "очікую завдання", theme.FG_FAINT
        try:
            total = progress["total"]
            done = progress["done"]
            percent = int(round(100 * done / total)) if total else 0
            self.stage_label.configure(
                text=f"{head}  ·  {done}/{total} ({percent}%)", fg=colour)
        except tk.TclError:
            pass

    def _paint_progress(self) -> None:
        try:
            width = max(1, self.progress.winfo_width() - 2)
            total = len(self.queue.tasks)
            done = self.queue.counts()[queue_engine.DONE]
            fraction = (done / total) if total else 0.0
            errors = self.queue.counts()[queue_engine.FAILED]
            colour = theme.ERROR if errors else theme.ACCENT
            self.progress.coords(self._progress_bar, 0, 0,
                                 int(width * fraction), 4)
            self.progress.itemconfigure(self._progress_bar, fill=colour)
        except tk.TclError:
            return

    def _paint_buttons(self, progress: dict[str, int]) -> None:
        active = any(t.active for t in self.queue.tasks)
        try:
            self.pause_btn.configure(text="▶ Продовжити" if self.queue.paused else "⏸ Пауза")
            # «Продовжити» має сенс, коли є пауза або призупинені кроки.
            resumable = self.queue.paused or progress["paused"] > 0
            self.resume_btn.configure(
                fg=theme.FG if resumable else theme.FG_FAINT)
            self.stop_btn.configure(fg=theme.FG if active else theme.FG_FAINT)
            has_failed = progress["errors"] > 0
            self.retry_btn.configure(fg=theme.FG if has_failed else theme.FG_FAINT)
            self.clear_btn.configure(
                fg=theme.FG if progress["done"] or progress["errors"] else theme.FG_FAINT)
        except tk.TclError:
            return
        hint = ""
        if self.executor is not None and self.executor.stopped:
            hint = "виконання зупинено"
        elif self.queue.paused:
            hint = "черга на паузі"
        elif not progress["total"]:
            hint = "кроків немає"
        try:
            self.hint_label.configure(text=hint)
        except tk.TclError:
            pass

    def _paint_rows(self) -> None:
        """Перемалювати список кроків (лише коли вміст справді змінився)."""
        signature = tuple(
            (task.id, task.status, task.number, task.current_step,
             task.title, len(task.history))
            for task in self.queue.tasks
        )
        selected = self.selected_id
        if signature == self._signature and selected == self._last_selected:
            return
        self._signature = signature
        self._last_selected = selected

        for row in self._rows.values():
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()
        self._dots.clear()

        tasks = self.queue.tasks
        try:
            if tasks:
                if self.empty_label.winfo_manager():
                    self.empty_label.pack_forget()
            elif not self.empty_label.winfo_manager():
                self.empty_label.pack(anchor="w", padx=theme.SPACE_LG,
                                      pady=theme.SPACE_XL)
        except tk.TclError:
            pass

        for task in tasks:
            self._rows[task.id] = self._row(task)

    def _row(self, task: queue_engine.QueueTask) -> tk.Frame:
        status = task.status
        colour = STATUS_COLOURS.get(status, theme.FG)
        selected = task.id == self.selected_id
        bg = theme.BG_ACTIVE if selected else theme.BG_CARD

        row = tk.Frame(self.list_host, bg=bg, cursor="hand2",
                       highlightthickness=1,
                       highlightbackground=(theme.ACCENT_SOFT if selected
                                            else theme.BORDER))
        row.pack(fill="x", padx=(theme.SPACE_MD, theme.SPACE_SM),
                 pady=(0, theme.SPACE_XS))
        row.columnconfigure(2, weight=1)

        # Номер кроку — обов'язковий, як у макеті («01», «02»).
        number = tk.Label(row, text=self._number(task), bg=bg, fg=theme.FG_FAINT,
                          font=("Consolas", 9), width=3, anchor="e")
        number.grid(row=0, column=0, sticky="n", padx=(theme.SPACE_SM, theme.SPACE_SM),
                    pady=(theme.SPACE_SM, 0))

        if status in (queue_engine.RUNNING, queue_engine.ANALYZING,
                      queue_engine.VERIFYING):
            dot = pulse.PulseDot(row, bg=bg, size=14, state=pulse.PulseDot.RUNNING)
            dot.set_colour(colour)
        else:
            dot = pulse.PulseDot(
                row, bg=bg, size=14,
                state=(pulse.PulseDot.DONE if status == queue_engine.DONE
                       else pulse.PulseDot.FAILED if status == queue_engine.FAILED
                       else pulse.PulseDot.IDLE))
        dot.grid(row=0, column=1, sticky="n", padx=(0, theme.SPACE_SM),
                 pady=(theme.SPACE_SM + 1, 0))
        self._dots[task.id] = dot

        title_colour = (theme.FG_BRIGHT if status in (queue_engine.RUNNING,
                                                      queue_engine.ANALYZING,
                                                      queue_engine.VERIFYING)
                        else theme.FG_FAINT if status in (queue_engine.DONE,
                                                          queue_engine.CANCELLED)
                        else theme.FG)
        wrap = max(160, min(520, self.list_host.winfo_width() - 120 or 320))
        title = tk.Label(row, text=task.title or task.text[:80], bg=bg,
                         fg=title_colour, font=("Segoe UI", 9),
                         justify="left", anchor="w", wraplength=wrap)
        title.grid(row=0, column=2, sticky="ew", pady=(theme.SPACE_SM, 0),
                   padx=(0, theme.SPACE_SM))

        # Статус — коротким бейджем праворуч.
        badge = tk.Label(row, text=STATUS_BADGES.get(status, status.upper()),
                         bg=bg, fg=colour, font=("Segoe UI", 7, "bold"), anchor="e")
        badge.grid(row=0, column=3, sticky="ne",
                   padx=(0, theme.SPACE_SM), pady=(theme.SPACE_SM + 2, 0))

        # Другий рядок: поточна операція або причина помилки.
        subtitle = task_executor.describe_status(task)
        if subtitle and subtitle != task.status_label:
            sub = tk.Label(row, text=subtitle, bg=bg,
                           fg=(theme.ERROR if status == queue_engine.FAILED
                               else theme.FG_FAINT),
                           font=("Segoe UI", 8), justify="left", anchor="w",
                           wraplength=wrap)
            sub.grid(row=1, column=2, columnspan=2, sticky="ew",
                     padx=(0, theme.SPACE_SM), pady=(1, theme.SPACE_SM))
        else:
            spacer = tk.Frame(row, bg=bg, height=4)
            spacer.grid(row=1, column=2, sticky="ew")

        for widget in (row, number, title, badge):
            widget.bind("<Button-1>", lambda _e, tid=task.id: self.select(tid))
            widget.bind("<Button-3>", lambda e, t=task: self._task_menu(t, e))
        title.bind("<Double-1>", lambda _e, t=task: self._open_files(t))
        return row

    def _task_menu(self, task: queue_engine.QueueTask, event) -> None:
        items: list[tuple[str, Optional[Callable[[], None]]]] = []
        items.append(("Повторити крок", lambda: self._retry_id(task.id)))
        if task.status == queue_engine.PENDING:
            items.append(("Скасувати", lambda: (self.queue.cancel(task.id), self.refresh())))
            items.append(("Вище", lambda: (self.queue.move(task.id, -1),
                                           self.queue.renumber(chat_id=self._chat_id()),
                                           self.refresh())))
            items.append(("Нижче", lambda: (self.queue.move(task.id, 1),
                                            self.queue.renumber(chat_id=self._chat_id()),
                                            self.refresh())))
        items.append(("", None))
        items.append(("Показати змінені файли", lambda: self._open_files(task)))
        items.append(("Прибрати крок", lambda: (self.queue.remove(task.id), self.refresh())))
        widgets.context_menu(self, items, event)

    def _retry_id(self, task_id: str) -> None:
        if self.on_retry is not None:
            self.on_retry(task_id)
            return
        if self.queue.retry(task_id):
            self.refresh()

    def _open_files(self, task: queue_engine.QueueTask) -> None:
        """Відкрити файл, який змінив крок (перший зі списку)."""
        if not task.files_changed:
            self._notify("Цей крок не змінював файлів.")
            return
        name = task.files_changed[0]
        if self.on_open_file is not None:
            self.on_open_file(name)
        else:
            self._notify(f"Змінений файл: {name}")

    # ── деталі ─────────────────────────────────────────────────────────────
    def _paint_details(self) -> None:
        task = self._selected()
        signature = (
            task.id if task is not None else "",
            task.status if task is not None else "",
            len(task.history) if task is not None else 0,
        )
        if signature == self._detail_signature:
            return
        self._detail_signature = signature

        for child in self.detail_body.winfo_children():
            try:
                child.destroy()
            except tk.TclError:
                pass
        if task is None:
            try:
                self.detail_title.configure(text="ВИБЕРИ КРОК")
            except tk.TclError:
                pass
            tk.Label(self.detail_body,
                     text="Клікни крок ліворуч, щоб побачити, що саме\n"
                          "мало бути зроблено і що зробила модель.",
                     bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                     justify="left", anchor="w").pack(
                anchor="w", padx=theme.SPACE_SM, pady=theme.SPACE_SM)
            return

        try:
            self.detail_title.configure(text=f"КРОК {self._number(task)}")
        except tk.TclError:
            return
        wrap = max(160, self.detail_body.winfo_width() - 24 or 240)

        def section(text: str) -> None:
            tk.Label(self.detail_body, text=text, bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 7, "bold"),
                     anchor="w").pack(fill="x", padx=theme.SPACE_SM,
                                      pady=(theme.SPACE_SM, 1))

        def paragraph(text: str, *, colour: str = theme.FG_DIM) -> None:
            if not text:
                return
            tk.Label(self.detail_body, text=text, bg=theme.BG_ALT, fg=colour,
                     font=("Segoe UI", 8), justify="left", anchor="w",
                     wraplength=wrap).pack(fill="x", padx=theme.SPACE_SM, pady=(0, 2))

        section("ЩО ПОТРІБНО БУЛО ЗРОБИТИ")
        paragraph(task.title or task.text, colour=theme.FG)
        if task.detail:
            paragraph(task.detail)
        if task.goal:
            section("ЗАГАЛЬНА МЕТА")
            paragraph(task.goal[:400])

        section("СТАТУС")
        colour = STATUS_COLOURS.get(task.status, theme.FG)
        paragraph(f"{STATUS_BADGES.get(task.status, task.status.upper())}"
                  + (f" · {task.elapsed_text}" if task.elapsed_text else "")
                  + (f" · спроб: {task.attempts}" if task.attempts else ""),
                  colour=colour)
        if task.current_step:
            paragraph(task.current_step, colour=theme.ACCENT)

        if task.depends_on:
            section("ЗАЛЕЖНОСТІ")
            blockers = self.queue.blocked_by(task)
            names = []
            for dep in task.depends_on:
                other = self.queue.get(dep)
                if other is None:
                    continue
                label = f"{self._number(other)} {other.title[:40]}"
                if other in blockers:
                    label += " (ще не завершено)"
                names.append(label)
            paragraph("\n".join(names) or "—")

        if task.tools:
            section("ІНСТРУМЕНТИ")
            paragraph(", ".join(task.tools))

        # ── журнал виконання: лише реальні події
        section("ЩО ЗРОБИЛА МОДЕЛЬ")
        entries = task.history[-self.MAX_LOG_ROWS:]
        if not entries:
            paragraph("Ще немає дій: крок не виконувався.", colour=theme.FG_FAINT)
        else:
            for entry in entries:
                kind = str(entry.get("kind") or "")
                text = str(entry.get("text") or "")
                stamp = _clock(entry.get("at"))
                entry_colour = {
                    "failed": theme.ERROR,
                    "error": theme.ERROR,
                    "done": theme.SUCCESS,
                    "verify": theme.PURPLE,
                    "tool": theme.FG,
                    "start": theme.ACCENT,
                    "paused": theme.WARN,
                    "retry": theme.WARN,
                }.get(kind, theme.FG_DIM)
                line = tk.Label(self.detail_body, text=f"{stamp}  {text[:300]}",
                                bg=theme.BG_ALT, fg=entry_colour,
                                font=("Consolas", 7), justify="left", anchor="w",
                                wraplength=wrap)
                line.pack(fill="x", padx=theme.SPACE_SM)

        if task.files_changed:
            section("ЗМІНЕНІ ФАЙЛИ")
            for name in task.files_changed[:12]:
                row = tk.Frame(self.detail_body, bg=theme.BG_ALT, cursor="hand2")
                row.pack(fill="x", padx=theme.SPACE_SM)
                label = tk.Label(row, text=f"› {name}", bg=theme.BG_ALT,
                                 fg=theme.ACCENT, font=("Segoe UI", 8), anchor="w")
                label.pack(side="left")
                for widget in (row, label):
                    widget.bind("<Button-1>",
                                lambda _e, n=name: self._open_files(task)
                                if n is None else self._open_named(n))
                widgets.Tip(label, "Відкрити файл у редакторі")

        if task.error and task.status != queue_engine.FAILED:
            section("ПРИМІТКА")
            paragraph(task.error, colour=theme.WARN)
        if task.result:
            section("РЕЗУЛЬТАТ")
            paragraph(" ".join(task.result.split())[:800])

    def _open_named(self, name: str) -> None:
        if self.on_open_file is not None:
            self.on_open_file(name)
        else:
            self._notify(f"Файл: {name}")


def _clock(stamp) -> str:
    """Час події у форматі ГГ:ХХ (або порожньо, якщо його немає)."""
    try:
        import time as _time

        return _time.strftime("%H:%M", _time.localtime(float(stamp)))
    except (TypeError, ValueError, OSError):
        return "--:--"


__all__ = ["STATUS_BADGES", "STATUS_COLOURS", "TaskCenter"]
