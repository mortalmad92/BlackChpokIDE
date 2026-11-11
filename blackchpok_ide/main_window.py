"""Головне вікно BlackChpok IDE у стилі сучасного агентного редактора.

Розкладка повторює дизайн, до якого ми прагнемо:

    ┌────┬────────────────┬─────────────────────────┬───────────────┐
    │    │  бічна панель  │   редактор / нижня      │  агент        │
    │рейк│  (провідник,   │   панель (термінал,     │  (чат)        │
    │    │  скіли, черга) │   пошук, хаб, MCP)      │  + контекст   │
    └────┴────────────────┴─────────────────────────┴───────────────┘

Усе, що натискається, справді працює: кнопки рейки перемикають панелі,
вкладки закриваються хрестиком, термінал тримає живу сесію, а черга задач
виконується тим самим агентом, що й чат.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

from . import (
    adaptive,
    app_control,
    auto_setup,
    autonomous,
    autonomous_panel,
    browser_panel,
    cases_panel,
    changes_panel,
    chat_list_panel,
    chat_mode_menu,
    chat_store,
    commands,    context_panel,
    command_registry,
    conversation,
    deep_mode,
    diff_stats,
    header_bar,
    layout_profiles,
    mcp_client,
    mcp_panel,
    mcp_watch,
    cloud_agents,
    effort,
    layout,
    memory_bridge,
    modes,
    modes_menu,
    model_selector,
    nav_sidebar,
    permissions,
    planner,
    power,
    project_gate,
    providers,
    pulse,
    rag,
    rag_panel,
    safe,
    server_state,
    session_header,
    task_plan,
    tools_panel,
    queue_engine,
    trace_store,
    voice,
    queue_panel,
    shell_session,
    skills as skills_module,
    skills_panel,
    task_center,
    task_executor,
    task_planner,
    theme,
    welcome,
    widgets,
    workspace as ws,
    workspace_menu,
)
from .agent import AgentRunner
from .agent_tools import ToolRegistry
from . import agent_tools
from .app_control import AppController
from .chat_panel import ChatPanel
from .config import APP_NAME, APP_VERSION, Settings, load_session, save_session
from . import model_hub as hub
from . import hardware
from . import runtime
from .editor import CodeEditor
from .file_tree import FileTree
from .first_run import FirstRunWizard
from .model_hub_panel import ModelHubPanel
from . import neuromesh_panel, runtime_panel
from .native import api as native_api
from .native import bridge as native_bridge
from .outline_panel import OutlinePanel
from .palette import Palette, ProjectSearch, SearchDialog
from .preview_panel import PreviewPanel
from .live_preview import LivePreviewPanel
from .settings_dialog import SettingsDialog
from .tabs import EditorTabs
from .terminal import TerminalPanel

WELCOME_TEXT = """# BlackChpok IDE
Локальна IDE з агентом у стилі сучасного агентного редактора.

## З чого почати

1. Відкрий теку проєкту: **Файл → Відкрити папку**.
2. Підключи модель: **Вигляд → Хаб моделей** (`Ctrl+Shift+M`). IDE визначить
   залізо, підбере модель, поставить рушій llama.cpp і підключить усе сама.
   Можна вказати й будь-який OpenAI-сумісний сервер (LM Studio, Ollama).
3. Напиши задачу в чаті праворуч. Агент сам прочитає файли, внесе зміни й
   запустить перевірки.

## Що є в оболонці

- **Черга завдань** — складай задачі списком, агент виконує їх одну за одною.
- **Скіли** — тека `.agents/skills/<назва>/SKILL.md` з інструкцією для агента.
- **MCP-сервери** — інструменти із зовнішніх процесів (`.mcp.json` у проєкті).
- **Вбудований термінал** — жива сесія cmd.exe: `cd`, змінні й venv зберігаються.

## Гарячі клавіші

| Клавіші | Дія |
| --- | --- |
| `Ctrl+P` | швидке відкриття файлу |
| `Ctrl+Shift+P` | палітра команд |
| `Ctrl+Shift+M` | хаб моделей |
| `Ctrl+F` / `Ctrl+Shift+F` | пошук у файлі / у проєкті |
| `Ctrl+S` / `Ctrl+W` | зберегти / закрити вкладку |
| `Ctrl+B` / `Ctrl+Alt+B` / `Ctrl+`` ` | провідник / агент / термінал |
| `Ctrl+Alt+K` / `Ctrl+Alt+J` | скіли / черга завдань |
| `F5` / `Ctrl+F5` | запустити файл / тести |
"""

LOG = logging.getLogger("blackchpok.ui")

#: Префікс повідомлення про збій ВЛАСНОГО рушія.
#:
#: Потрібен, щоб відрізнити помилку від успіху: ``_autostart_native_model``
#: повертає РЯДОК в обох випадках (успіх — «власний рушій: назва · ctx…»),
#: і без окремого маркера текст помилки виглядав як успішний результат —
#: фолбек на llama-server не запускався взагалі.
NATIVE_FAILURE_PREFIX = "✗ власний рушій: "


class _Point:
    """Мінімальна «подія» з координатами для ``context_menu``.

    ``widgets.context_menu`` читає лише ``x_root``/``y_root``. Передавати
    справжню подію тут не можна (меню відкриває кнопка, а не мишка), тому
    використовуємо цей простий носій координат.
    """

    __slots__ = ("x_root", "y_root")

    def __init__(self, x: int, y: int) -> None:
        self.x_root = int(x)
        self.y_root = int(y)

#: Куди веде кожен розділ навігації: ключ розділу → панель бічної колонки.
#: ``None`` означає «це окрема дія, а не панель» (налаштування).
#:
#: «Чати» й «Агенти» — один розділ: кожна розмова і є сесія агента, тож
#: окремі пункти меню лише змушували перемикатись між двома списками того
#: самого. Тепер це ``chats`` (єдина панель сесій).
SECTION_PANELS: dict[str, str] = {
    "chats": "chats",
    "mcp": "mcp",
    "projects": "explorer",
    "knowledge": "rag",
    "runtime": "runtime",
    "neuromesh": "neuromesh",
}

#: Панель → розділ навігації, до якого вона належить (для підсвітки).
#: «Автономний», черга й скіли належать чату: вони прив'язані до сесії й
#: проєкту, а не до всього застосунку (див. ``chat_mode_menu``).
PANEL_SECTIONS: dict[str, str] = {
    "chats": "chats",
    "cases": "chats",          # «Справи» — це живі кроки тієї ж сесії
    "autonomous": "chats",
    "queue": "chats",
    "skills": "chats",
    "mcp": "mcp",
    "tools": "mcp",
    "explorer": "projects",
    "search": "projects",
    "changes": "projects",
    "outline": "projects",
    "rag": "knowledge",
    "runtime": "runtime",
    "neuromesh": "neuromesh",
}

#: Заголовки панелей бічної колонки (щоб користувач бачив, де він).
PANEL_TITLES: dict[str, str] = {
    "chats": "Чати й агенти",
    "cases": "Кроки агента",
    "autonomous": "Автономний режим",
    "queue": "Черга завдань",
    "skills": "Скіли агента",
    "mcp": "MCP-сервери",
    "tools": "Інструменти",
    "explorer": "Файли проєкту",
    "changes": "Зміни у файлах",
    "outline": "Структура файлу",
    "rag": "База знань",
    "runtime": "AI Runtime",
    "neuromesh": "NEUROMESH Пам'ять",
}


def _plan_text_for(task) -> str:
    """Короткий опис задачі людською мовою для плану автономного режиму."""
    who = "твоя задача" if getattr(task, "from_user", False) else "покращення"
    text = " ".join(str(getattr(task, "text", "") or "").split())
    if len(text) > 110:
        text = text[:109] + "…"
    return f"{who}: {text}"


def task_planner_available(settings: Settings) -> bool:
    """Чи є налаштована модель, якій можна доручити планування.

    Перевіряємо лише заповненість налаштувань, без мережі: сам запит до
    моделі однаково покаже помилку, якщо сервер не піднятий. Ця перевірка
    потрібна, щоб не ставити в чергу «крок» без моделі й не вдавати, що
    план існує.
    """
    try:
        return bool(str(getattr(settings.llm, "model", "") or "").strip())
    except AttributeError:
        return False


class BlackChpokIDE(tk.Tk):
    """Вікно застосунку: збирає всі панелі разом."""

    #: Скільки секунд крок може лишатися «активним» без роботи агента,
    #: перш ніж вважати його завислим і повернути в чергу.
    #:
    #: Число не мале навмисно: між позначенням кроку й стартом потоку
    #: агента минає кілька тіків, і миттєва перевірка повертала крок у
    #: чергу прямо під час роботи.
    STALE_STEP_SECONDS = 25.0

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.session = load_session()
        self.title(f"{APP_NAME} {APP_VERSION}")
        # На весь екран за замовчуванням: агентна IDE має багато колонок,
        # і на маленькому вікні діалог стає вузькою смужкою. Розмір вікна
        # запам'ятовується між запусками, тож користувач може змінити його
        # мишкою, і наступний запуск відкриється так само.
        self.minsize(1020, 640)
        self._apply_start_geometry()
        self._apply_icon()

        self.theme = theme.Theme(self, settings.ui.font_family, settings.ui.font_size)
        # Тема з налаштувань (типово темна) діє одразу — до побудови віджетів,
        # тож жодного «світлого спалаху» при старті.
        theme.set_mode(getattr(settings.ui, "theme", theme.DEFAULT_MODE))
        self.theme.apply()

        root = Path(settings.workspace or Path.cwd())
        if not root.exists():
            root = Path.cwd()
        self.settings.workspace = str(root)
        self.registry = ToolRegistry(root, confirm_commands=settings.agent.confirm_commands)
        self.registry.command_guard = self._confirm_command
        # Збережений режим дозволів діє одразу після старту.
        self.permission_mode = permissions.normalise_mode(settings.agent.permission_mode)
        self.current_goal = ""

        # Двигуни
        self.skill_book = skills_module.SkillBook(root)
        self.task_queue = queue_engine.TaskQueue()
        # ── виконавець плану: веде кроки черги реальними діями агента.
        # Створюється ДО розкладки, бо центр завдань у нижній панелі вже
        # показує кнопки, підключені до нього. Сам агент створюється
        # пізніше — виконавець кличе його лише під час роботи кроку.
        self.executor = task_executor.QueueExecutor(
            self.task_queue,
            validator=task_executor.TaskValidator(self._project_root),
            on_run_step=self._run_plan_step,
            # Колбеки йдуть із ПОТОКУ АГЕНТА, а чіпають віджети. Tkinter
            # цього не дозволяє: ``set_status`` і ``_update_queue_badge``
            # звертаються до статусбара, панелі черги, центру завдань і
            # панелі контексту. Тому маршалізуємо в головний потік — так
            # само, як це вже зроблено для ``mcp_watcher`` нижче.
            on_status=lambda text: self._ui_call(self.set_status, text),
            on_change=lambda: self._ui_call(self._update_queue_badge),
            chat_id_provider=self._active_chat_id,
        )
        #: Чи крок черги зараз виконує агент (щоб відрізняти звичайний чат).
        self._plan_step_active = False
        #: Останній план, який склала модель (щоб показати/перепланувати).
        self._last_plan: list[task_planner.PlanStep] = []
        self._planning = False
        self.mcp_manager = mcp_client.McpManager()
        # Наглядач MCP: періодично перевіряє, що сервери ЖИВІ, а не лише
        # «колись ініціалізувались». Без нього померлий або завислий сервер
        # лишався зі статусом «працює», і агент отримував помилки на кожному
        # виклику. Успішні сервери наглядач не чіпає.
        self.mcp_watcher = mcp_watch.Watcher(
            self.mcp_manager,
            on_status=lambda text: self._ui_call(self.set_status, text))
        self.chat_store = chat_store.ChatStore()
        self.case_book = cases_panel.CaseBook()
        # RAG: наявний рушій rag_engine.py, підключений до IDE.
        self.rag_service = rag.RagService(root)
        # ── BLACKCHPOK NATIVE RUNTIME + NEUROMESH ────────────────────────
        # Рушій один на процес; він не потребує llama-server, LM Studio чи
        # Ollama. Пам'ять — окрема SQLite-база в теці даних застосунку.
        self.native_runtime = native_api.NativeRuntime()
        # МІСТ мусить бачити САМЕ ЦЕЙ екземпляр. Інакше ``bridge.runtime()``
        # створить другий рушій зі своєю моделлю — і у VRAM опиняться дві
        # копії (14B ≈ 9 ГБ кожна), тобто OOM замість роботи.
        native_bridge.set_runtime(self.native_runtime)
        self.memory = self._open_memory()
        if self.memory is not None:
            try:
                self.registry.attach_memory(self.memory)
            except Exception:                        # noqa: BLE001
                LOG.warning("Пам'ять не підключено до реєстру", exc_info=True)
        self.layout = layout.load()
        # Живе тестування: агент запускає/клікає/знімає скріншоти застосунку.
        self.app = AppController(self._project_root)
        self.registry.attach_app_controller(self.app)
        # Сторінка як дані: агент читає консоль, DOM і робить знімок САМОЇ
        # сторінки через CDP. Провайдер лінивий — на момент реєстрації
        # вбудованого браузера ще немає.
        self.registry.attach_cdp_provider(self._browser_cdp)
        # Дозвіл на DOM-міст ЗОВНІШНІХ сторінок береться з налаштувань.
        # Типово вимкнений: міст існує для власного Live Preview, а читання
        # чужого сайту — це доступ до особистих даних у полях форми.
        try:
            self.registry.allow_external_page_inspection = bool(
                getattr(self.settings.mcp, "allow_external_page_inspection", False))
        except AttributeError:
            self.registry.allow_external_page_inspection = False
        # Дескриптор вікна вбудованого браузера — для знімка САМЕ проєкту
        # (а не «першого-ліпшого Chrome» на машині користувача).
        self.registry.attach_browser_hwnd_provider(self._browser_hwnd)
        # Показ сторінки людині: агент може відкрити посилання в панелі
        # «Сайт» і показати, де саме він знайшов інформацію.
        self.registry.attach_page_opener(self.open_url_in_browser)

        self._active_side = "chats"
        self._mcp_busy = False
        self._queue_pump_after: Optional[str] = None
        self._ui_after: Optional[str] = None
        self._resize_after: Optional[str] = None
        self._ui_queue: "queue.Queue[tuple[object, tuple[object, ...]]]" = queue.Queue()
        self._running_task_id = ""
        self._setup_busy = False
        self._welcome_shown = False
        self._setup_note = ""
        #: Чи показана права колонка живого прев'ю застосунку.
        self._preview_shown = False
        #: Режим роботи агента (реальні дозволи + кроки, див. :mod:`modes`).
        self.agent_mode = modes.normalise(getattr(settings.ui, "mode", modes.DEFAULT_MODE))
        #: Спливні картки (селектор моделі, меню режимів).
        self._model_selector = None
        self._mode_menu = None
        self._probe = None
        self._probe_summary = ""
        self._probe_after: Optional[str] = None
        #: Результати перевірки провайдерів: ключ → ProbeOutcome.
        self._probe_state: dict[str, providers.ProbeOutcome] = {}
        #: True, поки панель навігації схована автоматично через вузьке вікно.
        self._sidebar_auto_hidden = False
        #: True, коли панель згорнута до рейки (лишаються самі іконки).
        self._sidebar_collapsed = False
        #: Екран «спершу вибери проєкт» (замість чату). ``None`` — не показано.
        self.project_gate: Optional[project_gate.ProjectGate] = None
        #: Вибір користувача щодо колонки контексту: None = автоматично.
        self._context_user_choice: Optional[bool] = None
        #: Останні обчислені адаптивні розміри діалогу (див. :mod:`adaptive`).
        self._chat_metrics = adaptive.metrics_for(
            screen=adaptive.screen_size(self),
            sidebar=self.settings.ui.sidebar_width,
        )
        self._chat_lines_limit = self._chat_metrics.body_lines
        #: Рушій автономного режиму. Створюється до розкладки: панель
        #: автономного режиму вже його показує. Черга — ТА САМА, що в
        #: панелі завдань: інакше задачі агента й задачі користувача жили б
        #: у двох списках і губились між ними.
        self.autonomous_engine = autonomous.AutonomousEngine(
            queue=self.task_queue,
            on_change=self._after_autonomous_change,
            on_status=self.set_status,
        )
        #: Зупинка агента й вивантаження моделі з відеокарти.
        self._managed_server = None
        self.model_keeper = power.ModelKeeper(
            server_provider=lambda: getattr(self, "_managed_server", None),
            start_provider=self._wake_model,
            on_status=self.set_status,
            # Власний рушій теж має віддавати VRAM на простої: інакше 10 ГБ
            # залишаються зайнятими, навіть коли користувач пішов.
            native_provider=lambda: getattr(self, "native_runtime", None),
            native_start_provider=self._wake_native_model,
        )
        self.model_keeper.tracker.policy.enabled = bool(
            getattr(self.settings.engine, "unload_when_idle", True))
        self.model_keeper.tracker.policy.idle_seconds = int(
            getattr(self.settings.engine, "idle_unload_seconds", 300) or 300)
        self.model_keeper.tracker.policy.normalise()
        # ── Єдине джерело правди про стан сервера ──────────────────────────
        # Раніше стан збирали чотири різні місця з різними таймаутами, і
        # вони суперечили одне одному: «online» при мертвому сервері,
        # 32768 у налаштуваннях проти 16384 у сервера. Тепер усі питають
        # ОДИН кеш, а мережа ходить лише у фоновому потоці.
        self.server_state = server_state.ServerStateCache(
            settings_provider=lambda: self.settings,
            server_provider=lambda: getattr(self, "_managed_server", None),
            on_update=self._on_server_state,
        )
        #: Тека, для якої ввімкнено автономний режим (None — вимкнено).
        self.project: Optional[Path] = None
        self._idle_after: Optional[str] = None
        self._autonomous_after: Optional[str] = None
        #: True, поки чекаємо, щоб агент дописав файл перед вимкненням режиму.
        self._autonomous_stop_pending = False

        self._build_layout()
        self._build_menu()
        self._build_status()

        self.agent = AgentRunner(self.registry, settings.llm, settings.agent, root)
        self.agent.skill_book = self.skill_book
        self.agent.mcp_manager = self.mcp_manager
        self.agent.on_finished = self._on_agent_finished
        self.agent.settings_ref = self.settings
        # «Що в цьому файлі» — роутер не бачить вікна, тож активний файл
        # редактора підставляє агент через цей провайдер.
        self.agent.active_path_provider = self._current_editor_path
        # ── Постійні побажання й вимірювання якості ────────────────────────
        # Побажання живуть у налаштуваннях (людина бачить і керує ними),
        # traces — у робочій теці програми: вони потрібні для порівняння
        # конфігурацій, а не для щоденної роботи.
        self._attach_profile(self.agent)
        self._attach_traces(self.agent)
        # Пам'ять NEUROMESH бере участь у розумінні запиту: факти й
        # обмеження проєкту потрапляють у контекст ДО запиту до моделі.
        self._attach_memory_bridge(self.agent)
        self.chat.attach_runner(self.agent)
        self.chat._workspace_root = root
        # Адаптивний ліміт рядків однієї відповіді: на малому екрані
        # відповідь не має забирати всю стрічку, на великому — обрізатись.
        try:
            self.chat.set_max_lines(self._chat_lines_limit)
        except (tk.TclError, AttributeError):
            LOG.debug("Не вдалось задати адаптивний ліміт рядків", exc_info=True)

        self._wire_shortcuts()
        # Увесь застосунок відкриває сторінки ЛИШЕ у вбудованому браузері.
        # Без цього панель змін кликала webbrowser.open і викидала
        # користувача в Chrome на сторінку завантаження git.
        browser_panel.set_url_opener(self.open_url_in_browser)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # ── Аварійний вихід: звільнити відеокарту навіть при збої ──────────
        # Штатний шлях — ``on_close``. Але якщо програма впаде, її вб'ють
        # через диспетчер задач або закриється вікно консолі, ``on_close``
        # не виконається, і ``llama-server`` лишиться живим із 8–11 ГБ VRAM.
        # Тоді користувач не може запустити гру, поки вручну не знайде
        # процес. ``atexit`` виконується при звичайному завершенні процесу
        # Python і при ``sys.exit``.
        atexit.register(self._release_model_now)
        self._drain_ui()
        self.after(150, self._startup)
        self.after(700, lambda: self.probe_providers(silent=True))

    # ── іконка ─────────────────────────────────────────────────────────────
    def _cleanup_orphans_quietly(self) -> None:
        """Прибрати «сирітські» рушії у фоні (не заважаючи старту)."""
        try:
            removed = runtime.cleanup_stale_processes()
        except Exception:  # noqa: BLE001 - старт не має падати
            LOG.debug("Прибирання сиріт не вдалось", exc_info=True)
            return
        if removed:
            LOG.info("На старті прибрано залишкових рушіїв: %s", removed)
            try:
                self._ui_call(self.set_status,
                              f"Звільнено відеопам'ять: зупинено "
                              f"залишкових рушіїв — {removed}")
            except Exception:  # noqa: BLE001
                pass

    def _apply_start_geometry(self) -> None:
        """Відкрити вікно на весь екран (або збереженим розміром).

        Чому на весь екран: в IDE чотири колонки — навігація, діалог,
        редактор і контекст. У вікні 1560×940 діалог лишався вузькою
        смужкою, а форма вводу зникала за межами екрана. Користувач просив:
        «розширити вікна на повному екрані».

        Якщо користувач змінив розмір мишкою, ``_remember_layout`` зберіг
        його — тоді відкриваємо саме той розмір, а не нав'язуємо свій.
        """
        saved = None
        try:
            saved = self.layout.get("window_size", "") if hasattr(self, "layout") else None
        except Exception:  # noqa: BLE001
            saved = None
        if saved and isinstance(saved, str) and "x" in saved:
            try:
                self.geometry(saved)
                return
            except tk.TclError:
                pass
        # Типово — максимальний робочий простір екрана (без панелі задач).
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            self.geometry(f"{max(1020, screen_w)}x{max(640, screen_h - 80)}+0+0")
        except tk.TclError:
            self.geometry("1560x940")
        # Розгорнути на весь екран після побудови — щоб Tk не скинув
        # розмір, коли віджети почнуть просити місце.
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        # Після розгортання саші ТРЕБА перерахувати: вони були розставлені
        # під початковий розмір, і при 3440 px діалог лишався вузькою
        # смужкою зліва, а решта вікна — порожньою.
        for delay in (60, 240, 600):
            self._sash_after(delay)

    def _apply_icon(self) -> None:
        from .config import resource_dir

        icon = resource_dir() / "assets" / "icon.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass

    # ── меню ───────────────────────────────────────────────────────────────
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Новий файл", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Відкрити файл…", accelerator="Ctrl+O", command=self.open_file_dialog)
        file_menu.add_command(label="Відкрити папку…", command=self.open_folder_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Зберегти", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Зберегти як…", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_command(label="Зберегти все", command=lambda: self.tabs.save_all())
        file_menu.add_separator()
        file_menu.add_command(label="Закрити вкладку", accelerator="Ctrl+W", command=self.close_tab)
        file_menu.add_command(label="Відкрити закриту вкладку", accelerator="Ctrl+Shift+T",
                              command=self.reopen_tab)
        file_menu.add_command(label="Закрити всі вкладки", command=self.close_all_tabs)
        file_menu.add_command(label="Стартовий екран", command=self.show_welcome)
        file_menu.add_separator()
        file_menu.add_command(label="Вихід", accelerator="Alt+F4", command=self.on_close)
        menubar.add_cascade(label="Файл", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Скасувати", accelerator="Ctrl+Z", command=lambda: self._editor_event("<Control-z>"))
        edit_menu.add_command(label="Повторити", accelerator="Ctrl+Y", command=lambda: self._editor_event("<Control-y>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Вирізати", accelerator="Ctrl+X", command=lambda: self._editor_event("<<Cut>>"))
        edit_menu.add_command(label="Копіювати", accelerator="Ctrl+C", command=lambda: self._editor_event("<<Copy>>"))
        edit_menu.add_command(label="Вставити", accelerator="Ctrl+V", command=lambda: self._editor_event("<<Paste>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Знайти в файлі…", accelerator="Ctrl+F", command=self.open_search)
        edit_menu.add_command(label="Пошук у проєкті…", accelerator="Ctrl+Shift+F", command=self.open_project_search)
        edit_menu.add_command(label="Перейти до рядка…", accelerator="Ctrl+G",
                              command=lambda: self.tabs.current() and self.tabs.current().focus_goto())
        edit_menu.add_separator()
        edit_menu.add_command(label="Командна палітра…", accelerator="Ctrl+Shift+P", command=self.command_palette)
        edit_menu.add_command(label="Швидке відкриття…", accelerator="Ctrl+P", command=self.quick_open)
        edit_menu.add_separator()
        edit_menu.add_command(label="Показати AST-дерево", accelerator="Ctrl+Shift+A",
                              command=self.show_ast_tree)
        edit_menu.add_command(label="Звіт про символи", command=self.show_symbols_report)
        edit_menu.add_command(label="Формат: коментар", accelerator="Ctrl+/",
                              command=lambda: self.tabs.current() and self.tabs.current()._toggle_comment())
        menubar.add_cascade(label="Правка", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Тільки чат", accelerator="Ctrl+Alt+F",
                              command=self.toggle_focus_mode)
        view_menu.add_separator()
        view_menu.add_command(label="Бічна панель", accelerator="Ctrl+B", command=self.toggle_sidebar)
        view_menu.add_command(label="Панель агента", accelerator="Ctrl+Alt+B", command=self.toggle_chat)
        view_menu.add_command(label="Колонка контексту", command=self.toggle_context)
        view_menu.add_command(label="Live Preview", accelerator="Ctrl+Alt+V", command=self.toggle_preview)
        view_menu.add_command(label="Термінал", accelerator="Ctrl+`", command=self.toggle_bottom)
        view_menu.add_command(label="Сайт у браузері", accelerator="Ctrl+Alt+P",
                              command=self.open_site)
        view_menu.add_separator()
        view_menu.add_command(label="Запустити застосунок", command=self.start_site)
        view_menu.add_command(label="Зупинити застосунок", command=self.stop_site)
        view_menu.add_command(label="Оновити сторінку", command=self.reload_site)
        view_menu.add_command(label="Відкрити адресу у вбудованому браузері…",
                              accelerator="Ctrl+Alt+L", command=self.open_url_dialog)
        view_menu.add_separator()
        # Радіо-пункти: галочка показує поточну тему без ручного перерахунку.
        self._theme_var = tk.StringVar(value=theme.current_mode())
        theme_menu = tk.Menu(view_menu, tearoff=0)
        theme_menu.add_radiobutton(
            label="Темна", variable=self._theme_var, value="dark",
            command=lambda: self.apply_theme_mode("dark"))
        theme_menu.add_radiobutton(
            label="Світла (cream)", variable=self._theme_var, value="light",
            command=lambda: self.apply_theme_mode("light"))
        theme_menu.add_separator()
        theme_menu.add_command(label="Зберегти поточну тему", command=self._save_theme)
        view_menu.add_cascade(label="Тема", menu=theme_menu)
        self._theme_menu = theme_menu
        view_menu.add_separator()
        view_menu.add_command(label="Скіли агента", accelerator="Ctrl+Alt+K", command=lambda: self.show_side("skills"))
        view_menu.add_command(label="Кроки агента", accelerator="Ctrl+Alt+D", command=lambda: self.show_side("cases"))
        view_menu.add_command(label="Автономний режим", accelerator="Ctrl+Alt+A",
                              command=self.show_autonomous)
        view_menu.add_command(label="Знання про проєкт (RAG)", accelerator="Ctrl+Alt+I",
                              command=lambda: self.show_side("rag"))
        view_menu.add_command(label="Інструменти агента", accelerator="Ctrl+Alt+T",
                              command=lambda: self.show_side("tools"))
        view_menu.add_command(label="Черга завдань", accelerator="Ctrl+Alt+J", command=lambda: self.show_side("queue"))
        view_menu.add_command(label="MCP-сервери", command=lambda: self.show_side("mcp"))
        view_menu.add_separator()
        view_menu.add_command(label="Хаб моделей…", accelerator="Ctrl+Shift+M", command=self.open_model_hub)
        view_menu.add_command(label="Майстер налаштування (бібліотеки, програми, модель)…",
                              command=self.open_first_run)
        view_menu.add_separator()
        view_menu.add_separator()
        view_menu.add_command(label="Скинути розкладку", command=self.reset_layout)
        view_menu.add_command(label="Зберегти розкладку", command=self._remember_layout)
        view_menu.add_command(label="Збільшити шрифт", accelerator="Ctrl+=", command=lambda: self.zoom(1))
        view_menu.add_command(label="Зменшити шрифт", accelerator="Ctrl+-", command=lambda: self.zoom(-1))
        view_menu.add_separator()
        view_menu.add_command(label="Налаштування…", accelerator="Ctrl+,", command=self.open_settings)
        view_menu.add_command(label="Показати журнал", command=self.show_log)
        menubar.add_cascade(label="Вигляд", menu=view_menu)

        agent_menu = tk.Menu(menubar, tearoff=0)
        agent_menu.add_command(label="Надіслати поточний файл агенту", accelerator="Ctrl+Alt+Enter",
                               command=self.send_file_to_agent)
        agent_menu.add_command(label="Пояснити виділене", command=self.explain_selection)
        agent_menu.add_command(label="Виправити виділене", command=self.fix_selection)
        agent_menu.add_separator()
        agent_menu.add_command(label="Додати задачу в чергу", accelerator="Ctrl+Alt+Q", command=self.add_queue_dialog)
        agent_menu.add_command(label="Запустити наступну задачу", command=self.run_next_task)
        agent_menu.add_command(label="Зупинити агента", command=self.stop_agent)
        agent_menu.add_separator()
        # ── план роботи: центр завдань і керування ним
        agent_menu.add_command(label="Центр завдань", accelerator="Ctrl+Alt+W",
                               command=lambda: self.show_bottom("tasks"))
        agent_menu.add_command(label="Призупинити план", command=self.pause_queue)
        agent_menu.add_command(label="Продовжити план", command=self.resume_queue)
        agent_menu.add_command(label="Зупинити виконання плану", command=self.stop_plan)
        agent_menu.add_command(label="Перепланувати залишок роботи", command=self.replan_now)
        agent_menu.add_command(label="Підсумковий звіт", command=self.finish_plan_report)
        agent_menu.add_separator()
        agent_menu.add_command(label="Автономний режим: старт / стоп",
                               accelerator="Ctrl+Alt+A", command=self.toggle_autonomous)
        agent_menu.add_command(label="Автономний режим: панель", command=self.show_autonomous)
        agent_menu.add_command(label="Вивантажити модель із відеокарти",
                               command=self.unload_model_now)
        agent_menu.add_separator()
        agent_menu.add_command(label="Новий чат", command=self.new_chat)
        agent_menu.add_command(label="Перевірити модель", command=lambda: self.probe_providers())
        agent_menu.add_command(label="Перепідключити MCP", command=self.reload_mcp)
        agent_menu.add_separator()
        # Реальні цифри про те, як агент працює: їх можна показати й
        # порівняти між конфігураціями, на відміну від «стало краще».
        agent_menu.add_command(label="Якість агента (метрики)", command=self.show_agent_quality)
        menubar.add_cascade(label="Агент", menu=agent_menu)

        git_menu = tk.Menu(menubar, tearoff=0)
        git_menu.add_command(label="Статус", command=lambda: self.terminal.run("git status --short --branch"))
        git_menu.add_command(label="Diff", command=lambda: self.terminal.run("git diff"))
        git_menu.add_command(label="Історія", command=lambda: self.terminal.run("git log --oneline -15"))
        git_menu.add_command(label="Додати все", command=lambda: self.terminal.run("git add -A"))
        menubar.add_cascade(label="Git", menu=git_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Гарячі клавіші", command=self.show_shortcuts)
        help_menu.add_command(label="Про програму", command=self.show_about)
        menubar.add_cascade(label="Довідка", menu=help_menu)

        self.configure(menu=menubar)

    # ── розкладка ──────────────────────────────────────────────────────────
    def _build_layout(self) -> None:
        """Зібрати оболонку: навігація | заголовок сесії + робоча область.

        Композиція навмисно повторює організацію робочого простору сучасної
        агентної оболонки: вузька навігація зліва, центральна колонка діалогу
        комфортної ширини, робоча область (редактор) праворуч, контекст —
        окремою колонкою за бажанням.

            ┌──────┬──────────────────────────────────────────────┐
            │ нав. │  заголовок сесії                             │
            │      ├──────────────────────────────────────────────┤
            │ панель│  діалог (центр)  │  робоча область  │ контекст│
            │      │  ───────────────  │                  │         │
            │      │  композер         │                  │         │
            └──────┴──────────────────────────────────────────────┘
        """
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        outer = tk.Frame(self, bg=theme.BG, bd=0, highlightthickness=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)
        self.outer = outer

        # ── нова верхня шапка: швидкий доступ до всього, що робить людина.
        # Вона йде ПЕРШОЮ, над панелями, і тримає власну висоту: це головна
        # панель керування, а не ще один рядок у робочій області.
        self._build_header(outer)

        # Ліва панель живе у власному PanedWindow: так її межу можна тягнути
        # мишею. Раніше вона була звичайним Frame із фіксованою шириною —
        # змінити її можна було лише в налаштуваннях, чого ніхто не робить.
        from tkinter import ttk

        self.side_split = ttk.PanedWindow(outer, orient="horizontal")
        self.side_split.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self._build_sidebar(self.side_split)
        self._build_centre(self.side_split)

        # Саші ставимо кілька разів: панелі додаються вже після першої
        # розкладки, і одного after_idle не вистачає.
        self._sash_after(0)
        self._sash_after(120)
        self._sash_after(420)
        # Вікно можуть розтягнути або звузити — тоді саші треба перерахувати.
        self.bind("<Configure>", self._on_root_configure, add="+")
        # Користувач рухає межі — запам'ятовуємо це.
        # Важливо: після руху мишею саші НЕ перераховуються, інакше
        # ``_apply_sash_positions`` повертала б їх на місце й панель
        # «не розширювалась» — саме на це скаржився користувач.
        self._user_dragging = False
        for widget in ("h_split", "v_split", "editor_split", "side_split"):
            split = getattr(self, widget, None)
            if split is None:
                continue
            split.bind("<ButtonPress-1>", self._on_sash_press, add="+")
            split.bind("<ButtonRelease-1>", self._on_sash_release, add="+")

        # Тепер, коли всі панелі створені, можна безпечно зареєструвати
        # команди: кожна з них посилається на реальні віджети.
        self._register_commands()
        self._refresh_header()

    def _on_sash_press(self, _event=None) -> None:
        """Почався рух межі: перерахунки розкладки на паузі."""
        self._user_dragging = True
        job = getattr(self, "_resize_after", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._resize_after = None

    # ── нова шапка та реєстр команд ────────────────────────────────────────
    def _build_header(self, outer: tk.Misc) -> None:
        """Зібрати верхню панель швидкого доступу.

        Шапка — це не «красива смужка»: кожна її кнопка виконує ту саму
        команду, що й пункт меню, бо всі вони зареєстровані в
        :mod:`commands`. Завдяки цьому немає двох списків, які можуть
        розійтись.
        """
        self.header_bar = header_bar.HeaderBar(
            outer,
            self.theme,
            on_command=self.run_command,
            on_menu=self._header_menu,
            on_palette=self.command_palette,
            on_project_menu=lambda anchor: self._show_project_menu(anchor),
            on_model_menu=lambda anchor: self.show_model_selector(anchor=anchor),
            on_agent_menu=lambda anchor: self.show_mode_menu(anchor=anchor),
            on_git_menu=lambda anchor: self._show_git_menu(anchor),
            on_more_menu=lambda anchor: self._show_more_menu(anchor),
            # Клік по великому статусу моделі відкриває самодіагностику:
            # користувач бачить не лише «офлайн», а й причину.
            on_status_click=self._on_model_status_click,
        )
        self.header_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        # Рядок шапки мусить мати ВЛАСНУ висоту: без цього grid стискав
        # шапку до вмісту (34 px), і збільшені іконки обрізались зверху й
        # знизу. ``minsize`` тримає висоту, навіть коли діти нижчі.
        try:
            outer.rowconfigure(0, minsize=header_bar.HEADER_HEIGHT)
        except tk.TclError:
            pass
        # Реєстрацію команд відкладено до кінця ``_build_layout``: частина
        # команд посилається на віджети (термінал, вкладки, чат), яких на
        # момент створення шапки ще немає.

    def _register_commands(self) -> None:
        """Наповнити реєстр команд (ідемпотентно).

        Сама таблиця живе в :mod:`command_registry` — тут лишається
        лише делегування, щоб решта коду кликала як раніше.
        """
        command_registry.register_all(self)
    def run_command(self, key: str) -> bool:
        """Виконати команду з реєстру (шапка, палітра, меню — усе через неї)."""
        command = commands.get(key)
        if command is None:
            LOG.debug("Невідома команда: %s", key)
            return False
        ok = command.run()
        if not ok and command.enabled is not None:
            self.set_status(f"«{command.label}» зараз недоступна.")
        self._refresh_header()
        return ok

    def _refresh_header(self) -> None:
        """Показати в шапці реальний стан (не вигаданий)."""
        bar = getattr(self, "header_bar", None)
        if bar is None:
            return
        name = Path(self.settings.workspace).name if self.has_project() else ""
        bar.set_project(name, workspace=str(self.settings.workspace or ""))
        try:
            mode = modes.get(getattr(self, "agent_mode", modes.DEFAULT_MODE))
            bar.set_agent(mode.label, busy=bool(getattr(self.chat, "_busy", False)))
        except Exception:  # noqa: BLE001 - шапка не має ламати старт
            LOG.debug("Режим агента недоступний", exc_info=True)
        entry = providers.current_entry(self.settings)
        bar.set_model(entry.name, local=entry.is_local, online=entry.online)
        # Git-чип раніше читав ``_git_branch``/``_git_changes``, які
        # НІКОЛИ не присвоювались — тобто завжди показував «⑂ —».
        # Тепер беремо справжні дані (з кешем: _refresh_header частий).
        branch, changes = self._git_badge_state()
        bar.set_git(branch, changes)
        for key in ("file.save", "edit.undo", "edit.redo", "agent.stop"):
            command = commands.get(key)
            if command is not None:
                bar.set_command_enabled(key, command.is_enabled())

    def _git_badge_state(self) -> tuple[str, int]:
        """Гілка й кількість змін для шапки (кеш 15 с, щоб не смикати git).

        ``git`` — зовнішній процес; викликати його на кожне оновлення шапки
        означало б десятки запусків на секунду. Тому кешуємо, а git-команда
        йде лише коли тека справді є репозиторієм.
        """
        root = self._project_root()
        if root is None:
            return "", 0
        now = time.time()
        cached = getattr(self, "_git_badge_cache", None)
        if cached is not None and (now - cached[0]) < 15.0:
            return cached[1], cached[2]
        branch = ""
        changes = 0
        try:
            branch = diff_stats.git_branch(root)
            if branch:
                change_set = diff_stats.detect_changes(root, prefer_git=True)
                changes = len(getattr(change_set, "files", []) or [])
        except Exception:  # noqa: BLE001 - шапка не має ламати вікно
            LOG.debug("Стан git для шапки недоступний", exc_info=True)
        self._git_badge_cache = (now, branch, changes)
        return branch, changes

    def _header_menu(self, which: str, anchor=None) -> None:
        """Меню шапки: ``git`` і «⋯».

        Окремі пункти «Файл/Правка/Вигляд» тут не потрібні: у вікна вже є
        справжнє нативне меню (``_build_menu``), і дублювати його в шапці
        означало показувати той самий список двічі.
        """
        if which == "git":
            self._show_git_menu(anchor)
        elif which == "more":
            self._show_more_menu(anchor)

    def _menu_items_for(self, group: str) -> list[tuple[str, Optional[object]]]:
        """Пункти меню групи: ``(підпис, дія|None)``; ``None`` — розділювач."""
        rows: list[tuple[str, Optional[object]]] = []
        for command in commands.all_commands():
            if command.group != group or command.level == commands.PRIMARY:
                continue
            if command.level not in (commands.MENU, commands.PALETTE):
                continue
            label = command.label
            if command.shortcut:
                label = f"{label}\t{command.shortcut}"
            if not command.is_enabled():
                # Недоступні пункти лишаємо видимими, але без дії.
                rows.append((label, None))
            else:
                rows.append((label, command.run))
        return rows

    def _popup(self, anchor, rows: list[tuple[str, Optional[object]]]) -> None:
        """Показати випадаюче меню біля кнопки шапки."""
        if not rows:
            return
        try:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height()
        except tk.TclError:
            return
        try:
            widgets.context_menu(self, rows, _Point(x, y))
        except tk.TclError:
            return

    def _show_git_menu(self, anchor=None) -> None:
        rows = self._menu_items_for("git")
        self._popup(anchor or self.header_bar.git_btn, rows)

    def _show_more_menu(self, anchor=None) -> None:
        """«⋯»: усе, що не потрапило на шапку — жодна команда не губиться."""
        rows: list[tuple[str, Optional[object]]] = []
        for category in commands.categories_present():
            items = [command for command in commands.all_commands()
                     if command.category == category
                     and command.level != commands.PRIMARY]
            if not items:
                continue
            if rows:
                rows.append(("", None))
            rows.append((f"— {category} —", None))
            for command in items:
                label = command.label
                if command.shortcut:
                    label = f"{label}\t{command.shortcut}"
                rows.append((label, command.run if command.is_enabled() else None))
        self._popup(anchor or self.header_bar.more_btn, rows)

    def _show_project_menu(self, anchor=None) -> None:
        rows: list[tuple[str, Optional[object]]] = [
            ("Відкрити папку…", self.open_folder_dialog),
            ("Створити проєкт…", self.create_project_folder),
        ]
        recent = [path for path in getattr(self.settings, "recent", []) if path]
        if recent:
            rows.append(("", None))
            rows.append(("— Останні —", None))
            for path in recent[:8]:
                label = f"{Path(path).name}  ·  {path}"
                rows.append((label, lambda p=path: self.open_recent_folder(p)))
        self._popup(anchor or self.header_bar.project_btn, rows)

    def _on_sash_release(self, _event=None) -> None:
        """Рух завершено: зберігаємо новий розмір і повертаємо розрахунки."""
        self._user_dragging = False
        self._remember_layout()

    #: Зворотна сумісність: раніше це була окрема рейка іконок.
    @property
    def rail(self) -> tk.Widget:
        """Рейка навігації — тепер це заголовок бічної панелі."""
        return getattr(self, "nav_head", self.sidebar)

    # 1. Бічна панель: навігація, проєкт, історія сесій, панелі розділів
    def _build_sidebar(self, outer: tk.Misc) -> None:
        self.sidebar = tk.Frame(outer, bg=theme.BG_ALT,
                                width=self.settings.ui.sidebar_width,
                                bd=0, highlightthickness=0)
        # Діти панелі пакуються, тому саме pack_propagate тримає ширину.
        self.sidebar.pack_propagate(False)
        try:
            self.side_split.add(self.sidebar, weight=0)
        except (AttributeError, tk.TclError):
            LOG.debug("Панель не додалась у PanedWindow", exc_info=True)
            self.sidebar.grid(row=0, column=0, sticky="ns")

        # ── бренд + згортання
        head = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        head.pack(fill="x", padx=theme.SPACE_LG, pady=(theme.SPACE_LG, theme.SPACE_MD))
        self.nav_head = head

        self.brand_icon = tk.Label(head, text="◤", bg=theme.BG_ALT, fg=theme.ACCENT,
                                   font=("Segoe UI", 13, "bold"))
        self.brand_icon.pack(side="left")
        self.brand_label = tk.Label(head, text="BlackChpok", bg=theme.BG_ALT,
                                    fg=theme.FG_BRIGHT, font=self.theme.ui_h2, anchor="w")
        self.brand_label.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.collapse_btn = widgets.IconButton(
            head, "«", self.toggle_sidebar, bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 9), tooltip="Згорнути панель (Ctrl+B)")
        self.collapse_btn.pack(side="right")

        # ── головна дія: новий чат (підпис українською)
        self.new_session_btn = tk.Label(
            self.sidebar, text="＋  Новий чат", bg=theme.BTN_BG, fg=theme.BTN_FG,
            font=("Segoe UI", 10, "bold"), padx=12, pady=8, cursor="hand2", anchor="w",
        )
        self.new_session_btn.pack(fill="x", padx=theme.SPACE_MD, pady=(0, theme.SPACE_MD))
        self.new_session_btn.bind("<Enter>", lambda _e: self.new_session_btn.configure(bg=theme.BTN_HOVER))
        self.new_session_btn.bind("<Leave>", lambda _e: self.new_session_btn.configure(bg=theme.BTN_BG))
        self.new_session_btn.bind("<Button-1>", lambda _e: self.new_chat_session())
        widgets.Tip(self.new_session_btn, "Створити нового агента (Ctrl+Alt+N)")

        # ── меню розділів ПРИБРАНО: ліворуч лишились самі чати.
        # Раніше тут стояли «Чати й агенти», «MCP Tools», «Проєкти», «База
        # знань», «Налаштування» — п'ять пунктів, які займали місце в
        # колонці, призначеній для розмов. Тепер усе це в меню «Вигляд» і
        # в діалозі налаштувань, а ліва панель показує лише чати.
        self.nav_host = None
        self._nav_buttons: dict[str, nav_sidebar.NavButton] = {}

        # ── швидкий доступ: те, що потрібно щохвилини.
        # Це НЕ меню розділів (його свідомо прибрано): чотири цілі —
        # чати, центр завдань, файли проєкту й налаштування. Кожна веде на
        # реальну панель, тож користувачу не треба шукати їх у меню.
        nav_row = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        nav_row.pack(fill="x", padx=theme.SPACE_MD, pady=(0, theme.SPACE_SM))
        self.quick_nav: dict[str, widgets.HoverLabel] = {}
        for key, caption, command, tip in (
            ("chats", "◍ Чати", lambda: self.show_side("chats"),
             "Історія розмов і живі сесії агента"),
            ("tasks", "≡ Завдання", lambda: self.show_bottom("tasks"),
             "Черга кроків локального агента (Ctrl+Alt+W)"),
            ("explorer", "▤ Файли", lambda: self.show_side("explorer"),
             "Файли й папки проєкту"),
            ("settings", "⚙", self.open_settings,
             "Налаштування (Ctrl+,)"),
        ):
            chip = widgets.HoverLabel(
                nav_row, text=caption, command=command, bg=theme.BG_ALT,
                fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
                hover_fg=theme.FG_BRIGHT, active_bg=theme.BG_ACTIVE,
                active_fg=theme.FG_BRIGHT, font=("Segoe UI", 8),
                padx=theme.SPACE_SM, pady=2, anchor="center")
            chip.pack(side="left", padx=(0, 2))
            widgets.Tip(chip, tip)
            self.quick_nav[key] = chip

        widgets.Divider(self.sidebar, colour=theme.BORDER, padx=theme.SPACE_MD)

        # ── смуга «назад» для панелей, відкритих із налаштувань.
        # Сам заголовок («ЧАТИ Й АГЕНТИ») не малюємо: коли ліворуч лишились
        # тільки чати, він дублював вкладку списку тим самим словом.
        panel_head = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        panel_head.pack(fill="x", padx=theme.SPACE_LG, pady=(theme.SPACE_MD, 2))

        self.panel_home = widgets.HoverLabel(
            panel_head, text="", command=self._panel_home, bg=theme.BG_ALT,
            fg=theme.FG_DIM, hover_bg=theme.BG_ALT, hover_fg=theme.FG_BRIGHT,
            font=("Segoe UI", 10), padx=0, pady=0, anchor="w")
        self.panel_home.pack(side="left", padx=(0, theme.SPACE_SM))

        self.panel_title = tk.Label(panel_head, text="", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=self.theme.ui_tiny, anchor="w")
        self.panel_title.pack(side="left")

        # ── стек панелей розділів: історія сесій, файли, RAG, MCP…
        # Це і є «історія сесій і робочі проєкти» з макета: для розділу
        # «Чати» тут живе живий список розмов зі сховища.
        self.side_stack = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        self.side_stack.pack(fill="both", expand=True)

        self.chat_list = chat_list_panel.ChatListPanel(
            self.side_stack, self.theme, store=self.chat_store,
            on_open=self.open_chat, on_new=self.new_chat_session,
            on_status=self.set_status,
            on_close_chat=self.close_chat,
            on_cleared=self._after_chats_cleared,
        )

        self.cases_panel = cases_panel.CasesPanel(
            self.side_stack, self.theme, self.case_book,
            on_status=self.set_status,
            on_focus_chat=lambda: self.show_chat(True),
        )

        self.autonomous_panel = autonomous_panel.AutonomousPanel(
            self.side_stack, self.theme, self.autonomous_engine,
            on_start=self.start_autonomous,
            on_stop=self.stop_autonomous,
            on_add_task=self.add_autonomous_task,
            on_pick_project=self.pick_autonomous_project,
            on_status=self.set_status,
            on_open_file=self._open_relative,
        )

        self.rag_panel = rag_panel.RagPanel(
            self.side_stack, self.theme, self.rag_service,
            on_open_path=lambda path, line: self.open_path(Path(path), line),
            on_insert_context=self._insert_rag_context,
            on_status=self.set_status,
        )

        self.tools_panel = tools_panel.ToolsPanel(
            self.side_stack, self.theme, self.registry,
            mcp_manager=self.mcp_manager,
            on_status=self.set_status,
            on_result=self._on_tool_result,
        )

        self.file_tree = FileTree(self.side_stack, self.open_path,
                                  root_dir=(Path(self.settings.workspace)
                                            if self.has_project() else None))
        self.file_tree.on_status = self.set_status
        self.file_tree.on_terminal = lambda folder: (self.terminal.set_cwd(folder),
                                                     self.show_bottom("terminal"))

        self.outline = OutlinePanel(self.side_stack, self.theme, on_goto=self._goto_line)
        self.skills_panel = skills_panel.SkillsPanel(
            self.side_stack, self.theme, self.skill_book,
            on_status=self.set_status,
            on_use=self._use_skill,
            on_queue=self._queue_skill,
            on_open_file=lambda path: self.open_path(Path(path)),
        )
        self.queue_panel = queue_panel.QueuePanel(
            self.side_stack, self.theme, self.task_queue,
            on_run_next=self.run_next_task,
            on_status=self.set_status,
            on_show_task=self._show_queue_task,
            on_changed=self._update_queue_badge,
        )
        # Задачі черги прив'язуються до активного чату: коли чат видаляють,
        # його задачі зникають разом із ним, а не виконуються «в нікуди».
        self.queue_panel.chat_id_provider = lambda: str(
            getattr(self.chat_store, "active_id", "") or "")
        self.mcp_panel = mcp_panel.McpPanel(
            self.side_stack, self.theme, self.mcp_manager,
            self._project_root,
            on_status=self.set_status,
            on_restart=self.reload_mcp,
            # Наглядач передається панелі: інакше «Діагностика» недосяжна, а
            # сервери, підняті з панелі, лишаються без контролю живучості.
            watcher=getattr(self, "mcp_watcher", None),
        )
        self.changes_panel = changes_panel.ChangesPanel(
            self.side_stack, self.theme, self._project_root,
            on_open_path=lambda path: self.open_path(Path(path)),
            on_status=self.set_status,
            on_show_diff=self.show_diff_for,
        )
        # ── Власний рушій і пам'ять NEUROMESH ────────────────────────────
        # Обидві панелі працюють із живими сервісами вікна: рушій один на
        # процес (``native_runtime``), пам'ять — одна база на користувача.
        self.runtime_panel = runtime_panel.RuntimePanel(
            self.side_stack, self.theme, lambda: self.native_runtime,
            on_model_activated=self._on_native_model,
            on_status=self.set_status,
        )
        self.neuromesh_panel = neuromesh_panel.NeuromeshPanel(
            self.side_stack, self.theme, lambda: self.memory,
            on_open_memory=self._show_memory_item,
            on_status=self.set_status,
        )
        self._side_widgets = {
            "chats": self.chat_list,
            "cases": self.cases_panel,
            "autonomous": self.autonomous_panel,
            "rag": self.rag_panel,
            "tools": self.tools_panel,
            "explorer": self.file_tree,
            "outline": self.outline,
            "changes": self.changes_panel,
            "skills": self.skills_panel,
            "queue": self.queue_panel,
            "mcp": self.mcp_panel,
            "runtime": self.runtime_panel,
            "neuromesh": self.neuromesh_panel,
        }

        # ── підвал: робоча тека й локальний стан
        foot = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        foot.pack(fill="x", side="bottom", padx=theme.SPACE_SM, pady=(0, theme.SPACE_SM))
        self.nav_foot = foot

        self.project_row = tk.Frame(foot, bg=theme.BG_ALT, cursor="hand2")
        self.project_row.pack(fill="x")
        self.project_icon = tk.Label(self.project_row, text="🗂", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=("Segoe UI", 9))
        self.project_icon.pack(side="left", padx=(theme.SPACE_SM, theme.SPACE_SM))
        self.project_label = tk.Label(self.project_row, text="не обрано", bg=theme.BG_ALT,
                                      fg=theme.FG_DIM, font=("Segoe UI", 8), anchor="w")
        self.project_label.pack(side="left", fill="x", expand=True, pady=2)
        for widget in (self.project_row, self.project_icon, self.project_label):
            widget.bind("<Button-1>", lambda _e: self.open_folder_dialog())
        widgets.Tip(self.project_row, "Змінити робочу теку проєкту")

        state_row = tk.Frame(foot, bg=theme.BG_ALT)
        state_row.pack(fill="x")
        self.local_label = tk.Label(state_row, text="● локально", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w")
        self.local_label.pack(side="left", padx=(theme.SPACE_SM, 0), pady=(0, 2))
        widgets.Tip(self.local_label, "Local-first: дані й моделі лишаються на цьому комп'ютері")
        widgets.IconButton(state_row, "◔", self.open_settings, bg=theme.BG_ALT,
                           fg=theme.FG_FAINT, font=("Segoe UI", 10),
                           tooltip="Налаштування (Ctrl+,)").pack(side="right")

    # 2. Центр: заголовок сесії + робоча область
    def _build_centre(self, outer: tk.Misc) -> None:
        self.main_area = tk.Frame(outer, bg=theme.BG, bd=0, highlightthickness=0)
        self.main_area.columnconfigure(0, weight=1)
        self.main_area.rowconfigure(1, weight=1)
        try:
            self.side_split.add(self.main_area, weight=1)
        except (AttributeError, tk.TclError):
            self.main_area.grid(row=0, column=1, sticky="nsew")

        from tkinter import ttk

        # 2a. Заголовок сесії — на всю ширину робочої області.
        self.header = session_header.SessionHeader(
            self.main_area, self.theme,
            on_modes=self.show_mode_menu,
            on_model=self.show_model_selector,
            on_view=self.set_view,
            on_workspace=lambda: self.set_view("workspace"),
            on_context=self.toggle_context,
            on_chat_mode=self.show_chat_mode_menu,
        )
        self.header.grid(row=0, column=0, sticky="ew")

        # 2b. Горизонтальний поділ: діалог | робоча область | контекст.
        self.h_split = ttk.PanedWindow(self.main_area, orient="horizontal")
        self.h_split.grid(row=1, column=0, sticky="nsew")

        # ── колонка діалогу (ЦЕНТРАЛЬНА)
        self.conversation_host = tk.Frame(self.h_split, bg=theme.BG, bd=0,
                                          highlightthickness=0)
        self.conversation_host.columnconfigure(0, weight=1)
        self.conversation_host.rowconfigure(0, weight=1)
        self.chat_column = self.conversation_host

        # Вертикальний поділ: стрічка діалогу зверху, композер знизу.
        self.v_split = ttk.PanedWindow(self.conversation_host, orient="vertical")
        self.v_split.grid(row=0, column=0, sticky="nsew")

        # Композер живе у власній відцентрованій колонці — тієї самої ширини,
        # що й стрічка діалогу, тож поле вводу не розтягується на весь екран.
        self.composer_host = widgets.CenteredColumn(
            self.conversation_host, bg=theme.BG_ALT,
            max_width=int(getattr(self.settings.ui, "chat_max_width", 0)
                          or theme.CHAT_MAX_WIDTH),
            gutter=theme.SPACE_XL,
        )

        self.chat = ChatPanel(self.conversation_host, self.theme, self.settings,
                              self.registry, on_status=self.set_status,
                              composer_parent=self.composer_host.inner)
        self.chat.on_apply_code = self._apply_code_from_chat
        self.chat.on_queue_task = self._queue_from_chat
        self.chat.on_split_task = self._split_task_to_queue
        self.chat.on_open_queue = lambda: self.show_side("queue")
        self.chat.on_open_skills = lambda: self.show_side("skills")
        self.chat.on_new_chat = self._on_new_chat
        self.chat.on_busy_change = self._on_chat_busy
        self.chat.on_message = self._remember_message
        # Підказки над полем («Поясни файл» тощо) мають бачити реальний файл.
        # Звертаємось ліниво: вкладки створюються пізніше за панель чату,
        # тож пряме ``self.tabs`` тут падало з AttributeError на старті.
        self.chat.current_path_provider = self._current_editor_path
        self.chat.on_permission_change = self._on_permission_change
        self.chat.on_set_goal = self._set_goal
        self.chat.on_feedback = self._save_feedback
        self.chat.on_pick_model = self.show_model_selector
        self.chat.on_export = self.export_current_chat
        self.chat.on_use_skill = self._use_skill_by_name
        self.chat.on_model_pick = self._on_chat_model_pick
        # Пігулки над полем вводу: та сама тека й той самий режим, що й у
        # шапці, але там, де користувач пише задачу.
        self.chat.on_workspace_menu = self.show_workspace_menu
        self.chat.on_mode_menu = self.show_mode_menu
        self.chat.on_effort_pick = self._on_chat_effort_pick
        self.chat.on_voice_query = self._on_voice_query
        self.chat.on_voice_action = self._on_voice_action
        # Єдиний шлюз до агента: без вибраної теки проєкту запит не стартує.
        # Раніше перевірка стояла лише в «Новий чат» та «Відкрити чат», тож
        # стартовий екран, голос, скіли й черга запускали агента з домашньою
        # текою користувача.
        self.chat.project_ready = self.has_project
        self.chat.on_need_project = self._show_project_gate
        # ── Підйом моделі на першу ж дію користувача ──────────────────────
        # Модель вивантажується через простій (це правильна економія VRAM),
        # але раніше НІКОЛИ не піднімалась назад: ``model_keeper.reload()``
        # не викликався ніде. Через це після 5 хв паузи кожен запит падав із
        # «модель недоступна», і здавалось, що вона взагалі не стартує
        # (реальний лог: старт о 19:03, вивантаження о 19:08, помилка о 19:10).
        self.chat.before_send = self._before_agent_request
        self.chat.on_title_change = self.header.set_title
        # «Справи»: кожен запит → справа, кожна подія агента → крок у ній.
        self.chat.on_case_start = self._case_begin
        self.chat.on_event = self._case_on_event
        # Стан чату (спінер, назва, доступність моделі) показуємо в заголовку.
        self.chat.bind_header(self.header.title_label, self.header.status_dot)
        self._apply_voice_settings()

        self.v_split.add(self.chat, weight=3)
        self.v_split.add(self.composer_host, weight=0)
        # Композер — НЕЗМІННА частина інтерфейсу: у ньому пишуть завдання.
        # ``PanedWindow`` тримає панель із ``weight=0`` сталою, але коли
        # стрічка діалогу просить більше місця (довга відповідь, картка
        # аналізу, етапи), Tk стискає саме композер — і поле вводу
        # зникає за нижнім краєм. Користувач бачив порожню смугу замість
        # форми («форма взагалі десь внизу ховається»).
        #
        # Тому: (1) композер має власну мінімальну висоту, (2) вертикальний
        # саш не можна посунути нижче за неї.
        try:
            self.composer_host.configure(height=theme.COMPOSER_HEIGHT)
            self.composer_host.pack_propagate(False)
        except (tk.TclError, AttributeError):
            pass
        self._chat_shown = True
        self._composer_shown = True
        self._focus_mode = False
        self._view = "chat"

        # ── робоча область: редактор + нижні вкладки
        centre = tk.Frame(self.h_split, bg=theme.BG, bd=0, highlightthickness=0)
        centre.rowconfigure(0, weight=1)
        centre.columnconfigure(0, weight=1)
        self.centre = centre

        self.editor_split = tk.Frame(centre, bg=theme.BG, bd=0, highlightthickness=0)
        self.editor_split.grid(row=0, column=0, sticky="nsew")
        self.editor_split.rowconfigure(0, weight=1)
        self.editor_split.columnconfigure(0, weight=1)

        self.tabs = EditorTabs(
            self.editor_split, self.theme, self.settings,
            on_status=self.set_status,
            on_cursor=self._on_cursor,
            on_saved=self._on_saved,
            on_changed=self._on_tabs_changed,
            on_new_tab=self.new_file,
            on_analysis=self._on_editor_analysis,
        )
        self.tabs.grid(row=0, column=0, sticky="nsew")

        # ── смуга перетягування між редактором і нижньою панеллю ───────────
        # Раніше висота нижньої панелі була ФІКСОВАНОЮ (grid з height), і
        # користувач не міг її розтягнути: «панель не розтягується по
        # розмірах». Тепер між редактором і панеллю лежить тонка смуга,
        # яку тягнуть мишею — як у будь-якій IDE.
        self.bottom_sash = tk.Frame(
            self.editor_split, bg=theme.BORDER, bd=0, highlightthickness=0,
            height=6, cursor="sb_v_double_arrow")
        self.bottom_sash.grid(row=1, column=0, sticky="ew")
        self.bottom_sash.grid_remove()
        self.bottom_sash.bind("<ButtonPress-1>", self._bottom_sash_press)
        self.bottom_sash.bind("<B1-Motion>", self._bottom_sash_drag)
        self.bottom_sash.bind("<ButtonRelease-1>", self._bottom_sash_release)
        self.bottom_sash.bind("<Enter>",
                              lambda _e: self.bottom_sash.configure(bg=theme.ACCENT))
        self.bottom_sash.bind("<Leave>",
                              lambda _e: self.bottom_sash.configure(bg=theme.BORDER))
        #: Висота панелі, поки користувач тягне смугу.
        self._sash_drag_from = 0
        self._sash_drag_height = 0

        self.bottom_tabs = ttk.Notebook(self.editor_split)
        self.terminal = TerminalPanel(self.bottom_tabs, self.theme, Path(self.settings.workspace))
        self.terminal.on_status = self.set_status
        self.project_search = ProjectSearch(self.bottom_tabs, self.theme,
                                            self._project_root)
        self.project_search.on_open = lambda path, line: self.open_path(path, line)
        self.model_hub = ModelHubPanel(self.bottom_tabs, self.theme, self.settings,
                                       on_model_ready=self._on_hub_model_ready)
        self.preview = LivePreviewPanel(self.bottom_tabs, self.theme,
                                        self._project_root,
                                        on_status=self.set_status,
                                        app=self.app)
        # ── Центр завдань: черга локального агента як повноцінна панель.
        # Кнопки тут викликають справжні дії виконавця, а не малюють стан.
        self.task_center = task_center.TaskCenter(
            self.bottom_tabs, self.theme, self.task_queue,
            executor=self.executor,
            on_pause=self.pause_queue,
            on_resume=self.resume_queue,
            on_stop=self.stop_plan,
            on_retry=self.retry_plan_task,
            on_clear=self.clear_plan_finished,
            on_run_next=self.run_next_task,
            on_add_task=self._queue_from_panel,
            on_open_file=self._open_project_file,
            on_status=self.set_status,
            chat_id_provider=self._active_chat_id,
        )
        self.bottom_tabs.add(self.task_center, text="  ≡ Завдання  ")
        self.bottom_tabs.add(self.terminal, text="  Термінал  ")
        self.bottom_tabs.add(self.project_search, text="  Пошук  ")
        self.bottom_tabs.add(self.model_hub, text="  Хаб моделей  ")
        self.bottom_tabs.add(self.preview, text="  🌐 Сайт  ")
        self._bottom_shown = False
        self._bottom_height = int(self.settings.ui.bottom_height or 200)
        if self.settings.ui.bottom_visible:
            # Показуємо через ту саму функцію, що й решта коду: вона ставить
            # смугу перетягування й правильний номер рядка.
            self._place_bottom(True)

        # Стартовий екран живе поверх КОЛОНКИ ДІАЛОГУ: це стан «сесії ще
        # немає», і він має бути там, де користувач очікує почати роботу.
        # ВАЖЛИВО: сам контейнер не розміщуємо тут. ``place`` ставив би
        # порожній кадр поверх стрічки діалогу вже під час побудови вікна, і
        # коли сесія має історію (welcome не показується), оверлей лишався б
        # назавжди — розмова виглядала порожньою. Показує його лише
        # :meth:`show_welcome`.
        self.workspace_host = tk.Frame(self.conversation_host, bg=theme.BG, bd=0,
                                       highlightthickness=0)

        # ── колонка контексту
        self.context_host = tk.Frame(self.h_split, bg=theme.BG_ALT,
                                     width=self.settings.ui.context_width, bd=0,
                                     highlightthickness=0)
        self.context_host.pack_propagate(False)
        self.context = context_panel.ContextPanel(
            self.context_host, self.theme, self._project_root,
            on_open_path=lambda path: self.open_path(Path(path)),
            on_close_tab=self.tabs.close_tab,
            on_select_tab=self.tabs.select,
            on_status=self.set_status,
            on_open_settings=self.open_settings,
            on_open_tools=lambda: self.show_side("tools"),
            on_toggle_collapse=self.toggle_context,
        )
        self.context.pack(fill="both", expand=True)
        self.context.tabs_provider = self.tabs.tab_titles
        self.context.active_tab_provider = self.tabs.current_key
        # Живі дані про агента: стан із черги, модель із налаштувань,
        # заповнення контексту зі статистики чату, інструменти з реєстру.
        self.context.agent_status_provider = self._agent_status_text
        self.context.model_provider = self._model_summary
        self.context.context_provider = self._context_usage
        self.context.tools_provider = self._active_tool_names
        # Стан лінивого реєстру й чесність підрахунку токенів — з реальних
        # механізмів, а не декоративні числа.
        self.context.registry_provider = self._registry_state_for_panel
        self.context.exact_counter_provider = self._counter_is_exact
        self.context.budget_provider = self._budget_state_for_panel

        # ── права колонка: живий прев'ю застосунку (агент тестує тут).
        self.preview_host = tk.Frame(self.h_split, bg=theme.BG_ALT,
                                     width=theme.PREVIEW_WIDTH, bd=0,
                                     highlightthickness=0)
        self.preview_host.pack_propagate(False)
        self.live_preview = LivePreviewPanel(
            self.preview_host, self.theme,
            self._project_root,
            on_status=self.set_status,
            app=self.app,
        )
        self.live_preview.pack(fill="both", expand=True)
        # ── сторінка як дані: інспектор, консоль, знімок, перевірки ────────
        # Панель не знає про CDP напряму — вона кличе ці колбеки, а вони вже
        # беруть сесію вбудованого браузера. Так панель можна тестувати без
        # мережі й без Chromium.
        self.live_preview.on_inspect_at = self._inspect_page_at
        self.live_preview.on_send_element = self.send_element_to_agent
        self.live_preview.console_provider = self._page_console
        self.live_preview.action_provider = self._page_action
        # ── Справжній HMR: оновлення сторінки за ТИПОМ файлу ──────────────
        # Панель прев'ю сама викликає ``hmr.update_for_file``: CSS підмінюється
        # без перезавантаження, HTML — точково, JS — із відновленням стану.
        # Їй потрібні дві речі: жива CDP-сесія і шлях збереженого файлу.
        self.live_preview.inner.hmr_session_provider = self._browser_cdp
        self.live_preview.inner.saved_path_provider = self._current_editor_path
        for holder in (self.live_preview.inner, self.preview):
            try:
                holder.saved_path_provider = self._current_editor_path
            except AttributeError:
                pass

        self.h_split.add(self.conversation_host, weight=1)
        self.h_split.add(centre, weight=1)
        self.h_split.add(self.context_host, weight=0)
        self._context_shown = True
        # Прев'ю ховаємо за замовчуванням: воно з'являється кнопкою
        # «Live Preview» або автоматично, коли агент запускає застосунок.
        self._preview_shown = False

    def _build_status(self) -> None:
        bar = tk.Frame(self, bg=theme.BG_ALT, height=24, bd=0, highlightthickness=0)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.status_bar = bar

        self.status_label = tk.Label(bar, text="Готово", bg=theme.BG_ALT, fg=theme.FG_DIM,
                                     font=("Segoe UI", 8), anchor="w")
        self.status_label.pack(side="left", padx=theme.SPACE_LG)

        # ── індикатор прихованих збоїв ─────────────────────────────────────
        # У коді багато місць, де виняток ковтається, щоб інтерфейс не
        # падав. Без цього підпису такі збої невидимі: кнопка натиснулась,
        # але «нічого не сталося», і причини не видно ніде.
        self.failure_label = tk.Label(
            bar, text="", bg=theme.BG_ALT, fg=theme.WARN,
            font=("Segoe UI", 8), cursor="hand2")
        self.failure_label.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.failure_label.bind("<Button-1>", lambda _e: self.show_failures())
        widgets.Tip(self.failure_label, "Приховані збої — натисни, щоб побачити")
        try:
            safe.on_failure(self._on_hidden_failure)
        except Exception:  # noqa: BLE001 - індикатор не має ламати старт
            LOG.debug("Не вдалось підписатись на реєстр збоїв", exc_info=True)

        self.cursor_label = tk.Label(bar, text="Ln 1, Col 1", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                     font=("Segoe UI", 8))
        self.cursor_label.pack(side="right", padx=theme.SPACE_LG)

        self.ast_label = tk.Label(bar, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                  font=("Segoe UI", 8))
        self.ast_label.pack(side="right", padx=theme.SPACE_MD)

        self.lang_label = tk.Label(bar, text="—", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8))
        self.lang_label.pack(side="right", padx=theme.SPACE_MD)

        self.agent_label = tk.Label(bar, text="агент: очікує", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8))
        self.agent_label.pack(side="right", padx=theme.SPACE_MD)

        # Без вибраного проєкту не показуємо шлях домашньої теки: інакше
        # статусбар казав «C:\Users\<ім'я>», ніби агент уже працює там.
        self.ws_label = tk.Label(
            bar, text=(str(self.settings.workspace) if self.has_project() else "теку не обрано"),
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8))
        self.ws_label.pack(side="right", padx=theme.SPACE_LG)

    def _on_root_configure(self, event=None) -> None:
        """Перерахувати саші після зміни розміру вікна (з невеликою паузою)."""
        if event is not None and event.widget is not self:
            return
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except (tk.TclError, ValueError):
                pass
        try:
            self._resize_after = self.after(120, self._apply_after_resize)
        except tk.TclError:
            self._resize_after = None

    def _apply_after_resize(self) -> None:
        self._resize_after = None
        self._apply_responsive()
        self._apply_sash_positions()

    def _apply_responsive(self) -> None:
        """Адаптивна композиція: розміри діалогу й панелей під екран.

        Три колонки (діалог + редактор + контекст) мають сенс лише на
        широкому екрані. Коли місця бракує, зникає саме колонка контексту:
        редактор лишається, бо він і є робоча область.

        Якщо користувач САМ перемикав контекст, його вибір поважається —
        інакше панель поверталась би щоразу після зміни розміру вікна.
        """
        try:
            total = self.h_split.winfo_width()
        except tk.TclError:
            return
        if total <= 1:
            return
        self._apply_adaptive_chat(total)
        # ── колонка контексту ──────────────────────────────────────────────
        # У режимі «Чат» (без редактора) контекст забирав 359 px у чату й
        # лишав його вузькою смужкою посередині. Ховаємо її, коли редактор
        # не показаний: користувач прийшов сюди розмовляти, а не дивитись
        # список файлів.
        chat_only = self._view != "workspace"
        if self._context_user_choice is None:
            want_context = total >= 1180 and not self._focus_mode and not chat_only
            if want_context != self._context_shown:
                self._context_shown = want_context
                self._reorder_panes(
                    with_centre=(self._view == "workspace" and self._centre_in_split()))
        # Редактор ховаємо лише в режимі «тільки чат» — це явний вибір.
        if self._focus_mode and self._centre_in_split():
            self._reorder_panes(with_centre=False)

    def _apply_adaptive_chat(self, total_width: int) -> None:
        """Підігнати ширину колонки діалогу й ліміт рядків під екран.

        Ширина стрічки не має бути сталою: на ноутбуці 1366 px «комфортні»
        920 px лишали редактору смужку, а на 4K розмова розтягувалась на
        пів екрана. Тут рахуємо ширину з екрана й поточного вікна, а
        кількість видимих рядків однієї відповіді — з висоти стрічки.
        """
        try:
            screen = adaptive.screen_size(self)
            height = self.conversation_host.winfo_height()
        except tk.TclError:
            return
        metrics = adaptive.metrics_for(
            screen=screen,
            window=(total_width, max(0, height) or self.winfo_height()),
            feed_height=max(0, height),
            sidebar=int(self.settings.ui.sidebar_width or 264),
            min_width=320,
            max_width=int(getattr(self.settings.ui, "chat_max_width", 0) or 0),
        )
        previous = getattr(self, "_chat_metrics", None)
        self._chat_metrics = metrics
        if previous is not None and previous.body_lines != metrics.body_lines:
            self._chat_lines_limit = metrics.body_lines
            try:
                self.chat.set_max_lines(metrics.body_lines)
            except (tk.TclError, AttributeError):
                pass
        # Вузький екран: коротші назви в списку сесій і згорнуті службові
        # підписи композера (це робить сам ChatPanel за шириною).
        try:
            self.chat_list.set_compact(metrics.compact)
        except (tk.TclError, AttributeError):
            pass

    def _apply_sash_positions(self) -> None:
        """Розставити саші за тим, які панелі зараз у розкладці.

        Панелей може бути від 1 до 4: діалог, робоча область, контекст і
        живий прев'ю — кожна ховається окремо. Тому НЕ можна звертатись до
        сашів фіксованими індексами: у ``PanedWindow`` з N панелями є лише
        N-1 сашів. Раніше саме через це розкладка ламалась, щойно
        з'являлась четверта панель.

        Алгоритм: збираємо фактичний порядок панелей, рахуємо бажану ширину
        кожної, далі ставимо саш за накопиченою сумою.

        ВАЖЛИВО про «зависання». На старті ця функція викликалась 8 разів
        (``after_idle`` + 120 мс + 420 мс + після кожного ``grid``), і кожен
        виклик робить ``update_idletasks()`` — тобто повний перерахунок
        розкладки. Заміряно профілером: 0.57 с із першого кадру, і
        інтерфейс застигав. Тепер запити ЗЛИВАЮТЬСЯ: скільки б разів її не
        покликали, справжній перерахунок відбудеться один раз, коли
        інтерфейс відпочине.
        """
        # Зливаємо виклики: плануємо один відкладений перерахунок.
        if getattr(self, "_sash_pending", False):
            return
        self._sash_pending = True
        try:
            job = self.after_idle(self._do_apply_sash)
        except tk.TclError:
            self._sash_pending = False
            return
        # Ідентифікатор теж треба знати: ``after_idle`` лишає команду в Tcl,
        # і після ``destroy()`` вона падає з «invalid command name».
        jobs = getattr(self, "_sash_jobs", None)
        if jobs is None:
            jobs = self._sash_jobs = []
        jobs.append(job)

    def _sash_after(self, delay: int) -> None:
        """Запланувати перерахунок сашів і ЗАПАМ'ЯТАТИ ідентифікатор.

        Без запам'ятовування відкладені виклики лишались у Tcl після
        ``destroy()``: Tk друкував у stderr

            invalid command name "1234_apply_sash_positions"

        а ``tests/live_every_button.py`` падав на самому закритті вікна —
        після 77 успішних натискань. Тепер усі вони знімаються разом із
        вікном (див. ``on_close``).
        """
        try:
            job = self.after(delay, self._apply_sash_positions)
        except tk.TclError:
            return
        jobs = getattr(self, "_sash_jobs", None)
        if jobs is None:
            jobs = self._sash_jobs = []
        jobs.append(job)
        # Список не має рости безкінечно: спрацьовані ідентифікатори
        # лишаємо лише на час, доки їх можна скасувати.
        if len(jobs) > 24:
            del jobs[: len(jobs) - 24]

    def _schedule_sash_retry(self) -> None:
        """Спробувати розставити саші ще раз, коли вікно отримає розмір.

        Геометрія недоступна лише на самому початку (``winfo_width()`` == 1).
        Повторюємо КІЛЬКА разів із наростанням паузи, а не нескінченно:
        якщо вікно так і не показали, це не привід крутити таймер вічно.
        """
        attempts = getattr(self, "_sash_retry", 0)
        if attempts >= 4:
            return
        self._sash_retry = attempts + 1
        delay = 80 * (attempts + 1)
        self._sash_after(delay)

    def _do_apply_sash(self) -> None:
        """Справжній перерахунок сашів (один раз на серію запитів)."""
        self._sash_pending = False
        try:
            # Користувач тягне межу — його розмір недоторканний. Інакше
            # перерахунок на кожну подію <Configure> повертав саш на місце,
            # і панель «не розширювалась мишкою».
            if getattr(self, "_user_dragging", False):
                return
            panes = [str(pane) for pane in self.h_split.panes()]
            total = self.h_split.winfo_width()
            if total <= 0:
                # Вікно ще не отримало геометрії (перший кадр, приховане
                # вікно або ``winfo_width() == 1`` до ``update_idletasks``).
                # Раніше тут просто виходили — і саші лишались на 0, тобто
                # збережена розкладка НЕ відновлювалась, хоч файл був
                # правильний. Під навантаженням (повний набір тестів) перший
                # кадр запізнюється, і ``test_layout_persist`` падав з
                # «було (620, 480), стало (0, 480)». Тому не здаємось, а
                # питаємо геометрію напряму й пробуємо ще раз пізніше.
                try:
                    self.update_idletasks()
                except tk.TclError:
                    return
                total = self.h_split.winfo_width()
                if total <= 0:
                    self._schedule_sash_retry()
                    self._apply_v_sash()
                    return
            if len(panes) < 2:
                self._apply_v_sash()
                return
            # Геометрія є — лічильник повторів більше не потрібен.
            self._sash_retry = 0

            # Скільки місця віддати кожній панелі праворуч від діалогу.
            # Межі — абсолютні, а не «третина вікна»: збережене значення з
            # попереднього запуску могло бути записане в іншій композиції
            # (напр. коли колонка контексту займала пів екрана), і тоді
            # воно з'їдало місце в редактора.
            ctx_w = layout.clamp(
                self.layout.get("context_width", self.settings.ui.context_width),
                170, theme.CONTEXT_MAX_WIDTH)
            prev_w = layout.clamp(
                self.layout.get("preview_width", theme.PREVIEW_WIDTH),
                theme.PREVIEW_MIN_WIDTH, theme.PREVIEW_MAX_WIDTH)

            has_centre = any(p.endswith(str(self.centre)) for p in panes)

            # ── ширина діалогу ─────────────────────────────────────────────
            # Збережений вибір користувача або адаптивний розрахунок. Стелю
            # задає залишок після правих колонок і мінімуму редактора.
            fixed_right = 0
            for p in panes:
                if p.endswith(str(self.context_host)):
                    fixed_right += ctx_w
                elif p.endswith(str(self.preview_host)):
                    fixed_right += prev_w
            # Мінімум діалогу — АБСОЛЮТНИЙ, а не «п'ята частина вікна».
            # Раніше тут стояло ``total * 0.20``: на екрані 3189 px це 637 px,
            # і збережена ширина 620 «не відновлювалась» після перезапуску —
            # межа поверталась на 637. Користувач, який сам звузив діалог,
            # має право на свій вибір; обмежуємо лише тим, щоб панель
            # лишалась робочою.
            chat_min = 240
            editor_min = 200 if has_centre else 0
            ceiling = max(chat_min, total - fixed_right - editor_min)
            default_w = int(getattr(self._chat_metrics, "chat_width", 0) or 0)
            if not default_w:
                default_w = int(total * 0.42) if has_centre else ceiling
            saved = self.layout.get("chat_split", default_w)
            # Адаптивна ширина тут — ТИПОВЕ значення, а не стеля: якщо
            # користувач сам потягнув межу, його вибір важливіший.
            chat_w = layout.clamp(saved, chat_min, ceiling)
            if not has_centre:
                # Редактора немає — діалог займає весь залишок.
                chat_w = ceiling

            # ── бажана ширина КОЖНОЇ панелі ────────────────────────────────
            # Панелі діляться на два види:
            #   * фіксовані (контекст, прев'ю) — мають свою ширину;
            #   * гнучкі (діалог, робоча область) — ділять залишок.
            #
            # Накопичувати позицію «додаю ширину кожного» НЕ можна: у
            # гнучкої панелі власної ширини немає, і саш за нею лишався б
            # на місці попереднього — редактор стискався до нуля, а
            # контекст забирав пів екрана (перевірено: 647 px).
            widths: dict[int, int] = {}
            fixed_total = 0
            flexible: list[int] = []
            for index, pane in enumerate(panes):
                if pane.endswith(str(self.context_host)):
                    widths[index] = ctx_w
                    fixed_total += ctx_w
                elif pane.endswith(str(self.preview_host)):
                    widths[index] = prev_w
                    fixed_total += prev_w
                elif pane.endswith(str(self.conversation_host)):
                    widths[index] = chat_w
                    fixed_total += chat_w
                else:
                    flexible.append(index)      # робоча область

            # Залишок ділимо між гнучкими панелями порівну.
            if flexible:
                rest = max(0, total - fixed_total)
                share = rest // len(flexible)
                for position_index, index in enumerate(flexible):
                    # Останній забирає залишок, щоб сума була точно total.
                    widths[index] = (rest - share * (len(flexible) - 1)
                                     if position_index == len(flexible) - 1
                                     else share)

            # ── ставимо саші за накопиченою сумою ──────────────────────────
            position = 0
            for index, pane in enumerate(panes[:-1]):
                position += widths.get(index, 0)
                # Саш не може стояти ближче ніж 60 px до краю.
                position = layout.clamp(position, 60, max(60, total - 60))
                self.h_split.sashpos(index, position)
            # Перевіряємо, що Tk справді застосував позицію. Поки внутрішня
            # розкладка не перерахована (``total`` щойно став >0, але Tk ще
            # не розклав панелі), ``sashpos(i, N)`` приймається й тут-таки
            # скидається у від'ємне значення — панель «злипається» в 0, і
            # збережена розкладка НЕ відновлюється. Саме це давало
            # «було (620, 480), стало (0, 480)» у ``test_layout_persist``.
            self._verify_sash_applied(widths, panes)
            self._apply_v_sash()
        except (tk.TclError, ValueError):
            pass

    def _verify_sash_applied(self, widths: dict[int, int],
                             panes: list[str]) -> None:
        """Переконатись, що саші стали там, куди їх поставили.

        ``PanedWindow.sashpos(i, N)`` не гарантує негайного результату: якщо
        Tk ще не розклав панелі, значення приймається, а потім скидається.
        Тому читаємо фактичні позиції й, якщо розбіжність є, плануємо один
        повторний перерахунок — уже після того, як Tk завершить розкладку.
        """
        expected = 0
        ok = True
        for index in range(len(panes) - 1):
            expected += widths.get(index, 0)
            expected = layout.clamp(expected, 60, max(60, self.h_split.winfo_width() - 60))
            try:
                actual = self.h_split.sashpos(index)
            except tk.TclError:
                return
            if actual < 60:
                ok = False
                break
        if not ok:
            self._schedule_sash_retry()

    def _apply_v_sash(self) -> None:
        """Розставити вертикальні саші (стрічка / композер, редактор / низ)."""
        try:
            # Ліва панель: ширина з розкладки або збережена, обмежена так,
            # щоб центру лишалось місце навіть на вузькому вікні.
            try:
                split_w = self.side_split.winfo_width()
                if split_w > 40 and self.sidebar.winfo_ismapped():
                    saved = self.layout.get("sidebar_width",
                                            int(self.settings.ui.sidebar_width or 300))
                    limit = max(180, int(split_w * 0.45))
                    width = layout.clamp(saved, 180, limit)
                    if self._sidebar_collapsed:
                        width = theme.RAIL_COLLAPSED_WIDTH
                    if self.side_split.sashpos(0) != width:
                        self.side_split.sashpos(0, width)
            except (tk.TclError, ValueError, AttributeError):
                pass
            height = self.v_split.winfo_height()
            if height > 0:
                row = self.layout.get("composer_height", self.settings.ui.composer_height)
                # Композер НІКОЛИ не має зникати: він потрібен під час роботи
                # агента найбільше — щоб дописати уточнення. Нижня межа —
                # theme.COMPOSER_HEIGHT (підказки + поле + рядок моделі);
                # верхня лишає стрічці щонайменше 200 px, щоб було видно
                # хоч кілька повідомлень.
                #
                # Раніше верхня межа була ``height - 40%``: на високому вікні
                # (1272 px) це 764 px, і збережена висота 792 не
                # відновлювалась — межа «сповзала» на 508 замість 480.
                # Тепер обмеження абсолютне, а не пропорційне: вибір
                # користувача переживає перезапуск.
                low = theme.COMPOSER_HEIGHT
                high = max(low, height - 200)
                row = layout.clamp(row, low, high)
                target = max(0, height - row)
                if self.v_split.sashpos(0) != target:
                    self.v_split.sashpos(0, target)
            inner = self.editor_split.winfo_height()
            if self._bottom_shown and inner > 0:
                bottom = self.layout.get("bottom_height", self._bottom_height)
                # Не менше 180 px: інакше хаб моделей не вміщає список
                # результатів і показує лише рядок пошуку.
                bottom = layout.clamp(bottom, 180, max(200, inner - 160))
                self._bottom_height = bottom
                try:
                    self.bottom_tabs.configure(height=bottom)
                except tk.TclError:
                    pass
        except (tk.TclError, ValueError):
            pass

    def _remember_layout(self) -> None:
        """Запам'ятати поточні позиції сашів."""
        try:
            # Розмір вікна: користувач міг розтягнути його мишкою, і
            # наступний запуск має відкритись так само (див. _apply_start_geometry).
            try:
                if self.state() != "zoomed":
                    self.layout.set("window_size",
                                    f"{self.winfo_width()}x{self.winfo_height()}")
                elif self.layout.get("window_size", ""):
                    # Розгорнуте вікно перекриває збережений розмір — тоді
                    # прибираємо його, щоб наступний запуск знову був повним.
                    try:
                        self.layout.values.pop("window_size", None)
                    except (AttributeError, TypeError):
                        pass
            except (tk.TclError, ValueError, AttributeError):
                pass
            # Ширина лівої панелі — її тепер можна тягнути мишею.
            try:
                if self._sidebar_visible() and not self._sidebar_collapsed:
                    width = int(self.side_split.sashpos(0))
                    if width >= 180:
                        self.layout.set("sidebar_width", width)
                        # Тримаємо налаштування в згоді з розкладкою: панель
                        # відкривається тією ж шириною і з налаштувань.
                        self.settings.ui.sidebar_width = width
            except (tk.TclError, ValueError, AttributeError):
                pass
            total = self.h_split.winfo_width()
            panes = [str(pane) for pane in self.h_split.panes()]
            if total > 0 and len(panes) >= 2:
                self.layout.set("chat_split", self.h_split.sashpos(0))
                last = total
                if len(panes) >= 3 and self._context_shown:
                    self.layout.set("context_width", max(170, total - self.h_split.sashpos(1)))
                if self._preview_shown and len(panes) >= 2:
                    # Прев'ю — завжди остання панель: його ширина це
                    # відстань від останнього саша до правого краю.
                    try:
                        pos = self.h_split.sashpos(len(panes) - 2)
                        width = total - pos
                        if width > 100:
                            self.layout.set("preview_width", width)
                    except (tk.TclError, ValueError):
                        pass
            height = self.v_split.winfo_height()
            if height > 0:
                self.layout.set("composer_height", height - self.v_split.sashpos(0))
            if self._bottom_shown:
                self.layout.set("bottom_height", self._bottom_height)
            layout.save(self.layout)
        except (tk.TclError, ValueError):
            pass

    def reset_layout(self) -> None:
        """Скинути розкладку до типових значень."""
        self.layout = layout.Layout()
        layout.save(self.layout)
        self._sash_after(0)
        self.set_status("Розкладку скинуто до типової.")

    def _auto_context(self, show: bool) -> None:
        """Увімкнути/вимкнути колонку контексту (завжди останньою)."""
        if show == self._context_shown:
            return
        self._context_shown = bool(show)
        self._reorder_panes(with_centre=(getattr(self, "_view", "chat") == "workspace"))
        if show:
            try:
                self.context.refresh()
            except tk.TclError:
                pass

    # ── гарячі клавіші ─────────────────────────────────────────────────────
    def _wire_shortcuts(self) -> None:
        bindings = {
            "<Control-n>": lambda e: self.new_file(),
            "<Control-o>": lambda e: self.open_file_dialog(),
            "<Control-s>": lambda e: self.save_file(),
            "<Control-Shift-S>": lambda e: self.save_file_as(),
            "<Control-w>": lambda e: self.close_tab(),
            "<Control-Shift-T>": lambda e: self.reopen_tab(),
            "<Control-p>": lambda e: self.quick_open(),
            "<Control-Shift-P>": lambda e: self.command_palette(),
            "<Control-Shift-M>": lambda e: self.open_model_hub(),
            "<Control-Shift-F>": lambda e: self.open_project_search(),
            "<Control-f>": lambda e: self.open_search(),
            "<Control-b>": lambda e: self.toggle_sidebar(),
            "<Control-Alt-b>": lambda e: self.toggle_chat(),
            "<Control-Alt-v>": lambda e: self.toggle_preview(),
            "<Control-grave>": lambda e: self.toggle_bottom(),
            "<Control-comma>": lambda e: self.open_settings(),
            "<Control-equal>": lambda e: self.zoom(1),
            "<Control-minus>": lambda e: self.zoom(-1),
            "<Control-Alt-Return>": lambda e: self.send_file_to_agent(),
            "<Control-Alt-q>": lambda e: self.add_queue_dialog(),
            "<Control-Alt-j>": lambda e: self.show_side("queue"),
            "<Control-Alt-c>": lambda e: self.terminal.interrupt(),
            # Ctrl+L — «очистити термінал», як у справжній консолі.
            # Команда ``run.terminal_clear`` існувала в реєстрі й показувала
            # цю комбінацію в палітрі, але прив'язки не було: клавіша не
            # працювала (знайдено ``tools/audit_keys_consistency.py``).
            "<Control-l>": lambda e: self.terminal.clear(),
            "<Control-Alt-w>": lambda e: self.show_bottom("tasks"),
            "<Control-Alt-s>": lambda e: self.stop_plan(),
            "<Control-Alt-k>": lambda e: self.show_side("skills"),
            "<Control-Alt-d>": lambda e: self.show_side("cases"),
            "<Control-Alt-a>": lambda e: self.toggle_autonomous(),
            "<Control-Alt-i>": lambda e: self.show_side("rag"),
            "<Control-Alt-t>": lambda e: self.show_side("tools"),
            "<Control-Alt-f>": lambda e: self.toggle_focus_mode(),
            "<Control-Alt-r>": lambda e: self.reset_layout(),
            "<Control-Shift-A>": lambda e: self.show_ast_tree(),
            "<Control-Alt-p>": lambda e: self.open_site(),
            "<Control-Alt-l>": lambda e: self.open_url_dialog(),
            "<Control-F5>": lambda e: self.run_tests(),
            "<F5>": lambda e: self.run_current_file(),
        }
        for sequence, handler in bindings.items():
            self.bind_all(sequence, self._wrap(handler), add="+")

        # Clicking anywhere outside a popup (or switching apps) must close it:
        # an -topmost card left on screen looks like a frozen second window.
        self.bind("<FocusOut>", self._on_window_deactivate, add="+")
        self.bind("<Button-1>", self._on_root_click, add="+")
        # Будь-який ввід користувача = «він працює»: таймер вивантаження
        # моделі скидається. Слухаємо на рівні вікна, тож клавіші в
        # редакторі й у полі чату теж рахуються.
        for sequence in ("<KeyPress>", "<ButtonPress>", "<MouseWheel>"):
            try:
                self.bind_all(sequence, self._wake_on_action, add="+")
            except tk.TclError:
                pass

    def _on_root_click(self, event=None) -> None:
        """Клік у головному вікні закриває спливні картки.

        Картки мають ``-topmost``; без цього вони лишались на екрані після
        переходу до іншої дії й перекривали діалоги.
        """
        if event is not None and event.widget is not self:
            return
        self._close_popovers()

    def _wrap(self, handler):
        def inner(event=None):
            try:
                return handler(event)
            except Exception as exc:  # noqa: BLE001 - не ламаємо обробку клавіш
                self.set_status(f"Помилка дії: {exc}")
                return None

        return inner

    # ── старт ──────────────────────────────────────────────────────────────
    def _startup(self) -> None:
        self.set_status(f"Робоча тека: {self.settings.workspace}")
        # Застосувати збережений режим дозволів до чату й агента.
        try:
            self.chat.set_permission_mode(self.permission_mode)
        except (tk.TclError, AttributeError):
            pass
        self.agent.permission_mode = self.permission_mode
        # Запам'ятати базовий ліміт кроків: режими не мають його переписувати.
        modes.remember_base_steps(self.settings.agent.max_steps)
        # Режим роботи: дозволи, ліміт кроків і підказка моделі.
        self.set_agent_mode(self.agent_mode)
        self._apply_cloud_provider()
        # Якщо модель не вибрана, а GGUF лежить на диску — підхопити її.
        # Інакше агент пише «Модель не вибрана» й мовчки йде в офлайн-роутер,
        # хоч модель у користувача вже є.
        self._adopt_local_model()
        self._sync_chat_model()
        # Без вибраного проєкту не показуємо вміст домашньої теки: у
        # провіднику й панелі «Зміни» з'являлись ``AppData``, ``NTUSER.DAT``
        # та інше, і це виглядало так, ніби агент уже працює в домі.
        start = Path(self.settings.workspace) if self.has_project() else None
        self.terminal.set_cwd(start or Path(self.settings.workspace))
        self.set_project(str(start) if start else "")
        self._show_side_initial()
        # Підпис моделі в чаті має бути правильним одразу, а не після першої
        # перевірки сервера — інакше заголовок показує «модель не вибрана».
        self._on_model_changed()
        self._ensure_chat()
        self._adopt_orphan_tasks()
        self.nav_refresh_history()

        if self.settings.ui.restore_session:
            for raw in (self.session.get("tabs") or [])[:12]:
                path = Path(raw)
                if path.exists():
                    self.tabs.open_file(path)

        # Початковий вид: діалог або робоча область (як зберіг користувач).
        self._view = ""
        self.set_view(getattr(self.settings.ui, "view", "chat"))

        self._sync_rail_state()
        self._refresh_context()
        self._update_queue_badge()
        # Прибираємо рушії, що лишились від попереднього запуску IDE. Якщо
        # програма закрилась аварійно, вони досі тримають відеопам'ять —
        # і користувач бачить «щось грузить відеокарту» ще до старту моделі.
        # Робимо у фоні, щоб не затримувати перший кадр.
        threading.Thread(target=self._cleanup_orphans_quietly, daemon=True,
                         name="cleanup-orphans").start()
        # ── Порядок запуску: спершу МОДЕЛЬ, потім MCP ─────────────────────
        # Раніше MCP стартував через 400 мс, а автозапуск моделі — через
        # 900 мс: MCP піднімався ДО моделі й міг падати саме через це
        # (сервер, що чекає модель, не встигав). Тепер автозапуск іде
        # першим, а MCP — з ``_after_auto_setup``, коли модель уже готова.
        #
        # Якщо автозапуск вимкнено або моделі немає, ``_after_auto_setup``
        # усе одно викличе ``_load_mcp_async``: MCP не має чекати вічно.
        self.after(400, self._auto_setup_in_background)
        self.after(2600, self._load_mcp_if_not_started)
        self._queue_pump()
        # Простій: у неавтономному режимі модель віддає пам'ять відеокарти,
        # коли користувач не працює. Тік легкий (раз на 20 с).
        self._idle_tick()
        if not self.settings.first_run_done:
            self.after(600, self.open_first_run)
        elif not self.has_project():
            # Проєкту ще не вибрано: замість порожнього чату показуємо
            # екран вибору теки — агент не може працювати без неї.
            self.after(120, self._show_project_gate)
        else:
            # Стартовий екран показуємо лише коли в активній сесії ще немає
            # жодного повідомлення. Якщо історія є — одразу відновлюємо чат,
            # інакше welcome-оверлей перекриває стрічку і «історія зникає».
            active = self.chat_store.active()
            if active is not None and active.message_count:
                self.open_chat(active.id)
            else:
                self.after(120, self.show_welcome)

    def _project_root(self) -> Optional[Path]:
        """Тека проєкту для панелей — або ``None``, поки її не вибрано.

        Панелі «Зміни» й провідник раніше брали ``settings.workspace``
        напряму. Оскільки там типово домашня тека, вони сканували
        ``C:\\Users\\<ім'я>`` і показували ``AppData`` та службові файли.
        """
        if not self.has_project():
            return None
        try:
            return Path(self.settings.workspace)
        except (TypeError, ValueError):
            return None

    def set_project(self, path: str) -> None:
        """Показати робочий проєкт у бічній панелі, шапці й пігулці чату."""
        name = Path(path).name if path else ""
        try:
            self.project_label.configure(text=name or "не обрано")
        except (tk.TclError, AttributeError):
            pass
        try:
            self.header.set_workspace(name)
        except (tk.TclError, AttributeError):
            pass
        # Пігулка над полем вводу показує ту саму теку: людина пише задачу
        # й бачить, у якій теці працюватиме агент, не дивлячись у шапку.
        try:
            self.chat.set_workspace(name, path=str(path or ""))
        except (tk.TclError, AttributeError):
            pass

    def _active_chat_id(self) -> str:
        """Ідентифікатор активного чату (``""`` — чернетка або чату немає)."""
        try:
            return str(getattr(self.chat_store, "active_id", "") or "")
        except AttributeError:
            return ""

    def _adopt_orphan_tasks(self) -> int:
        """Прив'язати задачі без власника до активного чату.

        До виправлення кроки плану й задачі автономного режиму додавались
        без ``chat_id`` — після видалення чату вони лишались у черзі
        «сиротами» й висіли в панелі «Автоматизації» (саме це видно на
        скріншоті користувача: три задачі, які мали зникнути з чатом).

        Тепер кожна нова задача має власника; старі дістають активний чат,
        щоб видалення чату прибирало й їх.
        """
        chat = self.chat_store.active()
        if chat is None:
            return 0
        adopted = self.task_queue.adopt_orphans(chat.id)
        if adopted:
            LOG.info("Прив'язано задач без чату до %s: %s", chat.id, adopted)
            self._update_queue_badge()
        return adopted

    def nav_refresh_history(self) -> None:
        """Оновити список сесій у бічній панелі."""
        try:
            self.chat_list.refresh()
        except (tk.TclError, AttributeError):
            pass
        try:
            self.chat_list.set_active(getattr(self.chat_store, "active_id", ""))
        except (tk.TclError, AttributeError):
            pass

    def show_welcome(self) -> None:
        """Показати стартовий екран запиту (вибір теки або перший запит)."""
        if not getattr(self, "_welcome_shown", False):
            self._build_welcome()
        try:
            self.welcome.pack(fill="both", expand=True)
            self.welcome.set_workspace(self.settings.workspace)
            self.welcome.set_model(self.settings.llm.model)
            self.workspace_host.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.workspace_host.lift()
        except (tk.TclError, AttributeError):
            pass
        self._welcome_shown = True

    def hide_welcome(self) -> None:
        self._hide_welcome()

    # ── стартовий екран ────────────────────────────────────────────────────
    def _build_welcome(self) -> None:
        """Великий екран запиту — те, що видно одразу після запуску."""
        self.welcome = welcome.WelcomeScreen(
            self.workspace_host,
            self.theme,
            on_submit=self._start_from_welcome,
            on_open_folder=self.open_folder_dialog,
            on_hint=self._on_welcome_hint,
            workspace=self.settings.workspace,
            model_label=self.settings.llm.model,
        )
        self.welcome.pack(fill="both", expand=True)
        self._welcome_shown = True
        # Перший запуск без жодного відкритого файлу — показуємо саме запит,
        # а не порожній редактор.
        return None

    def _hide_welcome(self) -> None:
        # Хост знімаємо завжди, навіть якщо прапорець уже скинуто: оверлей
        # міг лишитись від попереднього показу (напр. після відкриття чату
        # з історією), і тоді він перекриває стрічку діалогу.
        if getattr(self, "_welcome_shown", False):
            try:
                self.welcome.pack_forget()
            except (tk.TclError, AttributeError):
                pass
        try:
            self.workspace_host.place_forget()
        except tk.TclError:
            pass
        self._welcome_shown = False

    def _start_from_welcome(self, text: str) -> None:
        """Перший запит зі стартового екрана: відкриваємо робочу область.

        Спершу перевіряємо теку проєкту й лише потім ховаємо стартовий екран:
        інакше запит без проєкту забирав екран, нічого не надсилав, і
        користувач лишався перед порожнім чатом без пояснення.
        """
        if not self.has_project():
            # Стартовий екран лишається на місці — він і є вибором теки.
            # Текст запиту не втрачаємо: користувач одразу його побачить.
            try:
                self.welcome.set_text(text)
            except (tk.TclError, AttributeError):
                pass
            self._show_project_gate(
                reason="Чат відкриється, щойно буде вибрано теку проєкту.")
            self.set_status("Спершу вибери папку проєкту — без неї агенту ніде працювати.")
            return
        self._hide_welcome()
        self._ensure_chat()
        self.show_chat(True)
        self.chat._send(text)

    def _on_welcome_hint(self, title: str, _prompt: str) -> None:
        self.set_status(f"Підказка: {title}")

    def _ensure_owner_chat(self) -> str:
        """Гарантувати СПРАВЖНІЙ запис чату й повернути його ``id``.

        Навіщо окремий метод. ``_ensure_chat()`` не годиться: при старті
        програми чат перебуває в стані «чернетка» (``_pending_chat``), і
        ``_ensure_chat`` лише ПЕРЕКОНУЄТЬСЯ, що така чернетка є — запис у
        сховищі не створюється, ``chat_store.active_id`` лишається
        порожнім.

        Наслідок заміряний у живому прогоні (``check_full_cycle``, чиста
        тека):

            20:10:29,856  Завдання розбито на 6 кроків
            20:10:29,922  Створено чат 9012cbb3715c на перше повідомлення
            готово за 9 с: {'done': 1, 'pending': 5, 'errors': 0}

        Кроки народились із ``chat_id=""`` (сироти), а насос черги їх не
        прив'язує: ``_adopt_orphan_tasks`` вимагає НЕПОРОЖНІЙ активний чат.
        Черга ставала назавжди — без помилок, просто тиша.

        Тепер кроки отримують власника до створення: якщо чат — чернетка,
        вона перетворюється на справжній запис (``_ensure_pending_chat``).
        """
        owner = self._active_chat_id()
        if owner:
            return owner
        try:
            # Чернетка → справжній запис. Саме цей метод створює ``chat.id``
            # на перше повідомлення, тож порожніх сесій у списку не буде.
            self._ensure_pending_chat()
        except Exception:  # noqa: BLE001 - чат не має ламати планування
            LOG.debug("Запис чату не створено", exc_info=True)
        owner = self._active_chat_id()
        if not owner:
            try:
                self._ensure_chat()
            except Exception:  # noqa: BLE001
                LOG.debug("Чат не створено", exc_info=True)
            owner = self._active_chat_id()
        return owner

    def _ensure_chat(self) -> None:
        """Гарантувати активний чат — але лише коли є робочий проєкт.

        Без вибраної теки чат не створюється: інакше на старті з'являвся б
        «Новий агент», прив'язаний до домашньої теки користувача, і перший
        ж запит правив би файли не там, де треба.

        Заодно прибираємо порожні чати, що лишились від попередніх сесій:
        раніше кожне натискання «×» створювало новий чат «про запас», і
        їх накопичувалось десятками (перевірено: 35 порожніх із 36).
        """
        dropped = self._prune_empty_chats()
        if dropped:
            LOG.info("Прибрано порожніх чатів: %s", dropped)
        if not self.has_project():
            return None
        if not getattr(self.chat_store, "chats", []):
            created = self.new_chat_session()
            return self.chat_store.active() if created else None
        try:
            chat = self.chat_store.ensure_active(workspace=str(self.settings.workspace),
                                                 model=self.settings.llm.model)
            # Контекст відновлюємо й тут: ``ensure_active`` обирає чат без
            # проходження через ``open_chat`` (напр. після вибору теки).
            if chat is not None and chat.id:
                self._load_chat_context(chat.id)
            self.chat_list.refresh()
            self._sync_chat_title()
            return chat
        except Exception:  # noqa: BLE001 - чат не має ламати старт
            return None

    def _prune_empty_chats(self) -> int:
        """Видалити чати без жодного повідомлення (лишити активний).

        Активний порожній чат — це нормальний стан «щойно створив і ще не
        написав»; його не чіпаємо.
        """
        store = self.chat_store
        try:
            active = str(getattr(store, "active_id", "") or "")
            keep = [chat for chat in store.chats
                    if chat.message_count or chat.id == active or chat.pinned]
            dropped = len(store.chats) - len(keep)
            if dropped:
                store.chats = keep
                store.save()
            return dropped
        except Exception:  # noqa: BLE001 - прибирання не має ламати старт
            LOG.debug("Не вдалось прибрати порожні чати", exc_info=True)
            return 0

    def _auto_setup_in_background(self) -> None:
        """Тихо підготувати проєкт: модель, профіль, скіли, сервер.

        Користувач запускає програму й одразу отримує робочу модель: якщо
        локальна модель уже є — IDE сама піднімає рушій; якщо є
        налаштований зовнішній сервер — використовує його.

        ── ЧОМУ МОДЕЛЬ ПЕРША, А ПРОФІЛЬ ПОТІМ ────────────────────────────
        Раніше порядок був зворотний: спершу ``build_plan`` (сканування
        робочої теки — до 4000 файлів, читання 400 із них по 64 КБ), і лише
        потім завантаження моделі. Сканування великого проєкту триває
        десятки секунд, і весь цей час модель НЕ вантажилась.

        ЗАМІРЯНО на справжньому запуску (``ide.log``):

            18:29:15  Стан моделі скинуто: перемикання на qwen2.5-coder…
            18:30:29  Адреса http://127.0.0.1:8080/v1 не слухає
            18:30:34  LLM недоступна: …[WinError 10061]

        Між цими рядками НЕМАЄ жодного «Модель завантажена», хоч саме
        завантаження триває 3.3 с (видно в тому ж лозі о 18:13:21).
        Користувач бачив «● МОДЕЛЬ ОФЛАЙН» і «локальна модель недоступна»,
        хоча файл лежить на диску, а рушій увімкнений.

        Тепер модель піднімається ПЕРШОЮ (3–4 с), а профіль і скіли
        готуються після неї — вони нікому не потрібні в першу секунду.
        """
        if self._setup_busy:
            return
        self._setup_busy = True
        root = Path(self.settings.workspace)

        def start_model() -> dict:
            """Підняти модель — найважливіше, тому без черги за скануванням."""
            result: dict = {}
            try:
                local = [p.name for p in hub.local_models()]
                engine_ok = runtime.engine_installed()
                alive = self._server_alive()
                plan = auto_setup.describe_model_setup(
                    self.settings, engine_installed=engine_ok,
                    local_models=local, server_alive=alive,
                )
                result["plan"] = plan
                # ── Порядок запуску моделі ─────────────────────────────────
                # ВЛАСНИЙ рушій — головний шлях: модель працює всередині
                # процесу IDE, без сторонніх сервісів. Для нього не потрібен
                # ні живий HTTP-сервер, ні ``llama-server``: достатньо
                # встановленого рушія й файлу моделі.
                #
                # Раніше умовою було ``not alive``, тобто нативний рушій
                # узагалі не пробувався, поки не налаштовано зовнішній
                # сервер — саме тому модель «не відповідала».
                wants_native = bool(getattr(self.settings.engine, "native", True))
                if (wants_native and engine_ok and local
                        and getattr(self.settings.engine, "auto_start", True)):
                    result["started"] = self._autostart_local_model(local)
                elif (not alive and engine_ok and local
                        and plan.action == "local-server-ready"
                        and getattr(self.settings.engine, "auto_start", True)):
                    result["started"] = self._autostart_local_model(local)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Підбір моделі не вдався: %s", exc, exc_info=True)
            return result

        def work() -> None:
            # 1. МОДЕЛЬ — першою, бо без неї агент не працює взагалі.
            result: dict = {}
            try:
                result.update(start_model())
            except Exception as exc:  # noqa: BLE001 - старт не має ламати вікно
                LOG.warning("Автозапуск моделі впав: %s", exc, exc_info=True)
            # Панель стану показуємо ОДРАЗУ після моделі: користувач бачить
            # «онлайн», не чекаючи, поки доскане проєкт.
            self._ui_call(self._after_auto_setup, dict(result))
            # 2. Профіль і скіли — після моделі, окремим оновленням.
            try:
                profile, proposals = auto_setup.build_plan(root)
                installed = auto_setup.install_proposals(root, proposals)
                result.update(profile=profile, installed=installed)
            except Exception as exc:  # noqa: BLE001 - автоналаштування не критичне
                LOG.warning("Профіль/скіли не вдались: %s", exc, exc_info=True)
                return
            self._ui_call(self._after_skills_ready, installed)

        threading.Thread(target=work, daemon=True).start()

    def _after_skills_ready(self, installed: list) -> None:
        """Скіли згенеровано — оновити панель і рядок стану (без моделі)."""
        try:
            self.skill_book.reload()
            self.skills_panel.refresh()
        except (tk.TclError, AttributeError):
            LOG.debug("Панель скілів не оновилась", exc_info=True)
        if installed:
            self.set_status(f"Автоналагодження · створено скілів: {len(installed)}")


    def _server_alive(self, *, fresh: bool = False) -> bool:
        """Чи відповідає налаштований OpenAI-сумісний сервер.

        ВАЖЛИВО про «зависання»: це мережевий запит із таймаутом 4 с, і
        викликати його з потоку інтерфейсу НЕ МОЖНА. Заміряно профілером:
        перший кадр застигав на 2.4 с саме тут (``_model_summary`` →
        ``_server_alive`` → ``list_models``).

        Тепер функція працює так:

        * повертає ОСТАННІЙ відомий стан (кеш), не чекаючи на мережу;
        * якщо стан невідомий або застарілий — запускає перевірку у ФОНІ,
          а панель оновиться, коли відповідь прийде.
        """
        cached = getattr(self, "_alive_cache", None)
        if cached is not None and not fresh \
                and (time.time() - cached[1]) < 5.0:
            return cached[0]
        # Спершу — фонова перевірка, і лише потім (за наявності) кеш.
        self._probe_server_alive()
        if cached is not None:
            return cached[0]
        return False

    def _probe_server_alive(self) -> None:
        """Перевірити сервер у фоновому потоці (інтерфейс не чекає)."""
        if getattr(self, "_alive_probe_running", False):
            return
        self._alive_probe_running = True
        base_url = str(self.settings.llm.base_url or "")
        api_key = str(self.settings.llm.api_key or "")

        def work() -> None:
            alive = False
            try:
                # Для вбудованого рушія ``list_models()`` показує ФАЙЛИ на
                # диску, а не завантажену модель: вона повертала «живий» навіть
                # тоді, коли модель не в пам'яті. ``model_answers`` для
                # ``native://`` питає саме рушій.
                if runtime.embedded_url(base_url):
                    alive = runtime.embedded_model_loaded()
                else:
                    from .llm_client import LLMClient

                    LLMClient(base_url, api_key=api_key, timeout=4).list_models()
                    alive = True
            except Exception:  # noqa: BLE001 - сервер може бути відсутній
                alive = False
            finally:
                self._alive_probe_running = False
            self._alive_cache = (alive, time.time())
            # Панель контексту має показати справжній стан, щойно дізнаємось.
            self._ui_call(self._after_alive_probe)

        threading.Thread(target=work, daemon=True, name="alive-probe").start()

    def _after_alive_probe(self) -> None:
        """Оновити підпис моделі після фонової перевірки сервера."""
        try:
            self._refresh_header()
        except Exception:  # noqa: BLE001 - підпис не має ламати вікно
            LOG.debug("Шапку не оновлено", exc_info=True)
        try:
            self.context.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _autostart_native_model(self) -> str:
        """Завантажити модель у ВЛАСНИЙ рушій (без llama-server).

        Модель береться з ``engine.native_model``; якщо там порожньо —
        найбільший локальний GGUF. Порожній рядок у відповіді означає
        «не вдалось», і тоді виклик переходить на сумісний шлях.
        """
        try:
            entries = self.native_runtime.manager.local_models()
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("Моделі для власного рушія недоступні: %s", exc)
            return ""
        wanted = str(getattr(self.settings.engine, "native_model", "") or "")
        # ── Назва моделі могла зберегтись у ``llm.model`` ──────────────────
        # Коли користувач обирав модель у хабі, назва писалась у
        # ``llm.model``, а ``engine.native_model`` лишався порожнім. Через
        # це автозапуск брав «найбільший файл», а не вибрану модель — а
        # якщо назва була втрачена, шапка показувала «модель не вибрана»
        # при сімox GGUF-файлах на диску. Тепер враховуємо обидва поля.
        if not wanted:
            wanted = str(getattr(self.settings.llm, "model", "") or "")
        chosen = None
        if wanted:
            chosen = next((item for item in entries
                           if item.key == wanted or Path(item.name).name == wanted
                           or item.path == wanted
                           or Path(item.path).stem == wanted), None)
        if chosen is None and entries:
            chosen = max(entries, key=lambda item: item.size_gb)
        if chosen is None:
            return ""
        # Параметри з налаштувань МУСЯТЬ застосовуватись: інакше користувач
        # вибирає «24 шари» чи «f16-кеш», а рушій мовчки бере авто.
        stored_layers = int(getattr(self.settings.engine, "native_gpu_layers", -1))
        stored_cache = str(getattr(self.settings.engine, "native_cache_type", "") or "")
        stored_flash = str(getattr(self.settings.engine, "native_flash_attn", "auto") or "auto")
        try:
            info = self.native_runtime.load_model(
                chosen.path,
                ctx=int(getattr(self.settings.engine, "ctx_size", 0) or 0),
                gpu_layers=None if stored_layers == -1 else stored_layers,
                cache_type=stored_cache,
                flash_attn=stored_flash)
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("Власний рушій не завантажив модель: %s", exc)
            return f"{NATIVE_FAILURE_PREFIX}{exc}"[:120]
        self._on_native_model(info.get("path") or chosen.path)
        note = f" · ctx {info.get('context_actual', 0)}"
        return f"власний рушій: {chosen.key}{note}"
    def _stop_managed_server(self, *, reason: str = "") -> bool:
        """Зупинити попередній керований рушій, щоб не тримати VRAM двічі.

        Повертає True, якщо щось справді зупинили. Помилку не приховуємо:
        якщо процес не завершився, він далі тримає відеопам'ять, і
        користувач має про це дізнатись, а не шукати причину самотужки.
        """
        server = getattr(self, "_managed_server", None)
        if server is None:
            return False
        try:
            if not getattr(server, "running", False):
                self._managed_server = None
                return False
        except Exception:  # noqa: BLE001 - стан процесу може бути недоступний
            LOG.debug("Стан рушія не прочитано", exc_info=True)
        try:
            server.stop()
        except Exception as exc:  # noqa: BLE001 - показуємо причину
            LOG.warning("Рушій не зупинився (%s): %s", reason, exc,
                        exc_info=True)
            self.set_status(f"Не вдалось зупинити попередній рушій: {exc}")
            return False
        self._managed_server = None
        LOG.info("Попередній рушій зупинено: %s", reason or "перезапуск")
        return True

    def _autostart_local_model(self, local_names: list[str]) -> str:
        """Підняти модель при старті IDE.

        Два шляхи, і вибір між ними зберігається в налаштуваннях:

        * ``engine.native`` — ВЛАСНИЙ рушій (``llama.dll`` у цьому процесі);
        * інакше — сумісний ``llama-server`` (як було раніше).

        Повертає короткий текст результату для панелі стану.
        """
        if getattr(self.settings.engine, "native", False):
            native = self._autostart_native_model()
            # УВАЖНО: помилка тут теж непорожній рядок. Раніше ``if native:
            # return native`` вважав ПОВІДОМЛЕННЯ ПРО ПОМИЛКУ успіхом, і
            # фолбек на llama-server не виконувався взагалі: користувач
            # лишався без моделі, хоч робочий шлях був поруч.
            if native and not native.startswith(NATIVE_FAILURE_PREFIX):
                return native
            if native:
                LOG.warning("Власний рушій не стартував (%s) — пробую llama-server",
                            native)
            else:
                LOG.warning("Власний рушій не стартував — пробую llama-server")
        from .model_hub import models_dir

        chosen = self.settings.engine.model_path or ""
        path = Path(chosen) if chosen and Path(chosen).exists() else None
        if path is None:
            preferred = self.settings.llm.model
            candidates = [models_dir() / name for name in local_names]
            for candidate in candidates:
                if preferred and preferred in candidate.name:
                    path = candidate
                    break
            if path is None:
                # Найбільша модель — зазвичай найрозумніша, яку вже скачали.
                path = max(candidates, key=lambda p: p.stat().st_size if p.exists() else 0)
        if not path or not path.exists():
            return "немає файлу моделі"

        try:
            profile = hardware.detect()
            choice = self.chat_panel_choice(path)
            # ── Один рушій, а не два ───────────────────────────────────────
            # ЗАМІРЯНО ЖИВИМ ПРОГОНОМ: після вивантаження через простій
            # ``launch_with_recovery`` підняв НОВИЙ сервер на 8081 (8080 ще
            # не встиг звільнитись), а ``settings.llm.base_url`` на мить
            # лишався на 8080. Два процеси ``llama-server`` одночасно
            # тримали VRAM: 7.7 + 7.7 ГБ на картці 12 ГБ.
            #
            # Тепер старий керований сервер зупиняємо ПЕРЕД запуском нового.
            self._stop_managed_server(reason="перезапуск перед підйомом моделі")
            # ── Зір: приєднуємо візуальний проєктор, якщо він є ────────────
            # Без ``--mmproj`` мультимодальна модель НЕ бачить зображень:
            # llama.cpp приймає картинку в запиті, але модель її не читає.
            projector = hub.vision_projector_for(path)
            # ── Запуск із автоматичним відновленням ────────────────────────
            # Раніше тут був один-єдиний шанс: якщо GPU не впорався з
            # контекстом, агент писав «сервер не піднявся» і лишав
            # користувача без моделі. Тепер ``launch_with_recovery`` сам
            # зменшує контекст і offload, аж до чистого CPU, і повертає
            # справжню причину, якщо не допомогло жодне.
            servers, detail = runtime.launch_with_recovery(
                path,
                choice=choice,
                profile=profile,
                alias=path.stem,
                mmproj_path=str(projector) if projector else "",
                on_status=lambda text: self._ui_call(self.set_status, text),
            )
            if not servers:
                return f"сервер не піднявся: {detail[:160]}"
            server = servers[-1]
            self._managed_server = server
            base_url = server.base_url
            used_plan = server.config.plan
            self.settings.llm.base_url = base_url
            self.settings.llm.model = path.stem
            self.settings.llm.api_key = runtime.MANAGED_API_KEY
            self.settings.engine.managed = True
            self.settings.engine.model_path = str(path)
            self.settings.engine.port = server.config.port
            self.settings.engine.ctx_size = int(
                (used_plan.ctx_size if used_plan else 0) or 0)
            self.settings.save()
            # Смуга статистики має показувати реальне вікно контексту.
            self._context_limit = int((used_plan.ctx_size if used_plan else 0) or 0)
            self._ui_call(self._apply_context_limit)
            # ── Порт міг змінитись (8080 зайнятий) ─────────────────────────
            # Саме тут народжувалась розбіжність «інтерфейс показує одну
            # адресу, а запити йдуть на іншу». Стан сервера скидаємо й
            # опитуємо ЗАНОВО за новою адресою — тоді і вікно, і агент
            # бачать той самий порт і те саме вікно контексту.
            try:
                self.server_state.set_local(running=True)
                self.server_state.invalidate(reason="модель запущено")
                self.server_state.refresh(background=True)
            except (AttributeError, tk.TclError):
                LOG.debug("Стан сервера не оновлено після запуску моделі",
                          exc_info=True)
            self._invalidate_model_state(reason="модель запущено")
            # Прапорець зору для агента: передавати знімки як зображення
            # можна ЛИШЕ тоді, коли сервер справді запущено з проєктором.
            try:
                self.agent.vision_enabled = bool(projector)
            except AttributeError:
                pass
            note = (f" · зір: {projector.name}" if projector else "")
            return f"модель запущено: {path.stem}{note}"
        except Exception as exc:  # noqa: BLE001 - показуємо причину
            LOG.warning("Автозапуск моделі не вдався: %s", exc, exc_info=True)
            return f"автозапуск не вдався: {exc}"

    def chat_panel_choice(self, path: Path | str):
        """Оцінити модель за назвою файлу (для параметрів запуску)."""
        # Публічний метод: сюди можуть прийти рядки з налаштувань і панелей.
        path = Path(path)
        name = path.name.lower()
        for token, params, layers in (("0.5b", 0.5, 24), ("1.5b", 1.5, 28), ("3b", 3.0, 36),
                                      ("4b", 4.0, 36), ("7b", 7.0, 28), ("8b", 8.0, 32),
                                      ("14b", 14.0, 48), ("32b", 32.0, 64), ("70b", 70.0, 80)):
            if token in name:
                size_gb = params * 0.62
                return hardware.ModelChoice(str(path.parent), path.name, path.stem,
                                            params, size_gb, 0.0, "", layers)
        size_gb = max(0.5, path.stat().st_size / 2**30) if path.exists() else 2.0
        return hardware.ModelChoice(str(path.parent), path.name, path.stem,
                                    max(1.0, size_gb / 0.62), size_gb, 0.0, "", 32)

    def _confirm_model_online(self, detail: str = "") -> None:
        """Перевірити ФАКТИЧНО, чи модель відповідає, і показати правду.

        Навіщо окремий метод. Після автозапуску рушій міг піднятись на
        ІНШОМУ порту (8080 зайняв Steam → 8081), і ``llm.base_url``
        лишався старим. Статус у шапці при цьому показував «ОФЛАЙН», хоч
        модель працювала — саме це виглядало як «модель не стартує».

        Метод узгоджує адресу й ставить статус за РЕАЛЬНОЮ відповіддю
        сервера, а не за наявністю назви моделі.
        """
        self._reconcile_server_url()
        url = str(self.settings.llm.base_url or "")
        key = str(self.settings.llm.api_key or "")
        try:
            # ``model_answers``, а не ``server_responds``: для вбудованого
            # рушія (``native://blackchpok``) HTTP-перевірки не існує, і
            # саме через це шапка показувала «● МОДЕЛЬ ОФЛАЙН» на живій
            # моделі (заміряно: engine.loaded=True, ctx 32768, GPU 48).
            online = runtime.model_answers(url, api_key=key, timeout=1.5)
        except Exception:  # noqa: BLE001 - перевірка не має ламати старт
            online = False
        try:
            self.header_bar.set_model_status(
                online, detail=(f"{self.settings.llm.model} · {url}"
                                if online else f"{detail or 'сервер не відповідає'}"))
        except (tk.TclError, AttributeError):
            pass
        try:
            self.chat.set_online(online, detail if online else "")
        except (tk.TclError, AttributeError):
            pass
        if online:
            LOG.info("Модель онлайн: %s @ %s", self.settings.llm.model, url)
        else:
            LOG.warning("Модель офлайн після автозапуску: %s", detail[:160])

    def _after_auto_setup(self, result: dict) -> None:
        """Стан після спроби підняти модель (скіли приходять окремо).

        ``installed`` тут може бути порожнім: скіли генеруються ПІСЛЯ моделі
        й показуються через :meth:`_after_skills_ready`. Раніше все робилось
        одним викликом, і модель чекала, поки доскане проєкт.
        """
        self._setup_busy = False
        installed = result.get("installed") or []
        plan = result.get("plan")
        started = str(result.get("started") or "").strip()
        parts: list[str] = []
        if installed:
            parts.append(f"створено скілів: {len(installed)}")
        if plan is not None:
            parts.append(f"модель: {plan.action}")
            if getattr(plan, "note", ""):
                self._setup_note = plan.note
        # ── Результат АВТОЗАПУСКУ моделі ──────────────────────────────────
        # ``result["started"]`` записувався у фоні, але ніде не читався:
        # причина невдачі автозапуску губилась, і користувач бачив лише
        # «модель: local-server-ready», хоч сервер так і не піднявся.
        if started:
            if started.startswith(NATIVE_FAILURE_PREFIX) or started.startswith("сервер не піднявся"):
                parts.append(f"запуск: {started[:120]}")
                self.set_status("Автозапуск моделі не вдався · " + started[:160])
                try:
                    self.header_bar.set_model_status(False, detail=started[:120])
                except (tk.TclError, AttributeError):
                    pass
            else:
                parts.append(f"модель піднято: {started[:60]}")
                # ── Головне: після успішного автозапуску показати ОНЛАЙН ──
                # Дефект, через який користувач бачив «модель не стартує»:
                # рушій піднімався (у лозі видно «Старт рушія» й завантаження
                # моделі), але статус у шапці лишався «ОФЛАЙН», бо після
                # автозапуску ніхто не оновлював ні стан, ні адресу. Тепер
                # перевіряємо ФАКТИЧНО й показуємо правду.
                self._confirm_model_online(started)
        if parts:
            self.set_status("Автоналагодження · " + " · ".join(parts))
        # ── MCP після моделі ─────────────────────────────────────────────
        # Вимога порядку: спершу модель, потім MCP. Раніше MCP стартував
        # через 400 мс, а автозапуск моделі — через 900 мс, тобто MCP
        # піднімався ДО моделі й міг упасти саме через це.
        if started and not started.startswith(NATIVE_FAILURE_PREFIX) \
                and "не піднявся" not in started:
            self.after(200, self._load_mcp_async)
        # Стартовий екран має показати реальний стан скілів і моделі.
        if getattr(self, "_welcome_shown", False):
            try:
                self.welcome.set_workspace(self.settings.workspace)
                self.welcome.set_model(self.settings.llm.model)
            except tk.TclError:
                pass

    # ── сайт у вбудованому браузері ────────────────────────────────────────
    def open_site(self) -> None:
        """Показати сайт проєкту у вбудованому браузері й запустити його.

        Сторінка живе в **одній** колонці Live Preview праворуч. Раніше тут
        додатково відкривалась вкладка «🌐 Сайт» знизу, і виходило два
        незалежні вбудовані браузери для тієї самої адреси: два процеси
        Chromium, дві копії сторінки й заплутаний стан (кнопка «■» в одній
        панелі не зупиняла другу).
        """
        self.toggle_preview(True)
        if not self.app.running:
            self.start_site()
        else:
            self.live_preview.open_url(self.app.url)
            self.set_status(self.app.describe())

    def start_site(self) -> None:
        """Запустити застосунок проєкту і показати його у вбудованому браузері.

        Важливо йти через ``live_preview.start_server``, а не кликати
        ``self.app.start()`` напряму: контролер лише піднімає сервер, а
        показ сторінки у вбудованому вікні робить саме колонка прев'ю.
        Раніше через це «Запустити сайт» піднімало сервер, але вікно
        лишалось порожнім — сторінка не відкривалась.
        """
        self.toggle_preview(True)
        self.live_preview.start_server()
        controller = self.app
        if controller.running:
            self.set_status(controller.describe())
        else:
            self.set_status("Сайт не запущено — перевір стек проєкту.")

    def stop_site(self) -> None:
        # Зупиняємо через колонку прев'ю: вона тримає і сервер, і браузер,
        # і сама прибирає за собою вбудоване вікно.
        self.live_preview.stop_all()
        self.set_status("Застосунок зупинено.")

    def reload_site(self) -> None:
        self.live_preview.reload_page()

    # ── вбудований браузер для довільних адрес ─────────────────────────────
    def open_url_in_browser(self, url: str) -> bool:
        """Відкрити адресу у вбудованому браузері IDE (НЕ в браузері ПК).

        Це єдина точка входу для всіх модулів: панель змін, хаб моделей,
        налаштування й майстер першого запуску кличуть її замість
        ``webbrowser.open``. Тому клік «Встановити git» більше не викидає
        користувача з застосунку.

        Порядок дій:

        1. нормалізувати адресу (``git-scm.com`` → ``https://git-scm.com``);
        2. показати колонку Live Preview (там живе вбудований браузер);
        3. показати рядок адреси — щоб можна було піти далі самому;
        4. відкрити сторінку.
        """
        target = browser_panel.normalise_url(url)
        if not target:
            return False
        if not browser_panel.is_showable(target):
            self.set_status(f"Адресу {target} вбудоване вікно не відкриває.")
            return False
        self.toggle_preview(True)
        try:
            self.live_preview.show_address_bar()
        except (tk.TclError, AttributeError):
            pass
        ok = False
        try:
            ok = bool(self.live_preview.open_url(target))
        except (tk.TclError, AttributeError) as exc:
            LOG.debug("Вбудований браузер недоступний: %s", exc, exc_info=True)
        if not ok:
            # Браузера в системі може не бути зовсім — тоді чесно кажемо.
            self.set_status("Не вдалось відкрити сторінку у вбудованому браузері. "
                            f"Адреса: {target}")
            return False
        self.set_status(f"Відкрито у вбудованому браузері: {target}")
        return True

    def open_url_dialog(self) -> None:
        """Запитати адресу й показати її у вбудованому браузері."""
        from tkinter import simpledialog

        current = ""
        try:
            current = self.live_preview.inner.view.url or ""
        except (tk.TclError, AttributeError):
            current = ""
        url = simpledialog.askstring(
            "Відкрити адресу",
            "Адреса (локальний сайт або сторінка з інтернету):",
            initialvalue=current or "https://", parent=self)
        if url:
            self.open_url_in_browser(url)

    def open_local_page(self, path: Path) -> bool:
        """Показати локальний HTML-файл у вбудованому браузері."""
        target = browser_panel.file_url(path)
        if not target:
            self.set_status(f"Файл не знайдено: {path}")
            return False
        return self.open_url_in_browser(target)


    def apply_theme_mode(self, mode: str) -> None:
        """Перемкнути світлу/темну тему й зберегти вибір.

        Вибір одразу пишеться в ``settings.json``, тож наступний запуск
        відкривається в тій самій темі. Окрім кольорів віджетів
        перемальовується й підсвітка синтаксису: теги в ``Text`` тримають
        власні кольори й самі не оновлюються.
        """
        theme.switch_mode(mode, root=self, theme_obj=self.theme)
        self.settings.ui.theme = theme.current_mode()
        self.settings.save()
        try:
            self.chat.apply_font()
        except (tk.TclError, AttributeError):
            pass
        try:
            # Скидаємо кеш «останньої теми» стрічки й перемальовуємо картки.
            self.chat.retheme()
        except (tk.TclError, AttributeError):
            pass
        try:
            # Теги підсвітки в редакторах беруть кольори з theme.SYNTAX_COLORS.
            self.tabs.apply_settings()
        except (tk.TclError, AttributeError):
            pass
        try:
            self._update_theme_menu()
        except (tk.TclError, AttributeError):
            pass
        self.set_status(f"Тема: {'темна' if theme.current_mode() == 'dark' else 'світла'} "
                        f"(збережено).")

    def _update_theme_menu(self) -> None:
        """Показати в меню, яка тема активна (радіо-галочка)."""
        var = getattr(self, "_theme_var", None)
        if var is not None:
            try:
                var.set(theme.current_mode())
            except tk.TclError:
                pass

    def _save_theme(self) -> None:
        """Зберегти поточну тему в налаштуваннях (без перемикання)."""
        self.settings.ui.theme = theme.current_mode()
        self.settings.save()
        self.set_status(f"Тему збережено: {'темна' if theme.current_mode() == 'dark' else 'світла'}.")

    def show_ast_tree(self, path: Path | str | None = None) -> None:
        """Показати сире AST-дерево поточного файлу.

        ``path`` — необовʼязковий: так само, як ``open_path``, метод
        приймає шлях від палітри, дерева файлів і контекстного меню.
        Раніше виклик зі шляхом падав ``TypeError`` (перевірено
        ``tools/probe_str_args.py``): усі публічні входи мусять розуміти
        рядок, бо саме рядки приходять із JSON і віджетів.
        """
        from . import ast_index

        editor = self._editor_for(path)
        if editor is None:
            self.set_status("Спочатку відкрий файл.")
            return
        result = ast_index.analyse(editor.get_text())
        if result.problem is not None:
            self.show_text_window(
                f"AST · {editor.filename}",
                f"Файл не розбирається — рядок {result.problem.line}:\n"
                f"{result.problem.short}\n\n(виправ помилку, щоб побачити дерево)",
            )
            return
        rows = ast_index.tree_rows(result.tree, limit=600)
        lines = [f"AST для {editor.filename}", "=" * 40,
                 f"Символів: {len(result.symbols)} · вузлів: {len(rows)} · "
                 f"розбір: {result.elapsed:.1f} мс", ""]
        for depth, name, snippet in rows:
            lines.append(f"{'  ' * depth}{name}" + (f"  {snippet}" if snippet else ""))
        self.show_text_window(f"AST · {editor.filename}", "\n".join(lines))

    def show_symbols_report(self, path: Path | str | None = None) -> None:
        """Повний звіт про символи: підписи, доку, декоратори."""
        from . import ast_index

        editor = self._editor_for(path)
        if editor is None:
            return
        result = ast_index.analyse(editor.get_text())
        lines = [f"Символи {editor.filename}", "=" * 40, result.metrics.summary, ""]
        if result.problem is not None:
            lines.append(f"⚠ рядок {result.problem.line}: {result.problem.short}")
            lines.append("")
        for sym in result.symbols:
            indent = "  " * sym.depth
            lines.append(f"{indent}{sym.label}  — рядок {sym.line}"
                         f"–{sym.end_line or sym.line}")
            if sym.decorators:
                lines.append(f"{indent}    декоратори: {', '.join(sym.decorators)}")
            if sym.docstring:
                lines.append(f"{indent}    {sym.docstring}")
        for imported in result.imports:
            lines.append(f"{imported.icon} {imported.name} — рядок {imported.line}")
        self.show_text_window(f"Символи · {editor.filename}", "\n".join(lines))

    def show_diff_for(self, path: Path) -> None:
        """Показати diff між резервною копією файлу та поточною версією."""
        path = Path(path)
        backup = Path(str(path) + ".bak")
        try:
            new_text = diff_stats.read_text_safe(path) or ""
            old_text = diff_stats.read_text_safe(backup) or ""
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Не вдалось прочитати diff: {exc}")
            return
        self.show_text_window(
            f"diff · {path.name}",
            diff_stats.make_unified_diff(old_text, new_text, path.name),
        )

    def show_text_window(self, title: str, text: str) -> None:
        """Просте вікно з моноширинним текстом (diff, результат, журнал)."""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=theme.BG)
        win.transient(self)
        box = tk.Text(win, wrap="none", bg=theme.BG_EDITOR, fg=theme.FG, bd=0,
                      highlightthickness=0, font=self.theme.mono_small, padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, colour in (("add", theme.SUCCESS), ("del", theme.ERROR)):
            box.tag_configure(tag, foreground=colour)
        for line in (text or "(порожньо)").splitlines():
            tag = "add" if line.startswith("+") and not line.startswith("+++") else (
                "del" if line.startswith("-") and not line.startswith("---") else "")
            box.insert("end", line + "\n", tag)
        box.configure(state="disabled")
        footer = tk.Frame(win, bg=theme.BG)
        footer.pack(fill="x", padx=8, pady=(0, 8))
        widgets.Chip(footer, "Копіювати", lambda: self._copy_text(text)).pack(side="left")
        widgets.Chip(footer, "Закрити", win.destroy).pack(side="right")
        # Вікно має бути в межах екрана, а не «900x600 з лівого верхнього кута».
        widgets.place_window(win, width=900, height=600, center_on=self)

    def _copy_text(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text or "")
        except tk.TclError:
            pass

    def _show_side_initial(self) -> None:
        # Список чатів має бути завжди відкритий зліва.
        self.show_side("chats")

    def _open_welcome(self) -> None:
        """Порожній проєкт: показати коротку довідку замість чорного екрана."""
        editor = self.tabs.new_file()
        editor.filename = "Ласкаво просимо.md"
        editor.set_text(WELCOME_TEXT)
        self.tabs.rename_tab(editor, "Ласкаво просимо")
        editor.set_readonly(True)

    # ── MCP ────────────────────────────────────────────────────────────────
    def _ui_call(self, func, *args) -> None:
        """Виконати оновлення інтерфейсу з головного потоку.

        Фонові потоки не мають права кликати ``after()`` безпосередньо:
        tkinter не потокобезпечний, і в Release-збірці це падає з
        «main thread is not in main loop». Тому лише складаємо в чергу.
        """
        self._ui_queue.put((func, args))


    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _drain_ui(self) -> None:
        try:
            for _ in range(100):
                try:
                    func, args = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    func(*args)
                except tk.TclError:
                    pass
                except Exception as exc:  # noqa: BLE001 - одне оновлення не має
                    # валити весь цикл: інакше наступні оновлення губляться.
                    LOG.warning("Помилка оновлення інтерфейсу: %s", exc, exc_info=True)
        finally:
            try:
                if self.winfo_exists():
                    self._ui_after = (self.after(80, self._drain_ui) if self._timer_alive() else None)
            except tk.TclError:
                self._ui_after = None

    def _load_mcp_if_not_started(self) -> None:
        """Запустити MCP, якщо автозапуск моделі його не запустив.

        Порядок життєвого циклу: модель → inference → MCP. Основну спробу
        робить ``_after_auto_setup``; цей виклик — запобіжник на випадок,
        коли авторозкладка моделі вимкнена або триває довше: MCP не має
        чекати вічно, але й не має стартувати РАНІШЕ за модель.
        """
        if getattr(self, "_mcp_loaded", False) or self._mcp_busy:
            return
        self._load_mcp_async()

    def _load_mcp_async(self) -> None:
        if not self.settings.mcp.enabled or self._mcp_busy:
            return
        # Позначаємо спробу: далі або ``_after_mcp``, або тихий вихід
        # (немає конфігів) — в обох випадках повторний автозапуск не потрібен.
        self._mcp_loaded = True
        root = Path(self.settings.workspace)
        paths = mcp_panel.workspace_config_paths(root)
        if not paths:
            return
        configs = mcp_client.McpManager.load_configs(paths)
        configs = [c for c in configs if c.name not in set(self.settings.mcp.servers)]
        if not configs:
            return
        self._mcp_busy = True
        self.set_status(f"Підключаю MCP-сервери: {len(configs)}…")
        # Наглядач має знати конфіги, щоб уміти перезапустити сервер.
        try:
            self.mcp_watcher.remember(configs)
        except Exception:  # noqa: BLE001 - наглядач не має ламати старт
            LOG.debug("Конфіги MCP не передано наглядачу", exc_info=True)

        def work() -> None:
            statuses = self.mcp_manager.start_all(configs)
            self._ui_call(self._after_mcp, statuses)

        threading.Thread(target=work, daemon=True).start()

    def _after_mcp(self, statuses: dict[str, str]) -> None:
        self._mcp_busy = False
        self._mcp_loaded = True
        running = sum(1 for state in statuses.values() if state == "працює")
        self.mcp_panel.refresh()
        self.set_status(f"MCP: працює {running} з {len(statuses)} · інструментів "
                        f"{len(self.mcp_manager.tool_catalog())}")
        # Після старту вмикаємо наглядач: він перевірятиме ЖИВІСТЬ серверів,
        # а не лише факт «initialize не впав». Без цього померлий сервер
        # лишався зі статусом «працює».
        if statuses and not self.mcp_watcher.running:
            try:
                self.mcp_watcher.start()
            except Exception:  # noqa: BLE001 - наглядач необов'язковий
                LOG.debug("MCP-наглядач не запустився", exc_info=True)

    def reload_mcp(self) -> None:
        if self._mcp_busy:
            return
        self._mcp_busy = True

        def work() -> None:
            try:
                self.mcp_manager.stop_all()
            finally:
                root = Path(self.settings.workspace)
                configs = mcp_client.McpManager.load_configs(mcp_panel.workspace_config_paths(root))
                configs = [c for c in configs if c.name not in set(self.settings.mcp.servers)]
                try:
                    self.mcp_watcher.remember(configs)
                except Exception:  # noqa: BLE001
                    LOG.debug("Конфіги MCP не оновлено", exc_info=True)
                statuses = self.mcp_manager.start_all(configs) if configs else {}
                self._ui_call(self._after_mcp, statuses)

        threading.Thread(target=work, daemon=True).start()

    # ── агент і модель ─────────────────────────────────────────────────────
    def _on_model_changed(self) -> None:
        model = self.settings.llm.model or "модель не вибрана"
        self.agent.llm_settings = self.settings.llm
        self.agent.agent_settings = self.settings.agent
        self.chat.set_online(bool(self.settings.llm.model))
        # ── Після зміни моделі ВСЕ старе стає недійсним ────────────────────
        # Вікно контексту, набір схем інструментів і стан сервера описували
        # ІНШУ модель. Раніше вони лишались, і агент надсилав промпт,
        # розрахований на попереднє вікно: це і давало обрив з'єднання
        # (``WinError 10054``) одразу після перемикання.
        self._invalidate_model_state(reason=f"перемикання на {model}")
        self._apply_context_limit()
        # ── ОДИН підпис в усіх місцях ─────────────────────────────────────
        # Раніше тут ставився лише підпис композера, тому пігулка сесії
        # （``session_header``）ЛИШАЛАСЬ «модель не вибрана» назавжди: її
        # оновлював тільки селектор моделі, а не старт. На скріншоті
        # користувача це виглядало як «дві різні моделі вибрані».
        self._sync_model_labels()
        self.set_status(f"Модель: {model} @ {self.settings.llm.base_url}")

    def _invalidate_model_state(self, *, reason: str = "") -> None:
        """Скинути все похідне від моделі: контекст, схеми, стан сервера.

        Це ОДНА точка інвалідації. Раніше кожне місце скидало своє (або не
        скидало нічого), і після перемикання моделі агент працював із
        застарілим вікном контексту.
        """
        self._ctx_limit_cache = None
        self._context_limit = 0
        try:
            self.server_state.invalidate(reason=reason)
        except (AttributeError, tk.TclError):
            LOG.debug("Стан сервера не скинуто", exc_info=True)
        try:
            self.agent.invalidate_tool_cache(reason=reason)
        except (AttributeError, tk.TclError):
            LOG.debug("Кеш інструментів не скинуто", exc_info=True)
        try:
            self.agent.set_requested_context(
                int(self.settings.engine.ctx_size or 0))
        except (AttributeError, tk.TclError):
            pass
        # Агент має ПЕРЕВИЗНАЧИТИ вікно з нового сервера, а не взяти старе.
        try:
            self.agent._context_window = None
            self.agent._context_budget = None
        except AttributeError:
            pass
        LOG.info("Стан моделі скинуто: %s", reason or "зміна моделі")

    def _on_server_state(self, state) -> None:
        """Оновити інтерфейс за узгодженим станом сервера.

        Викликається з фонового потоку опитування, тому всі дії з віджетами
        йдуть через :meth:`_ui_call`.
        """
        def apply() -> None:
            try:
                self._alive_cache = (bool(state.reachable), time.time())
            except AttributeError:
                pass
            # Контекст беремо ЗВІДСИ, а не з власного опитування: інакше
            # інтерфейс і агент знову показували б різні числа.
            if state.context and state.context != int(self._context_limit or 0):
                self._context_limit = int(state.context)
                self._ctx_limit_cache = (int(state.context), time.time())
                try:
                    self.chat.set_context_limit(int(state.context))
                    self.agent.set_context_limit(int(state.context))
                except (tk.TclError, AttributeError):
                    LOG.debug("Ліміт контексту не застосовано", exc_info=True)
            try:
                self._refresh_header()
                self.context.refresh()
            except (tk.TclError, AttributeError):
                LOG.debug("Панель не оновлено після стану сервера",
                          exc_info=True)
            # Користувач має бачити РОЗБІЖНІСТЬ, а не здогадуватись.
            if state.reachable and not state.model_matches:
                self.set_status(
                    f"Увага: сервер обслуговує «{state.model_loaded}», а в "
                    f"налаштуваннях «{state.model_configured}».")

        self._ui_call(apply)

    def _apply_context_limit(self) -> None:
        """Передати чату розмір вікна контексту для смуги статистики.

        ВАЖЛИВО про «зависання». Раніше тут БЕЗУМОВНО йшов мережевий запит
        до ``/props``. Якщо сервер не запущено, з'єднання висіло до таймауту
        (3 с), і інтерфейс застигав НА СТАРТІ — профілер показав 5.1 с на
        першому кадрі (з них 2.1 с тут). Тепер:

        * спершу беремо відоме число з налаштувань (без мережі взагалі);
        * мережу питаємо ЛИШЕ у фоні, а результат застосовуємо пізніше.

        Так старт ніколи не блокується мережею.
        """
        limit = int(getattr(self, "_context_limit", 0) or 0)
        if not limit:
            limit = int(self.settings.engine.ctx_size or 0)
        if not limit:
            # Числа немає ні в пам'яті, ні в налаштуваннях — питаємо
            # ``_server_context_limit``, який віддає КЕШ (мережі тут немає)
            # і сам ставить фонове опитування.
            limit = int(self._server_context_limit() or 0)
        if not limit:
            # Невідомо — показуємо типове й питаємо сервер у ФОНІ.
            limit = 8192
        try:
            self.chat.set_context_limit(limit)
            self.agent.set_context_limit(limit)
        except (tk.TclError, AttributeError):
            pass
        # ── Заявлене ≠ реальне ───────────────────────────────────────────
        # ``launch_with_recovery`` може сам зменшити контекст (щоб модель
        # влізла у VRAM): у налаштуваннях лишається 32768, а сервер працює
        # з 16384. Агент визначає СПРАВЖНЄ вікно сам (``/props``), тому
        # заявлене число передаємо йому лише як запасний варіант — інакше
        # він повірить 32768 і надішле завеликий промпт.
        try:
            self.agent.set_requested_context(int(self.settings.engine.ctx_size or 0))
        except (tk.TclError, AttributeError):
            pass

    def _probe_context_async(self) -> None:
        """Спитати контекст сервера у фоновому потоці (не блокуючи UI)."""
        if getattr(self, "_ctx_probe_running", False):
            return
        cached = getattr(self, "_ctx_limit_cache", None)
        if cached is not None and (time.time() - cached[1]) < 30.0:
            return                      # нещодавно вже питали
        self._ctx_probe_running = True

        def work() -> None:
            value = 0
            try:
                value = self._probe_server_context()
            except Exception:  # noqa: BLE001 - фон не має падати
                LOG.debug("Опитування контексту впало", exc_info=True)
            finally:
                self._ctx_probe_running = False
            if value:
                self._ui_call(self._apply_probed_context, value)

        threading.Thread(target=work, daemon=True,
                         name="ctx-probe").start()

    def _apply_probed_context(self, value: int) -> None:
        """Застосувати контекст, який повернув сервер (у головному потоці)."""
        if value <= 0:
            return
        self._ctx_limit_cache = (value, time.time())
        self._context_limit = int(value)
        try:
            self.chat.set_context_limit(int(value))
            self.agent.set_context_limit(int(value))
        except (tk.TclError, AttributeError):
            pass

    def _server_context_limit(self) -> int:
        """Спитати в запущеного сервера, з яким контекстом він працює.

        llama.cpp віддає ``/props`` із ``n_ctx``. Це єдине чесне джерело
        числа: у налаштуваннях може стояти «авто», а LM Studio чи Ollama
        мають власні значення.

        ВАЖЛИВО: результат КЕШУЄТЬСЯ, а сама функція НЕ викликається з
        інтерфейсу напряму — тільки з фонового потоку
        (:meth:`_probe_context_async`). Інакше перший кадр застигав до
        таймауту з'єднання (заміряно профілером: 2.1 с).
        """
        cached = getattr(self, "_ctx_limit_cache", None)
        if cached is not None and (time.time() - cached[1]) < 30.0:
            return cached[0]
        value = self._probe_server_context()
        self._ctx_limit_cache = (value, time.time())
        return value

    def _probe_server_context(self) -> int:
        """Вікно контексту з ЄДИНОГО джерела стану (без власного запиту).

        Раніше тут був окремий ``urllib``-запит до ``/props`` з таймаутом
        3 с — п'яте місце в проєкті, яке питало те саме. Через це інтерфейс
        і агент могли показати РІЗНІ числа для одного сервера: хто встиг
        спитати, той і правий.

        Тепер стан сервера збирає :mod:`blackchpok_ide.server_state`, і саме
        звідти береться число. Якщо свіжого немає — повертаємо 0 і
        запускаємо фонове опитування: інтерфейс не блокується мережею.

        ВАЖЛИВО для вбудованого рушія: ``server_state`` описує HTTP-сервер і
        про ``llama.dll`` у цьому процесі не знає НІЧОГО. Тому для нативного
        рушія число береться з самої моделі (``describe()["context_actual"]``)
        — це РЕАЛЬНЕ вікно, з яким рушій завантажився, а не заявлене в
        налаштуваннях.
        """
        # ── Вбудований рушій: єдине чесне джерело — завантажена модель ───
        native_limit = self._native_context_limit()
        if native_limit:
            return native_limit
        try:
            state = self.server_state.snapshot()
        except AttributeError:
            return 0
        if state.context and state.age <= server_state.STALE_SECONDS:
            return int(state.context)
        # Свіжого числа немає — питаємо у фоні, а поки що віддаємо відоме.
        try:
            if not state.reachable and not state.running:
                self.server_state.refresh(background=True)
        except (AttributeError, tk.TclError):
            LOG.debug("Фонове опитування контексту не запустилось", exc_info=True)
        return int(state.context or 0)

    def _native_context_limit(self) -> int:
        """Справжнє вікно контексту завантаженої моделі у власному рушії.

        Повертає 0, якщо рушій нічого не завантажив або він вимкнений —
        тоді діє звичайний шлях через ``server_state``.
        """
        if not bool(getattr(self.settings.engine, "native", True)):
            return 0
        try:
            engine = self.native_runtime.engine
        except AttributeError:
            return 0
        if not getattr(engine, "loaded", False):
            return 0
        model = getattr(engine, "model", None)
        if model is None:
            return 0
        try:
            described = model.describe()
        except Exception:                            # noqa: BLE001
            return 0
        # ``describe()`` віддає словник із фактичними числами рушія.
        if isinstance(described, dict):
            return int(described.get("context_actual")
                       or described.get("context") or 0)
        context = getattr(engine, "context", None)
        return int(getattr(context, "n_ctx", 0) or 0)

    def _apply_code_from_chat(self, code: str, key: str) -> None:
        editor = self.tabs.current()
        if not editor:
            editor = self.tabs.new_file()
        selection = editor.selected_text()
        if selection:
            editor.text.delete("sel.first", "sel.last")
        editor.insert_text(code)
        self.chat.set_busy(False)
        self.set_status("Код із чату вставлено в редактор. Перевір і збережи (Ctrl+S).")

    def send_to_agent(self, text: str, *, submit: bool = True) -> None:
        self.show_chat(True)
        if submit:
            self._set_agent_state("працює")
            self.chat._send(text)
        else:
            self.chat.input.delete("1.0", "end")
            self.chat.input.insert("1.0", text)
            self.chat.input.focus_set()

    def _editor_for(self, path: Path | str | None = None):
        """Редактор для дії: або відкритий файл за шляхом, або поточний.

        Публічні дії (AST, символи, надсилання агенту) викликають і з
        палітри, і з дерева файлів, і з контекстного меню — тобто зі
        шляхом. Раніше кожен такий метод брав лише ``self.tabs.current()``,
        і виклик зі шляхом падав ``TypeError``.
        """
        if path in (None, ""):
            return self.tabs.current()
        try:
            target = Path(path)
        except TypeError:
            return self.tabs.current()
        opened = self.tabs.open_file(target)
        return self.tabs.current() if opened else None

    def send_file_to_agent(self, path: Path | str | None = None) -> None:
        editor = self._editor_for(path)
        current = self.tabs.current_path()
        path_obj = Path(path) if path not in (None, "") else current
        if not editor:
            return
        name = path_obj.name if path_obj else "поточний файл"
        relative = (ws.relative_to_root(Path(self.settings.workspace), path_obj)
                    if path_obj else name)
        self.send_to_agent(
            f"Прочитай файл {relative} інструментом read_file і поясни, що він робить."
        )

    def explain_selection(self) -> None:
        editor = self.tabs.current()
        if not editor:
            return
        selection = editor.selected_text().strip()
        if not selection:
            self.set_status("Виділи текст, який треба пояснити.")
            return
        self.send_to_agent("Поясни цей код:\n\n```\n" + selection[:6000] + "\n```")

    def fix_selection(self) -> None:
        editor = self.tabs.current()
        path = self.tabs.current_path()
        if not editor or not path:
            return
        selection = editor.selected_text().strip()
        relative = ws.relative_to_root(Path(self.settings.workspace), path)
        prompt = (f"У файлі {relative} виправ проблему в цьому фрагменті, зміни внеси "
                  f"інструментом edit_file:\n\n```\n{selection[:4000]}\n```")
        self.send_to_agent(prompt)

    def new_chat(self) -> None:
        self.new_chat_session()

    # ── чати ───────────────────────────────────────────────────────────────
    def has_project(self) -> bool:
        """Чи вибрано робочу теку проєкту.

        Два випадки, які раніше зливалися в один:

        * ``workspace`` порожня або не існує — теки немає;
        * ``workspace`` дорівнює домашній теці — це стан «ще нічого не
          вибрано», бо саме туди підставляється тека за замовчуванням.

        Другий випадок не має блокувати назавжди: якщо користувач **свідомо**
        вибрав домашню теку, прапорець ``project_chosen`` це пам'ятає, і чат
        працює. Інакше кнопка «Вибрати папку» на вибір домашньої теки
        нічого б не змінювала — екран лишався б на місці.
        """
        path = str(self.settings.workspace or "").strip()
        if not path:
            return False
        root = Path(path)
        if not root.is_dir():
            return False
        try:
            is_home = root.resolve() == Path.home().resolve()
        except OSError:
            is_home = False
        if is_home and not getattr(self.settings, "project_chosen", False):
            return False
        return True

    def _show_project_gate(self, *, reason: str = "") -> None:
        """Показати екран вибору проєкту замість чату."""
        self._close_project_gate()
        gate = project_gate.ProjectGate(
            self.conversation_host, self.theme,
            on_pick=self.open_folder_dialog,
            on_create=self.create_project_folder,
        )
        gate.set_hint(reason)
        # Показуємо, з чим користувач працюватиме, і даємо продовжити з цією
        # ж текою: раніше екран лише просив вибрати папку, навіть якщо вона
        # вже вибрана — і «новий чат» щоразу вимагав шукати її заново.
        current = str(self.settings.workspace or "").strip()
        if current and Path(current).is_dir():
            gate.set_current(current, on_use=self._use_current_project)
        self.project_gate = gate
        # Екран показуємо поверх області діалогу: сама побудова віджета ще не
        # означає, що його видно, а без цього користувач бачив порожній чат
        # замість пояснення, чому нічого не працює.
        try:
            gate.place(relx=0, rely=0, relwidth=1, relheight=1)
            gate.lift()
        except tk.TclError:
            LOG.debug("Екран вибору проєкту не вдалося показати", exc_info=True)

    def _use_current_project(self) -> None:
        """Продовжити з уже вибраною текою (кнопка на екрані вибору)."""
        current = str(self.settings.workspace or "").strip()
        if not current or not Path(current).is_dir():
            self._show_project_gate(reason="Ця тека більше не існує — вибери іншу.")
            return
        # Свідоме підтвердження вибору: без прапорця домашня тека вважалась
        # би «нічого не вибрано» і екран повертався б знову.
        self.settings.remember_workspace(current)
        safe.call_quiet(self.settings.save)
        self._close_project_gate()
        self.new_chat_session()
        self.set_status(f"Працюю з текою: {current}")

    def _close_project_gate(self) -> None:
        gate = getattr(self, "project_gate", None)
        self.project_gate = None
        if gate is None:
            return
        try:
            gate.destroy()
        except tk.TclError:
            pass

    def _after_chats_cleared(self, removed: int) -> None:
        """Усі чати видалено: очистити стрічку, заголовок і чергу."""
        try:
            self.chat.reset()
        except (tk.TclError, AttributeError):
            LOG.debug("Стрічку не вдалось очистити", exc_info=True)
        # Контекст агента належав видаленим чатам — починаємо з чистого.
        try:
            self.agent.session.reset()
        except AttributeError:
            LOG.debug("Сесія агента ще не створена", exc_info=True)
        # Черга належить чатам: якщо чатів немає, виконувати нічого.
        queue_dropped = len(self.task_queue.tasks)
        if queue_dropped:
            self.task_queue.clear()
            self._update_queue_badge()
        self._sync_chat_title()
        try:
            self.chat_list.set_active("")
            self.chat_list.refresh()
        except (tk.TclError, AttributeError):
            pass
        self.nav_refresh_history()
        message = f"Видалено всі чати: {removed}."
        if queue_dropped:
            message += f" Чергу очищено: {queue_dropped} задач."
        self.set_status(message)

    def create_project_folder(self) -> None:
        """Створити нову теку проєкту й одразу її відкрити."""
        from tkinter import simpledialog

        name = simpledialog.askstring(
            "Новий проєкт",
            "Назва теки проєкту (буде створена поруч із поточною):",
            parent=self)
        if not name or not name.strip():
            return
        clean = re.sub(r'[<>:"/\\|?*]', "_", name.strip()) or "project"
        base = Path(self.settings.workspace)
        if not base.is_dir() or not self.has_project():
            base = Path.home() / "Projects"
        target = base / clean
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Не вдалось створити",
                                 f"{target}\n\n{exc}", parent=self)
            return
        self.set_workspace(target)

    def new_chat_session(self) -> bool:
        """Підготувати новий чат. Без вибраного проєкту — спершу вибір теки.

        Чат НЕ записується у сховище одразу: запис у списку з'являється з
        першим повідомленням (див. ``_remember_message``). Раніше кожне
        натискання «＋ Новий чат» створювало порожній запис, і список
        заповнювався рядками «Без назви» з нулем повідомлень — саме те, що
        видно на скріншоті користувача.

        Повертає ``True``, якщо сесію підготовлено. Кнопка «Новий чат»,
        меню й стартовий екран ведуть сюди, тож перевірка одна на всі входи.
        """
        if not self.has_project():
            self._show_project_gate(
                reason="Чат відкриється, щойно буде вибрано теку проєкту.")
            self.set_status("Спершу вибери папку проєкту — без неї агенту ніде працювати.")
            return False
        # Агент зараз працює — перемикання знищило б поточний хід: стрічка
        # очищається, а потік агента продовжує дописувати у ВЖЕ ОЧИЩЕНУ
        # сесію, і результат попередньої задачі зникає (а частково ще й
        # зберігається під новим chat_id). Тому спершу зупиняємо.
        if self.agent.busy:
            self.set_status("Агент ще працює — дочекайся завершення або зупини його (■), "
                            "потім створи новий чат.")
            return False
        self._close_project_gate()
        # Знімаємо з активності попередній чат, але не чіпаємо його запис:
        # розмова лишається в списку, доки в ній є повідомлення.
        #
        # Контекст агента зберігаємо ПЕРЕД очищенням: інакше модель
        # втрачала все, що знала про попередню розмову, і повернутись до
        # неї було неможливо — саме це відчувалось як «чат зник».
        previous = str(getattr(self.chat_store, "active_id", "") or "")
        if previous:
            self._save_chat_context(previous)
        self._pending_chat = True
        self.chat_store.set_active("")
        self._hide_welcome()
        self.chat.reset()
        # Новий чат починається з ЧИСТОГО контексту — жодних слідів
        # попереднього діалогу в сесії агента.
        try:
            self.agent.session.reset()
        except AttributeError:
            LOG.debug("Сесія агента ще не створена", exc_info=True)
        self.chat_list.refresh()
        self._sync_chat_title()
        self._sync_chat_model()
        self._sync_chat_queue()
        self._focus_composer()
        self.set_status("Новий чат: запиши перше завдання — і сесія з'явиться у списку.")
        return True

    def _pending_chat_active(self) -> bool:
        """Чи зараз відкрито «чернетку» чату, ще не записану у сховище."""
        return bool(getattr(self, "_pending_chat", False)) and not self.chat_store.active()

    def _ensure_pending_chat(self) -> None:
        """Створити запис чату при першому повідомленні чернетки.

        Викликається лише тоді, коли користувач справді щось надіслав:
        так у списку не буває порожніх сесій, і кожен запис має власника
        (``chat_id``), до якого прив'язуються задачі черги.
        """
        if self.chat_store.active():
            self._pending_chat = False
            return
        if not self.has_project():
            return
        chat = self.chat_store.create(workspace=str(self.settings.workspace),
                                      model=self.settings.llm.model)
        self._pending_chat = False
        self.chat_list.refresh()
        self._sync_chat_title()
        self._sync_chat_model()
        LOG.info("Створено чат %s на перше повідомлення", chat.id)

    def _focus_composer(self) -> None:
        """Поставити курсор у поле введення (щоб одразу можна було писати)."""
        try:
            self.chat.input_box.focus_set()
        except (tk.TclError, AttributeError):
            pass

    def open_chat(self, chat_id: str) -> None:
        """Відкрити збережений чат: історія й КОНТЕКСТ агента відновлюються.

        Без вибраної теки проєкту чат не відкривається: інакше агент почав
        би працювати з файлами в домашній теці користувача.

        Головне тут — :meth:`_load_chat_context`. Раніше відкриття чату
        малювало лише стрічку, а сесія агента лишалась від попередньої
        розмови: модель або не бачила власної історії (продовжити роботу
        неможливо), або бачила ЧУЖУ. Тепер контекст перемикається разом із
        чатом, а поточний зберігається перед перемиканням.
        """
        if not self.has_project():
            self._show_project_gate(
                reason="Вибери теку проєкту — і цей чат відкриється.")
            self.set_status("Спершу вибери папку проєкту.")
            return
        chat = self.chat_store.get(chat_id)
        if chat is None:
            return
        if self.agent.busy:
            self.set_status("Агент ще працює — дочекайся завершення або зупини його (■).")
            return
        self._close_project_gate()
        previous = str(getattr(self.chat_store, "active_id", "") or "")
        if previous and previous != chat_id:
            self._save_chat_context(previous)
        self._pending_chat = False
        self.chat_store.set_active(chat_id)
        self._hide_welcome()          # оверлей стартового екрана ховаємо
        self.chat.show_history(chat.messages)
        self._load_chat_context(chat_id)
        self.chat_list.refresh()
        self._sync_chat_title()
        self._sync_chat_model()
        self._sync_chat_queue()
        self.set_status(f"Відкрито чат: {chat.title or 'Без назви'}")

    # ── контекст агента: один на чат ───────────────────────────────────────
    def _save_chat_context(self, chat_id: str) -> bool:
        """Зберегти контекст агента в запис чату (перед перемиканням/виходом)."""
        if not chat_id:
            return False
        session = getattr(self.agent, "session", None)
        if session is None:
            return False
        try:
            self.chat_store.store_context(chat_id, session.snapshot())
            # Стан розуміння завдання — окремо: він переживає перезапуск і
            # саме він не дає агентові перепитувати вже пояснене.
            state = getattr(self.agent, "state", None)
            if state is not None:
                self.chat_store.store_state(chat_id, state.to_dict())
        except Exception:  # noqa: BLE001 - перемикання не має ламати контекст
            LOG.warning("Не вдалось зберегти контекст чату %s", chat_id,
                        exc_info=True)
            return False
        return True

    def _load_chat_context(self, chat_id: str) -> int:
        """Відновити контекст агента з запису чату.

        Порядок: збережений контекст агента → повідомлення чату. Друге
        джерело потрібне для старих чатів (до появи поля ``context``) і для
        розмов, де повідомлення додавались без ходу агента: без нього агент
        відкривав чат з історією на екрані, але «не пам'ятав» нічого.
        Порожній результат — нормальний стан нового чату: сесія очищується.
        """
        session = getattr(self.agent, "session", None)
        if session is None:
            return 0
        try:
            messages = self.chat_store.load_context(chat_id)
            if not messages:
                messages = self._context_from_messages(chat_id)
            restored = session.restore(messages)
        except Exception:  # noqa: BLE001 - старт чату не має падати
            LOG.warning("Не вдалось відновити контекст чату %s", chat_id,
                        exc_info=True)
            try:
                session.reset()
            except Exception:  # noqa: BLE001
                pass
            return 0
        if restored:
            LOG.info("Відновлено контекст чату %s: %s повідомлень", chat_id, restored)
        # Стан розуміння завдання: мета, обмеження, об'єкти згадки. Без
        # нього агент у відновленому чаті не знав би, над чим працює, і
        # перепитував би те, що людина вже пояснила.
        try:
            self.agent.state = conversation.ConversationState.from_dict(
                self.chat_store.load_state(chat_id))
        except Exception:  # noqa: BLE001
            LOG.debug("Стан чату не відновлено", exc_info=True)
            self.agent.state = conversation.ConversationState()
        return restored

    def _context_from_messages(self, chat_id: str) -> list[dict]:
        """Побудувати контекст агента з видимих повідомлень чату.

        Використовується як запасний шлях: після перезапуску старої версії
        програми контексту агента ще немає, а історія розмови вже є.
        """
        chat = self.chat_store.get(chat_id)
        if chat is None:
            return []
        rows: list[dict] = []
        for message in chat.messages:
            role = getattr(message, "role", "")
            text = (getattr(message, "text", "") or "").strip()
            if not text:
                continue
            if role == "user":
                rows.append({"role": "user", "content": text})
            elif role == "assistant":
                rows.append({"role": "assistant", "content": text})
            # ``system``/``tool`` лишаємо осторонь: це службові позначки
            # стрічки, а не повідомлення діалогу, і сервер їх не прийме
            # без відповідного tool_call.
        # Останні 40 реплік достатньо, щоб продовжити розмову: решту
        # однаково підріже ``AgentSession.trim`` під вікно моделі.
        return rows[-40:]

    def _sync_chat_queue(self) -> None:
        """Показати в панелі чату чергу САМЕ цього чату.

        Раніше бейдж показував задачі всіх чатів одразу: у новому чаті
        висіло «Черга: 3» від попереднього, і користувач бачив чужу роботу.
        """
        chat_id = self._active_chat_id()
        try:
            tasks = [task for task in self.task_queue.tasks
                     if not chat_id or not getattr(task, "chat_id", "")
                     or task.chat_id == chat_id]
            self.chat.set_queue_count(len(tasks), tasks)
        except (tk.TclError, AttributeError):
            LOG.debug("Не вдалось оновити бейдж черги", exc_info=True)

    def _reconcile_server_url(self) -> None:
        """Узгодити адресу сервера з тим, що СПРАВДІ слухає.

        Навіщо. Порт рушія «плаває»: якщо 8080 займає інша програма (Steam
        на цій машині), llama-server бере 8081 — а в налаштуваннях лишається
        8080. Тоді кожен запит дістає HTTP 404, і в інтерфейсі це виглядає
        як «модель не працює», хоч вона працює.

        Функція НЕ вгадує: якщо нічого не відповідає, налаштування не
        змінюються й великий статус показує офлайн. Зміна відбувається лише
        тоді, коли робочий сервер справді знайдено.

        ВАЖЛИВО про швидкість. Перевірка ``server_responds`` на непіднятому
        сервері коштує до 4.6 с (три HTTP-спроби, кожна впирається в
        таймаут — на цій машині connect до закритого порту чекає весь
        таймаут). Раніше це виконувалось у ГОЛОВНОМУ потоці під час
        першого кадру, і старт займав 6.3 с. Тепер сама перевірка йде у
        фоновий потік, а результат застосовується через ``_ui_call`` —
        інтерфейс малюється одразу, адреса узгоджується за секунду-дві.
        """
        configured = str(self.settings.llm.base_url or "")
        # Вбудований рушій: порту немає й «плавати» нічому. Раніше тут
        # виконувався пошук по 8 портах, і для ``native://blackchpok``
        # шукати було нічого — лише гаяно час.
        if runtime.embedded_url(configured):
            return
        low = configured.lower()
        if configured and not any(marker in low for marker in
                                  ("127.0.0.1", "localhost", "0.0.0.0")):
            return   # хмара/зовнішній сервер: порт не «плаває»
        if getattr(self, "_reconcile_running", False):
            return
        self._reconcile_running = True
        key = str(self.settings.llm.api_key or "")

        def work() -> None:
            found = ""
            try:
                if configured and runtime.server_responds(configured,
                                                          api_key=key):
                    return
                found = runtime.discover_server_url(configured, api_key=key)
            except Exception:  # noqa: BLE001 - узгодження не має ламати старт
                LOG.debug("Узгодження адреси сервера не вдалось", exc_info=True)
                return
            finally:
                self._reconcile_running = False
            if found and found.rstrip("/") != configured.rstrip("/"):
                self._ui_call(lambda: self._apply_reconciled_url(configured, found))

        threading.Thread(target=work, daemon=True,
                         name="reconcile-server-url").start()

    def _apply_reconciled_url(self, configured: str, found: str) -> None:
        """Застосувати знайдену адресу (уже в головному потоці)."""
        LOG.info("Адреса сервера узгоджена: %s → %s", configured, found)
        self.settings.llm.base_url = found
        self.settings.llm.api_key = runtime.MANAGED_API_KEY
        safe.call_quiet(self.settings.save, where="збереження адреси сервера")
        self.agent.llm_settings = self.settings.llm
        self.set_status(f"Адресу сервера узгоджено з робочою: {found}")

    def _adopt_local_model(self) -> None:
        """Підхопити локальну модель, якщо в налаштуваннях назва порожня.

        Користувач міг скачати GGUF і не обрати його вручну; без цього
        рядок моделі показує «модель не вибрана», а агент іде в офлайн-роутер
        замість роботи з моделлю.
        """
        if self.settings.llm.model.strip():
            # Модель уже вибрана — але адреса могла застаріти (порт
            # змінився після перезапуску). Узгоджуємо її ПЕРЕД першим
            # запитом, інакше агент стукає в зайнятий порт і дістає 404.
            self._reconcile_server_url()
            return
        # ── Вбудований рушій — теж ЛОКАЛЬНИЙ ─────────────────────────────
        # Перевірка нижче шукає ``127.0.0.1``/``localhost`` в адресі, щоб не
        # чіпати зовнішній сервер. Але ``native://blackchpok`` не містить
        # жодного з цих маркерів, тож вбудований рушій вважався «зовнішнім»,
        # і модель НІКОЛИ не підхоплювалась: у налаштуваннях лишалось
        # порожнє поле, шапка показувала «модель не вибрана», а агент падав
        # із «Модель не вибрана» — хоч на диску лежало сім GGUF-файлів
        # (перевірено ``tools/check_server_adopt.py`` й живим прогоном).
        embedded = runtime.embedded_url(str(getattr(self.settings.llm, "base_url", "") or ""))
        if not embedded \
                and getattr(self.settings.llm, "base_url", "").strip() \
                and "127.0.0.1" not in self.settings.llm.base_url \
                and "localhost" not in self.settings.llm.base_url:
            return          # зовнішній сервер — модель визначає він
        try:
            local = [p for p in hub.local_models() if p.suffix.lower() == ".gguf"]
        except Exception:  # noqa: BLE001 - хаб може бути недоступний
            local = []
        if not local:
            return
        chosen = self.settings.engine.model_path
        path = Path(chosen) if chosen and Path(chosen).exists() else None
        if path is None:
            preferred = str(getattr(self.settings.engine, "native_model", "") or "")
            match = next((p for p in local if preferred and
                          (p.name == preferred or p.stem == preferred)), None)
            path = match or max(local, key=lambda p: p.stat().st_size if p.exists() else 0)
        self.settings.llm.model = path.stem
        if embedded:
            # Адресу вбудованого рушія НЕ переписуємо на HTTP: це той самий
            # рушій у цьому процесі, і підміна на ``http://127.0.0.1:8080``
            # змусила б агента шукати неіснуючий сервер.
            self.settings.engine.model_path = str(path)
            if not str(getattr(self.settings.engine, "native_model", "") or ""):
                self.settings.engine.native_model = path.stem
            safe.call_quiet(self.settings.save, where="збереження вибраної моделі")
            self.set_status(f"Модель: {path.stem}")
            return
        # URL і ключ мають відповідати рушію, який обслуговує цю модель:
        # інакше агент стукає в LM Studio на 1234 і мовчки йде в офлайн-роутер.
        port = int(getattr(self.settings.engine, "port", 0) or 0) or runtime.DEFAULT_PORT
        current_url = str(self.settings.llm.base_url or "")
        if not current_url or "1234" in current_url:
            self.settings.llm.base_url = f"http://127.0.0.1:{port}/v1"
        key = str(self.settings.llm.api_key or "").strip().lower()
        if not key or key in ("lm-studio", "none"):
            self.settings.llm.api_key = runtime.MANAGED_API_KEY
        self.settings.engine.model_path = str(path)
        # Збереження не має ламати старт, але його збій треба бачити:
        # інакше модель «підхопилась», а після перезапуску знову не
        # вибрана, і причину не знайти.
        safe.call_quiet(self.settings.save, where="збереження вибраної моделі")
        self.set_status(f"Модель: {path.stem}")

    def _current_editor_path(self) -> Optional[Path]:
        """Поточний файл редактора (``None``, якщо нічого не відкрито).

        Викликається з панелі чату під час підказок над полем; вкладки
        можуть бути ще не створені — тоді просто немає файлу.
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return None
        try:
            return tabs.current_path()
        except (tk.TclError, AttributeError):
            return None

    def _sync_chat_title(self) -> None:
        chat = self.chat_store.active()
        title = (chat.title if chat else "") or "Новий чат"
        try:
            self.chat.set_title(title)
        except (tk.TclError, AttributeError):
            pass

    def _remember_message(self, role: str, text: str) -> None:
        """Зберегти повідомлення; саме тут народжується запис чату.

        «Новий чат» готує порожню стрічку без запису в сховище, тож перший
        запис створюється на перше справжнє повідомлення. Без теки проєкту
        запис не створюємо: такий чат не має до чого прив'язатись.
        """
        if not self.chat_store.active():
            self._ensure_pending_chat()
        if not self.chat_store.active():
            return
        self.chat_store.append(role, text)
        # Контекст агента зберігаємо разом із повідомленням: навіть якщо
        # програму закриють посеред роботи, розмова відновиться повністю.
        chat_id = self._active_chat_id()
        if chat_id:
            self._save_chat_context(chat_id)
        self.chat_list.refresh()
        self._sync_chat_title()

    # ── постійні побажання й вимірювання ───────────────────────────────────
    def _attach_profile(self, runner: "AgentRunner") -> None:
        """Підключити збережені постійні побажання до агента."""
        try:
            runner.profile = conversation.UserProfile.from_list(
                self.settings.preferences)
        except Exception:                            # noqa: BLE001
            LOG.debug("Побажання не прочитано", exc_info=True)
            runner.profile = conversation.UserProfile()

    def _save_profile(self) -> None:
        """Записати побажання у налаштування (після кожного ходу).

        Пишемо лише коли список справді змінився: інакше кожен хід
        перезаписував би файл налаштувань.
        """
        runner = getattr(self, "agent", None)
        profile = getattr(runner, "profile", None)
        if profile is None:
            return
        try:
            fresh = profile.to_list()
        except Exception:                            # noqa: BLE001
            return
        if fresh == list(self.settings.preferences):
            return
        self.settings.preferences = fresh
        try:
            self.settings.save()
        except Exception:                            # noqa: BLE001
            LOG.debug("Побажання не збережено", exc_info=True)

    def _attach_traces(self, runner: "AgentRunner") -> None:
        """Підключити сховище прогонів (для метрик і навчальних прикладів)."""
        try:
            from .config import app_data_dir

            path = app_data_dir() / "agent_traces.jsonl"
            runner.traces = trace_store.TraceStore(path)
        except Exception:                            # noqa: BLE001
            LOG.debug("Сховище traces недоступне", exc_info=True)
            runner.traces = None

    def _attach_memory_bridge(self, runner: "AgentRunner") -> None:
        """Підключити пам'ять NEUROMESH до розуміння запиту.

        Сервіс створюється в ``__init__`` (``self.memory``), але тоді
        агента ще немає. Тому міст підключаємо окремо — і повторно, коли
        пам'ять перестворюється.
        """
        try:
            existing = getattr(runner, "memory_bridge", None)
            if existing is None:
                runner.memory_bridge = memory_bridge.MemoryBridge(self.memory)
            else:
                existing.attach(self.memory)
        except Exception:                            # noqa: BLE001
            LOG.debug("Пам'ять не підключена до агента", exc_info=True)

    def show_agent_quality(self) -> None:
        """Показати звіт про якість агента (реальні цифри, не обіцянки)."""
        runner = getattr(self, "agent", None)
        store = getattr(runner, "traces", None)
        if store is None:
            messagebox.showinfo(APP_NAME, "Вимірювання вимкнено в налаштуваннях.")
            return
        summary = store.summary()
        report = trace_store.format_report(summary)
        window = tk.Toplevel(self)
        window.title("Якість агента")
        window.configure(bg=theme.BG)
        window.geometry("760x560")
        window.transient(self)
        # Шрифт беремо з теми вікна (``self.theme``), а не з ``self.fonts``:
        # такого атрибута у вікна немає, і кнопка меню падала з
        # AttributeError замість того, щоб показати звіт.
        mono = getattr(getattr(self, "theme", None), "mono_small", None) \
            or ("Consolas", 9)
        box = tk.Text(window, wrap="word", bg=theme.BG_EDITOR, fg=theme.FG, bd=0,
                      highlightthickness=0, font=mono,
                      padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=8, pady=8)
        box.insert("1.0", report)
        box.configure(state="disabled")
        widgets.Chip(window, "Закрити", window.destroy).pack(anchor="e", padx=10,
                                                            pady=(0, 10))

    def _on_new_chat(self) -> None:
        self._refresh_context()
        self.chat_list.refresh()

    def _on_chat_busy(self, busy: bool) -> None:
        self._set_agent_state("працює" if busy else "очікує")
        # Хід завершився — зберігаємо побажання, які могли з'явитись у
        # розмові («завжди відповідай українською»). Пишемо лише зміни.
        if not busy:
            self._save_profile()
        # Статус сесії в списку агентів: працює / завершено. Порожня сесія
        # без повідомлень лишається idle — їй ще нічого «завершувати».
        chat = self.chat_store.active()
        if chat is not None:
            if busy:
                state = "working"
            elif chat.message_count:
                state = "done"
            else:
                state = "idle"
            self.chat_store.set_status(chat.id, state)
            self.chat_list.update_row_status(chat.id, state)
        # Агент саме закінчив роботу, а автономний режим чекав на це, щоб
        # зупинитись. Завершуємо зараз, а не на наступному тіку: інакше
        # зупинка «висить» до 2.5 с і користувач не розуміє, що сталось.
        if not busy and self._autonomous_stop_pending:
            self._finish_autonomous_stop()

    def stop_agent(self) -> None:
        self.chat.stop()

    # ── автономний режим ───────────────────────────────────────────────────
    def show_autonomous(self) -> None:
        """Відкрити панель автономного режиму в бічній колонці."""
        self.show_side("autonomous")

    def pick_autonomous_project(self) -> None:
        """Обрати теку проєкту для автономного режиму."""
        current = self.autonomous_engine.project or Path(self.settings.workspace)
        folder = filedialog.askdirectory(parent=self, title="Тека для автономного режиму",
                                         initialdir=str(current))
        if not folder:
            return
        target = Path(folder)
        ok, reason = self.autonomous_engine.can_start(target)
        if not ok:
            self.set_status(reason)
            messagebox.showinfo("Автономний режим", reason, parent=self)
            return
        # Тека стає робочою: агент править саме її, і файли видно в редакторі.
        self.set_workspace(target)
        self.autonomous_engine.project = target
        self.autonomous_panel.refresh()
        self.set_status(f"Автономний режим: обрано {target}")

    def start_autonomous(self) -> None:
        """Увімкнути безперервний режим покращення проєкту.

        Режим прив'язаний до КОНКРЕТНОГО чату й теки: задачі, які він
        ставить, дістають ``chat_id`` цього чату, і зникають разом із ним.
        Без прив'язки вони висіли в панелі «Автоматизації» назавжди.
        """
        if not self.settings.llm.model:
            messagebox.showwarning(
                "Автономний режим",
                "Спершу підключи модель (Хаб моделей або перший запуск): "
                "без моделі агент не може правити код.",
                parent=self)
            return
        if not self.has_project():
            self._show_project_gate(
                reason="Автономний режим потребує теки проєкту.")
            self.set_status("Спершу вибери папку проєкту — автономний режим працює в ній.")
            return
        project = self.autonomous_engine.project or Path(self.settings.workspace)
        ok, message = self.autonomous_engine.start(project)
        if not ok:
            self.set_status(message)
            messagebox.showinfo("Автономний режим", message, parent=self)
            return
        # Задачі режиму належатимуть поточному чату. Якщо чат ще чернетка —
        # створюємо запис: режим має власника, інакше задачі стануть сиротами.
        self._ensure_pending_chat()
        self.autonomous_engine.chat_id = str(
            getattr(self.chat_store, "active_id", "") or "")
        self.project = project
        self._autonomous_stop_pending = False
        self.autonomous_engine.seed(limit=autonomous.SEED_PER_CYCLE)
        self.show_side("autonomous")
        self.show_chat(True)
        self.autonomous_panel.refresh()
        self._autonomous_tick()
        self._update_queue_badge()
        self.set_status(f"Автономний режим увімкнено: {project.name}")

    def _agent_working(self) -> bool:
        """Чи агент справді ще виконує хід.

        Беремо прапорець чату, а не лише життя потоку: нитка може вже
        дописати відповідь, але ще не встигнути завершитись, і тоді
        зупинка чекала б на «мертвий» стан зайві секунди.
        """
        try:
            return bool(getattr(self.chat, "_busy", False))
        except Exception:  # noqa: BLE001 - віджет міг бути знищений
            return bool(getattr(self.agent, "busy", False))

    def stop_autonomous(self) -> None:
        """Коректна зупинка: поточний файл дописується й зберігається."""
        if not self.autonomous_engine.active:
            self.set_status("Автономний режим і так вимкнено.")
            return
        message = self.autonomous_engine.request_stop()
        self._autonomous_stop_pending = True
        self.autonomous_panel.refresh()
        self.set_status(message)
        # Якщо агент зараз нічого не робить — завершуємо просто зараз.
        if not self._agent_working():
            self._finish_autonomous_stop()

    def _finish_autonomous_stop(self) -> None:
        """Дописати файл (зберегти все) і вимкнути режим."""
        if not self.autonomous_engine.active or not self._autonomous_stop_pending:
            return
        self._autonomous_stop_pending = False
        saved = self._save_all_silently()
        reason = "Автономний режим вимкнено."
        if saved:
            reason += f" Збережено файлів: {saved}."
        self.autonomous_engine.confirm_stop(reason=reason)
        try:
            self.autonomous_panel.refresh()
        except (tk.TclError, AttributeError):
            pass
        self._update_queue_badge()
        self.set_status("Автономний режим вимкнено — усі зміни збережено.")

    def _save_all_silently(self) -> int:
        """Зберегти всі змінені вкладки, не питаючи нічого.

        Це та сама «дописка до кінця», якої вимагає коректна зупинка:
        жодного незакінченого файлу не лишається. Безіменні файли
        пропускаємо — для них немає шляху, і мовчки зберігати їх нікуди.
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return 0
        count = 0
        for frame_id in list(getattr(tabs, "_order", [])):
            editor = tabs.editors.get(frame_id)
            path = tabs.paths.get(frame_id)
            if editor is None or path is None:
                continue
            if not getattr(editor, "modified", False):
                continue
            try:
                ws.write_text_file(path, editor.get_text())
                editor.modified = False
                tab = tabs._tabs.get(frame_id) if hasattr(tabs, "_tabs") else None
                if tab is not None:
                    tab.set_title(Path(path).name, False)
                count += 1
            except Exception:  # noqa: BLE001 - зупинка не має падати на диску
                LOG.warning("Не вдалось зберегти %s під час зупинки", path, exc_info=True)
        if count:
            # Перемальовування вкладок — косметика, але збій фіксуємо: якщо
            # воно падає, користувач бачить «зірочку» змін навіть після
            # збереження й не розуміє, чому.
            safe.call_quiet(tabs._notify_changed,
                            where="оновлення позначок вкладок")
        return count

    def add_autonomous_task(self, text: str) -> None:
        """Гаряче додати свою задачу в автономну чергу (вищий пріоритет)."""
        ok, message = self.autonomous_engine.add_user_task(text)
        self.set_status(message)
        if ok:
            self._update_queue_badge()
            self.autonomous_panel.refresh()
            # Режим вимкнено — задача все одно в черзі й виконається після старту.
            if not self.autonomous_engine.active:
                self.set_status(message + " Натисни «Старт», щоб агент почав.")

    def _after_autonomous_change(self) -> None:
        """Рушій змінився — оновити панель і бейдж (з головного потоку)."""
        if not self._timer_alive():
            return
        try:
            self.autonomous_panel.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _autonomous_tick(self) -> None:
        """Серце режиму: раз на кілька секунд вирішує, що робити далі."""
        try:
            engine = self.autonomous_engine
            if engine.state == autonomous.STATE_OFF:
                self._autonomous_after = None
                return
            busy = self._agent_working()
            # Рахуємо лише задачі СВОГО чату: чужі не мають вважатись
            # роботою цього сеансу, інакше режим чекав би на них даремно.
            pending = self.task_queue.next_pending(
                chat_id=self._active_chat_id()) is not None
            action = engine.tick(busy=busy, has_pending=pending)
            if action == "stop_wait":
                # Агент дописує файл — не чіпаємо його, лише показуємо стан.
                self.set_status("Автономно: дописую поточний файл, далі зупинюсь…")
            elif action == "stop_finish":
                self._finish_autonomous_stop()
                self._autonomous_after = None
                return
            elif action == "run":
                self._autonomous_run_next()
            elif action == "seed":
                added = engine.seed(limit=autonomous.SEED_PER_CYCLE)
                self.autonomous_panel.refresh()
                if added:
                    self._autonomous_run_next()
                else:
                    self.set_status("Автономно: нових ідей немає, повторю аналіз за хвилину.")
        except Exception as exc:  # noqa: BLE001 - тік не має валити вікно
            LOG.warning("Тік автономного режиму впав: %s", exc, exc_info=True)
            self.set_status(f"Автономний режим: помилка кроку — {exc}")
        try:
            if self.winfo_exists():
                self._autonomous_after = (self.after(2500, self._autonomous_tick)
                                          if self._timer_alive() else None)
        except tk.TclError:
            self._autonomous_after = None

    def _autonomous_run_next(self) -> None:
        """Запустити наступну задачу черги в рамках автономного режиму."""
        task = self.task_queue.next_pending(chat_id=self._active_chat_id())
        if task is None:
            return
        engine = self.autonomous_engine
        engine.note_action(_plan_text_for(task), kind=autonomous.KIND_CODE,
                           file=task.file_hint)
        self.autonomous_panel.refresh()
        self.run_next_task(task)

    def _open_relative(self, path: str) -> None:
        """Відкрити файл проєкту за відносним шляхом (з панелі автономного режиму)."""
        clean = (path or "").strip()
        if not clean:
            return
        root = self.autonomous_engine.project or Path(self.settings.workspace)
        target = Path(root) / clean
        if target.exists():
            self.open_path(target)
        elif clean:
            self.set_status(f"Файл не знайдено: {clean}")

    # ── простій: вивантаження моделі з відеокарти ──────────────────────────
    def _wake_model(self) -> None:
        """Підняти локальну модель, якщо її вивантажили під час простою."""
        if self.model_keeper.loaded:
            return
        local = []
        try:
            local = [p.name for p in hub.local_models() if p.suffix.lower() == ".gguf"]
        except Exception:  # noqa: BLE001 - хаб може бути недоступний
            pass
        if local:
            self._autostart_local_model(local)

    def _wake_native_model(self) -> bool:
        """Завантажити модель назад у власний рушій після простою."""
        try:
            if self.native_runtime.loaded:
                return True
            result = self._autostart_native_model()
            return bool(result) and self.native_runtime.loaded
        except Exception:  # noqa: BLE001 - не ламаємо тік простою
            LOG.debug("Власний рушій не розбудився", exc_info=True)
            return False

    def _before_agent_request(self) -> None:
        """Перед кожним запитом: підняти модель, якщо її вивантажив простій."""
        try:
            self._wake_model_if_needed()
        except Exception:  # noqa: BLE001 - підйом не має блокувати запит
            LOG.debug("Підйом моделі перед запитом не вдався", exc_info=True)

    def _idle_tick(self) -> None:
        """Раз на кілька секунд: чи не час віддати пам'ять відеокарти."""
        try:
            keeper = self.model_keeper
            busy = self._agent_working()
            autonomous_on = self.autonomous_engine.active
            if keeper.poll(busy=busy, autonomous=autonomous_on):
                self._note_model_unloaded()
        except Exception as exc:  # noqa: BLE001 - фоновий тік не має ламати вікно
            LOG.debug("Тік простою впав: %s", exc, exc_info=True)
        try:
            if self.winfo_exists():
                self._idle_after = (self.after(20000, self._idle_tick)
                                    if self._timer_alive() else None)
        except tk.TclError:
            self._idle_after = None

    def _note_model_unloaded(self) -> None:
        """Модель пішла з відеокарти: сказати про це й запам'ятати стан.

        Навіщо окремий метод. У лозі користувача було так:

            19:03:50  Старт рушія: … --port 8080 …
            19:08:50  Модель вивантажено після 0 с простою
            19:10:31  Адреса 8080 не слухає → модель недоступна

        Модель вивантажилась через 5 хв простою — і БІЛЬШЕ НІКОЛИ не
        піднялась: ``model_keeper.reload()`` не викликався ніде в проєкті.
        Користувач бачив «модель не стартує», хоч вона стартувала.

        Тепер стан запам'ятовується (``_model_unloaded_by_idle``), і перша
        ж дія користувача піднімає модель назад.
        """
        self._model_unloaded_by_idle = True
        # Стан сервера тепер ІНШИЙ: він більше не обслуговує модель.
        # Без цього інтерфейс продовжував показувати «online» і старе вікно
        # контексту, хоч сервер уже зупинено.
        try:
            self.server_state.set_local(running=False)
            self.server_state.invalidate(reason="модель вивантажено через простій")
        except (AttributeError, tk.TclError):
            LOG.debug("Стан сервера не оновлено після вивантаження", exc_info=True)
        self.set_status("Модель вивантажено з відеокарти — вона вільна для "
                        "інших задач. Підніметься сама на наступний запит.")
        try:
            self.header_bar.set_model_status(
                False, detail="вивантажено через простій — підніметься на запит")
        except (tk.TclError, AttributeError):
            pass
        try:
            self.autonomous_panel.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _wake_model_if_needed(self) -> bool:
        """Підняти модель, якщо її вивантажив простій. ``True`` — підняли.

        Викликається ПЕРЕД відправкою запиту агенту: користувач повернувся
        після паузи, модель уже не в пам'яті, і без цього кожен такий
        запит закінчувався б «модель недоступна».
        """
        if not getattr(self, "_model_unloaded_by_idle", False):
            return False
        keeper = getattr(self, "model_keeper", None)
        if keeper is None:
            return False
        if keeper.loaded:
            # Модель уже десь завантажена — просто знімаємо прапорець.
            self._model_unloaded_by_idle = False
            return False
        try:
            self.model_keeper.touch()
            ok = keeper.reload()
        except Exception as exc:  # noqa: BLE001 - підйом не має ламати запит
            LOG.warning("Модель не піднялась після простою: %s", exc,
                        exc_info=True)
            return False
        if ok:
            self._model_unloaded_by_idle = False
            # Модель піднялась — контекст і набір схем МОЖУТЬ бути іншими.
            # Скидаємо їх, щоб перший же запит не пішов із старим вікном.
            self._invalidate_model_state(reason="модель піднято після простою")
            try:
                self.server_state.set_local(running=True)
                self.server_state.refresh(background=True)
            except (AttributeError, tk.TclError):
                LOG.debug("Стан сервера не оновлено після підйому", exc_info=True)
            self.set_status("Модель знову завантажена — виконую запит.")
            LOG.info("Модель піднято назад після простою")
            return True
        return False

    def unload_model_now(self) -> None:
        """Кнопка меню: негайно звільнити відеокарту."""
        if self.model_keeper.unload():
            self.set_status("Модель вивантажено з відеокарти.")
        else:
            self.set_status("Модель уже вивантажена або нею керує зовнішній сервер.")

    def free_vram_now(self) -> None:
        """Кнопка меню: звільнити відеокарту повністю.

        Крім штатного вивантаження моделі прибирає «сирітські» процеси
        ``llama-server``, що лишились від попередніх запусків IDE. Саме вони
        тримають відеопам'ять, коли користувач закрив програму, а гру
        запустити не може.
        """
        self._release_model_now()
        try:
            self.set_status("Відеопам'ять звільнено: рушії IDE зупинено. "
                            "Відеокарта вільна для інших програм.")
        except tk.TclError:
            pass

    def toggle_autonomous(self) -> None:
        if self.autonomous_engine.state == autonomous.STATE_OFF:
            self.start_autonomous()
        else:
            self.stop_autonomous()

    def close_chat(self, chat_id: str) -> bool:
        """Закрити чат зі списку (іконка «×» у рядку сесії).

        Поведінка залежить від того, чи є в чаті робота:

        * **порожній чат** (жодного повідомлення) — видаляється повністю:
          тримати в списку «Новий агент» без жодної репліки безглуздо, і
          саме через це лічильник зростав при кожному натисканні «×»;
        * **чат з історією** — архівується, щоб робота не пропала;
        * якщо закривають активний — звільняємо агента й показуємо
          наступний наявний чат (а якщо їх немає — екран вибору проєкту).

        Раніше тут безумовно кликався ``new_chat_session()``: кожне
        натискання «×» створювало НОВИЙ чат, і лічильник у панелі зростав
        замість того, щоб зменшуватись.
        """
        chat = self.chat_store.get(chat_id)
        if chat is None:
            return False
        if self.agent.busy and getattr(self.chat_store, "active_id", "") == chat_id:
            self.set_status("Агент ще працює — спершу зупини його (■).")
            return False

        empty = chat.message_count == 0
        active = getattr(self.chat_store, "active_id", "") == chat_id
        # Задачі черги, прив'язані до цього чату, гинуть разом із ним.
        dropped = self.task_queue.remove_for_chat(chat_id)
        if dropped:
            self._update_queue_badge()
        # ── Чат з АРХІВУ закривається остаточно ──────────────────────────
        # «×» в архіві означає «видалити», і підтвердження тут обов'язкове:
        # дія незворотна. Раніше архівний чат просто архівувався ще раз і
        # з архіву не зникав — саме на це скаржився користувач.
        if chat.archived and not empty:
            if not messagebox.askyesno(
                    "Видалити чат з архіву",
                    f"Видалити «{chat.title or 'Без назви'}» остаточно?\n\n"
                    "Історія розмови зникне без можливості відновлення.",
                    parent=self):
                return False
            self.chat_store.delete(chat_id)
            note = "Чат видалено з архіву."
        elif empty:
            # Порожній чат нема чого архівувати — видаляємо остаточно.
            self.chat_store.delete(chat_id)
            note = "Порожній чат прибрано."
        else:
            self.chat_store.archive(chat_id, True)
            note = "Чат перенесено в архів."

        if active:
            # Контекст закритого чату більше не потрібен у сесії агента:
            # інакше наступний чат починався б із чужої історії.
            try:
                self.agent.session.reset()
            except AttributeError:
                LOG.debug("Сесія агента ще не створена", exc_info=True)
            self.chat_store.set_active("")
            self._save_all_silently()
            # Не створюємо новий чат «про запас»: показуємо наявний, а якщо
            # їх немає — екран вибору проєкту.
            remaining = self.chat_store.visible()
            if remaining:
                self.open_chat(remaining[0].id)
            else:
                try:
                    self.chat.reset()
                except (tk.TclError, AttributeError):
                    pass
                self._sync_chat_title()
                self._sync_chat_queue()
                self._show_project_gate(
                    reason="Чатів немає. Вибери проєкт і створи новий чат.")
        self.chat_list.refresh()
        self.nav_refresh_history()
        self.set_status(note)
        return True

    def _wake_on_action(self, _event=None) -> None:
        """Будь-яка дія користувача скидає таймер простою.

        Кличеться на кожне натискання клавіші й кожен клік, тому робота
        тут має бути мінімальною: одне присвоєння часу. Скидання таймера
        не має кидати винятків — воно висить на ``bind_all`` і збій
        зламав би весь ввід у застосунку.
        """
        tracker = getattr(getattr(self, "model_keeper", None), "tracker", None)
        if tracker is not None:
            tracker.last_touch = time.time()

    def _confirm_command(self, command: str) -> bool:
        """Дозвіл на команду.

        Автономний режим: агент не питає підтвердження й не блокується.
        Діалог показуємо лише тоді, коли користувач сам увімкнув
        «питати дозвіл на команди» в налаштуваннях. Раніше діалог
        з'являвся завжди і зупиняв роботу посеред завдання — на нього
        ніхто не відповідав, і агент чекав до 10 хвилин.
        """
        if not self.settings.agent.confirm_commands:
            return True
        if threading.current_thread() is threading.main_thread():
            return self._ask_command(command)
        done = threading.Event()
        answer = {"value": False}

        def ask() -> None:
            try:
                answer["value"] = self._ask_command(command)
            finally:
                done.set()

        self._ui_call(ask)
        # Людина може думати довго — але агент не має висіти вічно.
        if not done.wait(timeout=600):
            return False
        return bool(answer["value"])

    def _ask_command(self, command: str) -> bool:
        return messagebox.askyesno(
            "Дозволити команду?",
            f"Агент хоче виконати:\n\n{command}\n\nДозволити?",
            parent=self,
        )

    # ── черга задач ────────────────────────────────────────────────────────
    def _queue_from_chat(self, text: str) -> int:
        added = self.queue_panel.add_text(text)
        self._update_queue_badge()
        if added:
            self.show_side("queue")
        return added

    def _split_task_to_queue(self, text: str) -> None:
        """Скласти план великого завдання локальною моделлю й наповнити чергу.

        Зміст кроків визначає САМА модель: окремим коротким запитом вона
        повертає нумерований список із назвами, описами й залежностями.
        Цей метод лише дає їй контекст проєкту (стек і файли), перевіряє
        відповідь і передає кроки в :class:`queue_engine.TaskQueue`.

        Якщо модель не змогла дати план (немає зв'язку, дивна відповідь),
        ставимо завдання однією задачею — краще так, ніж нічого, і
        повідомляємо причину замість вигаданого плану.
        """
        clean = (text or "").strip()
        if not clean:
            return
        if self.agent.busy:
            self.set_status("Агент зайнятий — розбиття поставимо після завершення.")
            return
        if getattr(self, "_planning", False):
            LOG.info("Планування вже триває — повторний запит ігнорую")
            return
        # Захист від подвійного розбиття: запит міг прийти двічі (подвійний
        # клік, Enter+кнопка, повторний виклик зі стрічки). Два плани підряд
        # дали 9 і 12 кроків у черзі — задачі дублювались, і агент робив
        # одну й ту саму роботу двічі.
        now = time.time()
        last = getattr(self, "_split_request", (0.0, ""))
        if last[1] == clean and (now - last[0]) < 5.0:
            LOG.info("Повторне розбиття того самого запиту — пропускаю")
            return
        self._split_request = (now, clean)
        self._planning = True
        # ── Чат мусить існувати ДО планування ─────────────────────────────
        # ``_after_split`` бере власника кроків через ``_active_chat_id()``,
        # а чат створюється першим повідомленням. ЗАМІРЯНО в живому прогоні:
        # план готовий о 20:00:24,978, а «Створено чат …» — о 20:00:25,044,
        # тобто на 66 мс ПІЗНІШЕ. Усі кроки народжувались без власника й
        # після першого ж кроку черга ставала: «done 1, pending 5», без
        # помилок і без руху.
        #
        # Тепер чат гарантовано є до створення кроків, і кожен крок одразу
        # належить своїй розмові.
        try:
            self._ensure_owner_chat()
        except Exception:  # noqa: BLE001 - чат не має ламати планування
            LOG.debug("Чат не створено перед плануванням", exc_info=True)
        self.show_bottom("tasks")
        self.set_status("Складаю план кроків локальною моделлю…")
        # Стан агента має показати, що робота ЙДЕ. Без цього вікно
        # показувало «агент: очікує», хоч модель активно складала план —
        # користувач думав, що натиск не спрацював (саме так і сталося
        # у живому прогоні: план складався 15 секунд, а індикатор стояв).
        self._set_agent_state("працює")
        try:
            self.chat.set_busy(True)
        except (tk.TclError, AttributeError):
            pass
        # Контекст проєкту й перелік інструментів: без них модель планує
        # «взагалі» й часто пропонує чужий стек.
        root = self._project_root()
        context = ""
        try:
            context = deep_mode.project_context(root)
        except Exception:  # noqa: BLE001 - контекст не має ламати планування
            LOG.debug("Контекст проєкту недоступний", exc_info=True)
        tool_names = [schema["function"]["name"] for schema in agent_tools.TOOL_SCHEMAS]
        llm = self.settings.llm

        def work() -> None:
            result = task_planner.plan_with_model(
                clean, llm, context=context, tool_names=tool_names)
            self._ui_call(self._after_split, clean, result)

        threading.Thread(target=work, daemon=True).start()

    def _after_split(self, brief: str, result: "task_planner.PlanResult") -> None:
        """Поставити план моделі в чергу й одразу почати виконання."""
        self._planning = False
        # Кроки плану народжуються з повідомлення в чаті, тож вони належать
        # йому ж: інакше після видалення чату задачі лишались у черзі
        # «сиротами» й агент продовжував їх виконувати.
        #
        # ── ЧОМУ ТУТ ЩЕ Й ``_ensure_chat`` ────────────────────────────────
        # Планування йде у ФОНОВОМУ потоці, тож між стартом і цим колбеком
        # чат міг ще не існувати (заміряно: 66 мс). Беремо власника ще раз
        # і, якщо його немає, створюємо чат — інакше кроки стають сиротами,
        # яких ``next_pending()`` не віддає жодному чату, і черга стоїть.
        owner = self._active_chat_id()
        if not owner:
            try:
                owner = self._ensure_owner_chat()
            except Exception:  # noqa: BLE001 - чат не має ламати план
                LOG.debug("Чат не створено після планування", exc_info=True)
                owner = self._active_chat_id()
        steps = result.steps if result is not None else []

        if not steps:
            # План не склався — ставимо запит ОДНІЄЮ задачею.
            reason = getattr(result, "error", "") or "невідома причина"
            task = self.task_queue.add(brief, chat_id=owner)
            if task is not None:
                task.add_history("note", f"план не склався: {reason[:160]}")
                self.task_queue.save()
            self._set_agent_state("очікує")
            self._finish_planning_ui()
            self.set_status(f"План не склався ({reason[:60]}) — завдання в черзі одним кроком.")
            self._update_queue_badge()
            # Модель недоступна — пробуємо виконати як звичайний запит,
            # щоб користувач не лишився ні з чим.
            if not task_planner_available(self.settings):
                return
            self._start_plan_execution()
            return

        # Другий захист від дублювання — за СКЛАДОМ плану. Першого (за
        # текстом запиту) не досить: поки модель складає план, користувач
        # міг надіслати той самий текст іще раз, і обидва плани лягали в
        # чергу (на скріншоті: 24 задачі замість 12).
        key = (brief.strip()[:200], tuple(step.title.strip() for step in steps))
        if getattr(self, "_last_plan_key", None) == key:
            LOG.info("Той самий план уже додано — пропускаю дубль")
            self._finish_planning_ui()
            return
        self._last_plan_key = key
        self._last_plan = list(steps)

        # Нове велике завдання замінює попередній незавершений план цього
        # чату: інакше стара черга змішувалась із новою метою.
        dropped = self.task_queue.drop_plan(chat_id=owner)
        created = self.task_queue.add_steps(result.rows(), chat_id=owner, goal=brief)
        # Смуга етапів над композером показує той самий поділ.
        try:
            stages = [task_plan.stage_from_text(step.title, index)
                      for index, step in enumerate(steps)]
            self.chat.stage_strip.set_stages(stages, goal=brief)
        except (tk.TclError, AttributeError):
            LOG.debug("Смуга етапів недоступна", exc_info=True)

        total = len(created)
        LOG.info("Завдання розбито на %d кроків", total)
        self._finish_planning_ui()
        # У чаті показуємо сам план — користувач бачить, що саме робитиме
        # агент, ще до початку роботи.
        try:
            self.chat._note(task_planner.plan_markdown(brief, steps))
        except (tk.TclError, AttributeError):
            LOG.debug("План не потрапив у чат", exc_info=True)
        self.set_status(
            f"План готовий: {total} кроків у черзі"
            + (f" (замінено {dropped} старих)" if dropped else ""))
        self._update_queue_badge()
        self.task_center.refresh()
        self._start_plan_execution()

    def _finish_planning_ui(self) -> None:
        """Повернути індикатори після складання плану."""
        self._set_agent_state("очікує")
        try:
            self.chat.set_busy(False)
        except (tk.TclError, AttributeError):
            pass

    def _start_plan_execution(self) -> None:
        """Запустити перший готовий крок плану (через виконавець)."""
        if self.task_queue.paused or self.agent.busy:
            return
        self.executor.start_next()
        self._update_queue_badge()

    # ── крок плану виконує справжній агент ─────────────────────────────────
    def _run_plan_step(self, task: queue_engine.QueueTask, prompt: str) -> bool:
        """Запустити один крок плану реальним агентським циклом.

        Викликається виконавцем: він уже позначив крок як активний. Тут ми
        лише віддаємо сформульований запит тому самому агенту, що працює в
        чаті, — з інструментами, дозволами й MCP.

        Повертає ``False``, якщо запит не пішов (агент зайнятий або немає
        теки): тоді виконавець поверне крок у чергу, а не лишить його
        «висіти» в стані «аналіз».
        """
        # Крок зі скіла виконує саме скіл: його інструкція важливіша за
        # загальний текст кроку.
        if task.skill:
            skill = self.skill_book.get(task.skill)
            if skill is not None:
                prompt = self._skill_prompt(skill)
        self._plan_step_active = True
        self._running_task_id = task.id
        self.show_chat(True)
        self._set_agent_state("працює")
        label = f"{task.number:02d}" if task.number else "—"
        self.set_status(f"Крок {label}: {task.title[:60]}…")
        chat = self.chat_store.active()
        if chat is not None:
            self.chat_store.set_status(chat.id, "working")
            self.chat_list.update_row_status(chat.id, "working")
        self.task_center.refresh()
        # ``plan_step=True``: це готовий крок плану. Розбивати його вдруге
        # не можна — інакше замість виконання запускалось нове планування
        # (рекурсія, у якій агент не робив жодної файлової дії).
        started = self.chat._send(prompt, deep=False, plan_step=True)
        if not started:
            self._plan_step_active = False
            self._running_task_id = ""
            LOG.info("Крок %s не запустився — повертаю в чергу", task.id)
        return bool(started)

    def _queue_skill(self, skill: skills_module.Skill) -> None:
        added = self.queue_panel.add_text(self._skill_prompt(skill), skill=skill.name)
        self._update_queue_badge()
        self.set_status(f"Скіл «{skill.name}» додано в чергу ({added})")

    # ── керування чергою з центру завдань ──────────────────────────────────
    def pause_queue(self) -> None:
        """Пауза: нові кроки не стартують, поточний доводить роботу."""
        self.task_queue.set_paused(True)
        self.set_status("Чергу поставлено на паузу — поточний крок дотягне роботу.")
        self._update_queue_badge()

    def resume_queue(self) -> None:
        """Продовжити чергу (знімає паузу й повертає призупинені кроки)."""
        self.executor.resume()
        self._update_queue_badge()
        self._start_plan_execution()

    def stop_plan(self) -> None:
        """Зупинити виконання: активний крок → «призупинено», агент спиняється."""
        self.executor.stop(reason="зупинено користувачем")
        if self.agent.busy:
            self.agent.cancel()
        self._plan_step_active = False
        self._running_task_id = ""
        self._set_agent_state("очікує")
        self.set_status("Виконання зупинено. Натисни «Продовжити», щоб іти далі.")
        self._update_queue_badge()

    def retry_plan_task(self, task_id: str) -> None:
        """Повторити невдалий крок (під контролем ліміту спроб)."""
        if self.executor.retry(task_id):
            task = self.task_queue.get(task_id)
            label = f"{task.number:02d}" if task and task.number else "—"
            self.set_status(f"Крок {label} повернуто в чергу.")
        else:
            self.set_status("Цей крок зараз не можна повторити.")
        self._update_queue_badge()

    def clear_plan_finished(self) -> None:
        """Прибрати завершені кроки з черги."""
        removed = self.executor.clear_finished()
        self.set_status(f"Прибрано завершених кроків: {removed}")
        self._update_queue_badge()

    def _queue_from_panel(self, text: str) -> None:
        """Крок, доданий вручну з центру завдань."""
        task = self.task_queue.add(text, chat_id=self._active_chat_id(),
                                   origin=queue_engine.ORIGIN_USER)
        if task is not None:
            self.task_queue.renumber(chat_id=self._active_chat_id())
            self.set_status("Крок додано в чергу.")
        self._update_queue_badge()

    def _open_project_file(self, name: str) -> None:
        """Відкрити файл кроку в редакторі (шлях відносний до проєкту)."""
        root = self._project_root()
        if root is None:
            self.set_status("Спершу вибери теку проєкту.")
            return
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = Path(root) / name
        if not candidate.exists():
            # Модель могла вказати лише ім'я файлу — шукаємо в проєкті.
            found = next(iter(Path(root).rglob(Path(name).name)), None)
            if found is None:
                self.set_status(f"Файл не знайдено: {name}")
                return
            candidate = found
        self.open_path(candidate)

    def replan_now(self) -> None:
        """Попросити модель перепланувати залишок робочого плану.

        Використовується, коли підхід не спрацював: модель бачить поточний
        стан кроків і повертає оновлений список. Уже виконані кроки
        зберігаються — вони реально змінили файли.
        """
        if getattr(self, "_planning", False):
            self.set_status("Планування вже триває.")
            return
        owner = self._active_chat_id()
        plan = self.task_queue.plan_tasks(chat_id=owner)
        if not plan:
            self.set_status("Немає плану для перепланування.")
            return
        goal = next((str(task.goal) for task in plan if task.goal), "")
        if not goal:
            goal = str(getattr(self, "_last_goal", "") or "продовжити роботу")
        self._planning = True
        self.set_status("Модель переплановує роботу…")
        self._set_agent_state("працює")
        root = self._project_root()
        context = ""
        try:
            context = deep_mode.project_context(root)
        except Exception:  # noqa: BLE001
            LOG.debug("Контекст для перепланування недоступний", exc_info=True)
        existing = task_planner.plan_as_text(plan)
        tool_names = [schema["function"]["name"] for schema in agent_tools.TOOL_SCHEMAS]
        llm = self.settings.llm

        def work() -> None:
            result = task_planner.plan_with_model(
                goal, llm, context=context, tool_names=tool_names,
                existing=existing, replan=True)
            self._ui_call(self._after_replan, result)

        threading.Thread(target=work, daemon=True).start()

    def _after_replan(self, result: "task_planner.PlanResult") -> None:
        """Замінити незавершені кроки новим планом моделі."""
        self._planning = False
        self._finish_planning_ui()
        if result is None or not result.steps:
            reason = getattr(result, "error", "") or "модель не дала кроків"
            self.set_status(f"Перепланування не вдалось: {reason[:80]}")
            return
        owner = self._active_chat_id()
        created = self.task_queue.replace_plan(
            result.rows(), chat_id=owner,
            goal=self.task_queue.plan_tasks(chat_id=owner)[0].goal
            if self.task_queue.plan_tasks(chat_id=owner) else "")
        self._last_plan = list(result.steps)
        self._update_queue_badge()
        try:
            self.chat._note("**План оновлено** — залишок роботи переплановано:\n\n"
                            + task_planner.plan_markdown("", result.steps))
        except (tk.TclError, AttributeError):
            LOG.debug("Оновлений план не потрапив у чат", exc_info=True)
        self.set_status(f"План оновлено: {len(created)} кроків.")
        self._start_plan_execution()

    def finish_plan_report(self) -> None:
        """Показати підсумковий звіт по плану в чаті."""
        report = self.executor.report(chat_id=self._active_chat_id())
        try:
            self.chat._note(report)
        except (tk.TclError, AttributeError):
            self.set_status(report.splitlines()[0] if report else "Звіт порожній.")
            return
        self.show_chat(True)
        self.set_status("Підсумковий звіт — у чаті.")

    def add_queue_dialog(self) -> None:
        self.show_side("queue")
        try:
            self.queue_panel.entry.focus_set()
        except tk.TclError:
            pass

    def _update_queue_badge(self) -> None:
        active_states = set(queue_engine.ACTIVE_STATUSES) | {queue_engine.PENDING}
        pending = [t for t in self.task_queue.tasks if t.status in active_states]
        try:
            self.chat.set_queue_count(len(pending), tasks=pending)
        except (tk.TclError, AttributeError):
            pass
        try:
            self.queue_panel.refresh()
        except (tk.TclError, AttributeError):
            pass
        try:
            self.task_center.refresh()
        except (tk.TclError, AttributeError):
            LOG.debug("Центр завдань не оновився", exc_info=True)
        # Колонка контексту показує той самий стан агента з черги — без
        # цього підпис «працює · крок 3» застигав на першому кроці.
        try:
            if self._context_shown:
                self.context._refresh_agent()
        except (tk.TclError, AttributeError):
            LOG.debug("Стан агента не оновився", exc_info=True)
        # Кнопка режиму чату показує, що саме цей чат робить у фоні.
        try:
            owner = str(getattr(self.chat_store, "active_id", "") or "")
            mine = [t for t in pending
                    if not getattr(t, "chat_id", "") or str(t.chat_id) == owner]
            self.header.set_chat_mode(
                autonomous=self.autonomous_engine.active, queue_count=len(mine))
        except (tk.TclError, AttributeError):
            pass

    def _queue_pump(self) -> None:
        """Раз на кілька секунд: якщо агент вільний, узяти наступну задачу.

        Під час зупинки автономного режиму нові задачі НЕ беремо: інакше
        щойно звільнений агент хапав би наступну задачу з черги й режим
        ніколи не завершувався б.
        """
        try:
            # ── Кроки без власника дістають активний чат ────────────────────
            # План складається в момент, коли чату ще немає: ``_after_split``
            # бере ``_active_chat_id()``, а він порожній, бо чат створюється
            # першим повідомленням. Такі кроки лишаються «сиротами», і
            # ``QueueExecutor.next_task()`` (який тепер передає свій
            # ``chat_id``) їх не бачить — черга стояла назавжди: 8 кроків
            # «очікує», 0 активних, 0 помилок (заміряно
            # ``.buildtmp/probe_next_task.py``).
            #
            # ``_adopt_orphan_tasks`` існував, але ніхто його не кликав.
            if (not self.task_queue.running_id and not self.agent.busy
                    and self._active_chat_id()):
                self._adopt_orphan_tasks()
            if (self.settings.agent.queue_auto_run and not self.task_queue.paused
                    and not self._autonomous_stop_pending
                    and self.autonomous_engine.state != autonomous.STATE_STOPPING
                    and not self.task_queue.running_id and not self.agent.busy
                    # Без теки проєкту черга не рухається: інакше насос
                    # викликав би run_next_task щосекунди й щоразу показував
                    # би екран вибору теки.
                    and self.has_project()
                    # Виконавець знає про залежності кроків, тому питаємо
                    # його, а не саму чергу.
                    and self.executor.next_task() is not None):
                self.run_next_task()
        except Exception as exc:  # noqa: BLE001 - фоновий насос не має ламати вікно
            # Насос спрацьовує кожні 1.2 с; безшумний збій означав би, що
            # черга просто перестала рухатись і ніхто не знає чому.
            safe.record_failure("запуск задачі з черги", exc)
            LOG.warning("Насос черги впав", exc_info=True)
        try:
            # Черга стоїть, бо активний крок «завис» (агент звільнився, а
            # статус лишився активним) — повертаємо його в чергу, інакше
            # виконання не рухатиметься ніколи.
            #
            # Перевірка навмисно ЧАСОВА, а не миттєва. Раніше умова
            # «агент не busy» спрацьовувала в проміжку між ``mark_running``
            # і фактичним стартом потоку агента: крок повертався в чергу
            # просто під час роботи, і панель показувала «готово до
            # запуску» замість «виконується». Тепер крок вважаємо завислим,
            # лише якщо він активний довше за ``STALE_STEP_SECONDS``.
            now = time.time()
            running_task = self.task_queue.get(self.task_queue.running_id) \
                if self.task_queue.running_id else None
            # ── Виконавець «зайнятий» кроком, якого агент уже не виконує ──
            # ``QueueExecutor.busy`` — це «``current_id`` вказує на активну
            # задачу». Якщо колбек завершення не дійшов, ``current_id``
            # лишається виставленим, ``busy`` — True, ``next_task()``
            # повертає None, і черга стоїть НАЗАВЖДИ: жоден із запобіжників
            # нижче не спрацьовує (вони всі під ``not self.executor.busy``).
            # Заміряно ``tools/check_stability.py``: прогін 3 із 3 завмер
            # на 150 с із «active 1, pending 5».
            if (running_task is not None and not self.agent.busy
                    and self.executor.current_id
                    and self.executor.current_id == running_task.id):
                started = float(running_task.started_at or 0.0)
                stuck_for = (now - started) if started else 0.0
                if stuck_for > self.STALE_STEP_SECONDS:
                    LOG.info("Виконавець застряг на кроці %s (%.0f с) — "
                             "звільняю", running_task.id, stuck_for)
                    self.executor.current_id = ""
                    self._plan_step_active = False
                    self._running_task_id = ""
            if running_task is not None and not self.agent.busy:
                started = float(running_task.started_at or 0.0)
                stale_for = (now - started) if started else 0.0
                if stale_for > self.STALE_STEP_SECONDS:
                    # ── Застряглий прапорець кроку ─────────────────────────
                    # ``_plan_step_active`` скидається в ``_on_agent_finished``.
                    # Якщо агент завершився, а колбек не дійшов (виняток у
                    # потоці, скасування посеред ходу), прапорець лишався
                    # True — і умова нижче НІКОЛИ не виконувалась: крок
                    # висів активним, черга стояла. У живому прогоні так
                    # завмер крок 2 на 150 с, а крок 1 при цьому вже
                    # створив файл.
                    if self._plan_step_active:
                        LOG.info("Прапорець кроку застряг (%.0f с) — скидаю",
                                 stale_for)
                        self._plan_step_active = False
                        self._running_task_id = ""
                    if not self.executor.busy:
                        stale = self.task_queue.requeue_running()
                        if stale is not None:
                            LOG.info("Завислий крок %s повернуто в чергу "
                                     "(активний %.0f с)", stale.id, stale_for)
                            self._update_queue_badge()
        except Exception:  # noqa: BLE001 - прибирання не має ламати вікно
            LOG.debug("Не вдалось перевірити завислий крок", exc_info=True)
        try:
            if self.winfo_exists():
                self._queue_pump_after = (self.after(1200, self._queue_pump) if self._timer_alive() else None)
        except tk.TclError:
            self._queue_pump_after = None

    def run_next_task(self, task: Optional[queue_engine.QueueTask] = None) -> None:
        """Запустити задачу з черги (наступну або конкретну).

        ``task`` передає автономний режим, коли вже обрав задачу й показав
        план: інакше між «обраним» і «запущеним» стан черги міг змінитись.

        Виконання йде через :class:`task_executor.QueueExecutor`: він
        перевіряє залежності, веде лічильник спроб і сам ставить статуси.
        """
        if self.agent.busy:
            self.set_status("Агент зайнятий — задача стартує після завершення поточної.")
            return
        # Без теки проєкту задачу не запускаємо. Перевірка стоїть ДО
        # ``mark_running``: інакше відмова шлюзу в ``chat._send`` лишала б
        # задачу в стані «в роботі» назавжди, і черга більше не рухалась би.
        if not self.has_project():
            # Паузи НЕ ставимо: вона лишилась би й після вибору теки, і черга
            # мовчки стояла б. Достатньо не запускати задачу — насос
            # ``_queue_pump`` сам не чіпає чергу, поки проєкту немає.
            self._show_project_gate(
                reason="Вибери теку проєкту — і черга продовжить роботу.")
            self.set_status("Черга чекає: спершу вибери папку проєкту.")
            return
        if task is not None:
            # Конкретну задачу (від автономного режиму) запускаємо напряму.
            self.executor.start(task)
            self._update_queue_badge()
            return
        # Автономний режим міг покласти задачу в чергу — виконавець знайде
        # найпершу ГОТОВУ (з виконаними залежностями).
        started = self.executor.start_next()
        if started is None:
            blocked = self.task_queue.waiting_on_dependencies(
                chat_id=self._active_chat_id())
            if blocked:
                self.set_status(
                    f"Черга чекає на попередні кроки: {len(blocked)}.")
            else:
                self.set_status("Черга порожня або на паузі.")
        self._update_queue_badge()

    def _skill_prompt(self, skill: skills_module.Skill) -> str:
        return (f"Застосуй скіл «{skill.name}».\n\n"
                f"Опис: {skill.description}\n\nІнструкція:\n{skill.body.strip()}")

    def _verify_task_result(self, text: str) -> tuple[bool, str]:
        """Перевірити, що задача черги справді дала результат на диску.

        Головна пастка локальних моделей: у відповіді написано «Файл
        створено», а на диску його немає. Тому задачу, яка згадує шлях до
        файлу, не зараховуємо, поки цього файлу не існує.

        Повертає (успіх, пояснення).
        """
        answer = text or ""
        if not answer.strip():
            return False, "порожня відповідь"
        # Шукаємо згадані шляхи з розширенням файлу.
        #
        # Раніше тут був ЖОРСТКИЙ список розширень (``js|json|html|css|ejs|
        # env|db|md``) — і в ньому не було ``py``. Тобто відповідь «створив
        # greeting.py» вважалась такою, що не згадує файлів, і крок
        # зараховувався навіть тоді, коли файлу на диску не було. Тепер
        # беремо будь-яке розширення, а службові слова відсіюємо нижче.
        mentioned = set()
        for match in re.finditer(r"[\w./\\-]+\.[A-Za-z][A-Za-z0-9]{0,7}\b", answer):
            name = match.group(0).replace("/", "\\").lstrip(".\\")
            # ``1.5``, ``v1.2``, ``3.14`` — це числа, а не файли.
            if re.fullmatch(r"[\d.\\-]+", name):
                continue
            mentioned.add(name)
        mentioned = {name for name in mentioned if len(name) > 3}
        if not mentioned:
            # Файлів не згадано — задача була не про створення файлу.
            return True, ""
        root = Path(self.settings.workspace)
        missing = []
        for name in sorted(mentioned):
            candidate = root / name
            if not candidate.exists():
                # Модель могла вказати лише ім'я без папки.
                if not any(p.name == Path(name).name
                           for p in root.rglob(Path(name).name)):
                    missing.append(name)
        if len(missing) == len(mentioned):
            return False, "файлів немає на диску: " + ", ".join(missing[:3])
        return True, ""

    def _on_agent_finished(self, ok: bool, text: str) -> None:
        """Агент завершив роботу — закриваємо поточний крок плану.

        Викликається з ПОТОКУ агента. ``TaskQueue._changed`` кличе
        ``queue_panel.refresh``, а це віджети tkinter — з чужого потоку вони
        кидають «main thread is not in main loop» і оновлення губиться.
        Тому на час зміни відчіплюємо колбек, а панель оновлюємо через чергу
        головного циклу.

        Статус ставить виконавець: він перевіряє результат
        (:class:`task_executor.TaskValidator`) і лише тоді закриває крок
        як «готово». Модель не може оголосити успіх сама.
        """
        task_id = getattr(self, "_running_task_id", "")
        if not task_id:
            return
        self._running_task_id = ""
        # Задачу про файли не зараховуємо без файлу на диску — інакше черга
        # показує «готово» там, де роботи не сталося.
        verified, reason = self._verify_task_result(text)
        if ok and not verified:
            ok = False
            LOG.info("Задача %s не підтверджена: %s", task_id, reason)
        saved = self.task_queue.on_change
        self.task_queue.on_change = None
        try:
            if getattr(self, "_plan_step_active", False):
                # Крок плану закриває виконавець — з перевіркою результату
                # й записом змінених файлів у журнал кроку.
                self._plan_step_active = False
                files = self._collect_changed_files(task_id)
                self.executor.finish(
                    ok, text,
                    changed=files,
                    error=(text or reason or "крок завершився з помилкою"),
                )
            elif ok:
                self.task_queue.mark_done(task_id, text)
            else:
                self.task_queue.mark_failed(task_id, text or reason or "невідома помилка")
        finally:
            self.task_queue.on_change = saved
        self._ui_call(self._after_task_finished, ok)

    def _collect_changed_files(self, task_id: str) -> list[str]:
        """Файли, які агент справді записав під час цього кроку."""
        task = self.task_queue.get(task_id)
        if task is None:
            return []
        names = [str(name) for name in task.files_changed if str(name).strip()]
        # Додатково — з журналу викликів write_file/edit_file.
        names.extend(task_executor.files_from_history(task.history))
        # Лишаємо тільки те, що СПРАВДІ є файлом у проєкті: у тексті виклику
        # трапляються ``unittest.TestCase``, ``self.assertEqual`` та інші
        # атрибути коду, і вони потрапляли в «змінені файли» як вигадка.
        root = self._project_root()
        verified: list[str] = []
        for name in dict.fromkeys(names):
            clean = name.replace("/", "\\").lstrip(".\\")
            if not clean:
                continue
            # ``.bak`` — це власна копія редактора, а не результат роботи
            # агента: у звіті вона виглядала як змінений файл.
            if clean.lower().endswith(".bak"):
                continue
            if root is None:
                verified.append(clean)
                continue
            if (Path(root) / clean).is_file():
                verified.append(clean)
                continue
            short = Path(clean).name
            if any(p.is_file() for p in Path(root).rglob(short)):
                verified.append(clean)
        return verified

    def _speak_answer(self, text: str) -> None:
        """Озвучити текст відповіді (якщо це ввімкнено)."""
        try:
            self._on_agent_answer_for_voice(text)
        except Exception:  # noqa: BLE001 - голос не має ламати роботу
            LOG.warning("Озвучення відповіді не вдалось", exc_info=True)

    def _after_task_finished(self, ok: bool) -> None:
        self._update_queue_badge()
        self._set_agent_state("готово" if ok else "помилка")
        # Етап у смузі над композером рухається разом із задачею черги:
        # «виконується» → «готово», а наступний стає поточним.
        #
        # ``ok`` передаємо КЛЮЧЕМ: ``advance_stage`` приймає лише
        # ``*, ok`` (позиційний виклик кидав TypeError, і етапи не рухались
        # зовсім — збій було видно лише в журналі прихованих збоїв).
        safe.call_quiet(self.chat.advance_stage, ok=ok,
                        where="рух етапів задачі")
        # Черга: наступні задачі позначають сесію як queued.
        pending = [t for t in self.task_queue.tasks
                   if t.status in {queue_engine.PENDING, queue_engine.RUNNING}]
        chat = self.chat_store.active()
        if chat is not None and pending:
            self.chat_store.set_status(chat.id, "queued")
            self.chat_list.update_row_status(chat.id, "queued")
        self._maybe_continue_plan(ok)

    def _maybe_continue_plan(self, ok: bool) -> None:
        """Перейти до наступного кроку плану або завершити роботу звітом.

        Автопродовження — основна вимога: користувач дав одне велике
        завдання, і агент має пройти план сам. Пауза зупиняє це, але не
        втрачає прогрес.
        """
        if not self.settings.agent.queue_auto_run:
            return
        if self._autonomous_stop_pending:
            return
        owner = self._active_chat_id()
        plan = self.task_queue.plan_tasks(chat_id=owner)
        if not plan:
            return
        running = [t for t in self.task_queue.tasks if t.active]
        if running or self.task_queue.paused:
            self.task_center.refresh()
            return
        ready = self.task_queue.next_pending(chat_id=owner)
        if ready is not None:
            # Наступний крок стартує в наступному тіку головного циклу, щоб
            # інтерфейс устиг перемалювати статус попереднього.
            self.after(120, self._start_plan_execution)
            return
        # Більше готових кроків немає: або все завершено, або лишились
        # заблоковані (їхні залежності впали) — тоді показуємо звіт.
        if all(t.settled for t in plan):
            self._finish_plan()

    def _finish_plan(self) -> None:
        """Показати підсумок і прибрати смугу етапів."""
        report = self.executor.report(chat_id=self._active_chat_id())
        try:
            self.chat._note(report)
        except (tk.TclError, AttributeError):
            LOG.debug("Звіт не потрапив у чат", exc_info=True)
        try:
            self.chat.finish_stages(ok=True)
        except (tk.TclError, AttributeError):
            pass
        progress = self.task_queue.progress()
        self.set_status(
            f"План завершено: {progress['done']} з {progress['total']} кроків"
            + (f", помилок {progress['errors']}" if progress["errors"] else ""))
        self.task_center.refresh()
        LOG.info("План завершено: %s", progress)

    def _set_agent_state(self, state: str) -> None:
        colours = {
            "очікує": theme.FG_FAINT,
            "працює": theme.ACCENT,
            "готово": theme.SUCCESS,
            "помилка": theme.ERROR,
        }
        try:
            self.agent_label.configure(text=f"агент: {state}",
                                       fg=colours.get(state, theme.FG_FAINT))
        except tk.TclError:
            pass

    def _show_queue_task(self, task: queue_engine.QueueTask) -> None:
        text = f"{task.status}\n\n{task.text}"
        if task.result:
            text += f"\n\n--- результат ---\n{task.result}"
        if task.error:
            text += f"\n\n--- помилка ---\n{task.error}"
        self.chat._note(text, kind="error" if task.error else "info")

    # ── живі дані для колонки контексту ────────────────────────────────────
    def _agent_status_text(self) -> str:
        """Що робить агент просто зараз (з реального стану)."""
        active = next((t for t in self.task_queue.tasks if t.active), None)
        if active is not None:
            label = f"{active.number:02d}" if active.number else "—"
            step = task_executor.describe_status(active)
            return f"працює · крок {label} · {step[:48]}"
        if self.agent.busy:
            return "працює · відповідає на запит"
        progress = self.task_queue.progress()
        if self.task_queue.paused:
            return "пауза · черга зупинена"
        if progress["errors"]:
            return f"помилка · кроків з помилкою {progress['errors']}"
        if progress["pending"]:
            waiting = self.task_queue.waiting_on_dependencies(
                chat_id=self._active_chat_id())
            if waiting and len(waiting) == progress["pending"]:
                return f"очікує · чекає на попередні кроки"
            return f"очікує · у черзі {progress['pending']} кроків"
        if progress["total"] and progress["done"] == progress["total"]:
            return f"завершено · усі {progress['total']} кроків"
        return "очікує завдання"

    def _model_summary(self) -> tuple[str, str]:
        """Назва поточної моделі й вид підключення (локальна / хмара).

        Вид визначаємо за АДРЕСОЮ, а не за наявністю налаштувань хмари:
        раніше локальна модель на 127.0.0.1:8080 показувалась як «хмара»,
        щойно в налаштуваннях лишався будь-який запис хмарного провайдера.
        """
        name = str(getattr(self.settings.llm, "model", "") or "").strip()
        if not name:
            return "не вибрана", "натисни, щоб вибрати"
        base_url = str(getattr(self.settings.llm, "base_url", "") or "").lower()
        # Вбудований рушій живе в цьому ж процесі — це найлокальніше, що буває,
        # але його адреса (``native://blackchpok``) не містить жодного
        # локального маркера, тому перевіряємо схему ОКРЕМО.
        if base_url.startswith(("native://", "inproc://", "blackchpok://")):
            state = "online" if self.native_runtime.engine.loaded else "не завантажена"
            return name, f"вбудований рушій · {state}"
        is_local = any(marker in base_url for marker in (
            "127.0.0.1", "localhost", "0.0.0.0", "::1", "192.168.", "10."))
        if is_local:
            kind = "локальна · online" if self._server_alive() else "локальна · offline"
        else:
            cloud = getattr(self.settings.cloud, "provider", "") \
                if hasattr(self.settings, "cloud") else ""
            kind = f"хмара · {cloud}" if str(cloud).strip() else "хмара"
        return name, kind

    def _context_usage(self) -> tuple[int, int]:
        """(використано, ліміт) токенів контексту з реальної статистики."""
        try:
            stats = self.chat.stats_bar.stats
            used = int(stats.prompt_tokens or 0)
            limit = int(stats.context_limit or 0)
            return used, limit
        except (AttributeError, TypeError, ValueError):
            return 0, 0

    def _active_tool_names(self) -> list[str]:
        """Інструменти, реально доступні агенту в поточному режимі.

        ``probe_window=False``: це ІНТЕРФЕЙСНА довідка (скільком схемам
        вистачило місця), і вона оновлюється кілька разів на секунду.
        Визначення вікна робить мережевий запит, тож у головному потоці
        його не робимо — інакше перший кадр чекав до 1 с (заміряно).
        """
        try:
            schemas = self.agent.tool_schemas(probe_window=False)
        except Exception:  # noqa: BLE001 - панель не має падати
            return []
        names = []
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if isinstance(function, dict) and function.get("name"):
                names.append(str(function["name"]))
        return names

    def _registry_state_for_panel(self) -> dict:
        """Стан реєстру інструментів для панелі контексту (реальні числа)."""
        try:
            return self.agent.tool_registry_state()
        except (AttributeError, TypeError):
            return {}

    def _counter_is_exact(self) -> bool:
        """Чи підраховуються токени справжнім tokenizer моделі."""
        from . import context_stats as context_stats_module

        try:
            return bool(context_stats_module.estimate_is_exact())
        except (AttributeError, TypeError):
            return False

    def _budget_state_for_panel(self) -> dict:
        """Розподіл бюджету контексту (вікно/відповідь/історія/схеми)."""
        budget = getattr(self.agent, "_context_budget", None)
        if budget is None:
            return {}
        return {
            "window": int(getattr(budget, "window", 0) or 0),
            "answer": int(getattr(budget, "answer", 0) or 0),
            "history": int(getattr(budget, "history", 0) or 0),
            "tools": int(getattr(budget, "tools", 0) or 0),
            "system": int(getattr(budget, "system", 0) or 0),
            "safety": int(getattr(budget, "safety", 0) or 0),
        }

    # ── RAG ────────────────────────────────────────────────────────────────
    def _insert_rag_context(self, text: str) -> None:
        """Покласти знайдений фрагмент у поле запиту як контекст."""
        clean = (text or "").strip()
        if not clean:
            return
        try:
            self.chat.insert_context(clean)
        except (tk.TclError, AttributeError):
            return
        self.show_chat(True)
        self.set_status("Фрагмент додано в запит.")

    def refresh_rag_status(self) -> None:
        """Оновити стан RAG після зміни робочої теки."""
        try:
            self.rag_service.set_root(Path(self.settings.workspace))
            self.rag_panel.refresh_status()
        except (tk.TclError, AttributeError):
            pass

    def _on_tool_result(self, output: str, ok: bool) -> None:
        """Результат ручного виклику інструмента — показати в чаті."""
        head = (output or "").strip()
        if not head:
            return
        try:
            self.chat._note(("✓ " if ok else "✗ ") + head[:800],
                            kind="info" if ok else "error")
        except (tk.TclError, AttributeError):
            pass

    # ── сайт проєкту: агент підняв — показуємо одразу ──────────────────────
    def _show_site_if_started(self, name: str, ok: bool, text: str) -> None:
        """Показати сайт у панелі «Сайт», коли агент його запустив.

        Користувач просив: «агент коли пише сайт вмів вмикати браузер і
        показувати мені наглядно готовий продукт». Раніше ``app_start``
        піднімав сервер, але панель про це не знала — сайт жив у фоні,
        і людина не бачила результату, доки не натисне «Сайт» вручну.

        Викликається з обробника подій агента, тому нічого не робить,
        якщо інструмент не про сайт або якщо запуск не вдався.
        """
        if not ok or name not in ("app_start", "app_restart", "project_screenshot"):
            return
        live = getattr(self, "live_preview", None)
        controller = getattr(self, "app", None)
        if live is None or controller is None:
            return
        try:
            url = controller.url
        except Exception:                            # noqa: BLE001
            url = ""
        if not url:
            return
        # Показуємо панель і відкриваємо адресу — людина одразу бачить
        # свій сайт і може натискати кнопки, як у звичайному браузері.
        try:
            self.show_bottom("site")
            live.open_url(url)
            self.set_status(f"Сайт проєкту відкрито: {url}")
        except (tk.TclError, AttributeError):
            LOG.debug("Панель «Сайт» не відкрилась", exc_info=True)
        del text

    # ── справи: живі кроки роботи агента ───────────────────────────────────
    def _case_begin(self, text: str) -> None:
        """Новий запит — відкриваємо справу й розгортаємо її в панелі."""
        self.case_book.begin(text)
        try:
            self.cases_panel.expand_active()
            self.cases_panel.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _case_on_event(self, event) -> None:
        """Перекласти подію агента в крок справи."""
        kind = getattr(event, "kind", "")
        text = (getattr(event, "text", "") or "").strip()
        data = getattr(event, "data", {}) or {}
        # Крок плану черги веде власний журнал: кожна реальна дія агента
        # потрапляє в нього, щоб картка «що зробила модель» показувала
        # справжні виклики й результати, а не переказ відповіді.
        # ``getattr`` потрібен, бо метод викликають і тести на «заглушці»
        # без повного стану вікна.
        if getattr(self, "_plan_step_active", False):
            self._note_plan_activity(kind, text, data)
        try:
            if kind == "status":
                if text:
                    # «Запит до моделі…» — окрема віха, не крок інструмента.
                    self.case_book.add_step(text)
            elif kind == "tool_call":
                self.case_book.add_step(text or f"{data.get('name', 'інструмент')}",
                                        key=str(data.get("call_id") or ""))
            elif kind == "tool_result":
                self.case_book.finish_step(
                    key=str(data.get("call_id") or ""),
                    text=data.get("name") or "",
                    ok=bool(data.get("ok", True)),
                )
                # Агент запустив застосунок — одразу показуємо прев'ю.
                if (str(data.get("name")) == "app_start"
                        and bool(data.get("ok", False))):
                    self._ui_call(self._auto_show_preview)
            elif kind == "tool_call":
                # Готуємось до скріншота: прев'ю має бути видимим.
                if str(data.get("name")) == "app_screenshot":
                    self._ui_call(self._auto_show_preview)
            elif kind == "error":
                self.case_book.add_step(text or "Помилка", status=cases_panel.FAILED)
            elif kind == "done":
                ok = bool(data.get("ok", True))
                summary = getattr(self.chat.runner, "last_answer", "") if self.chat.runner else ""
                error = getattr(self.chat.runner, "last_error", "") if self.chat.runner else ""
                self.case_book.end(ok=ok, summary=summary, error=error)
        except Exception:  # noqa: BLE001 - справи не мають ламати агента
            LOG.debug("Не вдалось оновити справу", exc_info=True)

    def _note_plan_activity(self, kind: str, text: str,
                            data: dict) -> None:
        """Записати реальну дію агента в журнал поточного кроку черги."""
        task = self.executor.current
        if task is None:
            return
        try:
            if kind == "status" and text:
                self.executor.note_step(text)
            elif kind == "tool_call":
                name = str(data.get("name") or "")
                arguments = str(data.get("arguments") or "")
                label = f"{name}({arguments})" if arguments else name
                task.add_history("tool", label)
                self.executor.note_step(label, status=queue_engine.RUNNING)
            elif kind == "tool_result":
                name = str(data.get("name") or "інструмент")
                ok = bool(data.get("ok", True))
                head = " ".join((text or "").split())[:220]
                task.add_history("tool_ok" if ok else "tool_fail",
                                 f"{name}: {head}" if head else name)
                if name in ("write_file", "edit_file"):
                    self._collect_task_files(task, name, head)
            elif kind == "error" and text:
                task.add_history("error", text)
                self.executor.note_step(text, status=queue_engine.RUNNING)
            elif kind == "reasoning" and text:
                # Вимога: показувати КОРОТКИЙ СТАТУС етапу, а не внутрішні
                # приховані міркування моделі. Сирі reasoning-тексти вже
                # живуть у згорнутому журналі роботи в чаті (це наявна
                # функція), а в картці кроку має бути лише стислий підпис:
                # перше речення, обрізане до 90 символів.
                first = " ".join(text.split()).split(". ")[0][:90]
                self.executor.note_step(f"міркую: {first}", status=queue_engine.RUNNING)
            self.task_center.refresh()
        except Exception:  # noqa: BLE001 - журнал кроку не має ламати агента
            LOG.debug("Журнал кроку не оновився", exc_info=True)

    def _collect_task_files(self, task: queue_engine.QueueTask, tool: str,
                            text: str) -> None:
        """Додати до кроку файли, які агент справді записав.

        Беремо лише те, що СХОЖЕ на шлях до файлу:

        * імена відносно проєкту (у виводі буває повний шлях — його
          приводимо до відносного);
        * розширення з відомого переліку ``task_executor.CODE_SUFFIXES``.

        Раніше сюди потрапляло будь-що з крапкою — ``calc.add``,
        ``unittest.TestCase``, ``self.assertEq``. У звіті це виглядало як
        «змінені файли», і користувач бачив вигадані назви.
        """
        import re as _re

        root = self._project_root()
        suffixes = "|".join(
            _re.escape(item.lstrip("."))
            for item in task_executor.CODE_SUFFIXES)
        pattern = _re.compile(
            r"[\w./\\-]+\.(?:" + suffixes + r")\b", _re.IGNORECASE)
        written: list[str] = []
        for match in pattern.finditer(text or ""):
            name = match.group(0)
            if root is not None:
                candidate = Path(name)
                if candidate.is_absolute():
                    try:
                        name = str(candidate.relative_to(Path(root)))
                    except ValueError:
                        # Поза проєктом — лишаємо тільки ім'я файлу.
                        name = candidate.name
            name = name.replace("/", "\\").lstrip(".\\")
            if not name:
                continue
            # Службові «хвости» на кшталт ``unittest.TestCase`` або
            # ``self.assertEqual`` — це атрибути коду, а не файли. Файл
            # мусить існувати в проєкті (або мати типове розширення й
            # роздільник шляху), інакше це вигадка з тексту виклику.
            if root is not None:
                exists = (Path(root) / name).exists()
                if not exists:
                    found = next((p for p in Path(root).rglob(Path(name).name)
                                  if p.is_file()), None)
                    if found is None:
                        continue
            if name not in written:
                written.append(name)
        task.files_changed = list(dict.fromkeys(list(task.files_changed) + written))

    # ── скіли ──────────────────────────────────────────────────────────────
    # ── режим дозволів, ціль, відгук ───────────────────────────────────────
    def _on_permission_change(self, mode: str) -> None:
        """Режим дозволів змінився в композері — застосовуємо до агента й реєстру."""
        active = permissions.normalise_mode(mode)
        self.agent.permission_mode = active
        self.settings.agent.permission_mode = active
        self.settings.save()
        # «Питати дозвіл на команди» — окремий перемикач; у повному доступі
        # він лишається як є, в інших режимах команди й так обмежені.
        self.registry.confirm_commands = (self.settings.agent.confirm_commands
                                          and active != permissions.FULL)
        self.set_status(f"Дозволи: {permissions.label_for(active)}")

    def _set_goal(self, text: str) -> None:
        """Запам'ятати ціль сесії й показати її в заголовку чату."""
        goal = (text or "").strip()
        if not goal:
            return
        self.current_goal = goal
        # Блок «Поточна ціль» живе в картці глибокого аналізу.
        try:
            self.chat.set_goal(goal)
        except (tk.TclError, AttributeError):
            LOG.debug("Ціль не потрапила в картку аналізу", exc_info=True)
        chat = self.chat_store.active()
        if chat is not None:
            self.chat_store.append("system", f"Ціль сесії: {goal}")
            self.chat_list.refresh()
        self.set_status(f"Ціль: {goal[:80]}")
        try:
            self.chat._note(f"Ціль сесії: {goal}")
        except (tk.TclError, AttributeError):
            pass

    def _save_feedback(self, text: str) -> None:
        """Зберегти відгук про сесію у файл поруч із налаштуваннями."""
        from .config import app_data_dir

        target = app_data_dir() / "feedback.md"
        stamp = time.strftime("%Y-%m-%d %H:%M")
        try:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(f"\n## {stamp}\n{text.strip()}\n")
            self.set_status(f"Відгук збережено: {target}")
        except OSError as exc:
            self.set_status(f"Не вдалось зберегти відгук: {exc}")

    # ── модель для поточного чату ──────────────────────────────────────────
    # ── голос ──────────────────────────────────────────────────────────────
    def _apply_voice_settings(self) -> None:
        """Передати налаштування голосу у віджет кнопки."""
        cfg = self.settings.voice
        try:
            vs = self.chat.voice_settings
            vs.enabled = bool(cfg.enabled)
            vs.auto_send = bool(cfg.auto_send)
            vs.speak_replies = bool(cfg.speak_replies)
            vs.language = cfg.language or "uk-UA"
            vs.whisper_dir = cfg.whisper_dir
            vs.model_path = cfg.model_path
            vs.seconds = float(cfg.seconds or 5.0)
        except (tk.TclError, AttributeError):
            pass

    def _on_voice_query(self, text: str) -> None:
        """Розпізнану фразу надіслати агенту."""
        self.show_chat(True)
        self._set_agent_state("працює")
        self.chat._send(text)

    def _on_voice_action(self, action: str) -> None:
        """Голосова команда інтерфейсу."""
        if action == "files":
            self.show_side("explorer")
        elif action == "terminal":
            self.show_bottom("terminal")

    def _on_agent_answer_for_voice(self, text: str) -> None:
        """Озвучити відповідь, якщо голос увімкнено."""
        if not self.settings.voice.speak_replies and not getattr(self.chat, "speak_last", False):
            return
        self.chat.speak_text(text)

    def _on_chat_model_pick(self, name: str) -> None:
        """Модель обрана для цього чату — застосувати до агента й зберегти.

        ВАЖЛИВО про узгодженість. Раніше тут змінювався ЛИШЕ
        ``llm.model``, а ``engine.model_path`` лишався вказувати на іншу
        модель. Саме так у налаштуваннях опинились «Ministral» в одному
        полі й «qwen2.5-coder-14b» у другому — і вікно показувало обидві.

        Тепер обидва поля узгоджуються, якщо модель є локальним файлом.
        """
        name = (name or "").strip()
        if not name:
            return
        self.settings.llm.model = name
        # ── Узгодити шлях до файлу моделі ─────────────────────────────────
        # ``engine.model_path`` — це те, що СПРАВДІ завантажує рушій. Якщо
        # він вказує на інший файл, ніж вибрана модель, інтерфейс показує
        # одну модель, а працює інша.
        self._adopt_model_path_for(name)
        self.agent.llm_settings = self.settings.llm
        self.settings.save()
        self._invalidate_model_state(reason=f"вибір моделі {name}")
        self._apply_context_limit()
        chat = self.chat_store.active()
        if chat is not None:
            chat.model = name
            self.chat_store.save()
        # Один підпис моделі — в усіх віджетах.
        self._sync_model_labels()
        self.set_status(f"Модель цього чату: {name}")

    def _adopt_model_path_for(self, name: str) -> bool:
        """Знайти файл моделі за назвою й записати його в ``engine.model_path``.

        Повертає True, якщо шлях оновлено. Якщо файлу немає (хмарна модель
        або назва без відповідника) — шлях ОЧИЩАЄТЬСЯ: краще «не задано»,
        ніж шлях до зовсім іншої моделі, який рушій завантажить замість
        вибраної.
        """
        wanted = (name or "").strip().lower()
        if not wanted:
            return False
        candidates: list[Path] = []
        try:
            candidates = list(hub.local_models())
        except Exception:  # noqa: BLE001 - диск може бути недоступний
            LOG.debug("Локальні моделі недоступні", exc_info=True)
        exact = [path for path in candidates if path.stem.lower() == wanted]
        if not exact:
            exact = [path for path in candidates
                     if wanted in path.stem.lower()]
        current = self.settings.engine.model_path
        if exact:
            chosen = exact[0]
            if str(current) != str(chosen):
                LOG.info("Шлях моделі узгоджено: %s → %s", current, chosen.name)
            self.settings.engine.model_path = str(chosen)
            return True
        # Файлу немає: шлях до іншої моделі лишати не можна.
        if current and Path(str(current)).stem.lower() != wanted:
            LOG.info("Шлях моделі очищено: він вказував на %s, а вибрано %s",
                     Path(str(current)).name, name)
            self.settings.engine.model_path = ""
        return False

    def _on_chat_effort_pick(self, key: str) -> None:
        """Рівень зусилля для reasoning-моделей."""
        level = effort.get(key)
        self.settings.llm.reasoning_effort = level.key
        if not level.is_default and level.temperature is not None:
            self.settings.llm.temperature = level.temperature
        self.settings.save()
        chat = self.chat_store.active()
        if chat is not None:
            meta = getattr(chat, "effort", "")
            setattr(chat, "effort", level.key)
            self.chat_store.save()
        self.set_status(f"Зусилля моделі: {level.label}")

    def _sync_chat_model(self) -> None:
        """Підставити модель поточного чату (або типову) у композер."""
        chat = self.chat_store.active()
        model = (getattr(chat, "model", "") if chat is not None else "") or self.settings.llm.model
        effort_key = (getattr(chat, "effort", "") if chat is not None else "") or "default"
        try:
            self.chat.set_chat_model(model, effort_key)
            self.chat.set_available_models(self._known_models())
        except (tk.TclError, AttributeError):
            pass

    def _known_models(self) -> list[str]:
        """Відомі моделі: з провайдера + поточна + локальні."""
        models: list[str] = []
        cloud = getattr(self.settings, "cloud", None)
        if cloud is not None and getattr(cloud, "provider", ""):
            models.extend(cloud_agents.models_for(cloud.provider))
        try:
            models.extend("" if not p.name else p.stem for p in hub.local_models())
        except Exception:  # noqa: BLE001
            LOG.debug("Не вдалось прочитати локальні моделі", exc_info=True)
        current = self.settings.llm.model
        if current and current not in models:
            models.insert(0, current)
        seen: set[str] = set()
        unique: list[str] = []
        for name in models:
            if name and name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    def export_current_chat(self) -> None:
        """Експорт поточної розмови у Markdown."""
        chat = self.chat_store.active()
        if chat is None:
            self.set_status("Немає активної розмови для експорту.")
            return
        from tkinter import filedialog

        target = filedialog.asksaveasfilename(
            parent=self, title="Експорт журналу сесії", defaultextension=".md",
            initialfile=f"{(chat.title or 'chat')[:40]}.md",
            filetypes=[("Markdown", "*.md"), ("Усі файли", "*.*")],
        )
        if not target:
            return
        try:
            Path(target).write_text(self.chat_store.export_markdown(chat.id),
                                    encoding="utf-8")
            self.set_status(f"Експортовано: {target}")
        except OSError as exc:
            self.set_status(f"Не вдалось зберегти: {exc}")

    def _use_skill_by_name(self, name: str) -> None:
        skill = self.skill_book.get(name)
        if skill is None:
            self.set_status(f"Скіла «{name}» не знайдено.")
            return
        self._use_skill(skill)

    def _use_skill(self, skill: skills_module.Skill) -> None:
        self.show_chat(True)
        self.chat._send(self._skill_prompt(skill))
        self.set_status(f"Скіл «{skill.name}» надіслано агенту.")

    # ── файли ──────────────────────────────────────────────────────────────
    def open_folder_dialog(self) -> None:
        """Вибрати теку проєкту й одразу підключити її.

        ``initialdir`` має вказувати на СПРАВЖНЮ теку: якщо збережена тека
        зникла (флешка, перенесений проєкт), діалог на Windows тихо не
        відкривався й кнопка «Вибрати папку» виглядала мертвою.
        """
        start = str(self.settings.workspace or "")
        if not start or not Path(start).is_dir():
            start = str(Path.home())
        folder = filedialog.askdirectory(parent=self, title="Вибрати папку проєкту",
                                         initialdir=start, mustexist=True)
        if not folder:
            # Користувач скасував — це не помилка, але екран має це сказати.
            gate = getattr(self, "project_gate", None)
            if gate is not None:
                try:
                    gate.set_hint("Теку не вибрано. Спробуй ще раз.")
                except (tk.TclError, AttributeError):
                    pass
            return
        self.set_workspace(Path(folder))

    def _autonomous_other_project(self, folder: Path) -> bool:
        """Чи автономний режим зараз працює для ІНШОЇ теки."""
        engine = getattr(self, "autonomous_engine", None)
        if engine is None or not engine.active or engine.project is None:
            return False
        try:
            return engine.project.resolve() != Path(folder).resolve()
        except OSError:
            return True

    def _confirm_autonomous_project_switch(self, folder: Path) -> bool:
        """Спитати підтвердження перед зміною теки під автономним режимом."""
        engine = self.autonomous_engine
        current = engine.project.name if engine.project else "?"
        answer = messagebox.askyesno(
            "Автономний режим",
            f"Автономний режим працює для «{current}».\n\n"
            f"Перейти на «{folder.name}»? Режим буде ЗУПИНЕНО, і його задачі "
            f"знімуться з черги — агент не правитиме файли іншого проєкту.",
            parent=self)
        if not answer:
            self.set_status("Зміну проєкту скасовано: автономний режим працює далі.")
        return bool(answer)

    def set_workspace(self, folder: Path) -> None:
        folder = Path(folder).resolve()
        if not folder.is_dir():
            messagebox.showerror("Папка", f"Не існує: {folder}", parent=self)
            return
        # Автономний режим прив'язаний до теки: мовчки переносити його на
        # інший проєкт небезпечно — агент почав би правити чужі файли без
        # відома користувача. Тому спершу зупиняємо й питаємо підтвердження.
        if self._autonomous_other_project(folder):
            if not self._confirm_autonomous_project_switch(folder):
                return
            self.stop_autonomous()
        self.settings.remember_workspace(str(folder))
        self.settings.save()
        self.registry.set_root(folder)
        self.agent.set_workspace(folder)
        self.file_tree.set_root(folder)
        self.terminal.set_cwd(folder)
        self.skill_book.set_root(folder)
        self.skills_panel.refresh()
        self.ws_label.configure(text=str(folder))
        # `os.chdir` тут БУВ, але він змінює робочу теку ВСЬОГО процесу:
        # це ламає будь-яке паралельне використання пакета як бібліотеки
        # й робить поведінку залежною від порядку дій. Усі підсистеми
        # (термінал, web-сервер, інструменти) отримують теку явно —
        # `set_cwd`/`cwd=`, тож глобальна зміна не потрібна.
        self.title(f"{APP_NAME} {APP_VERSION} — {folder.name}")
        self._refresh_context()
        self.refresh_rag_status()
        self.after(300, self._load_mcp_async)
        self.set_status(f"Відкрито проєкт: {folder}")
        self._refresh_header()
        # Проєкт вибрано — тепер чат можна відкривати. Якщо користувач
        # прийшов сюди з екрана вибору, повертаємо його в розмову.
        self._close_project_gate()
        if not self.chat_store.active():
            self.new_chat_session()

    def open_recent_folder(self, folder: str) -> None:
        """Відкрити проєкт зі списку останніх (меню проєкту в шапці)."""
        path = Path(str(folder or "").strip())
        if not path.is_dir():
            self.set_status(f"Теки більше немає: {folder}")
            # Прибираємо «мертвий» пункт, щоб меню не пропонувало неіснуючу теку.
            try:
                if str(path) in self.settings.recent:
                    self.settings.recent.remove(str(path))
                    self.settings.save()
            except Exception:  # noqa: BLE001 - чистка меню не критична
                LOG.debug("Не вдалось прибрати теку з останніх", exc_info=True)
            return
        self.set_workspace(path)

    # ── профілі робочого простору ──────────────────────────────────────────
    def apply_profile(self, profile) -> None:
        """Застосувати готовий профіль розкладки.

        Профіль змінює ЛИШЕ розміри й видимість панелей. Він не чіпає
        відкритих файлів, чатів і черги — це компонування, а не стан роботи.
        """
        if profile is None:
            return
        # Публічний метод: рядок або словник (з JSON налаштувань) не має
        # валити вікно з ``'str' object has no attribute 'sidebar_width'``.
        if isinstance(profile, str):
            profile = getattr(layout_profiles, profile.upper(), None)
        if isinstance(profile, dict):
            # Неповний словник (з JSON) не має валити вікно: LayoutProfile
            # вимагає ще key/label/tip, які для застосування не потрібні.
            try:
                profile = layout_profiles.LayoutProfile(**profile)
            except TypeError:
                return
        if profile is None or not hasattr(profile, "sidebar_width"):
            return
        ui = self.settings.ui
        if profile.sidebar_width:
            ui.sidebar_width = int(profile.sidebar_width)
            self.layout.set("sidebar_width", profile.sidebar_width)
        ui.chat_width = int(profile.chat_width)
        if profile.context_width:
            ui.context_width = int(profile.context_width)
            self.layout.set("context_width", profile.context_width)
        if profile.preview_width:
            self.layout.set("preview_width", profile.preview_width)
        if profile.bottom_height:
            ui.bottom_height = int(profile.bottom_height)
            self.layout.set("bottom_height", profile.bottom_height)
        ui.chat_visible = bool(profile.chat_visible)
        ui.context_visible = bool(profile.context_visible)
        ui.bottom_visible = bool(profile.bottom_visible)

        # Панелі: показати те, що в профілі, сховати решту.
        self.show_chat(profile.chat_visible)
        self.toggle_sidebar(profile.sidebar_width > 0)
        self.toggle_context(profile.context_visible)
        self.toggle_preview(profile.preview_visible)
        self._bottom_height = max(120, int(profile.bottom_height or 0))
        self.toggle_bottom(profile.bottom_visible)
        if profile.sidebar_width:
            try:
                self.sidebar.configure(width=int(profile.sidebar_width))
            except tk.TclError:
                pass
        self._apply_responsive()
        self._apply_sash_positions()
        self._remember_layout()
        self._refresh_header()
        self.set_status(f"Профіль робочого простору: {profile.label}")

    # ── Live Browser (окрема робоча область з поділом екрана) ──────────────
    def open_live_browser(self, url: str = "") -> bool:
        """Відкрити Live Browser: сайт праворуч, код і чат ліворуч.

        Це не «ще одна вкладка браузера», а робочий режим: ліва частина —
        редактор і діалог з агентом, права — запущений сайт. Співвідношення
        можна тягнути мишею (саш), і воно запам'ятовується.
        """
        # 1. Права колонка з сайтом.
        self.toggle_preview(True)
        # 2. Сайт: якщо адресу не дали — беремо вже запущений локальний
        #    сервер або піднімаємо його для проєкту.
        target = str(url or "").strip()
        if not target:
            target = self._running_site_url()
        if not target:
            if not self.has_project():
                self._show_project_gate(
                    reason="Live Browser відкриється, щойно буде вибрано проєкт.")
                self.set_status("Спершу вибери теку проєкту.")
                return False
            started = self.start_site()
            target = self._running_site_url() if started else ""
        if target:
            self.open_url_in_browser(target)
        # 3. Зліва — файли й діалог: працювати з кодом поруч із результатом.
        self.show_side("explorer")
        self.show_chat(True)
        self.set_status("Live Browser: сайт праворуч, код і агент ліворуч. "
                        "Межу можна тягнути, ширину збережено.")
        return True

    def _running_site_url(self) -> str:
        """Адреса вже запущеного локального сайту (``""``, якщо не запущено)."""
        for holder in (getattr(self, "live_preview", None),
                       getattr(self, "preview", None)):
            url = getattr(holder, "url", "") if holder is not None else ""
            if url:
                return str(url)
        return ""

    def _browser_view(self):
        """Вбудований браузер (права колонка або нижня вкладка «Сайт»)."""
        live = getattr(self, "live_preview", None)
        view = getattr(getattr(live, "inner", None), "view", None)
        if view is not None:
            return view
        return getattr(getattr(self, "preview", None), "view", None)

    def _browser_hwnd(self) -> int:
        """Дескриптор вікна вбудованого браузера (0 — вікна немає).

        Потрібен, щоб агент знімав САМЕ вікно проєкту. Пошук «за заголовком
        Chrome» на машині користувача знаходив чуже вікно — саме тому в чаті
        з'являвся темний незрозумілий знімок замість його сайту.
        """
        view = self._browser_view()
        if view is None:
            return 0
        try:
            hwnd = int(getattr(view, "hwnd", 0) or 0)
        except (TypeError, ValueError):
            return 0
        return hwnd if hwnd else 0

    def _browser_cdp(self):
        """CDP-сесія вбудованого браузера для інструментів агента.

        Повертає ``None``, поки сторінки немає: інструмент тоді чесно каже
        «браузер не підключений» замість вигаданої відповіді.
        """
        view = self._browser_view()
        if view is None:
            return None
        try:
            return view.ensure_cdp()
        except Exception:  # noqa: BLE001 - інструмент не має ламати агента
            LOG.warning("CDP недоступний", exc_info=True)
            return None

    # ── інспектор елементів у Live Browser ─────────────────────────────────
    def _inspect_page_at(self, x: int, y: int) -> dict:
        """Прочитати елемент сторінки в точці (координати СТОРІНКИ)."""
        session = self._browser_cdp()
        if session is None:
            return {}
        try:
            return session.inspect_at(int(x), int(y))
        except Exception:  # noqa: BLE001 - інспектор не має ламати вікно
            LOG.warning("Інспектор сторінки впав", exc_info=True)
            return {}

    def _page_console(self) -> tuple[list[str], int]:
        """Консоль сторінки: (рядки, кількість помилок)."""
        session = self._browser_cdp()
        if session is None:
            return ([], 0)
        try:
            entries = session.console_entries()
            errors = session.errors_count()
            return ([entry.as_line() for entry in entries], errors)
        except Exception:  # noqa: BLE001
            LOG.warning("Консоль сторінки недоступна", exc_info=True)
            return ([], 0)

    def _page_action(self, name: str) -> str:
        """Дії над сторінкою для панелі прев'ю: знімок, аудит, адаптивність."""
        session = self._browser_cdp()
        if session is None:
            return "Браузер не підключений: запусти сайт кнопкою ▶."
        key = (name or "").strip().lower()
        try:
            if key == "screenshot":
                return self.registry.call("web_screenshot", {}).output
            if key == "audit":
                return self.registry.call("web_audit", {}).output
            if key == "responsive":
                return self.registry.call("web_responsive", {}).output
        except Exception as exc:  # noqa: BLE001 - дія не має ламати вікно
            LOG.warning("Дія сторінки «%s» впала", key, exc_info=True)
            return f"{type(exc).__name__}: {exc}"
        return f"Невідома дія: {name}"

    def inspect_element_at(self, x: int, y: int) -> dict:
        """Прочитати елемент сторінки в точці (для панелі прев'ю)."""
        return self._inspect_page_at(x, y)

    def send_element_to_agent(self, info: dict, request: str = "") -> None:
        """Передати вибраний елемент у контекст агента.

        Це та сама дія, якої бракувало: «натисни на кнопку в браузері й
        скажи, що з нею зробити». Агент отримує селектор, класи, розміри й
        стилі — тобто рівно те, що потрібно, щоб знайти код і змінити його.

        Запит НЕ замінює те, що користувач уже написав: якщо в полі є
        текст, він стає проханням (це найприродніший спосіб — спершу
        написати «зроби більшою», потім вибрати елемент).
        """
        if not info:
            self.set_status("Елемент не вибрано — натисни на нього у браузері.")
            return
        text = agent_tools._format_element(info)
        typed = ""
        try:
            current = self.chat.input_box.get("1.0", "end-1c").strip()
            # Плейсхолдер — не текст користувача.
            if current and current != getattr(self.chat, "_placeholder", None):
                typed = current
        except (tk.TclError, AttributeError):
            typed = ""
        ask = (request or "").strip() or typed
        prompt = (
            "Ось елемент, який я вибрав у Live Browser:\n\n"
            f"{text}\n\n"
            "Знайди відповідний код у проєкті (за селектором, класами й "
            "стилями) і виконай моє прохання.\n\n"
            f"Прохання: {ask or '(допиши тут, що зробити з цим елементом)'}"
        )
        self.show_chat(True)
        self.chat.set_text(prompt)
        self.set_status("Елемент передано агенту — допиши прохання й натисни Enter.")

    def new_file(self) -> None:
        self.tabs.new_file()
        self.set_status("Новий файл")

    def open_file_dialog(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Відкрити файл",
                                          initialdir=self.settings.workspace)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path | str, line: int = 0) -> None:
        # Публічний вхід: сюди приходять і Path, і рядки з пошуку, палітри
        # та панелей. Без цього приведення ``file_tree.reveal`` падав на
        # рядку з ``'str' object has no attribute 'resolve'``.
        path = Path(path)
        if self.tabs.open_file(path, line=line):
            # Файл відкрито — стартовий екран більше не потрібен.
            self._hide_welcome()
            self.file_tree.reveal(path)
            self._remember_tab(path)
            self.outline.update_for(self.tabs.current())
            self._refresh_context()

    def save_file(self) -> None:
        self.tabs.save_current()
        self.outline.update_for(self.tabs.current())
        self._refresh_context()

    def save_file_as(self) -> None:
        self.tabs.save_as()
        self._refresh_context()

    def close_tab(self) -> None:
        self.tabs.close_current()
        self._refresh_context()

    def reopen_tab(self) -> None:
        """Відкрити останню закриту вкладку."""
        self.hide_welcome()
        if self.tabs.reopen_last_closed():
            self.set_status("Вкладку відновлено.")

    def _recent_closed_tabs(self) -> list[tuple[str, str, callable]]:
        items: list[tuple[str, str, callable]] = []
        for path in self.tabs.closed_paths()[:10]:
            items.append((
                f"Відкрити знову: {path.name}",
                "",
                lambda p=path: (self.hide_welcome(), self.tabs.reopen_path(p)),
            ))
        return items

    def close_all_tabs(self) -> None:
        self.tabs.close_all()
        self._refresh_context()

    def _remember_tab(self, path: Path) -> None:
        tabs = [str(p) for p in self.tabs.all_paths()]
        self.session["tabs"] = tabs[-12:]

    def _on_saved(self, path: Path) -> None:
        self.file_tree.refresh()
        # Застосунок у живому прев'ю оновлюється одразу (hot reload).
        # Збій тут не має ламати збереження, але й не має зникати: раніше
        # сторінка прев'ю просто не оновлювалась без жодного сліду.
        safe.call_quiet(self.live_preview.on_file_saved,
                        where="оновлення живого прев'ю")
        self.set_status(f"Збережено {path.name}")
        self._refresh_context()

    def _on_tabs_changed(self) -> None:
        self._refresh_context()

    def _refresh_context(self) -> None:
        # ``refresh()`` уже оновлює стан агента (перша секція панелі), тож
        # окремий виклик ``_refresh_agent`` тут був ДУБЛЕМ: панель
        # перебудовувалась двічі на кожне оновлення. Заміряно профілером —
        # цей зайвий виклик подвоював вартість найдорожчої операції
        # інтерфейсу.
        try:
            self.context.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _on_editor_analysis(self, editor, result) -> None:
        """AST-аналіз завершився — оновити панель структури й смугу стану."""
        if editor is not self.tabs.current():
            return
        try:
            self.outline.show_analysis(result, editor.current_line())
        except (tk.TclError, AttributeError):
            pass
        metrics = getattr(result, "metrics", None)
        if metrics is not None:
            self.ast_label.configure(
                text=f"{metrics.code_lines} рядків · {metrics.functions}ƒ · "
                     f"{metrics.classes}◈ · {result.elapsed:.1f} мс")
        problem = getattr(result, "problem", None)
        if problem is not None:
            self.set_status(f"Синтаксис: рядок {problem.line} — {problem.short}")
        elif getattr(result, "ok", False):
            count = len(getattr(result, "symbols", []))
            self.set_status(f"AST: {count} символів · {result.elapsed:.1f} мс")

    def _on_cursor(self, editor: CodeEditor) -> None:
        self.cursor_label.configure(text=f"Ln {editor.current_line()}, Col {editor.current_column()}")
        self.lang_label.configure(text=ws.language_label(editor.path or Path(editor.filename)))
        if self._active_side == "outline" and self.outline.winfo_ismapped():
            self.outline.highlight_line(editor.current_line())

    def _goto_line(self, line: int) -> None:
        editor = self.tabs.current()
        if editor:
            editor.goto_line(line)

    def run_current_file(self) -> None:
        path = self.tabs.current_path()
        if not path:
            self.set_status("Спочатку збережи файл.")
            return
        if self.tabs.current() and self.tabs.current().modified:
            self.tabs.save_current()
        self.show_bottom("terminal")
        if path.suffix == ".py":
            self.terminal.run(f'"{sys.executable}" "{path}"')
        elif path.suffix in {".bat", ".cmd"}:
            self.terminal.run(f'"{path}"')
        else:
            self.set_status(f"F5 запускає лише .py та .bat (файл {path.suffix}).")

    def run_tests(self) -> None:
        self.show_bottom("terminal")
        self.terminal.run(f'"{sys.executable}" -m unittest discover -s tests -v')

    # ── пошук і палітра ────────────────────────────────────────────────────
    def open_search(self) -> None:
        editor = self.tabs.current()
        if editor:
            SearchDialog(self, self.theme, editor)

    def open_project_search(self) -> None:
        self.show_bottom("search")
        self.project_search.query_entry.focus_set()

    def search_project_for(self, needle: str) -> None:
        self.show_bottom("search")
        self.project_search.search_for(needle)

    def quick_open(self) -> None:
        root = Path(self.settings.workspace)
        files = ws.quick_open_index(root)
        items = [
            (ws.relative_to_root(root, path), "", lambda p=path: self.open_path(p))
            for path in files
        ]
        Palette(self, self.theme, "Швидке відкриття файлу", items)

    def command_palette(self) -> None:
        """Палітра команд (Ctrl+Shift+P): усі команди з реєстру.

        Джерело — :mod:`commands`, тому в палітрі є КОЖНА команда програми,
        включно з тими, що живуть у випадаючих меню шапки. Недоступні зараз
        команди не зникають, а показуються з поміткою «недоступно».
        """
        self._close_popovers()
        items = commands.palette_items()
        if not items:
            self.set_status("Реєстр команд порожній — це помилка ініціалізації.")
            return
        Palette(self, self.theme, "Командна палітра", items,
                placeholder="Команда або категорія…")

    def _command_items(self) -> list[tuple[str, str, callable]]:
        """Сумісність: старі виклики отримують той самий список, що й палітра."""
        return commands.palette_items()

    # ── панелі ─────────────────────────────────────────────────────────────
    def _rail_action(self, key: str) -> None:
        """Дія навігації: розділ, панель або окрема команда."""
        if key == "settings":
            self.open_settings()
            return
        if key == "hub":
            self.open_model_hub()
            return
        if key == "search":
            self.open_project_search()
            self._sync_rail_state("search")
            return
        # Розділи навігації ведуть на свою «домашню» панель.
        panel = SECTION_PANELS.get(key)
        if panel is not None:
            self.show_side(panel)
            return
        self.show_side(key)

    def show_side(self, key: str) -> None:
        """Показати одну з панелей бічної колонки."""
        # Панель живе в PanedWindow: повертаємо її саме туди, а не через
        # grid() — `grid()` викидав віджет із PanedWindow, і сайдбар зникав
        # (перевірено: після show_side у side_split лишалась одна панель).
        if not self._sidebar_visible():
            self._sidebar_add()
        widget = self._side_widgets.get(key)
        if widget is None:
            widget = self.file_tree
            key = "explorer"
        for child in self.side_stack.winfo_children():
            child.pack_forget()
        # Заголовок панелі: користувач бачить, де саме він перебуває.
        self._paint_panel_title(key)
        widget.pack(fill="both", expand=True)
        self._active_side = key
        if key == "outline":
            self.outline.update_for(self.tabs.current())
        elif key == "skills":
            self.skills_panel.refresh()
        elif key == "queue":
            self.queue_panel.refresh()
        elif key == "mcp":
            self.mcp_panel.refresh()
        elif key == "rag":
            self.rag_panel.refresh_status()
        elif key == "tools":
            self.tools_panel.refresh()
        elif key == "changes":
            self.changes_panel.refresh()
        self._sync_rail_state(key)

    def _paint_panel_title(self, key: str) -> None:
        """Заголовок панелі: назва й шлях назад до списку чатів.

        Для самих чатів заголовок не показуємо — список має власну вкладку
        «ЧАТИ Й АГЕНТИ», і підпис над нею лише дублював її.
        """
        title = "" if key == "chats" else PANEL_TITLES.get(key, "").upper()
        try:
            self.panel_title.configure(text=title)
        except (tk.TclError, AttributeError):
            pass
        # Кнопка «назад до списку чатів»: будь-яка інша панель має шлях назад.
        try:
            if title:
                self.panel_home.configure(text="‹ до чатів", fg=theme.FG_DIM)
            else:
                self.panel_home.configure(text="", fg=theme.BG_ALT)
        except (tk.TclError, AttributeError):
            pass

    def _panel_home(self) -> None:
        """Повернутись до списку чатів із будь-якої панелі."""
        if self._active_side != "chats":
            self.show_side("chats")

    def _sync_rail_state(self, active: str = "") -> None:
        """Підсвітити чат як активний розділ лівої панелі.

        Пунктів навігації більше немає: ліворуч лишились самі чати, тож
        підсвічувати нічого — але виділення активного чату в списку
        лишається обов'язковим.
        """
        try:
            self.chat_list.set_active(getattr(self.chat_store, "active_id", ""))
        except (tk.TclError, AttributeError):
            pass
        # Швидкий доступ підсвічує те, де користувач зараз перебуває.
        for key, chip in getattr(self, "quick_nav", {}).items():
            try:
                chip.set_active(key == active)
            except (tk.TclError, AttributeError):
                continue

    def toggle_sidebar(self, show: bool | None = None) -> None:
        """Показати/сховати навігаційну панель.

        Панель живе в ``side_split`` (``PanedWindow``), тому показати її —
        це ``add``, а сховати — ``forget``. Раніше тут були ``grid``/
        ``grid_remove``, що працювало лише для звичайного ``Frame``.
        """
        visible = self._sidebar_visible()
        if show is None:
            show = not visible
        if bool(show) == visible:
            self._sync_rail_state()
            return
        if show:
            self._sidebar_collapsed = False
            self.sidebar.configure(width=self.layout.get(
                "sidebar_width", int(self.settings.ui.sidebar_width or 300)))
            self._sidebar_add()
            self.show_side(self._active_side or "chats")
        else:
            self._sidebar_forget()
            self._sync_rail_state("")
        self._sash_after(0)

    def _sidebar_visible(self) -> bool:
        """Чи панель справді в розкладці.

        Перевіряємо ``PanedWindow.panes()``, а не ``winfo_ismapped()``:
        приховане вікно (``withdraw``) або згорнуте вікно OS дає
        ``ismapped() == 0`` навіть тоді, коли панель стоїть у розкладці.
        На цьому вже спіткнулись: ширина сайдбара не зберігалась, бо
        перевірка «видимості» хибно казала «панелі немає».
        """
        try:
            return any(str(pane).endswith(str(self.sidebar))
                       for pane in self.side_split.panes())
        except (tk.TclError, AttributeError):
            return False

    def _sidebar_add(self) -> None:
        """Повернути панель у ``PanedWindow`` першою (ліворуч)."""
        try:
            panes = [str(pane) for pane in self.side_split.panes()]
        except (tk.TclError, AttributeError):
            panes = []
        if any(pane.endswith(str(self.sidebar)) for pane in panes):
            return
        # ``add`` додає в кінець, тому перебудовуємо порядок явно.
        try:
            for pane in panes:
                self.side_split.forget(pane)
            self.side_split.add(self.sidebar, weight=0)
            self.side_split.add(self.main_area, weight=1)
        except tk.TclError:
            LOG.debug("Не вдалось повернути панель у розкладку", exc_info=True)

    def _sidebar_forget(self) -> None:
        try:
            self.side_split.forget(self.sidebar)
        except tk.TclError:
            LOG.debug("Не вдалось прибрати панель із розкладки", exc_info=True)

    # ── вид робочої області ────────────────────────────────────────────────
    def set_view(self, view: str) -> None:
        """Перемкнути вид: ``chat`` (діалог на весь центр) або ``workspace``.

        Це і є перемикання «Chat ↔ Agent Workspace» із заголовка сесії:
        у режимі чату центральна колонка забирає весь простір, у режимі
        робочої області поруч із діалогом показується редактор.
        """
        target = "workspace" if (view or "").lower().startswith("work") else "chat"
        previous = getattr(self, "_view", "")
        self._view = target
        if self.settings.ui.view != target:
            self.settings.ui.view = target
            # Вибір виду переживає перезапуск, як і розкладка панелей.
            self.settings.save()
        self._chat_shown = True
        self._reorder_panes(with_centre=(target == "workspace"))
        self.header.set_view(target)
        if target == "workspace" and self._bottom_shown:
            # Нижня панель має бути видимою, якщо її відкривали.
            self._place_bottom(True)
        if previous != target:
            self.set_status("Робоча область: редактор і термінал." if target == "workspace"
                            else "Діалог з агентом на весь екран.")

    def _centre_in_split(self) -> bool:
        try:
            return any(str(pane).endswith(str(self.centre)) for pane in self.h_split.panes())
        except tk.TclError:
            return False

    def _insert_centre(self) -> None:
        """Повернути робочу область у розкладку НА СВОЄ місце.

        ``ttk.PanedWindow.add`` додає панель у кінець і не має опції
        ``-before``, тому після повторного показу редактор опинявся б
        праворуч від колонки контексту. Перебудовуємо порядок явно:
        діалог → робоча область → контекст.
        """
        if self._centre_in_split():
            return
        self._reorder_panes(with_centre=True)

    def _reorder_panes(self, *, with_centre: bool) -> None:
        """Розставити панелі у сталому порядку (діалог, редактор, контекст, прев'ю)."""
        wanted: list[tuple[tk.Widget, int]] = []
        if self._chat_shown:
            wanted.append((self.conversation_host, 1))
        if with_centre:
            wanted.append((self.centre, 1))
        if self._context_shown:
            wanted.append((self.context_host, 0))
        if self._preview_shown:
            wanted.append((self.preview_host, 0))
        try:
            for pane in self.h_split.panes():
                try:
                    self.h_split.forget(pane)
                except tk.TclError:
                    pass
            for widget, weight in wanted:
                self.h_split.add(widget, weight=weight)
        except tk.TclError:
            return
        self._sash_after(0)

    # ── живий прев'ю (права колонка) ───────────────────────────────────────
    def toggle_preview(self, show: bool | None = None) -> bool:
        """Показати/сховати колонку Live Preview із застосунком."""
        target = (not self._preview_shown) if show is None else bool(show)
        if target == self._preview_shown:
            return self._preview_shown
        self._preview_shown = target
        self._reorder_panes(with_centre=(self._view == "workspace"
                                         and self._centre_in_split()))
        if target:
            try:
                self.live_preview.inner.detect()
            except (tk.TclError, AttributeError):
                pass
        return self._preview_shown

    def _auto_show_preview(self) -> None:
        """Агент запустив застосунок — показуємо сайт і відкриваємо адресу.

        Раніше тут лише вмикалась права колонка, і вона могла лишитись із
        порожнім браузером: людина бачила панель, але не сайт. Тепер
        відкриваємо реальну адресу сервера.
        """
        if not self.app.running:
            return
        if not self._preview_shown:
            self.toggle_preview(True)
        url = ""
        try:
            url = self.app.url
        except Exception:                            # noqa: BLE001
            url = ""
        if not url:
            return
        try:
            self.live_preview.open_url(url)
            self.set_status(f"Сайт проєкту відкрито: {url}")
        except (tk.TclError, AttributeError):
            LOG.debug("Не вдалось відкрити сайт у прев'ю", exc_info=True)

    def _forget_centre(self) -> None:
        try:
            self.h_split.forget(self.centre)
        except tk.TclError:
            pass

    def show_chat(self, show: bool = True) -> None:
        """Показати або сховати колонку розмови."""
        if show == self._chat_shown:
            return
        self._chat_shown = bool(show)
        self._reorder_panes(with_centre=(getattr(self, "_view", "chat") == "workspace"))

    def toggle_chat(self) -> None:
        self.show_chat(not self._chat_shown)

    # ── режим «тільки чат» ─────────────────────────────────────────────────
    def toggle_focus_mode(self, enabled: bool | None = None) -> bool:
        """Режим роботи лише з чатом: усе інше — за бажанням.

        Коли ввімкнено, редактор, нижні вкладки й колонка контексту
        згортаються, а розмова займає вікно. Провідник, скіли, чергу й
        справи можна відкрити звичайним способом — вони нікуди не зникають,
        просто не забирають місця за замовчуванням.
        """
        target = (not self._focus_mode) if enabled is None else bool(enabled)
        if target == self._focus_mode:
            return self._focus_mode
        self._focus_mode = target

        if target:
            self._saved_focus_state = {
                "context": self._context_shown,
                "bottom": self._bottom_shown,
                "view": self._view,
            }
            self._chat_shown = True
            self._context_shown = False
            self._view = "chat"
            if self._bottom_shown:
                self._place_bottom(False)
            self._reorder_panes(with_centre=False)
            self.header.set_view("chat")
        else:
            saved = getattr(self, "_saved_focus_state", {}) or {}
            self._chat_shown = True
            self._context_shown = bool(saved.get("context", True))
            self._view = saved.get("view", "workspace")
            self._reorder_panes(with_centre=(self._view == "workspace"))
            self.header.set_view(self._view)
            if saved.get("bottom"):
                self._place_bottom(True)

        self._sync_focus_button()
        self.set_status("Режим «тільки чат» увімкнено." if target
                        else "Режим «тільки чат» вимкнено.")
        return self._focus_mode

    def _sync_focus_button(self) -> None:
        """Підсвітити кнопку режиму, якщо вона є."""
        button = getattr(self, "_focus_button", None)
        if button is None:
            return
        try:
            button.set_active(self._focus_mode)
        except (tk.TclError, AttributeError):
            pass

    def toggle_context(self, show: bool | None = None) -> None:
        """Показати або сховати колонку контексту (явний вибір користувача)."""
        target = (not self._context_shown) if show is None else bool(show)
        self._context_user_choice = target
        self._auto_context(target)

    def show_bottom(self, which: str = "terminal") -> None:
        """Показати нижню висувну панель (термінал, пошук, хаб, сайт).

        Вона живе під редактором у робочій області й займає рівно задану
        висоту — не «з'їдаючи» весь екран. У режимі діалогу вона сама
        відкриває робочу область, бо інакше її не було б видно.
        """
        if not self._bottom_shown:
            self._place_bottom(True)
        if self._view != "workspace" and not self._centre_in_split():
            self.set_view("workspace")
        else:
            self._insert_centre()
        if which == "search":
            self.bottom_tabs.select(self.project_search)
        elif which == "hub":
            self.bottom_tabs.select(self.model_hub)
        elif which == "site":
            self.bottom_tabs.select(self.preview)
        elif which in ("tasks", "queue", "task_center"):
            self.bottom_tabs.select(self.task_center)
        else:
            self.bottom_tabs.select(self.terminal)

    def _place_bottom(self, show: bool) -> None:
        """Розмістити/прибрати нижню панель разом зі смугою перетягування."""
        try:
            self.editor_split.rowconfigure(1, weight=0)
            self.editor_split.rowconfigure(2, weight=0)
            if show:
                # Смуга вище панелі: саме за неї тягнуть, щоб змінити висоту.
                self.bottom_sash.grid()
                self.bottom_tabs.grid(row=2, column=0, sticky="nsew")
                height = int(getattr(self, "_bottom_height", 200) or 200)
                self.bottom_tabs.configure(height=height)
                self._bottom_shown = True
            else:
                self.bottom_sash.grid_remove()
                self.bottom_tabs.grid_remove()
                self._bottom_shown = False
        except tk.TclError:
            return
        self._sash_after(0)

    # ── перетягування висоти нижньої панелі ───────────────────────────────
    def _bottom_sash_press(self, event) -> None:
        """Почали тягнути смугу: запам'ятати початкові координати."""
        self._sash_drag_from = int(event.y_root)
        self._sash_drag_height = int(self.bottom_tabs.winfo_height()
                                     or self._bottom_height or 200)
        # Поки тягнемо — не перераховуємо розкладку, інакше панель
        # «стрибала» б назад на збережену висоту.
        self._user_dragging = True

    def _bottom_sash_drag(self, event) -> None:
        """Тягнемо смугу: висота панелі змінюється за рухом миші."""
        try:
            total = self.editor_split.winfo_height()
        except tk.TclError:
            return
        if total <= 0:
            return
        delta = int(event.y_root) - int(self._sash_drag_from)
        # Тягнемо ВГОРУ — панель росте.
        wanted = self._sash_drag_height - delta
        # Межі: панель не менша за 120 px (щоб бачити рядок адреси) і не
        # більша за 80% робочої області (редактор має лишатись видимим).
        low, high = 120, max(160, int(total * 0.8))
        height = layout.clamp(wanted, low, high)
        if height == self._bottom_height:
            return
        self._bottom_height = height
        try:
            self.bottom_tabs.configure(height=height)
        except tk.TclError:
            pass

    def _bottom_sash_release(self, _event=None) -> None:
        """Відпустили смугу: запам'ятати нову висоту."""
        self._user_dragging = False
        self._remember_layout()
        self.set_status(f"Висота панелі: {self._bottom_height} px")

    def toggle_bottom(self, show: bool | None = None) -> None:
        """Показати/сховати нижню панель (``None`` — перемкнути стан)."""
        target = (not self._bottom_shown) if show is None else bool(show)
        if target:
            self.show_bottom("terminal")
        elif self._bottom_shown:
            self._place_bottom(False)

    def zoom(self, delta: int) -> None:
        # ``delta`` може прийти зі зворотного виклику без аргументу (меню
        # передає ``None``): тоді рахування ``font_size + delta`` падало
        # ``TypeError``, і кнопка «збільшити шрифт» не працювала зовсім.
        try:
            step = int(delta) if delta is not None else 1
        except (TypeError, ValueError):
            step = 1
        size = max(8, min(30, self.settings.ui.font_size + step))
        self.settings.ui.font_size = size
        self.theme.set_family(self.settings.ui.font_family, size)
        self.tabs.apply_settings()
        self.chat.apply_font()
        self.terminal.output.configure(font=self.theme.mono_small)
        self.terminal.entry.configure(font=self.theme.mono_small)
        self.settings.save()
        self.set_status(f"Розмір шрифту: {size}")

    # ── провайдери та моделі ───────────────────────────────────────────────
    def probe_providers(self, silent: bool = False) -> None:
        """Перевірити локальні сервери й показати справжній статус моделей.

        Хмарні провайдери не перевіряємо автоматично — це зайвий трафік і
        вимога ключа. Для локальних мережа це ``GET /models``, тобто реальний
        стан сервера, а не припущення.
        """
        targets = providers.probe_targets(self.settings)
        if self._probe is not None:
            try:
                self._probe.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._probe = providers.ProviderProbe(targets, timeout=4)
        self._probe.start()
        if not silent:
            self.set_status(f"Перевіряю локальні сервери: {len(targets)}…")
        self._drain_probe()

    def _drain_probe(self) -> None:
        self._probe_after = None
        outcomes: list[providers.ProbeOutcome] = []
        if self._probe is not None:
            outcomes = self._probe.drain()
        if outcomes:
            self._probe_state.update({item.key: item for item in outcomes})
            self._apply_probe_results(outcomes)
        running = self._probe is not None and self._probe.running
        if running:
            try:
                self._probe_after = self.after(180, self._drain_probe)
            except tk.TclError:
                self._probe_after = None

    def _apply_probe_results(self, outcomes: list[providers.ProbeOutcome]) -> None:
        found = [item for item in outcomes if item.ok]
        online = sum(1 for item in found)
        total = len(self._probe_state)
        self._probe_summary = (f"локальних онлайн: {online} з {total}" if total
                               else "сервери не перевірено")
        # Поточний сервер відповів — модель справді доступна.
        current_url = (self.settings.llm.base_url or "").rstrip("/")
        for item in outcomes:
            if item.base_url.rstrip("/") != current_url:
                continue
            if item.ok and not self.settings.llm.model and item.models:
                self.settings.llm.model = item.models[0]
            self._refresh_model_state(online=item.ok, detail=item.detail)
        # Локальний стан у підвалі навігації.
        local_online = [item for item in found
                        if providers._kind_of(item.base_url) == providers.LOCAL]
        try:
            if local_online:
                self.local_label.configure(text=f"● {local_online[0].key}", fg=theme.SUCCESS)
            elif total:
                self.local_label.configure(text="● локально", fg=theme.FG_FAINT)
        except (tk.TclError, AttributeError):
            pass
        if self._model_selector is not None and self._model_selector.visible:
            self._fill_model_selector()

    def _refresh_model_state(self, *, online: bool, detail: str = "") -> None:
        """Оновити показ активної моделі В УСІХ місцях — з одного джерела.

        ДЕФЕКТ (скріншот користувача): шапка й панель контексту показували
        ``qwen2.5-coder-14b``, а пігулка в куті, рядок композера й статус —
        ``Ministral-3-14B``. Причина: підписи оновлювались РІЗНИМИ шляхами,

        * ``header_bar`` (шапка) — лише з ``_refresh_header()``;
        * ``session_header`` (пігулка) і ``chat`` — з ``_sync_active_model()``;
        * композер — узагалі з моделі ЧАТУ (``chat.model``), яка лишалась
          від попереднього вибору.

        Через це в одному вікні жили ДВА різні значення, і користувач
        слушно питав «чому вибрані дві моделі?».

        Тепер усі підписи ставляться ОДНИМ викликом і з ОДНОГО джерела —
        ``providers.current_entry(settings)``. Це єдине місце, де модель
        перетворюється на підпис.
        """
        entry = providers.current_entry(self.settings)
        entry.online = online
        self.header.set_model(entry)
        self.chat.set_online(online, detail)
        # ВЕЛИКИЙ статус у шапці: «● МОДЕЛЬ ОНЛАЙН / ОФЛАЙН». Саме він
        # дає відповідь на головне питання користувача одним поглядом.
        try:
            self.header_bar.set_model_status(
                bool(online),
                detail=detail or f"{entry.name} · {self.settings.llm.base_url}")
        except (tk.TclError, AttributeError):
            pass
        self._sync_model_labels(entry)

    def _sync_model_labels(self, entry: "providers.ModelEntry" = None) -> None:
        """Поставити ОДИН підпис моделі в усі віджети, що її показують.

        Це єдина точка. Раніше їх було три, і вони розходились: шапка
        брала модель із налаштувань, композер — із запису чату, пігулка —
        з третього виклику. Тепер джерело одне й обовʼязкове.
        """
        if entry is None:
            entry = providers.current_entry(self.settings)
        name = entry.name
        # 1. Шапка (header_bar) — саме вона показує «⊟ модель · локальна ▾».
        bar = getattr(self, "header_bar", None)
        if bar is not None:
            try:
                bar.set_model(name, local=entry.is_local, online=entry.online)
            except (tk.TclError, AttributeError):
                LOG.debug("Підпис моделі в шапці не оновлено", exc_info=True)
        # 2. Пігулка сесії під назвою чату.
        header = getattr(self, "header", None)
        if header is not None:
            try:
                header.set_model(entry)
            except (tk.TclError, AttributeError):
                LOG.debug("Підпис моделі в пігулці не оновлено", exc_info=True)
        # 3. Кнопка моделі в композері. ВАЖЛИВО: ставимо модель
        #    налаштувань, а не «модель чату» — інакше після зміни моделі
        #    в налаштуваннях композер показував стару (саме це й було).
        chat = getattr(self, "chat", None)
        if chat is not None:
            try:
                chat.chat_model = name
                chat.set_model_label(name)
                chat._paint_model_button()
            except (tk.TclError, AttributeError):
                LOG.debug("Підпис моделі в композері не оновлено", exc_info=True)
        # 4. Запис активного чату — щоб після перезапуску було те саме.
        store = getattr(self, "chat_store", None)
        try:
            active = store.active() if store is not None else None
        except (AttributeError, tk.TclError):
            active = None
        if active is not None and getattr(active, "model", "") != name:
            try:
                active.model = name
                store.save()
            except Exception:  # noqa: BLE001 - історія не має ламати показ
                LOG.debug("Модель чату не збережено", exc_info=True)

    def _sync_active_model(self) -> None:
        """Сумісність: те саме, що :meth:`_sync_model_labels`."""
        self._sync_model_labels()

    def show_model_selector(self, anchor: object = None) -> None:
        """Відкрити селектор моделей.

        ``anchor`` — віджет, над яким показати список (кнопка моделі в
        шапці або композер). Шапка передає його явно: без цього список
        відкривався над композером навіть тоді, коли натиснули кнопку
        вгорі, і виглядав «приклеєним» до чужого місця.
        """
        if self._model_selector is None:
            self._model_selector = model_selector.ModelSelector(
                self, self.theme, self.settings,
                on_pick=self._on_model_selected,
                on_refresh=self.probe_providers,
                on_manage=self.open_settings,
            )
        elif self._model_selector.visible:
            self._model_selector.close()
            return
        self._fill_model_selector()
        target = anchor or getattr(self.chat, "composer_card", None) \
            or self.header.model_label
        self._model_selector.show_above(target)

    def _fill_model_selector(self) -> None:
        if self._model_selector is None:
            return
        entries = providers.catalogue(self.settings, probed=self._probe_state)
        local = sum(1 for entry in entries if entry.is_local and entry.online)
        summary = self._probe_summary or f"точок входу: {len(entries)}"
        if local:
            summary = f"локальних готово: {local} · {summary}"
        self._model_selector.set_entries(entries, summary=summary)

    def _on_model_selected(self, entry: providers.ModelEntry) -> None:
        """Користувач вибрав модель у селекторі."""
        providers.apply_choice(self.settings, entry)
        self.agent.llm_settings = self.settings.llm
        chat = self.chat_store.active()
        if chat is not None:
            try:
                chat.model = entry.name
                self.chat_store.save()
            except Exception:  # noqa: BLE001 - історія не має ламати вибір
                LOG.warning("Не вдалось зберегти модель у чаті", exc_info=True)
        self.chat.set_chat_model(entry.name, self.chat.chat_effort)
        self._on_model_changed()
        # Реальний стан — з перевірки провайдера, а не «модель вибрано, отже
        # онлайн». Раніше тут стояло ``entry.online or True``: умова завжди
        # істинна, тож зелений індикатор світився навіть для недоступного
        # сервера, і користувач бачив «працює» перед реальною помилкою.
        self._refresh_model_state(online=entry.online)
        kind = "локальна" if entry.is_local else "хмарна"
        self.set_status(f"Модель: {entry.name} · {entry.provider_label} ({kind})")

    def show_mode_menu(self, anchor: object = None) -> None:
        """Меню режимів роботи агента (реальні дозволи й кроки).

        ``anchor`` передає шапка або пігулка композера: меню мусить
        відкритись під ТІЄЮ кнопкою, яку натиснули, а не під підписом
        режиму в шапці.
        """
        if self._mode_menu is not None and self._mode_menu.visible:
            self._mode_menu.close()
            return
        self._mode_menu = modes_menu.ModeMenu(
            self, self.theme, self._on_mode_selected, current=self.agent_mode)
        self._mode_menu.show_below(anchor or self.header.mode_label)

    def show_workspace_menu(self, anchor: object = None) -> None:
        """Меню робочого простору: поточна тека, останні, «додати».

        Це той самий вибір, що й у шапці, але доступний із пігулки над
        полем вводу. Показуються лише РЕАЛЬНІ теки: поточна (якщо існує)
        і ті зі списку останніх, що досі на диску. Мертві пункти не
        малюються — раніше вибір зниклої теки виглядав як поломка кнопки.
        """
        menu = getattr(self, "_workspace_menu", None)
        if menu is not None:
            try:
                menu.destroy()
            except tk.TclError:
                pass
            self._workspace_menu = None
            return
        current = str(self.settings.workspace or "") if self.has_project() else ""
        menu = workspace_menu.WorkspaceMenu(
            self, self.theme,
            current=current,
            recent=list(getattr(self.settings, "recent", []) or []),
            on_pick=self._pick_workspace_from_chat,
            on_add=self.open_folder_dialog,
        )
        self._workspace_menu = menu
        target = anchor or getattr(self.chat, "workspace_btn", None) \
            or self.header.workspace_btn
        menu.show_at(target)

    def _pick_workspace_from_chat(self, path: str) -> None:
        """Теку вибрано пігулкою в чаті — застосувати тією ж логікою, що й шапка."""
        folder = Path(str(path or "").strip())
        if not folder.is_dir():
            self.set_status(f"Теки більше немає: {path}")
            return
        if self.has_project():
            try:
                same = Path(self.settings.workspace).resolve() == folder.resolve()
            except OSError:
                same = False
            if same:
                self.set_status(f"Уже працюю з текою: {folder}")
                return
        self.set_workspace(folder)

    def show_chat_mode_menu(self) -> None:
        """Спливне меню режиму чату: автономний і автоматизації.

        Ці два пункти прибрано з лівого меню: вони стосуються конкретної
        сесії й теки, а не всього застосунку. Меню показує, до якого чату
        й проєкту вони належать, і саме тому в ньому видно і назву чату,
        і теку.
        """
        menu = getattr(self, "_chat_mode_menu", None)
        if menu is not None:
            try:
                menu.destroy()
            except tk.TclError:
                pass
            self._chat_mode_menu = None
            return
        pending = [t for t in self.task_queue.tasks
                   if t.status in {queue_engine.PENDING, queue_engine.RUNNING}]
        owner = str(getattr(self.chat_store, "active_id", "") or "")
        mine = [t for t in pending
                if not getattr(t, "chat_id", "") or str(t.chat_id) == owner]
        chat = self.chat_store.active()
        menu = chat_mode_menu.ChatModeMenu(
            self, self.theme,
            chat_title=(chat.title if chat else "") or "Новий чат",
            project=self._project_root().name if self._project_root() else "",
            autonomous_on=self.autonomous_engine.active,
            autonomous_state=self.autonomous_engine.state,
            queue_count=len(mine),
            on_autonomous=self._toggle_autonomous_for_chat,
            on_automations=lambda: self.show_side("queue"),
            on_pick_project=self.open_folder_dialog,
        )
        self._chat_mode_menu = menu
        menu.show_at(self.header.chat_mode_label)

    def _toggle_autonomous_for_chat(self) -> None:
        """Старт/зупинка автономного режиму для ПОТОЧНОГО чату й проєкту."""
        if self.autonomous_engine.active:
            self.stop_autonomous()
            return
        self.start_autonomous()

    def _on_mode_selected(self, key: str) -> None:
        self.set_agent_mode(key)

    def set_agent_mode(self, key: str) -> None:
        """Застосувати режим: дозволи, ліміт кроків, підказка агенту."""
        mode = modes.apply(self.settings, self.agent, key)
        self.agent_mode = mode.key
        self.settings.ui.mode = mode.key
        self.settings.agent.mode = mode.key
        self.settings.save()
        # Синхронізувати перемикач дозволів у композері з режимом.
        try:
            self.chat.set_permission_mode(mode.permission)
        except (tk.TclError, AttributeError):
            pass
        self.header.set_mode(mode.key)
        self.header.set_status("idle", mode.hint)
        # Пігулка над полем вводу показує той самий режим: це те, що агент
        # справді застосує (дозволи, кроки, інструменти), а не підпис.
        try:
            self.chat.set_mode(mode.label, icon=mode.icon,
                               accent=mode.key != modes.CHAT)
        except (tk.TclError, AttributeError):
            pass
        self.set_status(f"Режим: {mode.label} · {mode.hint}")

    # ── хаб моделей ────────────────────────────────────────────────────────
    def open_model_hub(self) -> None:
        self.show_bottom("hub")
        self.model_hub.start()

    def open_first_run(self) -> None:
        self._close_popovers()
        wizard = FirstRunWizard(self, self.theme, self.settings, on_done=self._after_first_run)
        wizard.focus_set()

    def _after_first_run(self, connected: bool) -> None:
        if not connected:
            self.set_status("Майстер закрито. Модель можна налаштувати пізніше через «Хаб моделей».")
            # Бібліотеки й програми могли змінитись — перечитуємо стан, щоб
            # панелі одразу бачили, що тепер доступно (напр. з'явився git).
            self.after(300, self._refresh_after_env_change)
            return
        self._on_model_changed()
        self.probe_providers(silent=True)
        self._refresh_after_env_change()
        self.set_status(f"Модель підключена: {self.settings.llm.model or 'локальний сервер'}")

    def _refresh_after_env_change(self) -> None:
        """Після майстра: оновити панелі, які залежать від програм і пакетів."""
        try:
            self.changes_panel.refresh()
        except (tk.TclError, AttributeError):
            LOG.debug("Панель змін не оновилась", exc_info=True)
        try:
            self.rag_panel.refresh_status()
        except (tk.TclError, AttributeError):
            LOG.debug("Статус RAG не оновився", exc_info=True)
        try:
            self.refresh_rag_status()
        except (tk.TclError, AttributeError):
            pass

    def _apply_cloud_provider(self) -> bool:
        """Якщо в налаштуваннях є хмарний агент — підключити його замість локального."""
        cloud = getattr(self.settings, "cloud", None)
        if cloud is None or not getattr(cloud, "enabled", False):
            return False
        url = cloud_agents.normalise_base_url(cloud.base_url)
        if not url or not cloud.api_key.strip():
            return False
        self.settings.llm.base_url = url
        self.settings.llm.api_key = cloud.api_key
        if cloud.model:
            self.settings.llm.model = cloud.model
        self.settings.llm.max_tokens = max(256, int(cloud.max_tokens or 2048))
        self.settings.llm.temperature = float(cloud.temperature or 0.3)
        # Хмарний агент уже запущений — локальний рушій не потрібен.
        self.settings.engine.auto_start = False
        self.agent.llm_settings = self.settings.llm
        provider = cloud_agents.get(cloud.provider)
        name = provider.label if provider else "хмара"
        reasoning = " · reasoning" if cloud_agents.is_reasoning_model(cloud.model) else ""
        self.set_status(f"Хмарний агент: {name} · {cloud.model}{reasoning}")
        self._cloud_active = True
        return True

    def _on_hub_model_ready(self, base_url: str, model_name: str) -> None:
        from .runtime import MANAGED_API_KEY

        # ── Вивантаження попередньої моделі ───────────────────────────────
        # Коли користувач запускає ІНШУ модель із хаба, попередній
        # керований сервер мусить бути зупинений. Інакше дві моделі
        # одночасно тримають відеопам'ять: перша вже не потрібна, але
        # займає гігабайти, і друга не влізає (перевірено:
        # tests/test_model_switch_live.py).
        #
        # ``_release_models`` уже вміє це робити (він же викликається при
        # закритті IDE), тому використовуємо саме його — одна логіка на
        # всі випадки, а не копія.
        previous = getattr(self, "_managed_server", None)
        previous_url = ""
        if previous is not None:
            previous_url = str(getattr(previous, "base_url", "") or "")
            if previous_url.rstrip("/") != str(base_url or "").rstrip("/"):
                self._stop_previous_model(previous, previous_url)

        self.settings.llm.base_url = base_url
        self.settings.llm.model = model_name
        self.settings.llm.api_key = MANAGED_API_KEY
        self.settings.engine.managed = True
        self.settings.save()
        self.agent.llm_settings = self.settings.llm
        # Чи має ця модель зір: перевіряємо, чи знайшовся проєктор для
        # завантаженого файлу. Так агент знає, чи можна передавати знімки
        # як зображення (з проєктором) чи лише як шлях.
        vision = False
        try:
            for path in hub.local_models():
                if path.stem == model_name or path.name == model_name:
                    vision = hub.vision_projector_for(path) is not None
                    break
        except Exception:  # noqa: BLE001 - перевірка не має ламати старт
            LOG.debug("Перевірка зору не вдалась", exc_info=True)
        try:
            self.agent.vision_enabled = vision
        except AttributeError:
            pass
        self.probe_providers(silent=True)
        note = " · зір увімкнено" if vision else ""
        self.set_status(f"Модель готова: {model_name} · {base_url}{note}")

    def _stop_previous_model(self, server, url: str = "") -> None:
        """Зупинити попередню модель ПЕРЕД запуском нової (звільнити VRAM).

        Порядок важливий: спершу зупинка, потім зміна налаштувань. Інакше
        агент якусь мить стукає на стару адресу, а старий процес ще живе.
        """
        self.set_status(f"Вивантажую попередню модель{f' ({url})' if url else ''}…")
        try:
            server.stop()
        except Exception:  # noqa: BLE001 - зупинка не має ламати перемикання
            LOG.debug("Попередній сервер не зупинився", exc_info=True)
        if getattr(self, "_managed_server", None) is server:
            self._managed_server = None
        # Сервер із панелі хаба — окреме поле; зупиняємо й його, якщо це
        # інший об'єкт (хаб міг тримати власний екземпляр).
        try:
            hub_server = getattr(self.model_hub, "server", None)
            if hub_server is not None and hub_server is not server:
                hub_server.stop()
                self.model_hub.server = None
        except Exception:  # noqa: BLE001
            LOG.debug("Сервер хаба не зупинився", exc_info=True)
        # Найнадійніше: добити будь-які рушії, які ми самі записали.
        try:
            removed = runtime.cleanup_stale_processes()
            if removed:
                LOG.info("Зупинено залишкових рушіїв: %s", removed)
        except Exception:  # noqa: BLE001
            LOG.debug("Прибирання рушіїв не вдалось", exc_info=True)
        self.set_status(f"Попередню модель вивантажено{f' ({url})' if url else ''}.")

    # ── налаштування ───────────────────────────────────────────────────────
    def _close_popovers(self) -> None:
        """Закрити всі спливні картки (модель, режими, контекст, меню команд).

        Проблема, яку це лікує: картка «Модель» має прапорець ``-topmost`` і
        лишалась на екрані, коли зверху відкривався модальний діалог. Два
        вікна одночасно — користувач бачив «два налаштування», а введення
        губилось між ними.
        """
        try:
            widgets.close_popovers()
        except Exception:  # noqa: BLE001 - прибирання не має ламати дію
            pass

    def _on_window_deactivate(self, event=None) -> None:
        """Головне вікно втратило фокус — прибираємо спливні картки.

        Обережно: картка теж забирає фокус (у неї поле пошуку), і тоді
        ``FocusOut`` приходить одразу після відкриття — закривати в цей
        момент не можна, інакше картка «миготить» і зникає. Тому перевіряємо,
        ЧИЙ саме віджет отримав фокус: якщо це наше спливне вікно —
        лишаємо картку відкритою.
        """
        if event is not None and getattr(event, "widget", None) is not self:
            return
        # Модальний діалог забирає фокус — картки він уже прибрав сам.
        if widgets.active_modal() is not None:
            return
        try:
            focused = self.focus_get()
        except (tk.TclError, KeyError):
            focused = None
        if focused is not None and widgets.is_popover_widget(focused):
            return
        self._close_popovers()

    def open_settings(self) -> None:
        # Спершу прибираємо спливні картки: інакше вони лишаються поверх
        # або поряд із модальним діалогом.
        self._close_popovers()
        SettingsDialog(self, self.theme, self.settings, on_saved=self._after_settings,
                       on_open_hub=self.open_model_hub,
                       on_open_panel=self._open_panel_from_settings,
                       on_first_run=self.open_first_run)

    def _open_panel_from_settings(self, key: str) -> None:
        """Відкрити панель програми з діалогу налаштувань.

        Ліва колонка показує лише чати, тому «MCP», «Проєкти», «База знань»
        і решта тепер відкриваються звідси. Панель показуємо праворуч від
        діалогу — так її видно, а не ховаємо за перемикачем.
        """
        if not self._sidebar_visible():
            self._sidebar_add()
        self.show_side(key)
        self.set_status(f"Відкрито панель: {PANEL_TITLES.get(key, key)}")

    def _after_settings(self) -> None:
        self.registry.confirm_commands = self.settings.agent.confirm_commands
        self.agent.agent_settings = self.settings.agent
        self.agent.llm_settings = self.settings.llm
        # Політика простою могла змінитись у вкладці «Агент».
        try:
            policy = self.model_keeper.tracker.policy
            policy.enabled = bool(getattr(self.settings.engine, "unload_when_idle", True))
            policy.idle_seconds = int(
                getattr(self.settings.engine, "idle_unload_seconds", 300) or 300)
            policy.normalise()
        except Exception:  # noqa: BLE001 - налаштування не мають ламати вікно
            LOG.debug("Не вдалось застосувати політику простою", exc_info=True)
        # Тему могли змінити у вкладці «Редактор» — застосовуємо до всього
        # вікна (перефарбування редакторів і карток чату робить цей метод).
        if self.settings.ui.theme != theme.current_mode():
            self.apply_theme_mode(self.settings.ui.theme)
        self.theme.set_family(self.settings.ui.font_family or self.theme.mono_family,
                              self.settings.ui.font_size)
        self.tabs.apply_settings()
        self.probe_providers(silent=True)
        self._on_model_changed()
        self._apply_voice_settings()
        # ── УВІМКНУЛИ ВЛАСНИЙ РУШІЙ — ЗАВАНТАЖИТИ МОДЕЛЬ ─────────────────
        # Прапорця було замало: адреса лишалась HTTP, а модель у рушій не
        # завантажувалась узагалі, тож перший же запит ішов у мережу й падав
        # з «[WinError 10061] target machine actively refused it».
        # Тепер збереження налаштувань справді вмикає рушій.
        self._apply_engine_choice()
        self.set_status("Налаштування збережено.")

    def _apply_engine_choice(self) -> None:
        """Привести стан рушія у відповідність до налаштувань.

        Викликається після збереження налаштувань і при старті. Правила:

        * увімкнено вбудований рушій — модель МУСИТЬ бути завантажена, інакше
          наступний запит піде в порожнечу;
        * вимкнено — звільняємо відеопам'ять, щоб не тримати її намарно.
        """
        wants_native = bool(getattr(self.settings.engine, "native", True))
        if wants_native:
            if self.native_runtime.loaded:
                # Уже завантажено — лишається переконатись, що чат дивиться
                # саме на вбудований рушій.
                if not str(self.settings.llm.base_url or "").startswith("native://"):
                    self._on_native_model(self.native_runtime.model_path or "")
                return
            result = self._autostart_native_model()
            if result and not result.startswith(NATIVE_FAILURE_PREFIX):
                LOG.info("Рушій увімкнено з налаштувань: %s", result)
                self.set_status(f"Власний рушій: {result}")
            elif result:
                self.set_status(
                    f"Власний рушій не завантажився: {result[len(NATIVE_FAILURE_PREFIX):]}")
            return
        # Рушій вимкнено — звільняємо пам'ять, але не чіпаємо HTTP-адресу,
        # яку користувач міг налаштувати навмисно.
        if self.native_runtime.loaded:
            try:
                self.native_runtime.unload_model()
                self.set_status("Власний рушій вимкнено — відеопам'ять звільнено.")
            except Exception as exc:                 # noqa: BLE001
                LOG.warning("Не вдалось вивантажити модель: %s", exc)

    # ── власний рушій і пам'ять ─────────────────────────────────────────────
    def _open_memory(self):
        """Відкрити пам'ять NEUROMESH (або чесно повернути ``None``).

        Пам'ять не має ламати старт IDE: якщо база недоступна (права,
        пошкодження, зайнятий файл), застосунок працює далі, а панель
        показує причину.
        """
        try:
            from .pcmm import Neuromesh

            service = Neuromesh()
            service.attach_engine(self.native_runtime.engine)
            return service
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("Пам'ять NEUROMESH недоступна: %s", exc, exc_info=True)
            self.set_status(f"Пам'ять недоступна: {exc}")
            return None

    def _on_native_model(self, path: str) -> None:
        """Модель завантажено у власний рушій: підключити її до чату.

        Саме тут налаштування перемикаються на вбудований рушій, щоб агент
        почав працювати з моделлю, яку виконала сама IDE — без
        llama-server і без ручного запуску сторонніх програм.

        ── ЧОМУ ПОТРІБЕН ``_ui_call`` ──────────────────────────────────────
        Метод кличеться з ФОНОВОГО потоку автозапуску
        (``_auto_setup_in_background`` → ``_autostart_local_model``). Тут
        змінюються віджети (``_on_model_changed`` → підписи, ``set_status`` →
        статусбар), а tkinter поза головним потоком падає:

            RuntimeError: main thread is not in main loop

        Через це чат НЕ перемикався на вбудований рушій: модель
        завантажена, а запити йдуть на стару HTTP-адресу. Тепер усе
        інтерфейсне виконується в головному потоці, а налаштування
        зберігаються одразу (це не віджет).
        """
        from .native import bridge

        # Частину, яка чіпає ВІДЖЕТИ, виконуємо в головному потоці.
        def apply_ui() -> None:
            try:
                self._on_model_changed()
                if self.memory is not None:
                    self.memory.attach_engine(self.native_runtime.engine)
                self._attach_memory_bridge(self.agent)
                self._wire_exact_tokens()
                # ── Статус «ОНЛАЙН» ставимо ТУТ, а не лише після автозапуску ──
                # Це єдина точка, через яку проходить КОЖНЕ завантаження
                # моделі у вбудований рушій: автозапуск при старті,
                # збереження налаштувань, пробудження після простою, вибір
                # моделі. Раніше статус у шапці оновлювався лише з
                # ``_after_auto_setup``, тож після інших шляхів лишався
                # «● МОДЕЛЬ ОФЛАЙН» на живій моделі.
                self._confirm_model_online(f"власний рушій: {Path(path).stem}")
                self.set_status(
                    f"Власний рушій: модель «{Path(path).stem}» готова до чату.")
            except (tk.TclError, AttributeError) as exc:
                LOG.warning("Підписи моделі не оновлено: %s", exc)

        try:
            bridge.remember_model("")
            self.settings.llm.base_url = bridge.EMBEDDED_URL
            self.settings.llm.model = Path(path).stem
            self.settings.llm.api_key = "local"
            self.settings.llm.auto_detect = False
            self.settings.engine.managed = True
            self.settings.engine.model_path = str(path)
            # Контекст — фактичний, з яким рушій завантажився.
            limit = self._native_context_limit()
            if limit:
                self.settings.engine.ctx_size = int(limit)
                self._context_limit = int(limit)
            safe.call_quiet(self.settings.save)
            # Агент бачить ту саму адресу — це чистий Python, без tkinter.
            self.agent.llm_settings = self.settings.llm
            self._context_limit = int(limit or self._context_limit or 0)
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("Не вдалось активувати модель: %s", exc, exc_info=True)
            # Лямбда виконується ПІЗНІШЕ, коли змінна ``exc`` уже знищена
            # (Python прибирає її після виходу з ``except``), тому беремо
            # знімок тексту зараз — інакше замість причини був NameError.
            detail = str(exc)
            self._ui_call(lambda: self.set_status(
                f"Модель завантажена, але чат не перемкнувся: {detail}"))
            return
        # Інтерфейс — у головному потоці.
        self._ui_call(apply_ui)

    def _wire_exact_tokens(self) -> None:
        """Підключити точний підрахунок токенів до агента й статистики.

        Без цього агент рахує токени за «символи / 3.5», і для української
        кирилиці помиляється більш ніж удвічі: історія або ріжеться
        завчасно, або переповнює вікно. Точний tokenizer завантаженої
        моделі вже є — лишається віддати його тим, хто вирішує, скільки
        тексту влізе.
        """
        model = getattr(self.native_runtime.engine, "model", None)
        tokenizer = getattr(model, "tokenizer", None) if model else None
        if tokenizer is None:
            return
        def counter(text: str) -> int:
            """Точна кількість токенів у тексті за tokenizer моделі."""
            return tokenizer.count(str(text or ""), add_special=False)

        from . import agent as agent_module
        from . import context_stats as context_stats_module

        agent_module.set_token_counter(counter)
        setter = getattr(self.agent, "set_token_counter", None)
        if callable(setter):
            setter(counter)
        # Смуга статистики теж має рахувати ті самі токени.
        context_stats_module.set_token_counter(counter)

    def _show_memory_item(self, memory_id: str) -> None:
        """Показати деталі спогаду (виклик із панелі пам'яті)."""
        if self.memory is None:
            return
        data = self.memory.explain(memory_id)
        if not data:
            self.set_status(f"Спогад {memory_id} не знайдено.")
            return
        memory = data["memory"]
        lines = [
            f"ID: {memory['id']}",
            f"Тип: {memory['kind']} · впевненість {memory['confidence']}",
            f"Походження: {data.get('provenance') or 'невідомо'}",
            "",
            str(memory.get("content") or ""),
            "",
            f"Впевненість: {data.get('why_confidence')}",
        ]
        for event in (data.get("history") or [])[:10]:
            lines.append(f"· {event.get('action')}: {str(event.get('detail'))[:160]}")
        self.show_text_window(f"Спогад {memory_id[-8:]}", "\n".join(lines))

    # ── статус ─────────────────────────────────────────────────────────────
    def set_status(self, text: str) -> None:
        try:
            self.status_label.configure(text=text)
        except tk.TclError:
            return

    def _on_hidden_failure(self, count: int) -> None:
        """Реєстр збоїв повідомив про новий: оновити індикатор.

        Кличеться з будь-якого потоку, тому лише ставимо оновлення в чергу
        головного циклу — tkinter не потокобезпечний.
        """
        try:
            self._ui_call(self._paint_failures, count)
        except Exception:  # noqa: BLE001 - індикатор не має ламати роботу
            LOG.debug("Не вдалось поставити оновлення індикатора", exc_info=True)

    def _paint_failures(self, count: int) -> None:
        try:
            if count <= 0:
                self.failure_label.configure(text="")
            else:
                self.failure_label.configure(text=f"⚠ прихованих збоїв: {count}")
        except tk.TclError:
            pass

    def show_failures(self) -> None:
        """Показати список прихованих збоїв у редакторі."""
        rows = safe.failures()
        if not rows:
            messagebox.showinfo("Приховані збої",
                                "Збоїв не зафіксовано.", parent=self)
            return
        import time as _time

        lines = ["# Приховані збої", "",
                 f"Усього: {len(rows)} (останні зверху)", ""]
        for stamp, where, kind, text in reversed(rows):
            clock = _time.strftime("%H:%M:%S", _time.localtime(stamp))
            lines.append(f"## {clock} · {where}")
            lines.append(f"`{kind}`: {text}")
            lines.append("")
        lines.append("_Повний стек — у журналі `ide.log`._")
        editor = self.tabs.new_file()
        editor.filename = "приховані-збої.md"
        editor.set_text("\n".join(lines))
        self.tabs.rename_tab(editor, "Приховані збої")
        self.set_status(f"Прихованих збоїв: {len(rows)}")

    def show_log(self) -> None:
        from .config import app_data_dir

        log_file = app_data_dir() / "ide.log"
        if not log_file.exists():
            messagebox.showinfo("Журнал", "Журнал ще порожній.", parent=self)
            return
        self.tabs.open_file(log_file)

    # ── самодіагностика й вивід помилок ───────────────────────────────────
    def run_diagnostics(self) -> None:
        """Самодіагностика: чому модель не працює — з причиною й виправленням.

        У лозі користувача модель працювала на 8081 (8080 тримав Steam), а
        клієнт стукав у 8080 — і в інтерфейсі це було просто «модель
        недоступна». Діагностика проходить ланцюг «рушій → файл → порт →
        ключ → відповідь» і показує, де саме обрив.
        """
        self.show_bottom("terminal")
        terminal = getattr(self, "terminal", None)

        def note(text: str) -> None:
            if terminal is not None:
                try:
                    terminal.write_text(text + "\n")
                    return
                except (tk.TclError, AttributeError):
                    pass
            LOG.info("%s", text)

        note("── САМОДІАГНОСТИКА ─────────────────────────────────────────")
        self.set_status("Самодіагностика: перевіряю рушій, порт і модель…")

        def work() -> None:
            from . import diagnostics

            try:
                report = diagnostics.run(
                    settings=self.settings,
                    engine_log_tail=lambda n: self._engine_log_tail(n),
                )
            except Exception as exc:  # noqa: BLE001 - діагностика не має падати
                self._ui_call(note, f"✗ діагностика впала: {exc}")
                return
            self._ui_call(self._after_diagnostics, report)

        threading.Thread(target=work, daemon=True, name="diagnostics").start()

    def _engine_log_tail(self, lines: int = 25) -> str:
        """Останні рядки логу рушія (``server.log``)."""
        try:
            path = runtime.runtime_dir() / "server.log"
            if not path.exists():
                return ""
            raw = path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(raw.splitlines()[-max(1, int(lines)):])
        except (OSError, AttributeError):
            return ""

    def _after_diagnostics(self, report) -> None:
        """Показати звіт у терміналі й оновити великий статус моделі."""
        text = report.text()
        terminal = getattr(self, "terminal", None)
        if terminal is not None:
            try:
                terminal.write_text(text + "\n")
            except (tk.TclError, AttributeError):
                LOG.info("Діагностика:\n%s", text)
        else:
            LOG.info("Діагностика:\n%s", text)
        # Статус у шапці — за фактичною відповіддю моделі.
        answered = any(item.name == "Відповідь моделі" and item.ok
                       for item in report.checks)
        try:
            self.header.set_model_status(
                True if answered else False,
                detail=report.verdict[:160])
        except (tk.TclError, AttributeError):
            pass
        # Адреса в налаштуваннях застаріла — пропонуємо виправити одразу.
        if report.working_url and not report.ok:
            from . import diagnostics as diagnostics_mod
            stale = any(item.name == "Робочий порт"
                        and item.status == diagnostics_mod.WARN
                        for item in report.checks)
            if stale:
                if messagebox.askyesno(
                        "Адреса сервера",
                        f"У налаштуваннях {self.settings.llm.base_url}, але "
                        f"робочий сервер на {report.working_url}.\n\n"
                        f"Перемкнутись на робочу адресу?",
                        parent=self):
                    self._apply_working_url(report.working_url)
                    return
        self.set_status(report.verdict[:200])

    def _apply_working_url(self, url: str) -> None:
        """Записати робочу адресу сервера й одразу перевірити її."""
        if not url:
            return
        self.settings.llm.base_url = url
        self.settings.llm.api_key = runtime.MANAGED_API_KEY
        safe.call_quiet(self.settings.save, where="збереження адреси сервера")
        self.agent.llm_settings = self.settings.llm
        try:
            self.header.set_model_status(True, detail=f"сервер: {url}")
        except (tk.TclError, AttributeError):
            pass
        self.set_status(f"Адресу сервера виправлено: {url}")
        terminal = getattr(self, "terminal", None)
        if terminal is not None:
            try:
                terminal.write_text(f"✓ адресу сервера виправлено: {url}\n")
            except (tk.TclError, AttributeError):
                pass
        self._on_model_changed()
        self.probe_providers(silent=True)

    def _on_model_status_click(self) -> None:
        """Клік по великому статусу моделі → самодіагностика."""
        self.run_diagnostics()

    def show_shortcuts(self) -> None:
        text = (
            "ГАРЯЧІ КЛАВІШІ\n\n"
            "Ctrl+N          новий файл\n"
            "Ctrl+O          відкрити файл\n"
            "Ctrl+S          зберегти\n"
            "Ctrl+Shift+S    зберегти як\n"
            "Ctrl+W          закрити вкладку\n"
            "Ctrl+P          швидке відкриття файлу\n"
            "Ctrl+Shift+P    командна палітра\n"
            "Ctrl+F          пошук у файлі\n"
            "Ctrl+Shift+F    пошук у проєкті\n"
            "Ctrl+G          перейти до рядка\n"
            "Ctrl+/          коментувати рядок\n"
            "Ctrl+D          дублювати рядок\n"
            "Ctrl+B          бічна панель\n"
            "Ctrl+Alt+B      панель агента\n"
            "Ctrl+Alt+K      скіли агента\n"
            "Ctrl+Alt+J      черга завдань\n"
            "Ctrl+`          термінал\n"
            "Ctrl+Alt+C      перервати команду в терміналі\n"
            "Ctrl+= / Ctrl+- розмір шрифту\n"
            "Ctrl+Alt+Enter  надіслати файл агенту\n"
            "F5              запустити файл\n"
            "Ctrl+F5         запустити тести\n"
            "Ctrl+,          налаштування\n"
        )
        messagebox.showinfo(APP_NAME, text, parent=self)

    def show_about(self) -> None:
        messagebox.showinfo(
            "Про програму",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Локальна IDE з агентом у стилі сучасного агентного редактора.\n"
            "Модель: будь-який OpenAI-сумісний сервер (LM Studio, Ollama, llama.cpp).\n"
            "Без моделі працює вбудований офлайн-роутер інструментів.\n\n"
            f"Робоча тека: {self.settings.workspace}\n"
            f"Налаштування: {self.settings.save()}\n",
            parent=self,
        )

    # ── коректне закриття ──────────────────────────────────────────────────
    def _release_model_now(self) -> None:
        """Звільнити відеопам'ять: зупинити всі рушії, якими керує IDE.

        Це окремий метод, а не частина ``on_close``, бо його треба викликати
        з кількох місць: під час закриття вікна, в аварійному обробнику
        (``atexit``) і при виході з помилкою. Ідемпотентний: повторний виклик
        безпечний.

        Що зупиняємо:
        1. керований ``llama-server`` (``_managed_server``);
        2. сервер із хаба моделей (``model_hub.server``);
        3. власний вбудований рушій (``native_runtime``);
        4. будь-які залишкові рушії, записані у файл PID.
        """
        released = False
        # 1. Керований сервер.
        server = getattr(self, "_managed_server", None)
        if server is not None:
            try:
                server.stop()
                released = True
            except Exception:  # noqa: BLE001 - закриття не має падати
                LOG.debug("Керований сервер не зупинився", exc_info=True)
            self._managed_server = None
        # 2. Сервер із панелі хаба.
        try:
            hub_server = getattr(self.model_hub, "server", None)
            if hub_server is not None:
                hub_server.stop()
                self.model_hub.server = None
                released = True
        except Exception:  # noqa: BLE001
            LOG.debug("Сервер хаба не зупинився", exc_info=True)
        # 3. Власний рушій у процесі.
        try:
            self.native_runtime.shut_down()
            released = True
        except Exception:  # noqa: BLE001
            LOG.debug("Власний рушій не вивантажився", exc_info=True)
        # 4. Залишкові процеси від попередніх запусків.
        try:
            removed = runtime.cleanup_stale_processes()
            if removed:
                LOG.info("Прибрано залишкових рушіїв: %s", removed)
                released = True
        except Exception:  # noqa: BLE001
            LOG.debug("Прибирання залишкових процесів не вдалось", exc_info=True)
        if released:
            LOG.info("Відеопам'ять звільнено: рушії IDE зупинено.")
        return None

    def _editor_event(self, sequence: str) -> None:
        """Виконати дію редагування в поточному редакторі.

        ``event_generate("<Control-z>")`` НЕ працює: у Tk клас ``Text`` на
        Windows не має прив'язки ``<Control-z>`` (є лише віртуальна
        ``<<Undo>>``). Тобто «Скасувати» з меню й палітри мовчки нічого не
        робило — перевірено в живому вікні. Тому відомі дії виконуємо
        прямими методами ``Text``, а невідомі передаємо як віртуальні події.
        """
        editor = self.tabs.current()
        if not editor:
            return
        widget = getattr(editor, "text", None)
        if widget is None:
            return
        mapping = {
            "<Control-z>": lambda: widget.edit_undo(),
            "<<Undo>>": lambda: widget.edit_undo(),
            "<Control-y>": lambda: widget.edit_redo(),
            "<<Redo>>": lambda: widget.edit_redo(),
            "<<Copy>>": lambda: widget.event_generate("<<Copy>>"),
            "<<Cut>>": lambda: widget.event_generate("<<Cut>>"),
            "<<Paste>>": lambda: widget.event_generate("<<Paste>>"),
            "<<SelectAll>>": lambda: widget.event_generate("<<SelectAll>>"),
        }
        action = mapping.get(str(sequence or ""))
        try:
            if action is not None:
                action()
                return
            widget.event_generate(sequence)
        except tk.TclError:
            pass
        except Exception:  # noqa: BLE001 - «нічого скасовувати» не помилка
            LOG.debug("Дія редагування %s не виконалась", sequence, exc_info=True)

    def on_close(self) -> None:
        """Закрити застосунок рівно один раз.

        ``on_close`` викликається і кнопкою «×», і пунктом меню, і
        ``atexit``, і тестами. Другий виклик раніше падав з
        ``TclError: cannot invoke "destroy" command: application has been
        destroyed`` — бо вікно вже знищене, а ми знову чіпаємо Tk. Тепер
        повторний вхід тихо виходить.
        """
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self._remember_layout()
        # Контекст активної розмови зберігаємо на диск: інакше після
        # перезапуску чат відкривався б із повідомленнями, але агент не
        # пам'ятав би жодного кроку попередньої роботи.
        try:
            self._save_chat_context(self._active_chat_id())
        except Exception:  # noqa: BLE001 - закриття не має падати
            LOG.debug("Контекст чату не збережено", exc_info=True)
        # Автономний режим має завершитись коректно: файл дописується й
        # зберігається, задачі агента знімаються з черги. Інакше наступний
        # запуск починався б із «обірваної» правки.
        try:
            if self.autonomous_engine.active:
                self._save_all_silently()
                self.autonomous_engine.confirm_stop(
                    reason="Автономний режим вимкнено разом із застосунком.")
        except Exception:  # noqa: BLE001 - закриття не має падати
            LOG.debug("Не вдалось коректно завершити автономний режим", exc_info=True)
        try:
            self.autonomous_engine.queue.save()
        except Exception:  # noqa: BLE001
            pass
        # Виконавець плану має лишити чергу в узгодженому стані: активний
        # крок стає «призупинено», а не «висить» у queue.json. Після
        # наступного запуску користувач натисне «Продовжити» й піде далі.
        try:
            if self.executor.current is not None:
                self.executor.stop(reason="IDE закрито під час виконання кроку")
            else:
                self.task_queue.save()
        except Exception:  # noqa: BLE001 - закриття не має падати
            LOG.debug("Чергу не вдалось зберегти під час закриття", exc_info=True)
        try:
            self.live_preview.on_close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.app.on_close()
        except Exception:  # noqa: BLE001
            pass
        # Власний рушій: модель має бути вивантажена, інакше процес
        # зависає на закритті, тримаючи гігабайти VRAM.
        #
        # Налаштування ``engine.native_unload_on_exit`` РАНІШЕ зберігалось,
        # але ніде не читалось: вивантаження було безумовним. Тепер його
        # поважаємо — воно потрібне тим, хто тримає модель «теплою» між
        # запусками (окремий рушій лишається живим).
        if getattr(self.settings.engine, "native_unload_on_exit", True):
            try:
                self.native_runtime.shut_down()
            except Exception:  # noqa: BLE001
                LOG.debug("Рушій не вивантажився при закритті", exc_info=True)
        else:
            LOG.info("Модель лишена завантаженою (native_unload_on_exit=False)")
        try:
            if self.memory is not None:
                self.memory.close()
        except Exception:  # noqa: BLE001
            LOG.debug("Пам'ять не закрилась коректно", exc_info=True)
        # Скасувати відкладені цикли, щоб не сипались «invalid command name».
        for job in (self._ui_after, self._queue_pump_after, self._resize_after,
                    self._probe_after, self._idle_after, self._autonomous_after):
            if job:
                try:
                    self.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
        # Відкладені перерахунки сашів: вони плануються на 60/240/600 мс і
        # на серію повторів, тож без цього циклу Tk друкував
        # «invalid command name ..._apply_sash_positions» уже після destroy.
        for job in list(getattr(self, "_sash_jobs", [])):
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._sash_jobs = []
        if self._probe is not None:
            try:
                self._probe.cancel()
            except Exception:  # noqa: BLE001
                pass
        for card in (self._model_selector, self._mode_menu):
            if card is not None:
                try:
                    card.destroy()
                except tk.TclError:
                    pass
        # ``cancel_probe`` живе в ``chat_panel.ModelBar``, а ``ModelBar``
        # ніде не створюється — тобто на ``ChatPanel`` такого методу немає
        # (перевірено: ``hasattr(ChatPanel, "cancel_probe") is False``).
        # Виклик через getattr був гарантованим no-op. Шукаємо метод там,
        # де він справді є: спершу в панелі, потім у її рядку моделі.
        for owner in (self.chat, getattr(self.chat, "model_bar", None),
                      getattr(self, "model_bar", None)):
            cancel = getattr(owner, "cancel_probe", None) if owner is not None else None
            if cancel is not None:
                try:
                    cancel()
                except (tk.TclError, AttributeError, RuntimeError):
                    pass
                break
        # Зупинити спінер і таймери чату.
        try:
            stop_spin = getattr(self.chat, "_stop_spinner", None)
            if stop_spin is not None:
                stop_spin()
            cancel_events = getattr(self.chat, "cancel_events", None)
            if cancel_events is not None:
                cancel_events()
        except Exception:  # noqa: BLE001
            pass
        # Таймери панелей: у кожної власна назва поля (_after, _drain_job,
        # _poll_job…). Без цього заплановані виклики лишаються в Tcl і
        # спрацьовують ПІСЛЯ destroy — Tk друкує «invalid command name»
        # і закриття падає з «application has been destroyed». Саме так
        # падав tests/live_every_button.py: 77 натискань проходили, а
        # закриття ламалось.
        cancelled = 0
        for widget in list(getattr(self, "_side_widgets", {}).values()) + [
                self.chat, self.chat.stage_strip, self.chat.queue_strip,
                self.terminal, self.context]:
            try:
                cancelled += widgets.cancel_after(widget)
            except Exception:  # noqa: BLE001 - зняття таймера не має валити вихід
                LOG.debug("Не вдалось зняти таймер віджета", exc_info=True)
        if cancelled:
            LOG.debug("Знято таймерів панелей: %s", cancelled)
        # Зупинити спільний тікер анімації «Справ» — інакше після закриття
        # вікна лишається таймер, що смикає знищені віджети.
        try:
            pulse.forget_ticker(self)
        except Exception:  # noqa: BLE001
            pass
        if not self.tabs.close_all():
            # Користувач відмовився закривати незбережені файли — вікно
            # лишається. Модель НЕ зупиняємо: робота продовжується. Але
            # якщо він усе ж закриє програму інакше (диспетчер задач),
            # спрацює ``atexit``-хук, зареєстрований у конструкторі.
            return
        # ── ВІДЕОКАРТА — ПЕРШИМ ДІЛОМ ───────────────────────────────────────
        #
        # Навіщо саме тут. ``llama-server`` тримає 8–11 ГБ VRAM. Якщо його не
        # зупинити, користувач закриває IDE, а відеокарта лишається зайнятою:
        # ігри не запускаються («щось грузить відеокарту»).
        #
        # Раніше зупинка стояла в кінці ``on_close`` і могла НЕ ВИКОНАТИСЬ:
        # будь-який виняток вище (а їх тут десятки, кожен у своєму try) або
        # достроковий ``return`` лишав процес живим. Тепер звільняємо пам'ять
        # до збереження стану: навіть якщо подальше закриття впаде, VRAM уже
        # вільна.
        self._release_model_now()
        save_session({"tabs": [str(p) for p in self.tabs.all_paths()]})
        self.settings.save()
        self.task_queue.save()
        try:
            self.agent.cancel()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.terminal.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            # Наглядач має спинитись ДО зупинки серверів: інакше він
            # побачить мертві сервери й почне їх перезапускати під час виходу.
            self.mcp_watcher.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            threading.Thread(target=self.mcp_manager.stop_all, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.model_hub.on_close()
            if self.model_hub.server is not None:
                self.model_hub.server.stop()
        except Exception:  # noqa: BLE001
            pass
        # Не лишаємо «сирітський» llama-server, який тримає гігабайти в пам'яті.
        # (Основне звільнення вже відбулось на початку — ``_release_model_now``;
        # тут повторна, ідемпотентна спроба, якщо щось піднялось заново.)
        self._release_model_now()
        if self._queue_pump_after is not None:
            try:
                self.after_cancel(self._queue_pump_after)
            except (tk.TclError, ValueError):
                pass
        try:
            self.destroy()
        except tk.TclError:
            # Вікно вже знищене (подвійний закрив, закриття з atexit).
            LOG.debug("Вікно вже знищене до destroy()")


def launch(settings: Settings) -> int:
    """Запустити застосунок і повернути код виходу."""
    app = BlackChpokIDE(settings)
    app.mainloop()
    return 0
