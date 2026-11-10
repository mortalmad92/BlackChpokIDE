"""Живий журнал роботи агента в чаті — згорнутий блок «Аналіз запиту».

Коли агент думає й викликає інструменти, користувачу мало бачити фінальну
відповідь: цікаво, *що саме* він робить просто зараз. Тому кроки збираються
в одну картку згорнутого вигляду:

    ▾ ◎ Аналіз запиту                          міркую… 12 с
      Спершу вивчу поточний стан проєкту.
      ▤ Читає · blackchpok_ide/main_window.py
      ⌕ Шукає · check\\(|def test_
      ✦ Міркує · Треба перевірити розкладку…
      ❯ Запускає · python tests/test_layout.py
      ✓ Готово · 5 кроків · 18 с

Заголовок клікається — блок згортається й розгортається. Поки справа
виконується, у заголовку пульсує зелена крапка й цокає таймер; коли
завершується, таймер застигає на витраченому часі.
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Optional

from . import pulse, theme, widgets

#: Скільки рядків тримаємо в журналі (старіші відрізаються).
MAX_ROWS = 60

#: Іконка, підпис і аргумент-ціль для кожного інструмента.
#: Ключ — назва інструмента агента.
#:
#: Підписи — українською й у третій особі («Читає», «Шукає»): журнал описує
#: дію агента, а не назву команди. Англійські назви лишались тут із ранніх
#: версій і робили рядки на кшталт «▤ Read file» посеред українського тексту.
#:
#: Третій елемент — КЛЮЧ АРГУМЕНТА, який справді є в схемі інструмента.
#: Раніше тут стояли ``file_path`` і ``file``, яких у схемах немає (там
#: ``path``), тож журнал показував сирий рядок аргументів замість імені
#: файлу — «path=calc.py, content=…» замість «calc.py».
TOOL_VIEWS: dict[str, tuple[str, str, str]] = {
    "read_file": ("▤", "Читає", "path"),
    "write_file": ("✎", "Записує", "path"),
    "edit_file": ("✎", "Редагує", "path"),
    "append_file": ("✎", "Дописує", "path"),
    "list_dir": ("▤", "Дивиться теку", "path"),
    "search_text": ("⌕", "Шукає", "query"),
    "find_files": ("⌕", "Шукає файли", "pattern"),
    "run_command": ("❯", "Запускає", "command"),
    "git_status": ("⑂", "Стан git", ""),
    "git_diff": ("⑂", "Зміни git", "path"),
    "project_tree": ("▦", "Будує дерево", "depth"),
    "python_check": ("✓", "Перевіряє синтаксис", "path"),
    # ── інтернет ───────────────────────────────────────────────────────────
    "search_web": ("⌕", "Шукає в інтернеті", "query"),
    "fetch_url": ("🌐", "Читає сторінку", "url"),
    "web_open": ("🖥", "Відкриває сторінку у браузері", "url"),
    "web_api": ("⇄", "Питає API", "url"),
    "internet_status": ("◍", "Перевіряє мережу", ""),
    "app_start": ("▶", "Запускає застосунок", ""),
    "app_stop": ("■", "Зупиняє застосунок", ""),
    "app_restart": ("⟳", "Перезапускає застосунок", ""),
    "app_status": ("◔", "Стан застосунку", ""),
    "app_screenshot": ("⊠", "Знімає екран", ""),
    "project_screenshot": ("⊠", "Знімає сайт проєкту", ""),
    "app_windows": ("▣", "Дивиться вікна", ""),
    "window_screenshot": ("⊠", "Знімає вікно", "title"),
    "app_logs": ("▤", "Читає журнал", ""),
    "app_click": ("◉", "Клікає", ""),
    "app_type": ("⌨", "Вводить текст", ""),
    "app_key": ("⌨", "Натискає клавішу", ""),
    # ── живий браузер (CDP) ────────────────────────────────────────────────
    "web_url": ("🌐", "Дивиться адресу", ""),
    "web_console": ("⚠", "Читає консоль", ""),
    "web_inspect": ("◎", "Інспектує елемент", "selector"),
    "web_screenshot": ("⊠", "Знімає сторінку", ""),
    "web_audit": ("✓", "Перевіряє сторінку", ""),
    "web_responsive": ("⇔", "Перевіряє адаптивність", ""),
    "web_click": ("◉", "Клікає на сторінці", "selector"),
    "web_type": ("⌨", "Вводить на сторінці", "selector"),
    # ── зір: знімки як ДАНІ (розміри, координати, ділянки, різниця) ────────
    # Цих 13 рядків не було зовсім, коли інструменти вже існували й
    # виконувались. Журнал показував замість дії сирий ідентифікатор
    # («⚙ capture_screen») посеред українського тексту, а тест повноти
    # підписів падав — тобто розбіжність була видима й не виправлена.
    "capture_screen": ("⊠", "Знімає екран", ""),
    "capture_region": ("⊠", "Знімає область екрана", ""),
    "crop_screenshot": ("✂", "Вирізає ділянку знімка", "path"),
    "get_image_dimensions": ("◇", "Міряє зображення", "path"),
    "get_screenshot_metadata": ("◇", "Читає метадані знімка", "path"),
    "inspect_screenshot_regions": ("⊞", "Розбирає знімок на ділянки", "path"),
    "compare_screenshots": ("⇄", "Порівнює знімки", "first"),
    "analyze_visual_difference": ("⇄", "Шукає, що змінилось", "first"),
    "list_screenshots": ("▤", "Дивиться історію знімків", ""),
    "dom_tree": ("▦", "Будує дерево DOM", ""),
    "dom_find_text": ("⌕", "Шукає текст на сторінці", "text"),
    "dom_styles": ("◎", "Читає стилі елемента", "selector"),
    "dom_console": ("⚠", "Читає консоль сторінки", ""),
    # ── лінивий реєстр інструментів ────────────────────────────────────────
    # Без цих рядків журнал показував «⚙ find_tools» посеред українського
    # тексту: саме та розбіжність, яку помітили в попередньому аудиті.
    "find_tools": ("⌕", "Шукає інструмент", "query"),
    "load_tools": ("⊕", "Довантажує схеми", "names"),
    "run_tool": ("⚙", "Викликає інструмент за назвою", "name"),
}

#: Людські підписи для видів рядків.
KIND_NARRATION = "narration"
KIND_TOOL = "tool"
KIND_REASONING = "reasoning"
KIND_STATUS = "status"
KIND_NOTE = "note"
KIND_SUMMARY = "summary"


def tool_view(name: str) -> tuple[str, str, str]:
    """Іконка, підпис і ключ аргументу для інструмента (з запасним варіантом)."""
    clean = (name or "").strip()
    if clean.startswith(("router:", "mcp:")):
        clean = clean.split(":", 1)[1]
    if clean in TOOL_VIEWS:
        return TOOL_VIEWS[clean]
    return "⚙", clean or "Інструмент", ""


def human_duration(seconds: float) -> str:
    """Тривалість по-людськи: 12 с · 2 хв 54 с · 1 год 5 хв."""
    total = int(max(0, seconds))
    if total < 60:
        return f"{total} с"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} хв {secs} с" if secs else f"{minutes} хв"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} год {minutes} хв"


def plural_steps(count: int) -> str:
    """Українське відмінювання: 1 крок · 2 кроки · 5 кроків."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} крок"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} кроки"
    return f"{count} кроків"


class _Row:
    """Один рядок журналу: тримає віджети, щоб оновлювати стан на місці."""

    __slots__ = ("frame", "icon", "label", "target", "kind", "call_id", "ok")

    def __init__(self, frame: tk.Frame, icon: tk.Label, label: tk.Label,
                 target: tk.Label, kind: str, call_id: str) -> None:
        self.frame = frame
        self.icon = icon
        self.label = label
        self.target = target
        self.kind = kind
        self.call_id = call_id
        self.ok = True


class WorkLog(tk.Frame):
    """Згорнутий журнал кроків агента для однієї відповіді."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        wrap_width: int = 420,
        on_open_result: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BORDER, bd=0, highlightthickness=0)
        self.fonts = fonts
        self._wrap = max(220, int(wrap_width))
        self.on_open_result = on_open_result

        self._rows: list[_Row] = []
        self._by_call: dict[str, _Row] = {}
        self._expanded = True
        self._running = False
        self._started = 0.0
        self._finished = 0.0
        self._timer_job: Optional[str] = None
        self._expanded_before_finish = True
        #: Рядок роздумів, який зараз дописується стрімінгом.
        self._live_reasoning: Optional[_Row] = None

        self.body = tk.Frame(self, bg=theme.BG_CARD, bd=0, highlightthickness=0)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_header()
        self.rows_host = tk.Frame(self.body, bg=theme.BG_CARD)
        self.rows_host.pack(fill="x", padx=(0, 8), pady=(0, 8))

    # ── заголовок ──────────────────────────────────────────────────────────
    def _build_header(self) -> None:
        self.header = tk.Frame(self.body, bg=theme.BG_CARD, cursor="hand2")
        self.header.pack(fill="x", padx=(10, 8), pady=(7, 5))
        self.header.columnconfigure(2, weight=1)

        self.arrow = tk.Label(self.header, text="▾", bg=theme.BG_CARD,
                              fg=theme.FG_FAINT, font=("Segoe UI", 8))
        self.arrow.grid(row=0, column=0, padx=(0, 6))

        self.dot = pulse.PulseDot(self.header, size=12, bg=theme.BG_CARD,
                                  state=pulse.PulseDot.RUNNING)
        self.dot.grid(row=0, column=1, padx=(0, 6))

        self.title_label = tk.Label(self.header, text="Аналіз запиту", bg=theme.BG_CARD,
                                    fg=theme.FG, font=("Segoe UI", 9, "bold"), anchor="w")
        self.title_label.grid(row=0, column=2, sticky="w")

        self.timer_label = tk.Label(self.header, text="", bg=theme.BG_CARD,
                                    fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="e")
        self.timer_label.grid(row=0, column=3, sticky="e", padx=(8, 0))

        for widget in (self.header, self.arrow, self.title_label, self.timer_label):
            widget.bind("<Button-1>", lambda _e: self.toggle())

    def set_title(self, text: str) -> None:
        try:
            self.title_label.configure(text=text or "Аналіз запиту")
        except tk.TclError:
            pass

    # ── життєвий цикл ──────────────────────────────────────────────────────
    def begin(self, title: str = "Аналіз запиту") -> None:
        """Почати новий журнал: чистимо рядки, запускаємо таймер."""
        self.clear()
        self.set_title(title)
        self._running = True
        self._started = time.time()
        self._finished = 0.0
        self._expanded = True
        self._apply_expanded()
        try:
            self.dot.configure(state=pulse.PulseDot.RUNNING)
        except tk.TclError:
            pass
        self._start_timer()
        self._paint_timer()

    def finish(self, *, ok: bool = True) -> None:
        """Завершити журнал: зупинити таймер, поставити підсумок."""
        if not self._running:
            return
        self._running = False
        self._finished = time.time()
        try:
            self.dot.set_state(pulse.PulseDot.DONE if ok else pulse.PulseDot.FAILED)
        except tk.TclError:
            pass
        self._stop_timer()
        self._paint_timer()
        steps = sum(1 for row in self._rows if row.kind == KIND_TOOL)
        summary = f"{'Готово' if ok else 'Зупинено'} · {plural_steps(steps)} · " \
                  f"{human_duration(self._finished - self._started)}"
        self.add_row(KIND_SUMMARY, "✓" if ok else "✗", summary,
                     colour=theme.SUCCESS if ok else theme.ERROR)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def duration(self) -> float:
        if not self._started:
            return 0.0
        return max(0.0, (self._finished or time.time()) - self._started)

    @property
    def step_count(self) -> int:
        return sum(1 for row in self._rows if row.kind == KIND_TOOL)

    # ── рядки ──────────────────────────────────────────────────────────────
    def clear(self) -> None:
        for row in self._rows:
            try:
                row.frame.destroy()
            except tk.TclError:
                pass
        self._rows.clear()
        self._by_call.clear()

    def add_row(
        self,
        kind: str,
        icon: str,
        text: str,
        *,
        target: str = "",
        call_id: str = "",
        colour: str = "",
        italic: bool = False,
        clickable: str = "",
    ) -> Optional[_Row]:
        """Додати рядок журналу й повернути його ручку."""
        clean = " ".join((text or "").split())
        if not clean and not target:
            return None

        colour = colour or {
            KIND_REASONING: theme.PURPLE,
            KIND_STATUS: theme.FG_FAINT,
            KIND_NOTE: theme.FG_FAINT,
            KIND_SUMMARY: theme.FG_DIM,
        }.get(kind, theme.FG_DIM)

        frame = tk.Frame(self.rows_host, bg=theme.BG_CARD)
        frame.pack(fill="x", pady=(0, 2))
        frame.columnconfigure(2, weight=1)

        icon_label = tk.Label(frame, text=icon, bg=theme.BG_CARD, fg=colour,
                              font=("Segoe UI", 8), width=2, anchor="w")
        icon_label.grid(row=0, column=0, padx=(0, 2), sticky="nw")

        label = tk.Label(frame, text=clean, bg=theme.BG_CARD, fg=colour,
                         font=("Segoe UI", 8, "italic") if italic else ("Segoe UI", 8),
                         justify="left", anchor="w", wraplength=self._wrap - 90)
        label.grid(row=0, column=1, sticky="w")

        target_label = tk.Label(frame, text=target, bg=theme.BG_CARD, fg=theme.FG_FAINT,
                                font=self.fonts.mono_small, justify="left", anchor="w")
        if target:
            target_label.grid(row=0, column=2, sticky="w", padx=(6, 0))
            # Довгі шляхи обрізаємо з початку: важливіше кінець.
            shown = target if len(target) <= 46 else "…" + target[-45:]
            try:
                target_label.configure(text="› " + shown)
            except tk.TclError:
                pass

        if clickable:
            for widget in (label, target_label, icon_label):
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>",
                            lambda _e, t=clickable: self._open(t))

        row = _Row(frame, icon_label, label, target_label, kind, call_id)
        self._rows.append(row)
        if call_id:
            self._by_call[call_id] = row
        self._trim()
        return row

    def add_tool(self, name: str, arguments: str = "", *, call_id: str = "") -> Optional[_Row]:
        """Рядок виклику інструмента з людським підписом."""
        icon, verb, key = tool_view(name)
        target = _target_of(key, arguments)
        return self.add_row(KIND_TOOL, icon, verb, target=target, call_id=call_id)

    def add_reasoning(self, text: str) -> Optional[_Row]:
        """Рядок роздумів моделі (reasoning_content)."""
        preview = _first_sentence(text)
        if not preview:
            return None
        row = self.add_row(KIND_REASONING, "✦", preview, colour=theme.PURPLE,
                           italic=True, clickable=text if len(text) > len(preview) else "")
        self._live_reasoning = row
        return row

    def set_live_reasoning(self, text: str) -> None:
        """Оновлювати рядок роздумів у міру стрімінгу (один рядок, не сотні)."""
        preview = _first_sentence(text, limit=160)
        if not preview:
            return
        row = getattr(self, "_live_reasoning", None)
        try:
            if row is not None and row.frame.winfo_exists():
                row.label.configure(text=preview)
                row.clickable = text  # type: ignore[attr-defined]
                return
        except tk.TclError:
            pass
        self.add_reasoning(text)

    def add_narration(self, text: str) -> Optional[_Row]:
        """Проміжний текст агента («Спершу вивчу проєкт…»)."""
        preview = _first_sentence(text, limit=180)
        if not preview:
            return None
        return self.add_row(KIND_NARRATION, "│", preview, colour=theme.FG,
                            clickable=text if len(text) > len(preview) else "")

    def finish_tool(self, call_id: str, *, ok: bool = True) -> None:
        """Позначити інструмент завершеним: галочка й приглушений колір."""
        row = self._by_call.get(call_id) if call_id else None
        if row is None:
            row = next((r for r in reversed(self._rows)
                        if r.kind == KIND_TOOL and r.ok is None), None)
        if row is None:
            return
        row.ok = bool(ok)
        try:
            row.icon.configure(text="✓" if ok else "✗",
                               fg=theme.SUCCESS if ok else theme.ERROR)
            row.label.configure(fg=theme.FG_DIM if ok else theme.ERROR)
        except tk.TclError:
            pass

    def _trim(self) -> None:
        while len(self._rows) > MAX_ROWS:
            row = self._rows.pop(0)
            if row.call_id:
                self._by_call.pop(row.call_id, None)
            try:
                row.frame.destroy()
            except tk.TclError:
                pass

    def _open(self, text: str) -> None:
        if self.on_open_result:
            try:
                self.on_open_result(text)
            except Exception:  # noqa: BLE001 - перегляд не має ламати чат
                pass

    # ── згортання ──────────────────────────────────────────────────────────
    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded()

    def set_expanded(self, expanded: bool) -> None:
        if bool(expanded) == self._expanded:
            return
        self._expanded = bool(expanded)
        self._apply_expanded()

    def _apply_expanded(self) -> None:
        try:
            if self._expanded:
                self.rows_host.pack(fill="x", padx=(0, 8), pady=(0, 8))
                self.arrow.configure(text="▾")
            else:
                self.rows_host.pack_forget()
                self.arrow.configure(text="▸")
        except tk.TclError:
            pass

    # ── таймер ─────────────────────────────────────────────────────────────
    def _start_timer(self) -> None:
        self._stop_timer()
        self._schedule_tick()

    def _schedule_tick(self) -> None:
        if not self._running:
            return
        try:
            self._timer_job = self.after(500, self._tick)
        except tk.TclError:
            self._timer_job = None

    def _tick(self) -> None:
        self._timer_job = None
        if not self._running:
            return
        self._paint_timer()
        self._schedule_tick()

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            try:
                self.after_cancel(self._timer_job)
            except (tk.TclError, ValueError):
                pass
            self._timer_job = None

    def _paint_timer(self) -> None:
        if not self._started:
            return
        elapsed = self.duration
        if self._running:
            text = f"міркую… {human_duration(elapsed)}"
            colour = theme.STATUS_WORKING
        else:
            text = human_duration(elapsed)
            colour = theme.FG_FAINT
        try:
            self.timer_label.configure(text=text, fg=colour)
        except tk.TclError:
            pass

    def stop_timers(self) -> None:
        """Зупинити таймери (при закритті вікна)."""
        self._stop_timer()
        try:
            self.dot.set_state(pulse.PulseDot.IDLE)
        except tk.TclError:
            pass

    def apply_font(self, wrap_width: int) -> None:
        """Оновити переноси після зміни розміру вікна."""
        self._wrap = max(220, int(wrap_width))
        for row in self._rows:
            try:
                row.label.configure(wraplength=self._wrap - 90)
            except tk.TclError:
                continue


def _target_of(key: str, arguments: str) -> str:
    """Витягти з аргументів інструмента найважливіше (шлях, запит, команду)."""
    raw = (arguments or "").strip()
    if not raw:
        return ""
    if not key:
        return raw if len(raw) <= 46 else raw[:45] + "…"
    # Аргументи приходять як «key=value, key2=value2».
    for chunk in raw.split(","):
        name, _, value = chunk.partition("=")
        if name.strip() == key:
            clean = value.strip().strip("'\"")
            return clean if len(clean) <= 46 else "…" + clean[-45:]
    return raw if len(raw) <= 46 else raw[:45] + "…"


def _first_sentence(text: str, limit: int = 120) -> str:
    """Перше змістовне речення — для прев'ю рядка роздумів."""
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    for stop in (". ", "! ", "? ", "\n"):
        cut = clean.find(stop)
        if 0 < cut <= limit:
            return clean[: cut + 1].strip()
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


__all__ = [
    "KIND_NARRATION",
    "KIND_NOTE",
    "KIND_REASONING",
    "KIND_STATUS",
    "KIND_SUMMARY",
    "KIND_TOOL",
    "MAX_ROWS",
    "TOOL_VIEWS",
    "WorkLog",
    "human_duration",
    "plural_steps",
    "tool_view",
]
