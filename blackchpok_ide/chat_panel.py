"""Права панель агента: стрічка повідомлень, виклики інструментів, композер.

Повідомлення малюються картками в прокручуваному полотні — так само, як у
сучасних агентних інтерфейсах: окремий блок для запиту користувача, окремий
для відповіді, окремі рядки для викликів інструментів.
"""

from __future__ import annotations

import difflib
import logging
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

from . import (command_menu, deep_mode, deep_view, effort, markdown_view,
               message_parts, model_menu, permissions, planner, safe,
               slash_commands, stage_strip, stats_bar, task_plan, theme, voice,
               voice_panel, widgets, work_log)
from .agent import AgentEvent, AgentRunner
from .agent_tools import ToolRegistry
from .config import Settings

LOG = logging.getLogger("blackchpok.chat")

ROLE_USER = "ВИ"
ROLE_AGENT = "АГЕНТ"
ROLE_TOOL = "ІНСТРУМЕНТ"

#: Скільки повідомлень показувати при відкритті збереженого чату.
#: Довгі розмови малюються помітно довше, тож у стрічку йде останній
#: «хвіст» — решта лишається у сховищі й доступна через експорт.
HISTORY_RENDER_LIMIT = 200

#: Скільки рядків однієї відповіді показувати, якщо розмір ще не задано.
#: Вікно IDE перераховує це адаптивно до екрана (див. :meth:`set_max_lines`).
_DEFAULT_BODY_LINES = 60

#: Абсолютний запобіжник: довший текст показуємо з власною прокруткою.
#: Полотно Tk перестає малювати вміст під ~24 000 px, тож відповідь на
#: тисячі рядків усе одно треба обмежити — інакше вона просто зникне.
_HARD_TEXT_LINES = 400


class Transcript:
    """Плоский текстовий журнал чату (для експорту, копіювання й тестів)."""

    def __init__(self) -> None:
        self._chunks: list[str] = []

    def add(self, text: str) -> None:
        if text:
            self._chunks.append(text)

    def clear(self) -> None:
        self._chunks.clear()

    def get(self, _start: str = "1.0", _end: str = "end") -> str:
        return "".join(self._chunks)

    def dump(self) -> str:
        return self.get()

    def __len__(self) -> int:
        return len(self._chunks)


class _MessageCard(tk.Frame):
    """Картка одного повідомлення в стилі Cursor: м'яка, світла, заокруглена.

    Запит користувача — біла картка з тонкою рамкою; відповідь агента — на
    тлі стрічки, з підписом ролі. Жодних важких «коробок».
    """

    def __init__(self, master: tk.Misc, fonts: theme.Theme, role: str, *, accent: str = theme.FG_DIM,
                 bg: str = theme.BG_CARD) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.role = role
        self._bg = bg
        self._accent = accent

        body = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True)

        head = tk.Frame(body, bg=bg)
        head.pack(fill="x", pady=(theme.SPACE_MD, 0))
        self.role_label = tk.Label(head, text=role, bg=bg, fg=accent,
                                   font=("Segoe UI", 8, "bold"))
        self.role_label.pack(side="left")
        self.time_label = tk.Label(head, text=time.strftime("%H:%M"), bg=bg, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8))
        self.time_label.pack(side="right")
        self.extra = tk.Frame(head, bg=bg)
        self.extra.pack(side="right", padx=(0, 8))

        self.content = tk.Frame(body, bg=bg)
        self.content.pack(fill="both", expand=True, pady=(theme.SPACE_XS, theme.SPACE_LG))

    def add_action(self, text: str, command: Callable[[], None], tooltip: str = "") -> tk.Label:
        label = widgets.HoverLabel(self.extra, text=text, command=command, bg=self._bg,
                                   fg=theme.FG_FAINT, hover_fg=theme.FG,
                                   font=("Segoe UI", 8), padx=4, pady=0)
        label.pack(side="right")
        if tooltip:
            widgets.Tip(label, tooltip)
        return label


def make_diff_lines(old_text: str, new_text: str) -> list[tuple[str, str]]:
    """Рядки unified diff для картки змін: [('add'|'del'|'ctx', text)]."""
    diff = difflib.unified_diff(
        (old_text or "").splitlines(), (new_text or "").splitlines(),
        lineterm="", n=2,
    )
    rows: list[tuple[str, str]] = []
    for line in list(diff)[2:]:
        if line.startswith("+") and not line.startswith("+++"):
            rows.append(("add", line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            rows.append(("del", line[1:]))
        else:
            rows.append(("ctx", line))
    return rows


class _QueueStrip(tk.Frame):
    """Компактний список черги завдань над полем вводу.

    Показує лише те, що потрібно бачити в розмові: що виконується зараз і
    що буде далі. Кожен рядок — один рядок тексту з маркером стану; повний
    список із керуванням лишається в панелі «Черга завдань».

    Чому тут, а не в сайдбарі: черга — це частина поточної роботи, і
    ховати її за перемикачем панелей означало постійно втрачати контекст.
    """

    #: Скільки задач показуємо (решта — «і ще N»).
    VISIBLE = 3

    def __init__(self, master: tk.Misc, fonts: theme.Theme) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.columnconfigure(0, weight=1)
        self._rows: list[tk.Widget] = []
        self._signature: tuple = ()
        self._build()

    def _build(self) -> None:
        self.header = tk.Frame(self, bg=theme.BG_ALT)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(1, weight=1)

        self.title = tk.Label(self.header, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                              font=("Segoe UI", 9, "bold"), anchor="w")
        self.title.grid(row=0, column=0, sticky="w")

        self.more = tk.Label(self.header, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                             font=("Segoe UI", 8), anchor="e")
        self.more.grid(row=0, column=1, sticky="e")

        self.list_host = tk.Frame(self, bg=theme.BG_ALT)
        self.list_host.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.grid_remove()

    def update_from(self, tasks, *, on_open=None) -> None:
        """Оновити список за задачами черги.

        ``tasks`` — послідовність об'єктів із полями ``text``, ``status``,
        ``from_user``. Перемальовуємо лише коли вміст справді змінився:
        метод кличеться часто, а перебудова віджетів на кожен тік помітна.
        """
        active = [task for task in (tasks or ())
                  if getattr(task, "status", "") in ("виконується", "очікує")]
        signature = tuple((getattr(t, "text", ""), getattr(t, "status", ""),
                           bool(getattr(t, "from_user", False))) for t in active)
        if signature == self._signature:
            return
        self._signature = signature

        for row in self._rows:
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._rows.clear()

        if not active:
            try:
                self.grid_remove()
            except tk.TclError:
                pass
            return
        try:
            self.grid()
        except tk.TclError:
            return

        self.title.configure(
            text=f"Черга · {len(active)}" if len(active) != 1 else "Черга · 1 задача")
        hidden = max(0, len(active) - self.VISIBLE)
        self.more.configure(text=f"і ще {hidden}" if hidden else "")

        for task in active[: self.VISIBLE]:
            running = getattr(task, "status", "") == "виконується"
            mark = "◐" if running else "○"
            colour = theme.ACCENT if running else theme.FG_FAINT
            mine = bool(getattr(task, "from_user", False))
            row = tk.Frame(self.list_host, bg=theme.BG_ALT, cursor="hand2")
            row.pack(fill="x", pady=0)
            row.columnconfigure(1, weight=1)
            tk.Label(row, text=mark, bg=theme.BG_ALT, fg=colour,
                     font=("Segoe UI", 10)).grid(row=0, column=0, padx=(0, 4), sticky="w")
            text = " ".join(str(getattr(task, "text", "") or "").split())
            shown = text if len(text) <= 92 else text[:91] + "…"
            tk.Label(row, text=shown, bg=theme.BG_ALT,
                     fg=theme.FG if running else theme.FG_DIM,
                     font=("Segoe UI", 9), anchor="w", justify="left").grid(
                row=0, column=1, sticky="ew")
            if mine:
                tk.Label(row, text="від тебе", bg=theme.BG_ALT, fg=theme.ACCENT,
                         font=("Segoe UI", 8)).grid(row=0, column=2, padx=(6, 0), sticky="e")
            if on_open is not None:
                for widget in row.winfo_children():
                    widget.bind("<Button-1>", lambda _e: on_open())
                row.bind("<Button-1>", lambda _e: on_open())
            self._rows.append(row)


class _ComposerPill(tk.Frame):
    """Пігулка вибору над полем вводу: «🗂 проєкт ▾» або «◈ режим ▾».

    Чому окремий віджет, а не ``Chip``: пігулка мусить показувати **стан**
    (теку проєкту, режим роботи) і міняти його випадаючим меню, а не просто
    виконувати дію. Тому тут дві частини — іконка з підписом і «▾», — і
    клік по будь-якій відкриває меню.

    Підпис ніколи не «бреше»: текст задає оболонка через
    :meth:`set_text` рівно тим значенням, яке справді застосоване.
    """

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        icon: str = "",
        text: str = "",
        command: Optional[Callable[[], None]] = None,
        tip: str = "",
        bg: str = theme.BG_ACTIVE,
    ) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0, cursor="hand2")
        self._bg = bg
        self._command = command
        self._icon_text = icon
        self._arrow_text = "▾"
        self._fg = theme.FG
        self.icon = tk.Label(self, text=icon, bg=bg, fg=theme.FG_DIM,
                             font=("Segoe UI", 9), cursor="hand2")
        self.icon.pack(side="left", padx=(theme.SPACE_MD, theme.SPACE_XS), pady=4)
        self.label = tk.Label(self, text=text, bg=bg, fg=theme.FG,
                              font=("Segoe UI", 9), cursor="hand2", anchor="w")
        self.label.pack(side="left", pady=4)
        self.arrow = tk.Label(self, text=self._arrow_text, bg=bg, fg=theme.FG_FAINT,
                              font=("Segoe UI", 8), cursor="hand2")
        self.arrow.pack(side="left", padx=(theme.SPACE_XS, theme.SPACE_MD), pady=4)
        for widget in (self, self.icon, self.label, self.arrow):
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
            widget.bind("<Button-1>", self._on_click, add="+")
        if tip:
            widgets.Tip(self.icon, tip)

    def set_text(self, text: str, *, accent: bool = False) -> None:
        """Показати реальне значення (не припущення)."""
        self._fg = theme.FG_BRIGHT if accent else theme.FG
        try:
            self.label.configure(text=text or "", fg=self._fg)
        except tk.TclError:
            pass

    def set_icon(self, icon: str) -> None:
        try:
            self.icon.configure(text=icon or "")
        except tk.TclError:
            pass

    def set_command(self, command: Optional[Callable[[], None]]) -> None:
        self._command = command

    def _paint(self, colour: str) -> None:
        for widget in (self, self.icon, self.label, self.arrow):
            try:
                widget.configure(bg=colour)
            except tk.TclError:
                pass

    def _on_enter(self, _event=None) -> None:
        self._paint(theme.BG_HOVER)
        try:
            self.label.configure(fg=theme.FG_BRIGHT)
        except tk.TclError:
            pass

    def _on_leave(self, _event=None) -> None:
        self._paint(self._bg)
        try:
            self.label.configure(fg=self._fg)
        except tk.TclError:
            pass

    def _on_click(self, _event=None) -> None:
        if self._command is not None:
            self._command()


class ChatPanel(tk.Frame):
    """Чат: історія повідомлень, виклики інструментів, поле вводу."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        settings: Settings,
        registry: ToolRegistry,
        *,
        on_status: Optional[Callable[[str], None]] = None,
        on_open_file: Optional[Callable[[str, int], None]] = None,
        on_apply_code: Optional[Callable[[str, str], None]] = None,
        composer_parent: Optional[tk.Misc] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.settings = settings
        self.registry = registry
        self.runner: Optional[AgentRunner] = None
        self.on_open_file = on_open_file
        self.on_status = on_status
        self.on_apply_code = on_apply_code
        self.on_new_chat: Optional[Callable[[], None]] = None
        self.on_queue_task: Optional[Callable[[str], None]] = None
        #: Розбити велике завдання на кроки черги (див. :mod:`planner`).
        self.on_split_task: Optional[Callable[[str], None]] = None
        #: Автоматично розбивати великі завдання на кроки черги.
        self.auto_split: bool = True
        self.on_open_queue: Optional[Callable[[], None]] = None
        self.on_open_skills: Optional[Callable[[], None]] = None
        self.on_busy_change: Optional[Callable[[bool], None]] = None
        self.on_message: Optional[Callable[[str, str], None]] = None
        #: Поточний відкритий файл (для підказок над полем введення).
        self.current_path_provider: Optional[Callable[[], object]] = None
        #: Кожна подія агента (status / tool_call / tool_result / done) —
        #: для панелі «Справи», яка показує роботу крок за кроком.
        self.on_event: Optional[Callable[["AgentEvent"], None]] = None
        #: Новий запит користувача — привід відкрити справу в панелі «Справи».
        self.on_case_start: Optional[Callable[[str], None]] = None
        self.on_permission_change: Optional[Callable[[str], None]] = None
        self.on_set_goal: Optional[Callable[[str], None]] = None
        self.on_feedback: Optional[Callable[[str], None]] = None
        self.on_pick_model: Optional[Callable[[], None]] = None
        self.on_export: Optional[Callable[[], None]] = None
        self.on_use_skill: Optional[Callable[[str], None]] = None
        self.on_model_pick: Optional[Callable[[str], None]] = None
        self.on_voice_query: Optional[Callable[[str], None]] = None
        self.on_voice_action: Optional[Callable[[str], None]] = None
        #: Чи є робоча тека проєкту. Поки ``False``, чат не надсилає запитів:
        #: без теки агент правив би файли в домашній теці користувача.
        #: Оболонка підключає сюди ``self.has_project``.
        self.project_ready: Optional[Callable[[], bool]] = None
        #: Екран вибору теки треба показати замість чату (оболонка малює його).
        self.on_need_project: Optional[Callable[[], None]] = None
        #: Крок ПЕРЕД відправкою запиту — оболонка піднімає модель, якщо її
        #: вивантажив простій. Без цього кожен запит після 5 хв паузи падав
        #: із «модель недоступна» (реальний лог: старт 19:03, вивантаження
        #: 19:08, помилка 19:10 — модель «не стартувала», хоч стартувала).
        self.before_send: Optional[Callable[[], None]] = None
        #: Назва чату змінилась — оболонка оновлює заголовок сесії.
        self.on_title_change: Optional[Callable[[str], None]] = None
        self.speak_last: bool = False
        self.on_effort_pick: Optional[Callable[[str], None]] = None
        #: Пігулка «робочий простір» над полем вводу: оболонка показує меню
        #: тек і застосовує вибір через ``set_workspace``.
        self.on_workspace_menu: Optional[Callable[["_ComposerPill"], None]] = None
        #: Пігулка «режим» над полем вводу: оболонка показує меню режимів.
        self.on_mode_menu: Optional[Callable[["_ComposerPill"], None]] = None
        self.chat_model: str = ""
        self.chat_effort: str = effort.DEFAULT_EFFORT
        self._model_menu = None
        self.permission_mode: str = permissions.WORKSPACE
        self.plan_mode: bool = False
        self._menu = None
        self._menu_mode = ""
        self._events_after: Optional[str] = None
        self._composer_parent = composer_parent
        self._title_text: str = ""

        self.transcript = Transcript()
        self._pending_code: dict[str, str] = {}
        self._cards: list[tk.Frame] = []
        self._busy = False
        self._spinner_index = 0
        self._spin_after: Optional[str] = None
        self._tool_rows: dict[str, tk.Frame] = {}
        #: Журнал роботи поточної відповіді (згорнутий блок «Аналіз запиту»).
        self._log: Optional[work_log.WorkLog] = None
        self._log_card: Optional[tk.Frame] = None
        #: Живий вивід моделі (стрімінг): шматки тексту й тимчасова картка.
        self._stream_parts: list[str] = []
        self._stream_reasoning: list[str] = []
        self._stream_dirty = False
        self._stream_widget: Optional[tk.Text] = None
        self._stream_card: Optional[tk.Frame] = None
        #: Рендерер тимчасової картки стріму: текст форматується одразу,
        #: а не «сирим» до кінця генерації (див. _flush_stream).
        self._stream_renderer: Optional[markdown_view.MarkdownRenderer] = None
        #: Етапи, які агент побудував із кадру наміру (подія ``plan_step``).
        self._agent_plan_stages: list[task_plan.Stage] = []
        #: Останній власний запит користувача — для «редагувати» й «повторити».
        self._last_user_text: str = ""
        self._pending_role: Optional[tuple[str, str]] = None
        #: True, поки малюється збережена історія — тоді нічого не пишемо назад.
        self._replaying = False
        #: True, поки висоти карток вимірюються пакетом, а не по одній.
        self._batch_fits = False
        #: Тексти, чию висоту треба дорахувати пакетом (див. _fit_text).
        self._pending_fits: list[tuple[tk.Text, int]] = []
        #: Помилки озвучення з фонового потоку → головний потік.
        self._speech_errors: "queue.Queue[str]" = queue.Queue()
        self._body_lines = _DEFAULT_BODY_LINES
        #: Запобіжник для справді великих текстів (див. _HARD_TEXT_LINES).
        self._hard_line_limit = _HARD_TEXT_LINES
        #: Режим глибокого аналізу: картка сеансу й прапорець «не вмикати».
        self.deep_card: Optional[deep_view.DeepCard] = None
        self._deep_card_holder: Optional[tk.Frame] = None
        self.deep_enabled: bool = True
        #: Ціль поточної сесії (блок «Поточна ціль» у картці аналізу).
        self.current_goal: str = ""
        self._build()
        self._poll_events()
        # Ширина колонки змінюється — підписи мають переноситись заново.
        self.feed.bind("<Configure>", self._on_feed_resize, add="+")

    def _on_feed_resize(self, _event=None) -> None:
        """Оновити перенос у підписах, що мають фіксований wraplength.

        Тексти карток теж переносяться заново: на вужчому вікні рядків стає
        більше, і без перерахунку низ відповіді обрізався б (висота
        лишалась від широкої розкладки).
        """
        width = self._wrap_width()
        if width == getattr(self, "_last_wrap", 0):
            return
        self._last_wrap = width
        for card in self._cards:
            label = getattr(card, "wrap_label", None)
            if label is not None:
                try:
                    label.configure(wraplength=width)
                except tk.TclError:
                    pass
            widget = getattr(card, "text_widget", None)
            if widget is not None:
                try:
                    if widget.winfo_exists():
                        self._apply_fit(widget, getattr(card, "max_lines",
                                                        self._body_lines))
                except tk.TclError:
                    continue
            # Картка глибокого аналізу має свої підписи з переносом.
            deep = getattr(card, "deep", None)
            if deep is not None:
                try:
                    if deep.winfo_exists():
                        deep.apply_wrap(width - 24)
                except tk.TclError:
                    continue

    # ── сумісність зі старим API ───────────────────────────────────────────
    @property
    def history(self) -> Transcript:
        return self.transcript

    @property
    def input(self) -> tk.Text:
        return self.input_box

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        # Заголовок сесії будує оболонка (він на всю ширину робочої області),
        # але стан («●», назва чату, спінер) живе тут. Ці два підписи —
        # носії стану: оболонка підключає до них свої видимі віджети через
        # :meth:`bind_header`, тож підпис моделі й статус не дублюються.
        self.title_label = tk.Label(self, text="")
        self.status_dot = tk.Label(self, text="●", fg=theme.FG_FAINT)
        self._model_label_text = ""

        # 1. Стрічка повідомлень — на всю ширину колонки діалогу.
        # Раніше вміст стискався до 920 px і центрувався: на широкому
        # моніторі розмова виглядала вузькою смужкою. Тепер ширина не
        # обмежена (0 = зайняти все), а відступи лишились невеликі.
        self.scroll = widgets.ScrollFrame(
            self, bg=theme.BG,
            max_content_width=int(getattr(self.settings.ui, "chat_max_width", 0)
                                  or theme.CHAT_MAX_WIDTH),
            gutter=theme.SPACE_MD,
        )
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.feed = self.scroll.inner
        self._feed_host_container = self.scroll

        # 2. Композер знизу — та сама ширина, що й стрічка.
        parent = getattr(self, "_composer_parent", None)
        self._own_composer = parent is None
        if self._own_composer:
            self.composer_column = widgets.CenteredColumn(
                self, bg=theme.BG_ALT,
                max_width=int(getattr(self.settings.ui, "chat_max_width", 0)
                              or theme.COMPOSER_MAX_WIDTH),
                gutter=theme.SPACE_MD,
            )
            self.composer_column.grid(row=1, column=0, sticky="ew")
            host = self.composer_column.inner
        else:
            host = parent

        self.bottom_box = tk.Frame(host, bg=theme.BG_ALT)
        self.bottom_box.columnconfigure(0, weight=1)

        # 2a. Компактні підказки — один тонкий рядок над полем.
        # Підказка має називати РЕАЛЬНИЙ файл: якщо нічого не відкрито,
        # агент отримував «поясни відкритий файл» без жодного шляху й
        # відповідав «локальна модель недоступна» замість корисної дії.
        quick = tk.Frame(self.bottom_box, bg=theme.BG_ALT)
        quick.grid(row=0, column=0, sticky="ew", padx=(theme.SPACE_SM, theme.SPACE_SM),
                   pady=(0, theme.SPACE_SM))
        for text, prompt in (
            ("Поясни файл",
             "Поясни, що робить файл {file}. Спершу прочитай його інструментом read_file."),
            ("Знайди помилки",
             "Перевір файл {file} на помилки та ризики. Спершу прочитай його."),
            ("Додай тести", "Додай unit-тести для файлу {file} й запусти їх."),
            ("Рефакторинг", "Запропонуй і зроби безпечний рефакторинг файлу {file}."),
        ):
            chip = widgets.Chip(quick, text, lambda p=prompt: self._send_quick(p),
                                font=("Segoe UI", 9))
            chip.pack(side="left", padx=(0, theme.SPACE_SM))

        # 2a2. Черга завдань — компактний список над полем вводу.
        # Раніше черга жила окремою панеллю в сайдбарі: щоб побачити, що
        # агент виконуватиме далі, треба було піти з чату. Тепер вона тут,
        # під рукою, і показує лише найважливіше.
        self.queue_strip = _QueueStrip(self.bottom_box, self.fonts)
        self.queue_strip.grid(row=1, column=0, sticky="ew", padx=theme.SPACE_SM,
                              pady=(0, theme.SPACE_SM))

        # 2a3. Етапи поточної задачі — там само, над композером: людина
        # бачить поділ великого завдання й те, на чому агент зараз стоїть,
        # не йдучи з поля вводу.
        self.stage_strip = stage_strip.StageStrip(self.bottom_box, self.fonts)
        self.stage_strip.grid(row=2, column=0, sticky="ew", padx=theme.SPACE_SM,
                              pady=(0, theme.SPACE_SM))
        self.stage_strip.on_open = self._open_stage_details

        # 2a4. Глибоке мислення — ОКРЕМА зона над формою, не в стрічці чату.
        # Раніше картка аналізу росла в чаті й витісняла форму вводу за
        # екран; користувач просив: «глибоке мислення має бути над формою
        # для вводу тексту ... а чат окремо зробити».
        self.thought_box = tk.Frame(self.bottom_box, bg=theme.BG_ALT)
        self.thought_box.grid(row=3, column=0, sticky="ew", padx=theme.SPACE_SM,
                              pady=(0, theme.SPACE_XS))
        self.thought_box.grid_remove()
        self._thought_label = tk.Label(
            self.thought_box, text="", bg=theme.BG_ALT, fg=theme.FG_DIM,
            font=("Segoe UI", 8), anchor="w", justify="left", wraplength=900)
        self._thought_label.pack(fill="x", padx=(2, 2))

        # 2b. Сам композер: одна компактна картка, без «стіни» на весь екран.
        composer = widgets.Card(self.bottom_box, bg=theme.BG_INPUT, border=theme.BORDER_SOFT)
        composer.grid(row=4, column=0, sticky="ew", padx=theme.SPACE_SM, pady=(0, 0))
        self.composer_card = composer
        box = composer.inner
        box.columnconfigure(0, weight=1)

        # 2b0. Дві пігулки над полем — робочий простір і режим роботи агента.
        #
        # Раніше теку й режим можна було змінити лише з шапки або з меню
        # проєкту. У роботі ж потрібно бачити й перемикати їх ТАМ, ДЕ ПИШЕШ
        # задачу: людина дивиться на поле вводу, а не на шапку. Пігулки
        # показують реальний стан (теку проєкту й режим), а натискання
        # віддають колбекам оболонки — самі вони нічого не міняють.
        # Ряди картки композера (саме в цьому порядку):
        #   0 — пігулки «робочий простір ▾» і «режим ▾»
        #   1 — поле вводу
        #   2 — рядок дій (＋, /, дозволи, модель, черга, голос, надіслати)
        #   3 — підказка під полем
        self.space_row = tk.Frame(box, bg=theme.BG_INPUT)
        self.space_row.grid(row=0, column=0, sticky="ew",
                            padx=(theme.SPACE_MD, theme.SPACE_MD),
                            pady=(theme.SPACE_SM, 0))
        self.space_row.columnconfigure(2, weight=1)

        self.workspace_btn = _ComposerPill(
            self.space_row, self.fonts, icon="🗂", text="теку не обрано",
            command=self._open_workspace_menu,
            tip="Робочий простір: тека, у якій агент працює з файлами")
        self.workspace_btn.grid(row=0, column=0, sticky="w")

        self.mode_btn = _ComposerPill(
            self.space_row, self.fonts, icon="◈", text="Агент",
            command=self._open_mode_menu,
            tip="Режим роботи агента: чат / агент / код / план / інструменти")
        self.mode_btn.grid(row=0, column=1, sticky="w", padx=(theme.SPACE_SM, 0))

        self.input_box = tk.Text(
            box, height=2, width=30, wrap="word", bd=0, highlightthickness=0,
            background=theme.BG_INPUT, foreground=theme.FG, insertbackground=theme.FG_BRIGHT,
            font=self.fonts.chat, padx=theme.SPACE_LG, pady=theme.SPACE_MD,
            spacing1=1, spacing3=2,
        )
        self.input_box.grid(row=1, column=0, sticky="ew", padx=1, pady=(2, 0))
        self.input_box.bind("<Return>", self._on_return)
        self.input_box.bind("<Shift-Return>", lambda _e: None)
        self.input_box.bind("<Control-Return>", lambda _e: (self._send_from_box(), "break")[1])
        # Стандартні комбінації редагування. Без них Ctrl+A не виділяв текст,
        # і нове завдання дописувалося в кінець попереднього (перевірено:
        # п'ять окремих реплік склеїлись в одне повідомлення на 3324 символи).
        self.input_box.bind("<Control-a>", self._select_all)
        self.input_box.bind("<Control-A>", self._select_all)
        self.input_box.bind("<Control-c>", lambda _e: self._clip_copy())
        self.input_box.bind("<Control-v>", self._clip_paste)
        self.input_box.bind("<Control-x>", lambda _e: self._clip_cut())
        self.input_box.bind("<<Modified>>", self._on_input_modified)

        #: Підказка в полі введення БІЛЬШЕ не вставляється як текст.
        #:
        #: Раніше ``_show_placeholder`` писав рядок усередину ``Text``, і
        #: користувач бачив «Напиши задачу агенту…» як звичайний вміст:
        #: курсор стояв усередині цього тексту, Backspace не працював,
        #: редагування йшло «крізь» підказку. Тепер підказку показує
        #: окремий ``hint_label`` під формою (``_refresh_hint``), а поле
        #: введення завжди містить рівно те, що набрав користувач.
        self._placeholder = ""
        self._placeholder_on = False
        #: Рядок-підказка під композером. Він НЕ перехоплює події мишею
        #: (``takefocus=0``, без cursor="hand2"), тому не заважає ставити
        #: курсор у поле введення.
        self.hint_label = tk.Label(
            box, text="", bg=theme.BG_INPUT, fg=theme.FG_FAINT,
            font=("Segoe UI", 8), anchor="w", justify="left",
        )
        self.hint_label.grid(row=3, column=0, sticky="ew",
                             padx=(theme.SPACE_LG, theme.SPACE_MD),
                             pady=(0, theme.SPACE_SM))
        self._refresh_hint()

        tools_row = tk.Frame(box, bg=theme.BG_INPUT)
        tools_row.grid(row=2, column=0, sticky="ew", padx=(theme.SPACE_MD, theme.SPACE_MD),
                       pady=(0, theme.SPACE_MD))
        tools_row.columnconfigure(3, weight=1)

        widgets.IconButton(tools_row, "＋", self._attach_file, bg=theme.BG_INPUT, fg=theme.FG_DIM,
                           font=("Segoe UI", 11), tooltip="Додати файл до запиту").grid(
            row=0, column=0, padx=(0, theme.SPACE_XS))

        # Кнопка слэш-команд: відкриває меню «/файл, /ціль, /план…»
        self.commands_btn = tk.Label(
            tools_row, text="/", bg=theme.BG_INPUT, fg=theme.FG_DIM,
            font=("Segoe UI", 11, "bold"), padx=6, cursor="hand2",
        )
        self.commands_btn.grid(row=0, column=1, padx=(theme.SPACE_XS, theme.SPACE_SM))
        self.commands_btn.bind("<Button-1>", lambda _e: self.toggle_command_menu())
        widgets.Tip(self.commands_btn, "Команди (/) — файл, ціль, план, дозвіл…")

        # Перемикач режиму дозволів.
        self.permission_label = tk.Label(
            tools_row, text="", bg=theme.BG_INPUT, fg=theme.FG_FAINT,
            font=("Segoe UI", 8), padx=theme.SPACE_SM, pady=3, cursor="hand2",
        )
        self.permission_label.grid(row=0, column=2, padx=(0, theme.SPACE_SM))
        self.permission_label.bind("<Button-1>", lambda _e: self.toggle_permission_menu())
        widgets.Tip(self.permission_label,
                    "Режим дозволів: лише читання / запис у робочій області / повний доступ")

        # Кнопка вибору моделі (праворуч, разом із рештою дій).
        self.model_button = tk.Label(
            tools_row, text="", bg=theme.BG_INPUT, fg=theme.FG_DIM,
            font=("Segoe UI", 8), padx=theme.SPACE_SM, pady=3, cursor="hand2",
        )
        self.model_button.grid(row=0, column=3, sticky="e", padx=(0, theme.SPACE_SM))
        self.model_button.bind("<Button-1>", lambda _e: self.toggle_model_menu())
        widgets.Tip(self.model_button, "Модель і зусилля для цієї розмови")

        self.mode_label = tk.Label(tools_row, text="Черга: 0", bg=theme.BG_INPUT, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8), cursor="hand2")
        self.mode_label.grid(row=0, column=4, sticky="e", padx=(0, theme.SPACE_SM))
        self.mode_label.bind("<Button-1>", lambda _e: self.on_open_queue and self.on_open_queue())

        self.queue_btn = widgets.IconButton(tools_row, "≡", self._queue_current, bg=theme.BG_INPUT,
                                            fg=theme.FG_DIM, font=("Segoe UI", 11),
                                            tooltip="Додати в чергу завдань")
        self.queue_btn.grid(row=0, column=5, padx=(0, theme.SPACE_XS))

        self.stop_btn = widgets.IconButton(tools_row, "■", self.stop, bg=theme.BG_INPUT,
                                           fg=theme.FG_DIM, font=("Segoe UI", 9),
                                           tooltip="Зупинити агента")
        self.stop_btn.grid(row=0, column=6, padx=(0, theme.SPACE_XS))

        # Голосове керування: кнопка мікрофона.
        self.voice_settings = voice.VoiceSettings()
        self.voice_btn = voice_panel.VoiceButton(
            tools_row, self.fonts, settings=self.voice_settings,
            on_text=self._on_voice_text, on_status=self._note,
            bg=theme.BG_INPUT,
        )
        self.voice_btn.grid(row=0, column=8, padx=(theme.SPACE_XS, 0))

        self.send_btn = widgets.IconButton(tools_row, "↑", self._send_from_box, bg=theme.ACCENT,
                                           fg=theme.ON_ACCENT, font=("Segoe UI", 10),
                                           tooltip="Надіслати (Enter)")
        self.send_btn.grid(row=0, column=7)

        # 2c. Смуга статистики контексту — тонкий рядок під композером.
        # Рядок 4, а не 3: композер зайняв row=3, і два віджети в одній
        # комірці grid накладались — поле вводу зникало з екрана.
        self.stats_bar = stats_bar.StatsBar(self.bottom_box, self.fonts, bg=theme.BG_ALT)
        self.stats_bar.grid(row=5, column=0, sticky="ew", padx=theme.SPACE_SM,
                           pady=(2, theme.SPACE_LG))

        # Композер у зовнішньому контейнері (для тестів і вбудовування).
        if not self._own_composer:
            self.bottom_box.pack(fill="x", expand=False)
            try:
                self.bottom_box.pack_propagate(True)
            except tk.TclError:
                pass

        # Показати поточний режим дозволів і модель одразу після побудови.
        self._paint_permission_label()
        self._paint_model_button()

        self._welcome()
        # Вузька колонка — приховуємо другорядні підписи, щоб не тіснити поле.
        self.bottom_box.bind("<Configure>", self._on_composer_resize, add="+")

    def _on_composer_resize(self, event=None) -> None:
        """Адаптивний рядок інструментів композера.

        У вузькій колонці підписи «режим доступу» й «модель» не вміщаються й
        наїжджають на кнопки. Показуємо їх лише тоді, коли є місце, а
        головне — поле вводу й кнопки — лишається завжди.
        """
        width = 0
        if event is not None and getattr(event, "width", 0):
            width = int(event.width)
        else:
            try:
                width = self.bottom_box.winfo_width()
            except tk.TclError:
                return
        if width <= 1:
            return
        compact = width < 560
        if compact == getattr(self, "_composer_compact", None):
            return
        self._composer_compact = compact
        for widget in (getattr(self, "permission_label", None),
                       getattr(self, "model_button", None)):
            if widget is None:
                continue
            try:
                if compact:
                    widget.grid_remove()
                else:
                    widget.grid()
            except tk.TclError:
                continue

    # ── стрічка ────────────────────────────────────────────────────────────
    def _welcome(self) -> None:
        card = _MessageCard(self.feed, self.fonts, "ПОРАДА", accent=theme.ACCENT)
        card.pack(fill="x", padx=2, pady=(2, 4))
        label = tk.Label(
            card.content,
            text=("Готовий до роботи. Опиши задачу — я прочитаю файли, внесу зміни "
                  "й перевірю результат.\nБез запущеної моделі працює вбудований "
                  "роутер команд («покажи файли», «дерево проєкту»)."),
            bg=theme.BG_CARD, fg=theme.FG_DIM, font=self.fonts.ui_small, justify="left",
            wraplength=self._wrap_width(),
        )
        label.pack(anchor="w")
        card.wrap_label = label  # type: ignore[attr-defined]
        self._cards.append(card)

    def _wrap_width(self) -> int:
        """Ширина тексту в картках — за фактичною шириною стрічки.

        Стрічка живе в обмеженій колонці (``max_content_width``), тому
        беремо ширину ``feed``, а не панелі: інакше довгі рядки обрізались
        би на правому краї. Мінімум 220 px лишає текст читабельним навіть
        у вузькому вікні.
        """
        width = 0
        for candidate in (self.feed, getattr(self.scroll, "canvas", None), self):
            try:
                if candidate is not None and candidate.winfo_exists():
                    width = candidate.winfo_width()
            except tk.TclError:
                width = 0
            if width > 40:
                break
        if width <= 40:
            width = self.settings.ui.chat_width
        return max(220, width - theme.SPACE_XL * 2)

    def _new_card(self, role: str, accent: str = theme.FG_DIM,
                  bg: str = theme.BG_CARD) -> _MessageCard:
        card = _MessageCard(self.feed, self.fonts, role, accent=accent, bg=bg)
        card.pack(fill="x", padx=2, pady=(2, 6))
        self._cards.append(card)
        self._trim_cards()
        return card

    def _trim_cards(self, limit: int = 120) -> None:
        # Під час відтворення історії ліміт має вмістити весь показаний
        # «хвіст», інакше щойно створені картки одразу знищуються.
        if self._replaying:
            limit = max(limit, HISTORY_RENDER_LIMIT)
        while len(self._cards) > limit:
            card = self._cards.pop(0)
            try:
                card.destroy()
            except tk.TclError:
                pass

    def _trim_to_height(self, budget: int) -> None:
        """Прибрати найстаріші картки, щоб стрічка вмістилась у ``budget``.

        Canvas у Tk має межу координат: нижче ~24 000 px вміст просто не
        малюється, хоч ``bbox`` й ``scrollregion`` рапортують його повним.
        Довга розмова (десятки тисяч пікселів) через це показувала порожній
        низ — саме там, де відповідь агента. Тому тримаємо сумарну висоту
        карток у межах ліміту, відрізаючи найстаріші.

        Висоти карток беруться з layout, який щойно завершився; якщо його
        ще немає (віджети створені, але не виміряні), висоту оцінюємо за
        вмістом тексту, щоб обрізання не «проскочило» повз мету.
        """
        if budget <= 0 or not self._cards:
            return

        def card_height(card) -> int:
            actual = card.winfo_height()
            estimated = card.winfo_reqheight()
            best = max(actual, estimated)
            if best > 4:
                return best
            # Ще не виміряно — рахуємо за текстом.
            widget = getattr(card, "text_widget", None)
            if widget is None:
                return 60
            try:
                content = widget.get("1.0", "end-1c")
                lines = int(widget.cget("height") or 1)
            except tk.TclError:
                return 60
            line_px = 20
            return max(40, lines * line_px + 45)

        heights = [card_height(card) for card in self._cards]
        total = sum(heights)
        removed = 0
        while total > budget and len(self._cards) > 1:
            self._cards.pop(0)
            total -= heights.pop(0)
            card = None
            removed += 1
        # Видаляємо з екрана стільки ж найстаріших карток.
        children = [child for child in self.feed.winfo_children()
                    if child.winfo_class() == "Frame"]
        for card in children[:removed]:
            try:
                card.destroy()
            except tk.TclError:
                pass
        if removed:
            self._note("Показано останні повідомлення — старіші лишились у сховищі.")

    def _body_text(self, card: _MessageCard, text: str, *, tag_colour: str = theme.FG,
                   font=None) -> tk.Text:
        widget = tk.Text(
            card.content, wrap="word", height=1, width=1, bd=0, highlightthickness=0,
            background=card._bg, foreground=tag_colour, insertbackground=theme.FG_BRIGHT,
            font=font or self.fonts.chat, padx=0, pady=0, spacing1=2, spacing3=3,
            state="disabled", cursor="arrow", selectbackground=theme.SELECTION,
        )
        widget.pack(fill="x")
        widget.configure(state="normal")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        self._track_text(card, widget, max_lines=self._body_lines)
        self._fit_text(widget)
        return widget

    def _track_text(self, card: _MessageCard, widget: tk.Text, *, max_lines: int) -> None:
        """Запам'ятати текст картки, щоб перерахувати висоту при зміні ширини."""
        try:
            card.text_widget = widget  # type: ignore[attr-defined]
            card.max_lines = max_lines  # type: ignore[attr-defined]
        except tk.TclError:
            pass

    def _measure_width(self, widget: tk.Text | None = None) -> int:
        """Ширина в пікселях, за якою рахувати перенос рядків.

        Віджет, який ще не брав участі в layout, має ширину 1 px. Якщо
        покладатись на неї, кожен символ вважається окремим рядком і
        коротка відповідь «розтягується» до ліміту в 60–80 рядків — стрічка
        показує порожнечу замість тексту. Тому беремо реальну ширину, коли
        вона вже є, інакше — ширину стрічки.
        """
        try:
            pixels = widget.winfo_width() if widget is not None else 0
        except tk.TclError:
            pixels = 0
        if pixels <= 4:
            pixels = self._wrap_width()
        return max(80, int(pixels))

    def _estimate_lines(self, text: str, pixel_width: int) -> int:
        """Скільки екранних рядків займе текст за заданої ширини.

        Рахуємо перенос по словах метриками шрифту, не чекаючи layout:
        ``count("displaylines")`` залежить від фактичної ширини віджета, а
        під час відтворення історії її ще немає. Слово, довше за рядок,
        Tk переносить по символах — це теж враховано, інакше довгі шляхи й
        base64-рядки обрізались би знизу.
        """
        try:
            font = self.fonts.chat
            measure = font.measure
        except (AttributeError, tk.TclError):
            measure = lambda value: len(value) * 8  # noqa: E731 - запасний шлях
        width = max(1, int(pixel_width))
        try:
            space = max(0, int(measure(" ")))
            char_px = max(1, int(measure("0")))
        except (tk.TclError, TypeError):
            space, char_px = 8, 8
        total = 0
        for paragraph in (text or "").split("\n"):
            if not paragraph:
                total += 1
                continue
            line_width = 0
            lines = 1
            for word in paragraph.split(" "):
                try:
                    word_width = int(measure(word))
                except (tk.TclError, TypeError):
                    word_width = len(word) * char_px
                # Слово довше за рядок переноситься по символах.
                if word_width > width:
                    if line_width:
                        lines += 1
                        line_width = 0
                    lines += (word_width - 1) // width
                    line_width = word_width % width or width
                    continue
                if line_width and line_width + space + word_width > width:
                    lines += 1
                    line_width = word_width
                else:
                    line_width += (space if line_width else 0) + word_width
            total += lines
        return max(1, total)

    def _fit_text(self, widget: tk.Text, max_lines: int = 0) -> None:
        """Підігнати висоту тексту під вміст.

        ``update_idletasks()`` на кожній картці дорогий: tkinter щоразу
        перераховує layout усієї стрічки, тож N карток коштують O(N²) і
        довга розмова «зависає» при відкритті. Тому під час пакетного
        малювання (``_batch_fits``) вимір відкладається й робиться один раз
        у :meth:`_flush_pending_fits`.
        """
        limit = int(max_lines or 0) or self._body_lines
        if self._batch_fits:
            self._pending_fits.append((widget, limit))
            return
        self._apply_fit(widget, limit)

    def _apply_fit(self, widget: tk.Text, max_lines: int = 0) -> None:
        """Виставити висоту віджета за фактичною кількістю рядків.

        Раніше висота обрізалась на ``max_lines`` (12–70 залежно від екрана),
        і все, що не вміщалось, ховалось у **власній прокрутці** віджета —
        саме та смуга й з'являлась між відповідями агента. Тепер текст
        показується повністю: висота дорівнює всьому вмісту.

        ``max_lines`` лишається параметром сумісності: якщо передано
        додатне число, воно діє як запобіжник від справді величезних
        текстів (сотні рядків), але типово не задається.
        """
        try:
            text = widget.get("1.0", "end-1c")
        except tk.TclError:
            return
        count = self._estimate_lines(text, self._measure_width(widget))
        limit = int(max_lines or 0) or self._hard_line_limit
        try:
            widget.configure(height=max(1, min(count + 1, limit)))
            # Власна прокрутка віджета не потрібна: вся стрічка і так
            # прокручується цілком.
            if self._text_has_yscroll(widget):
                widget.configure(yscrollcommand="")
        except tk.TclError:
            pass

    @staticmethod
    def _text_has_yscroll(widget: tk.Text) -> bool:
        """Чи ввімкнено у віджета власну вертикальну прокрутку."""
        try:
            return bool(str(widget.cget("yscrollcommand") or "").strip())
        except tk.TclError:
            return False

    def _flush_pending_fits(self) -> None:
        """Порахувати висоти всіх відкладених текстів (без зайвого layout)."""
        pending, self._pending_fits = self._pending_fits, []
        for widget, max_lines in pending:
            try:
                if not widget.winfo_exists():
                    continue
            except tk.TclError:
                continue
            self._apply_fit(widget, max_lines)

    def _scroll_to_end(self) -> None:
        # Прокрутка — це повний перерахунок layout полотна; під час
        # відтворення історії достатньо одного разу в кінці.
        if self._replaying:
            return
        try:
            self.scroll.sync_scrollregion()
            self.scroll.canvas.update_idletasks()
            self.scroll.canvas.yview_moveto(1.0)
        except tk.TclError:
            pass

    # ── сервіс ─────────────────────────────────────────────────────────────
    def attach_runner(self, runner: AgentRunner) -> None:
        self.runner = runner

    def set_model_label(self, text: str) -> None:
        """Показати активну модель у рядку композера (запасний шлях)."""
        limit = 28
        shown = text if len(text) <= limit else text[: limit - 1] + "…"
        self._model_label_text = shown
        if not self.chat_model:
            try:
                self.model_button.configure(text=f"⊟ {shown}" if text else "модель не вибрана",
                                            fg=theme.FG_DIM if text else theme.FG_FAINT)
            except (tk.TclError, AttributeError):
                pass

    def set_online(self, online: bool, detail: str = "") -> None:
        try:
            self.status_dot.configure(fg=theme.SUCCESS if online else theme.ERROR)
        except (tk.TclError, AttributeError):
            pass
        if detail and self.on_status:
            self.on_status(detail)

    def set_context_limit(self, limit: int) -> None:
        """Розмір вікна контексту моделі — для відсотка заповнення."""
        try:
            self.stats_bar.set_limit(limit)
        except (tk.TclError, AttributeError):
            pass

    def set_max_lines(self, lines: int) -> None:
        """Скільки рядків показувати в одній відповіді (адаптивно до екрана).

        Картки вже намальовані — перераховуємо їхню висоту, інакше на
        меншому екрані відповідь обрізалась би там, де лишала місце на
        більшому.
        """
        limit = max(6, int(lines or 0) or _DEFAULT_BODY_LINES)
        if limit == self._body_lines:
            return
        self._body_lines = limit
        for card in list(self._cards):
            widget = getattr(card, "text_widget", None)
            if widget is None:
                continue
            try:
                if widget.winfo_exists():
                    self._apply_fit(widget, limit)
                    card.max_lines = limit
            except tk.TclError:
                continue

    def set_queue_count(self, count: int, tasks=None) -> None:
        """Оновити підпис і компактний список черги над полем вводу."""
        text = "Черга: 0" if count <= 0 else f"Черга: {count}"
        try:
            self.mode_label.configure(text=text,
                                      fg=theme.FG_FAINT if count <= 0 else theme.ACCENT)
        except (tk.TclError, AttributeError):
            pass
        strip = getattr(self, "queue_strip", None)
        if strip is not None:
            try:
                strip.update_from(
                    tasks if tasks is not None else (),
                    on_open=lambda: self.on_open_queue and self.on_open_queue())
            except (tk.TclError, AttributeError):
                pass

    # ── пігулки композера: робочий простір і режим ─────────────────────────
    def set_workspace(self, name: str, *, path: str = "") -> None:
        """Показати реальну теку проєкту на пігулці над полем вводу.

        Порожня назва — це «теку не обрано», а не порожня пігулка: інакше
        користувач не розуміє, чому агент відмовляється працювати.
        """
        button = getattr(self, "workspace_btn", None)
        if button is None:
            return
        shown = (name or "").strip()
        text = shown if shown else "теку не обрано"
        if len(text) > 34:
            text = text[:33] + "…"
        button.set_text(text, accent=bool(shown))
        button.set_command(self._open_workspace_menu)
        button._body_tip = str(path or "")  # для діагностики й тестів
        try:
            widgets.Tip(button.icon, str(path) if path else "Робочий простір не вибрано")
        except tk.TclError:
            pass

    def set_mode(self, label: str, *, icon: str = "◈", accent: bool = True) -> None:
        """Показати поточний режим роботи агента на пігулці."""
        button = getattr(self, "mode_btn", None)
        if button is None:
            return
        button.set_icon(icon)
        button.set_text(label or "Агент", accent=accent)
        button.set_command(self._open_mode_menu)

    def _open_workspace_menu(self) -> None:
        callback = self.on_workspace_menu
        if callback is None:
            if self.on_status:
                self.on_status("Меню робочого простору недоступне.")
            return
        safe.call_quiet(callback, self.workspace_btn, where="меню робочого простору")

    def _open_mode_menu(self) -> None:
        callback = self.on_mode_menu
        if callback is None:
            if self.on_status:
                self.on_status("Меню режимів недоступне.")
            return
        safe.call_quiet(callback, self.mode_btn, where="меню режимів")

    def stop(self) -> None:
        if self.runner and self.runner.busy:
            self.runner.cancel()
            self._note("Агента зупинено користувачем.")
            self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.configure(fg=theme.FG_FAINT if busy else theme.ON_ACCENT)
        if busy:
            self._start_spinner()
        else:
            self._stop_spinner()
            self.send_btn.configure(bg=theme.ACCENT, fg=theme.ON_ACCENT)
        if self.on_busy_change:
            safe.call_quiet(self.on_busy_change, busy, where="оновлення стану агента")

    def _start_spinner(self) -> None:
        if self._spin_after is not None:
            return
        frames = "◐◓◑◒"

        def tick() -> None:
            self._spinner_index = (self._spinner_index + 1) % len(frames)
            try:
                self.status_dot.configure(text=frames[self._spinner_index], fg=theme.ACCENT)
                self._spin_after = self.after(220, tick)
            except tk.TclError:
                self._spin_after = None

        self.status_dot.configure(text="◐", fg=theme.ACCENT)
        self._spin_after = self.after(220, tick)

    def _stop_spinner(self) -> None:
        if self._spin_after is not None:
            try:
                self.after_cancel(self._spin_after)
            except (tk.TclError, ValueError):
                pass
            self._spin_after = None
        try:
            self.status_dot.configure(text="●")
        except tk.TclError:
            pass

    def new_chat(self) -> None:
        if self.runner:
            self.runner.reset()
        self._clear_work_log()
        self._pending_code.clear()
        self._tool_rows.clear()
        self._pending_fits.clear()
        for card in self._cards:
            try:
                card.destroy()
            except tk.TclError:
                pass
        self._cards.clear()
        self.transcript.clear()
        self.set_busy(False)
        self.stats_bar.reset()
        try:
            self.scroll.sync_scrollregion()
            self.scroll.canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        self._welcome()
        self._note("Новий чат. Історія попереднього діалогу очищена.")
        if self.on_new_chat:
            self.on_new_chat()

    def _clear_work_log(self) -> None:
        """Відчепити журнал роботи (перед очищенням стрічки)."""
        if self._log is not None:
            try:
                self._log.stop_timers()
            except tk.TclError:
                pass
        self._log = None
        self._log_card = None
        # Картка глибокого аналізу теж належить стрічці: її таймер має
        # зупинитись, інакше після очищення він смикає знищені віджети.
        card = self.deep_card
        self.deep_card = None
        self._deep_card_holder = None
        self._planner_queue = None
        if card is not None:
            try:
                card.stop_timers()
            except tk.TclError:
                pass
        # Стан стріму теж належить стрічці — інакше новий чат починався б
        # із залишками попередньої відповіді.
        self._stream_parts.clear()
        self._stream_reasoning.clear()
        self._stream_dirty = False
        self._stream_widget = None
        self._stream_card = None
        self._stream_renderer = None
        # План належить стрічці: новий чат не має починатись із етапів
        # попереднього завдання.
        self._agent_plan_stages = []

    def reset(self) -> None:
        """Очистити стрічку без повідомлень (для перемикання чатів)."""
        if self.runner:
            self.runner.reset()
        self._clear_work_log()
        self._pending_code.clear()
        self._tool_rows.clear()
        self._pending_fits.clear()
        for card in self._cards:
            try:
                card.destroy()
            except tk.TclError:
                pass
        self._cards.clear()
        self.transcript.clear()
        self.set_busy(False)
        if getattr(self, "stats_bar", None) is not None:
            self.stats_bar.reset()
        # Порожня стрічка має «схлопнутись» одразу: інакше полотно лишається
        # висотою попередньої довгої розмови й новий чат відкривається в її
        # низу — екран виглядає порожнім.
        try:
            self.scroll.sync_scrollregion()
            self.scroll.canvas.yview_moveto(0.0)
        except tk.TclError:
            pass

    def show_history(self, messages) -> None:
        """Показати збережений чат у стрічці.

        Малювання історії не має права писати в сховище: інакше кожне
        відкриття чату додає його ж повідомлення назад, файл росте, а
        наступне відкриття стає довшим. Тому тут ``_replaying = True``.
        """
        self.reset()
        if not messages:
            self._welcome()
            return
        items = list(messages)
        skipped = 0
        if len(items) > HISTORY_RENDER_LIMIT:
            skipped = len(items) - HISTORY_RENDER_LIMIT
            items = items[-HISTORY_RENDER_LIMIT:]
        self._replaying = True
        self._batch_fits = True
        try:
            if skipped:
                self._note(f"Показано останні {len(items)} повідомлень із "
                           f"{len(items) + skipped}. Старіші лишились у сховищі.")
            for message in items:
                role = getattr(message, "role", "")
                text = getattr(message, "text", "") or ""
                if not text.strip():
                    continue
                if role == "user":
                    card = self._new_card(ROLE_USER, accent=theme.CHAT_USER, bg=theme.BG_CARD)
                    self._body_text(card, text, tag_colour=theme.FG_BRIGHT)
                    self.transcript.add(f"\n{ROLE_USER}\n{text}\n")
                elif role == "assistant":
                    self._add_assistant(text)
                elif role == "tool":
                    self._note(text)
        finally:
            self._replaying = False
            self._batch_fits = False
        self._flush_pending_fits()
        # Canvas у Tk не малює вміст, що лежить нижче ~24 000 px: без
        # обрізання низ довгої розмови виглядав порожнім. Лишаємо стільки
        # останніх карток, щоб стрічка вмістилась у межу полотна.
        self._trim_to_height(self.scroll.MAX_CANVAS_HEIGHT)
        self._scroll_to_end()

    def set_title(self, title: str) -> None:
        """Підпис поточного чату в заголовку панелі."""
        text = (title or "Новий чат")
        self._title_text = text
        try:
            self.title_label.configure(text=text.upper()[:40])
        except (tk.TclError, AttributeError):
            pass
        # Оболонка малює власний заголовок — повідомляємо її про зміну.
        callback = getattr(self, "on_title_change", None)
        safe.call_quiet(callback, text, where="оновлення заголовка сесії")

    def bind_header(self, title_label: tk.Label, status_dot: tk.Label) -> None:
        """Підключити видимі віджети заголовка з оболонки.

        Так стан чату (назва, спінер, доступність моделі) показується в
        заголовку сесії, не створюючи другої копії цих підписів.
        """
        self.title_label = title_label
        self.status_dot = status_dot
        try:
            self.title_label.configure(text=(getattr(self, "_title_text", "") or "").upper()[:40])
        except (tk.TclError, AttributeError):
            pass

    # ── винесення частин у зовнішні контейнери ────────────────────────────
    def detach(self, feed_host: tk.Misc, composer_host: tk.Misc) -> None:
        """Розмістити розмову й композер у зовнішніх контейнерах.

        Віджети не можна переносити між батьками в tkinter, тому композер
        створюється одразу в наданому контейнері, а стрічка розмови лишається
        на місці — вікно кладе саму панель чату в центр.
        """
        self._detached = True
        self._feed_host = feed_host
        self._composer_host = composer_host

    def mount_composer(self) -> None:
        """Перекласти композер у зовнішній контейнер (якщо він заданий)."""
        host = getattr(self, "_composer_host", None)
        if host is None:
            return
        self.bottom_box.grid(in_=host, row=0, column=0, sticky="ew")
        try:
            host.columnconfigure(0, weight=1)
        except tk.TclError:
            pass

    @property
    def composer_host(self) -> tk.Frame:
        """Контейнер композера (для вікна)."""
        return self.bottom_box

    @property
    def feed_host(self) -> "widgets.ScrollFrame":
        """Стрічка розмови (для вікна)."""
        return self.scroll

    # ── голос ──────────────────────────────────────────────────────────────
    def _on_voice_text(self, result) -> None:
        """Обробити розпізнане мовлення: команда або запит агенту."""
        if not getattr(result, "ok", False):
            return
        text = (getattr(result, "text", "") or "").strip()
        if not text:
            return
        text = voice.strip_wake_word(text)

        action, label = voice.parse_command(text)
        if action:
            self._handle_voice_action(action)
            self._note(f"Голосова команда: {label}")
            return

        if self.on_voice_query is not None:
            # Колбек нічого не повертає: успіх означає «оброблено, далі не йдемо».
            marker = object()
            done = safe.call(self.on_voice_query, text, where="голосовий запит",
                             default=marker)
            if done is not marker:
                return
        self.set_text(text)
        if self.voice_settings.auto_send:
            self._send_from_box()

    def _handle_voice_action(self, action: str) -> None:
        """Виконати голосову команду."""
        if action == "stop":
            self.stop()
        elif action == "new_chat":
            self.new_chat()
        elif action in ("files", "terminal") and self.on_voice_action:
            self.on_voice_action(action)
        elif action == "queue" and self.on_open_queue:
            self.on_open_queue()
        elif action == "skills" and self.on_open_skills:
            self.on_open_skills()
        elif action == "speak":
            self.speak_last = True
            self._note("Наступну відповідь буде озвучено.")
        elif action == "mute":
            self.speak_last = False
            self.voice_settings.speak_replies = False
            self._note("Озвучення вимкнено.")
        elif action == "help":
            self._note(voice_commands_text())

    def speak_text(self, text: str) -> None:
        """Озвучити текст у фоні.

        Помилку озвучення повертаємо через чергу: викликати ``after()`` з
        фонового потоку не можна — Tk реєструє команду в інтерпретаторі й
        падає з «main thread is not in main loop».
        """
        body = (text or "").strip()
        if not body:
            return
        import threading

        def work() -> None:
            ok, detail = voice.speak(voice.clean_for_speech(body))
            if not ok:
                self._speech_errors.put(detail)

        threading.Thread(target=work, daemon=True).start()
        self._drain_speech_errors()

    def _drain_speech_errors(self) -> None:
        """Головний потік: показати помилки озвучення з черги."""
        shown = False
        while True:
            try:
                detail = self._speech_errors.get_nowait()
            except queue.Empty:
                break
            self._note(f"Озвучення не вдалось: {detail}")
            shown = True
        if not shown:
            return

    # ── меню моделі для поточного чату ─────────────────────────────────────
    def _ensure_model_menu(self) -> "model_menu.ModelMenu":
        if getattr(self, "_model_menu", None) is None:
            self._model_menu = model_menu.ModelMenu(
                self, self.fonts,
                on_pick_model=self._on_model_picked,
                on_pick_effort=self._on_effort_picked,
            )
            self._model_menu.bind("<Escape>", lambda _e: self._model_menu.back())
        return self._model_menu

    def set_available_models(self, models: list[str]) -> None:
        """Оновити список моделей, доступних для вибору."""
        self._available_models = list(models or [])
        self._paint_model_button()

    def set_chat_model(self, model: str, effort_key: str = "") -> None:
        """Показати модель і зусилля, збережені для цього чату."""
        self.chat_model = (model or "").strip() or self.chat_model
        if effort_key:
            self.chat_effort = effort.normalise(effort_key)
        self._paint_model_button()

    def _paint_model_button(self) -> None:
        """Напис кнопки: «модель · зусилля» (компактно, як у заголовку)."""
        model = self.chat_model or "модель"
        limit = 22
        short = model if len(model) <= limit else model[: limit - 1] + "…"
        level = effort.get(self.chat_effort)
        text = f"⊟ {short}"
        if not level.is_default:
            text += f" · {level.label.lower()}"
        try:
            self.model_button.configure(text=text)
        except (tk.TclError, AttributeError):
            pass

    def toggle_model_menu(self) -> None:
        menu = self._ensure_model_menu()
        if menu.visible:
            menu.close()
            return
        models = list(getattr(self, "_available_models", []) or [])
        if self.chat_model and self.chat_model not in models:
            models.insert(0, self.chat_model)
        menu.show_root(self.chat_model, self.chat_effort, models)
        menu.place_above(self.input_box)
        self.input_box.focus_set()

    def _on_model_picked(self, name: str) -> None:
        self.chat_model = name
        self._paint_model_button()
        safe.call_quiet(self.on_model_pick, name, where="вибір моделі")
        self._note(f"Модель для цього чату: {name}")

    def _on_effort_picked(self, key: str) -> None:
        self.chat_effort = effort.normalise(key)
        self._paint_model_button()
        safe.call_quiet(self.on_effort_pick, self.chat_effort,
                        where="вибір зусилля моделі")
        self._note(f"Зусилля: {effort.label_for(self.chat_effort)} — "
                   f"{effort.get(self.chat_effort).hint}")

    # ── меню команд і режим дозволів ───────────────────────────────────────
    def _ensure_menu(self) -> "command_menu.CommandMenu":
        if getattr(self, "_menu", None) is None:
            self._menu = command_menu.CommandMenu(self, self.fonts, on_choose=self._on_menu_choice)
            command_menu.attach_keys(self._menu, self.input_box)
        return self._menu

    def toggle_command_menu(self) -> None:
        menu = self._ensure_menu()
        if menu.visible and self._menu_mode == "commands":
            menu.close()
            return
        self._menu_mode = "commands"
        menu.show_commands("")
        menu.place_above(self.input_box)
        self.input_box.focus_set()

    def toggle_permission_menu(self) -> None:
        menu = self._ensure_menu()
        if menu.visible and self._menu_mode == "permissions":
            menu.close()
            return
        self._menu_mode = "permissions"
        menu.show_permissions(self.permission_mode)
        menu.place_above(self.input_box)
        self.input_box.focus_set()

    def _on_menu_choice(self, payload) -> None:
        if isinstance(payload, str) and payload in permissions.MODES:
            self.set_permission_mode(payload)
            return
        command = payload
        if isinstance(command, slash_commands.SlashCommand):
            self._run_slash_command(command, "")

    def _paint_permission_label(self) -> None:
        """Намалювати поточний режим дозволів у композері.

        Підпис повний («Запис у робочій області») — він і є джерелом істини
        для користувача й тестів. Вузький рядок композера не є проблемою:
        підпис стоїть ліворуч і не стискається.
        """
        active = self.permission_mode
        try:
            self.permission_label.configure(
                text=f"{permissions.icon_for(active)} {permissions.label_for(active)}",
                fg=theme.WARN if active == permissions.FULL else (
                    theme.FG_DIM if active == permissions.WORKSPACE else theme.FG_FAINT),
            )
        except (tk.TclError, AttributeError):
            pass

    def set_permission_mode(self, mode: str) -> None:
        """Змінити режим дозволів і показати це в композері."""
        active = permissions.normalise_mode(mode)
        self.permission_mode = active
        self._paint_permission_label()
        safe.call_quiet(self.on_permission_change, active,
                        where="зміна режиму дозволів")
        self._note(f"Режим дозволів: {permissions.label_for(active)}. "
                   f"{permissions.hint_for(active)}")

    # ── виконання слэш-команд ──────────────────────────────────────────────
    def _run_slash_command(self, command: "slash_commands.SlashCommand", argument: str) -> bool:
        """Виконати команду. Повертає True, якщо текст був командою."""
        name = command.name
        if name == "файл":
            self._attach_file()
        elif name == "ціль":
            if not argument:
                self.set_text("/ціль ")
                self._note("Опиши ціль після команди: /ціль переписати парсер")
                return True
            if self.on_set_goal:
                self.on_set_goal(argument)
            self._note(f"Ціль встановлено: {argument}")
        elif name == "план":
            self.start_plan_mode()
        elif name == "відгук":
            if not argument:
                self.set_text("/відгук ")
                self._note("Напиши відгук після команди.")
                return True
            if self.on_feedback:
                self.on_feedback(argument)
            self._note("Дякую! Відгук збережено.")
        elif name == "стиснути":
            self.compact_history()
        elif name == "дозвіл":
            if argument:
                mode = permissions.normalise_mode(argument)
                # normalise_mode тихо повертає «workspace» для сміття, тому
                # перевіряємо, чи аргумент справді схожий на режим.
                if _looks_like_mode(argument):
                    self.set_permission_mode(mode)
                    return True
                self._note("Невідомий режим. Доступні: read-only, workspace, full "
                           "(або лише читання, робоча, повний).")
                return True
            self.toggle_permission_menu()
        elif name == "модель":
            if self.on_pick_model:
                self.on_pick_model()
            self._note("Вибір моделі — у рядку над чатом.")
        elif name == "експорт":
            if self.on_export:
                self.on_export()
        elif name == "скіли":
            if self.on_open_skills:
                self.on_open_skills()
            self._note("Скіли агента — у бічній панелі.")
        elif name == "скіл":
            if not argument:
                self.set_text("/скіл ")
                self._note("Назви скіл: /скіл tests")
                return True
            if self.on_use_skill:
                self.on_use_skill(argument)
            self._note(f"Скіл «{argument}» надіслано агенту.")
        elif name == "стоп":
            self.stop()
        elif name == "очистити":
            self.new_chat()
        elif name == "допомога":
            self._note(slash_commands.help_text())
        return True

    def start_plan_mode(self) -> None:
        """Режим планування: агент спершу складає план, без правок файлів."""
        self.plan_mode = True
        self.set_permission_mode(permissions.READ_ONLY)
        prompt = ("Склади детальний план реалізації цієї задачі кроками. "
                  "Файли поки не змінюй — спершу узгодь план зі мною.")
        self._note("Режим плану: агент складе план, файли не змінюються.")
        self._send(prompt)

    def compact_history(self) -> None:
        """Стиснути історію: лишаємо суть, звільняємо контекст."""
        if self.runner is not None:
            self.runner.compact()
        self.stats_bar.reset()
        self._note("Історію стиснуто — контекст звільнено.")

    def _maybe_slash(self) -> bool:
        """Якщо в полі команда — виконати її замість надсилання агенту."""
        text = self._composer_text()
        if not slash_commands.is_slash(text):
            return False
        command, argument = slash_commands.parse(text)
        if command is None:
            self._note(f"Невідома команда. {slash_commands.help_text()}")
            return True
        self._clear_box()
        return self._run_slash_command(command, argument)

    # ── ввід ───────────────────────────────────────────────────────────────
    def _show_placeholder(self) -> None:
        """Показати підказку (тепер — у ``hint_label``, не в полі введення).

        Метод лишено для сумісності: старі виклики не мають нічого ламати.
        """
        self._placeholder_on = False
        self._refresh_hint()

    def _clear_placeholder(self) -> None:
        """Сумісність: раніше прибирав текст-підказку з поля введення.

        Тепер підказка живе окремо, тому очищати в полі нічого — лишається
        відновити нормальний колір тексту (він міг лишитись приглушеним).
        """
        self._placeholder_on = False
        try:
            self.input_box.configure(fg=theme.FG)
        except tk.TclError:
            pass

    def _on_input_modified(self, _event=None) -> None:
        if not self.input_box.edit_modified():
            return
        self.input_box.edit_modified(False)
        self._refresh_hint()

    def _select_all(self, _event=None) -> str:
        """Ctrl+A — виділити весь текст у полі введення."""
        try:
            self.input_box.tag_add("sel", "1.0", "end-1c")
            self.input_box.mark_set("insert", "1.0")
            self.input_box.see("insert")
        except tk.TclError:
            pass
        return "break"

    def _clip_copy(self) -> str:
        """Ctrl+C — скопіювати виділене з поля."""
        try:
            selected = self.input_box.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        try:
            self.clipboard_clear()
            self.clipboard_append(selected)
        except tk.TclError:
            pass
        return "break"

    def _clip_cut(self) -> str:
        """Ctrl+X — вирізати виділене з поля."""
        try:
            selected = self.input_box.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        try:
            self.clipboard_clear()
            self.clipboard_append(selected)
            self.input_box.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    def _clip_paste(self, _event=None) -> str:
        """Ctrl+V — вставити з буфера обміну."""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            if self.input_box.tag_ranges("sel"):
                self.input_box.delete("sel.first", "sel.last")
            self.input_box.insert("insert", text)
        except tk.TclError:
            pass
        return "break"

    def _on_return(self, event) -> str:
        if event.state & 0x0001:  # Shift — новий рядок
            return ""
        # Відкрите меню перехоплює Enter (вибір команди/режиму).
        menu = getattr(self, "_menu", None)
        if menu is not None and menu.visible:
            return menu.choose()
        if self._maybe_slash():
            return "break"
        self._send_from_box()
        return "break"

    def _composer_text(self) -> str:
        if self._placeholder_on:
            return ""
        return self.input_box.get("1.0", "end-1c").strip()

    def _send_from_box(self) -> None:
        if self._maybe_slash():
            return
        text = self._composer_text()
        if not text:
            self.input_box.focus_set()
            return
        self._clear_box()
        self._send(text)

    def set_text(self, text: str) -> None:
        """Покласти текст у поле введення (для команд із аргументом)."""
        self._placeholder_on = False
        self.input_box.configure(fg=theme.FG)
        self.input_box.delete("1.0", "end")
        self.input_box.insert("1.0", text)
        try:
            self.input_box.mark_set("insert", "end-1c")
            self.input_box.focus_set()
        except tk.TclError:
            pass
        self._refresh_hint()

    def rerun(self, text: str = "") -> None:
        """Повторити запит: надіслати той самий текст ще раз."""
        clean = (text or "").strip()
        if not clean:
            self._note("Немає що повторювати.", kind="error")
            return
        if self.runner and self.runner.busy:
            self._note("Зачекай: агент ще виконує попередній запит.", kind="error")
            return
        self._note(f"Повторюю запит: {clean[:80]}")
        self._send(clean)

    def edit_last_message(self) -> None:
        """Взяти останній свій запит назад у поле вводу для правки."""
        text = self._last_user_text or ""
        if not text:
            self._note("Немає попереднього запиту для редагування.")
            return
        self.set_text(text)
        self._note("Запит повернуто в поле — відредагуй і надішли.")

    def insert_context(self, text: str) -> None:
        clean = (text or "").strip()
        if not clean:
            return
        self._clear_placeholder()
        current = self.input_box.get("1.0", "end-1c").strip()
        block = f"```\n{clean}\n```"
        combined = f"{current}\n\n{block}" if current else block
        self.input_box.delete("1.0", "end")
        self.input_box.insert("1.0", combined)
        try:
            self.input_box.mark_set("insert", "end-1c")
            self.input_box.focus_set()
        except tk.TclError:
            pass
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        """Оновити підказку залежно від того, чи поле заповнене."""
        try:
            filled = bool(self.input_box.get("1.0", "end-1c").strip())
            self.hint_label.configure(
                text="" if filled else "Enter — надіслати · Shift+Enter — новий рядок")
        except (tk.TclError, AttributeError):
            pass

    def _clear_box(self) -> None:
        self._placeholder_on = False
        self.input_box.delete("1.0", "end")
        self.input_box.configure(fg=theme.FG)
        self._show_placeholder()

    def _queue_current(self) -> None:
        text = self._composer_text()
        if not text:
            self._note("Напиши задачу, щоб додати її в чергу.")
            return
        if self.on_queue_task:
            self.on_queue_task(text)
            self._clear_box()
            self._note("Задачу додано в чергу.")

    def _send_quick(self, template: str) -> None:
        """Підказка над полем: підставити реальний файл замість «відкритого».

        Якщо файл не відкрито, чесно про це повідомляємо й пропонуємо
        вибрати файл — замість того, щоб надіслати агенту запит без мети.
        """
        path = ""
        provider = getattr(self, "current_path_provider", None)
        if provider is not None:
            try:
                found = provider()
                path = str(found) if found else ""
            except Exception:  # noqa: BLE001 - підказка не має падати
                path = ""
        if not path:
            self._note("Спершу відкрий файл (Ctrl+P або провідник) — тоді підказка "
                       "працюватиме з конкретним файлом.")
            return
        self._send(template.replace("{file}", path))

    def _project_ok(self, text: str = "") -> bool:
        """Чи можна зараз запускати агента: спершу має бути тека проєкту.

        Перевірка стоїть саме тут, у ``_send``, а не лише в кнопках «Новий
        чат»: до агента ведуть ще кілька входів (стартовий екран, голос,
        скіл, черга задач, підказки над полем, ``send_to_agent`` з меню), і
        кожен обходив перевірку. Результат був той самий, що й до появи
        екрана: чат створювався з ``workspace = C:\\Users\\<ім'я>``, і
        перший же ``read_file``/``write_file`` працював у домашній теці.

        Без підключеного ``project_ready`` поводимось як раніше: сама панель
        не знає про налаштування й не має права блокувати роботу в тестах.
        """
        if self.project_ready is None:
            return True
        try:
            ok = bool(self.project_ready())
        except Exception as exc:  # noqa: BLE001 - перевірка не має ламати чат
            safe.record_failure("перевірка теки проєкту", exc)
            return True
        if ok:
            return True
        # Запит не втрачаємо: повертаємо текст у поле, щоб після вибору теки
        # користувач натиснув Enter, а не набирав усе заново.
        if text.strip():
            self.set_text(text)
        safe.call_quiet(self.on_need_project, where="показ екрана вибору теки")
        self._note("Спершу вибери теку проєкту — без неї агенту ніде працювати.",
                   kind="error")
        return False

    def _send(self, text: str, *, deep: Optional[bool] = None,
              plan_step: bool = False) -> bool:
        """Надіслати запит агенту. Повертає ``True``, якщо робота СПРАВДІ почалась.

        ``deep`` керує режимом глибокого аналізу: ``None`` — вирішити
        самостійно за текстом, ``False`` — не вмикати (так робить черга
        задач: там задачі вже дрібні й розписані, а план лише гальмував би
        виконання), ``True`` — увімкнути примусово.

        ``plan_step=True`` означає «це вже готовий крок плану»: розбивати
        його НЕ можна. Раніше крок із черги містив загальну мету, текст
        перевищував поріг ``is_big_task``, і замість виконання запускалось
        НОВЕ планування — рекурсія, у якій агент не робив жодної файлової
        дії, а інтерфейс показував «аналіз» назавжди.

        Значення, що повертається, принципове для черги: якщо запит НЕ
        стартував (агент ще зайнятий, теки немає), виконавець має одразу
        повернути крок у чергу. Інакше крок «висів» би в стані «аналіз»
        назавжди — саме це й виглядало як зависання моделі.
        """
        text = (text or "").strip()
        if not text:
            return False
        if not self.runner:
            self._note("Агент ще не ініціалізований.", kind="error")
            return False
        if self.runner.busy:
            self._note("Зачекай: агент ще виконує попередній запит.", kind="error")
            return False
        if not self._project_ok(text):
            return False
        # ── Модель могла бути вивантажена простоєм ─────────────────────────
        # Перевіряємо ПЕРЕД стартом роботи: якщо модель пішла з пам'яті,
        # оболонка підніме її, і запит не впаде з «модель недоступна».
        safe.call_quiet(self.before_send, where="підйом моделі перед запитом")
        # Етапи показуємо ОДРАЗУ, до будь-якого розгалуження: людина має
        # бачити поділ задачі навіть тоді, коли далі йде глибокий аналіз
        # або черга. Розбиття локальне (без моделі), тож затримки не додає.
        self._show_local_stages(text)
        # Велике завдання розбиваємо на кроки автоматично — без жодних
        # команд. Користувач просто пише, чого хоче, як замовник.
        # Готовий крок плану НЕ розбиваємо: його вже виділила модель, і
        # повторне планування перетворювалось би на нескінченну рекурсію.
        if (not plan_step) and self.auto_split and planner.is_big_task(text):
            if self.on_split_task:
                card = self._new_card(ROLE_USER, accent=theme.CHAT_USER, bg=theme.BG_CARD)
                self._body_text(card, text, tag_colour=theme.FG_BRIGHT)
                self.transcript.add(f"\n{ROLE_USER}\n{text}\n")
                self._remember("user", text)
                self._last_user_text = text
                self._scroll_to_end()
                self.on_split_task(text)
                # Планування почалося — це теж «робота запущена».
                return True
        card = self._new_card(ROLE_USER, accent=theme.CHAT_USER, bg=theme.BG_CARD)
        self._body_text(card, text, tag_colour=theme.FG_BRIGHT)
        self._last_user_text = text
        # Дії над власним запитом: скопіювати, повторити, відредагувати.
        card.add_action("↺", lambda t=text: self.rerun(t), "Повторити запит")
        card.add_action("✎", lambda t=text: self.set_text(t), "Редагувати запит")
        card.add_action("⧉", lambda t=text: self._copy(t), "Копіювати запит")
        self.transcript.add(f"\n{ROLE_USER}\n{text}\n")
        self._remember("user", text)
        safe.call_quiet(self.on_case_start, text, where="відкриття справи")
        self.set_busy(True)
        # Складна задача: спершу показати в чаті аналіз і план, і лише потім
        # почати роботу. План складає :meth:`_plan_deep` у фоні.
        #
        # Для готового кроку плану глибокий аналіз ВИМКНЕНО завжди: крок
        # уже виділений моделлю, і повторне планування всередині кроку
        # давало рекурсію замість роботи.
        want_deep = False if plan_step else (
            self._deep_wanted(text) if deep is None else bool(deep))
        if want_deep:
            self.begin_deep(text)
        self._scroll_to_end()
        if want_deep:
            self._plan_deep(text)
            return True
        return self._start_with_stages(text, fresh=plan_step)

    # ── етапи задачі ───────────────────────────────────────────────────────
    def _arrow_thought(self, text: str, *, show: bool = True) -> None:
        """Показати/сховати рядок «глибокого мислення» над формою.

        Думки агента живуть окремою тонкою зоною, а не в стрічці чату:
        інакше вони розтягують стрічку й витісняють поле вводу за екран.
        """
        clean = " ".join((text or "").split())
        try:
            if show and clean:
                shown = clean if len(clean) <= 200 else clean[:199] + "…"
                self._thought_label.configure(text="◔ " + shown)
                self.thought_box.grid()
            elif not show:
                self.thought_box.grid_remove()
        except (tk.TclError, AttributeError):
            pass

    def _show_agent_plan(self, event: AgentEvent) -> None:
        """Показати план агента в смузі етапів над композером.

        Подія приходить по одному кроку, тож етапи накопичуються: перша
        подія починає нову смугу, наступні додаються. Так модель і людина
        бачать ТУ САМУ структуру, а не два різні плани.
        """
        index = int(event.data.get("index") or 0)
        total = int(event.data.get("total") or 0)
        if index <= 1:
            self._agent_plan_stages = []
        stages = self._agent_plan_stages
        tools = tuple(str(item) for item in
                      (event.data.get("tools") or []) if str(item))
        stages.append(task_plan.Stage(
            text=str(event.text or f"Крок {index}"),
            index=max(1, index),
            state=task_plan.STAGE_PENDING,
            tools=tools,
        ))
        if len(stages) != total and total > 0:
            return
        # Усі кроки зібрано — показуємо смугу й позначаємо перший як активний.
        try:
            self.stage_strip.set_stages(stages, goal=self._last_user_text)
            self.stage_strip.update_stage(stages[0].index,
                                          task_plan.STAGE_RUNNING)
        except tk.TclError:
            pass

    def _show_local_stages(self, text: str) -> list[task_plan.Stage]:
        """Показати етапи задачі над композером (розбиття без моделі).

        Смуга починається з нової задачі, а не з попередньої. Один етап не
        показуємо: смуга з єдиним рядком «те саме, що я написав» лише
        забирала б місце над полем вводу.
        """
        self.stage_strip.clear()
        stages = task_plan.split_into_stages(text)
        if len(stages) > 1:
            self.stage_strip.set_stages(stages, goal=text)
        return stages

    def _start_with_stages(self, text: str, *, fresh: bool = False) -> bool:
        """Почати роботу з підказкою про доречні інструменти.

        Навіщо: агент бере не той інструмент, коли бачить усі 19 одразу.
        Тут до запиту додається перелік доречних — модель обирає серед них.

        ``fresh=True`` — почати з чистої історії (крок черги: він має бути
        незалежним запитом, а не продовженням попереднього кроку).

        Повертає ``True``, якщо агент справді прийняв запит.
        """
        stages = self.stage_strip.stages or task_plan.split_into_stages(text)
        self._stage_tools = task_plan.tools_for_intents(
            task_plan.understand(text).intents)
        hint = task_plan.tools_hint(self._stage_tools)
        prompt = f"{text}\n\n{hint}" if hint else text
        if stages:
            self.stage_strip.update_stage(stages[0].index,
                                          task_plan.STAGE_RUNNING)
        return bool(self.runner.start(prompt, fresh=fresh))

    def advance_stage(self, *, ok: bool = True) -> None:
        """Позначити поточний етап виконаним і перевести наступний у роботу."""
        stages = self.stage_strip.stages
        if not stages:
            return
        current = self.stage_strip.running_index()
        if current < 0:
            current = next((s.index for s in stages if not s.settled), -1)
        if current < 0:
            return
        self.stage_strip.update_stage(
            current, task_plan.STAGE_DONE if ok else task_plan.STAGE_FAILED)
        following = next((s.index for s in stages
                          if s.index > current and not s.settled), -1)
        if following >= 0:
            self.stage_strip.update_stage(following, task_plan.STAGE_RUNNING)

    def finish_stages(self, *, ok: bool = True) -> None:
        """Завершити всі етапи (хід агента закінчився)."""
        for stage in self.stage_strip.stages:
            if stage.running:
                self.stage_strip.update_stage(
                    stage.index,
                    task_plan.STAGE_DONE if ok else task_plan.STAGE_FAILED)

    def _open_stage_details(self) -> None:
        """Клік по смузі етапів — показати повний список у «Справах»."""
        safe.call_quiet(self.on_case_start, self._last_user_text or "Етапи задачі",
                        where="відкриття справи зі смуги етапів")

    def _plan_deep(self, text: str) -> None:
        """Скласти план у фоні, показати його й аж тоді почати роботу.

        План — окремий короткий запит до моделі. Якщо модель недоступна або
        не дала кроків, агент усе одно стартує: краще працювати без плану,
        ніж не працювати зовсім. Причину показуємо наративом у картці.
        """
        settings = getattr(self, "settings", None)
        llm = getattr(settings, "llm", None)
        if llm is None or not str(getattr(llm, "model", "") or "").strip():
            self._deep_narration("Модель не вибрана — працюю без плану, одразу дією.")
            self._start_with_stages(text)
            return
        self._planner_queue: "queue.Queue[tuple[list[str], str]]" = queue.Queue()
        # Тека проєкту: без неї модель планує «взагалі» й вигадує чужий
        # стек (перевірено наживо: на Tkinter-проєкт пропонувала HTML/CSS/JS).
        root = getattr(self, "_workspace_root", None)

        def work() -> None:
            steps, error = deep_mode.plan_tasks(text, llm, root=root)
            self._planner_queue.put((steps, error))

        threading.Thread(target=work, daemon=True).start()
        self._poll_planner(text)

    def _poll_planner(self, text: str) -> None:
        """Дочекатись плану в головному потоці й запустити агента."""
        pending = getattr(self, "_planner_queue", None)
        if pending is None:
            return
        try:
            steps, error = pending.get_nowait()
        except queue.Empty:
            try:
                if self._timer_alive():
                    self.after(150, lambda: self._poll_planner(text))
            except tk.TclError:
                pass
            return
        self._planner_queue = None
        if steps:
            self.set_deep_plan(steps)
        else:
            reason = f" ({error[:80]})" if error else ""
            self._deep_narration(f"План не склався{reason} — починаю одразу з роботи.")
        # Агент стартує, щойно план на екрані: спершу перша задача плану.
        stages = self.stage_strip.stages
        if stages:
            self.stage_strip.update_stage(stages[0].index,
                                          task_plan.STAGE_RUNNING)
        self._start_with_stages(text)

    def _remember(self, role: str, text: str) -> None:
        """Зберегти повідомлення в історію чатів (якщо підключено).

        Під час відтворення збереженої історії запис заборонений: інакше
        кожне відкриття чату дублює його ж повідомлення у ``chats.json``.
        """
        if self._replaying:
            return
        if self.on_message is None or not (text or "").strip():
            return
        # Збій збереження історії має бути ВИДНО: інакше повідомлення
        # зникає з пам'яті без жодного сліду.
        safe.call(self.on_message, role, text, where="збереження історії чату",
                  on_error=self._note)

    # ── події агента ───────────────────────────────────────────────────────

    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _poll_events(self) -> None:
        if self.runner:
            try:
                # Стрімінг сипле багато дрібних подій — обробляємо з запасом,
                # інакше черга росте швидше, ніж ми її читаємо.
                for _ in range(400):
                    event = self.runner.events.get_nowait()
                    self._handle_event(event)
            except queue.Empty:
                pass
        self._flush_stream()
        try:
            if self._timer_alive():
                self._events_after = self.after(90, self._poll_events)
        except tk.TclError:
            self._events_after = None

    def cancel_events(self) -> None:
        """Скасувати відкладене опитування подій агента."""
        job = getattr(self, "_events_after", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._events_after = None

    def _handle_event(self, event: AgentEvent) -> None:
        # Панель «Справи» має бачити кожну подію — навіть ту, яку стрічка
        # чату лише побіжно згадує. Збій підписника не має ламати чат,
        # але й не повинен зникати безслідно.
        safe.call_quiet(self.on_event, event, where="панель справ")
        if event.kind == "assistant":
            self._add_assistant(event.text, offline=bool(event.data.get("offline")),
                                final=bool(event.data.get("final", True)))
        elif event.kind == "reasoning":
            # Думки моделі: у журнал роботи (він згорнутий) І коротким
            # рядком у зону над формою. Друга гілка `reasoning` нижче була
            # недосяжною — Python зупиняється на першому збігу, тож
            # `_arrow_thought` для думок не викликався взагалі.
            self._add_reasoning(event.text)
            self._arrow_thought(event.text, show=True)
        elif event.kind == "token":
            self._on_token(event.text)
        elif event.kind == "reasoning_token":
            self._on_reasoning_token(event.text)
        elif event.kind == "tool_call":
            self._add_tool_call(event)
        elif event.kind == "tool_result":
            self._add_tool_result(event)
        elif event.kind == "status":
            self._add_status(event.text)
            if self.on_status:
                self.on_status(event.text)
            # «Працює…» — короткий стан у зоні мислення над формою.
            self._arrow_thought(event.text, show=bool(event.text))
        elif event.kind == "plan_step":
            # Агент побудував план із кадру наміру (без моделі). Показуємо
            # його тією самою смугою етапів, що й розбиття задачі: людина
            # має бачити, з чого складається робота, ще до першого виклику.
            self._show_agent_plan(event)
        elif event.kind == "stats":
            stats = event.data.get("step_stats")
            if stats is not None:
                self.stats_bar.set_stats(stats)
        elif event.kind == "error":
            self._note(event.text, kind="error")
            self.end_deep(ok=False)
        elif event.kind == "done":
            ok = bool(event.data.get("ok", True))
            self._finish_work_log(ok=ok)
            self.end_deep(ok=ok)
            # Хід завершився — етап, що був у роботі, отримує підсумок.
            # Без цього спінер крутився б вічно після останньої відповіді.
            self.finish_stages(ok=ok)
            # Зона мислення більше не потрібна — приховуємо, щоб не
            # забирала місце над полем вводу.
            self._arrow_thought("", show=False)
            self.set_busy(False)
            self._scroll_to_end()

    # ── стрімінг ───────────────────────────────────────────────────────────
    def _on_token(self, piece: str) -> None:
        """Шматок тексту від моделі — накопичуємо для живого показу."""
        if not piece:
            return
        self._stream_parts.append(piece)
        self._stream_dirty = True

    def _on_reasoning_token(self, piece: str) -> None:
        """Шматок роздумів — у журнал роботи, у міру надходження."""
        if not piece:
            return
        self._stream_reasoning.append(piece)
        self._stream_dirty = True

    def _flush_stream(self) -> None:
        """Показати накопичений стрім (виклик із циклу подій, не з потоку).

        Текст під час генерації малюється ТИМ САМИМ рендерером, що й
        фінальна відповідь. Раніше тут був простий ``insert`` — і поки
        модель писала, користувач бачив сирий markdown (``**…**``, ```),
        а після завершення все різко переформатовувалось. Тепер
        форматування стабільне від першого токена.

        Незакритий блок коду — звичайний стан стріму: ``parse_markdown``
        уже вважає його кодом до кінця тексту, тож блок не «стрибає».
        """
        if not self._stream_dirty:
            return
        self._stream_dirty = False
        text = "".join(self._stream_parts)
        thought = "".join(self._stream_reasoning)
        if thought:
            log = self._work_log()
            if log is not None:
                try:
                    log.set_live_reasoning(thought)
                except (tk.TclError, AttributeError):
                    pass
        if not text:
            return
        widget = self._stream_widget
        if widget is None:
            # Перший шматок: створюємо картку відповіді й пишемо в неї.
            self._finish_work_log(ok=True)
            card = self._new_card(ROLE_AGENT, accent=theme.CHAT_OK, bg=theme.BG_CARD)
            widget = tk.Text(
                card.content, wrap="word", height=1, width=1, bd=0,
                highlightthickness=0, background=card._bg, foreground=theme.FG,
                insertbackground=theme.FG_BRIGHT, font=self.fonts.chat,
                padx=0, pady=0, spacing1=2, spacing3=3, cursor="arrow",
                selectbackground=theme.SELECTION,
            )
            widget.pack(fill="x")
            widget.configure(state="normal")
            self._stream_widget = widget
            self._stream_card = card
            self._stream_renderer = markdown_view.MarkdownRenderer(
                widget, self.fonts, self._palette())
            try:
                self._stream_renderer.configure_tags()
            except tk.TclError:
                self._stream_renderer = None
        renderer = getattr(self, "_stream_renderer", None)
        try:
            if renderer is not None:
                # ``clear=False`` неможливий: перемальовуємо з нуля, інакше
                # теги накладаються на старий текст і код «пливе».
                renderer.render(text, clear=True)
            else:
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
            # Під час стрімінгу теж без обмеження: текст має рости, а не
            # обрізатись у власну прокрутку.
            self._fit_text(widget)
        except tk.TclError:
            self._stream_widget = None
            self._stream_renderer = None
            return
        self._scroll_to_end()

    def _end_stream(self, final_text: str = "") -> str:
        """Завершити стрім: прибрати тимчасову картку й віддати повний текст."""
        collected = "".join(self._stream_parts)
        text = (final_text or collected).strip()
        self._stream_parts.clear()
        self._stream_reasoning.clear()
        self._stream_dirty = False
        card = self._stream_card
        self._stream_card = None
        self._stream_widget = None
        self._stream_renderer = None
        if card is not None:
            # Тимчасова картка теж лежить у self._cards — інакше після
            # знищення лишається «мертвий» віджет у списку, і ліміт карток
            # рахує фантоми.
            try:
                self._cards.remove(card)
            except ValueError:
                pass
            try:
                card.destroy()
            except tk.TclError:
                pass
        return text

    @property
    def streaming(self) -> bool:
        """Чи зараз іде живий вивід."""
        return bool(self._stream_parts) or self._stream_card is not None

    def _add_assistant(self, text: str, *, offline: bool = False,
                       final: bool = True) -> None:
        """Відповідь агента.

        Проміжний текст (модель каже, що робитиме далі) — це рядок журналу
        роботи. Фінальна відповідь — окрема картка, як і раніше.

        У режимі глибокого аналізу проміжний текст стає **окремим абзацом у
        картці аналізу**: саме так на скріншоті видно думки агента між
        згортаними блоками.
        """
        if not final and self.deep_active():
            self._deep_narration(text)
            self.transcript.add(f"\n{ROLE_AGENT}\n{text}\n")
            return
        if not final and self._log is not None:
            try:
                if self._log.winfo_exists():
                    self._log.add_narration(text)
                    self.transcript.add(f"\n{ROLE_AGENT}\n{text}\n")
                    self._scroll_to_end()
                    return
            except tk.TclError:
                pass
        # Відповідь показуємо після журналу, тож журнал завершуємо першим.
        # Якщо йшов живий вивід — прибираємо тимчасову картку й беремо
        # повний текст звідти (він уже на екрані, дублювати не треба).
        streamed = self._end_stream(text)
        if streamed and not final:
            final = True
        text = streamed or text
        self._finish_work_log(ok=True)
        role = "АГЕНТ · локальний роутер" if offline else ROLE_AGENT
        card = self._new_card(role, accent=theme.CHAT_OK, bg=theme.BG_CARD)
        self._render_markdown(card, text, key_prefix=f"a{len(self._cards)}")
        self.transcript.add(f"\n{role}\n{text}\n")
        self._remember("assistant", text)
        card.add_action("⧉", lambda t=text: self._copy(t), "Копіювати відповідь")
        card.add_action("⇥", lambda: self._insert_last_code(card), "Вставити код у редактор")
        card.add_action("↺", lambda t=text: self.rerun(t), "Повторити цей запит")
        self._scroll_to_end()

    def _render_markdown(self, card: _MessageCard, text: str, *, key_prefix: str = "") -> None:
        widget = tk.Text(
            card.content, wrap="word", height=1, width=1, bd=0, highlightthickness=0,
            background=card._bg, foreground=theme.FG, insertbackground=theme.FG_BRIGHT,
            font=self.fonts.chat, padx=0, pady=0, spacing1=2, spacing3=3,
            state="normal", cursor="arrow", selectbackground=theme.SELECTION,
        )
        widget.pack(fill="x")
        renderer = markdown_view.MarkdownRenderer(widget, self.fonts, self._palette())
        renderer.configure_tags()
        blocks = renderer.render(text, clear=True)
        # Ті самі блоки коду, але вже як ЧАСТИНИ повідомлення: звідти їх
        # бере «вставити в редактор», і саме вони зберігаються в історії.
        # Раніше індекси рахував рендерер, і будь-яка зміна розбору ламала
        # відповідність «кнопка → код».
        try:
            parts = message_parts.build_parts(text)
            codes = [part.content for part in message_parts.code_parts(parts)]
        except Exception:  # noqa: BLE001 - рендер не має падати через це
            codes = blocks
        for index, code in enumerate(codes or blocks):
            key = f"{key_prefix}:{index}"
            self._pending_code[key] = code
        widget.configure(state="disabled")
        self._track_text(card, widget, max_lines=0)
        # Рендерер запам'ятовуємо: при зміні теми ним же перемальовуємо текст.
        try:
            card.renderer = renderer  # type: ignore[attr-defined]
        except tk.TclError:
            pass
        # Відповідь показуємо ПОВНІСТЮ: жодних власних прокруток усередині
        # картки — інакше між повідомленнями з'являлась смуга прокрутки.
        self._fit_text(widget)
        widget.bind("<Button-3>", lambda e, r=renderer: self._code_menu(e, r, card))

    def _palette(self) -> markdown_view.ChatPalette:
        return markdown_view.ChatPalette(
            fg=theme.FG, fg_dim=theme.FG_DIM, fg_bright=theme.FG_BRIGHT, accent=theme.ACCENT,
            success=theme.SUCCESS, warn=theme.WARN, error=theme.ERROR,
            code_bg=theme.BG_EDITOR, code_fg=theme.ACCENT, border=theme.BORDER,
            bg=theme.BG_CARD, bg_input=theme.BG_INPUT, selection=theme.SELECTION,
        )

    # ── diff-перегляд змін ─────────────────────────────────────────────────
    def _show_diff(self, path: str, old_text: str, new_text: str) -> None:
        """Картка diff у стилі Cursor: заголовок файла + рядки +/−.

        Рядки на зеленому/червоному тлі, службові — приглушені. Блок
        колапсувався, як tool-call: клік по заголовку ховає тіло.
        """
        card = self._new_card("", accent=theme.SUCCESS, bg=theme.BG_CARD)
        try:
            card.role_label.master.pack_forget()
        except (tk.TclError, AttributeError):
            pass
        lines = make_diff_lines(old_text, new_text)
        added = sum(1 for kind, _t in lines if kind == "add")
        removed = sum(1 for kind, _t in lines if kind == "del")
        name = Path(path).name if path else "зміни"

        header = tk.Frame(card.content, bg=theme.BG_CARD, cursor="hand2")
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)
        arrow = tk.Label(header, text="▾", bg=theme.BG_CARD, fg=theme.FG_FAINT,
                         font=("Segoe UI", 8))
        arrow.grid(row=0, column=0, padx=(0, 6))
        tk.Label(header, text=f"diff · {name}", bg=theme.BG_CARD, fg=theme.FG,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(row=0, column=1, sticky="w")
        stats = tk.Label(header, text=f"+{added} −{removed}", bg=theme.BG_CARD,
                         fg=theme.SUCCESS, font=("Segoe UI", 8))
        stats.grid(row=0, column=2, sticky="e")

        body = tk.Frame(card.content, bg=theme.BG_EDITOR, bd=0, highlightthickness=0)
        body.pack(fill="x", pady=(6, 0))
        inner = tk.Frame(body, bg=theme.BG_EDITOR)
        inner.pack(fill="x", padx=1, pady=1)
        mono = self.fonts.mono_small
        for kind, text in lines[:400]:
            if kind == "add":
                bg, fg, sign = theme.DIFF_ADD_BG, theme.DIFF_ADD_FG, "+"
            elif kind == "del":
                bg, fg, sign = theme.DIFF_DEL_BG, theme.DIFF_DEL_FG, "−"
            else:
                bg, fg, sign = theme.BG_EDITOR, theme.FG_FAINT, " "
            row = tk.Frame(inner, bg=bg)
            row.pack(fill="x")
            tk.Label(row, text=sign, bg=bg, fg=fg, font=mono,
                     width=1, anchor="nw").pack(side="left")
            shown = (text or "")[:240]
            tk.Label(row, text=shown, bg=bg, fg=fg, font=mono, anchor="w",
                     justify="left").pack(side="left", fill="x", expand=True)
        if len(lines) > 400:
            tk.Label(inner, text=f"… і ще {len(lines) - 400} рядків", bg=theme.BG_EDITOR,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8)).pack(anchor="w", padx=8, pady=4)

        def toggle(_event=None) -> None:
            try:
                if body.winfo_ismapped():
                    body.pack_forget()
                    arrow.configure(text="▸")
                else:
                    body.pack(fill="x", pady=(6, 0), after=header)
                    arrow.configure(text="▾")
            except tk.TclError:
                pass

        for widget in (header, arrow):
            widget.bind("<Button-1>", toggle)
        self._scroll_to_end()

    def _show_screenshot(self, path: str, caption: str = "") -> None:
        """Вбудований скріншот у стрічці (результат роботи агента).

        Раніше тут вимагався Pillow (``ImageTk``), а його в проєкті не було —
        тож навіть коли знімок існував, користувач бачив лише рядок тексту.
        Тепер:

        * **Tk 8.6+/9** уміє PNG сам (``tk.PhotoImage``) — малюємо напряму;
        * якщо PNG завеликий для Tk, зменшуємо його нашим модулем
          :mod:`screenshot` (без залежностей) і показуємо зменшене;
        * якщо картинку показати не вдалось — чесно кажемо шлях, а не
          мовчимо.
        """
        clean = (path or "").strip().strip("'\"")
        if not clean or not Path(clean).exists():
            return
        try:
            max_width = max(240, self._wrap_width() - 24)
        except (tk.TclError, AttributeError):
            max_width = 480

        photo = self._load_photo(Path(clean), max_width)
        card = self._new_card("", accent=theme.SUCCESS, bg=theme.BG_CARD)
        try:
            card.role_label.master.pack_forget()
        except (tk.TclError, AttributeError):
            pass
        tk.Label(card.content, text=f"⊠ {caption or Path(clean).name}",
                 bg=theme.BG_CARD, fg=theme.FG_DIM,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))
        if photo is None:
            # Не вдалось показати — даємо шлях і кнопку «відкрити».
            row = tk.Frame(card.content, bg=theme.BG_CARD)
            row.pack(anchor="w", pady=(0, 4))
            tk.Label(row, text="Знімок збережено, але показати не вдалось:",
                     bg=theme.BG_CARD, fg=theme.WARN,
                     font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(row, text=str(clean), bg=theme.BG_CARD, fg=theme.FG_FAINT,
                     font=self.fonts.mono_small, wraplength=max_width,
                     justify="left").pack(anchor="w")
            return
        holder = tk.Label(card.content, image=photo, bg=theme.BG_EDITOR,
                          bd=1, relief="solid", cursor="hand2")
        holder.image = photo  # type: ignore[attr-defined] - тримаємо посилання
        holder.pack(anchor="w", padx=1, pady=(0, 4))
        holder.bind("<Button-1>", lambda _e, p=clean: self._open_screenshot(p))
        widgets.Tip(holder, f"{clean} — натисни, щоб відкрити на весь екран")
        self._scroll_to_end()

    def _load_photo(self, path: Path, max_width: int):
        """Завантажити зображення для показу (Tk PhotoImage, без Pillow)."""
        try:
            photo = tk.PhotoImage(file=str(path))
        except tk.TclError as exc:
            LOG.debug("Tk не прочитав зображення: %s", exc, exc_info=True)
            return None
        if photo.width() <= max_width:
            return photo
        # Завелике: зменшуємо через ``subsample`` (цілочисельне зменшення
        # без втрати якості й без бібліотек). Крок 2..8 — достатньо для
        # знімка екрана 4K у колонку чату.
        step = 2
        while step <= 8 and photo.width() // step > max_width:
            step += 1
        if step > 8:
            step = 8
        try:
            return tk.PhotoImage(file=str(path)).subsample(step, step)
        except tk.TclError:
            return photo

    def _open_screenshot(self, path: str) -> None:
        """Показати знімок окремим вікном (на весь екран)."""
        target = Path(str(path))
        if not target.exists():
            self._note(f"Файл знімка вже видалено: {target}")
            return
        try:
            window = tk.Toplevel(self)
            window.title(f"Скріншот · {target.name}")
            window.configure(bg=theme.BG)
            photo = tk.PhotoImage(file=str(target))
            # Обмежуємо розмір вікна екраном.
            scale = 1
            while (photo.width() // scale > window.winfo_screenwidth() - 60
                   or photo.height() // scale > window.winfo_screenheight() - 120):
                scale += 1
                if scale > 8:
                    break
            if scale > 1:
                photo = photo.subsample(scale, scale)
            label = tk.Label(window, image=photo, bg=theme.BG)
            label.image = photo  # type: ignore[attr-defined]
            label.pack(fill="both", expand=True)
            window.bind("<Escape>", lambda _e: window.destroy())
            window.lift()
        except tk.TclError as exc:
            self._note(f"Не вдалось відкрити знімок: {exc}")

    def _code_menu(self, event, renderer, card: _MessageCard) -> None:
        index = self._code_index_at(event, card)
        items: list[tuple[str, Optional[Callable[[], None]]]] = []
        if index is not None:
            code = renderer.get_code(index)
            items.append(("Копіювати код", lambda: self._copy(code or "")))
            items.append(("Вставити в редактор", lambda: self._apply_code(code or "")))
            items.append(("Додати в чат як контекст", lambda: self._quote(code or "")))
            items.append(("", None))
        items.append(("Копіювати всю відповідь", lambda: self._copy(self.transcript.get())))
        widgets.context_menu(self, items, event)

    def _code_index_at(self, event, card: _MessageCard) -> Optional[int]:
        """Номер блоку коду під курсором (за рядком заголовка блоку)."""
        widget = event.widget
        try:
            line = int(widget.index(f"@{event.x},{event.y}").split(".")[0])
        except (tk.TclError, ValueError):
            return None
        headers = [int(index.split(".")[0]) for index in widget.tag_ranges("md_code_header")]
        current: Optional[int] = None
        for order, start in enumerate(headers):
            if start <= line:
                current = order
            else:
                break
        return current

    # ── режим глибокого аналізу ────────────────────────────────────────────
    def _deep_wanted(self, text: str) -> bool:
        """Чи вмикати для цього запиту режим глибокого планування."""
        if not self.deep_enabled:
            return False
        if self.permission_mode == permissions.READ_ONLY and self.plan_mode:
            # Режим «План» і так просить спершу план — не дублюємо картку.
            return False
        return deep_mode.wants_deep_plan(text)

    def begin_deep(self, goal: str) -> Optional[deep_view.DeepCard]:
        """Почати сеанс глибокого аналізу й показати картку в чаті.

        Картка створюється одразу після запиту користувача: далі агент
        дописує в неї свої думки, групи кроків і план — усе на очах.
        """
        self.end_deep()      # попередній сеанс (якщо лишився) — закрити
        self.current_goal = goal
        session = deep_mode.DeepSession(goal=deep_mode.goal_from(goal))
        card = self._new_card("", accent=theme.FG_FAINT, bg=theme.BG_CARD)
        try:
            card.role_label.master.pack_forget()
        except (tk.TclError, AttributeError):
            pass
        widget = deep_view.DeepCard(
            card.content, self.fonts, session,
            wrap_width=self._wrap_width() - 24,
            on_open_result=self._show_full,
        )
        widget.pack(fill="x")
        card.deep = widget  # type: ignore[attr-defined]
        self.deep_card = widget
        self._deep_card_holder = card
        # Картку не наповнюємо штучною думкою: перше справжнє повідомлення
        # агента прийде за мить, а вигаданий рядок лишався б у стрічці
        # назавжди й дублювався з реальним («Розберуся…» двічі).
        self.transcript.add("\n◔ Глибокий аналіз\n")
        self._scroll_to_end()
        return widget

    def set_deep_plan(self, steps) -> None:
        """Показати складений план у картці аналізу."""
        card = self.deep_card
        if card is None:
            return
        try:
            card.set_tasks(steps)
            card.add_narration("План готовий — починаю з першої задачі.")
        except tk.TclError:
            return
        self._scroll_to_end()

    def deep_active(self) -> bool:
        return bool(self.deep_card is not None and self.deep_card.winfo_exists())

    def end_deep(self, *, ok: bool = True) -> None:
        """Закрити сеанс: таймер застигає, задачі отримують фінальний стан."""
        card = self.deep_card
        self.deep_card = None
        self._deep_card_holder = None
        if card is None:
            return
        try:
            if card.winfo_exists():
                card.finish(ok=ok)
        except tk.TclError:
            pass

    def set_goal(self, text: str) -> None:
        """Оновити «Поточну ціль» і в картці аналізу, і для наступних сеансів."""
        self.current_goal = (text or "").strip()
        if self.deep_active():
            try:
                self.deep_card.set_goal(self.current_goal)
            except (tk.TclError, AttributeError):
                pass

    def _deep_tool(self, event: AgentEvent) -> None:
        """Записати виклик інструмента в картку аналізу (якщо вона є)."""
        if not self.deep_active():
            return
        name = str(event.data.get("name") or "")
        arguments = str(event.data.get("arguments") or "")
        try:
            self.deep_card.add_tool(name, work_log._target_of(
                work_log.tool_view(name)[2], arguments))
        except (tk.TclError, AttributeError):
            pass

    def _deep_tool_done(self, event: AgentEvent) -> None:
        if not self.deep_active():
            return
        try:
            self.deep_card.finish_tool(ok=bool(event.data.get("ok")))
        except (tk.TclError, AttributeError):
            pass

    def _deep_narration(self, text: str) -> None:
        """Проміжна думка агента — в картку аналізу."""
        if not self.deep_active():
            return
        try:
            self.deep_card.add_narration(text)
        except (tk.TclError, AttributeError):
            pass
        self._scroll_to_end()

    # ── журнал роботи ──────────────────────────────────────────────────────
    def _work_log(self) -> Optional[work_log.WorkLog]:
        """Поточний журнал роботи (створюється на перший крок)."""
        if self._log is not None:
            try:
                if self._log.winfo_exists():
                    return self._log
            except tk.TclError:
                pass
        card = self._new_card("", accent=theme.FG_FAINT, bg=theme.BG_CARD)
        # Порожній підпис ролі не потрібен — журнал має власний заголовок.
        try:
            card.role_label.master.pack_forget()
        except (tk.TclError, AttributeError):
            pass
        log = work_log.WorkLog(
            card.content, self.fonts, wrap_width=self._wrap_width() - 24,
            on_open_result=self._show_full,
        )
        log.pack(fill="x")
        card.log = log  # type: ignore[attr-defined]
        self._log = log
        self._log_card = card
        log.begin("Аналіз запиту")
        return log

    def _finish_work_log(self, *, ok: bool = True) -> None:
        """Завершити журнал: таймер застигає, крапка стає спокійною."""
        log = self._log
        self._log = None
        if log is None:
            return
        try:
            if log.winfo_exists():
                log.finish(ok=ok)
        except tk.TclError:
            pass

    def _add_reasoning(self, text: str) -> None:
        """Роздуми моделі — у журнал, а не окремою карткою."""
        log = self._work_log()
        if log is None:
            return
        try:
            log.add_reasoning(text)
        except tk.TclError:
            return
        self.transcript.add(f"\n✦ {text}\n")
        self._scroll_to_end()

    def _add_status(self, text: str) -> None:
        """Службовий статус агента — у журнал, без окремих ноток.

        «Запит до <модель>…» не показуємо: це дублює заголовок журналу,
        який і так пульсує «міркую…». Решта статусів (офлайн-режим,
        скасування) лишаються корисними.
        """
        clean = (text or "").strip()
        if not clean:
            return
        if clean.startswith("Запит до ") and clean.endswith("…"):
            self.transcript.add(f"· {clean}\n")
            return
        log = self._work_log()
        if log is None:
            self._note(clean)
            return
        try:
            log.add_row(work_log.KIND_STATUS, "·", clean, colour=theme.FG_FAINT)
        except tk.TclError:
            return
        self.transcript.add(f"· {clean}\n")

    def _add_tool_call(self, event: AgentEvent) -> None:
        # У режимі глибокого аналізу кроки йдуть у згортані групи картки —
        # окремий журнал там зайвий, інакше те саме видно двічі.
        self._deep_tool(event)
        log = None if self.deep_active() else self._work_log()
        call_id = str(event.data.get("call_id") or "")
        if log is None:
            self.transcript.add(f"\n⚙ {event.text}\n")
            return
        try:
            log.add_tool(str(event.data.get("name") or event.text),
                         str(event.data.get("arguments") or ""), call_id=call_id)
        except tk.TclError:
            return
        self.transcript.add(f"\n⚙ {event.text}\n")
        self._scroll_to_end()

    def _add_tool_result(self, event: AgentEvent) -> None:
        ok = bool(event.data.get("ok"))
        call_id = str(event.data.get("call_id") or "")
        name = str(event.data.get("name") or "")
        self._deep_tool_done(event)
        log = self._log
        if log is not None:
            try:
                log.finish_tool(call_id, ok=ok)
            except tk.TclError:
                pass
        body = (event.text or "").strip()
        if not body:
            return
        # ── скріншот: вбудовуємо картинку прямо в стрічку ─────────────────
        # Працює і для знімка вікна (``app_screenshot``), і для знімка
        # СТОРІНКИ через CDP (``web_screenshot``) — обидва повертають шлях
        # до PNG, тож шукаємо будь-який шлях із розширенням .png.
        if name in ("app_screenshot", "web_screenshot", "project_screenshot") and ok:
            match = re.search(r"([A-Za-z]:\\[^\"\n]+?\.png)", body)
            if match:
                captions = {
                    "web_screenshot": "Сторінка проєкту",
                    "project_screenshot": "Вікно проєкту",
                    "app_screenshot": "Вікно застосунку",
                }
                self._show_screenshot(match.group(1), captions.get(name, "Знімок"))
        # ── diff після правки файлу: картка +зелені/−червоні
        if name in ("edit_file", "write_file") and ok:
            self._maybe_show_diff(name, body)
        # Повний результат не захаращує стрічку: він за рядком у журналі
        # й відкривається кліком у вікні «Результат інструмента».
        preview = body if len(body) <= 90 else body[:89] + "…"
        preview = preview.replace("\n", " ")
        if log is not None:
            try:
                log.add_row(
                    work_log.KIND_NOTE, "✓" if ok else "✗", preview,
                    colour=theme.FG_FAINT if ok else theme.ERROR,
                    clickable=body,
                )
            except tk.TclError:
                pass
        self.transcript.add(("✓ " if ok else "✗ ") + body + "\n")
        self._scroll_to_end()

    def _maybe_show_diff(self, tool: str, body: str) -> None:
        """Показати diff файлу після write_file / edit_file.

        Береться попередня версія з ``.bak`` (її кладе ``write_text_file``)
        проти поточного вмісту. Якщо ``.bak`` немає або файл не існує —
        нічого не малюємо.
        """
        match = re.search(r"([A-Za-z0-9_.\-\\/]+\.(?:py|js|ts|tsx|jsx|html|css|md|json|txt|bat|cmd))",
                          body)
        if not match:
            return
        root = getattr(self, "_workspace_root", None) or Path.cwd()
        relative = match.group(1).replace("\\", "/").lstrip("./")
        target = Path(root) / relative
        if not target.exists():
            for candidate in Path(root).rglob(Path(relative).name):
                target = candidate
                break
        if not target.exists():
            return
        try:
            new_text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        backup = Path(str(target) + ".bak")
        if not backup.exists():
            return
        try:
            old_text = backup.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        if old_text == new_text:
            return
        try:
            rel = target.relative_to(root)
        except ValueError:
            rel = target
        self._show_diff(str(rel), old_text, new_text)

    def _show_full(self, text: str) -> None:
        if self.on_apply_code:
            pass
        win = tk.Toplevel(self)
        win.title("Результат інструмента")
        win.configure(bg=theme.BG)
        win.geometry("760x520")
        win.transient(self.winfo_toplevel())
        box = tk.Text(win, wrap="word", bg=theme.BG_EDITOR, fg=theme.FG, bd=0,
                      highlightthickness=0, font=self.fonts.mono_small, padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=8, pady=8)
        box.insert("1.0", text)
        box.configure(state="disabled")
        widgets.Chip(win, "Закрити", win.destroy).pack(anchor="e", padx=10, pady=(0, 10))

    def _note(self, text: str, *, kind: str = "info") -> None:
        colour = {"error": theme.ERROR, "info": theme.FG_FAINT}.get(kind, theme.FG_FAINT)
        row = tk.Label(self.feed, text=("✗ " if kind == "error" else "· ") + text,
                       bg=theme.BG, fg=colour, font=("Segoe UI", 8), anchor="w",
                       justify="left", wraplength=self._wrap_width() - 10)
        row.pack(fill="x", padx=(8, 4), pady=(0, 3))
        self._cards.append(row)
        self.transcript.add(f"· {text}\n")

    # ── сумісність зі старим API ───────────────────────────────────────────
    def _write(self, text: str, tag: str = "") -> None:
        """Старий метод: пише текст як нотатку або повідомлення.

        Виклики йшли парами ``_write("ВИ", "user_role")`` +
        ``_write("текст", "user_text")``. Щоб не плодити порожні картки,
        роль запам'ятовуємо й дочіплюємо до наступного рядка тексту.
        """
        clean = (text or "").strip()
        if tag in {"user_role", "assistant_role"}:
            self._pending_role = ("ВИ" if tag == "user_role" else "АГЕНТ", tag)
            return
        if tag == "user_text":
            card = self._new_card(ROLE_USER, accent=theme.CHAT_USER, bg=theme.BG_CARD)
            self._body_text(card, clean, tag_colour=theme.FG_BRIGHT)
            self._pending_role = None
            self.transcript.add(f"\n{ROLE_USER}\n{clean}\n")
            return
        if not clean:
            return
        self._note(clean)
        self.transcript.add(text)

    def _write_markdown(self, text: str) -> None:
        self._add_assistant(text)

    # ── дії з текстом ──────────────────────────────────────────────────────
    def _copy(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text or "")
            self._note("Скопійовано в буфер обміну.")
        except tk.TclError:
            pass

    def _apply_code(self, code: str) -> None:
        if code and self.on_apply_code:
            self.on_apply_code(code, "chat")

    def _insert_last_code(self, card: _MessageCard) -> None:
        keys = sorted(self._pending_code, key=lambda k: (len(k), k))
        if not keys:
            self._note("У цій відповіді немає блоків коду.")
            return
        self._apply_code(self._pending_code[keys[-1]])

    def _quote(self, code: str) -> None:
        self._clear_placeholder()
        current = self.input_box.get("1.0", "end-1c")
        prefix = (current + "\n\n") if current.strip() else ""
        self.input_box.delete("1.0", "end")
        self.input_box.insert("1.0", f"{prefix}```\n{code}\n```\n")
        self.input_box.focus_set()

    #: Розширення, які вважаємо зображеннями для передачі в модель.
    IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

    def _attach_file(self) -> None:
        """Прикріпити файл до запиту.

        Зображення й текст обробляються ПО-РІЗНОМУ, і це принципово:

        * зображення стає в чергу ``pending_images`` агента — модель отримає
          його як ``image_url`` і справді побачить;
        * текст вставляється в поле як блок коду.

        Раніше тут БУЛО лише читання тексту:

        ``Path(path).read_text(encoding="utf-8", errors="replace")``

        Якщо користувач вибирав PNG, у поле введення потрапляв «текст»
        із бінарного сміття, а модель не бачила нічого. Тобто прикріпити
        скриншот через інтерфейс було неможливо взагалі.
        """
        path = filedialog.askopenfilename(
            parent=self,
            title="Додати файл або зображення до запиту",
            filetypes=[
                ("Зображення", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("Текст і код", "*.py *.js *.ts *.html *.css *.json *.md *.txt"),
                ("Усі файли", "*.*"),
            ],
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix in self.IMAGE_SUFFIXES:
            self._attach_image(Path(path))
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._note(f"Не вдалось прочитати файл: {exc}", kind="error")
            return
        snippet = content[:6000]
        self._clear_placeholder()
        self.input_box.insert("end", f"\n\n```{Path(path).name}\n{snippet}\n```\n")
        self.input_box.focus_set()
        if self.on_status:
            self.on_status(f"Додано файл: {Path(path).name}")

    def _attach_image(self, path: Path) -> None:
        """Поставити зображення в чергу моделі як СПРАВЖНІЙ image input."""
        runner = self.runner
        if runner is None:
            self._note("Агент ще не готовий — зображення не додано.", kind="error")
            return
        if not getattr(runner, "vision_enabled", True):
            # Модель без зору: запит із картинкою сервер відхилив би, тому
            # чесно кажемо про це замість тихого ігнорування.
            self._note("Поточна модель не має зору (немає mmproj). "
                       "Увімкни мультимодальну модель у «Хабі моделей».",
                       kind="error")
            return
        try:
            queue = runner.session.pending_images
        except AttributeError:
            self._note("Не вдалось додати зображення до контексту.", kind="error")
            return
        text = str(path)
        if text not in queue:
            queue.append(text)
        self._note(f"Зображення додано до запиту: {path.name}")
        if self.on_status:
            self.on_status(f"Зображення: {path.name} — модель побачить його в наступному запиті")

    def retheme(self) -> None:
        """Перемалювати вже намальовані картки під активну тему.

        Картки повідомлень тримають кольори в тегах ``tk.Text`` (markdown) і
        у власних атрибутах (фон картки). Загальний обхід ``retheme`` їх не
        покриває, тому текст перемальовуємо зі свіжою палітрою, а висоту
        перераховуємо — у темній темі метрики ті самі, але ширина рядка
        може відрізнятись через інший шрифт.
        """
        if not self._cards:
            return
        self._last_wrap = 0
        for card in list(self._cards):
            try:
                body_bg = str(card.cget("bg"))
            except tk.TclError:
                continue
            text = getattr(card, "text_widget", None)
            if text is None:
                continue
            try:
                content = text.get("1.0", "end-1c")
            except tk.TclError:
                continue
            renderer = getattr(card, "renderer", None)
            card.configure(bg=body_bg)
            try:
                if renderer is not None:
                    renderer.palette = self._palette()
                    renderer.configure_tags()
                    renderer.render(content, clear=True)
                    text.configure(background=body_bg)
                else:
                    text.configure(background=body_bg, foreground=theme.FG)
            except tk.TclError:
                continue
            self._apply_fit(text, getattr(card, "max_lines", self._body_lines))
        # Після перемальовування тексти можуть мати іншу кількість рядків —
        # полотно має стиснутись/розтягнутись за новим вмістом.
        try:
            self.scroll.sync_scrollregion()
        except tk.TclError:
            pass

    def apply_font(self) -> None:
        """Оновити шрифти після зміни масштабу."""
        mono = str(self.fonts.mono_small)
        for card in list(self._cards):
            try:
                for widget in self._walk(card):
                    if isinstance(widget, tk.Text):
                        current = str(widget.cget("font"))
                        widget.configure(font=mono if current == mono or "Consolas" in current
                                         else str(self.fonts.chat))
                    elif isinstance(widget, tk.Label):
                        widget.configure(font=self.fonts.ui_small)
                wrap_label = getattr(card, "wrap_label", None)
                if wrap_label is not None:
                    wrap_label.configure(wraplength=self._wrap_width())
                deep = getattr(card, "deep", None)
                if deep is not None:
                    deep.apply_wrap(self._wrap_width() - 24)
            except tk.TclError:
                continue

    def _walk(self, widget) -> list[tk.Misc]:
        found: list[tk.Misc] = []
        stack = list(widget.winfo_children())
        while stack:
            item = stack.pop()
            found.append(item)
            stack.extend(item.winfo_children())
        return found


def _looks_like_mode(argument: str) -> bool:
    """Чи схожий аргумент на назву режиму дозволів."""
    clean = (argument or "").strip().lower().replace("-", "_").replace(" ", "_")
    known = {
        "read", "readonly", "read_only", "лише_читання", "читання",
        "workspace", "work", "project", "запис", "робоча", "робочій",
        "full", "all", "unrestricted", "повний", "повний_доступ",
    }
    return clean in known or clean in permissions.MODES


class ModelBar(tk.Frame):
    """Рядок стану моделі над чатом: статус, вибір моделі, оновлення."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, settings: Settings) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.settings = settings
        self.on_change: Optional[Callable[[], None]] = None
        self._probe_after: Optional[str] = None
        self._probe_queue: "queue.Queue[tuple[bool, str, list[str]]]" = queue.Queue()
        self.columnconfigure(1, weight=1)

        self.status = tk.Label(self, text="●", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                               font=("Segoe UI", 8))
        self.status.grid(row=0, column=0, padx=(12, 6))

        self._model_var = tk.StringVar(value=self._initial_text())
        self.combo = tk.OptionMenu(self, self._model_var, "—")
        self.combo.configure(bg=theme.BG_INPUT, fg=theme.FG, activebackground=theme.BG_HOVER,
                             activeforeground=theme.FG_BRIGHT, bd=0, highlightthickness=0,
                             relief="flat", font=("Segoe UI", 8), anchor="w", padx=8)
        self.combo["menu"].configure(bg=theme.BG_INPUT, fg=theme.FG, activebackground=theme.BG_ACTIVE,
                                     activeforeground=theme.FG_BRIGHT, font=("Segoe UI", 9), bd=0)
        self.combo.grid(row=0, column=1, sticky="ew", pady=6)

        widgets.IconButton(self, "⟳", self.refresh, bg=theme.BG_ALT, fg=theme.FG_DIM,
                           font=("Segoe UI", 10), tooltip="Оновити список моделей").grid(
            row=0, column=2, padx=(4, 10))

    def _initial_text(self) -> str:
        return self.settings.llm.model or "модель не вибрана"

    # ── оновлення ──────────────────────────────────────────────────────────
    def set_models(self, models: list[str], online: bool) -> None:
        menu = self.combo["menu"]
        menu.delete(0, "end")
        if not models:
            models = [self.settings.llm.model or "модель не вибрана"]
        for name in models:
            menu.add_command(label=name, command=lambda m=name: self._pick(m))
        current = self.settings.llm.model or models[0]
        self.set_current(current)
        self.set_online(online)

    def set_current(self, name: str) -> None:
        """Показати назву моделі (OptionMenu не має методу set)."""
        try:
            self._model_var.set(name)
        except (tk.TclError, AttributeError):
            pass

    def _pick(self, name: str) -> None:
        self.settings.llm.model = name
        self.set_current(name)
        self.settings.save()
        self.set_online(True)
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        from .agent import ModelProbe

        self.status.configure(fg=theme.WARN)
        ModelProbe(
            self.settings.llm.base_url,
            self.settings.llm.api_key,
            lambda ok, detail, models: self._probe_queue.put((ok, detail, models)),
        ).start()
        self._drain_probe()


    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _drain_probe(self) -> None:
        try:
            while True:
                ok, _detail, models = self._probe_queue.get_nowait()
                self.set_models(models, ok)
                if self.on_change:
                    self.on_change()
        except queue.Empty:
            pass
        # Плануємо лише поки віджет живий — інакше після закриття вікна
        # в черзі лишаються «мертві» виклики.
        try:
            if self.winfo_exists():
                self._probe_after = self.after(150, self._drain_probe)
        except tk.TclError:
            self._probe_after = None

    def cancel_probe(self) -> None:
        """Скасувати відкладене опитування (при закритті вікна)."""
        job = getattr(self, "_probe_after", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._probe_after = None

    def set_online(self, online: bool) -> None:
        self.status.configure(fg=theme.SUCCESS if online else theme.ERROR)
