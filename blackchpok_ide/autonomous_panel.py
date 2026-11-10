"""Панель «Автономний режим»: статус, план, черга задач і журнал дій.

    ┌──────────────────────────────────────────────────────────┐
    │ АВТОНОМНИЙ РЕЖИМ                        ● працює         │
    │ ┌──────────────────────────────────────────────────────┐ │
    │ │ 🗂 blackchpock_ai        [■ Зупинити]  [▶ Старт]     │ │
    │ │ Зараз: рефакторю обробку помилок у auth.py · 12 с    │ │
    │ └──────────────────────────────────────────────────────┘ │
    │ ПЛАН                                                     │
    │   ◆ зараз  Розібрати позначку TODO у main.py:41          │
    │   · далі   Додати тести для chat_store.py                │
    │ ЧЕРГА ЗАВДАЧ                    4 (моїх 1 · агента 3)    │
    │   ● ● моя задача — виправити баг у login       [×]      │
    │   ○ агент — прогнати тести                              │
    │ [поле: своя задача…]                              [＋]   │
    │ ЖУРНАЛ ДІЙ                                               │
    │   12:04:01  Автономний режим увімкнено   …               │
    └──────────────────────────────────────────────────────────┘

Панель нічого не вирішує сама: усі рішення живе в
:class:`blackchpok_ide.autonomous.AutonomousEngine`, а панель показує його
стан і передає дії назад у вікно IDE. Це дозволяє перевіряти логіку
тестами без ``mainloop``.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import theme, widgets
from . import autonomous as auto
from .autonomous import (
    KIND_ANALYSIS,
    KIND_CODE,
    KIND_RESEARCH,
    KIND_VERIFY,
    STATE_OFF,
    STATE_RUNNING,
    STATE_STOPPING,
)
from .queue_engine import ORIGIN_USER

#: Іконка й підпис для кожного виду робіт.
KIND_VIEWS = {
    KIND_ANALYSIS: ("◔", "аналіз"),
    KIND_CODE: ("✎", "код"),
    KIND_RESEARCH: ("⌕", "пошук"),
    KIND_VERIFY: ("✓", "перевірка"),
}

#: Кольори станів режиму.
STATE_COLOURS = {
    STATE_RUNNING: theme.SUCCESS,
    STATE_STOPPING: theme.WARN,
    STATE_OFF: theme.FG_FAINT,
}


class AutonomousPanel(tk.Frame):
    """Панель автономного режиму для бічної колонки."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        engine: auto.AutonomousEngine,
        *,
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_add_task: Optional[Callable[[str], None]] = None,
        on_pick_project: Optional[Callable[[], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_open_file: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.engine = engine
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_add_task = on_add_task
        self.on_pick_project = on_pick_project
        self.on_status = on_status
        self.on_open_file = on_open_file
        self._task_widgets: list[tk.Widget] = []
        self._plan_widgets: list[tk.Widget] = []
        self._log_widgets: list[tk.Widget] = []
        #: Підписи вмісту, щоб не перемальовувати секції без змін.
        #: ``None`` означає «ще не малювали»: порожній план теж дає
        #: підпис ``()``, і без відмінності між «нічого» та «порожньо»
        #: перша ж перемальовка пропускалась би й панель лишалась пустою.
        self._plan_signature: Optional[tuple] = None
        self._queue_signature: Optional[tuple] = None
        self._log_signature: Optional[tuple] = None
        self._build()
        self.refresh()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        # Заголовок і картка стану — фіксовані; усе інше (план, черга,
        # журнал) живе в ОДНІЙ прокручуваній колонці. Раніше кожна секція
        # мала власне полотно, і в невисокій бічній панелі всі три
        # стискались до одного рядка — панель виглядала порожньою.
        self.rowconfigure(2, weight=1)

        # ── заголовок: назва + стан
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 10), pady=(10, 2))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="АВТОНОМНИЙ РЕЖИМ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        self.state_label = tk.Label(head, text=STATE_OFF, bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="e")
        self.state_label.grid(row=0, column=1, sticky="e")

        # ── картка стану: проєкт, «зараз», кнопки
        card = widgets.Card(self, bg=theme.BG_CARD, border=theme.BORDER)
        card.grid(row=1, column=0, sticky="ew", padx=(10, 8), pady=(2, 6))
        body = card.inner
        body.columnconfigure(0, weight=1)

        project_row = tk.Frame(body, bg=theme.BG_CARD)
        project_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        project_row.columnconfigure(0, weight=1)
        self.project_label = tk.Label(project_row, text="проєкт не обрано",
                                      bg=theme.BG_CARD, fg=theme.FG_DIM,
                                      font=("Segoe UI", 9), anchor="w")
        self.project_label.grid(row=0, column=0, sticky="w")
        self.pick_btn = widgets.IconButton(project_row, "🗂", self._pick_project,
                                           bg=theme.BG_CARD, fg=theme.FG_FAINT,
                                           font=("Segoe UI", 9),
                                           tooltip="Обрати теку проєкту для автономного режиму")
        self.pick_btn.grid(row=0, column=1, sticky="e")

        self.focus_label = tk.Label(body, text="Режим вимкнено", bg=theme.BG_CARD,
                                    fg=theme.FG_FAINT, font=("Segoe UI", 8),
                                    anchor="w", justify="left", wraplength=self._wrap())
        self.focus_label.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))

        buttons = tk.Frame(body, bg=theme.BG_CARD)
        buttons.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.start_btn = widgets.Chip(buttons, "▶ Старт", self._start, font=("Segoe UI", 9))
        self.start_btn.pack(side="left", padx=(0, 4))
        self.stop_btn = widgets.Chip(buttons, "■ Зупинити", self._stop, font=("Segoe UI", 9))
        self.stop_btn.pack(side="left")

        # ── прокручувана стрічка секцій
        self.body_scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.body_scroll.grid(row=2, column=0, sticky="nsew", padx=(0, 0), pady=(0, 0))
        host = self.body_scroll.inner
        host.columnconfigure(0, weight=1)

        # План
        self._section_head(host, 0, "ПЛАН")
        self.plan_count = tk.Label(host, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 7), anchor="e")
        self.plan_count.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.plan_host = tk.Frame(host, bg=theme.BG_ALT)
        self.plan_host.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(4, 4), pady=(0, 6))

        # Черга задач
        self._section_head(host, 2, "ЧЕРГА ЗАВДАЧ")
        self.queue_count = tk.Label(host, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 7), anchor="e")
        self.queue_count.grid(row=2, column=1, sticky="e", padx=(0, 8))
        self.queue_host = tk.Frame(host, bg=theme.BG_ALT)
        self.queue_host.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(2, 2), pady=(0, 6))

        # Журнал дій
        log_head = self._section_head(host, 4, "ЖУРНАЛ ДІЙ")
        widgets.IconButton(log_head, "✕", self._clear_log, bg=theme.BG_ALT,
                           fg=theme.FG_FAINT, font=("Segoe UI", 8),
                           tooltip="Очистити журнал").grid(row=0, column=2, sticky="e",
                                                          padx=(0, 6))
        self.log_host = tk.Frame(host, bg=theme.BG_ALT)
        self.log_host.grid(row=5, column=0, columnspan=2, sticky="ew", padx=(4, 4), pady=(0, 8))

        # ── поле додавання задачі: завжди внизу, не прокручується
        add_row = tk.Frame(self, bg=theme.BG_ALT)
        add_row.grid(row=3, column=0, sticky="ew", padx=(8, 6), pady=(6, 6))
        add_row.columnconfigure(0, weight=1)
        self.task_entry = tk.Entry(
            add_row, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=("Segoe UI", 9), bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT,
        )
        self.task_entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self.task_entry.bind("<Return>", lambda _e: self._add_task())
        widgets.Tip(self.task_entry,
                    "Своя задача в автономну чергу. Пріоритет вищий за задачі агента.")
        widgets.IconButton(add_row, "＋", self._add_task, bg=theme.BG_INPUT,
                           fg=theme.FG_DIM, font=("Segoe UI", 10),
                           tooltip="Додати задачу (Enter)").grid(row=0, column=1, padx=(4, 0))

    def _wrap(self) -> int:
        """Довжина рядка переносу за фактичною шириною (а не за константою)."""
        try:
            width = self.winfo_width()
        except tk.TclError:
            width = 0
        if width < 80:
            width = theme.SIDEBAR_WIDTH
        return max(120, width - 56)

    def _section_head(self, master: tk.Misc, row: int, text: str) -> tk.Frame:
        head = tk.Frame(master, bg=theme.BG_ALT)
        head.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(12, 4), pady=(4, 2))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text=text, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 7, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        return head

    # ── дії ────────────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001 - статус не має ламати панель
                pass

    def _pick_project(self) -> None:
        if self.on_pick_project:
            self.on_pick_project()

    def _start(self) -> None:
        if self.on_start:
            self.on_start()

    def _stop(self) -> None:
        if self.on_stop:
            self.on_stop()

    def _add_task(self) -> None:
        text = self.task_entry.get().strip()
        if not text:
            self.task_entry.focus_set()
            return
        self.task_entry.delete(0, "end")
        if self.on_add_task:
            self.on_add_task(text)
        else:
            ok, message = self.engine.add_user_task(text)
            self._notify(message)
            self.refresh()

    def _clear_log(self) -> None:
        self.engine.log_entries.clear()
        self.refresh()
        self._notify("Журнал автономного режиму очищено.")

    def _open_touched(self, path: str) -> None:
        if path and self.on_open_file:
            self.on_open_file(path)

    # ── малювання ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Перемалювати панель зі стану рушія.

        Секції перемальовуються лише тоді, коли їхній вміст справді
        змінився: ``refresh`` кличеться на кожну подію рушія (кілька разів
        на секунду), а знищення й створення десятків віджетів щоразу
        помітно гальмувало б вікно.
        """
        if not self.winfo_exists():
            return
        snap = self.engine.snapshot()
        state = str(snap.get("state") or STATE_OFF)
        colour = STATE_COLOURS.get(state, theme.FG_FAINT)
        try:
            self.state_label.configure(text=f"● {state}", fg=colour)
            project = str(snap.get("project") or "")
            self.project_label.configure(
                text=project or "проєкт не обрано",
                fg=theme.FG_BRIGHT if project else theme.FG_DIM)
            running = state != STATE_OFF
            self.start_btn.configure(fg=theme.FG_FAINT if running else theme.FG)
            self.stop_btn.configure(fg=theme.FG if state == STATE_RUNNING else theme.FG_FAINT)
            focus = str(snap.get("focus") or "")
            if state == STATE_STOPPING:
                focus = "Зупиняю після поточного кроку: " + (focus or "чекаю агента")
            elif not focus:
                focus = ("Режим вимкнено — натисни «Старт»."
                         if state == STATE_OFF else "Шукаю, що покращити…")
            elapsed = self.engine.focus.elapsed_text if state == STATE_RUNNING else ""
            self.focus_label.configure(
                text=f"Зараз: {focus}" + (f" · {elapsed}" if elapsed else ""),
                fg=theme.FG if state != STATE_OFF else theme.FG_FAINT)
        except tk.TclError:
            return

        self._draw_plan(self._signature(self.engine.plan_rows()))
        self._draw_queue(snap, self._signature(self._queue_rows()))
        self._draw_log(self._signature([(e.clock, e.text, e.kind) for e in
                                        self.engine.recent_log(limit=80)]))

    @staticmethod
    def _signature(rows) -> tuple:
        return tuple(tuple(str(part) for part in row) for row in rows)

    def _queue_rows(self):
        """Рядки черги для показу (спершу задачі користувача)."""
        return [(task.id, task.status, task.text, task.origin, task.file_hint)
                for task in self.engine.pending_tasks(limit=30)]

    def _clear_rows(self, widgets_list: list[tk.Widget]) -> None:
        for widget in widgets_list:
            try:
                widget.destroy()
            except tk.TclError:
                pass
        widgets_list.clear()

    def _draw_plan(self, signature: Optional[tuple] = None) -> None:
        if signature is not None and signature == self._plan_signature:
            return
        self._plan_signature = signature
        self._clear_rows(self._plan_widgets)
        rows = self.engine.plan_rows()
        left = len([row for row in rows if row[2] != "готово"])
        try:
            self.plan_count.configure(text=f"у роботі {left}" if rows else "")
        except tk.TclError:
            pass
        if not rows:
            label = tk.Label(self.plan_host, text="Плану ще немає — він з'явиться після старту.",
                             bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                             justify="left", anchor="w", wraplength=self._wrap())
            label.pack(anchor="w", fill="x", padx=6, pady=4)
            self._plan_widgets.append(label)
            return
        for text, kind, state in rows:
            icon, _label = KIND_VIEWS.get(kind, ("·", kind))
            if state == "зараз":
                colour, mark = theme.ACCENT, "◆"
            elif state == "готово":
                colour, mark = theme.FG_FAINT, "✓"
            else:
                colour, mark = theme.FG_DIM, "·"
            row = tk.Frame(self.plan_host, bg=theme.BG_ALT)
            row.pack(fill="x", padx=2, pady=(0, 2))
            tk.Label(row, text=mark, bg=theme.BG_ALT, fg=colour,
                     font=("Segoe UI", 8)).pack(side="left", padx=(2, 4), anchor="n")
            tk.Label(row, text=f"{icon} {text}", bg=theme.BG_ALT, fg=colour,
                     font=("Segoe UI", 8), justify="left", anchor="w",
                     wraplength=max(110, self._wrap() - 24)).pack(side="left", fill="x",
                                                                 expand=True)
            self._plan_widgets.append(row)

    def _draw_queue(self, snap: dict, signature: Optional[tuple] = None) -> None:
        mine = int(snap.get("pending_user") or 0)
        theirs = int(snap.get("pending_agent") or 0)
        try:
            self.queue_count.configure(
                text=f"{mine + theirs} (моїх {mine} · агента {theirs})" if (mine or theirs) else "")
        except tk.TclError:
            pass
        if signature is not None and signature == self._queue_signature:
            return
        self._queue_signature = signature
        self._clear_rows(self._task_widgets)
        tasks = self.engine.pending_tasks(limit=30)
        if not tasks:
            label = tk.Label(self.queue_host,
                             text="Черга порожня. Агент сам додасть задачі, коли знайде покращення.",
                             bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                             justify="left", anchor="w", wraplength=self._wrap())
            label.pack(anchor="w", fill="x", padx=6, pady=4)
            self._task_widgets.append(label)
            return
        for task in tasks:
            row = tk.Frame(self.queue_host, bg=theme.BG_CARD, highlightthickness=1,
                           highlightbackground=theme.BORDER)
            row.pack(fill="x", padx=2, pady=(0, 3))
            row.columnconfigure(1, weight=1)
            user = task.origin == ORIGIN_USER
            mark = "●" if user else "○"
            colour = theme.ACCENT if user else theme.FG_DIM
            tk.Label(row, text=mark, bg=theme.BG_CARD, fg=colour,
                     font=("Segoe UI", 9)).grid(row=0, column=0, padx=(6, 4),
                                                pady=(4, 0), sticky="n")
            text = task.text if len(task.text) <= 110 else task.text[:107] + "…"
            tk.Label(row, text=text, bg=theme.BG_CARD, fg=theme.FG, font=("Segoe UI", 8),
                     justify="left", anchor="w",
                     wraplength=max(110, self._wrap() - 40)).grid(
                row=0, column=1, sticky="ew", pady=(4, 0), padx=(0, 4))
            badge = "від тебе" if user else "від агента"
            if task.file_hint:
                badge += f" · {task.file_hint}"
            tk.Label(row, text=badge, bg=theme.BG_CARD,
                     fg=theme.ACCENT if user else theme.FG_FAINT,
                     font=("Segoe UI", 7), anchor="w",
                     wraplength=max(110, self._wrap() - 40), justify="left").grid(
                row=1, column=1, sticky="w", pady=(0, 4), padx=(0, 4))
            # Зняти задачу з черги (не для активної — її можна лише зупинити).
            if task.status == "очікує":
                widgets.IconButton(row, "×", lambda t=task: self._drop_task(t),
                                   bg=theme.BG_CARD, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8),
                                   tooltip="Прибрати задачу з черги").grid(
                    row=0, column=2, rowspan=2, padx=(0, 2))
            self._task_widgets.append(row)

    def _drop_task(self, task) -> None:
        dropped = self.engine.queue.cancel(task.id)
        self._notify("Задачу знято з черги." if dropped else "Активну задачу можна лише зупинити.")
        self.refresh()

    def _draw_log(self, signature: Optional[tuple] = None) -> None:
        if signature is not None and signature == self._log_signature:
            return
        self._log_signature = signature
        self._clear_rows(self._log_widgets)
        entries = self.engine.recent_log(limit=80)
        if not entries:
            label = tk.Label(self.log_host, text="Журнал порожній.", bg=theme.BG_ALT,
                             fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w")
            label.pack(anchor="w", fill="x", padx=6, pady=4)
            self._log_widgets.append(label)
            return
        for entry in entries:
            colour = {
                "ok": theme.SUCCESS,
                "error": theme.ERROR,
                "user": theme.ACCENT,
                "stop": theme.WARN,
            }.get(entry.kind, theme.FG_DIM)
            row = tk.Frame(self.log_host, bg=theme.BG_ALT)
            row.pack(fill="x", padx=2, pady=(0, 1))
            tk.Label(row, text=entry.clock, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Consolas", 7)).pack(side="left", padx=(2, 6), anchor="n")
            tk.Label(row, text=entry.text, bg=theme.BG_ALT, fg=colour, font=("Segoe UI", 8),
                     justify="left", anchor="w",
                     wraplength=max(100, self._wrap() - 34)).pack(side="left", fill="x",
                                                                 expand=True)
            self._log_widgets.append(row)
        # Навмисно НЕ прокручуємо автоматично: план, черга й журнал живуть в
        # одній стрічці, і стрибок до кінця вибивав би користувача з читання
        # плану після кожного оновлення (а оновлення йдуть кілька разів на
        # секунду). Записи журналу й так ідуть останніми знизу.


__all__ = ["AutonomousPanel", "KIND_VIEWS", "STATE_COLOURS"]
