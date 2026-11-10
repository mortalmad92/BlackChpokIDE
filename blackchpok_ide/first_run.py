"""Майстер першого запуску: залізо → бібліотеки → програми → модель.

Сценарій для користувача:

  1. **Залізо** — показує CPU, RAM, GPU і вільне місце, підбирає модель.
  2. **Бібліотеки** — перевіряє пакети Python і ставить відсутні через pip.
  3. **Програми** — перевіряє git/node/npm; ставить через winget, а якщо
     не вийшло — відкриває сторінку завантаження **у вбудованому браузері**.
  4. **Модель** — ставить рушій llama.cpp, качає модель і піднімає сервер.

Кроки можна проходити по одному («Далі») або натиснути «Зробити все» й
дочекатись кінця. Усе важке — у фонових потоках, вікно показує смугу
прогресу й не «замерзає».

Головне, що змінилось: раніше майстер ставив лише модель, а бібліотеки й
програми лишались на користувача — і перший запуск перетворювався на
«постав це сам». Тепер майстер бачить усе середовище й закриває його сам.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Optional

from . import env_setup as env
from . import hardware as hw
from . import model_hub as hub
from . import runtime as rt
from . import theme, widgets

#: Кроки майстра (ключ, підпис на смузі кроків).
STEPS: tuple[tuple[str, str], ...] = (
    ("hardware", "Залізо"),
    ("libs", "Бібліотеки"),
    ("tools", "Програми"),
    ("model", "Модель"),
)


class FirstRunWizard(tk.Toplevel):
    """Модальне вікно першого запуску з чотирма кроками."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, settings,
                 on_done: Optional[Callable[[bool], None]] = None) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.settings = settings
        self.on_done = on_done
        self.profile = hw.HardwareProfile()
        self.choice = hw.MODEL_CATALOG[0]
        self.download: Optional[hub.Download] = None
        self.install_job: Optional[rt.EngineInstall] = None
        self.server: Optional[rt.LocalServer] = None
        self._poll_after: Optional[str] = None
        self._stage = "detect"     # detect | install | download | start | done | error
        self._cancelled = False
        #: Який крок показуємо (ключ зі :data:`STEPS`).
        self.step = "hardware"
        #: Стани пакетів і програм (заповнюються під час перевірки).
        self.lib_rows: list[env.ItemState] = []
        self.tool_rows: list[env.ItemState] = []
        #: Результати останньої установки — для підсумку на кроці.
        self._install_notes: list[str] = []
        self._ui_queue: "queue.Queue[tuple[Any, tuple[Any, ...], dict[str, Any]]]" = queue.Queue()

        self.title("Перший запуск · BlackChpok IDE")
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._skip)

        self._build()
        self._center(master)
        threading.Thread(target=self._detect, daemon=True).start()
        threading.Thread(target=self._scan_environment, daemon=True).start()
        self._poll()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        self.body = body

        ttk.Label(body, text="Вітаємо в BlackChpok IDE", font=self.fonts.ui_title).grid(
            row=0, column=0, sticky="w")
        ttk.Label(body,
                  text="Налаштую все саме: перевірю залізо, доставлю бібліотеки, "
                       "встановлю потрібні програми й підключу локальну модель.",
                  wraplength=600, justify="left", foreground=theme.FG_DIM).grid(
            row=1, column=0, sticky="w", pady=(6, 10))

        # ── смуга кроків
        self.step_bar = tk.Frame(body, bg=theme.BG)
        self.step_bar.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._step_labels: dict[str, tk.Label] = {}
        for index, (key, label) in enumerate(STEPS):
            chip = tk.Label(self.step_bar, text=f"{index + 1}. {label}", bg=theme.BG_ALT,
                            fg=theme.FG_FAINT, font=("Segoe UI", 8),
                            padx=10, pady=4, cursor="hand2")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda _e, k=key: self.show_step(k))
            self._step_labels[key] = chip

        # ── вміст кроку (перемикається)
        self.page_host = ttk.Frame(body)
        self.page_host.grid(row=3, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        # Без цього рядок не розтягується й сторінка зі списками лишає
        # піввікна порожнім — прокрутка виглядала обрізаною.
        self.page_host.rowconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        self.pages: dict[str, ttk.Frame] = {}
        self._build_hardware_page()
        self._build_libs_page()
        self._build_tools_page()
        self._build_model_page()

        # ── прогрес
        progress_box = ttk.Frame(body)
        progress_box.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        progress_box.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.stage_label = ttk.Label(progress_box, text="Визначаю залізо…",
                                     foreground=theme.FG, wraplength=600, justify="left")
        self.stage_label.grid(row=1, column=0, sticky="w", pady=(6, 0))

        # ── кнопки
        footer = ttk.Frame(body)
        footer.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        self.skip_btn = ttk.Button(footer, text="Пропустити", style="Icon.TButton",
                                   command=self._skip)
        self.skip_btn.pack(side="left")
        self.cancel_btn = ttk.Button(footer, text="Скасувати", style="Icon.TButton",
                                     command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(6, 0))
        self.back_btn = ttk.Button(footer, text="‹ Назад", style="Icon.TButton",
                                   command=self._prev_step, state="disabled")
        self.back_btn.pack(side="left", padx=(6, 0))
        self.go_btn = ttk.Button(footer, text="Далі", style="Accent.TButton",
                                 command=self._next_step)
        self.go_btn.pack(side="right")
        self.all_btn = ttk.Button(footer, text="Зробити все", style="Flat.TButton",
                                  command=self._run_all)
        self.all_btn.pack(side="right", padx=(0, 6))
        # Підказки: у майстрі чотири кнопки з короткими підписами, і без
        # пояснення різниця між «Далі» та «Зробити все» неочевидна.
        for button, tip in (
            (self.skip_btn, "Пропустити майстер: IDE запуститься без "
                            "доставлення бібліотек і моделі"),
            (self.cancel_btn, "Скасувати поточну дію (встановлення, "
                              "завантаження) і лишити все як було"),
            (self.back_btn, "Повернутися до попереднього кроку"),
            (self.go_btn, "Перейти до наступного кроку налаштування"),
            (self.all_btn, "Пройти всі кроки одразу: залізо, бібліотеки, "
                           "програми, рушій і модель"),
        ):
            widgets.Tip(button, tip)

        self.show_step("hardware")

    # ── сторінка: залізо ───────────────────────────────────────────────────
    def _build_hardware_page(self) -> None:
        page = ttk.Frame(self.page_host)
        page.columnconfigure(0, weight=1)
        self.pages["hardware"] = page

        hw_box = ttk.LabelFrame(page, text=" Твоє залізо ", padding=12)
        hw_box.grid(row=0, column=0, sticky="ew")
        hw_box.columnconfigure(1, weight=1)
        self.hw_rows: dict[str, ttk.Label] = {}
        for index, (key, label) in enumerate((
            ("cpu", "Процесор"),
            ("ram", "Пам'ять"),
            ("gpu", "Відеокарта"),
            ("disk", "Вільно на диску"),
            ("budget", "Під модель"),
        )):
            ttk.Label(hw_box, text=label + ":", foreground=theme.FG_DIM).grid(
                row=index, column=0, sticky="w", pady=1)
            value = ttk.Label(hw_box, text="…")
            value.grid(row=index, column=1, sticky="w", padx=(10, 0), pady=1)
            self.hw_rows[key] = value

        model_box = ttk.LabelFrame(page, text=" Рекомендована модель ", padding=12)
        model_box.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        model_box.columnconfigure(0, weight=1)

        self.model_label = ttk.Label(model_box, text="Підбираю…", font=self.fonts.ui_bold)
        self.model_label.grid(row=0, column=0, sticky="w")
        self.model_note = ttk.Label(model_box, text="", foreground=theme.FG_DIM,
                                    wraplength=560, justify="left")
        self.model_note.grid(row=1, column=0, sticky="w", pady=(2, 6))

        self.alternative = ttk.Combobox(model_box, state="readonly", values=[])
        self.alternative.grid(row=2, column=0, sticky="ew")
        self.alternative.bind("<<ComboboxSelected>>", self._on_alt_selected)
        widgets.Tip(
            self.alternative,
            "Вибрати іншу модель із каталогу. Залізо й сумісність "
            "перераховуються автоматично")
        # ── Список не має бути порожнім до визначення заліза ──────────────
        # Раніше ``values=[]`` заповнювався лише після ``_detect``, тож на
        # першому кроці користувач бачив порожній спадний список — виглядало
        # як зламаний. Кладемо каталог ОДРАЗУ, а ``_detect`` лише уточнює
        # підписи (додає режим GPU/CPU).
        self._option_map = {}
        self.alternative.configure(values=self._catalog_labels())

    # ── сторінка: бібліотеки ───────────────────────────────────────────────
    def _build_libs_page(self) -> None:
        page = ttk.Frame(self.page_host)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.pages["libs"] = page

        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.libs_title = ttk.Label(header, text="Перевіряю бібліотеки Python…",
                                    font=self.fonts.ui_bold)
        self.libs_title.grid(row=0, column=0, sticky="w")
        self.libs_btn = ttk.Button(header, text="Встановити відсутні",
                                   style="Flat.TButton", command=self._install_libs)
        self.libs_btn.grid(row=0, column=1, sticky="e")
        widgets.Tip(self.libs_btn,
                    "Поставити відсутні бібліотеки Python у .venv проєкту. "
                    "Без них частина можливостей IDE вимикається")
        self.libs_note = ttk.Label(page, text="", foreground=theme.FG_DIM,
                                   wraplength=560, justify="left")
        self.libs_note.grid(row=2, column=0, sticky="w", pady=(6, 0))

        self.libs_host = widgets.ScrollFrame(page, bg=theme.BG)
        self.libs_host.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    # ── сторінка: програми ─────────────────────────────────────────────────
    def _build_tools_page(self) -> None:
        page = ttk.Frame(self.page_host)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.pages["tools"] = page

        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.tools_title = ttk.Label(header, text="Перевіряю програми…",
                                     font=self.fonts.ui_bold)
        self.tools_title.grid(row=0, column=0, sticky="w")
        self.tools_btn = ttk.Button(header, text="Встановити відсутні",
                                    style="Flat.TButton", command=self._install_tools)
        self.tools_btn.grid(row=0, column=1, sticky="e")
        widgets.Tip(self.tools_btn,
                    "Поставити відсутні зовнішні програми (напр. git) через winget")
        self.tools_note = ttk.Label(page, text="", foreground=theme.FG_DIM,
                                    wraplength=560, justify="left")
        self.tools_note.grid(row=2, column=0, sticky="w", pady=(6, 0))

        self.tools_host = widgets.ScrollFrame(page, bg=theme.BG)
        self.tools_host.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    # ── сторінка: модель ───────────────────────────────────────────────────
    def _build_model_page(self) -> None:
        page = ttk.Frame(self.page_host)
        page.columnconfigure(0, weight=1)
        self.pages["model"] = page

        ttk.Label(page, text="Локальна модель", font=self.fonts.ui_bold).grid(
            row=0, column=0, sticky="w")
        self.model_summary = ttk.Label(
            page, text="Модель обрано на кроці «Залізо».",
            foreground=theme.FG_DIM, wraplength=560, justify="left")
        self.model_summary.grid(row=1, column=0, sticky="w", pady=(4, 10))

        self.engine_label = ttk.Label(page, text="", foreground=theme.FG_DIM,
                                      wraplength=560, justify="left")
        self.engine_label.grid(row=2, column=0, sticky="w")

        buttons = ttk.Frame(page)
        buttons.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.install_model_btn = ttk.Button(
            buttons, text="Встановити рушій і модель", style="Accent.TButton",
            command=self._start)
        self.install_model_btn.pack(side="left")
        widgets.Tip(self.install_model_btn,
                    "Завантажити llama.cpp і локальну модель та одразу "
                    "завантажити її у вбудований рушій IDE")
        skip_btn = ttk.Button(buttons, text="Хаб моделей пізніше", style="Icon.TButton",
                              command=self._skip)
        skip_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(skip_btn,
                    "Пропустити цей крок. Модель можна вибрати пізніше "
                    "в «Хабі моделей»")

    def _center(self, master: tk.Misc) -> None:
        """Розмістити майстер по центру батька, гарантовано в межах екрана."""
        widgets.place_window(self, width=680, height=620, center_on=master)

    # ── навігація кроками ──────────────────────────────────────────────────
    def show_step(self, key: str) -> None:
        """Показати крок і підсвітити його на смузі кроків."""
        if key not in self.pages:
            return
        self.step = key
        for name, page in self.pages.items():
            try:
                if name == key:
                    page.grid(row=0, column=0, sticky="nsew")
                else:
                    page.grid_remove()
            except tk.TclError:
                continue
        for name, label in self._step_labels.items():
            try:
                active = name == key
                label.configure(bg=theme.BG_ACTIVE if active else theme.BG_ALT,
                                fg=theme.FG_BRIGHT if active else theme.FG_FAINT)
            except tk.TclError:
                continue
        try:
            self.back_btn.state(["!disabled"] if self._step_index() > 0 else ["disabled"])
            self.go_btn.configure(text="Готово" if key == "model" else "Далі")
        except tk.TclError:
            pass
        if key == "model":
            self._paint_model_page()

    def _step_index(self) -> int:
        keys = [key for key, _label in STEPS]
        try:
            return keys.index(self.step)
        except ValueError:
            return 0

    def _next_step(self) -> None:
        keys = [key for key, _label in STEPS]
        index = self._step_index()
        if index >= len(keys) - 1:
            self._skip()
            return
        self.show_step(keys[index + 1])

    def _prev_step(self) -> None:
        keys = [key for key, _label in STEPS]
        index = self._step_index()
        if index > 0:
            self.show_step(keys[index - 1])

    # ── крок 1: залізо ─────────────────────────────────────────────────────
    def _detect(self) -> None:
        try:
            profile = hw.detect()
            choice = hw.recommend(profile)
            fitted = hw.fit(profile, choice)
        except Exception as exc:  # noqa: BLE001 - показуємо проблему, не падаємо
            self._ui(self._fail, f"Не вдалось визначити залізо: {exc}")
            return
        self._ui(self._apply_hardware, profile, choice, fitted)

    def _apply_hardware(self, profile: hw.HardwareProfile, choice: hw.ModelChoice,
                        fitted: hw.ModelFit) -> None:
        self.profile = profile
        self.choice = choice
        ram = profile.ram_available_gb or profile.ram_total_gb
        gpu = profile.best_gpu
        self.hw_rows["cpu"].configure(
            text=f"{profile.cpu_name or 'невідомо'} ({profile.cpu_threads} потоків)")
        self.hw_rows["ram"].configure(
            text=f"{ram:.0f} ГБ доступно з {profile.ram_total_gb:.0f} ГБ")
        self.hw_rows["gpu"].configure(
            text=f"{gpu.name} · {gpu.vram_gb:.0f} ГБ VRAM" if gpu and gpu.vram_gb
            else "інтегрована або відсутня (працюватиме CPU)")
        self.hw_rows["disk"].configure(text=f"{profile.disk_free_gb:.0f} ГБ")
        self.hw_rows["budget"].configure(
            text=f"{profile.usable_gb:.0f} ГБ (режим: {profile.backend.upper()})")

        size_gb = choice.approx_gb
        speed = {"gpu": "повністю на GPU", "hybrid": "частково на GPU",
                 "cpu": "на CPU (повільно)"}[fitted.speed]
        self.model_label.configure(text=f"{choice.label} · {size_gb:.1f} ГБ")
        self.model_note.configure(
            text=f"{choice.note}. Працюватиме {speed}, контекст "
                 f"{fitted.plan.ctx_size // 1024}K токенів.")

        options = []
        self._option_map: dict[str, hw.ModelChoice] = {}
        for candidate in hw.MODEL_CATALOG:
            fit = hw.fit(profile, candidate)
            label = f"{candidate.label} — {candidate.approx_gb:.1f} ГБ ({fit.speed})"
            options.append(label)
            self._option_map[label] = candidate
        self.alternative.configure(values=options)
        current = f"{choice.label} — {size_gb:.1f} ГБ ({fitted.speed})"
        if current in self._option_map:
            self.alternative.set(current)

        if profile.disk_free_gb and profile.disk_free_gb < size_gb * 1.5:
            self._set_stage(f"Мало місця: потрібно ~{size_gb * 1.5:.0f} ГБ, вільно "
                            f"{profile.disk_free_gb:.0f} ГБ. Вибери меншу модель.",
                            error=True)
            return
        self._set_stage("Залізо визначено. Далі — бібліотеки й програми.")
        self._paint_model_page()

    def _catalog_labels(self) -> list[str]:
        """Підписи каталогу для спадного списку — без визначення заліза.

        Потрібні, щоб список був непорожнім одразу після відкриття майстра:
        визначення заліза йде у фоні й може тривати секунди.
        """
        labels: list[str] = []
        self._option_map = getattr(self, "_option_map", {})
        for candidate in hw.MODEL_CATALOG:
            label = f"{candidate.label} — {candidate.approx_gb:.1f} ГБ"
            labels.append(label)
            self._option_map[label] = candidate
        return labels

    def _on_alt_selected(self, _event=None) -> None:
        chosen = self._option_map.get(self.alternative.get())
        if chosen is None:
            return
        self.choice = chosen
        fitted = hw.fit(self.profile, chosen)
        speed = {"gpu": "повністю на GPU", "hybrid": "частково на GPU",
                 "cpu": "на CPU (повільно)"}[fitted.speed]
        self.model_label.configure(text=f"{chosen.label} · {chosen.approx_gb:.1f} ГБ")
        self.model_note.configure(
            text=f"{chosen.note}. Працюватиме {speed}, "
                 f"контекст {fitted.plan.ctx_size // 1024}K.")
        self._paint_model_page()

    def _paint_model_page(self) -> None:
        """Оновити сторінку моделі (стан рушія й обрана модель)."""
        try:
            self.model_summary.configure(
                text=f"Обрана модель: {self.choice.label} · "
                     f"{self.choice.approx_gb:.1f} ГБ")
            engine = ("Рушій llama.cpp: встановлено"
                      if rt.engine_installed()
                      else "Рушій llama.cpp: буде встановлено зараз")
            self.engine_label.configure(text=engine)
        except (tk.TclError, AttributeError):
            pass

    # ── крок 2 і 3: бібліотеки та програми ────────────────────────────────
    def _scan_environment(self) -> None:
        """Перевірити пакети й програми у фоні."""
        try:
            libs = env.check_requirements()
        except Exception as exc:  # noqa: BLE001 - перевірка не має валити вікно
            self._ui(self._set_stage, f"Не вдалось перевірити бібліотеки: {exc}", error=True)
            libs = []
        try:
            tools = env.check_tools()
        except Exception as exc:  # noqa: BLE001
            self._ui(self._set_stage, f"Не вдалось перевірити програми: {exc}", error=True)
            tools = []
        self._ui(self._apply_environment, libs, tools)

    def _apply_environment(self, libs: list[env.ItemState],
                           tools: list[env.ItemState]) -> None:
        self.lib_rows = libs
        self.tool_rows = tools
        self._draw_rows(self.libs_host.inner, libs, self._libs_summary)
        self._draw_rows(self.tools_host.inner, tools, self._tools_summary)
        libs_stats = env.summary(libs)
        tools_stats = env.summary(tools)
        try:
            self.libs_title.configure(
                text=f"Бібліотеки Python — {libs_stats['ok']} з {libs_stats['total']}")
            self.libs_note.configure(text=env.describe_problems(libs))
            self.tools_title.configure(
                text=f"Програми — {tools_stats['ok']} з {tools_stats['total']}")
            note = env.describe_problems(tools)
            if not env.winget_available():
                note += ("  winget не знайдено: відсутні програми відкриються "
                         "сторінкою завантаження у вбудованому браузері.")
            self.tools_note.configure(text=note)
        except tk.TclError:
            pass

    def _libs_summary(self) -> str:
        return env.describe_problems(self.lib_rows)

    def _tools_summary(self) -> str:
        return env.describe_problems(self.tool_rows)

    def _draw_rows(self, host: tk.Misc, rows: list[env.ItemState],
                   summary_fn: Callable[[], str]) -> None:
        """Намалювати список елементів середовища."""
        for child in host.winfo_children():
            child.destroy()
        if not rows:
            tk.Label(host, text="Перевіряю…", bg=theme.BG, fg=theme.FG_FAINT,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=6, pady=6)
            return
        for item in rows:
            row = tk.Frame(host, bg=theme.BG_CARD, highlightthickness=1,
                           highlightbackground=theme.BORDER)
            row.pack(fill="x", padx=2, pady=(0, 3))
            row.columnconfigure(1, weight=1)

            if item.ok:
                mark, colour = "✓", theme.SUCCESS
            elif item.required:
                mark, colour = "✗", theme.ERROR
            else:
                mark, colour = "○", theme.WARN
            tk.Label(row, text=mark, bg=theme.BG_CARD, fg=colour,
                     font=("Segoe UI", 10)).grid(row=0, column=0, rowspan=2,
                                                 padx=(8, 6), pady=4, sticky="n")
            tk.Label(row, text=item.label, bg=theme.BG_CARD, fg=theme.FG,
                     font=("Segoe UI", 9, "bold"), anchor="w").grid(
                row=0, column=1, sticky="w", pady=(6, 0))
            detail = item.purpose
            if item.detail:
                detail += f" · {item.detail}"
            tk.Label(row, text=detail, bg=theme.BG_CARD, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), anchor="w", justify="left",
                     wraplength=380).grid(row=1, column=1, sticky="w", pady=(0, 6))
            if item.actionable:
                widgets.Chip(row, "Встановити" if item.install_kind else "Сторінка",
                             lambda i=item: self._install_one(i),
                             font=("Segoe UI", 8)).grid(row=0, column=2, rowspan=2,
                                                        padx=(0, 6))

    def _install_one(self, item: env.ItemState) -> None:
        """Поставити один елемент (у фоні)."""
        self._set_stage(f"Встановлюю {item.label}…")
        self.cancel_btn.state(["!disabled"])

        def work() -> None:
            result = env.install_item(
                item, on_status=lambda text: self._ui(self._set_stage, text))
            self._ui(self._after_install, [result])

        threading.Thread(target=work, daemon=True).start()

    def _install_libs(self) -> None:
        self._install_group(self.lib_rows, "бібліотеки")

    def _install_tools(self) -> None:
        self._install_group(self.tool_rows, "програми")

    def _install_group(self, rows: list[env.ItemState], title: str) -> None:
        """Поставити всі відсутні елементи групи (у фоні)."""
        pending = [item for item in rows if not item.ok and item.actionable]
        if not pending:
            self._set_stage(f"Немає чого встановлювати: {title} на місці.")
            return
        self.cancel_btn.state(["!disabled"])
        self._set_stage(f"Встановлюю {title}: {len(pending)}…")

        def work() -> None:
            results = env.install_missing(
                rows,
                on_status=lambda text: self._ui(self._set_stage, text),
            )
            self._ui(self._after_install, results)

        threading.Thread(target=work, daemon=True).start()

    def _after_install(self, results: list[env.StepResult]) -> None:
        """Оновити стани після установки й показати підсумок."""
        if self._cancelled:
            return
        done = sum(1 for result in results if result.ok)
        opened = sum(1 for result in results if result.opened_page)
        notes = [result.message for result in results if result.message]
        self._install_notes = notes
        tail = f" Готово: {done} з {len(results)}." if results else ""
        if opened:
            tail += f" Відкрито сторінок завантаження: {opened} (у вбудованому браузері)."
        self._set_stage("Перевіряю стан заново…" + tail)

        def refresh() -> None:
            rows = env.refresh_states()
            libs = [row for row in rows if row.key in {r.package for r in env.REQUIREMENTS}]
            tools = [row for row in rows if row.key not in {r.package for r in env.REQUIREMENTS}]
            self._ui(self._apply_environment, libs, tools)
            self._ui(self._set_stage, self._install_report(notes, tail))

        threading.Thread(target=refresh, daemon=True).start()

    @staticmethod
    def _install_report(notes: list[str], tail: str) -> str:
        shown = notes[-2:] if notes else []
        text = " ".join(shown) + tail
        return text.strip() or "Готово."

    # ── крок 4: модель ────────────────────────────────────────────────────
    def _start(self) -> None:
        self.show_step("model")
        self.install_model_btn.state(["disabled"])
        self.go_btn.state(["disabled"])
        self.skip_btn.state(["disabled"])
        self.all_btn.state(["disabled"])
        self.cancel_btn.state(["!disabled"])
        self.progress.configure(value=0)
        self._stage = "install"
        threading.Thread(target=self._work, daemon=True).start()

    def _run_all(self) -> None:
        """Пройти все: бібліотеки, програми, потім модель."""
        self._set_stage("Ставлю бібліотеки й програми…")
        self.all_btn.state(["disabled"])
        self.cancel_btn.state(["!disabled"])

        def work() -> None:
            rows = env.check_all()
            results = env.install_missing(
                rows, on_status=lambda text: self._ui(self._set_stage, text))
            self._ui(self._after_install, results)
            if self._cancelled:
                return
            self._ui(self._start)

        threading.Thread(target=work, daemon=True).start()

    def _work(self) -> None:
        try:
            if not rt.engine_installed():
                self._stage_text("Встановлюю рушій llama.cpp (один раз)…")
                job = rt.EngineInstall(profile=self.profile,
                                       on_status=lambda text: self._ui(self._stage_text, text))
                self.install_job = job
                if not job.run_blocking():
                    self._ui(self._fail, job.error or "Не вдалось встановити рушій.")
                    return
                self.install_job = None
            if self._cancelled:
                return

            self._stage = "download"
            target = hub.models_dir() / hub.safe_filename(self.choice.filename)
            self._ui(self._stage_text,
                     f"Завантажую {self.choice.label} ({self.choice.approx_gb:.1f} ГБ)…")
            if not target.exists():
                url = self.choice.url
                task = hub.Download(url, target, expected_size=0)
                self.download = task
                task.run_blocking()
                if self._cancelled:
                    return
                if task.error:
                    self._ui(self._fail, f"Завантаження не вдалось: {task.error}")
                    return
                self.download = None

            if self._cancelled:
                return
            self._stage = "start"
            self._ui(self._stage_text, "Запускаю модель…")
            plan = hw.fit(self.profile, self.choice).plan
            port = rt.free_port(8080)
            config = rt.ServerConfig(
                model_path=str(target), port=port, plan=plan,
                alias=self.choice.short_name,
            )
            server = rt.LocalServer(config)
            server.start()
            self.server = server
            ok, detail = server.wait_ready(
                timeout=300, on_status=lambda text: self._ui(self._stage_text, text))
            if not ok:
                self._ui(self._fail, f"Модель не запустилась: {detail[:300]}")
                return
            self._ui(self._finish, server.base_url, self.choice)
        except Exception as exc:  # noqa: BLE001 - показуємо користувачу
            self._ui(self._fail, f"{type(exc).__name__}: {exc}")

    def _finish(self, base_url: str, choice: hw.ModelChoice) -> None:
        self._stage = "done"
        self.progress.configure(value=100)
        self.cancel_btn.state(["disabled"])
        self.settings.llm.base_url = base_url
        self.settings.llm.model = choice.short_name
        self.settings.llm.api_key = rt.MANAGED_API_KEY
        self.settings.llm.auto_detect = False
        self.settings.first_run_done = True
        if hasattr(self.settings, "engine"):
            self.settings.engine.managed = True
            self.settings.engine.model_path = str(
                hub.models_dir() / hub.safe_filename(choice.filename))
            self.settings.engine.port = self.server.config.port if self.server else 0
        self.settings.save()
        self._set_stage(f"✓ Готово! Модель {choice.label} працює. Можна закривати вікно.")
        self.go_btn.configure(text="Продовжити", command=self._close_ok)
        self.go_btn.state(["!disabled"])
        self.skip_btn.configure(text="Закрити", command=self._close_ok)

    def _close_ok(self) -> None:
        self._close(True)

    def _skip(self) -> None:
        """Користувач відмовився: більше не показуємо майстер."""
        self.settings.first_run_done = True
        self.settings.save()
        self._close(False)

    def _cancel(self) -> None:
        self._cancelled = True
        if self.download is not None:
            self.download.cancel()
        if self.install_job is not None:
            self.install_job.cancel()
        if self.server is not None:
            self.server.stop()
            self.server = None
        self._set_stage("Скасовано.")
        self.cancel_btn.state(["disabled"])
        for button in (self.go_btn, self.all_btn, self.skip_btn):
            try:
                button.state(["!disabled"])
            except tk.TclError:
                pass
        self.install_model_btn.state(["!disabled"])

    def _close(self, ok: bool) -> None:
        if self._poll_after:
            try:
                self.after_cancel(self._poll_after)
            except (tk.TclError, ValueError):
                pass
        if self.on_done:
            self.on_done(ok)
        self.destroy()

    # ── службове ───────────────────────────────────────────────────────────
    def _poll(self) -> None:
        try:
            self._drain_ui()
            self._poll_progress()
        finally:
            try:
                self._poll_after = (self.after(200, self._poll) if self._timer_alive() else None)
            except tk.TclError:
                pass

    def _poll_progress(self) -> None:
        task = self.download if self._stage == "download" else None
        if task is not None:
            state = task.state
            self.progress.configure(value=state.percent)
            if state.total:
                text = (f"Завантажую {self.choice.label}: {state.percent:.0f}%  ·  "
                        f"{state.downloaded / 2**30:.2f} з {state.total / 2**30:.2f} ГБ")
                if state.speed_text:
                    text += f"  ·  {state.speed_text}"
                if state.eta_text:
                    text += f"  ·  лишилось ~{state.eta_text}"
                self._set_stage(text)
        job = self.install_job
        if job is not None and job.download is not None and job.download.running:
            state = job.download.state
            self.progress.configure(value=state.percent)
            if state.speed_text:
                self._set_stage(f"Рушій llama.cpp: {state.percent:.0f}%  ·  {state.speed_text}")

    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _ui(self, func, *args, **kwargs) -> None:
        """Поставити оновлення в чергу (віджети — лише з головного потоку)."""
        self._ui_queue.put((func, args, kwargs))

    def _drain_ui(self) -> None:
        for _ in range(100):
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                func(*args, **kwargs)
            except tk.TclError:
                pass

    def _stage_text(self, text: str) -> None:
        self._set_stage(text)

    def _set_stage(self, text: str, *, error: bool = False) -> None:
        try:
            self.stage_label.configure(text=text, foreground=theme.ERROR if error else theme.FG)
            self.update_idletasks()
        except tk.TclError:
            pass

    def _fail(self, message: str) -> None:
        self._stage = "error"
        self._set_stage(f"✗ {message}", error=True)
        self.cancel_btn.state(["disabled"])
        self.install_model_btn.configure(text="Спробувати ще раз")
        self.install_model_btn.state(["!disabled"])
        self.go_btn.configure(text="Далі", command=self._next_step)
        self.go_btn.state(["!disabled"])
        for button in (self.skip_btn, self.all_btn):
            try:
                button.state(["!disabled"])
            except tk.TclError:
                pass
        if self.server is not None:
            self.server.stop()
            self.server = None

    def on_close_cleanup(self) -> None:
        """Зупинити сервер, якщо майстер закрили посеред роботи."""
        if self._stage not in {"done"} and self.server is not None:
            self.server.stop()
            self.server = None


__all__ = ["FirstRunWizard", "STEPS"]
