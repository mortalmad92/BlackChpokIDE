"""Діалог налаштувань: модель, редактор, агент."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from . import browser_panel, cloud_agents, secrets, social, theme, voice, widgets
from .agent import ModelProbe
from .config import Settings
from .llm_client import KNOWN_ENDPOINTS

LOG = __import__("logging").getLogger("blackchpok.settings")


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, fonts: theme.Theme, settings: Settings,
                 on_saved: Optional[Callable[[], None]] = None,
                 on_open_hub: Optional[Callable[[], None]] = None,
                 on_open_panel: Optional[Callable[[str], None]] = None,
                 on_first_run: Optional[Callable[[], None]] = None) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.settings = settings
        self.on_saved = on_saved
        self.on_open_hub = on_open_hub
        #: Відкрити панель за ключем (``mcp``, ``rag``, ``queue``…).
        #: Ліворуч лишились самі чати, тож усі розділи тепер тут.
        self.on_open_panel = on_open_panel
        #: Відкрити майстер налаштування (залізо, бібліотеки, програми, модель).
        self.on_first_run = on_first_run
        self._probe_queue: "queue.Queue[tuple[bool, str, list[str]]]" = queue.Queue()
        self._probe_after: Optional[str] = None
        self.title("Налаштування · BlackChpok IDE")
        self.configure(bg=theme.BG)
        self.transient(master)
        # Одне модальне вікно за раз і жодних спливних карток під ним:
        # інакше «Налаштування» й «Вибір моделі» ділили введення, а картка
        # моделі лишалась поверх діалогу — застосунок виглядав завислим.
        self._has_grab = widgets.open_only_modal(self)
        if not self._has_grab:
            # Уже щось відкрите — не дублюємо діалог, лише піднімаємо його.
            self.destroy()
            existing = widgets.active_modal()
            if existing is not None:
                widgets.lift_modal(existing)
            return
        self._build()
        self.bind("<Escape>", lambda _e: self.destroy())
        # Журнал налаштувань наповнюється з фонових потоків (завантаження
        # моделі, перевірка провайдерів) — читаємо його в головному потоці.
        self._text_queue = None
        self._text_pump_after = None
        self._ensure_text_queue()
        # Позиція під розмір діалогу й межі екрана, а не «десь зверху».
        widgets.place_window(self, width=820, height=640, center_on=master)

    def _build(self) -> None:
        # Footer пакується ПЕРШИМ (side="bottom"): pack резервує нижню смугу
        # одразу, і жодна висока вкладка не виганяє кнопки «Зберегти» за
        # край — саме це траплялось на вкладці «Соцмережі» (889 px).
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x", padx=12, pady=12)
        ttk.Button(footer, text="Скасувати", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Зберегти", style="Accent.TButton", command=self._save).pack(side="right")

        notebook = ttk.Notebook(self)
        notebook.pack(side="top", fill="both", expand=True, padx=12, pady=(12, 0))
        #: Вкладки доступні ззовні (``self.notebook``) — це потрібно й тестам,
        #: і коду, який відкриває налаштування одразу на потрібній вкладці
        #: (напр. «Хмарні агенти» з меню провайдерів). Раніше ``notebook``
        #: був локальною змінною, і дістатись до вкладок було неможливо.
        self.notebook = notebook

        notebook.add(self._model_tab(notebook), text="  Модель  ")
        notebook.add(self._runtime_tab(notebook), text="  AI Runtime  ")
        notebook.add(self._editor_tab(notebook), text="  Редактор  ")
        notebook.add(self._agent_tab(notebook), text="  Агент  ")
        notebook.add(self._sections_tab(notebook), text="  Розділи  ")
        notebook.add(self._mcp_tab(notebook), text="  MCP  ")
        notebook.add(self._cloud_tab(notebook), text="  Хмарні агенти  ")
        notebook.add(self._social_tab(notebook), text="  Соцмережі  ")
        notebook.add(self._voice_tab(notebook), text="  Голос  ")

        # Висота діалогу під найвищу вкладку — у межах екрана: тоді навіть
        # «Соцмережі» видно целиком, а на маленьких екранах footer усе одно
        # на місці (пакується першим).
        self.after_idle(lambda: self._fit_height(notebook, footer))
        # Підказки — ПІСЛЯ побудови вкладок: дочірні віджети вже існують.
        self.after_idle(self._attach_tips)

    # ── підказки ───────────────────────────────────────────────────────────
    #: Пояснення для елементів, де самого підпису замало. Ключ — початок
    #: підпису віджета (без урахування регістру).
    TIPS: tuple[tuple[str, str], ...] = (
        ("скасувати", "Закрити налаштування без збереження змін"),
        ("зберегти", "Записати всі зміни на диск і застосувати їх до агента"),
        ("lm studio", "Локальний сервер LM Studio (OpenAI-сумісний API). "
                      "Потрібен лише якщо модель піднята в LM Studio"),
        ("ollama", "Локальний сервер Ollama. Підставляє його типову адресу"),
        ("llama.cpp", "Зовнішній llama-server. Вбудований рушій IDE "
                      "не потребує його взагалі"),
        ("vllm", "Локальний сервер vLLM (OpenAI-сумісний)"),
        ("хаб моделей", "Відкрити хаб: пошук, завантаження й запуск моделей"),
        ("оновити список", "Перечитати моделі з сервера й з диска"),
        ("список", "Показати локальні .gguf-файли з теки моделей"),
        ("використовувати власний рушій", "Модель виконується ВСЕРЕДИНІ IDE "
                                          "через llama.dll — без сторонніх програм"),
        ("перевірити залізо", "Показати RAM/VRAM/CPU і прогноз для моделі"),
        ("завантажити у рушій", "Завантажити вибрану модель у пам'ять IDE "
                                "(модель стане доступною в чаті)"),
        ("вивантажити", "Звільнити відеопам'ять: прибрати модель із пам'яті"),
        ("бенчмарк", "Заміряти швидкість: токени за секунду, TTFT, VRAM"),
        ("панель ai runtime", "Відкрити бічну панель із живими показниками рушія"),
        ("переносити довгі рядки", "Переносити рядки в редакторі замість "
                                   "горизонтальної прокрутки"),
        ("показувати номери рядків", "Показувати нумерацію рядків у редакторі"),
        ("підсвічувати поточний рядок", "Виділяти рядок, де стоїть курсор"),
        ("відновлювати відкриті вкладки", "Після запуску відкрити ті самі "
                                          "файли, що були відкриті"),
        ("питати дозвіл на команди", "Перед виконанням команди в терміналі "
                                     "питати підтвердження"),
        ("офлайн-роутер", "Коли модель недоступна, відповідати простими "
                          "правилами замість помилки"),
        ("додавати увімкнені скіли", "Вставляти інструкції скілів у системний "
                                     "промпт агента"),
        ("автоматично виконувати чергу", "Запускати наступну задачу черги "
                                         "без натискання «Далі»"),
        ("показувати відповідь у міру", "Показувати текст під час генерації, "
                                        "а не лише готову відповідь"),
        ("перевіряти аргументи", "Відхиляти виклик інструмента з аргументами, "
                                 "що не відповідають схемі"),
        ("виконувати незалежні читання", "Читати кілька файлів одночасно — "
                                         "швидше на великих проєктах"),
        ("зберігати знеособлену статистику", "Локальна статистика ходів без "
                                             "вмісту файлів і тексту"),
        ("пам'ять neuromesh", "Пам'ять бере участь у розумінні запитів: "
                              "знайдені спогади додаються в контекст агента"),
        ("будувати план кроків", "Для складних завдань спершу складати план, "
                                 "а потім виконувати"),
        ("вивантажувати модель із відеокарти", "Звільняти VRAM після простою "
                                               "(модель підніметься на запит)"),
        ("забути всі постійні", "Прибрати всі збережені побажання користувача"),
        ("увімкнути mcp-сервери", "Запускати MCP-сервери зі знайдених "
                                  "конфігурацій"),
        ("читати .mcp.json", "Підхоплювати .mcp.json із робочої теки при старті"),
        ("де взяти ключ", "Посилання на сторінку, де видають API-ключ"),
        ("перевірити ключ", "Зробити справжній запит і показати результат"),
        ("дозволяти reasoning-моделі", "Не прихо��увати «думки» reasoning-моделей"),
        ("увімкнути голосове", "Кнопка 🎙 у полі введення записує голос"),
        ("надсилати розпізнане", "Одразу надсилати розпізнаний текст агенту"),
        ("озвучувати відповіді", "Читати відповіді агента вголос"),
        ("хаб моделей…", "Відкрити хаб моделей із цього діалогу"),
    )

    def _attach_tips(self) -> None:
        """Додати підказки всім кнопкам і прапорцям діалогу.

        Навіщо централізовано. У діалозі 54 інтерактивні елементи на дев'яти
        вкладках; додавати ``Tip`` біля кожного — це 54 правки в 1250 рядках,
        і будь-яка нова кнопка знову лишилась би без пояснення. Тут підказка
        виводиться з ПІДПИСУ елемента, а елементи без явного тексту
        отримують пояснення свого типу.
        """
        for widget in self._walk(self):
            if not isinstance(widget, (ttk.Button, tk.Button, ttk.Checkbutton,
                                       tk.Checkbutton, tk.Radiobutton)):
                continue
            try:
                label = str(widget.cget("text") or "").strip()
            except (tk.TclError, AttributeError):
                continue
            tip = self._tip_for(label)
            if not tip:
                continue
            try:
                widgets.Tip(widget, tip)
            except tk.TclError:
                continue

    def _tip_for(self, label: str) -> str:
        """Підібрати пояснення за підписом елемента."""
        low = label.lower()
        # Спершу явні пояснення: вони важливіші за довжину підпису.
        for marker, tip in self.TIPS:
            if low.startswith(marker) or marker in low:
                return tip
        # Довгий підпис, для якого немає окремого пояснення, — це вже абзац.
        if len(label) > 60:
            return ""
        # Панель за ключем: «◉  AI Runtime», «≡  Черга завдань» тощо —
        # підпис уже описує розділ, тож підказка каже, ЩО станеться.
        if label[:1] in {"◉", "⌘", "⚒", "🗂", "±", "◫", "≡", "✦", "∞",
                         "◎", "◧", "⚙"}:
            return f"Відкрити розділ «{label[1:].strip()}» у бічній панелі"
        return ""

    @staticmethod
    def _walk(widget: tk.Misc):
        """Обійти дерево віджетів (вкладені вкладки теж)."""
        yield widget
        for child in widget.winfo_children():
            try:
                yield from SettingsDialog._walk(child)
            except tk.TclError:
                continue

    def _fit_height(self, notebook: ttk.Notebook, footer: ttk.Frame) -> None:
        """Підібрати висоту діалогу під вміст, не виходячи за екран."""
        try:
            needed = notebook.winfo_reqheight() + footer.winfo_reqheight() + 40
            limit = max(560, self.winfo_screenheight() - 120)
            height = max(560, min(needed, limit))
            width = max(820, self.winfo_width())
            # Не просто задаємо розмір, а й тримаємо вікно в межах екрана:
            # інакше після зміни висоти воно зсувалось за нижній край.
            widgets.place_window(self, width=width, height=height)
        except tk.TclError:
            pass

    # ── модель ─────────────────────────────────────────────────────────────
    def _model_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(frame, text="Сервер (OpenAI-сумісний URL)").grid(row=row, column=0, sticky="w", pady=4)
        self.url_entry = ttk.Entry(frame)
        self.url_entry.insert(0, self.settings.llm.base_url)
        self.url_entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(10, 0))
        row += 1

        presets = ttk.Frame(frame)
        presets.grid(row=row, column=1, sticky="w", pady=(0, 6), padx=(10, 0))
        for index, (name, url) in enumerate(KNOWN_ENDPOINTS):
            ttk.Button(presets, text=name, style="Icon.TButton",
                       command=lambda u=url: self._set_url(u)).grid(row=0, column=index, padx=(0, 4))
        row += 1

        hub_row = ttk.Frame(frame)
        hub_row.grid(row=row, column=1, sticky="w", pady=(0, 8), padx=(10, 0))
        ttk.Button(hub_row, text="⬇  Хаб моделей — знайти й завантажити", style="Icon.TButton",
                   command=self._open_hub).pack(side="left")
        ttk.Label(hub_row, text="(модель, рушій і налаштування — автоматично)",
                  style="Panel.TLabel").pack(side="left", padx=(8, 0))
        row += 1

        ttk.Label(frame, text="API-ключ").grid(row=row, column=0, sticky="w", pady=4)
        self.key_entry = ttk.Entry(frame, show="•")
        self.key_entry.insert(0, self.settings.llm.api_key)
        self.key_entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(10, 0))
        row += 1

        ttk.Label(frame, text="Модель").grid(row=row, column=0, sticky="w", pady=4)
        model_row = ttk.Frame(frame)
        model_row.grid(row=row, column=1, sticky="ew", pady=4, padx=(10, 0))
        model_row.columnconfigure(0, weight=1)
        self.model_combo = ttk.Combobox(model_row, values=[])
        self.model_combo.set(self.settings.llm.model)
        self.model_combo.grid(row=0, column=0, sticky="ew")
        # ── Список не має бути порожнім до першого запиту ─────────────────
        # Раніше ``values=[]`` лишалось порожнім, поки користувач не натисне
        # «Оновити список». Тепер одразу кладемо те, що вже знаємо: локальні
        # .gguf-файли з диска й поточну модель. Мережевий запит (якщо сервер
        # живий) лише ДОПОВНЮЄ список.
        self.model_combo.configure(values=self._known_models())
        ttk.Button(model_row, text="Оновити список", style="Icon.TButton",
                   command=self._probe).grid(row=0, column=1, padx=(6, 0))
        row += 1

        self.probe_label = ttk.Label(frame, text="", style="Panel.TLabel")
        self.probe_label.grid(row=row, column=1, sticky="w", padx=(10, 0))
        row += 1

        ttk.Label(frame, text="Температура").grid(row=row, column=0, sticky="w", pady=4)
        self.temp_var = tk.DoubleVar(value=self.settings.llm.temperature)
        ttk.Scale(frame, from_=0.0, to=1.5, variable=self.temp_var,
                  command=lambda _v: self.temp_label.configure(text=f"{self.temp_var.get():.2f}")
                  ).grid(row=row, column=1, sticky="ew", padx=(10, 0))
        row += 1
        self.temp_label = ttk.Label(frame, text=f"{self.settings.llm.temperature:.2f}", style="Panel.TLabel")
        self.temp_label.grid(row=row, column=0, sticky="w", padx=(0, 0))
        row += 1

        ttk.Label(frame, text="Максимум токенів").grid(row=row, column=0, sticky="w", pady=4)
        self.tokens_var = tk.IntVar(value=self.settings.llm.max_tokens)
        ttk.Spinbox(frame, from_=256, to=32768, increment=256, textvariable=self.tokens_var
                    ).grid(row=row, column=1, sticky="w", pady=4, padx=(10, 0))
        row += 1

        ttk.Label(frame, text="Таймаут, с").grid(row=row, column=0, sticky="w", pady=4)
        self.timeout_var = tk.IntVar(value=self.settings.llm.timeout)
        ttk.Spinbox(frame, from_=30, to=1800, increment=30, textvariable=self.timeout_var
                    ).grid(row=row, column=1, sticky="w", pady=4, padx=(10, 0))
        row += 1

        # ── Контекст локальної моделі
        ttk.Label(frame, text="Розмір контексту").grid(row=row, column=0, sticky="w", pady=4)
        ctx_row = ttk.Frame(frame)
        ctx_row.grid(row=row, column=1, sticky="ew", pady=4, padx=(10, 0))
        self.ctx_var = tk.IntVar(value=int(getattr(self.settings.engine, "ctx_size", 0) or 0))
        ttk.Spinbox(ctx_row, from_=0, to=131072, increment=1024,
                    textvariable=self.ctx_var, width=10).pack(side="left")
        ttk.Label(ctx_row, text="0 = авто (найбільший, що влізе)",
                  style="Panel.TLabel").pack(side="left", padx=(8, 0))
        row += 1
        ttk.Label(
            frame,
            text=("Більший контекст забирає відеопам'ять у ваг моделі й робить\n"
                  "кожен токен повільнішим. Замалий змушує агента перечитувати\n"
                  "файли. IDE сама обере стиснутий кеш (q8_0) або винесе його\n"
                  "в системну пам'ять, якщо контекст не влазить у VRAM."),
            style="Panel.TLabel", justify="left").grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=(0, 4))
        return frame

    def _on_theme_pick(self, _event=None) -> None:
        """Застосувати тему одразу — користувач бачить результат у діалозі."""
        mode = "light" if "світл" in self.theme_combo.get().lower() else "dark"
        self.settings.ui.theme = mode
        try:
            theme.switch_mode(mode, root=self.winfo_toplevel(), theme_obj=self.fonts)
        except tk.TclError:
            pass

    def _set_url(self, url: str) -> None:
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)

    def _open_hub(self) -> None:
        """Передати керування хабу моделей (діалог закриваємо, щоб не було двох модальних)."""
        widgets.release_modal(self)
        self.destroy()
        if self.on_open_hub:
            self.on_open_hub()

    def _known_models(self) -> list[str]:
        """Моделі, які вже відомі БЕЗ мережі.

        Джерела: поточна модель із налаштувань, файли ``.gguf`` у теці
        моделей і вбудований рушій. Це робить список робочим одразу, а
        ``_probe`` потім лише доповнює його відповіддю сервера.
        """
        names: list[str] = []
        current = str(getattr(self.settings.llm, "model", "") or "").strip()
        if current:
            names.append(current)
        try:
            from .model_hub import local_models

            for path in local_models():
                stem = path.stem
                if stem and stem not in names:
                    names.append(stem)
        except Exception:  # noqa: BLE001 - список моделей не має ламати діалог
            LOG.debug("Локальні моделі не прочитано", exc_info=True)
        try:
            from .native import bridge

            data = bridge.runtime().list_models()
            for item in data.get("models") or []:
                key = str(item.get("key") or "")
                if key and key not in names:
                    names.append(key)
        except Exception:  # noqa: BLE001 - рушій може бути недоступний
            LOG.debug("Моделі рушія не прочитано", exc_info=True)
        return names

    def _probe(self) -> None:
        url = self.url_entry.get().strip()
        self.probe_label.configure(text="Перевіряю…")
        # потік лише кладе результат у чергу; віджети оновлює головний цикл
        ModelProbe(
            url,
            self.key_entry.get().strip(),
            lambda ok, detail, models: self._probe_queue.put((ok, detail, models)),
        ).start()
        self._drain_probe()

    def _drain_probe(self) -> None:
        try:
            while True:
                ok, detail, models = self._probe_queue.get_nowait()
                self._apply_probe(ok, detail, models)
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self._probe_after = self.after(150, self._drain_probe)
        except tk.TclError:
            self._probe_after = None

    def destroy(self) -> None:
        """Закрити діалог, знявши таймер опитування моделей.

        Без цього ``after(150, self._drain_probe)`` лишається в Tcl після
        знищення вікна: Tk друкує «invalid command name ..._drain_probe», а
        закриття застосунку падає з «application has been destroyed».
        """
        job = getattr(self, "_probe_after", None)
        self._probe_after = None
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        super().destroy()

    def _apply_probe(self, ok: bool, detail: str, models: list[str]) -> None:
        try:
            self.probe_label.configure(text=("✓ " if ok else "✗ ") + detail)
            if models:
                self.model_combo.configure(values=models)
                if self.model_combo.get() not in models:
                    self.model_combo.set(models[0])
        except tk.TclError:
            pass

    # ── редактор ───────────────────────────────────────────────────────────
    def _editor_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(frame, text="Тема інтерфейсу").grid(row=row, column=0, sticky="w", pady=4)
        self.theme_combo = ttk.Combobox(frame, state="readonly",
                                        values=("Темна", "Світла (cream)"))
        self.theme_combo.set("Світла (cream)" if self.settings.ui.theme == "light" else "Темна")
        self.theme_combo.grid(row=row, column=1, sticky="w", padx=(10, 0))
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_pick)
        row += 1

        ttk.Label(frame, text="Розмір шрифту").grid(row=row, column=0, sticky="w", pady=4)
        self.size_var = tk.IntVar(value=self.settings.ui.font_size)
        ttk.Spinbox(frame, from_=8, to=32, textvariable=self.size_var).grid(
            row=row, column=1, sticky="w", padx=(10, 0))
        row += 1

        ttk.Label(frame, text="Шрифт").grid(row=row, column=0, sticky="w", pady=4)
        from .theme import FONT_CANDIDATES

        self.font_combo = ttk.Combobox(frame, values=list(FONT_CANDIDATES))
        self.font_combo.set(self.settings.ui.font_family or self.fonts.mono_family)
        self.font_combo.grid(row=row, column=1, sticky="w", padx=(10, 0))
        row += 1

        ttk.Label(frame, text="Ширина табуляції").grid(row=row, column=0, sticky="w", pady=4)
        self.tab_var = tk.IntVar(value=self.settings.ui.tab_size)
        ttk.Spinbox(frame, from_=2, to=8, textvariable=self.tab_var).grid(
            row=row, column=1, sticky="w", padx=(10, 0))
        row += 1

        self.wrap_var = tk.BooleanVar(value=self.settings.ui.word_wrap)
        ttk.Checkbutton(frame, text="Переносити довгі рядки", variable=self.wrap_var).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=4)
        row += 1

        self.numbers_var = tk.BooleanVar(value=self.settings.ui.show_line_numbers)
        ttk.Checkbutton(frame, text="Показувати номери рядків", variable=self.numbers_var).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=4)
        row += 1

        self.current_line_var = tk.BooleanVar(value=self.settings.ui.highlight_current_line)
        ttk.Checkbutton(frame, text="Підсвічувати поточний рядок", variable=self.current_line_var).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=4)
        row += 1

        self.restore_var = tk.BooleanVar(value=self.settings.ui.restore_session)
        ttk.Checkbutton(frame, text="Відновлювати відкриті вкладки при старті", variable=self.restore_var).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=4)
        return frame

    # ── розділи програми ───────────────────────────────────────────────────
    #: Панелі, які раніше були пунктами лівого меню. Тепер вони тут:
    #: ліва колонка показує лише чати, а все інше відкривається звідси.
    SECTIONS: tuple[tuple[str, str, str], ...] = (
        ("runtime", "◉  AI Runtime", "Власний рушій: моделі, GPU, контекст, бенчмарк"),
        ("neuromesh", "∞  NEUROMESH Пам'ять", "Спогади, зв'язки, прогноз і бекапи"),
        ("mcp", "⌘  MCP Tools", "Підключені MCP-сервери та їхні інструменти"),
        ("tools", "⚒  Інструменти агента", "Вбудовані інструменти, які бачить модель"),
        ("explorer", "🗂  Проєкти й файли", "Дерево файлів робочого проєкту"),
        ("changes", "±  Зміни у файлах", "Що змінилося в проєкті"),
        ("rag", "◫  База знань", "RAG: індексація й семантичний пошук"),
        ("queue", "≡  Черга завдань", "Задачі, прив'язані до поточного чату"),
        ("skills", "✦  Скіли агента", "Готові інструкції для типових робіт"),
        ("autonomous", "∞  Автономний режим", "Безперервне покращення проєкту"),
        ("cases", "◎  Кроки агента", "Що агент робить просто зараз"),
        ("outline", "◧  Структура файлу", "Символи поточного файлу"),
    )

    def _sections_tab(self, master) -> ttk.Frame:
        """Розділи програми: усе, що раніше висіло пунктами лівого меню.

        Навіщо переносити: ліва колонка існує для розмов, а п'ять пунктів
        навігації забирали в неї місце й збивали з пантелику — «Проєкти»
        й «База знань» виглядали як чати, хоч це панелі.
        """
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text=("Ліва панель показує лише чати. Панелі програми "
                  "відкриваються звідси — вони з'являться праворуч від діалогу."),
            style="Panel.TLabel", wraplength=720, justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 10))

        host = ttk.Frame(frame)
        host.grid(row=1, column=0, sticky="ew")
        host.columnconfigure(0, weight=1)

        for index, (key, label, tip) in enumerate(self.SECTIONS):
            row = ttk.Frame(host)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            row.columnconfigure(1, weight=1)
            ttk.Button(row, text=label, style="Icon.TButton", width=26,
                       command=lambda k=key: self._open_panel(k)
                       ).grid(row=0, column=0, sticky="w")
            ttk.Label(row, text=tip, style="Panel.TLabel").grid(
                row=0, column=1, sticky="w", padx=(10, 0))

        ttk.Separator(frame).grid(row=2, column=0, sticky="ew", pady=10)

        extra = ttk.Frame(frame)
        extra.grid(row=3, column=0, sticky="ew")
        ttk.Button(extra, text="⚙  Майстер налаштування", style="Icon.TButton",
                   command=self._open_first_run).pack(side="left")
        ttk.Button(extra, text="Хаб моделей…", style="Icon.TButton",
                   command=self._open_hub).pack(side="left", padx=(8, 0))
        return frame

    def _open_panel(self, key: str) -> None:
        """Відкрити панель і закрити діалог (панель має бути видною)."""
        callback = self.on_open_panel
        self.destroy()
        if callback is not None:
            try:
                callback(key)
            except Exception:  # noqa: BLE001 - панель не має ламати налаштування
                pass

    def _open_first_run(self) -> None:
        """Майстер налаштування (залізо, бібліотеки, програми, модель)."""
        callback = getattr(self, "on_first_run", None)
        self.destroy()
        if callback is not None:
            try:
                callback()
            except Exception:  # noqa: BLE001
                pass

    # ── агент ──────────────────────────────────────────────────────────────
    def _agent_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text="Системний промпт").grid(row=0, column=0, sticky="w")
        self.prompt_text = tk.Text(frame, height=12, wrap="word", bg=theme.BG_INPUT, fg=theme.FG,
                                   insertbackground=theme.FG_BRIGHT, relief="flat", font=self.fonts.mono_small,
                                   padx=8, pady=6)
        self.prompt_text.insert("1.0", self.settings.agent.system_prompt)
        self.prompt_text.grid(row=1, column=0, sticky="nsew", pady=(4, 8))

        options = ttk.Frame(frame)
        options.grid(row=2, column=0, sticky="ew")
        self.confirm_cmd_var = tk.BooleanVar(value=self.settings.agent.confirm_commands)
        ttk.Checkbutton(options, text="Питати дозвіл на команди терміналу",
                        variable=self.confirm_cmd_var).grid(row=0, column=0, sticky="w", pady=2)
        self.offline_var = tk.BooleanVar(value=self.settings.agent.offline_fallback)
        ttk.Checkbutton(options, text="Офлайн-роутер, якщо модель недоступна",
                        variable=self.offline_var).grid(row=1, column=0, sticky="w", pady=2)

        ttk.Label(options, text="Максимум кроків агента").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.steps_var = tk.IntVar(value=self.settings.agent.max_steps)
        ttk.Spinbox(options, from_=1, to=25, textvariable=self.steps_var, width=6).grid(
            row=2, column=1, sticky="w", padx=(10, 0), pady=(8, 0))

        self.skills_var = tk.BooleanVar(value=self.settings.agent.use_skills)
        ttk.Checkbutton(options, text="Додавати увімкнені скіли в системний промпт",
                        variable=self.skills_var).grid(row=3, column=0, columnspan=2,
                                                       sticky="w", pady=(8, 0))

        self.autorun_var = tk.BooleanVar(value=self.settings.agent.queue_auto_run)
        ttk.Checkbutton(options, text="Автоматично виконувати чергу завдань",
                        variable=self.autorun_var).grid(row=4, column=0, columnspan=2,
                                                        sticky="w", pady=2)

        self.stream_var = tk.BooleanVar(value=getattr(self.settings.agent, "stream", True))
        ttk.Checkbutton(options, text="Показувати відповідь у міру генерації (стрімінг)",
                        variable=self.stream_var).grid(row=5, column=0, columnspan=2,
                                                       sticky="w", pady=2)

        # ── інструменти й вимірювання ─────────────────────────────────────
        # Ці перемикачі впливають на те, наскільки агент перевіряє себе сам.
        # Типово все ввімкнено: саме це відрізняє «реальну роботу» від
        # «модель написала, що зробила».
        self.validate_args_var = tk.BooleanVar(
            value=getattr(self.settings.agent, "validate_tool_arguments", True))
        ttk.Checkbutton(options, text="Перевіряти аргументи інструментів за схемою",
                        variable=self.validate_args_var).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=2)

        self.parallel_var = tk.BooleanVar(
            value=getattr(self.settings.agent, "parallel_tools", True))
        ttk.Checkbutton(options, text="Виконувати незалежні читання паралельно",
                        variable=self.parallel_var).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=2)

        self.traces_var = tk.BooleanVar(
            value=getattr(self.settings.agent, "save_traces", True))
        ttk.Checkbutton(options, text="Зберігати знеособлену статистику ходів "
                                      "(для перевірки якості)",
                        variable=self.traces_var).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=2)

        self.memory_join_var = tk.BooleanVar(
            value=getattr(self.settings.agent, "memory_participates", True))
        ttk.Checkbutton(options, text="Пам'ять NEUROMESH бере участь у розумінні "
                                      "запиту (факти й обмеження проєкту)",
                        variable=self.memory_join_var).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=2)

        self.auto_plan_var = tk.BooleanVar(
            value=getattr(self.settings.agent, "auto_plan", True))
        ttk.Checkbutton(options, text="Будувати план кроків для складних завдань",
                        variable=self.auto_plan_var).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=2)

        # ── відеокарта: звільняти пам'ять, коли користувач не працює
        self.idle_unload_var = tk.BooleanVar(
            value=getattr(self.settings.engine, "unload_when_idle", True))
        ttk.Checkbutton(options, text="Вивантажувати модель із відеокарти під час простою",
                        variable=self.idle_unload_var).grid(row=11, column=0, columnspan=2,
                                                             sticky="w", pady=(10, 0))
        ttk.Label(options, text="Через скільки секунд простою").grid(
            row=12, column=0, sticky="w", pady=(2, 0))
        self.idle_seconds_var = tk.IntVar(
            value=getattr(self.settings.engine, "idle_unload_seconds", 300))
        ttk.Spinbox(options, from_=60, to=1800, increment=30,
                    textvariable=self.idle_seconds_var, width=8).grid(
            row=12, column=1, sticky="w", padx=(10, 0), pady=(2, 0))
        ttk.Label(options, text="В автономному режимі модель не вивантажується: "
                                "агент працює безперервно.",
                  style="Faint.TLabel", wraplength=460).grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ── постійні побажання ────────────────────────────────────────────
        # Показуємо РІВНО те, що агент запам'ятав, і даємо це стерти.
        # Жодного «профілю особистості»: лише те, що людина сказала прямо.
        remembered = list(getattr(self.settings, "preferences", []) or [])
        summary = ("Постійні побажання: " + "; ".join(
            str(item.get("value") or "") for item in remembered
            if isinstance(item, dict) and item.get("value"))) if remembered \
            else "Постійних побажань ще немає."
        ttk.Label(options, text=summary, style="Faint.TLabel",
                  wraplength=460).grid(row=14, column=0, columnspan=2,
                                       sticky="w", pady=(10, 0))
        self.clear_prefs_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Забути всі постійні побажання",
                        variable=self.clear_prefs_var).grid(
            row=15, column=0, columnspan=2, sticky="w", pady=2)
        return frame

    # ── MCP ────────────────────────────────────────────────────────────────
    def _mcp_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        self.mcp_enabled_var = tk.BooleanVar(value=self.settings.mcp.enabled)
        ttk.Checkbutton(frame, text="Увімкнути MCP-сервери (stdio)",
                        variable=self.mcp_enabled_var).grid(row=0, column=0, sticky="w")

        self.mcp_auto_var = tk.BooleanVar(value=self.settings.mcp.auto_load_workspace)
        ttk.Checkbutton(frame, text="Читати .mcp.json з робочої теки при старті",
                        variable=self.mcp_auto_var).grid(row=1, column=0, sticky="w", pady=2)

        ttk.Label(frame, text="Конфігурація береться з .mcp.json або .cursor/mcp.json "
                              "у теці проєкту.",
                  style="Dim.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 6))

        self.mcp_text = tk.Text(frame, height=10, wrap="word", bg=theme.BG_INPUT, fg=theme.FG,
                                insertbackground=theme.FG_BRIGHT, relief="flat",
                                font=self.fonts.mono_small, padx=8, pady=6)
        self.mcp_text.grid(row=3, column=0, sticky="nsew")
        self._fill_mcp_preview()
        return frame

    def _fill_mcp_preview(self) -> None:
        """Показати, що саме знайдено в конфігурації робочої теки."""
        from pathlib import Path

        from .mcp_panel import workspace_config_paths

        lines: list[str] = []
        root = Path(self.settings.workspace)
        for path in workspace_config_paths(root):
            lines.append(f"# {path}")
            try:
                lines.append(path.read_text(encoding="utf-8", errors="replace")[:2000])
            except OSError as exc:
                lines.append(f"[не читається: {exc}]")
        if not lines:
            lines.append("У робочій теці немає .mcp.json або .cursor/mcp.json.")
        self.mcp_text.insert("1.0", "\n".join(lines))
        self.mcp_text.configure(state="disabled")

    # ── хмарні агенти ──────────────────────────────────────────────────────
    def _cloud_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(frame, text="Провайдер").grid(row=row, column=0, sticky="w", pady=4)
        self.cloud_provider = tk.StringVar(value=cloud_agents.label_for(
            self.settings.cloud.provider or "deepseek"))
        self.cloud_combo = ttk.Combobox(
            frame, state="readonly", width=28,
            values=[label for _key, label in cloud_agents.provider_labels()],
        )
        self.cloud_combo.set(self.cloud_provider.get())
        self.cloud_combo.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=4)
        self.cloud_combo.bind("<<ComboboxSelected>>", self._on_cloud_provider)
        row += 1

        self.cloud_note = ttk.Label(frame, text=cloud_agents.describe(
            self.settings.cloud.provider or "deepseek"),
            style="Dim.TLabel", wraplength=560, justify="left")
        self.cloud_note.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

        ttk.Label(frame, text="API-ключ").grid(row=row, column=0, sticky="w", pady=4)
        self.cloud_key = ttk.Entry(frame, show="•", width=48)
        self.cloud_key.insert(0, self.settings.cloud.api_key)
        self.cloud_key.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
        row += 1

        # Стан зберігання ключа — чесний, а не «наче все безпечно».
        ttk.Label(
            frame,
            text=("Ключ шифрується Windows DPAPI і зберігається лише для "
                  "твого облікового запису. У файлі немає відкритого тексту."
                  if secrets.available() else
                  "Увага: системне шифрування недоступне — ключ НЕ буде "
                  "збережено у файл; вводь його після кожного запуску."),
            style="Dim.TLabel", wraplength=560, justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        key_row = ttk.Frame(frame)
        key_row.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=(0, 8))
        self.cloud_key_hint = ttk.Label(key_row, text="", style="Dim.TLabel")
        self.cloud_key_hint.pack(side="left")
        ttk.Button(key_row, text="Де взяти ключ", style="Icon.TButton",
                   command=self._open_key_page).pack(side="left", padx=(8, 0))
        row += 1

        ttk.Label(frame, text="Базова адреса").grid(row=row, column=0, sticky="w", pady=4)
        self.cloud_url = ttk.Entry(frame, width=48)
        self.cloud_url.insert(0, self.settings.cloud.base_url)
        self.cloud_url.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
        row += 1

        # Регіони Deploy: від них залежить затримка.
        self.cloud_region_frame = ttk.Frame(frame)
        self.cloud_region_frame.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=(0, 6))
        ttk.Label(self.cloud_region_frame, text="Регіон:").pack(side="left", padx=(0, 6))
        self.cloud_region = ttk.Combobox(
            self.cloud_region_frame, state="readonly", width=22,
            values=[label for label, _url in cloud_agents.deploy_endpoints()],
        )
        self.cloud_region.pack(side="left")
        self.cloud_region.bind("<<ComboboxSelected>>", self._on_cloud_region)
        row += 1

        ttk.Label(frame, text="Модель").grid(row=row, column=0, sticky="w", pady=4)
        model_row = ttk.Frame(frame)
        model_row.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
        model_row.columnconfigure(0, weight=1)
        self.cloud_model = ttk.Combobox(model_row, width=34)
        self.cloud_model.set(self.settings.cloud.model)
        self.cloud_model.grid(row=0, column=0, sticky="ew")
        # Список типових моделей провайдера — одразу, без натискання
        # «Перевірити ключ». Порожній Combobox виглядав як зламаний.
        self.cloud_model.configure(values=self._cloud_model_hints())
        ttk.Button(model_row, text="Перевірити ключ", style="Accent.TButton",
                   command=self._check_cloud).grid(row=0, column=1, padx=(8, 0))
        row += 1

        self.cloud_status = ttk.Label(frame, text=self.settings.cloud.last_status or "",
                                      style="Dim.TLabel", wraplength=560, justify="left")
        self.cloud_status.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 8))
        row += 1

        options = ttk.Frame(frame)
        options.grid(row=row, column=0, columnspan=2, sticky="w")
        self.cloud_reasoning = tk.BooleanVar(value=self.settings.cloud.reasoning)
        ttk.Checkbutton(options, text="Дозволяти reasoning-моделі (deepseek-reasoner, o3…)",
                        variable=self.cloud_reasoning).grid(row=0, column=0, sticky="w")
        row += 1

        ttk.Label(frame, text="Максимум токенів").grid(row=row, column=0, sticky="w", pady=4)
        self.cloud_tokens = tk.IntVar(value=self.settings.cloud.max_tokens)
        ttk.Spinbox(frame, from_=512, to=200000, increment=512,
                    textvariable=self.cloud_tokens, width=10).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=4)
        row += 1

        ttk.Label(frame, text="Температура").grid(row=row, column=0, sticky="w", pady=4)
        self.cloud_temp = tk.DoubleVar(value=self.settings.cloud.temperature)
        ttk.Scale(frame, from_=0.0, to=1.5, variable=self.cloud_temp).grid(
            row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
        row += 1

        self._sync_region_visibility(self._current_provider())

        ttk.Label(frame, text="Після збереження агент працюватиме через обрану хмару: "
                              "усі інструменти IDE й MCP доступні так само.",
                  style="Dim.TLabel", wraplength=600, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        return frame

    def _cloud_model_hints(self) -> list[str]:
        """Типові моделі всіх хмарних провайдерів — щоб список не був порожнім."""
        names: list[str] = []
        current = str(getattr(self.settings.cloud, "model", "") or "").strip()
        if current:
            names.append(current)
        try:
            for key, _label in cloud_agents.provider_labels():
                provider = cloud_agents.get(key)
                for model in getattr(provider, "models", ()) or ():
                    if model and model not in names:
                        names.append(model)
        except Exception:  # noqa: BLE001 - список не має ламати діалог
            LOG.debug("Типові хмарні моделі не прочитано", exc_info=True)
        return names

    def _current_provider(self):
        label = self.cloud_combo.get()
        for key, name in cloud_agents.provider_labels():
            if name == label:
                return cloud_agents.get(key)
        return cloud_agents.get("custom")

    def _on_cloud_region(self, _event=None) -> None:
        """Підставити адресу вибраного регіону Deploy."""
        label = self.cloud_region.get()
        for name, url in cloud_agents.deploy_endpoints():
            if name == label:
                self.cloud_url.delete(0, "end")
                self.cloud_url.insert(0, url)
                break

    def _sync_region_visibility(self, provider) -> None:
        """Показати вибір регіону лише для Deploy."""
        is_deploy = provider is not None and provider.key == "deploy"
        try:
            if is_deploy:
                self.cloud_region_frame.grid()
                current = self.cloud_url.get().strip().rstrip("/")
                for name, url in cloud_agents.deploy_endpoints():
                    if url.rstrip("/") == current:
                        self.cloud_region.set(name)
                        break
                else:
                    self.cloud_region.set(cloud_agents.deploy_endpoints()[0][0])
            else:
                self.cloud_region_frame.grid_remove()
        except (tk.TclError, AttributeError):
            pass

    def _on_cloud_provider(self, _event=None) -> None:
        provider = self._current_provider()
        if provider is None:
            return
        self.cloud_note.configure(text=cloud_agents.describe(provider.key))
        if provider.base_url:
            self.cloud_url.delete(0, "end")
            self.cloud_url.insert(0, provider.base_url)
        self.cloud_model.configure(values=list(provider.models))
        if provider.models:
            self.cloud_model.set(provider.models[0])
        self.cloud_key_hint.configure(
            text=(f"Взяти ключ: {provider.key_url}" if provider.key_url
                  else "Свій OpenAI-сумісний endpoint"))
        self._sync_region_visibility(provider)

    def _open_key_page(self) -> None:
        provider = self._current_provider()
        if provider is not None and provider.key_url:
            # Сторінка з ключем — у вбудованому браузері IDE, щоб не
            # перемикати вікна під час налаштування.
            browser_panel.open_url(provider.key_url)
            self.cloud_status.configure(text=f"Відкрито у вбудованому браузері: "
                                             f"{provider.key_url}")

    def _check_cloud(self) -> None:
        """Перевірити ключ — У ФОНІ, щоб не заморожувати вікно.

        ``cloud_agents.probe`` робить справжній HTTP-запит із таймаутом
        15 с. Раніше він кликався в головному потоці: вікно «зависало» на
        весь час перевірки, і користувач вважав, що програма зламалась.
        """
        key = self.cloud_key.get().strip()
        url = self.cloud_url.get().strip()
        if not key:
            self.cloud_status.configure(text="✗ Ключ не введено.")
            return
        self.cloud_status.configure(text="Перевіряю ключ… (можна працювати далі)")
        results: "queue.Queue[object]" = queue.Queue()

        def work() -> None:
            try:
                results.put(cloud_agents.probe(key, url))
            except Exception as exc:  # noqa: BLE001 - показуємо причину
                results.put(exc)

        threading.Thread(target=work, daemon=True,
                         name="cloud-key-check").start()
        self._poll_cloud(results, 0)

    def _poll_cloud(self, results: "queue.Queue[object]", attempt: int) -> None:
        """Дочекатись результату перевірки в головному потоці."""
        try:
            outcome = results.get_nowait()
        except queue.Empty:
            if attempt >= 200:                 # ≈20 с — запобіжник
                self.cloud_status.configure(text="✗ Перевірка не завершилась.")
                return
            try:
                self.after(100, lambda: self._poll_cloud(results, attempt + 1))
            except tk.TclError:
                return
            return
        if isinstance(outcome, Exception):
            self.cloud_status.configure(
                text=f"✗ {secrets.redact(str(outcome))[:240]}")
            return
        detail = secrets.redact(str(getattr(outcome, "detail", "")))[:240]
        ok = bool(getattr(outcome, "ok", False))
        self.cloud_status.configure(text=("✓ " if ok else "✗ ") + detail)
        models = list(getattr(outcome, "models", []) or [])
        if models:
            self.cloud_model.configure(values=models)
            if self.cloud_model.get() not in models:
                self.cloud_model.set(models[0])
        self.settings.cloud.last_status = detail

    # ── соцмережі ──────────────────────────────────────────────────────────
    def _social_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text="Увімкни мережі, у які агент зможе публікувати пости.",
                  style="Dim.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.social_entries: dict[str, dict[str, ttk.Entry]] = {}
        holder = ttk.Frame(frame)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)

        for index, network in enumerate(social.NETWORKS):
            box = ttk.LabelFrame(holder, text=f" {network.label} ", padding=10)
            box.grid(row=index, column=0, sticky="ew", pady=(0, 8))
            box.columnconfigure(1, weight=1)

            stored = self.settings.social.account(network.key)
            entries: dict[str, ttk.Entry] = {}
            for line, (name, label, hint) in enumerate(network.fields):
                ttk.Label(box, text=label).grid(row=line * 2, column=0, sticky="w", pady=(2, 0))
                entry = ttk.Entry(box, width=44,
                                  show="•" if name in network.secret_fields else "")
                entry.insert(0, stored.get(name, ""))
                entry.grid(row=line * 2, column=1, sticky="ew", padx=(10, 0), pady=(2, 0))
                ttk.Label(box, text=hint, style="Dim.TLabel").grid(
                    row=line * 2 + 1, column=1, sticky="w", padx=(10, 0))
                entries[name] = entry
            self.social_entries[network.key] = entries
            ttk.Label(box, text=network.how, style="Dim.TLabel",
                      wraplength=560, justify="left").grid(
                row=len(network.fields) * 2, column=0, columnspan=2,
                sticky="w", pady=(6, 0))
        return frame

    # ── голос ──────────────────────────────────────────────────────────────
    def _voice_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(0, weight=1)
        row = 0

        self.voice_enabled = tk.BooleanVar(value=self.settings.voice.enabled)
        ttk.Checkbutton(frame, text="Увімкнути голосове керування (кнопка 🎙 у чаті)",
                        variable=self.voice_enabled).grid(row=row, column=0, sticky="w")
        row += 1

        self.voice_auto = tk.BooleanVar(value=self.settings.voice.auto_send)
        ttk.Checkbutton(frame, text="Надсилати розпізнане агенту одразу",
                        variable=self.voice_auto).grid(row=row, column=0, sticky="w", pady=2)
        row += 1

        self.voice_speak = tk.BooleanVar(value=self.settings.voice.speak_replies)
        ttk.Checkbutton(frame, text="Озвучувати відповіді агента",
                        variable=self.voice_speak).grid(row=row, column=0, sticky="w", pady=2)
        row += 1

        ttk.Label(frame, text="Тривалість запису, с").grid(row=row, column=0, sticky="w",
                                                          pady=(10, 0))
        self.voice_seconds = tk.DoubleVar(value=self.settings.voice.seconds)
        ttk.Spinbox(frame, from_=2, to=30, increment=1,
                    textvariable=self.voice_seconds, width=8).grid(
            row=row + 1, column=0, sticky="w", pady=2)
        row += 2

        ttk.Label(frame, text="Швидкість озвучення").grid(row=row, column=0, sticky="w")
        self.voice_rate = tk.IntVar(value=self.settings.voice.rate)
        ttk.Scale(frame, from_=-10, to=10, variable=self.voice_rate).grid(
            row=row + 1, column=0, sticky="ew", pady=2)
        row += 2

        # ── стан рушіїв
        box = ttk.LabelFrame(frame, text=" Рушії розпізнавання ", padding=10)
        box.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)
        self.voice_engine_labels: dict[str, ttk.Label] = {}
        for index, (key, available, note) in enumerate(voice.engines()):
            mark = "✓" if available else "—"
            ttk.Label(box, text=f"{mark}  {note}").grid(row=index, column=0, sticky="w")
            label = ttk.Label(box, text="доступний" if available else "не знайдено",
                              style="Dim.TLabel")
            label.grid(row=index, column=1, sticky="e")
            self.voice_engine_labels[key] = label
        row += 1

        ttk.Label(frame, text=f"Голоси системи: {', '.join(voice.voices()) or 'не знайдено'}",
                  style="Dim.TLabel", wraplength=560, justify="left").grid(
            row=row, column=0, sticky="w", pady=(10, 0))
        row += 1

        ttk.Label(frame, text="Команди: «стоп», «новий чат», «покажи файли», "
                              "«термінал», «допомога». Будь-яка інша фраза йде агенту.",
                  style="Dim.TLabel", wraplength=600, justify="left").grid(
            row=row, column=0, sticky="w", pady=(8, 0))
        return frame

    # ── AI Runtime (власний рушій) ─────────────────────────────────────────
    def _runtime_tab(self, master) -> ttk.Frame:
        """Керування вбудованим рушієм: модель, GPU, контекст, бенчмарк.

        Вкладка показує ТІЛЬКИ те, що справді є: пристрої, які бачить ggml,
        реальну VRAM через ``nvidia-smi`` і список локальних GGUF. Кнопки
        викликають справжні операції рушія; якщо бібліотеки немає — чесно
        пише, що її треба встановити.
        """
        frame = ttk.Frame(master, padding=16)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text=("Власний рушій BLACKCHPOK виконує GGUF-моделі просто в процесі "
                  "IDE. LM Studio, Ollama чи llama-server для цього не потрібні."),
            style="Panel.TLabel", wraplength=720, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self.runtime_status = tk.StringVar(value="перевіряю рушій…")
        ttk.Label(frame, textvariable=self.runtime_status, style="Dim.TLabel",
                  wraplength=720, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        # ── модель
        ttk.Label(frame, text="Модель для рушія").grid(row=2, column=0, sticky="w",
                                                       pady=3)
        self.native_model_var = tk.StringVar(value=self.settings.engine.native_model)
        self.native_model_combo = ttk.Combobox(frame, textvariable=self.native_model_var,
                                               width=52)
        self.native_model_combo.grid(row=2, column=1, sticky="ew", padx=(10, 6), pady=3)
        ttk.Button(frame, text="Список", style="Icon.TButton",
                   command=self._refresh_native_models).grid(row=2, column=2, sticky="w")

        # ── контекст / шари / кеш
        ttk.Label(frame, text="Контекст (0 = авто)").grid(row=3, column=0, sticky="w",
                                                          pady=3)
        self.native_ctx_var = tk.StringVar(
            value=str(self.settings.engine.ctx_size or 0))
        ttk.Spinbox(frame, from_=0, to=131072, increment=1024, width=10,
                    textvariable=self.native_ctx_var).grid(row=3, column=1,
                                                           sticky="w", padx=(10, 6), pady=3)

        ttk.Label(frame, text="Шарів на GPU (-1 = авто)").grid(row=4, column=0,
                                                              sticky="w", pady=3)
        self.native_layers_var = tk.StringVar(
            value=str(self.settings.engine.native_gpu_layers))
        ttk.Spinbox(frame, from_=-1, to=999, width=10,
                    textvariable=self.native_layers_var).grid(row=4, column=1,
                                                              sticky="w", padx=(10, 6),
                                                              pady=3)

        ttk.Label(frame, text="Тип KV-кешу").grid(row=5, column=0, sticky="w", pady=3)
        self.native_cache_var = tk.StringVar(
            value=self.settings.engine.native_cache_type or "авто")
        ttk.Combobox(frame, textvariable=self.native_cache_var,
                     values=("авто", "q8_0", "q4_0", "f16", "bf16"), width=10,
                     state="readonly").grid(row=5, column=1, sticky="w",
                                            padx=(10, 6), pady=3)

        # ── перемикач
        self.native_enabled_var = tk.BooleanVar(value=bool(self.settings.engine.native))
        ttk.Checkbutton(
            frame,
            text="Використовувати власний рушій для чату (не llama-server)",
            variable=self.native_enabled_var,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 2))

        # ── дії
        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(6, 6))
        for text, command in (
            ("Перевірити залізо", self._runtime_probe_hardware),
            ("Завантажити у рушій", self._runtime_load_model),
            ("Вивантажити", self._runtime_unload_model),
            ("Бенчмарк", self._runtime_benchmark),
            ("Панель AI Runtime", lambda: self._open_panel("runtime")),
        ):
            ttk.Button(actions, text=text, style="Icon.TButton",
                       command=command).pack(side="left", padx=(0, 6))

        self.runtime_log = tk.Text(frame, height=9, wrap="word",
                                   font=("Consolas", 9), relief="flat")
        self.runtime_log.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        frame.rowconfigure(8, weight=1)

        self._refresh_native_models()
        self.after(120, self._runtime_auto_probe)
        return frame

    def _runtime_text(self, text: str) -> None:
        """Дописати рядок у журнал вкладки (без падіння, якщо вкладки немає)."""
        log = getattr(self, "runtime_log", None)
        if log is None:
            return
        try:
            log.insert("end", text + "\n")
            log.see("end")
        except tk.TclError:
            pass

    def _runtime_auto_probe(self) -> None:
        """Показати стан рушія одразу після відкриття вкладки."""
        from .native import bridge

        try:
            info = bridge.runtime().library_info()
        except Exception as exc:                     # noqa: BLE001
            self.runtime_status.set(f"Рушій недоступний: {exc}")
            return
        if not info.get("ok"):
            self.runtime_status.set(
                f"Рушій не встановлено: {info.get('error') or 'немає llama.dll'}")
            return
        devices = ", ".join(
            f"{item.get('name')} ({item.get('memory_total_mb', 0):.0f} МБ)"
            for item in info.get("devices") or []
        ) or "лише CPU"
        self.runtime_status.set(
            f"llama.cpp {info.get('version', '')} · {devices}")

    def _refresh_native_models(self) -> None:
        """Заповнити список моделей із теки моделей (без мережі)."""
        from .native import bridge

        try:
            names = bridge.list_models()
        except Exception as exc:                     # noqa: BLE001
            self._runtime_text(f"Список моделей недоступний: {exc}")
            return
        combo = getattr(self, "native_model_combo", None)
        if combo is None:
            return
        combo["values"] = names
        if names and not self.native_model_var.get():
            self.native_model_var.set(names[0])
        self._runtime_text(f"Знайдено моделей: {len(names)}")

    def _runtime_probe_hardware(self) -> None:
        """Показати залізо й прогноз для обраної моделі."""
        from .native import bridge

        self._runtime_text("── залізо ──")
        try:
            runtime = bridge.runtime()
            profile = runtime.hardware(refresh=True)
            self._runtime_text(profile.summary())
        except Exception as exc:                     # noqa: BLE001
            self._runtime_text(f"✗ {exc}")
            return
        target = self.native_model_var.get().strip()
        if not target:
            return
        try:
            data = runtime.inspect_model(target)
        except Exception as exc:                     # noqa: BLE001
            self._runtime_text(f"✗ метадані: {exc}")
            return
        self._runtime_text(
            f"{data.get('display_name')} · {data.get('quant')} · "
            f"{data.get('params_b')}B · шарів {data.get('layer_count')}")
        self._runtime_text(
            f"прогноз: {data.get('fits')} · VRAM ~{data.get('vram_needed_gb')} ГБ · "
            f"RAM ~{data.get('ram_needed_gb')} ГБ · ctx {data.get('suggested_ctx')} · "
            f"шарів на GPU {data.get('suggested_gpu_layers')}")
        for note in (data.get("notes") or [])[:3]:
            self._runtime_text(f"· {note}")

    def _runtime_load_model(self) -> None:
        """Завантажити вибрану модель у власний рушій."""
        from .native import bridge

        target = self.native_model_var.get().strip()
        if not target:
            self._runtime_text("✗ спершу вибери модель")
            return
        try:
            ctx = int(self.native_ctx_var.get() or 0)
        except (TypeError, ValueError):
            ctx = 0
        self._runtime_text(f"Завантажую {target}…")

        def work() -> None:
            try:
                info = bridge.runtime().load_model(
                    target, ctx=ctx,
                    on_progress=lambda text: self._ui_text(text))
                self._ui_text(
                    f"✓ {info.get('description')} · ctx {info.get('context_actual')} · "
                    f"GPU-шарів {info.get('gpu_layers')}")
            except Exception as exc:                 # noqa: BLE001
                self._ui_text(f"✗ {exc}")

        threading.Thread(target=work, daemon=True, name="settings-load").start()

    def _ui_text(self, text: str) -> None:
        """Дописати в журнал із будь-якого потоку (через головний цикл).

        КЛЮЧОВЕ: Tkinter не можна чіпати з фонового потоку. Раніше тут
        стояло ``self.after(0, ...)``, викликане з ``work()`` (рядки 1051
        і 1086) — а ``after`` сам звертається до інтерпретатора Tcl.

        У ``chat_panel.py`` ця сама пастка вже описана коментарем:
        «викликати after() з фонового потоку не можна … main thread is not
        in main loop». Тут вона лишалась.

        Тепер працюємо через чергу ``queue``, яку читає головний потік:
        фон лише кладе повідомлення, а ``after`` викликає вже UI-потік.
        """
        try:
            self._text_queue.put_nowait(str(text or ""))
        except queue.Full:                       # журнал переповнено — не біда
            LOG.debug("Черга журналу налаштувань переповнена")
        except AttributeError:
            # Черги ще немає (див. _ensure_text_queue) — створюємо й пробуємо ще.
            self._ensure_text_queue()
            try:
                self._text_queue.put_nowait(str(text or ""))
            except (queue.Full, AttributeError):
                pass

    def _ensure_text_queue(self) -> None:
        """Створити чергу журналу й запустити її читання в головному потоці.

        Окремий метод, бо його викликає і конструктор (коли віджети вже є),
        і сам ``_ui_text`` — на випадок, якщо фон звернувся раніше.
        """
        if getattr(self, "_text_queue", None) is not None:
            return
        self._text_queue = queue.Queue(maxsize=500)
        self._pump_text_queue()

    def _pump_text_queue(self) -> None:
        """Перенести накопичені повідомлення у віджет (лише в UI-потоці)."""
        try:
            while True:
                text = self._text_queue.get_nowait()
                self._runtime_text(text)
        except queue.Empty:
            pass
        except (tk.TclError, AttributeError):
            return                               # вікно закрилось
        try:
            self._text_pump_after = self.after(120, self._pump_text_queue)
        except tk.TclError:
            self._text_pump_after = None

    def _runtime_unload_model(self) -> None:
        from .native import bridge

        try:
            data = bridge.unload()
            self._runtime_text("Модель вивантажено." if data.get("unloaded")
                               else "Моделі в пам'яті не було.")
        except Exception as exc:                     # noqa: BLE001
            self._runtime_text(f"✗ {exc}")

    def _runtime_benchmark(self) -> None:
        from .native import bridge

        self._runtime_text("Заміряю швидкість…")

        def work() -> None:
            try:
                data = bridge.runtime().benchmark_model(runs=1, max_tokens=32)
                self._ui_text(
                    f"✓ {data.get('tokens_per_second')} tok/s · TTFT "
                    f"{data.get('time_to_first_token_ms')} мс · ctx "
                    f"{data.get('context')} · шарів на GPU {data.get('gpu_layers')}")
            except Exception as exc:                 # noqa: BLE001
                self._ui_text(f"✗ {exc}")

        threading.Thread(target=work, daemon=True, name="settings-bench").start()

    # ── збереження ─────────────────────────────────────────────────────────
    def _save(self) -> None:
        """Зберегти налаштування. Помилку показуємо, а не ковтаємо.

        Тут був тихий збій: ``float(self.temp_var.get())`` і подібні рядки
        кидали ``ValueError``, якщо користувач вписав у поле «0,3» з комою
        або взагалі текст. Callback Tk падав, діалог лишався відкритим, і
        НІЧОГО не зберігалось — без жодного слова про причину. Тепер
        значення перевіряються заздалегідь, а некоректне поле називається
        користувачу разом із очікуваним форматом.
        """
        bad = self._first_bad_number()
        if bad is not None:
            label, value, hint = bad
            messagebox.showerror(
                "Налаштування",
                f"Поле «{label}» містить «{value}».\nОчікується {hint}.",
                parent=self)
            return
        try:
            self._apply_fields()
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("Збереження налаштувань упало: %s", exc, exc_info=True)
            messagebox.showerror(
                "Налаштування",
                f"Не вдалось зберегти налаштування: {exc}",
                parent=self)
            return
        self.destroy()

    def _number_fields(self) -> list[tuple[str, str, str, str]]:
        """(підпис, ім'я змінної, вид, підказка) для числових полів.

        Один список на всі поля: і перевірка, і збереження беруть його,
        тому додати нове поле достатньо в одному місці.
        """
        return [
            ("Температура", "temp_var", "float", "число від 0 до 2, напр. 0.3"),
            ("Максимум токенів", "tokens_var", "int", "ціле число, напр. 4096"),
            ("Тайм-аут", "timeout_var", "int", "ціле число секунд"),
            ("Розмір шрифту", "size_var", "int", "ціле число, напр. 11"),
            ("Ширина табуляції", "tab_var", "int", "ціле число, напр. 4"),
            ("Кроків агента", "steps_var", "int", "ціле число, напр. 12"),
            ("Хмарні токени", "cloud_tokens", "int", "ціле число, напр. 8192"),
            ("Температура хмари", "cloud_temp", "float", "число від 0 до 2"),
            ("Секунд запису", "voice_seconds", "float", "число, напр. 5"),
            ("Швидкість мовлення", "voice_rate", "int", "ціле від -10 до 10"),
        ]

    def _first_bad_number(self) -> tuple[str, str, str] | None:
        """Перше числове поле з непридатним значенням (або ``None``)."""
        for label, attribute, kind, hint in self._number_fields():
            widget = getattr(self, attribute, None)
            if widget is None:
                continue
            try:
                raw = str(widget.get()).strip()
            except (AttributeError, tk.TclError):
                continue
            if not raw:
                continue                      # порожнє поле — беремо типове
            # Кома як десятковий розділ — звична для української клавіатури.
            candidate = raw.replace(",", ".") if kind == "float" else raw
            try:
                float(candidate) if kind == "float" else int(float(candidate))
            except (TypeError, ValueError):
                return label, raw, hint
        return None

    def _number(self, attribute: str, kind: str, default: float) -> float:
        """Прочитати число з поля; некоректне значення → типове."""
        widget = getattr(self, attribute, None)
        try:
            raw = str(widget.get()).strip() if widget is not None else ""
        except (AttributeError, tk.TclError):
            raw = ""
        if not raw:
            return default
        candidate = raw.replace(",", ".") if kind == "float" else raw
        try:
            return float(candidate) if kind == "float" else int(float(candidate))
        except (TypeError, ValueError):
            LOG.warning("Поле %s: «%s» не число — використано %s",
                        attribute, raw, default)
            return default

    def _apply_fields(self) -> None:
        """Перенести значення полів у ``settings`` (без запису на диск)."""
        s = self.settings
        s.llm.base_url = self.url_entry.get().strip()
        s.llm.api_key = self.key_entry.get().strip()
        s.llm.model = self.model_combo.get().strip()
        s.llm.temperature = self._number("temp_var", "float", 0.3)
        s.llm.max_tokens = int(self._number("tokens_var", "int", 4096))
        s.llm.timeout = int(self._number("timeout_var", "int", 120))
        s.llm.normalise()

        s.ui.font_size = int(self._number("size_var", "int", 11))
        s.ui.font_family = self.font_combo.get()
        s.ui.tab_size = int(self._number("tab_var", "int", 4))
        s.ui.word_wrap = bool(self.wrap_var.get())
        s.ui.show_line_numbers = bool(self.numbers_var.get())
        s.ui.highlight_current_line = bool(self.current_line_var.get())
        s.ui.restore_session = bool(self.restore_var.get())
        s.ui.theme = "light" if "світл" in self.theme_combo.get().lower() else "dark"

        s.agent.system_prompt = self.prompt_text.get("1.0", "end-1c").strip()
        s.agent.confirm_commands = bool(self.confirm_cmd_var.get())
        s.agent.offline_fallback = bool(self.offline_var.get())
        s.agent.max_steps = int(self._number("steps_var", "int", 12))
        s.agent.use_skills = bool(self.skills_var.get())
        s.agent.queue_auto_run = bool(self.autorun_var.get())
        s.agent.stream = bool(self.stream_var.get())
        s.agent.validate_tool_arguments = bool(self.validate_args_var.get())
        s.agent.parallel_tools = bool(self.parallel_var.get())
        s.agent.save_traces = bool(self.traces_var.get())
        s.agent.memory_participates = bool(self.memory_join_var.get())
        s.agent.auto_plan = bool(self.auto_plan_var.get())
        if bool(self.clear_prefs_var.get()):
            s.preferences = []

        # ── відеокарта: простій
        s.engine.unload_when_idle = bool(self.idle_unload_var.get())
        try:
            seconds = int(self.idle_seconds_var.get())
        except (TypeError, ValueError, tk.TclError):
            seconds = 300
        s.engine.idle_unload_seconds = max(60, min(1800, seconds))

        s.mcp.enabled = bool(self.mcp_enabled_var.get())
        s.mcp.auto_load_workspace = bool(self.mcp_auto_var.get())

        # ── контекст локальної моделі (0 = авто)
        # Запам'ятовуємо ЗАВАНТАЖЕНЕ значення ДО будь-яких змін: нижче
        # ``s`` — це той самий об'єкт налаштувань, тож після присвоєння
        # ``s.engine.ctx_size`` старе значення вже втрачене, і порівняння
        # «чи змінено» завжди давало хибний висновок.
        loaded_ctx = int(getattr(self.settings.engine, "ctx_size", 0) or 0)
        try:
            want = int(self.ctx_var.get())
        except (TypeError, ValueError, tk.TclError):
            want = 0
        # Драбина: 0 або кратне 1024 у межах, які взагалі мають сенс.
        s.engine.ctx_size = 0 if want <= 0 else max(2048, min(131072, want))

        # ── вбудований рушій (вкладка «AI Runtime»)
        # УВАЖНО з ``native_ctx``: поле на цій вкладці читається з налаштувань
        # на момент ВІДКРИТТЯ діалогу. Якщо користувач змінив контекст на
        # головній вкладці (або поставив «авто» = 0), старе значення звідси
        # перезаписувало щойно введене — «авто» ніколи не зберігалось
        # (перевірено ``tools/check_context_setting.py``: ставимо 0, а на
        # диску лишається 32768).
        #
        # Головніше поле — те, що на вкладці контексту: саме його бачить
        # користувач. ``native_ctx`` застосовуємо ЛИШЕ коли воно справді
        # змінене відносно завантаженого значення.
        try:
            native_ctx = int(self.native_ctx_var.get())
        except (TypeError, ValueError, tk.TclError):
            native_ctx = 0
        if native_ctx > 0 and native_ctx != loaded_ctx:
            s.engine.ctx_size = max(2048, min(131072, native_ctx))
        s.engine.native = bool(getattr(self, "native_enabled_var", None)
                               and self.native_enabled_var.get())
        # ── АДРЕСА МУСИТЬ ВІДПОВІДАТИ ПРАПОРЦЮ ────────────────────────────
        # Тут був корінь «увімкнув власний рушій — все одно не працює»:
        # прапорець зберігався, а ``llm.base_url`` лишався
        # ``http://127.0.0.1:8080/v1``. Агент бачив HTTP-адресу й ішов у
        # мережу, де нічого не слухає:
        #
        #   Не вдалось з'єднатися з локальним сервером http://127.0.0.1:8080/…
        #   [WinError 10061] No connection could be made because the target
        #   machine actively refused it.
        #
        # Тепер прапорець і адреса перемикаються РАЗОМ.
        if s.engine.native:
            from .native import bridge

            s.llm.base_url = bridge.EMBEDDED_URL          # native://blackchpok
            s.llm.api_key = "local"
            s.llm.auto_detect = False
            # Без автозапуску модель не завантажиться у рушій взагалі.
            s.engine.auto_start = True
        native_model = str(getattr(self, "native_model_var",
                                   tk.StringVar(value="")).get()).strip()
        if native_model:
            s.engine.native_model = native_model
        try:
            layers = int(self.native_layers_var.get())
        except (TypeError, ValueError, tk.TclError):
            layers = -1
        s.engine.native_gpu_layers = max(-1, min(999, layers))
        cache_choice = str(self.native_cache_var.get()).strip().lower()
        s.engine.native_cache_type = "" if cache_choice in ("", "авто") else cache_choice
        # Контекст уже застосовано вище. Друге читання ``native_ctx_var`` тут
        # перезаписувало вибір користувача з вкладки контексту (зокрема
        # «авто» = 0) — саме через цей дубль значення не зберігалось.

        # ── хмарні агенти
        provider = self._current_provider()
        s.cloud.provider = provider.key if provider else "custom"
        s.cloud.api_key = self.cloud_key.get().strip()
        s.cloud.base_url = cloud_agents.normalise_base_url(self.cloud_url.get().strip())
        s.cloud.model = self.cloud_model.get().strip()
        s.cloud.reasoning = bool(self.cloud_reasoning.get())
        s.cloud.max_tokens = int(self._number("cloud_tokens", "int", 8192))
        s.cloud.temperature = self._number("cloud_temp", "float", 0.3)

        # ── голос
        s.voice.enabled = bool(self.voice_enabled.get())
        s.voice.auto_send = bool(self.voice_auto.get())
        s.voice.speak_replies = bool(self.voice_speak.get())
        s.voice.seconds = self._number("voice_seconds", "float", 5.0)
        s.voice.rate = int(self._number("voice_rate", "int", 0))

        # ── соцмережі
        for key, entries in self.social_entries.items():
            values = {name: entry.get().strip() for name, entry in entries.items()}
            s.social.set_values(key, values)

        s.save()
        if self.on_saved:
            self.on_saved()
