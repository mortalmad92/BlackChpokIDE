"""Права колонка контексту: проєкт, агент, файли, зміни, інструменти.

Це «панель ситуації» праворуч від діалогу. Користувач має бачити одним
поглядом, у якому проєкті він працює, якою моделлю й з якими інструментами,
що відкрито й змінено, і скільки контексту вже зайнято:

    ┌──────────────────────────────┐
    │ ПРОЄКТ                       │
    │   blackchpock_ai             │
    │   Python · 2 години тому     │
    │ АГЕНТ                        │
    │   ● працює · крок 3 з 9      │
    │   модель qwen2.5-coder-14b   │
    │   контекст ▓▓▓░░░░░ 34%      │
    │ ІНСТРУМЕНТИ                  │
    │   read_file · write_file …   │
    │ ВІДКРИТІ ВКЛАДКИ             │
    │ ЗМІНИ                        │
    │ ФАЙЛИ                        │
    └──────────────────────────────┘

Усі дані — з реального стану: тека проєкту, назва моделі з налаштувань,
лічильники вкладок і змінених файлів, статус із черги кроків.
"""

from __future__ import annotations

import logging
import tkinter as tk
import time
from pathlib import Path
from typing import Callable, Optional

from . import queue_engine, theme, widgets, workspace as ws

LOG = logging.getLogger("blackchpok.context")

MAX_TABS = 12
MAX_CHANGES = 8
MAX_FILES = 14
MAX_TOOLS = 6


class _Row(tk.Frame):
    """Один рядок списку: іконка, текст, лічильник."""

    def __init__(self, master: tk.Misc, text: str, *, icon: str = "", hint: str = "",
                 bg: str = theme.BG_ALT, on_click: Optional[Callable[[], None]] = None,
                 on_context: Optional[Callable[[object], None]] = None,
                 fg: str = theme.FG_DIM) -> None:
        super().__init__(master, bg=bg, cursor="hand2")
        self._bg = bg
        self.columnconfigure(1, weight=1)

        self.icon = tk.Label(self, text=icon, bg=bg, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                             width=2, anchor="w")
        self.icon.grid(row=0, column=0, sticky="w", padx=(6, 0), pady=2)

        self.label = tk.Label(self, text=text, bg=bg, fg=fg, font=("Segoe UI", 8),
                              anchor="w", justify="left")
        self.label.grid(row=0, column=1, sticky="ew", pady=2)

        self.hint = tk.Label(self, text=hint, bg=bg, fg=theme.FG_FAINT, font=("Segoe UI", 8))
        self.hint.grid(row=0, column=2, sticky="e", padx=(4, 8), pady=2)

        for widget in (self, self.icon, self.label, self.hint):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            if on_click is not None:
                widget.bind("<Button-1>", lambda _e: on_click())
            if on_context is not None:
                widget.bind("<Button-3>", on_context)

    def _on_enter(self, _event=None) -> None:
        for widget in (self, self.icon, self.label, self.hint):
            widget.configure(bg=theme.BG_HOVER)
        self.label.configure(fg=theme.FG_BRIGHT)

    def _on_leave(self, _event=None) -> None:
        for widget in (self, self.icon, self.label, self.hint):
            widget.configure(bg=self._bg)
        self.label.configure(fg=theme.FG_DIM)


class ContextPanel(tk.Frame):
    """Колонка «Відкриті вкладки / Зміни / Файли»."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        root_provider: Callable[[], Optional[Path]],
        *,
        on_open_path: Optional[Callable[[Path], None]] = None,
        on_close_tab: Optional[Callable[[str], None]] = None,
        on_select_tab: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_open_tools: Optional[Callable[[], None]] = None,
        on_toggle_collapse: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.root_provider = root_provider
        self.on_open_path = on_open_path
        self.on_close_tab = on_close_tab
        self.on_select_tab = on_select_tab
        self.on_status = on_status
        self.on_open_settings = on_open_settings
        self.on_open_tools = on_open_tools
        self.on_toggle_collapse = on_toggle_collapse
        self.tabs_provider: Optional[Callable[[], list[tuple[str, str, bool]]]] = None
        self.active_tab_provider: Optional[Callable[[], str]] = None
        #: Джерела ЖИВИХ даних про агента (ставляться вікном).
        self.agent_status_provider: Optional[Callable[[], str]] = None
        self.model_provider: Optional[Callable[[], tuple[str, str]]] = None
        self.context_provider: Optional[Callable[[], tuple[int, int]]] = None
        self.tools_provider: Optional[Callable[[], list[str]]] = None
        #: Стан реєстру інструментів: скільки існує, скільки схем у запиті,
        #: чи ввімкнено лінивість. Дані з реального механізму, не декоративні.
        self.registry_provider: Optional[Callable[[], dict]] = None
        #: Чи підрахунок токенів точний (tokenizer моделі) чи оцінка.
        self.exact_counter_provider: Optional[Callable[[], bool]] = None
        #: Детальний бюджет контексту (вікно, відповідь, історія, схеми).
        self.budget_provider: Optional[Callable[[], dict]] = None
        #: Кеш дорогих обходів диска: ключ → (значення, час).
        self._cache: dict[str, tuple[object, float]] = {}
        #: Останні показані рядки секцій — щоб не перебудовувати віджети,
        #: коли вміст не змінився.
        self._rows_cache: dict[str, list] = {}
        #: Підпис стану агента: якщо не змінився, секція не перебудовується.
        self._agent_signature: tuple = ()
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── шапка колонки з кнопкою згортання
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)

        self.head_label = tk.Label(head, text="КОНТЕКСТ", bg=theme.BG_ALT,
                                   fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8, "bold"), anchor="w")
        self.head_label.grid(row=0, column=0, sticky="w",
                             padx=(theme.SPACE_LG, 0), pady=(theme.SPACE_MD, 0))
        self.collapse_btn = widgets.IconButton(
            head, "»", self._collapse, bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 9), tooltip="Згорнути панель контексту")
        self.collapse_btn.grid(row=0, column=1, sticky="e",
                               padx=(0, theme.SPACE_SM))

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=1, column=0, sticky="nsew")
        host = self.scroll.inner

        # Секція «агент» іде ПЕРШОЮ: це найважливіше, що робить IDE.
        self.agent_section = self._section(host, "АГЕНТ · ЛОКАЛЬНА МОДЕЛЬ", "agent")
        self.project_section = self._section(host, "ПРОЄКТ", "project")
        self.tools_section = self._section(host, "ІНСТРУМЕНТИ", "tools")
        self.tabs_section = self._section(host, "ВІДКРИТІ ВКЛАДКИ", "tabs")
        self.changes_section = self._section(host, "ЗМІНИ", "changes")
        self.files_section = self._section(host, "ФАЙЛИ", "files")

    def _collapse(self) -> None:
        if self.on_toggle_collapse is not None:
            self.on_toggle_collapse()
        else:
            self._collapse_self()

    def _collapse_self(self) -> None:
        """Згорнути себе, якщо вікно не підключило власний обробник."""
        try:
            self.grid_remove()
        except tk.TclError:
            pass

    def _section(self, host: tk.Misc, title: str, key: str) -> dict[str, tk.Frame]:
        head = widgets.SectionHeader(host, title)
        head.pack(fill="x")
        body = tk.Frame(host, bg=theme.BG_ALT)
        body.pack(fill="x", padx=0, pady=(0, 4))
        widgets.Divider(host, colour=theme.BORDER)
        return {"head": head, "body": body}  # type: ignore[return-value]

    # ── наповнення ─────────────────────────────────────────────────────────
    def refresh(self) -> None:
        self._refresh_agent()
        self._refresh_project()
        self._refresh_tools()
        self._refresh_tabs()
        self._refresh_changes()
        self._refresh_files()

    def _cached(self, key: str, produce, *, ttl: float = 3.0):
        """Порахувати значення не частіше, ніж раз на ``ttl`` секунд.

        Навіщо: обхід проєкту (до 4000 файлів) коштував 138 мс, і панель
        смикала його на КОЖНЕ оновлення — а оновлення йдуть кілька разів на
        секунду під час роботи агента. Заміряно: це найдорожча операція
        інтерфейсу. Файли не змінюються за секунду, тож кеш нічого не
        спотворює, а кадри перестають залипати.

        ``produce`` може кинути виняток — тоді повертаємо попереднє
        значення (або порожній список), щоб панель не зникала.
        """
        now = time.time()
        entry = self._cache.get(key)
        if entry is not None and (now - entry[1]) < ttl:
            return entry[0]
        try:
            value = produce()
        except Exception:  # noqa: BLE001 - панель не має ламати вікно
            LOG.debug("Кешований розрахунок %s упав", key, exc_info=True)
            value = entry[0] if entry is not None else []
        self._cache[key] = (value, now)
        return value

    def invalidate(self) -> None:
        """Скинути кеш (наприклад, після зміни файлів або теки)."""
        self._cache.clear()

    def _refresh_agent(self) -> None:
        """Стан локального агента: що робить, якою моделлю, скільки контексту."""
        # Провайдери стану можуть бути ДОРОГИМИ: ``_model_summary`` робить
        # мережевий запит до сервера моделі, щоб показати «online». Панель
        # оновлюється кілька разів на секунду, і кожне оновлення робило цей
        # запит — заміряно: 260 мс на кадр, найдорожча операція інтерфейсу.
        #
        # Тому стан збираємо не частіше, ніж раз на секунду, і
        # перевикористовуємо, поки не змінився.
        cached = self._cached("agent_state", self._collect_agent_state, ttl=1.0)
        status, model_name, model_kind, used, limit, _tools, registry, \
            exact, budget = cached
        signature = (str(status), str(model_name), str(model_kind),
                     int(used or 0), int(limit or 0),
                     dict(registry or {}), bool(exact), dict(budget or {}))
        if self._agent_signature == signature:
            return
        self._agent_signature = signature

        body = self._clear(self.agent_section)

        # Рядок стану: крапка + текст.
        status_row = tk.Frame(body, bg=theme.BG_ALT)
        status_row.pack(fill="x", padx=(10, 6), pady=(2, 1))
        colour = theme.ACCENT if "роб" in str(status).lower() else theme.FG_FAINT
        tk.Label(status_row, text="●", bg=theme.BG_ALT, fg=colour,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(status_row, text=_short(str(status), 40), bg=theme.BG_ALT,
                 fg=theme.FG if colour == theme.ACCENT else theme.FG_DIM,
                 font=("Segoe UI", 8), anchor="w").pack(side="left", padx=(4, 0))

        # Модель — клік відкриває налаштування. Назву показуємо окремим
        # рядком, а вид підключення — підписом нижче: у вузькій колонці
        # (212 px) назва й «локальна · online» в одному рядку обрізали
        # назву до двох символів.
        #
        # ЗАУВАЖЕННЯ КОРИСТУВАЧА «навіщо ці всі пункти дублюються?»: спершу
        # тут було по рядку на кожен факт, і панель перетворювалась на
        # стовпчик із п'яти рядків про те саме. Тепер модель — одна строка
        # (назва · вид), а стан контексту — одна строка з числами.
        kind_tail = f" · {_short(str(model_kind), 22)}" if model_kind else ""
        model_row = _Row(
            body, f"модель: {_short(str(model_name), 26)}",
            icon="◈",
            hint=kind_tail.strip(" ·")[:16],
            on_click=self.on_open_settings,
            fg=theme.FG_DIM if str(model_name) != "не вибрана" else theme.WARN,
        )
        model_row.pack(fill="x")

        # Заповнення контексту: смуга, а не сухе число.
        if limit > 0:
            fraction = max(0.0, min(1.0, used / limit))
            percent = int(round(fraction * 100))
            gauge = tk.Frame(body, bg=theme.BG_ALT)
            gauge.pack(fill="x", padx=(10, 8), pady=(3, 1))
            gauge.columnconfigure(1, weight=1)
            tk.Label(gauge, text="контекст", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w").grid(row=0, column=0, sticky="w")
            bar = tk.Canvas(gauge, height=4, bg=theme.BG_INPUT, bd=0,
                            highlightthickness=0, takefocus=0)
            bar.grid(row=0, column=1, sticky="ew", padx=(6, 6))
            fill = bar.create_rectangle(
                0, 0, 0, 4, outline="",
                fill=(theme.ERROR if percent >= 90
                      else theme.WARN if percent >= 70 else theme.ACCENT))
            tk.Label(gauge, text=f"{percent}%", bg=theme.BG_ALT,
                     fg=theme.FG_DIM, font=("Segoe UI", 8)).grid(
                row=0, column=2, sticky="e")

            def paint(_event=None, canvas=bar, rect=fill, value=fraction) -> None:
                try:
                    width = max(1, canvas.winfo_width())
                    canvas.coords(rect, 0, 0, int(width * value), 4)
                except tk.TclError:
                    pass

            bar.bind("<Configure>", paint)
            body.after_idle(paint)
        else:
            tk.Label(body, text="контекст: немає даних від моделі", bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w").pack(
                fill="x", padx=(10, 8), pady=(2, 2))

        self._paint_budget_detail(body, used, limit, budget, exact)
        self._paint_registry(body, registry)

    def _paint_budget_detail(self, body: tk.Frame, used: int, limit: int,
                             budget: dict, exact: bool) -> None:
        """Розподіл бюджету й чесність підрахунку — з реального механізму.

        ОДИН рядок на бюджет і ОДИН на чесність підрахунку. Раніше їх було
        три окремі, і користувач слушно питав, навіщо дублювати те саме.
        Показуємо «оцінка» чи «точно» прямо тут: без цього приблизні числа
        сприймались як точні, а потім запит обривався на межі вікна.
        """
        parts: list[str] = []
        if limit > 0:
            free = max(0, int(limit) - int(used or 0))
            parts.append(f"вільно {free:,}".replace(",", " "))
        for key, label in (("answer", "відп"), ("history", "іст"),
                           ("tools", "схеми"), ("system", "сис")):
            value = int((budget or {}).get(key) or 0)
            if value:
                parts.append(f"{label} {value:,}".replace(",", " "))
        if parts:
            tk.Label(body, text=" · ".join(parts), bg=theme.BG_ALT,
                     fg=theme.FG_FAINT, font=("Segoe UI", 7), anchor="w",
                     justify="left", wraplength=190).pack(
                fill="x", padx=(26, 8))
        tk.Label(body, text=("токени: точно" if exact else "токени: оцінка"),
                 bg=theme.BG_ALT,
                 fg=theme.FG_FAINT if exact else theme.WARN,
                 font=("Segoe UI", 7), anchor="w").pack(fill="x", padx=(26, 8))

    def _paint_registry(self, body: tk.Frame, registry: dict) -> None:
        """Стан реєстру інструментів: скільки існує й скільки схем у запиті.

        Один рядок замість двох: числа вже пояснюють режим, а повна причина
        («7122 токенів > бюджету 4096») потрібна в журналі, не в панелі.
        """
        if not registry:
            return
        total = int(registry.get("total") or 0)
        eager = int(registry.get("eager") or 0)
        loaded = int(registry.get("loaded") or 0)
        lazy = bool(registry.get("lazy"))
        if not total:
            return
        if lazy:
            text = (f"схем у запиті: {eager} з {total}"
                    + (f" · довантажено {loaded}" if loaded else ""))
            colour = theme.ACCENT
        else:
            text = f"схем у запиті: усі {total}"
            colour = theme.FG_FAINT
        tk.Label(body, text=text, bg=theme.BG_ALT, fg=colour,
                 font=("Segoe UI", 7), anchor="w").pack(fill="x", padx=(26, 8))

    def _collect_agent_state(self) -> tuple:
        """Зібрати стан агента з провайдерів (викликається рідко, з кешем)."""
        status = self._safe(self.agent_status_provider, "очікує")
        model_name, model_kind = self._safe(self.model_provider,
                                            ("не вибрана", "—"))
        used, limit = self._safe(self.context_provider, (0, 0))
        tools = self._safe(self.tools_provider, [])
        registry = self._safe(self.registry_provider, {})
        exact = bool(self._safe(self.exact_counter_provider, False))
        budget = self._safe(self.budget_provider, {})
        return status, model_name, model_kind, used, limit, tools, \
            registry, exact, budget

    def _refresh_project(self) -> None:
        """Який проєкт відкрито і який у ньому стек."""
        body = self._clear(self.project_section)
        root = self.root_provider() if self.root_provider else None
        if not root or not Path(root).is_dir():
            self._empty(body, "Теку проєкту не обрано")
            return
        folder = Path(root)
        # ``_modified_hint`` обходить до 2000 файлів — це найдорожча
        # операція панелі (заміряно: 220 мс із 110 мс повного оновлення).
        # Кешуємо на 10 с: «коли востаннє змінювали проєкт» не потребує
        # точності до секунди, зате кадри перестають залипати.
        hint = self._cached(f"mtime:{folder}",
                            lambda: _modified_hint(folder), ttl=10.0)
        stack = self._cached(f"stack:{folder}",
                             lambda: _stack_of(folder), ttl=30.0)
        row = _Row(
            body, folder.name or str(folder), icon="🗂",
            hint=hint,
            on_click=self.on_open_settings,
            fg=theme.FG_BRIGHT,
        )
        row.pack(fill="x")
        if stack:
            tk.Label(body, text=stack, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w", justify="left",
                     wraplength=190).pack(fill="x", padx=(26, 8), pady=(0, 2))

    def _refresh_tools(self) -> None:
        """Активні інструменти агента (справжній перелік, не вигаданий)."""
        # Список інструментів приходить із конфігурації агента й не
        # змінюється на кожному кадрі — беремо з кешу.
        tools = self._cached("tools_list",
                             lambda: self._safe(self.tools_provider, []),
                             ttl=5.0)
        names = [str(name) for name in tools if str(name).strip()][:MAX_TOOLS]
        if self._rows_cache.get("tools") == names:
            return
        body = self._clear(self.tools_section)
        self._remember_rows("tools", names)
        if not names:
            self._empty(body, "Інструменти не підключені")
            return
        for name in names:
            _Row(body, name, icon="⚒", fg=theme.FG_DIM,
                 on_click=self.on_open_tools).pack(fill="x")

    def _refresh_tabs(self) -> None:
        body = self._clear(self.tabs_section)
        rows: list[tuple[str, str, bool]] = []
        if self.tabs_provider:
            try:
                rows = self.tabs_provider()
            except Exception:  # noqa: BLE001 - панель не має ламати вікно
                rows = []
        active = ""
        if self.active_tab_provider:
            try:
                active = self.active_tab_provider()
            except Exception:  # noqa: BLE001
                active = ""
        if not rows:
            self._empty(body, "Немає відкритих файлів")
            return
        for frame_id, title, modified in rows[:MAX_TABS]:
            display = f"● {title}" if modified else title
            row = _Row(
                body, display,
                icon="▤",
                bg=theme.BG_ACTIVE if frame_id == active else theme.BG_ALT,
                fg=theme.FG_BRIGHT if frame_id == active else theme.FG_DIM,
                on_click=(lambda f=frame_id: self.on_select_tab and self.on_select_tab(f)),
                on_context=(lambda e, f=frame_id: self._tab_menu(f, e)),
            )
            row.pack(fill="x")
        if len(rows) > MAX_TABS:
            tk.Label(body, text=f"… ще {len(rows) - MAX_TABS}", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=(18, 8))

    @staticmethod
    def _safe(provider, default):
        """Викликати провайдер стану, не ламаючи панель."""
        if provider is None:
            return default
        try:
            value = provider()
        except Exception:  # noqa: BLE001 - панель не має падати
            return default
        return default if value is None else value

    def _clear(self, section: dict[str, tk.Frame]) -> tk.Frame:
        body = section["body"]
        for child in body.winfo_children():
            child.destroy()
        return body

    def _empty(self, body: tk.Frame, text: str) -> None:
        tk.Label(body, text=text, bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                 anchor="w", justify="left").pack(fill="x", padx=(18, 8), pady=2)

    def _tab_menu(self, frame_id: str, event) -> None:
        widgets.context_menu(self, (
            ("Закрити вкладку", lambda: self.on_close_tab and self.on_close_tab(frame_id)),
        ), event)

    def _refresh_changes(self) -> None:
        body = self._clear(self.changes_section)
        root = self.root_provider() if self.root_provider else None
        if not root or not Path(root).is_dir():
            self._empty(body, "Немає робочої теки")
            return
        hits = self._cached(f"changes:{root}", lambda: _recent_changes(Path(root)))
        rows = [(str(path), stamp) for path, stamp in hits[:MAX_CHANGES]]
        # Перемальовуємо лише коли вміст справді змінився: панель оновлюється
        # кілька разів на секунду, а віджети створюються заново щоразу —
        # це і були десятки мілісекунд на кадр.
        if not self._same_rows("changes", rows):
            for raw, stamp in rows:
                path = Path(raw)
                try:
                    name = ws.relative_to_root(Path(root), path)
                except Exception:  # noqa: BLE001
                    name = path.name
                _Row(
                    body, name, icon="±", hint=stamp,
                    on_click=(lambda p=path: self.on_open_path and self.on_open_path(p)),
                ).pack(fill="x")
            self._remember_rows("changes", rows)
        if not hits:
            self._empty(body, "Немає змінених файлів")

    def _refresh_files(self) -> None:
        body = self._clear(self.files_section)
        root = self.root_provider() if self.root_provider else None
        if not root or not Path(root).is_dir():
            self._empty(body, "Відкрий теку проєкту")
            return
        files = self._cached(f"files:{root}", lambda: _top_files(Path(root)))
        rows = [str(path) for path in files[:MAX_FILES]]
        if not self._same_rows("files", rows):
            for raw in rows:
                path = Path(raw)
                _Row(
                    body, path.name, icon="·",
                    on_click=(lambda p=path: self.on_open_path and self.on_open_path(p)),
                ).pack(fill="x")
            self._remember_rows("files", rows)
        if not files:
            self._empty(body, "Файлів не знайдено")

    def _same_rows(self, key: str, rows: list) -> bool:
        """Чи той самий набір рядків, що й минулого разу (без перебудови)."""
        return self._rows_cache.get(key) == rows

    def _remember_rows(self, key: str, rows: list) -> None:
        self._rows_cache[key] = list(rows)


def _short(text: str, limit: int) -> str:
    """Обрізати рядок для вузької колонки."""
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _modified_hint(folder: Path) -> str:
    """Коли проєкт востаннє змінювали (за часом найновішого файлу)."""
    latest: Optional[float] = None
    try:
        for path in ws.walk_text_files(folder, limit=2000):
            try:
                stamp = path.stat().st_mtime
            except OSError:
                continue
            if latest is None or stamp > latest:
                latest = stamp
    except OSError:
        return ""
    if latest is None:
        return ""
    delta = max(0.0, time.time() - latest)
    if delta < 3600:
        return f"{max(1, int(delta // 60))} хв тому"
    if delta < 86400:
        return f"{int(delta // 3600)} год тому"
    return f"{int(delta // 86400)} дн тому"


def _stack_of(folder: Path) -> str:
    """Короткий опис стеку проєкту з реальних файлів у теці."""
    markers: list[str] = []
    try:
        names = {path.name.lower() for path in folder.iterdir() if path.is_file()}
    except OSError:
        return ""
    if names & {"pyproject.toml", "requirements.txt", "setup.py"}:
        markers.append("Python")
    if "package.json" in names:
        markers.append("Node.js")
    if names & {"cargo.toml", "go.mod", "pom.xml", "build.gradle"}:
        markers.append("системна мова")
    if any(name.endswith((".csproj", ".sln")) for name in names):
        markers.append(".NET")
    if names & {"index.html", "vite.config.js", "next.config.js"}:
        markers.append("веб")
    return " · ".join(markers[:4])


def _recent_changes(root: Path, limit: int = MAX_CHANGES) -> list[tuple[Path, str]]:
    """Файли, змінені нещодавно, від найновіших."""
    import time

    cutoff = time.time() - 7 * 24 * 3600
    found: list[tuple[float, Path]] = []
    try:
        for path in ws.walk_text_files(root, limit=4000):
            # .bak лишає сам редактор при записі — це не «зміна» користувача.
            if path.name.endswith(".bak") or path.name.endswith(".pyc-check"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime >= cutoff:
                found.append((stat.st_mtime, path))
    except OSError:
        return []
    found.sort(key=lambda item: item[0], reverse=True)
    now = time.time()
    result: list[tuple[Path, str]] = []
    for stamp, path in found[:limit]:
        delta = max(0.0, now - stamp)
        if delta < 3600:
            hint = f"{int(delta // 60) or 1} хв"
        elif delta < 86400:
            hint = f"{int(delta // 3600)} год"
        else:
            hint = f"{int(delta // 86400)} дн"
        result.append((path, hint))
    return result


def _top_files(root: Path, limit: int = MAX_FILES) -> list[Path]:
    """Найважливіші файли теки: спершу корінь, далі вкладені."""
    files: list[Path] = []
    try:
        for path in sorted(root.iterdir(), key=lambda p: (p.is_dir(), p.name.lower())):
            if path.name in ws.SKIP_DIRS:
                continue
            if path.is_dir():
                continue
            files.append(path)
    except OSError:
        return []
    try:
        for path in ws.walk_text_files(root, limit=limit * 4):
            if path not in files:
                files.append(path)
            if len(files) >= limit:
                break
    except OSError:
        pass
    return files
