"""Смуга етапів над полем вводу: що агент робитиме й на чому він зараз.

Велике завдання агент розбиває на етапи, і людині треба бачити цей поділ
**у тому ж місці, де вона пише**, а не в окремій панелі:

    ┌──────────────────────────────────────────────────────────┐
    │ Етап 2 з 4 · blackchpok_ide/chat_mode_menu.py            │
    │ ◐ Об'єднати вкладки в один список                        │
    │   читання файлу · правка фрагмента                        │
    │ ✓ Додати іконки закриття й архівування                   │
    │ ○ Адаптивний розмір чату                                 │
    │ ○ Оновити документацію                                   │
    └──────────────────────────────────────────────────────────┘

Свідомі рішення:

* **кружечок, що крутиться**, а не статична крапка: поки етап виконується,
  видно рух — людина розуміє, що робота йде, а не зависла;
* **зелений ✓** після завершення: стан читається одним поглядом;
* **інструменти підписано людською мовою** («правка фрагмента»), а не
  назвами функцій — це підказка, що саме зараз відбувається;
* перемальовуємо лише коли вміст справді змінився: смуга живе над полем
  вводу, і зайва перебудова віджетів смикала б курсор.

Модуль має tkinter, тож логіка станів лежить у :mod:`task_plan`.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Sequence

from . import task_plan, theme

#: Період кадру спінера (мс).
SPIN_MS = 110
#: Кадри спінера: той самий «кружечок», що й у панелі справ.
SPIN_FRAMES = ("◜", "◝", "◞", "◟")


class StageStrip(tk.Frame):
    """Список етапів поточної задачі над композером."""

    #: Скільки етапів показуємо (решта — «і ще N»).
    VISIBLE = 6

    def __init__(self, master: tk.Misc, fonts: theme.Theme) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.columnconfigure(0, weight=1)
        self._stages: list[task_plan.Stage] = []
        self._goal = ""
        self._rows: list[tk.Widget] = []
        self._signature: tuple = ()
        self._spin_job: Optional[str] = None
        self._frame = 0
        self._marks: dict[int, tk.Label] = {}
        self.on_open: Optional[Callable[[], None]] = None
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)

        self.title = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_DIM,
                              font=("Segoe UI", 9, "bold"), anchor="w")
        self.title.grid(row=0, column=0, sticky="w")

        self.goal_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8), anchor="e")
        self.goal_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.list_host = tk.Frame(self, bg=theme.BG_ALT)
        self.list_host.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.grid_remove()

    # ── дані ───────────────────────────────────────────────────────────────
    def set_stages(self, stages: Sequence[task_plan.Stage], *, goal: str = "") -> None:
        """Показати етапи задачі (перемальовує лише при зміні)."""
        self._stages = list(stages or ())
        self._goal = " ".join((goal or "").split())
        signature = tuple((stage.text, stage.state) for stage in self._stages)
        if signature == self._signature:
            self._sync_spinner()
            return
        self._signature = signature
        self._paint()
        self._sync_spinner()

    def update_stage(self, index: int, state: str) -> None:
        """Оновити стан одного етапу (без перемальовки всього списку)."""
        target: Optional[task_plan.Stage] = None
        for stage in self._stages:
            if stage.index == index:
                if stage.state == state:
                    return
                stage.state = state
                target = stage
                break
        if target is None:
            return
        self._signature = tuple((s.text, s.state) for s in self._stages)
        mark = self._marks.get(index)
        was_running = state == task_plan.STAGE_RUNNING
        # Підпис інструментів є лише в поточного етапу, тож при зміні
        # «хто зараз у роботі» список треба перемалювати — інакше підпис
        # з'являвся б лише в того етапу, який був у роботі на момент побудови.
        if was_running or self._had_running_hint(index):
            self._paint()
            self._sync_spinner()
            return
        if mark is not None:
            try:
                mark.configure(text=target.mark, fg=self._colour_for(state))
            except tk.TclError:
                self._paint()
                self._sync_spinner()
                return
        self._paint_title()
        self._sync_spinner()

    def _had_running_hint(self, index: int) -> bool:
        """Чи показувався в рядка підпис інструментів (рядок вищій)."""
        for stage in self._stages:
            if stage.index == index:
                return bool(stage.tools_text())
        return False

    def clear(self) -> None:
        """Прибрати смугу (нова задача або очищення чату)."""
        self._stages = []
        self._goal = ""
        self._signature = ()
        self._paint()
        self._sync_spinner()

    @property
    def stages(self) -> list[task_plan.Stage]:
        return list(self._stages)

    def running_index(self) -> int:
        """Індекс етапу, що виконується (-1, якщо такого немає)."""
        for stage in self._stages:
            if stage.running:
                return stage.index
        return -1

    # ── малювання ──────────────────────────────────────────────────────────
    @staticmethod
    def _colour_for(state: str) -> str:
        return {
            task_plan.STAGE_RUNNING: theme.ACCENT,
            task_plan.STAGE_DONE: theme.SUCCESS,
            task_plan.STAGE_FAILED: theme.ERROR,
        }.get(state, theme.FG_FAINT)

    def _paint(self) -> None:
        for row in self._rows:
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()
        self._marks.clear()

        if not self._stages:
            try:
                self.grid_remove()
            except tk.TclError:
                pass
            return
        try:
            self.grid()
        except tk.TclError:
            return
        self._paint_title()

        hidden = max(0, len(self._stages) - self.VISIBLE)
        for stage in self._stages[: self.VISIBLE]:
            self._rows.append(self._row(stage))
        if hidden:
            more = tk.Label(self.list_host, text=f"і ще {hidden}",
                            bg=theme.BG_ALT, fg=theme.FG_FAINT,
                            font=("Segoe UI", 8), anchor="w")
            more.pack(fill="x", padx=(18, 0), pady=(1, 0))
            self._rows.append(more)

    def _paint_title(self) -> None:
        total = len(self._stages)
        done = sum(1 for stage in self._stages if stage.state == task_plan.STAGE_DONE)
        running = self.running_index()
        if running >= 0:
            head = f"Етап {running + 1} з {total}"
        elif total and done == total:
            head = f"Готово · усі {total} етапів"
        else:
            head = f"Етапи · {done} з {total}"
        try:
            self.title.configure(text=head)
            self.goal_label.configure(text=self._goal[:70])
        except tk.TclError:
            pass

    def _row(self, stage: task_plan.Stage) -> tk.Widget:
        row = tk.Frame(self.list_host, bg=theme.BG_ALT, cursor="hand2")
        row.pack(fill="x", pady=0)
        row.columnconfigure(1, weight=1)

        colour = self._colour_for(stage.state)
        mark = tk.Label(row, text=stage.mark, bg=theme.BG_ALT, fg=colour,
                        font=("Segoe UI", 10), width=2, anchor="w")
        mark.grid(row=0, column=0, sticky="w", padx=(0, 2))
        self._marks[stage.index] = mark

        text = " ".join((stage.text or "").split())
        shown = text if len(text) <= 90 else text[:89] + "…"
        label = tk.Label(row, text=shown, bg=theme.BG_ALT,
                         fg=theme.FG if stage.running else (
                             theme.FG_FAINT if stage.settled else theme.FG_DIM),
                         font=("Segoe UI", 9), anchor="w", justify="left")
        label.grid(row=0, column=1, sticky="ew")

        # Підпис інструментів: лише в поточного етапу — інакше шум.
        tools = stage.tools_text()
        if stage.running and tools:
            hint = tk.Label(row, text=tools, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                            font=("Segoe UI", 7), anchor="w", justify="left")
            hint.grid(row=1, column=1, sticky="ew")

        if self.on_open is not None:
            for widget in (row, mark, label):
                widget.bind("<Button-1>", lambda _e: self.on_open())
        return row

    # ── спінер ─────────────────────────────────────────────────────────────
    def _sync_spinner(self) -> None:
        """Увімкнути обертання, якщо є етап у роботі; інакше зупинити."""
        index = self.running_index()
        if index < 0:
            self._stop_spinner()
            return
        if self._spin_job is None:
            self._spin_spin()

    def _spin_spin(self) -> None:
        self._spin_job = None
        index = self.running_index()
        if index < 0:
            return
        self._frame = (self._frame + 1) % len(SPIN_FRAMES)
        mark = self._marks.get(index)
        if mark is not None:
            try:
                mark.configure(text=SPIN_FRAMES[self._frame], fg=theme.ACCENT)
            except tk.TclError:
                return
        try:
            if self.winfo_exists():
                self._spin_job = self.after(SPIN_MS, self._spin_spin)
        except tk.TclError:
            self._spin_job = None

    def _stop_spinner(self) -> None:
        if self._spin_job is not None:
            try:
                self.after_cancel(self._spin_job)
            except (tk.TclError, ValueError):
                pass
            self._spin_job = None
        # Повертаємо статичні позначки всім, хто не в роботі.
        for stage in self._stages:
            mark = self._marks.get(stage.index)
            if mark is None or stage.running:
                continue
            try:
                mark.configure(text=stage.mark, fg=self._colour_for(stage.state))
            except tk.TclError:
                continue

    def stop_timers(self) -> None:
        """Зупинити спінер (закриття вікна або очищення стрічки)."""
        self._stop_spinner()

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        self._stop_spinner()


__all__ = ["StageStrip"]
