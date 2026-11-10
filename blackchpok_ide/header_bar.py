"""Верхня шапка IDE: логотип, проєкт, агент, модель, запуск, Git, Live Browser.

Задум. Класичне меню (Файл / Правка / Вигляд / Агент / Git / Довідка) нікуди
не зникає — воно лишається доступним із шапки через випадаючі групи, — але
часті дії переїжджають нагору й стають видимими без відкриття меню:

    ┌──────────────────────────────────────────────────────────────────────────┐
    │ ◈ BLACKCHPOK │ my-project ▾ │ ⊕ ▤ ⤓ ↶ ↷ │ ⊟ модель ▾ │ ● сервер │ ▶ ⏹ ⌨ │
    │                                                      │ ⑂ main ▾ │ ⚙ ⋯    │
    └──────────────────────────────────────────────────────────────────────────┘

Шапка нічого не вирішує сама: усі дії приходить ззовні колбеками, а стан
показує те, що їй передали. Це дозволяє тестувати її без справжнього вікна
й тримати логіку в одному місці (``commands.py``).
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import theme, widgets

#: Висота шапки: один рядок із великими іконками.
#:
#: Текстового рядка меню тут НЕМАЄ: у вікна вже є справжнє нативне меню
#: (``tk.Menu`` у ``main_window._build_menu``) — Файл / Правка / Вигляд /
#: Агент / Git / Довідка. Другий такий самий рядок у шапці лише дублював
#: його й з'їдав 22 px висоти.
HEADER_HEIGHT = 48

#: Ширина, вужче за яку шапка переходить у компактний режим (лишаються
#: логотип, проєкт, агент, запуск і «⋯»).
COMPACT_WIDTH = 1180

#: Ще вужче — ховаються підписи й частина групи (лишаються іконки).
NARROW_WIDTH = 860

# ── Розміри шрифтів шапки ──────────────────────────────────────────────────
#
# Один набір констант замість «9» і «10» розкиданих по коду: саме через це
# збільшити іконки було неможливо без пошуку кожного місця.
UI_FONT = "Segoe UI"
#: Значки дій (＋ ▤ ⤓ ↶ ↷ ▶ ■ ⟳) — великі, бо це основна взаємодія.
ICON_SIZE = 15
#: Підписи меню (Агент, модель, проєкт) — читабельні, не дрібні.
TEXT_SIZE = 11
#: Службові підписи (стан сервера) — трохи менші, але не 8 pt.
SMALL_SIZE = 9


class HeaderBar(tk.Frame):
    """Верхня панель швидкого доступу."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_command: Callable[[str], None],
        on_menu: Callable[[str, tk.Misc], None],
        on_palette: Callable[[], None],
        on_project_menu: Callable[[tk.Misc], None],
        on_model_menu: Callable[[tk.Misc], None],
        on_agent_menu: Callable[[tk.Misc], None],
        on_git_menu: Callable[[tk.Misc], None],
        on_more_menu: Callable[[tk.Misc], None],
        on_status_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, height=HEADER_HEIGHT,
                         bd=0, highlightthickness=0)
        self.fonts = fonts
        self._on_command = on_command
        self._on_menu = on_menu
        self._on_palette = on_palette
        self._on_project_menu = on_project_menu
        self._on_model_menu = on_model_menu
        self._on_agent_menu = on_agent_menu
        self._on_git_menu = on_git_menu
        self._on_more_menu = on_more_menu
        #: Клік по великому статусу моделі → самодіагностика.
        self._on_status_click = on_status_click
        self.pack_propagate(False)
        # Один рядок із minsize: без цього grid стискає шапку до вмісту й
        # збільшені іконки обрізаються зверху та знизу.
        self.rowconfigure(0, minsize=HEADER_HEIGHT)
        self.grid_propagate(False)
        self._mode = "wide"
        self._project = ""
        self._branch = ""
        self._changes = 0
        self._agent = "Агент"
        self._model = "модель не вибрана"
        self._server = ("", "")
        self._buttons: dict[str, widgets.HoverLabel] = {}
        self._labels: dict[str, tk.Label] = {}
        self._hidden: set[str] = set()
        self._build()
        self.bind("<Configure>", self._on_resize, add="+")

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=0)   # бренд + проєкт
        self.columnconfigure(1, weight=0)   # файли
        self.columnconfigure(2, weight=0)   # агент / модель / сервер
        self.columnconfigure(3, weight=0)   # запуск
        self.columnconfigure(4, weight=0)   # git
        self.columnconfigure(5, weight=1)   # розтяжка
        self.columnconfigure(6, weight=0)   # праворуч: палітра, налаштування

        # ── бренд + проєкт
        brand = tk.Frame(self, bg=theme.BG_ALT)
        brand.grid(row=0, column=0, sticky="w", padx=(theme.SPACE_LG, theme.SPACE_MD))

        logo = tk.Label(brand, text="◈", bg=theme.BG_ALT, fg=theme.ACCENT,
                        font=(UI_FONT, ICON_SIZE, "bold"))
        logo.pack(side="left")
        tk.Label(brand, text="BLACKCHPOK", bg=theme.BG_ALT, fg=theme.FG_BRIGHT,
                 font=(UI_FONT, TEXT_SIZE, "bold")).pack(side="left", padx=(6, 0))

        divider = tk.Frame(self, bg=theme.BORDER, width=1, height=HEADER_HEIGHT - 18)
        divider.grid(row=0, column=0, sticky="e", padx=(0, 0))

        self.project_btn = widgets.HoverLabel(
            brand, text="проєкт не вибрано ▾", command=lambda: self._menu("project"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, TEXT_SIZE),
            padx=theme.SPACE_SM, pady=3)
        self.project_btn.pack(side="left", padx=(theme.SPACE_MD, 0))
        widgets.Tip(self.project_btn, "Проєкт: відкрити теку, створити нову, останні")
        self._buttons["project"] = self.project_btn

        # ── файли: створити / відкрити / зберегти / скасувати / повторити
        files = tk.Frame(self, bg=theme.BG_ALT)
        files.grid(row=0, column=1, sticky="w", padx=(theme.SPACE_MD, theme.SPACE_MD))
        for key, icon, tip in (
            ("file.new", "＋", "Новий файл (Ctrl+N)"),
            ("file.open", "▤", "Швидке відкриття файлу (Ctrl+P)"),
            ("file.save", "⤓", "Зберегти (Ctrl+S)"),
            ("edit.undo", "↶", "Скасувати (Ctrl+Z)"),
            ("edit.redo", "↷", "Повторити (Ctrl+Y)"),
        ):
            button = widgets.HoverLabel(
                files, text=icon, command=lambda k=key: self._command(k),
                bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
                hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=8, pady=3)
            button.pack(side="left", padx=1)
            widgets.Tip(button, tip)
            self._buttons[key] = button

        # ── агент / модель / стан сервера
        agent = tk.Frame(self, bg=theme.BG_ALT)
        agent.grid(row=0, column=2, sticky="w", padx=(0, theme.SPACE_MD))

        self.agent_btn = widgets.HoverLabel(
            agent, text="◈ Агент ▾", command=lambda: self._menu("agent"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, TEXT_SIZE), padx=theme.SPACE_SM,
            pady=3)
        self.agent_btn.pack(side="left")
        widgets.Tip(self.agent_btn, "Режим агента, автономний режим, скіли, черга")
        self._buttons["agent"] = self.agent_btn

        self.model_btn = widgets.HoverLabel(
            agent, text="⊟ модель ▾", command=lambda: self._menu("model"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, TEXT_SIZE), padx=theme.SPACE_SM,
            pady=3)
        self.model_btn.pack(side="left", padx=(2, 0))
        widgets.Tip(self.model_btn, "Активна модель: локальна або хмарна")
        self._buttons["model"] = self.model_btn

        self.server_dot = tk.Label(agent, text="●", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=(UI_FONT, SMALL_SIZE))
        self.server_dot.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.server_label = tk.Label(agent, text="сервер", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=(UI_FONT, SMALL_SIZE))
        self.server_label.pack(side="left", padx=(3, 0))
        widgets.Tip(self.server_dot, "Стан локального сервера моделі")
        self._labels["server"] = self.server_label

        # ── ВЕЛИКИЙ статус моделі: «● МОДЕЛЬ ОНЛАЙН / ОФЛАЙН» ─────────────
        #
        # Навіщо окремий великий індикатор. У лозі користувача модель
        # працювала на 8081, а клієнт стукав у 8080 — і в інтерфейсі це
        # виглядало як «модель не працює», без єдиного помітного сигналу,
        # де саме проблема. Тепер стан видно одним поглядом, великими
        # літерами, зеленим або червоним кружечком.
        self.model_status = tk.Label(
            agent, text="● МОДЕЛЬ ОФЛАЙН", bg=theme.BG_ALT, fg=theme.ERROR,
            font=(UI_FONT, 10, "bold"), padx=theme.SPACE_MD, pady=2,
        )
        self.model_status.pack(side="left", padx=(theme.SPACE_MD, 0))
        widgets.Tip(self.model_status,
                    "Стан моделі: зелений — сервер відповідає, червоний — ні")
        # Клік по статусу відкриває самодіагностику: користувач бачить не
        # лише «офлайн», а й ПРИЧИНУ (порт, ключ, модель, лог рушія).
        self.model_status.bind("<Button-1>", self._on_model_status_click)
        try:
            self.model_status.configure(cursor="hand2")
        except tk.TclError:
            pass
        self._model_online: Optional[bool] = None

        # ── запуск / термінал / live browser / стоп
        run = tk.Frame(self, bg=theme.BG_ALT)
        run.grid(row=0, column=3, sticky="w", padx=(0, theme.SPACE_MD))
        for key, icon, tip in (
            ("run.start", "▶", "Запустити проєкт"),
            ("run.stop", "⏹", "Зупинити проєкт"),
            ("run.terminal", "⌨", "Термінал (Ctrl+`)"),
            ("run.browser", "🌐", "Live Browser: сайт поруч із кодом"),
        ):
            button = widgets.HoverLabel(
                run, text=icon, command=lambda k=key: self._command(k),
                bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
                hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=8, pady=3)
            button.pack(side="left", padx=1)
            widgets.Tip(button, tip)
            self._buttons[key] = button

        # ── git
        git = tk.Frame(self, bg=theme.BG_ALT)
        git.grid(row=0, column=4, sticky="w")
        self.git_btn = widgets.HoverLabel(
            git, text="⑂ — ▾", command=lambda: self._menu("git"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, TEXT_SIZE), padx=theme.SPACE_SM,
            pady=3)
        self.git_btn.pack(side="left")
        widgets.Tip(self.git_btn, "Git: гілка, зміни, commit, синхронізація")
        self._buttons["git"] = self.git_btn

        # ── праворуч: палітра команд, налаштування, «⋯»
        right = tk.Frame(self, bg=theme.BG_ALT)
        right.grid(row=0, column=6, sticky="e", padx=(0, theme.SPACE_LG))

        self.palette_btn = widgets.HoverLabel(
            right, text="⌕ Команди", command=self._on_palette,
            bg=theme.BG_CARD, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, TEXT_SIZE),
            padx=theme.SPACE_MD, pady=4)
        self.palette_btn.pack(side="left", padx=(0, theme.SPACE_SM))
        widgets.Tip(self.palette_btn, "Палітра команд (Ctrl+Shift+P)")

        self.settings_btn = widgets.HoverLabel(
            right, text="⚙", command=lambda: self._command("view.settings"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=8, pady=2)
        self.settings_btn.pack(side="left")
        widgets.Tip(self.settings_btn, "Налаштування (Ctrl+,)")
        self._buttons["view.settings"] = self.settings_btn

        self.more_btn = widgets.HoverLabel(
            right, text="⋯", command=lambda: self._menu("more"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=8, pady=2)
        self.more_btn.pack(side="left")
        widgets.Tip(self.more_btn, "Усі команди: довідка, панелі, діагностика")
        self._buttons["more"] = self.more_btn

        bottom = tk.Frame(self, bg=theme.BORDER, height=1)
        bottom.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")

    # ── дії ────────────────────────────────────────────────────────────────
    def _command(self, key: str) -> None:
        self._on_command(key)

    def _menu(self, which: str) -> None:
        handler = {
            "project": self._on_project_menu,
            "agent": self._on_agent_menu,
            "model": self._on_model_menu,
            "git": self._on_git_menu,
            "more": self._on_more_menu,
        }.get(which)
        if handler is None:
            return
        try:
            handler(self._buttons.get(which, self))
        except tk.TclError:
            return

    # ── стан ───────────────────────────────────────────────────────────────
    def set_project(self, name: str, *, workspace: str = "") -> None:
        self._project = name or ""
        text = f"{name} ▾" if name else "проєкт не вибрано ▾"
        try:
            self.project_btn.configure(text=text,
                                       fg=theme.FG_BRIGHT if name else theme.FG_DIM)
        except tk.TclError:
            pass
        if workspace:
            widgets.Tip(self.project_btn, f"Проєкт: {workspace}")

    def set_agent(self, label: str, *, busy: bool = False) -> None:
        self._agent = label
        try:
            self.agent_btn.configure(text=f"◈ {label} ▾",
                                     fg=theme.ACCENT if busy else theme.FG)
        except tk.TclError:
            pass

    def set_model(self, label: str, *, local: bool = True, online: bool = True) -> None:
        self._model = label
        colour = theme.FG_DIM if online else theme.WARN
        try:
            suffix = "локальна" if local else "хмара"
            self.model_btn.configure(text=f"⊟ {label} · {suffix} ▾", fg=colour)
        except tk.TclError:
            pass

    def set_model_status(self, online: Optional[bool], *, detail: str = "") -> None:
        """ВЕЛИКИЙ статус моделі: «● МОДЕЛЬ ОНЛАЙН» / «● МОДЕЛЬ ОФЛАЙН».

        ``None`` — стан ще невідомий (перевірка не завершилась): показуємо
        сірий кружечок, а не вигаданий зелений.

        Чому так помітно: раніше єдиним сигналом була крихітна крапка
        поруч із підписом «сервер», і користувач бачив «модель не працює»
        без жодної підказки, що сталося. Тепер стан видно з першого
        погляду, а клік відкриває причину.
        """
        if online is True:
            text, colour = "● МОДЕЛЬ ОНЛАЙН", theme.SUCCESS
        elif online is False:
            text, colour = "● МОДЕЛЬ ОФЛАЙН", theme.ERROR
        else:
            text, colour = "● МОДЕЛЬ …", theme.FG_FAINT
        self._model_online = online
        try:
            self.model_status.configure(text=text, fg=colour)
        except tk.TclError:
            pass
        if detail:
            widgets.Tip(self.model_status,
                        f"Стан моделі: {detail}\nКлік — самодіагностика")

    def _on_model_status_click(self, _event=None) -> None:
        if self._on_status_click is not None:
            self._on_status_click()

    def set_server(self, text: str, state: str = "idle") -> None:
        """Стан локального сервера: idle | ok | warn | error."""
        self._server = (text, state)
        colours = {
            "ok": theme.SUCCESS,
            "warn": theme.WARN,
            "error": theme.ERROR,
        }
        colour = colours.get(state, theme.FG_FAINT)
        try:
            self.server_dot.configure(fg=colour)
            self.server_label.configure(text=text or "сервер", fg=colour)
        except tk.TclError:
            pass

    def set_git(self, branch: str, changes: int = 0) -> None:
        self._branch = branch or ""
        self._changes = int(changes or 0)
        parts = [f"⑂ {branch or '—'}"]
        if self._changes:
            parts.append(f"{self._changes}△")
        text = " ".join(parts) + " ▾"
        try:
            self.git_btn.configure(text=text,
                                   fg=theme.WARN if self._changes else theme.FG_DIM)
        except tk.TclError:
            pass

    def set_command_enabled(self, key: str, enabled: bool) -> None:
        button = self._buttons.get(key)
        if button is None:
            return
        try:
            button.configure(fg=theme.FG_DIM if enabled else theme.FG_FAINT)
        except tk.TclError:
            pass

    # ── адаптивність ───────────────────────────────────────────────────────
    def _on_resize(self, event=None) -> None:
        width = int(getattr(event, "width", 0) or 0)
        if width <= 1:
            return
        if width < NARROW_WIDTH:
            mode = "narrow"
        elif width < COMPACT_WIDTH:
            mode = "compact"
        else:
            mode = "wide"
        if mode != self._mode:
            self._apply_mode(mode)

    def _apply_mode(self, mode: str) -> None:
        """Компактні режими: ховаємо другорядне, головне лишається.

        Правило: шапка НІКОЛИ не показує обрізаних підписів і не робить
        горизонтальної прокрутки. Тому при звуженні ми не стискаємо
        віджети, а прибираємо цілі групи — і кожна прибрана команда
        лишається в меню «⋯» (там перелічені ВСІ команди програми).

        Live Browser не ховаємо ніколи: це окремий робочий режим, і саме
        на вузькому екрані він найпотрібніший.
        """
        self._mode = mode
        keep_always = {"run.browser", "view.settings", "agent.stop"}
        hide: set[str] = set()
        if mode in ("compact", "narrow"):
            hide = {"run.terminal", "edit.redo"}
        if mode == "narrow":
            hide = {"run.terminal", "edit.redo", "edit.undo", "file.open",
                    "run.stop", "agent.stop"}
        hide -= keep_always
        self._hidden = set(hide)
        for key, button in self._buttons.items():
            try:
                if key in hide:
                    button.pack_forget()
                else:
                    # ``pack`` без параметрів зберігає сторону, задану раніше.
                    button.pack(side="left", padx=1)
            except tk.TclError:
                pass
        try:
            self.palette_btn.configure(text="⌕" if mode != "wide" else "⌕ Команди")
            self.server_label.configure(
                text="" if mode == "narrow" else (self._server[0] or "сервер"))
        except tk.TclError:
            pass
        # Великий статус моделі лишається ВСІДИ, але у вузькому вікні
        # коротшає до «● ОНЛАЙН» / «● ОФЛАЙН»: важливий сам стан, а не слово
        # «МОДЕЛЬ». Ховати його не можна — це головний індикатор справності.
        try:
            online = self._model_online
            short = "● ОНЛАЙН" if online is True else (
                "● ОФЛАЙН" if online is False else "● …")
            full = "● МОДЕЛЬ ОНЛАЙН" if online is True else (
                "● МОДЕЛЬ ОФЛАЙН" if online is False else "● МОДЕЛЬ …")
            self.model_status.configure(text=short if mode == "narrow" else full)
        except tk.TclError:
            pass

    @property
    def hidden_commands(self) -> set[str]:
        """Ключі команд, прихованих адаптивним режимом (усі доступні з «⋯»)."""
        return set(getattr(self, "_hidden", set()))


__all__ = ["COMPACT_WIDTH", "HEADER_HEIGHT", "HeaderBar", "NARROW_WIDTH"]
