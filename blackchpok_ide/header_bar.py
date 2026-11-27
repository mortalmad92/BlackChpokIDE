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

from . import icons, theme, widgets
from . import i18n

#: Висота шапки: один рядок із великими іконками.
#:
#: Текстового рядка меню тут НЕМАЄ: у вікна вже є справжнє нативне меню
#: (``tk.Menu`` у ``main_window._build_menu``) — Файл / Правка / Вигляд /
#: Агент / Git / Довідка. Другий такий самий рядок у шапці лише дублював
#: його й з'їдав 22 px висоти.
HEADER_HEIGHT = 60

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
ICON_SIZE = 28
#: Підписи меню (Агент, модель, проєкт) — читабельні, не дрібні.
TEXT_SIZE = 13
#: Службові підписи (стан сервера) — трохи менші, але не 8 pt.
SMALL_SIZE = 12


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
        self._neon_bar_canvas = tk.Canvas(self, height=2, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self._neon_bar_canvas.pack(side="bottom", fill="x")
        self._neon_bar_pos = 0
        self.bind("<Configure>", self._on_resize, add="+")
        self.after(800, self._refresh_internet_async)

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
        brand.grid(row=0, column=0, sticky="w", padx=(theme.SPACE_SM, theme.SPACE_MD))

        #: Кнопка «☰» — РОЗГОРНУТИ згорнуту бічну панель.
        #:
        #: Показується лише тоді, коли панель прихована (керує вікно через
        #: ``set_reveal_visible``). Раніше згорнуту панель можна було
        #: повернути тільки через меню або ``Ctrl+B``, і користувач бачив
        #: порожній лівий край без жодної підказки.
        self.reveal_btn = widgets.HoverLabel(
            brand, text="☰", command=lambda: self._command("view.sidebar"),
            bg=theme.BG_ALT, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=8, pady=3)
        widgets.Tip(self.reveal_btn, "Показати бічну панель (Ctrl+B)")
        self._reveal_shown = False

        logo = tk.Label(brand, text="\u25c8", bg=theme.BG_ALT, fg=theme.ACCENT, font=(UI_FONT, ICON_SIZE + 1, "bold"))
        self.logo = logo; self._brand_vec_img = icons.get_icon("brand", color=theme.ACCENT, size=42); logo.configure(image=self._brand_vec_img, text=""); logo.pack(side="left")
        brand_title = tk.Frame(brand, bg=theme.BG_ALT)
        brand_title.pack(side="left", padx=(6, 10))
        tk.Label(brand_title, text="BlackChpok", bg=theme.BG_ALT, fg=theme.FG_BRIGHT, font=(UI_FONT, 14, "bold")).pack(side="left")
        tk.Label(brand_title, text="AI", bg=theme.BG_ALT, fg="#38BDF8", font=(UI_FONT, 14, "bold")).pack(side="left")
        for ck, ct in (("cat_file", i18n.tr("cat_file")), ("cat_edit", i18n.tr("cat_edit")), ("cat_view", i18n.tr("cat_view")), ("cat_mode", i18n.tr("cat_mode"))):
            cb = widgets.HoverLabel(brand, text=ct, command=lambda k=ck: self._menu(k), bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=(UI_FONT, 9), width=8, padx=4, pady=4)
            cb.pack(side="left", padx=1); self._buttons[ck] = cb

        self.agent_btn = widgets.HoverLabel(
            brand, text="\u25c8 \u0410\u0433\u0435\u043d\u0442 \u25be", command=lambda: self._menu("agent"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, 9), width=9, padx=4, pady=4)
        self.agent_btn.pack(side="left", padx=(2, 1))
        widgets.Tip(self.agent_btn, "\u0406\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u0438 \u0430\u0433\u0435\u043d\u0442\u0430")
        self._buttons["agent"] = self.agent_btn

        self.model_btn = widgets.HoverLabel(
            brand, text="\u229f \u043c\u043e\u0434\u0435\u043b\u044c \u25be", command=lambda: self._menu("model"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, 9), width=9, padx=4, pady=4)
        self.model_btn.pack(side="left", padx=(1, 4))
        widgets.Tip(self.model_btn, "\u0412\u0438\u0431\u0456\u0440 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0457 \u0447\u0438 \u0445\u043c\u0430\u0440\u043d\u043e\u0457 \u043c\u043e\u0434\u0435\u043b\u0456")
        self._buttons["model"] = self.model_btn

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
        files.grid(row=0, column=1, sticky="w", padx=(6, 6))
        groups = [
            [("file.new", "\uff0b", "New (Ctrl+N)"), ("file.open_dialog", "\u2398", "Open (Ctrl+O)"), ("file.save_all", "\u2913", "Save All (Ctrl+S)"),
             ("side.explorer", "\u25a4", "Files"), ("edit.search_project", "\u2315", "Search (Ctrl+Shift+F)"), ("side.changes", "\u00b1", "Changes (Git)")],
            [("side.rag", "\u25eb", "Knowledge (RAG)"), ("side.skills", "\u2726", "Skills"), ("side.tools", "\u2692", "Tools"),
             ("view.queue", "\u2261", "Queue"), ("view.autonomous", "\u221e", "Autonomous")],
            [("edit.palette", "\u2318", "Command Palette (Ctrl+Shift+P)"), ("view.settings", "\u2699", "Settings (Ctrl+,)")],
        ]
        for gi, grp in enumerate(groups):
            if gi > 0:
                tk.Frame(files, bg=theme.BORDER_SOFT, width=1, height=24).pack(side="left", padx=6, pady=4)
            for key, icon, tip in grp:
                b = widgets.HoverLabel(files, text=icon, command=lambda k=key: self._command(k), bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=4, pady=4)
                b.pack(side="left", padx=1); widgets.Tip(b, tip); self._buttons[key] = b

        agent = tk.Frame(self, bg=theme.BG_ALT)
        agent.grid(row=0, column=2, sticky="w", padx=(0, theme.SPACE_MD))

        #: Індикатор режиму, який агент обрав САМ із запиту.
        #:
        #: Стрілки «▾» тут більше немає: пункт не відкриває меню вибору
        #: режиму. Клік веде до панелі можливостей агента (скіли, черга,
        #: автономний режим), а сам режим перемикається автоматично.
        self.server_dot = tk.Label(agent, text="●", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=(UI_FONT, SMALL_SIZE))
        # clean 2026 header: self.server_dot.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.server_label = tk.Label(agent, text="сервер", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=(UI_FONT, SMALL_SIZE))
        # compact header
        widgets.Tip(self.server_dot, "Стан локального сервера моделі")
        self._labels["server"] = self.server_label

        # ── ВЕЛИКИЙ статус моделі: «● МОДЕЛЬ ОНЛАЙН / ОФЛАЙН» ─────────────
        #
        # Навіщо окремий великий індикатор. У лозі користувача модель
        # працювала на 8081, а клієнт стукав у 8080 — і в інтерфейсі це
        # виглядало як «модель не працює», без єдиного помітного сигналу,
        # де саме проблема. Тепер стан видно одним поглядом, великими
        # літерами, зеленим або червоним кружечком.
        #
        # ── ЧОМУ СПОЧАТКУ «…», А НЕ «ОФЛАЙН» ─────────────────────────────
        # Початковим значенням стояло «● МОДЕЛЬ ОФЛАЙН» ЧЕРВОНИМ. Це
        # суперечило ``_model_online = None`` нижче («стан ще невідомий») і
        # показувало користувачу червону тривогу в перші секунди запуску —
        # рівно тоді, коли автозапуск ще тільки вантажить модель (3–4 с).
        # На скріншоті це виглядало як «модель не працює» на живій моделі.
        # Тепер початковий стан — сіре «…» (невідомо), а справжній статус
        # ставить перевірка (``_confirm_model_online``).
        self.model_status = tk.Label(
            agent, text="●", bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=(UI_FONT, 14, "bold"), padx=4, pady=2,
        )
        # hidden_dup: self.model_status.pack(side="left", padx=(theme.SPACE_MD, 0))
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
        git.grid(row=0, column=4, sticky="w", padx=(4, 4))
        self.net_status = widgets.HoverLabel(
            git, text="\u25cf Internet: \u2026", command=self._refresh_internet_async,
            bg=theme.BG_CARD, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, SMALL_SIZE, "bold"), padx=8, pady=3)
        self.net_status.configure(bg="#161B22", padx=6, pady=2)
        # hidden_dup: self.net_status.pack(side="left", padx=(0, 5))
        widgets.Tip(self.net_status, "Internet ON/OFF (click to check)")
        self.quick_gemini_btn = widgets.HoverLabel(
            git, text="\u2601 Gemini", command=lambda: self._menu("model"),
            bg=theme.BG_CARD, fg=theme.ACCENT, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, SMALL_SIZE, "bold"), padx=8, pady=3)
        self.quick_gemini_btn.configure(bg="#161B22", padx=6, pady=2)
        self.quick_gemini_btn.pack(side="left", padx=(0, 4))
        widgets.Tip(self.quick_gemini_btn, "Gemini cloud tandem: permanently active")
        self.quick_web_btn = widgets.HoverLabel(
            git, text="\U0001f50e Web: ON", command=lambda: self._command("agent.toggle_web"),
            bg=theme.BG_CARD, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, SMALL_SIZE, "bold"), padx=8, pady=3)
        self.quick_web_btn.configure(bg="#161B22", padx=6, pady=2)
        self.quick_web_btn.pack(side="left", padx=(0, 4))
        widgets.Tip(self.quick_web_btn, "Multi-engine web search: permanently active")
        self.quick_hub_btn = widgets.HoverLabel(
            git, text="\U0001f4e6 Hub", command=lambda: self._command("view.model_hub"),
            bg=theme.BG_ALT, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, SMALL_SIZE), padx=4, pady=4)
        self.quick_hub_btn.pack(side="left", padx=(0, 6))
        self.pipeline_scheme_lbl = tk.Label(
            git, text="", bg=git.cget("bg"), fg=theme.FG_DIM, font=theme.font(8, "bold"),
        )
        self.pipeline_scheme_lbl.pack(side="left", padx=(2, 8))
        widgets.Tip(self.pipeline_scheme_lbl, "\u041f\u043e\u0442\u043e\u0447\u043d\u0430 \u0441\u0445\u0435\u043c\u0430 \u0440\u043e\u0431\u043e\u0442\u0438 \u0430\u0433\u0435\u043d\u0442\u0430")
        widgets.Tip(self.quick_hub_btn, "Open Model Hub")
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
        # hidden right duplicate block: right.grid(...)

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

        def _switch_ui_lang():
            _nl = i18n.toggle_lang()
            _flg = i18n.get_flag_icon(_nl)
            self.lang_btn.configure(text=f" {_nl.upper()}", image=_flg)
            self.lang_btn._flag_img = _flg
            for _k in ("cat_file", "cat_edit", "cat_view", "cat_mode", "agent", "model"):
                if _k in self._buttons:
                    try:
                        self._buttons[_k].configure(text=i18n.tr(_k))
                    except Exception:
                        pass
            try:
                i18n.apply_to_widget_tree(self.winfo_toplevel(), _nl)
            except Exception:
                pass

        _init_lang = i18n.get_lang()
        _init_flag = i18n.get_flag_icon(_init_lang)
        self.lang_btn = widgets.HoverLabel(
            right,
            text=f" {_init_lang.upper()}",
            image=_init_flag,
            compound="left",
            command=_switch_ui_lang,
            bg="#161B22",
            fg=theme.FG_BRIGHT,
            hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT,
            font=(UI_FONT, 9, "bold"),
            width=46 if _init_flag else 6,
            padx=8,
            pady=4,
        )
        self.lang_btn._flag_img = _init_flag
        self.lang_btn.pack(side="right", padx=(8, 4))
        widgets.Tip(self.lang_btn, "Language / ???? (UA / EN)")
        self._buttons["lang"] = self.lang_btn

        widgets.Tip(self.settings_btn, "Налаштування (Ctrl+,)")
        # keep visible view.settings

        self.bug_btn = widgets.HoverLabel(
            self, text="\U0001f41e", command=self.run_dropdown_self_test,
            bg=theme.BG_ALT, fg="#EF4444", hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=6, pady=4)
        self.bug_btn.place(relx=1.0, x=-12, rely=0.5, anchor="e")
        self.bug_btn.lift()
        widgets.Tip(self.bug_btn, "\u041f\u043e\u0432\u043d\u0430 \u0441\u0430\u043c\u043e\u0434\u0456\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0430 UI + \u0442\u0435\u0441\u0442\u0438 (\u043a\u043e\u043f\u0456\u044e\u0454 \u0432 \u0431\u0443\u0444\u0435\u0440 Ctrl+V)")
        self._buttons["ui.test_dropdowns"] = self.bug_btn

        self.more_btn = widgets.HoverLabel(
            right, text="⋯", command=lambda: self._menu("more"),
            bg=theme.BG_ALT, fg=theme.FG, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=(UI_FONT, ICON_SIZE), padx=8, pady=2)
        self.more_btn.pack(side="left")
        widgets.Tip(self.more_btn, "Усі команди: довідка, панелі, діагностика")
        self._buttons["more"] = self.more_btn

        bottom = tk.Frame(self, bg=theme.BORDER, height=1)
        bottom.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")
        self.bug_btn.lift()
        self.after(250, self._bind_hover_dropdowns)

    # ── дії ────────────────────────────────────────────────────────────────
    def set_reveal_visible(self, visible: bool) -> None:
        """Показати/сховати «☰» (панель згорнута/розгорнута)."""
        if bool(visible) == self._reveal_shown:
            return
        self._reveal_shown = bool(visible)
        try:
            if visible:
                # Першим у рядку бренду: ліворуч від логотипа.
                self.reveal_btn.pack(side="left", padx=(0, 4), before=self.logo)
            else:
                self.reveal_btn.pack_forget()
        except tk.TclError:
            pass

    def _command(self, key: str) -> None:
        self._on_command(key)

    def _bind_hover_dropdowns(self) -> None:
        """??????????? ??????????? ???? ?????????? ???? ??? ?????????? ??????? ? ????-????? ????????."""
        self._active_dd_key = ""
        self._dd_timer = None
        dd_keys = ("cat_file", "cat_edit", "cat_view", "cat_mode", "agent", "model", "project", "git")

        def _close_all_popups():
            try:
                top = self.winfo_toplevel()
                for w in list(top.winfo_children()):
                    if w.winfo_class() == "Toplevel":
                        try:
                            w.grab_release()
                        except Exception:
                            pass
                        w.destroy()
            except Exception:
                pass

        def _switch_to(hit_key: str, immediate: bool = False):
            if not hit_key:
                return
            if hit_key == self._active_dd_key:
                top = self.winfo_toplevel()
                tops = [w for w in top.winfo_children() if w.winfo_class() == "Toplevel" and w.winfo_ismapped()]
                if tops:
                    return
            self._active_dd_key = hit_key
            if self._dd_timer is not None:
                try:
                    self.after_cancel(self._dd_timer)
                except Exception:
                    pass
                self._dd_timer = None
            def _open_new(k=hit_key):
                _close_all_popups()
                try:
                    from . import widgets
                    if getattr(widgets.Tip, "_ACTIVE_TIP", None) is not None:
                        widgets.Tip._ACTIVE_TIP._hide()
                    top = self.winfo_toplevel()
                    for attr in ("_model_popup", "_mode_popup", "_git_popup", "_project_popup"):
                        if hasattr(top, attr):
                            setattr(top, attr, None)
                except Exception:
                    pass
                if k == "agent":
                    b = self._buttons.get("agent")
                    if b is not None:
                        class _Ev:
                            x_root = b.winfo_rootx()
                            y_root = b.winfo_rooty() + b.winfo_height() + 2
                        from . import widgets
                        widgets.context_menu(self, [
                            ("\u2726  \u0421\u043a\u0456\u043b\u0438 \u0430\u0433\u0435\u043d\u0442\u0430", lambda: self._command("side.skills")),
                            ("\u2692  \u0406\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u0438 \u0430\u0433\u0435\u043d\u0442\u0430", lambda: self._command("side.tools")),
                            ("\u25eb  \u0411\u0430\u0437\u0430 \u0437\u043d\u0430\u043d\u044c (RAG)", lambda: self._command("side.rag")),
                            ("", None),
                            ("\u2261  \u0427\u0435\u0440\u0433\u0430 \u0437\u0430\u0434\u0430\u0447", lambda: self._command("view.queue")),
                            ("\u221e  \u0410\u0432\u0442\u043e\u043d\u043e\u043c\u043d\u0438\u0439 \u0440\u0435\u0436\u0438\u043c", lambda: self._command("view.autonomous")),
                        ], _Ev())
                        return
                if k == "model":
                    b = self._buttons.get("model")
                    if b is not None:
                        class _EvM:
                            x_root = b.winfo_rootx()
                            y_root = b.winfo_rooty() + b.winfo_height() + 2
                        from . import widgets
                        from pathlib import Path as _P
                        top = self.winfo_toplevel()
                        state_file = _P.home() / "AppData" / "Roaming" / "BlackChpokIDE" / "last_model.txt"
                        saved_m = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else ""
                        cur_m = (
                            getattr(top, "_last_selected_model", "")
                            or saved_m
                            or str(getattr(getattr(top, "settings", None), "model_name", "") or "")
                        ).strip().lower()

                        def _remember_choice(name_str: str):
                            setattr(top, "_last_selected_model", name_str)
                            try:
                                state_file.parent.mkdir(parents=True, exist_ok=True)
                                state_file.write_text(name_str, encoding="utf-8")
                            except Exception:
                                pass
                            try:
                                b.configure(text=f"\u229f {name_str[:22]} \u25be")
                            except Exception:
                                pass

                        items_m = [("\u041b\u041e\u041a\u0410\u041b\u042c\u041d\u0406 \u041c\u041e\u0414\u0415\u041b\u0406 (\u041f\u041a / GPU)", None)]
                        ggufs = []
                        for d_cand in (_P.cwd() / "models", _P.cwd() / "userdata" / "models", _P.home() / "AppData" / "Roaming" / "BlackChpokIDE" / "models"):
                            if d_cand.exists():
                                ggufs.extend(sorted(d_cand.rglob("*.gguf")))
                        seen = set()
                        for gp in ggufs:
                            stem = gp.stem
                            if "mmproj" in stem.lower() or stem in seen:
                                continue
                            seen.add(stem)
                            is_cur = bool(cur_m) and (stem.lower() == cur_m or stem.lower() in cur_m or cur_m in stem.lower())
                            mark = "\u2713  " if is_cur else "\u229f  "
                            def _pick_local(ps=str(gp), ms=stem):
                                _remember_choice(ms)
                                if hasattr(top, "_select_model_path"): top._select_model_path(ps)
                                elif hasattr(top, "switch_model"): top.switch_model(ms)
                                elif hasattr(top, "show_model_selector"): top.show_model_selector()
                            items_m.append((f"{mark}{stem}", _pick_local))

                        items_m.append(("", None))
                        items_m.append(("\u0425\u041c\u0410\u0420\u041d\u0406 \u041c\u041e\u0414\u0415\u041b\u0406 (CLOUD API)", None))
                        for cid, ctitle in (("gemini-2.5-pro", "Gemini 2.5 Pro"), ("gemini-2.5-flash", "Gemini 2.5 Flash")):
                            is_c = bool(cur_m) and (cid in cur_m or ctitle.lower() in cur_m)
                            cm = "\u2713  " if is_c else "\u2601  "
                            def _pick_cloud(c=cid, ct=ctitle):
                                _remember_choice(ct)
                                if hasattr(top, "switch_model"): top.switch_model(c)
                                elif hasattr(top, "_set_cloud_model"): top._set_cloud_model(c)
                                elif hasattr(top, "show_model_selector"): top.show_model_selector()
                            items_m.append((f"{cm}{ctitle}", _pick_cloud))

                        items_m.append(("", None))
                        items_m.append(("\U0001f4e6  \u0412\u0456\u0434\u043a\u0440\u0438\u0442\u0438 \u0425\u0430\u0431 \u043c\u043e\u0434\u0435\u043b\u0435\u0439", lambda: self._command("view.model_hub")))
                        items_m.append(("\u27f3  \u041f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0438 \u0441\u0435\u0440\u0432\u0435\u0440 \u043c\u043e\u0434\u0435\u043b\u0456", lambda: top._restart_model_server() if hasattr(top, "_restart_model_server") else None))
                        widgets.context_menu(self, items_m, _EvM())
                        return
                self._menu(k)
            if immediate:
                _open_new()
            else:
                self._dd_timer = self.after(45, _open_new)

        def _on_global_motion(event):
            try:
                px, py = event.x_root, event.y_root
                hy1 = self.winfo_rooty()
                hy2 = hy1 + self.winfo_height()
                if not (hy1 <= py <= hy2):
                    return
                for k in dd_keys:
                    b = self._buttons.get(k)
                    if b is None or not b.winfo_ismapped():
                        continue
                    bx1 = b.winfo_rootx() - 2
                    bx2 = bx1 + b.winfo_width() + 4
                    if bx1 <= px <= bx2:
                        _switch_to(k, immediate=False)
                        return
            except Exception:
                pass

        # ?????? <Enter> ?? ????? ?????? (??????????? ?????? ???? ???? ?? Windows HWND)
        for k in dd_keys:
            b = self._buttons.get(k)
            if b is not None:
                b.bind("<Enter>", lambda _e, key=k: _switch_to(key, immediate=False), add="+")

        self._on_global_motion_fn = _on_global_motion
        top = self.winfo_toplevel()
        top.bind("<Motion>", _on_global_motion, add="+")

        def _on_outside_click(ev):
            try:
                w = ev.widget
                if w is None or str(w.winfo_toplevel()) != str(top):
                    return
                hy1, hy2 = self.winfo_rooty(), self.winfo_rooty() + self.winfo_height()
                if not (hy1 <= ev.y_root <= hy2):
                    _close_all_popups()
                    self._active_dd_key = ""
            except Exception:
                pass
        top.bind("<ButtonPress-1>", _on_outside_click, add="+")

    def run_dropdown_self_test(self) -> None:
        from . import ui_diagnostics
        ui_diagnostics.run_full_ui_audit(self)

    def _menu(self, which: str) -> None:
        handler = {
            "project": self._on_project_menu,
            "agent": self._on_agent_menu,
            "model": self._on_model_menu,
            "git": self._on_git_menu,
            "more": self._on_more_menu,
        }.get(which)
        if handler is None:
            if self._on_menu is not None:
                try:
                    self._on_menu(which, self._buttons.get(which, self))
                except Exception:
                    pass
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
            text, colour = "●", theme.SUCCESS
        elif online is False:
            text, colour = "●", theme.ERROR
        else:
            text, colour = "●", theme.FG_FAINT
        self._model_online = online
        try:
            self.model_status.configure(text=text, fg=colour)
        except tk.TclError:
            pass
        if detail:
            widgets.Tip(self.model_status,
                        f"Стан моделі: {detail}\nКлік — самодіагностика")




    def start_busy_animation(self) -> None:
        """????????? ?????????????? ??????? ??????????? ??????????? ? ????? ??? ??? ?????? ??????."""
        if getattr(self, "_busy_anim_on", False):
            return
        self._busy_anim_on = True
        self._busy_anim_idx = 0
        self._tick_busy_animation()

    def stop_busy_animation(self) -> None:
        """???????? ???????? ?? ????????? ????????? ??????."""
        self._busy_anim_on = False
        try:
            if hasattr(self, "_neon_bar_canvas"):
                self._neon_bar_canvas.delete("all")
        except Exception:
            pass
        try:
            self.update_pipeline_scheme()
            self._sync_quick_toggles()
        except Exception:
            pass

    def _tick_busy_animation(self) -> None:
        if not getattr(self, "_busy_anim_on", False):
            return
        try:
            if not self.winfo_exists():
                return
            palette = ["#7C6DA8", "#588B99", "#528B76", "#8E7B5B", "#8B6988", "#5E7CA6"]
            frames = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"]
            i = getattr(self, "_busy_anim_idx", 0)
            self._busy_anim_idx = i + 1
            c1 = palette[i % len(palette)]
            c2 = palette[(i + 2) % len(palette)]
            c3 = palette[(i + 4) % len(palette)]
            sp = frames[i % len(frames)]

            if hasattr(self, "pipeline_scheme_lbl"):
                cur_txt = str(self.pipeline_scheme_lbl.cget("text") or "")
                clean_txt = cur_txt.lstrip("\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f ")
                self.pipeline_scheme_lbl.configure(text=f"{sp} {clean_txt}", fg=c1)
            if hasattr(self, "quick_gemini_btn"):
                self.quick_gemini_btn.configure(fg=c2)
            if hasattr(self, "quick_web_btn"):
                self.quick_web_btn.configure(fg=c3)
            if hasattr(self, "server_dot"):
                self.server_dot.configure(fg=c1)
            if hasattr(self, "_neon_bar_canvas"):
                import math
                cv = self._neon_bar_canvas
                w = max(240, cv.winfo_width())
                cv.delete("all")
                phase = getattr(self, "_neon_bar_pos", 0.0) + 0.18
                self._neon_bar_pos = phase
                steps = 32
                sw = w / steps
                for s in range(steps):
                    t_val = phase + (s / steps) * 2.0 * math.pi
                    r = int(115 + 45 * math.sin(t_val))
                    g = int(130 + 45 * math.sin(t_val + 2.09))
                    b = int(165 + 45 * math.sin(t_val + 4.18))
                    hx = f"#{r:02x}{g:02x}{b:02x}"
                    cv.create_rectangle(int(s * sw), 0, int((s + 1) * sw) + 1, 2, fill=hx, outline="")
            self.after(120, self._tick_busy_animation)
        except Exception:
            self._busy_anim_on = False

    def update_pipeline_scheme(self, net_ok: Optional[bool] = None) -> None:
        """??????? ? ????? ???? ?????:  NEUROMESH ?? ?????? ????? ? ???? ???????."""
        lbl = getattr(self, "pipeline_scheme_lbl", None)
        if lbl is None:
            return
        try:
            from . import config as _cfg
            st = _cfg.Settings.load()
            llm = getattr(st, "llm", None)
            cloud = getattr(st, "cloud", None)
            b_url = str(getattr(llm, "base_url", "") or "").lower()
            m_raw = str(getattr(llm, "model", "") or "Local").split("/")[-1].replace(".gguf", "")
            if len(m_raw) > 20:
                m_raw = m_raw[:18] + ".."
            is_local = b_url.startswith(("native://", "inproc://", "http://127.0.0.1", "http://localhost"))
            c_name = str(getattr(cloud, "model", "") or "Gemini").split("/")[-1]
            if len(c_name) > 18:
                c_name = c_name[:16] + ".."
            if net_ok is None:
                net_ok = "ON" in str(self.net_status.cget("text") or "")
            if is_local:
                if net_ok:
                    scheme = f"\U0001f9e0 NEUROMESH \u21c4 \U0001f5a5 {m_raw} \u2794 \U0001f310 \u0406\u043d\u0442\u0435\u0440\u043d\u0435\u0442 \u2794 \u2601 \u041f\u043e\u043c\u0456\u0447\u043d\u0438\u043a {c_name}"
                    col = theme.SUCCESS
                else:
                    scheme = f"\U0001f9e0 NEUROMESH \u21c4 \U0001f5a5 {m_raw} \u2794 \U0001f4f4 \u041e\u0444\u043b\u0430\u0439\u043d"
                    col = theme.WARN
            else:
                scheme = f"\U0001f9e0 NEUROMESH \u21c4 \u2601 {m_raw} \u2794 \U0001f310 \u0406\u043d\u0442\u0435\u0440\u043d\u0435\u0442 (\u043d\u0430\u0432\u0447\u0430\u0454 \U0001f5a5 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u0443)"
                col = theme.ACCENT
            lbl.configure(text=scheme, fg=col)
        except Exception:
            pass

    def _sync_quick_toggles(self) -> None:
        try:
            from . import config as _cfg
            st = _cfg.Settings.load()
            w_on = True
            g_on = True
            self.quick_web_btn.configure(text=f"\U0001f50e Web: {'ON' if w_on else 'OFF'}", fg=theme.SUCCESS if w_on else theme.FG_FAINT)
            self.update_pipeline_scheme()
            self.quick_gemini_btn.configure(text=f"\u2601 Gemini: {'ON' if g_on else 'OFF'}", fg=theme.ACCENT if g_on else theme.FG_FAINT)
        except Exception:
            pass

    def _toggle_quick_web(self) -> None:
        try:
            from . import config as _cfg
            st = _cfg.Settings.load()
            st.agent.web_every_turn = not bool(getattr(getattr(st, "agent", None), "web_every_turn", True))
            st.save()
            self._sync_quick_toggles()
        except Exception:
            pass

    def _toggle_quick_gemini(self) -> None:
        try:
            from . import config as _cfg
            st = _cfg.Settings.load()
            if getattr(st, "cloud", None) is not None:
                st.cloud.enabled = not bool(getattr(st.cloud, "enabled", True))
                st.save()
            self._sync_quick_toggles()
        except Exception:
            pass

    def _refresh_internet_async(self) -> None:
        import threading
        def _w():
            try:
                from . import internet
                ok, det = internet.connectivity()
            except Exception as e:
                ok, det = False, str(e)
            def _u():
                try:
                    self.net_status.configure(text=f"\u25cf Internet: {'ON' if ok else 'OFF'}", fg=theme.SUCCESS if ok else theme.ERROR)
                    widgets.Tip(self.net_status, f"Internet: {det}")
                    self.update_pipeline_scheme(net_ok=ok)
                    self._sync_quick_toggles()
                except Exception:
                    pass
            try:
                self.after(0, _u)
            except Exception:
                pass
        threading.Thread(target=_w, daemon=True).start()
        try:
            self.after(25000, self._refresh_internet_async)
        except Exception:
            pass

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
            full = "●" if online is True else (
                "●" if online is False else "●")
            self.model_status.configure(text=short if mode == "narrow" else full)
        except tk.TclError:
            pass

    @property
    def hidden_commands(self) -> set[str]:
        """Ключі команд, прихованих адаптивним режимом (усі доступні з «⋯»)."""
        return set(getattr(self, "_hidden", set()))


__all__ = ["COMPACT_WIDTH", "HEADER_HEIGHT", "HeaderBar", "NARROW_WIDTH"]
