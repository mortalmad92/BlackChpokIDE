"""Панель «Справи»: живий список того, що агент робить просто зараз.

Кожен запит користувача — це «справа». Поки агент працює, справа показує
свій список кроків (прочитав файл, викликав інструмент, сформулював
відповідь) із зеленими крапками, що пульсують, і кільцями, які розходяться.
Щойно крок завершується — кільце зникає, крапка стає спокійною галочкою.

Модель (:class:`CaseBook`) навмисно не тягне tkinter: її легко перевіряти
тестами, а панель лише малює те, що в ній лежить.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import tkinter as tk

from . import pulse, theme, widgets

#: Стани кроку й справи.
RUNNING = "виконується"
DONE = "готово"
FAILED = "помилка"
PENDING = "очікує"

#: Скільки кроків тримаємо в одній справі (старіші відрізаються).
MAX_STEPS = 40

#: Скільки справ тримаємо в списку.
MAX_CASES = 30


@dataclass
class Step:
    """Один крок роботи агента."""

    text: str
    status: str = RUNNING
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    key: str = ""

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.created_at)

    @property
    def elapsed_text(self) -> str:
        seconds = int(self.elapsed)
        if seconds <= 0:
            return ""
        if seconds < 60:
            return f"{seconds} с"
        return f"{seconds // 60} хв {seconds % 60} с"


@dataclass
class Case:
    """Справа: один запит і все, що агент зробив для нього."""

    title: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = RUNNING
    steps: list[Step] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    summary: str = ""
    error: str = ""

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.created_at)

    @property
    def elapsed_text(self) -> str:
        seconds = int(self.elapsed)
        if seconds <= 0:
            return ""
        if seconds < 60:
            return f"{seconds} с"
        return f"{seconds // 60} хв {seconds % 60} с"

    @property
    def active_steps(self) -> int:
        return sum(1 for step in self.steps if step.status == RUNNING)

    def short_title(self, limit: int = 90) -> str:
        text = " ".join((self.title or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"


class CaseBook:
    """Список справ і кроків. Джерело правди для панелі «Справи»."""

    def __init__(self) -> None:
        self.cases: list[Case] = []
        self.on_change: Optional[Callable[[], None]] = None
        self._current_id: str = ""

    # ── доступ ─────────────────────────────────────────────────────────────
    def current(self) -> Optional[Case]:
        """Справа, яка зараз виконується."""
        if not self._current_id:
            return None
        for case in self.cases:
            if case.id == self._current_id:
                return case
        return None

    def get(self, case_id: str) -> Optional[Case]:
        for case in self.cases:
            if case.id == case_id:
                return case
        return None

    @property
    def active(self) -> list[Case]:
        return [case for case in self.cases if case.status == RUNNING]

    def counts(self) -> dict[str, int]:
        result = {RUNNING: 0, DONE: 0, FAILED: 0}
        for case in self.cases:
            if case.status in result:
                result[case.status] += 1
        return result

    # ── зміни ──────────────────────────────────────────────────────────────
    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - панель не має ламати агента
                pass

    def begin(self, title: str) -> Case:
        """Почати нову справу (усі попередні, що «висять», закриваються)."""
        for case in self.cases:
            if case.status == RUNNING:
                case.status = DONE
                case.finished_at = time.time()
                for step in case.steps:
                    if step.status == RUNNING:
                        step.status = DONE
                        step.finished_at = time.time()
        case = Case(title=(title or "Запит").strip() or "Запит")
        self.cases.insert(0, case)
        self._current_id = case.id
        self._trim()
        self._changed()
        return case

    def add_step(self, text: str, *, key: str = "", status: str = RUNNING) -> Optional[Step]:
        """Додати крок до поточної справи.

        Кроки-віхи (без ``key``) — це повідомлення агента «що я роблю зараз»
        («Запит до моделі…», «Зрозумів як дію…»). Новий крок означає, що
        попередня віха вже позаду, тож її закриваємо: інакше в списку
        назавжди лишаються крапки, що «пульсують» без причини.
        """
        case = self.current()
        if case is None:
            return None
        clean = " ".join((text or "").split())
        if not clean:
            return None
        now = time.time()
        for previous in case.steps:
            if previous.status == RUNNING and not previous.key:
                previous.status = DONE
                previous.finished_at = now
        step = Step(text=clean[:300], status=status, key=key)
        case.steps.append(step)
        if len(case.steps) > MAX_STEPS:
            del case.steps[: len(case.steps) - MAX_STEPS]
        self._changed()
        return step

    def finish_step(self, *, key: str = "", text: str = "", ok: bool = True) -> bool:
        """Позначити крок завершеним (за ключем або за текстом)."""
        case = self.current()
        if case is None:
            return False
        target: Optional[Step] = None
        if key:
            for step in reversed(case.steps):
                if step.key == key and step.status == RUNNING:
                    target = step
                    break
        if target is None and text:
            needle = " ".join(text.split())[:120]
            for step in reversed(case.steps):
                if step.status == RUNNING and needle and needle in step.text:
                    target = step
                    break
        if target is None:
            for step in reversed(case.steps):
                if step.status == RUNNING:
                    target = step
                    break
        if target is None:
            return False
        target.status = DONE if ok else FAILED
        target.finished_at = time.time()
        self._changed()
        return True

    def end(self, *, ok: bool = True, summary: str = "", error: str = "") -> Optional[Case]:
        """Завершити поточну справу."""
        case = self.current()
        if case is None:
            return None
        case.status = DONE if ok else FAILED
        case.finished_at = time.time()
        case.summary = (summary or "").strip()
        case.error = (error or "").strip()
        for step in case.steps:
            if step.status == RUNNING:
                step.status = DONE if ok else FAILED
                step.finished_at = time.time()
        self._current_id = ""
        self._changed()
        return case

    def clear_finished(self) -> int:
        before = len(self.cases)
        self.cases = [case for case in self.cases if case.status == RUNNING]
        removed = before - len(self.cases)
        if removed:
            self._changed()
        return removed

    def clear(self) -> None:
        if not self.cases:
            return
        self.cases = []
        self._current_id = ""
        self._changed()

    def _trim(self) -> None:
        while len(self.cases) > MAX_CASES:
            # Найстарішу незавершену не викидаємо.
            victim = None
            for index in range(len(self.cases) - 1, -1, -1):
                if self.cases[index].status != RUNNING:
                    victim = index
                    break
            if victim is None:
                return
            del self.cases[victim]


def plural_steps(count: int) -> str:
    """Українське відмінювання: 1 крок · 2 кроки · 5 кроків."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} крок"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} кроки"
    return f"{count} кроків"


class CasesPanel(tk.Frame):
    """Список справ із живими індикаторами кроків."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        book: CaseBook,
        *,
        on_status: Optional[Callable[[str], None]] = None,
        on_focus_chat: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.book = book
        self.on_status = on_status
        self.on_focus_chat = on_focus_chat
        self._rows: dict[str, tk.Frame] = {}
        self._dots: list[pulse.PulseDot] = []
        self._expanded: set[str] = set()
        self._build()
        self.book.on_change = self.refresh

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="СПРАВИ", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e")

        clear = widgets.IconButton(head, "⌫", self._clear_done, bg=theme.BG_ALT,
                                   fg=theme.FG_FAINT, font=("Segoe UI", 9),
                                   tooltip="Прибрати завершені справи")
        clear.grid(row=0, column=2, padx=(6, 0))

        self.hint = tk.Label(
            self, text="Тут видно, що агент робить просто зараз — крок за кроком.",
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
            justify="left", wraplength=210,
        )
        self.hint.grid(row=1, column=0, sticky="ew", padx=(12, 8), pady=(0, 6))

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.host = self.scroll.inner

        self.empty = tk.Label(
            self.host, text="Справ ще немає.\nНапиши задачу в чаті — вона з'явиться тут.",
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 9), justify="left",
        )
        self.empty.pack(anchor="w", padx=6, pady=10)

    # ── дії ────────────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _clear_done(self) -> None:
        removed = self.book.clear_finished()
        self._notify(f"Прибрано справ: {removed}" if removed else "Немає завершених справ.")
        self.refresh()

    def toggle_case(self, case_id: str) -> None:
        if case_id in self._expanded:
            self._expanded.discard(case_id)
        else:
            self._expanded.add(case_id)
        self.refresh()

    def expand_active(self) -> None:
        """Розгорнути поточну справу, щоб кроки було видно одразу."""
        case = self.book.current()
        if case is not None:
            self._expanded.add(case.id)

    # ── малювання ──────────────────────────────────────────────────────────
    def _reset_dots(self) -> None:
        for dot in self._dots:
            try:
                dot.set_state(pulse.PulseDot.IDLE)
            except tk.TclError:
                pass
        self._dots.clear()

    def refresh(self) -> None:
        self._reset_dots()
        for row in self._rows.values():
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()

        counts = self.book.counts()
        running = counts.get(RUNNING, 0)
        self.count_label.configure(
            text=f"активних {running} · готово {counts.get(DONE, 0)}"
                 + (f" · збої {counts[FAILED]}" if counts.get(FAILED) else "")
        )

        has_cases = bool(self.book.cases)
        if has_cases and self.empty.winfo_ismapped():
            self.empty.pack_forget()
        elif not has_cases and not self.empty.winfo_ismapped():
            self.empty.pack(anchor="w", padx=6, pady=10)

        # Активна справа розгортається сама — саме її кроки цікаві під час роботи.
        self.expand_active()
        for case in self.book.cases:
            self._rows[case.id] = self._case_row(case)

    def _case_row(self, case: Case) -> tk.Frame:
        state = {
            RUNNING: pulse.PulseDot.RUNNING,
            DONE: pulse.PulseDot.DONE,
            FAILED: pulse.PulseDot.FAILED,
        }.get(case.status, pulse.PulseDot.IDLE)
        colour = {
            RUNNING: theme.SUCCESS,
            DONE: theme.SUCCESS,
            FAILED: theme.ERROR,
        }.get(case.status, theme.FG_FAINT)
        bg = theme.BG_CARD if case.status == RUNNING else theme.BG_ALT

        row = tk.Frame(self.host, bg=bg, bd=0, highlightthickness=1,
                       highlightbackground=theme.BORDER)
        row.pack(fill="x", padx=2, pady=(0, 4))
        row.columnconfigure(1, weight=1)

        dot = pulse.PulseDot(row, size=14, bg=bg, state=state, colour=colour)
        dot.grid(row=0, column=0, padx=(8, 6), pady=(7, 0), sticky="n")
        self._dots.append(dot)

        expanded = case.id in self._expanded
        head_text = case.short_title()
        header = tk.Label(row, text=head_text, bg=bg, fg=colour, font=("Segoe UI", 9),
                          justify="left", anchor="w", wraplength=210)
        header.grid(row=0, column=1, sticky="ew", pady=(6, 0), padx=(0, 4))

        meta_bits = [case.status]
        if case.elapsed_text:
            meta_bits.append(case.elapsed_text)
        if case.steps:
            meta_bits.append(plural_steps(len(case.steps)))
        meta = tk.Label(row, text=" · ".join(meta_bits), bg=bg, fg=theme.FG_FAINT,
                        font=("Segoe UI", 8), anchor="w")
        meta.grid(row=1, column=1, sticky="ew", padx=(0, 4), pady=(0, 6))

        arrow = tk.Label(row, text="▾" if expanded else "▸", bg=bg, fg=theme.FG_FAINT,
                         font=("Segoe UI", 8), cursor="hand2")
        arrow.grid(row=0, column=2, padx=(0, 8), pady=(7, 0), sticky="ne")

        for widget in (header, meta, arrow, row):
            widget.bind("<Button-1>", lambda _e, c=case.id: self.toggle_case(c))
            if widget is not row:
                widget.configure(cursor="hand2")

        if expanded and case.steps:
            steps_host = tk.Frame(row, bg=bg)
            steps_host.grid(row=2, column=0, columnspan=3, sticky="ew",
                            padx=(10, 6), pady=(0, 6))
            steps_host.columnconfigure(1, weight=1)
            for index, step in enumerate(case.steps):
                self._step_row(steps_host, index, step, bg)

        return row

    def _step_row(self, host: tk.Frame, index: int, step: Step, bg: str) -> None:
        state = {
            RUNNING: pulse.PulseDot.RUNNING,
            DONE: pulse.PulseDot.DONE,
            FAILED: pulse.PulseDot.FAILED,
        }.get(step.status, pulse.PulseDot.IDLE)
        colour = {
            RUNNING: theme.SUCCESS,
            DONE: theme.FG_DIM,
            FAILED: theme.ERROR,
        }.get(step.status, theme.FG_FAINT)

        dot = pulse.PulseDot(host, size=10, bg=bg, state=state,
                             colour=theme.SUCCESS if step.status == RUNNING else colour)
        dot.grid(row=index, column=0, padx=(0, 6), pady=2, sticky="n")
        self._dots.append(dot)

        text = step.text
        if step.status in {DONE, FAILED} and step.elapsed_text:
            text = f"{text}  ·  {step.elapsed_text}"
        label = tk.Label(host, text=text, bg=bg, fg=colour, font=("Segoe UI", 8),
                         justify="left", anchor="w", wraplength=190)
        label.grid(row=index, column=1, sticky="ew", pady=2)


__all__ = [
    "DONE",
    "FAILED",
    "MAX_CASES",
    "MAX_STEPS",
    "PENDING",
    "RUNNING",
    "Case",
    "CaseBook",
    "CasesPanel",
    "Step",
    "plural_steps",
]
