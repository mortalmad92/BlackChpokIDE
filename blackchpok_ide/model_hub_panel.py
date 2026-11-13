"""Панель «Хаб моделей»: пошук у реальному часі, смуга завантаження, локальні моделі.

Один екран закриває весь шлях «знайшов → скачав → запустив»:

  * пошук іде паралельно по Hugging Face, GitHub, Civitai і TensorArt и
    результати з'являються в міру надходження;
  * кожен рядок показує розмір, квантування й джерело;
  * завантаження має живу смугу прогресу, швидкість, ETA і скасування;
  * окрема вкладка показує вже завантажені моделі й дозволяє підняти сервер.
"""

from __future__ import annotations

import queue
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Optional

from . import browser_panel
from . import hardware as hw
from . import model_caps
from . import model_hub as hub
from . import runtime as rt
from . import theme, widgets
from .browser_panel import open_url as open_page

LOG = __import__("logging").getLogger("blackchpok.modelhub")

SOURCE_ORDER = ("huggingface", "github", "civitai")
# Символи джерел для компактного списку.
SOURCE_MARK = {"huggingface": "🤗", "github": "🐙", "civitai": "🎨", "tensorart": "🅣"}

#: Стеля очікування на результати пошуку моделей (секунди).
#:
#: Це не таймаут запиту, а захист від «мертвого» джерела: якщо один із
#: пошукових майданчиків не відповідає, потік збирання результатів мусить
#: завершитись і сказати про це, а не висіти вічно (див. ``_collect_search``).
SEARCH_DEADLINE_S = 45.0


class ModelHubPanel(ttk.Frame):
    """Вікно-панель хабу моделей з живою смугою завантаження."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, settings,
                 on_model_ready: Optional[Callable[[str, str], None]] = None,
                 on_before_delete: Optional[Callable[[str], bool]] = None) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.fonts = fonts
        self.settings = settings
        self.on_model_ready = on_model_ready
        self.on_before_delete = on_before_delete
        #: Шляхи, які хаб уже показував. Якщо файл зник з диска, рядок
        #: лишається зі станом «видалено», а не зникає без пояснення.
        self._seen_models: set[str] = set()
        self.profile = hw.HardwareProfile()
        self.hits: list[hub.ModelHit] = []
        self.search_job: Optional[hub.SearchJob] = None
        self.download: Optional[hub.Download] = None
        self.install_job: Optional[rt.EngineInstall] = None
        self.server: Optional[rt.LocalServer] = None
        #: Результати перевірки можливостей: ``{назва моделі: {можливість: bool}}``.
        #: Заповнюється кнопкою «Перевірити можливості» реальними тестами й
        #: ЗБЕРІГАЄТЬСЯ у файлі поруч із налаштуваннями. Раніше словник жив
        #: лише в пам'яті: після перезапуску IDE доказів не було, і значки
        #: знову спирались на назву файлу — рівно те, що ТЗ забороняє.
        self._verified: dict[str, dict[str, bool]] = self._load_verified()
        self._search_after: Optional[str] = None
        self._poll_after: Optional[str] = None
        self._selected: Optional[hub.ModelHit] = None
        # Черга оновлень з фонових потоків — виконується у головному циклі.
        self._ui_queue: "queue.Queue[tuple[Any, tuple[Any, ...], dict[str, Any]]]" = queue.Queue()

        self._build()
        self._poll()

    # ── докази перевірки можливостей (зберігаються) ─────────────────────────
    @staticmethod
    def _verified_path() -> Path:
        from .config import app_data_dir

        return app_data_dir() / "capabilities_verified.json"

    def _load_verified(self) -> dict[str, dict[str, bool]]:
        """Прочитати збережені результати перевірки моделей."""
        import json

        try:
            raw = self._verified_path().read_text(encoding="utf-8")
        except OSError:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        clean: dict[str, dict[str, bool]] = {}
        for name, flags in data.items():
            if isinstance(flags, dict):
                clean[str(name)] = {str(k): bool(v) for k, v in flags.items()}
        return clean

    def _save_verified(self) -> None:
        """Зберегти докази, щоб вони пережили перезапуск IDE."""
        import json

        target = self._verified_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(self._verified, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            LOG.debug("Результати перевірки не збережено", exc_info=True)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        # Результати й вкладки мають забирати весь вільний простір, інакше
        # панель обрізає список і показує лише рядок пошуку.
        for row in range(6):
            self.rowconfigure(row, weight=0)
        self.rowconfigure(4, weight=1)
        self.rowconfigure(3, weight=0)

        head = ttk.Frame(self, style="Panel.TFrame")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        head.columnconfigure(1, weight=1)

        ttk.Label(head, text="ХАБ МОДЕЛЕЙ", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        # Велика іконка поруч із назвою: користувач просив «хаб моделей має
        # бути видно, велика іконка». Емодзі-значок масштабується шрифтом,
        # тож додаткових ресурсів не потрібно.
        self.hub_icon = tk.Label(head, text="🗂", bg=theme.BG_ALT, fg=theme.ACCENT,
                                 font=("Segoe UI", 20))
        self.hub_icon.grid(row=0, column=3, sticky="e", padx=(0, 8))
        self.hw_label = ttk.Label(head, text="Визначаю залізо…", style="Panel.TLabel")
        self.hw_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # рядок пошуку
        search = ttk.Frame(self, style="Panel.TFrame")
        search.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        search.columnconfigure(0, weight=1)

        self.query = tk.StringVar()
        self.entry = ttk.Entry(search, textvariable=self.query, font=self.fonts.ui)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _e: self.start_search())
        self.entry.bind("<KeyRelease>", self._on_typing)
        # Ctrl+V у ttk.Entry не завжди доходить (фокус переходить зі списку),
        # а правого меню в нього немає взагалі. Підключаємо явно: користувач
        # не міг вставити назву моделі — «навіть через Ctrl+V не можу».
        widgets.attach_edit_actions(self.entry)

        find_btn = ttk.Button(search, text="Знайти", style="Accent.TButton",
                              command=self.start_search)
        find_btn.grid(row=0, column=1, padx=(6, 0))
        widgets.Tip(find_btn, "Шукати моделі в позначених джерелах (Enter у полі)")
        reset_btn = ttk.Button(search, text="Скинути", style="Icon.TButton",
                               command=self._clear)
        reset_btn.grid(row=0, column=2, padx=(4, 0))
        widgets.Tip(reset_btn, "Очистити поле пошуку й список результатів")        # Явна кнопка вставки: коли в буфері вже лежить назва моделі, це
        # швидше за Ctrl+V і не залежить від фокуса клавіатури.
        self.paste_btn = ttk.Button(
            search, text="⧉ Вставити", style="Icon.TButton",
            command=self._paste_query)
        self.paste_btn.grid(row=0, column=3, padx=(4, 0))
        widgets.Tip(self.paste_btn,
                    "Вставити назву з буфера обміну (працює і без Ctrl+V)")

        # джерела
        sources = ttk.Frame(self, style="Panel.TFrame")
        sources.grid(row=2, column=0, sticky="new", padx=12)
        self.source_vars: dict[str, tk.BooleanVar] = {}
        for index, source in enumerate(SOURCE_ORDER):
            available, label = hub.source_available(source)
            var = tk.BooleanVar(value=available)
            check = ttk.Checkbutton(sources, text=f"{SOURCE_MARK[source]} {label}", variable=var,
                                    state="normal" if available else "disabled")
            check.grid(row=0, column=index, sticky="w", padx=(0, 10))
            widgets.Tip(
                check,
                f"Шукати в джерелі «{label}»"
                + ("" if available else " — зараз недоступне (немає мережі)"))
            self.source_vars[source] = var
        self.sources_note = ttk.Label(sources, text="", style="Panel.TLabel")
        self.sources_note.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # вкладки: результати / локальні / рушій
        self.nb = ttk.Notebook(self)
        self.nb.grid(row=4, column=0, sticky="nsew", padx=12, pady=(6, 0))
        self.rowconfigure(3, weight=1)

        self.nb.add(self._results_tab(self.nb), text="  Результати  ")
        self.nb.add(self._local_tab(self.nb), text="  Локальні  ")
        self.nb.add(self._engine_tab(self.nb), text="  Рушій  ")

        # смуга завантаження — завжди внизу, видима з будь-якої вкладки
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.grid(row=5, column=0, sticky="ew", padx=12, pady=(8, 12))
        bar.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ttk.Button(bar, text="Стоп", style="Icon.TButton", command=self._cancel_download)
        self.cancel_btn.grid(row=0, column=1, padx=(6, 0))
        self.cancel_btn.state(["disabled"])
        widgets.Tip(self.cancel_btn,
                    "Скасувати завантаження. Недокачаний файл .part прибирається "
                    "й не займає місце")

        self.status = ttk.Label(bar, text="Готово. Введи назву моделі й натисни «Знайти».",
                                style="Panel.TLabel")
        self.status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _results_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, style="Panel.TFrame")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        self.results = ttk.Treeview(
            frame,
            columns=("source", "caps", "model", "size", "meta"),
            show="headings",
            selectmode="browse",
        )
        self.results.heading("source", text="")
        self.results.column("source", width=36, anchor="center", stretch=False)
        # Позначки можливостей: 🔨 інструменти · 🧠 міркування · 🖼 зображення · 🎙 голос
        self.results.heading("caps", text="🔨🧠🖼🎙")
        self.results.column("caps", width=74, anchor="center", stretch=False)
        self.results.heading("model", text="Модель")
        self.results.column("model", width=300, anchor="w")
        self.results.heading("size", text="Розмір")
        self.results.column("size", width=80, anchor="e", stretch=False)
        self.results.heading("meta", text="Деталі")
        self.results.column("meta", width=180, anchor="w")
        self.results.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.results.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)
        self.results.bind("<<TreeviewSelect>>", self._on_select)
        self.results.bind("<Double-1>", lambda _e: self.download_selected())

        actions = ttk.Frame(frame, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        dl_btn = ttk.Button(actions, text="Завантажити", style="Accent.TButton",
                            command=self.download_selected)
        dl_btn.pack(side="left")
        widgets.Tip(dl_btn, "Завантажити вибрану модель у теку моделей "
                            "(з докачкою й перевіркою цілісності)")
        quant_btn = ttk.Button(actions, text="Варіанти квантування…", style="Icon.TButton",
                               command=self.show_quants)
        quant_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(quant_btn, "Показати доступні квантизації цієї моделі "
                               "й вибрати розмір файлу")
        page_btn = ttk.Button(actions, text="Сторінка в браузері", style="Icon.TButton",
                              command=self.open_page)
        page_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(page_btn, "Відкрити сторінку моделі в вбудованому браузері")
        return frame

    def _local_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, style="Panel.TFrame")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.local_list = ttk.Treeview(frame, columns=("caps", "name", "size", "state"),
                                       show="headings", selectmode="browse")
        self.local_list.heading("caps", text="🔨🧠🖼🎙")
        self.local_list.column("caps", width=74, anchor="center", stretch=False)
        self.local_list.heading("name", text="Файл моделі")
        self.local_list.column("name", width=280, anchor="w")
        self.local_list.heading("size", text="Розмір")
        self.local_list.column("size", width=80, anchor="e", stretch=False)
        self.local_list.heading("state", text="На диску")
        self.local_list.column("state", width=110, anchor="w", stretch=False)
        self.local_list.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.local_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.local_list.configure(yscrollcommand=scroll.set)
        self.local_list.bind("<Double-1>", lambda _e: self.use_local())

        actions = ttk.Frame(frame, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        run_btn = ttk.Button(actions, text="Запустити цю модель", style="Accent.TButton",
                             command=self.use_local)
        run_btn.pack(side="left")
        widgets.Tip(run_btn, "Завантажити модель у ВЛАСНИЙ рушій IDE "
                             "(модель працює всередині програми)")
        # Перевірка РЕАЛЬНИХ можливостей: дає доказ, а не припущення.
        # Значок у списку ставиться за фактом тесту, а не за назвою файлу.
        verify_btn = ttk.Button(actions, text="Перевірити можливості", style="Icon.TButton",
                                command=self.verify_capabilities)
        verify_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(verify_btn, "Зробити справжні запити до моделі й показати доказ: "
                                "інструменти, зір, міркування, JSON, стрімінг")
        refresh_btn = ttk.Button(actions, text="Оновити", style="Icon.TButton",
                                 command=self.refresh_local)
        refresh_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(refresh_btn, "Перечитати теку моделей з диска і перевірити, "
                                 "чи файли ще існують")
        delete_btn = ttk.Button(actions, text="Видалити файл", style="Icon.TButton",
                                command=self.delete_local)
        delete_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(delete_btn, "Видалити вибраний .gguf з диска. "
                                "Спершу треба підтвердити")
        folder_btn = ttk.Button(actions, text="Тека моделей", style="Icon.TButton",
                                command=self._open_models_folder)
        folder_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(folder_btn, "Відкрити теку з файлами .gguf у провіднику Windows")
        return frame

    def _engine_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, style="Panel.TFrame", padding=10)
        frame.columnconfigure(0, weight=1)

        self.engine_label = ttk.Label(frame, text="Перевіряю рушій…", style="Panel.TLabel",
                                      wraplength=560, justify="left")
        self.engine_label.grid(row=0, column=0, sticky="w")

        buttons = ttk.Frame(frame, style="Panel.TFrame")
        buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.install_btn = ttk.Button(buttons, text="Встановити рушій llama.cpp",
                                      style="Accent.TButton", command=self.install_engine)
        self.install_btn.pack(side="left")
        widgets.Tip(self.install_btn,
                    "Завантажити llama.cpp (llama.dll) під це залізо. "
                    "Рушій виконує модель ВСЕРЕДИНІ IDE, без сторонніх програм")
        self.stop_btn = ttk.Button(buttons, text="Зупинити сервер", style="Icon.TButton",
                                   command=self.stop_server)
        self.stop_btn.pack(side="left", padx=(6, 0))
        widgets.Tip(self.stop_btn,
                    "Зупинити зовнішній llama-server і звільнити відеопам'ять. "
                    "Вбудований рушій зупиняється кнопкою «Вивантажити» "
                    "на панелі AI Runtime")

        self.engine_log = tk.Text(frame, height=12, wrap="word", bg=theme.BG_INPUT, fg=theme.FG,
                                  insertbackground=theme.FG_BRIGHT, relief="flat",
                                  font=self.fonts.mono_small, padx=8, pady=6)
        self.engine_log.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        frame.rowconfigure(2, weight=1)
        self.refresh_engine()
        return frame

    # ── залізо ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Показати локальні моделі. Залізо визначаємо один раз.

        Повторний виклик (клік по вкладці) лише оновлює список файлів і
        не затирає вже введений пошуковий запит.
        """
        self.refresh_local()
        if getattr(self, "_hardware_started", False):
            return
        self._hardware_started = True
        threading.Thread(target=self._detect_hardware, daemon=True).start()

    def _detect_hardware(self) -> None:
        try:
            self.profile = hw.detect()
        except Exception:  # noqa: BLE001 - залізо не має ламати панель
            return
        recommendation = hw.recommend(self.profile)
        text = f"{self.profile.summary()}\nРекомендую: {recommendation.label} ({recommendation.approx_gb:.1f} ГБ)"
        self._ui(self.hw_label.configure, text=text)
        self._ui(self.query.set, recommendation.label.replace("Qwen2.5-Coder ", "qwen2.5 coder "))

    def _ui(self, func, *args, **kwargs) -> None:
        """Поставити оновлення інтерфейсу в чергу.

        Викликати віджети (і навіть ``after``) з робочого потоку небезпечно:
        tkinter не гарантує потокобезпеки, і в Release-збірці оновлення просто
        губиться. Тому фонові потоки лише кладуть дію в чергу, а виконує її
        головний цикл у ``_poll``.
        """
        self._ui_queue.put((func, args, kwargs))


    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _drain_ui(self) -> None:
        """Виконати накопичені оновлення (тільки з головного потоку)."""
        for _ in range(200):
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                func(*args, **kwargs)
            except tk.TclError:
                pass


    # ── пошук ──────────────────────────────────────────────────────────────
    def _on_typing(self, _event=None) -> None:
        """Пошук у реальному часі: невелика пауза після останнього символу."""
        if self._search_after:
            try:
                self.after_cancel(self._search_after)
            except (tk.TclError, ValueError):
                pass
        self._search_after = self.after(450, self.start_search)

    def start_search(self) -> None:
        query = self.query.get().strip()
        if len(query) < 2:
            self._set_status("Введи хоча б два символи назви моделі.")
            return
        sources = tuple(name for name, var in self.source_vars.items() if var.get())
        if not sources:
            self._set_status("Обери хоча б одне джерело.")
            return
        if self.search_job is not None and self.search_job.running:
            self.search_job.cancel()

        self.results.delete(*self.results.get_children(""))
        self.hits.clear()
        self._set_status(f"Шукаю «{query}» у {len(sources)} джерелах…")
        self.sources_note.configure(text="")
        job = hub.SearchJob(query, sources, limit=12)
        job.start()
        self.search_job = job
        threading.Thread(target=self._collect_search, args=(job,), daemon=True).start()

    def _collect_search(self, job: hub.SearchJob) -> None:
        """Чекати результати кожного джерела й одразу додавати їх у список.

        Чому тут дедлайн. Раніше цикл виходив ЛИШЕ коли ``job.running`` стало
        хибним І черга порожня. Якщо хоч одне джерело повисло (мережа без
        відповіді, ``urllib`` без таймауту всередині), потік не завершувався
        НІКОЛИ: статус вічно показував «Шукаю…», а новий пошук запускав ще
        один такий самий потік. Тепер є стеля часу: після неї чесно кажемо,
        що частина джерел не відповіла, і звільняємо потік.
        """
        deadline = time.monotonic() + SEARCH_DEADLINE_S
        while True:
            try:
                source, hits, error = job.results.get(timeout=0.3)
            except Exception:  # noqa: BLE001 - queue.Empty
                if not job.running and job.results.empty():
                    break
                if time.monotonic() > deadline:
                    LOG.warning("Пошук моделей не завершився за %s с — "
                                "показую те, що встигло прийти", SEARCH_DEADLINE_S)
                    self._ui(self._note_error, "пошук",
                             f"частина джерел не відповіла за "
                             f"{int(SEARCH_DEADLINE_S)} с")
                    break
                continue
            if error:
                self._ui(self._note_error, source, error)
                continue
            for hit in hits:
                self._ui(self._add_hit, hit)
        total = len(self.hits)
        self._ui(self._set_status, f"Знайдено {total} результатів." if total else
                 "Нічого не знайдено. Спробуй іншу назву або інше джерело.")
        self._ui(self.nb.select, 0)

    def _note_error(self, source: str, error: str) -> None:
        label = hub.SOURCE_LABELS.get(source, source)
        current = self.sources_note.cget("text")
        text = f"{current}  ✗ {label}: {error}".strip()
        self.sources_note.configure(text=text[:180])

    def _capabilities_text(self, hit: hub.ModelHit) -> tuple[str, str]:
        """(позначки, підказка) для рядка результатів."""
        caps = model_caps.from_hit(hit)
        return model_caps.split_icons(caps), caps.tooltip()

    def _add_hit(self, hit: hub.ModelHit) -> None:
        if len(self.hits) >= 200:
            return
        self.hits.append(hit)
        detail = hit.quant or hit.base_model or (hit.kind if hit.kind != "llm" else "")
        model_text = hit.name
        if hit.filename and hit.filename != hit.name:
            model_text = f"{hit.name}  ·  {hit.filename}"
        self.results.insert(
            "",
            "end",
            iid=str(len(self.hits) - 1),
            values=(SOURCE_MARK.get(hit.source, "•"), self._capabilities_text(hit)[0],
                    model_text[:90], hit.size_text, detail),
        )

    def _on_select(self, _event=None) -> None:
        selection = self.results.selection()
        if not selection:
            self._selected = None
            return
        try:
            self._selected = self.hits[int(selection[0])]
        except (ValueError, IndexError):
            self._selected = None

    def _clear(self) -> None:
        self.query.set("")
        self.results.delete(*self.results.get_children(""))
        self.hits.clear()
        self.sources_note.configure(text="")
        self._set_status("Готово.")

    def _paste_query(self) -> None:
        """Вставити назву моделі з буфера й ОДРАЗУ шукати.

        Користувач скаржився: «ввожу Ministral, результати є, а побачити не
        можу». Тому кнопка не лише вставляє текст, а й запускає пошук —
        результат з'являється без другого кліку.
        """
        try:
            text = str(self.clipboard_get() or "").strip()
        except tk.TclError:
            self._set_status("Буфер обміну порожній — скопіюй назву моделі.")
            return
        if not text:
            self._set_status("Буфер обміну порожній — скопіюй назву моделі.")
            return
        # Багаторядковий текст (напр. скопійований рядок таблиці) зводимо
        # до одного рядка: у полі пошуку переносів бути не має.
        clean = " ".join(text.split())
        self.query.set(clean[:120])
        self.entry.icursor("end")
        self._set_status(f"Вставлено: {clean[:60]}")
        self.start_search()

    # ── завантаження ───────────────────────────────────────────────────────
    def download_selected(self) -> None:
        hit = self._selected
        if hit is None and self.results.selection():
            self._on_select()
            hit = self._selected
        if hit is None:
            self._set_status("Спершу вибери модель у списку.")
            return
        self._start_download(hit)

    def _start_download(self, hit: hub.ModelHit) -> None:
        if self.download is not None and self.download.running:
            self._set_status("Уже завантажую іншу модель. Дочекайся або натисни «Стоп».")
            return
        if hit.source != "huggingface":
            self._set_status(f"{hit.source_label}: ваги не завантажуються напряму — відкриваю сторінку.")
            if hit.page_url:
                open_page(hit.page_url)
            return
        if not hit.filename:
            self._set_status("У цій моделі немає GGUF-файлу — відкрий сторінку й вибери іншу версію.")
            if hit.page_url:
                open_page(hit.page_url)
            return

        free_gb = self.profile.disk_free_gb
        needed_gb = hit.size_gb * 1.1
        if free_gb and needed_gb > free_gb:
            messagebox.showwarning(
                "Мало місця",
                f"Файл {hit.size_text} більший за вільне місце ({free_gb:.0f} ГБ).\n"
                "Звільни диск або вибери менше квантування.",
                parent=self.winfo_toplevel(),
            )
            return

        try:
            task = hub.download_model(hit, target_dir=hub.models_dir())
        except hub.HubError as exc:
            self._set_status(f"Не вдалось підготувати завантаження: {exc}")
            return

        self.progress.configure(value=0)
        self.cancel_btn.state(["!disabled"])
        self._set_status(f"Завантажую {hit.filename} ({hit.size_text})…")
        self.download = task
        task.start()

    def _cancel_download(self) -> None:
        if self.download is not None and self.download.running:
            self.download.cancel()
            self._set_status("Скасовую завантаження…")
        if self.install_job is not None and self.install_job.running:
            self.install_job.cancel()
            self._set_status("Скасовую встановлення рушія…")

    def _poll(self) -> None:
        """Опитувати стан завантаження й оновлювати смугу (головний цикл)."""
        try:
            self._drain_ui()
            self._poll_download()
            self._poll_engine()
            self._poll_server()
        finally:
            try:
                self._poll_after = (self.after(200, self._poll) if self._timer_alive() else None)
            except tk.TclError:
                pass

    def _poll_download(self) -> None:
        task = self.download
        if task is None:
            return
        state = task.state
        if state.done:
            self.progress.configure(value=100)
            self.cancel_btn.state(["disabled"])
            size_gb = state.downloaded / (1024 ** 3)
            self._set_status(f"✓ Завантажено: {Path(state.path).name} ({size_gb:.2f} ГБ)")
            self.download = None
            self.refresh_local()
            self._ask_use_new_model(Path(state.path))
            return
        if state.error:
            self.cancel_btn.state(["disabled"])
            if state.error != "Скасовано":
                self._set_status(f"✗ {state.error}")
            else:
                self._set_status("Завантаження скасовано.")
            self.download = None
            return
        self.progress.configure(value=state.percent)
        parts = [f"{state.percent:5.1f}%"]
        if state.total:
            parts.append(f"{state.downloaded / 2**30:.2f} з {state.total / 2**30:.2f} ГБ")
        if state.speed_text:
            parts.append(state.speed_text)
        if state.eta_text:
            parts.append(f"лишилось ~{state.eta_text}")
        self._set_status("  ·  ".join(parts))

    def _ask_use_new_model(self, path: Path) -> None:
        if messagebox.askyesno("Модель готова",
                               f"Завантажено {path.name}.\nЗапустити її зараз як робочу модель?",
                               parent=self.winfo_toplevel()):
            self._activate_model(path)

    # ── локальні моделі ────────────────────────────────────────────────────
    def refresh_local(self) -> None:
        try:
            self.local_list.delete(*self.local_list.get_children(""))
        except (tk.TclError, AttributeError):
            return
        ordered: list[Path] = []
        seen: set[str] = set()

        def _take(path: Path) -> None:
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                return
            seen.add(key)
            ordered.append(path)

        for path in hub.local_models():
            _take(path)
        engine = getattr(self.settings, "engine", None)
        for raw in (getattr(engine, "native_model", ""), getattr(engine, "model_path", "")):
            text = str(raw or "").strip()
            if text.lower().endswith(".gguf"):
                _take(Path(text))
        for remembered in list(self._seen_models):
            _take(Path(remembered))
        for path in ordered:
            exists = path.is_file()
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if exists:
                self._seen_models.add(key)
            try:
                size = path.stat().st_size if exists else 0
            except OSError:
                size = 0
                exists = False
            # local_path передаємо, щоб значок зору означав ФАКТ (є проєктор
            # на диску), а не лише слово в назві файлу.
            caps = model_caps.detect(path.name, filename=path.name,
                                     local_path=path if exists else None)
            # ── Доказ важливіший за припущення ────────────────────────────
            # Якщо модель перевірено кнопкою «Перевірити можливості»,
            # показуємо результат ТЕСТУ. Якщо ні — значки з назви файлу
            # позначаємо як припущення: ТЗ прямо забороняє зелений значок
            # за назвою моделі або за наявністю файлу MMProj.
            verified = (self._verified or {}).get(path.stem)
            icons = ""
            if verified:
                caps.flags[model_caps.TOOLS] = bool(verified.get("tool_calling"))
                caps.flags[model_caps.VISION] = bool(verified.get("vision"))
                caps.flags[model_caps.REASONING] = bool(verified.get("reasoning"))
                icons = model_caps.split_icons(caps)
            else:
                # Немає тесту — показуємо «?» замість вигаданих значків.
                guessed = caps.icon_text()
                icons = f"? {guessed}" if guessed else "?"
            state = "на диску" if exists else "видалено"
            self.local_list.insert("", "end", text=str(path), values=(
                icons,
                path.name,
                f"{size / 2**30:.2f} ГБ" if size else "—",
                state))

    def _selected_local(self) -> Optional[Path]:
        selection = self.local_list.selection()
        if not selection:
            return None
        text = self.local_list.item(selection[0], "text")
        return Path(text) if text else None

    def use_local(self) -> None:
        path = self._selected_local()
        if path is None:
            self._set_status("Вибери модель у списку «Локальні».")
            return
        if not path.is_file():
            self._set_status(f"Файлу немає на диску: {path.name}. Його вже видалено.")
            self.refresh_local()
            return
        self._activate_model(path)

    def delete_local(self) -> None:
        """Видалити вибраний файл моделі з диска після підтвердження."""
        path = self._selected_local()
        if path is None:
            self._set_status("Вибери модель у списку «Локальні».")
            return
        if not path.is_file():
            self._seen_models.discard(str(path))
            try:
                self._seen_models.discard(str(path.resolve()))
            except OSError:
                pass
            self._set_status(f"Файлу вже немає: {path.name}")
            self.refresh_local()
            return
        if not messagebox.askyesno(
                "Видалити модель",
                f"Видалити файл з диска?\n\n{path}\n\nЦе не скасувати.",
                parent=self.winfo_toplevel()):
            return
        guard = getattr(self, "on_before_delete", None)
        if guard is not None:
            try:
                allowed = bool(guard(str(path)))
            except Exception as exc:  # noqa: BLE001 - видалення не має падати
                self._set_status(f"Не вдалось звільнити модель: {exc}")
                return
            if not allowed:
                return
        try:
            hub.delete_local_model(path)
        except OSError as exc:
            messagebox.showerror("Видалення", f"Файл не видалено: {exc}",
                                 parent=self.winfo_toplevel())
            return
        try:
            gone = str(path.resolve())
        except OSError:
            gone = str(path)
        self._seen_models.discard(gone)
        self._seen_models.discard(str(path))
        engine = getattr(self.settings, "engine", None)
        if engine is not None:
            for field_name in ("native_model", "model_path"):
                current = str(getattr(engine, field_name, "") or "")
                try:
                    same = bool(current) and Path(current).resolve() == Path(gone)
                except OSError:
                    same = current == str(path)
                if same:
                    setattr(engine, field_name, "")
            try:
                self.settings.save()
            except OSError:
                LOG.debug("Налаштування після видалення не записано", exc_info=True)
        self.refresh_local()
        self._set_status(f"Видалено {path.name}")

    def _open_models_folder(self) -> None:
        folder = hub.models_dir()
        # Тека на диску — це НЕ сторінка: показуємо у вбудованому браузері
        # списком файлів (``file://``), щоб не відкривати провідник Windows.
        if not browser_panel.open_url(folder.as_uri() if folder.exists() else ""):
            self._set_status(f"Тека моделей: {folder}")

    # ── рушій ──────────────────────────────────────────────────────────────
    def refresh_engine(self) -> None:
        installed = rt.engine_installed()
        version = rt.engine_version()
        backend = ""
        try:
            backend = (rt.runtime_dir() / "backend.txt").read_text(encoding="utf-8").strip()
        except OSError:
            pass
        if installed:
            text = (f"✓ Рушій встановлено{(' · ' + version) if version else ''}"
                    f"{(' · ' + backend.upper()) if backend else ''}\n"
                    f"Тека: {rt.runtime_dir()}")
            self.install_btn.configure(text="Перевстановити рушій")
        else:
            text = ("Рушій не встановлено. Натисни «Встановити рушій llama.cpp» — "
                    "IDE сама скачає збірку з GitHub (Vulkan/CUDA/CPU) під твоє залізо.")
            self.install_btn.configure(text="Встановити рушій llama.cpp")
        self.engine_label.configure(text=text)

    def install_engine(self) -> None:
        if self.install_job is not None and self.install_job.running:
            self._set_status("Встановлення вже йде.")
            return
        self._engine_log("Починаю встановлення рушія…")
        self.cancel_btn.state(["!disabled"])
        job = rt.EngineInstall(
            profile=self.profile if self.profile.cpu_threads else None,
            on_status=lambda text: self._ui(self._engine_log, text),
        )
        job.start()
        self.install_job = job

    def _poll_engine(self) -> None:
        job = self.install_job
        if job is None:
            return
        task = job.download
        if task is not None and task.running:
            state = task.state
            self.progress.configure(value=state.percent)
            if state.speed_text:
                self._set_status(f"Рушій: {state.percent:.0f}%  ·  {state.speed_text}")
        if job.running:
            return
        self.install_job = None
        self.cancel_btn.state(["disabled"])
        if job.error:
            self._engine_log(f"✗ {job.error}")
            self._set_status(f"Не вдалось встановити рушій: {job.error[:120]}")
        else:
            self.progress.configure(value=100)
            self._engine_log("✓ Рушій готовий.")
            self._set_status("Рушій llama.cpp встановлено.")
        self.refresh_engine()

    def _engine_log(self, text: str) -> None:
        try:
            self.engine_log.insert("end", text + "\n")
            self.engine_log.see("end")
        except (tk.TclError, AttributeError):
            pass

    # ── запуск сервера ─────────────────────────────────────────────────────
    def _activate_model(self, path: Path) -> None:
        if not rt.engine_installed():
            if not messagebox.askyesno(
                "Потрібен рушій",
                "Для запуску моделі потрібен llama.cpp. Встановити його зараз (≈200–400 МБ)?",
                parent=self.winfo_toplevel(),
            ):
                return
            self.install_engine()
            self._set_status("Спершу встановлюю рушій — потім запущу модель.")
            return
        if self.server is not None and self.server.running:
            self.server.stop()
            self.server = None

        self._set_status(f"Запускаю {path.name}…")
        threading.Thread(target=self._start_server, args=(path,), daemon=True).start()

    def _start_server(self, path: Path) -> None:
        try:
            choice = self._guess_choice(path)
            # Бажаний контекст беремо з налаштувань: 0 — авто (найбільший,
            # що влізе). Явне число дає змогу підняти контекст ціною
            # частини VRAM або з винесенням KV-кешу в RAM.
            want_ctx = 0
            try:
                want_ctx = int(getattr(self.settings.engine, "ctx_size", 0) or 0)
            except (AttributeError, TypeError, ValueError):
                want_ctx = 0
            plan = (hw.fit(self.profile, choice, target_ctx=want_ctx).plan
                    if self.profile.cpu_threads else None)
            if plan is not None:
                self._ui(self._set_status, f"План запуску: {plan.summary()}")
            port = rt.free_port(8080)
            config = rt.ServerConfig(model_path=str(path), port=port, plan=plan)
            server = rt.LocalServer(config)
            server.start()
            self.server = server
            ok, detail = server.wait_ready(timeout=240,
                                           on_status=lambda s: self._ui(self._set_status, s))
            if not ok:
                self._ui(self._set_status, f"✗ Модель не запустилась: {detail[:200]}")
                server.stop()
                self.server = None
                return
            self._ui(self._on_server_ready, server.base_url, path)
        except Exception as exc:  # noqa: BLE001 - показуємо користувачу
            self._ui(self._set_status, f"✗ {type(exc).__name__}: {exc}")

    def _on_server_ready(self, base_url: str, path: Path) -> None:
        self._set_status(f"✓ Модель працює: {base_url}")
        if self.on_model_ready:
            self.on_model_ready(base_url, path.stem)
        self.refresh_engine()
        self._engine_log(f"Сервер: {base_url}")

    def verify_capabilities(self) -> None:
        """Перевірити СПРАВЖНІ можливості вибраної моделі.

        Чому кнопка, а не автоматика. Перевірка робить кілька реальних
        запитів до моделі, кожен із яких триває секунди. Робити це мовчки на
        кожен клік списку — марно. Користувач натискає кнопку й отримує
        доказ: що саме перевірено, яким запитом і який результат.
        """
        path = self._selected_local()
        if path is None:
            self._set_status("Вибери модель у списку «Локальні», щоб перевірити.")
            return
        if self.server is None or not getattr(self.server, "running", False):
            self._set_status("Спершу запусти модель — перевіряти нічого.")
            return
        base_url = self.server.base_url
        model_name = path.stem
        self._set_status(f"Перевіряю можливості {model_name}…")
        self._engine_log(f"── Перевірка можливостей: {model_name} ──")

        def work() -> None:
            from . import model_verify

            # Тестове зображення: беремо свіжий знімок сторінки, якщо він є.
            # Без зображення тест зору пропускається (а не «проходить»).
            image = None
            try:
                from .config import app_data_dir

                folder = app_data_dir() / "screenshots"
                shots = sorted(folder.glob("*.png"),
                               key=lambda p: p.stat().st_mtime, reverse=True)
                image = shots[0] if shots else None
            except Exception:  # noqa: BLE001
                image = None
            # ── Еталон для зору ───────────────────────────────────────────
            # Без очікуваних слів тест зору НЕ може пройти: «модель щось
            # написала» не доводить, що вона бачить саме це зображення.
            # Раніше GUI не передавав еталон, і зір був зеленим завжди —
            # зокрема на відповідь «я не можу аналізувати зображення».
            expected: tuple[str, ...] = ()
            if image is not None:
                expected = self._vision_expectation(image)
            if image is not None and not expected:
                # Еталона немає — краще згенерувати власне контрольне
                # зображення з відомим вмістом, ніж показувати фальшивий ✓.
                image = self._verify_probe_image()
                expected = ("квадрат", "square", "червон", "red")
            report = model_verify.run_all(
                base_url, model_name,
                vision_image=image,
                vision_expected=expected,
                on_progress=lambda text: self._ui(self._set_status, text))
            for item in report.results:
                self._ui(self._engine_log, "  " + item.line())
            self._ui(self._after_verify, report)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _vision_expectation(image: Path) -> tuple[str, ...]:
        """Слова, які МУСИТЬ згадати модель для цього зображення.

        Для скріншота IDE очікуємо згадку інтерфейсу або його елементів.
        Це не ідеальний еталон, але він відсіює випадок «модель не бачить
        зображення взагалі» — головний ризик, який треба виявити.
        """
        try:
            name = image.name.lower()
        except AttributeError:
            return ()
        if "screen" in name or "shot" in name:
            return ("вікно", "інтерфейс", "панель", "кнопк", "текст",
                    "window", "interface", "panel", "button")
        return ()

    def _verify_probe_image(self) -> Path:
        """Створити контрольне зображення з ВІДОМИМ вмістом.

        Червоне коло на білому тлі — модель із зором назве коло/квадрат/колір.
        Модель без зору не зможе цього зробити (або прямо відмовиться).
        """
        from . import multiscale
        from .config import app_data_dir

        folder = app_data_dir() / "screenshots"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = Path(tempfile.gettempdir())
        target = folder / "verify-probe.png"
        size = 128
        rgb = bytearray(size * size * 3)
        for y in range(size):
            for x in range(size):
                index = (y * size + x) * 3
                dx, dy = x - size / 2, y - size / 2
                inside = (dx * dx + dy * dy) < (size * 0.36) ** 2
                if inside:
                    rgb[index], rgb[index + 1], rgb[index + 2] = 220, 30, 30
                else:
                    rgb[index] = rgb[index + 1] = rgb[index + 2] = 255
        try:
            multiscale.write_png(target, size, size, bytes(rgb))
        except OSError:
            pass
        return target

    def _after_verify(self, report) -> None:
        """Показати підсумок і зберегти докази."""
        self._set_status(report.summary())
        try:
            self._verified[report.model] = report.capabilities
        except AttributeError:
            self._verified = {report.model: report.capabilities}
        # Доказ має пережити перезапуск: інакше після рестарту значки знову
        # спираються на назву файлу.
        self._save_verified()
        self._engine_log("── Підсумок ──")
        self._engine_log(report.text())
        # Оновлюємо список: значки тепер можуть спиратись на ФАКТ перевірки.
        self.refresh_local()

    def _guess_choice(self, path: Path) -> hw.ModelChoice:
        """Приблизно оцінити модель за назвою файлу (для параметрів запуску)."""
        name = path.name.lower()
        for token, params, layers in (("0.5b", 0.5, 24), ("1.5b", 1.5, 28), ("3b", 3.0, 36),
                                      ("4b", 4.0, 36), ("7b", 7.0, 28), ("8b", 8.0, 32),
                                      ("14b", 14.0, 48), ("32b", 32.0, 64), ("70b", 70.0, 80)):
            if token in name:
                size_gb = params * 0.62
                return hw.ModelChoice(str(path.parent), path.name, path.stem, params, size_gb, 0.0, "", layers)
        size_gb = max(0.5, path.stat().st_size / 2**30) if path.exists() else 2.0
        return hw.ModelChoice(str(path.parent), path.name, path.stem, max(1.0, size_gb / 0.62),
                              size_gb, 0.0, "", 32)

    def _poll_server(self) -> None:
        if self.server is not None and not self.server.running:
            self.server = None
            self._engine_log("Сервер зупинився.")

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None
            self._set_status("Сервер зупинено.")
        else:
            self._set_status("Сервер не запущений.")

    def on_close(self) -> None:
        if self._poll_after:
            try:
                self.after_cancel(self._poll_after)
            except (tk.TclError, ValueError):
                pass
        self._cancel_download()
        if self.search_job is not None:
            self.search_job.cancel()

    # ── додаткові дії ──────────────────────────────────────────────────────
    def show_quants(self) -> None:
        hit = self._selected
        if hit is None or hit.source != "huggingface":
            self._set_status("Варіанти квантування доступні для моделей Hugging Face.")
            return
        self._set_status(f"Читаю список файлів {hit.model_id}…")
        threading.Thread(target=self._load_quants, args=(hit,), daemon=True).start()

    def _load_quants(self, hit: hub.ModelHit) -> None:
        try:
            files = hub.resolve_files(hit.model_id)
        except hub.HubError as exc:
            self._ui(self._set_status, f"✗ {exc}")
            return
        options = [f for f in files if f["size"] and not f["multipart"]]
        if not options:
            self._ui(self._set_status, "У цій моделі немає готових GGUF-файлів.")
            return
        self._ui(self._show_quant_dialog, hit, options)

    def _show_quant_dialog(self, hit: hub.ModelHit, options: list[dict[str, Any]]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(f"Квантування · {hit.name}")
        dialog.configure(bg=theme.BG)
        dialog.transient(self.winfo_toplevel())

        ttk.Label(dialog, text=f"{hit.model_id}", style="Header.TLabel").pack(
            anchor="w", padx=12, pady=(10, 2))
        budget = self.profile.usable_gb
        ttk.Label(dialog, text=f"Твоє залізо вміщає приблизно {budget:.0f} ГБ ваг.",
                  style="Panel.TLabel").pack(anchor="w", padx=12, pady=(0, 6))

        tree = ttk.Treeview(dialog, columns=("name", "size", "fit"), show="headings", selectmode="browse")
        tree.heading("name", text="Файл")
        tree.column("name", width=300, anchor="w")
        tree.heading("size", text="Розмір")
        tree.column("size", width=90, anchor="e", stretch=False)
        tree.heading("fit", text="")
        tree.column("fit", width=90, anchor="center", stretch=False)
        tree.pack(fill="both", expand=True, padx=12)

        for index, item in enumerate(options):
            gb = item["size"] / 2**30
            mark = "✓ влізе" if budget and gb <= budget else ("— велика" if budget else "")
            tree.insert("", "end", iid=str(index), values=(item["name"], f"{gb:.2f} ГБ", mark))

        def take() -> None:
            selection = tree.selection()
            if not selection:
                return
            item = options[int(selection[0])]
            dialog.destroy()
            variant = hub.ModelHit(
                source="huggingface",
                model_id=hit.model_id,
                name=hit.name,
                filename=item["name"],
                size_bytes=int(item["size"]),
                page_url=hit.page_url,
                download_url=hub.download_url_for(hit.model_id, item["name"]),
            )
            self._start_download(variant)

        tree.bind("<Double-1>", lambda _e: take())
        footer = ttk.Frame(dialog, style="Panel.TFrame")
        footer.pack(fill="x", padx=12, pady=10)
        ttk.Button(footer, text="Завантажити вибране", style="Accent.TButton", command=take).pack(side="right")
        ttk.Button(footer, text="Закрити", command=dialog.destroy).pack(side="right", padx=(6, 0))
        # Діалог має бути в межах екрана й модальним лише один за раз.
        widgets.place_window(dialog, width=560, height=420, center_on=self)
        widgets.open_only_modal(dialog)

    def open_page(self) -> None:
        hit = self._selected
        if hit is None or not hit.page_url:
            self._set_status("Вибери результат, щоб відкрити його сторінку.")
            return
        # Сторінка моделі — у вбудованому браузері, а не в браузері ПК.
        if not open_page(hit.page_url):
            self._set_status(f"Не вдалось відкрити сторінку. Адреса: {hit.page_url}")

    def _set_status(self, text: str) -> None:
        try:
            self.status.configure(text=text)
        except tk.TclError:
            pass


__all__ = ["ModelHubPanel"]
