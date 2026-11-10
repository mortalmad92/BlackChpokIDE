"""Картка глибокого аналізу в чаті: думки, згортані групи, план, ціль.

Це та частина режиму, яку бачить користувач. Усе живе **в самому чаті** —
окремого вікна немає:

    ┌──────────────────────────────────────────────────────────────┐
    │ ◔ Глибоке розмислення                  7м 0с                 │
    ├──────────────────────────────────────────────────────────────┤
    │ Розберуся, що зараз відкриває браузер і як влаштований        │
    │ вбудований браузер.                                          │
    │                                                              │
    │ ▸ Читання файлів, пошук коду            4 кроки     міркую…  │
    │ Тепер зрозуміло. Перевірю ще кілька місць…                    │
    │ ▸ Читання файлів                        2 кроки     ✓        │
    │ Тепер маю повну картину. Складу план і почну.                │
    ├──────────────────────────────────────────────────────────────┤
    │ Діла            1 у процесі · 7 в очікуванні            ▾    │
    │   ◐ browser_panel: реєстр відкривача URL…                    │
    │   ○ preview_panel/live_preview: публічний open_url…          │
    ├──────────────────────────────────────────────────────────────┤
    │ ◎ Поточна ціль  BlackChpok IDE, частина 2: (1) жодне місце…  │
    └──────────────────────────────────────────────────────────────┘

Свідомі рішення:

* **наративи — окремі підписи**, а не рядки журналу: на скріншоті думки
  агента стоять абзацами між згортаними блоками;
* **групи згортані й підписані людською мовою** («Читання файлів»), а не
  списком викликів інструментів;
* **стани задач оновлюються на місці** — картка не перемальовується
  цілком, інакше прокрутка чату смикалась би.
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Optional

from . import deep_mode, pulse, theme, widgets


class _ThoughtGroup(tk.Frame):
    """Згортаний блок «що саме агент робив» (читання, пошук, команди)."""

    def __init__(self, master: tk.Misc, title: str, *, bg: str = theme.BG_CARD) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self._bg = bg
        self._expanded = False
        self._count = 0

        self.head = tk.Frame(self, bg=bg, cursor="hand2")
        self.head.pack(fill="x")
        self.head.columnconfigure(1, weight=1)

        self.arrow = tk.Label(self.head, text="▸", bg=bg, fg=theme.FG_FAINT,
                              font=("Segoe UI", 8))
        self.arrow.grid(row=0, column=0, padx=(2, 4), pady=2, sticky="w")

        self.title_label = tk.Label(self.head, text=title, bg=bg, fg=theme.FG_DIM,
                                    font=("Segoe UI", 8), anchor="w")
        self.title_label.grid(row=0, column=1, sticky="ew", pady=2)

        self.count_label = tk.Label(self.head, text="", bg=bg, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 7), anchor="e")
        self.count_label.grid(row=0, column=2, padx=(6, 6), pady=2, sticky="e")

        self.state_label = tk.Label(self.head, text="міркую…", bg=bg,
                                    fg=theme.STATUS_WORKING, font=("Segoe UI", 7),
                                    anchor="e")
        self.state_label.grid(row=0, column=3, padx=(0, 2), pady=2, sticky="e")

        #: Рядки всередині (приховані, поки блок згорнутий).
        self.body = tk.Frame(self, bg=bg)
        self._rows: list[tk.Label] = []

        for widget in (self.head, self.arrow, self.title_label, self.count_label):
            widget.bind("<Button-1>", lambda _e: self.toggle())

    # ── дії ────────────────────────────────────────────────────────────────
    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        try:
            if self._expanded:
                self.body.pack(fill="x", padx=(18, 4), pady=(0, 4))
                self.arrow.configure(text="▾")
            else:
                self.body.pack_forget()
                self.arrow.configure(text="▸")
        except tk.TclError:
            pass

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def row_count(self) -> int:
        return self._count

    def set_title(self, title: str) -> None:
        try:
            self.title_label.configure(text=title)
        except tk.TclError:
            pass

    def add_row(self, text: str, *, ok: Optional[bool] = None) -> None:
        """Додати рядок у групу (видно лише в розгорнутому стані)."""
        self._count += 1
        mark = "·" if ok is None else ("✓" if ok else "✗")
        colour = theme.FG_FAINT if ok is None else (
            theme.SUCCESS if ok else theme.ERROR)
        try:
            label = tk.Label(self.body, text=f"{mark} {text}", bg=self._bg, fg=colour,
                             font=("Segoe UI", 8), anchor="w", justify="left",
                             wraplength=380)
            label.pack(fill="x", pady=0)
        except tk.TclError:
            # Групу вже знищено (стрічку очищено), а фоновий потік агента ще
            # дописує крок. Лічильник лишається чесним, віджету немає кому
            # малювати — це не привід валити хід виконання.
            self._paint_count()
            return
        self._rows.append(label)
        self._paint_count()

    def finish(self, *, ok: bool = True) -> None:
        try:
            self.state_label.configure(text="✓" if ok else "✗",
                                       fg=theme.SUCCESS if ok else theme.ERROR)
        except tk.TclError:
            pass

    def _paint_count(self) -> None:
        try:
            self.count_label.configure(
                text=f"{self._count} кроків" if self._count != 1 else "1 крок")
        except tk.TclError:
            pass

    def apply_wrap(self, width: int) -> None:
        for label in self._rows:
            try:
                label.configure(wraplength=max(160, width))
            except tk.TclError:
                continue


class DeepCard(tk.Frame):
    """Картка одного сеансу глибокого аналізу.

    Малює три речі, які видно на скріншоті:

    1. індикатор «Глибоке розмислення» з таймером;
    2. наративи й згортані групи кроків;
    3. панель задач і блок поточної цілі.
    """

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        session: deep_mode.DeepSession,
        *,
        wrap_width: int = 520,
        on_open_result: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                         highlightbackground=theme.BORDER)
        self.fonts = fonts
        self.session = session
        self.on_open_result = on_open_result
        self._wrap = max(240, int(wrap_width))
        self._timer_job: Optional[str] = None
        self._group: Optional[_ThoughtGroup] = None
        self._group_tools: list[str] = []
        self._task_rows: dict[int, dict[str, tk.Label]] = {}
        self._goal_text = session.goal
        self._expanded_tasks = True

        self.columnconfigure(0, weight=1)
        self._build_header()
        self._build_thoughts()
        self._build_tasks()
        self._build_goal()
        self._start_timer()
        # Картку можуть знищити ззовні (очищення стрічки, закриття вікна) без
        # виклику stop_timers(). Тоді запланований ``after`` лишається живим,
        # а його команда зникає разом із віджетом — Tk друкує в stderr
        # «invalid command name ..._tick». Знімаємо таймер на самому знищенні.
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        self._stop_timer()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build_header(self) -> None:
        head = tk.Frame(self, bg=theme.BG_CARD, cursor="hand2")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        head.columnconfigure(2, weight=1)

        self.dot = pulse.PulseDot(head, size=12, bg=theme.BG_CARD,
                                  state=pulse.PulseDot.RUNNING)
        self.dot.grid(row=0, column=0, padx=(0, 6))

        self.title_label = tk.Label(head, text="Глибоке розмислення", bg=theme.BG_CARD,
                                    fg=theme.FG, font=("Segoe UI", 9, "bold"), anchor="w")
        self.title_label.grid(row=0, column=2, sticky="w")

        self.timer_label = tk.Label(head, text="0с", bg=theme.BG_CARD,
                                    fg=theme.STATUS_WORKING, font=("Segoe UI", 8),
                                    anchor="e")
        self.timer_label.grid(row=0, column=3, sticky="e", padx=(8, 0))
        self.header = head

    def _build_thoughts(self) -> None:
        self.thoughts = tk.Frame(self, bg=theme.BG_CARD)
        self.thoughts.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.thoughts.columnconfigure(0, weight=1)

    def _build_tasks(self) -> None:
        self.tasks_box = tk.Frame(self, bg=theme.BG_CARD)
        self.tasks_box.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 4))
        self.tasks_box.columnconfigure(0, weight=1)

        head = tk.Frame(self.tasks_box, bg=theme.BG_CARD, cursor="hand2")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="Діла", bg=theme.BG_CARD, fg=theme.FG,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w", pady=(4, 0))
        self.tasks_count = tk.Label(head, text="", bg=theme.BG_CARD, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="w")
        self.tasks_count.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

        self.tasks_arrow = tk.Label(head, text="▾", bg=theme.BG_CARD, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8))
        self.tasks_arrow.grid(row=0, column=2, sticky="e", pady=(4, 0))
        for widget in (head, self.tasks_arrow):
            widget.bind("<Button-1>", lambda _e: self.toggle_tasks())

        self.tasks_list = tk.Frame(self.tasks_box, bg=theme.BG_CARD)
        self.tasks_list.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        # Заголовок «Діла» без числа виглядав як обірваний: поки плану немає,
        # чесно пишемо «задач немає» — те саме, що повертає summary().
        self._paint_tasks_count()

    def _build_goal(self) -> None:
        self.goal_box = tk.Frame(self, bg=theme.BG_ALT, highlightthickness=0)
        self.goal_box.grid(row=3, column=0, sticky="ew", padx=10, pady=(2, 8))
        self.goal_box.columnconfigure(1, weight=1)

        self.goal_icon = tk.Label(self.goal_box, text="◎", bg=theme.BG_ALT,
                                  fg=theme.ACCENT, font=("Segoe UI", 9))
        self.goal_icon.grid(row=0, column=0, padx=(8, 6), pady=5, sticky="n")

        self.goal_label = tk.Label(
            self.goal_box,
            text=f"Поточна ціль  {deep_mode.goals_text(self._goal_text, limit=180)}",
            bg=theme.BG_ALT, fg=theme.FG_DIM, font=("Segoe UI", 8),
            anchor="w", justify="left", wraplength=self._wrap - 60)
        self.goal_label.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=5)
        widgets.Tip(self.goal_box, self._goal_text or "Ціль не задано")

    # ── наративи ───────────────────────────────────────────────────────────
    def add_narration(self, text: str) -> None:
        """Проміжна думка агента — окремий абзац стрічки."""
        clean = " ".join((text or "").split())
        if not clean:
            return
        # Наратив закриває поточну групу кроків: далі почнеться нова.
        self._close_group()
        label = tk.Label(self.thoughts, text=clean, bg=theme.BG_CARD, fg=theme.FG,
                         font=self.fonts.chat, anchor="w", justify="left",
                         wraplength=self._wrap - 20)
        label.pack(fill="x", pady=(2, 3))
        self.session.narrations += 1

    # ── групи кроків ───────────────────────────────────────────────────────
    def add_tool(self, name: str, target: str = "") -> None:
        """Додати виклик інструмента у поточну групу (створює її за потреби).

        Група об'єднує **споріднені** кроки: читання й пошук ідуть разом,
        бо для людини це один етап «вивчаю проєкт». Група закривається, коли
        починається інший ЕТАП — наприклад, зміна файлів чи запуск команд,
        або коли агент написав проміжну думку.
        """
        category = deep_mode.category_of(name)
        # Читання й пошук — один етап дослідження, тож лишаємо їх в одній групі.
        study = {deep_mode.CAT_READ, deep_mode.CAT_SEARCH}
        same_stage = (
            self._group is not None
            and self._group_tools
            and (category in study
                 and deep_mode.category_of(self._group_tools[0]) in study
                 or deep_mode.category_of(self._group_tools[0]) == category)
        )
        if not same_stage:
            self._close_group()
            self._group_tools = []
            self._group = _ThoughtGroup(self.thoughts, deep_mode.group_title([name]))
            self._group.pack(fill="x", pady=(1, 2))
        self._group_tools.append(name)
        self._group.set_title(deep_mode.group_title(self._group_tools))
        self._group.add_row(f"{name} {target}".strip())

    def finish_tool(self, *, ok: bool = True) -> None:
        """Позначити останній крок групи завершеним."""
        if self._group is not None:
            self._group.add_row("готово" if ok else "помилка", ok=ok)

    def _close_group(self) -> None:
        """Завершити поточну групу: підпис «✓» у заголовку."""
        group = self._group
        self._group = None
        self._group_tools = []
        if group is None:
            return
        try:
            group.finish(ok=True)
        except tk.TclError:
            pass

    # ── план ───────────────────────────────────────────────────────────────
    def set_tasks(self, steps) -> None:
        """Показати список задач (кружечки + текст).

        Ширина маркера задана в пікселях через ``minsize`` стовпця, а не
        через ``width=2`` символи: `○` і `◐` у шрифті Segoe UI ширші за
        цифру, і колонка «2 символи» обрізала текст задачі — на екрані це
        виглядало як обрізана перша літера замість кружечка.
        """
        self.session.set_tasks(steps)
        for child in self.tasks_list.winfo_children():
            child.destroy()
        self._task_rows.clear()
        for task in self.session.tasks:
            row = tk.Frame(self.tasks_list, bg=theme.BG_CARD)
            row.pack(fill="x", pady=0)
            row.columnconfigure(0, weight=0, minsize=18)
            row.columnconfigure(1, weight=1)
            mark = tk.Label(row, text=task.mark, bg=theme.BG_CARD,
                            fg=theme.FG_FAINT, font=("Segoe UI", 9), anchor="nw")
            mark.grid(row=0, column=0, sticky="nw", pady=1)
            text = tk.Label(row, text=task.text, bg=theme.BG_CARD, fg=theme.FG_DIM,
                            font=("Segoe UI", 8), anchor="w", justify="left",
                            wraplength=self._wrap - 50)
            text.grid(row=0, column=1, sticky="ew", pady=1)
            self._task_rows[task.index] = {"mark": mark, "text": text}
        self._paint_tasks_count()
        self.phase_note = True

    def paint_task(self, index: int) -> None:
        """Оновити стан однієї задачі на місці (без перемальовки списку)."""
        task = self.session.task_at(index)
        row = self._task_rows.get(index)
        if task is None or row is None:
            return
        colour = {
            deep_mode.STATE_RUNNING: theme.ACCENT,
            deep_mode.STATE_DONE: theme.SUCCESS,
            deep_mode.STATE_FAILED: theme.ERROR,
        }.get(task.state, theme.FG_FAINT)
        try:
            row["mark"].configure(text=task.mark, fg=colour)
            row["text"].configure(
                fg=theme.FG if task.running else (
                    theme.FG_FAINT if task.settled else theme.FG_DIM))
        except tk.TclError:
            pass
        self._paint_tasks_count()

    def _paint_tasks_count(self) -> None:
        try:
            self.tasks_count.configure(text=self.session.summary())
        except tk.TclError:
            pass

    def toggle_tasks(self) -> None:
        self._expanded_tasks = not self._expanded_tasks
        try:
            if self._expanded_tasks:
                self.tasks_list.grid()
                self.tasks_arrow.configure(text="▾")
            else:
                self.tasks_list.grid_remove()
                self.tasks_arrow.configure(text="▸")
        except tk.TclError:
            pass

    # ── ціль ───────────────────────────────────────────────────────────────
    def set_goal(self, text: str) -> None:
        self._goal_text = " ".join((text or "").split())
        try:
            self.goal_label.configure(
                text=f"Поточна ціль  {deep_mode.goals_text(self._goal_text, limit=180)}")
        except tk.TclError:
            pass

    # ── таймер ─────────────────────────────────────────────────────────────
    def _start_timer(self) -> None:
        self._stop_timer()
        self._tick()

    def _tick(self) -> None:
        self._timer_job = None
        self._paint_timer()
        if self.session.done:
            return
        try:
            if self.winfo_exists():
                self._timer_job = self.after(500, self._tick)
        except tk.TclError:
            self._timer_job = None

    def _paint_timer(self) -> None:
        try:
            self.timer_label.configure(text=self.session.elapsed_text)
        except tk.TclError:
            pass

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            try:
                self.after_cancel(self._timer_job)
            except (tk.TclError, ValueError):
                pass
            self._timer_job = None

    # ── завершення ─────────────────────────────────────────────────────────
    def finish(self, *, ok: bool = True) -> None:
        """Закрити сесію: застигнути таймер, закрити групу, поставити підсумок."""
        self._close_group()
        self.session.finish(ok=ok)
        for task in self.session.tasks:
            self.paint_task(task.index)
        self._stop_timer()
        self._paint_timer()
        try:
            self.dot.set_state(pulse.PulseDot.DONE if ok else pulse.PulseDot.FAILED)
            self.timer_label.configure(
                fg=theme.FG_FAINT if ok else theme.ERROR)
            self.title_label.configure(text="Аналіз завершен")
        except tk.TclError:
            pass

    def stop_timers(self) -> None:
        """Зупинити таймер (при закритті вікна)."""
        self._stop_timer()

    def apply_wrap(self, width: int) -> None:
        """Оновити переноси після зміни ширини чату."""
        self._wrap = max(240, int(width))
        for child in self.thoughts.winfo_children():
            try:
                child.configure(wraplength=self._wrap - 20)
            except tk.TclError:
                apply = getattr(child, "apply_wrap", None)
                if callable(apply):
                    apply(self._wrap - 50)
        try:
            self.goal_label.configure(wraplength=self._wrap - 60)
        except tk.TclError:
            pass
        for row in self._task_rows.values():
            try:
                row["text"].configure(wraplength=self._wrap - 50)
            except tk.TclError:
                continue


__all__ = ["DeepCard"]
