"""Конфігурація BlackChpok IDE: шляхи, налаштування, журналювання.

Модуль не залежить від tkinter, тому його можна використовувати у тестах
і в консольних перевірках (`python main.py --selftest`).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import tempfile
from dataclasses import dataclass, field, fields, asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import secrets

APP_NAME = "BlackChpok IDE"
APP_SLUG = "BlackChpokIDE"
APP_VERSION = "2.0.0"
ORGANISATION = "BlackChpok AI"

LOG = logging.getLogger("blackchpok")


# ─────────────────────────────────────────────────────────────────────────────
# Шляхи
# ─────────────────────────────────────────────────────────────────────────────

def is_frozen() -> bool:
    """True, якщо код працює зібраним у .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Тека з ресурсами (іконки). У .exe це тимчасова тека _MEIPASS."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def app_data_dir() -> Path:
    """Тека налаштувань і журналів користувача.

    Порядок: змінна BLACKCHPOK_HOME → %APPDATA% → домашня тека → тимчасова.
    Якщо жодна не доступна, повертається тека поруч із програмою.
    """
    override = os.environ.get("BLACKCHPOK_HOME", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    appdata = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    if appdata:
        candidates.append(Path(appdata) / APP_SLUG)
    candidates.append(Path.home() / f".{APP_SLUG.lower()}")
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    if tmp:
        candidates.append(Path(tmp) / APP_SLUG)
    candidates.append(resource_dir() / "userdata")
    for target in candidates:
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return target
        except OSError:
            continue
    return resource_dir()


def data_roots() -> list[Path]:
    """Усі теки, де можуть лежати моделі й рушій.

    Порядок важливий: спершу основна тека програми, далі «переносна» тека
    ``userdata`` поруч із кодом. Так зібрана програма бачить власні
    завантажені моделі, навіть якщо вони лежать у ``userdata`` (портативна
    збірка), а не в ``%APPDATA%``.
    """
    roots: list[Path] = []
    for candidate in (app_data_dir(), resource_dir() / "userdata", resource_dir()):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def find_data_dir(name: str, *, marker: str = "") -> Path:
    """Перша тека ``name`` з усіх ``data_roots``, де вже щось є.

    ``marker`` — ім'я файлу-ознаки (напр. ``llama-server.exe``). Якщо ознаку
    знайдено, повертається ця тека одразу; інакше — основна тека застосунку
    (її й наповнюватиме завантажувач).
    """
    for root in data_roots():
        folder = root / name
        if marker:
            if (folder / marker).exists():
                return folder
            try:
                if folder.is_dir() and any(folder.iterdir()):
                    return folder
            except OSError:
                pass
        elif folder.is_dir():
            try:
                if any(folder.iterdir()):
                    return folder
            except OSError:
                continue
    return app_data_dir() / name


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def session_path() -> Path:
    return app_data_dir() / "session.json"


#: Порти, на яких IDE піднімає ВЛАСНИЙ керований ``llama-server``.
#: Саме їх вважаємо «нашими»: якщо адреса вказує сюди, а рушій увімкнено —
#: це залишок від старого режиму, і його треба виправити.
MANAGED_PORTS = (8080, 8081, 8082, 8083, 8084)


def _points_at_managed_server(url: str, engine: "EngineSettings") -> bool:
    """Чи адреса веде на КЕРОВАНИЙ сервер IDE, а не на чужий сервіс.

    Навіщо розрізняти. Коли користувач увімкнув вбудований рушій, адреса
    ``http://127.0.0.1:8080/v1`` — це неодмінно залишок старого режиму
    (8080 — типовий порт ``llama-server``, який піднімає сама IDE). Але
    ``http://127.0.0.1:1234/v1`` (LM Studio) або ``:11434`` (Ollama) — це
    СВІДОМИЙ вибір користувача, і міняти його не можна.

    Без цього розрізнення міграція нищила б робочу конфігурацію з чужим
    сервером — саме це зламало ``test_ide_core.TestSettings.test_roundtrip``.
    """
    text = (url or "").strip().lower()
    if not text or text.startswith(("native://", "inproc://", "blackchpok://")):
        return False
    if not any(host in text for host in ("127.0.0.1", "localhost", "0.0.0.0")):
        return False
    ports = set(MANAGED_PORTS)
    configured = int(getattr(engine, "port", 0) or 0)
    if configured:
        ports.add(configured)
    for port in ports:
        if f":{port}/" in text or text.endswith(f":{port}"):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Журналювання
# ─────────────────────────────────────────────────────────────────────────────

class _RedactSecrets(logging.Filter):
    """Вичищати схожі на ключі рядки з КОЖНОГО запису журналу.

    Навіщо фільтр, а не «не логувати»: провайдер сам повертає фрагмент
    ключа в тілі помилки (``your api key: ****3456 is invalid``), і цей
    текст іде в ``LOG.info("LLM недоступна: %s", exc)``. Один фільтр на
    обробниках покриває всі місця одразу — включно з тими, які додадуть
    пізніше.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - форматування не має ламати лог
            return True
        cleaned = secrets.redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def _as_int(value: Any, default: int) -> int:
    """Терпиме перетворення у ``int``: зіпсоване значення → типове.

    ``settings.json`` можна відредагувати вручну, і там цілком законно
    трапляється ``"max_steps": "багато"`` або ``"max_tokens": null``.
    Раніше ``int(value)`` кидав ``ValueError`` прямо з ``from_dict``, тобто
    IDE не запускалась узагалі — без вікна й без підказки. Тепер читаємо
    файл завжди, а некоректне поле замінюємо типовим, лишивши попередження.

    Відсутнє поле (``None``) — не помилка: це просто «не задано», тому
    попередження не пишемо, щоб не засмічувати журнал на кожному старті.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        LOG.warning("Очікувалось ціле число, отримано %r — використано %s",
                    value, default)
        return default


def _as_float(value: Any, default: float) -> float:
    """Те саме, що :func:`_as_int`, але для ``float``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        LOG.warning("Очікувалось число, отримано %r — використано %s",
                    value, default)
        return default


def _as_bool(value: Any, default: bool) -> bool:
    """Терпиме перетворення у ``bool`` (``"false"`` більше не стає True)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in ("1", "true", "yes", "так", "on"):
            return True
        if clean in ("0", "false", "no", "ні", "off", ""):
            return False
    return default


def setup_logging(level: int = logging.INFO) -> Path:
    """Пише журнал у файл (у .exe stdout недоступний)."""
    log_file = app_data_dir() / "ide.log"
    if LOG.handlers:
        return log_file
    LOG.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    redactor = _RedactSecrets()
    try:
        handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        LOG.addHandler(handler)
    except OSError as exc:
        # Мовчати тут не можна: якщо журнал не пишеться, користувач втрачає
        # ЄДИНЕ джерело діагностики (у .exe stdout недоступний). Кажемо про
        # це в stderr і позначаємо, що файловий журнал недоступний.
        LOG.warning("Файловий журнал недоступний (%s): %s", log_file, exc)
        if sys.stderr is not None:
            print(f"Увага: журнал не пишеться у {log_file}: {exc}",
                  file=sys.stderr)
    if not is_frozen() and sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(redactor)
        LOG.addHandler(stream)
    return log_file


# ─────────────────────────────────────────────────────────────────────────────
# Налаштування
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = """Ти — BlackChpok AI, автономний програмний агент усередині IDE.

Головне: користувач говорить звичайною людською мовою, як замовник. Він не
зобов'язаний знати назви інструментів, шляхи чи команди. Твоя робота —
зрозуміти, чого він хоче, і зробити це самому, а не перепитувати.

Як читати прохання (це найважливіше):
1. Люди не кажуть «створи файл». Вони кажуть: «зроби калькулятор»,
   «мені потрібен сайт», «хочу гру», «треба щоб було меню», «поміняй колір»,
   «воно не працює». Усе це — ЗАВДАННЯ. Починай робити.
2. Визнач ДІЮ (створити / змінити / запустити / виправити / показати) і
   ПРЕДМЕТ (сайт, гра, кнопка, файл, функція, тест). Якщо предмета не
   названо — подивись, що є в проєкті (list_dir, project_tree), і виріши
   сам, а не питай.
3. Дієслово може бути будь-яке: «зроби», «напиши», «накидай», «намути»,
   «замути», «добав», «перероби», «поміняй», «прибери», «збільш». Сенс
   важливіший за форму слова. Відмінки й помилки в словах — норма.
4. Скарга («не працює», «падає», «нічого не видно», «вилітає») — це
   завдання «знайди причину й полагодь». Не проси текст помилки: спершу
   знайди її сам (run_command, read_file, search_text).
5. Прохання може містити кілька робіт в одному реченні («зроби форму й
   перевір, що зберігає») — виконай усі, по порядку.
6. Уточнюй ЛИШЕ тоді, коли без відповіді можна зробити шкоду: видалити
   дані, перезаписати чужий файл, змінити щось поза проєктом. В усіх
   інших випадках обирай розумний варіант і йди далі.

Як працювати:
1. ІНТЕРНЕТ — ОБОВ'ЯЗКОВИЙ ІНСТРУМЕНТ, А НЕ ОПЦІЯ.
   У тебе є search_web (пошук), fetch_url (прочитати сторінку) і web_api
   (запит до API). Вони працюють завжди, без жодних налаштувань.
   Викликай search_web, коли:
   • питають про ціну (криптовалюта, акції), курс валют, погоду — ЗАВЖДИ,
     без винятків: пам'ять моделі застаріла, цифри треба брати з мережі;
   • питають про новини, події, «що зараз», «останній», «актуальний»;
   • треба дізнатись поточну версію бібліотеки, фреймворку чи API;
   • треба документацію або приклад коду для бібліотеки, яку ти не знаєш
     достеменно (fetch_url на docs);
   • сумніваєшся у факті — перевір, а не вигадуй.
   НІКОЛИ не вигадуй ціни, курси, дати, версії та новини. Якщо мережа
   недоступна — скажи про це прямо.
   Посилання на джерела додавай у відповідь (вони вже приходять у
   результатах пошуку).

2. Дивись фактам у вічі: спершу list_dir / read_file / search_text, потім
   зміни. Не вигадуй вмісту файлів, яких не бачив.
3. Зміни внось через write_file (новий файл), edit_file (точкова правка) або
   append_file (дописати в кінець, не затираючи наявне).
   Один файл — один виклик. Не переписуй файл навмання.
   Якщо просять «додай рядок» — це append_file, а не write_file: інакше
   попередній вміст файлу зникне.
   ЛАПКИ В КОДІ: якщо в тексті є апостроф (ім'я, комп'ютер, м'яч), бери
   подвійні лапки: input("Введіть ім'я: "). Інакше рядок обривається й
   програма не запускається. Після запису коду завжди перевіряй синтаксис
   (python_check) або запуском — інструмент уже попереджає про помилку.
4. Перевіряй результат командою (run_command): запусти сервер, тести,
   компіляцію. Якщо впало — прочитай помилку й виправ. Не оголошуй успіх,
   поки не переконався.
5. Працюй ітераціями: спершу робочий каркас, потім функції, потім
   оздоблення. Не намагайся зробити все одним гігантським файлом.
6. Ніколи не вигадуй результатів команд і не пиши, що щось зроблено, якщо
   інструмент цього не підтвердив.

Приклади «проста фраза → що робити»:
- «зроби калькулятор» → створи calc.py з функціями, запусти перевірку.
- «хочу щоб було темно» → знайди тему/стилі, зміни кольори через edit_file.
- «воно не працює» → запусти проєкт, прочитай помилку, виправ, запусти знову.
- «покажи що там» → list_dir або read_file відкритого файлу, коротко поясни.
- «прибери зайве» → знайди очевидний дубль/сміття, прибери, перевір.
- «яка ціна SOL / біткоїна / долара» → search_web, відповідай із джерелом.
- «як зробити X у FastAPI» → search_web або fetch_url на документацію,
  потім пиши код за знайденим прикладом.

Стиль відповіді: українською, коротко, по суті. У фінальній відповіді —
що зроблено, які файли змінено, як перевірити."""


#: Стислий варіант системного промпту для вузьких вікон контексту.
#:
#: Навіщо окремий текст: повний промпт (≈1670 токенів) разом зі схемами
#: інструментів (≈2335) з'їдав понад половину вікна 8192 і лишав моделі
#: кілька сотень токенів на саму розмову — вона «забувала» початок задачі
#: й плутала кроки. Тут лишені ТІ САМІ правила, але без прикладів і
#: пояснень: приблизно вчетверо коротше.
COMPACT_SYSTEM_PROMPT = """Ти — BlackChpok AI, агент усередині IDE. Розумій звичайну
людську мову: «зроби калькулятор», «поміняй колір», «воно не працює» — це
завдання, а не привід перепитувати. Визнач дію й предмет, подивись факти в
проєкті (list_dir, read_file, search_text) і зроби.

Правила роботи:
1. ІНТЕРНЕТ ОБОВ'ЯЗКОВИЙ. Є search_web (пошук), fetch_url (сторінка),
   web_api (запит до API) — працюють завжди. Викликай search_web для цін,
   курсів, погоди, новин, версій бібліотек і будь-яких свіжих даних.
   НІКОЛИ не вигадуй ціни, курси, дати й версії. Додавай посилання на джерела.
2. Зміни — через write_file (новий файл), edit_file (правка) або append_file
   (дописати, не затираючи). Один файл — один виклик.
3. Після змін перевір синтаксис (python_check) або запуском (run_command).
   Якщо впало — прочитай помилку й виправ. Не оголошуй успіх без перевірки.
4. У рядках із апострофом (ім'я, комп'ютер) бери подвійні лапки:
   input("Введіть ім'я: ").
5. Не вигадуй вмісту файлів і результатів команд. Уточнюй лише тоді, коли
   без відповіді можна зіпсувати дані.
6. Відповідай українською, коротко: що зроблено, які файли змінені, як
   перевірити."""


@dataclass
class LLMSettings:
    """Підключення до локальної або хмарної моделі (OpenAI-сумісний API)."""

    base_url: str = "native://blackchpok"
    model: str = ""
    api_key: str = "local"
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout: int = 300
    auto_detect: bool = True
    reasoning_effort: str = "default"   # default | low | medium | high

    def normalise(self) -> "LLMSettings":
        url = (self.base_url or "").strip().rstrip("/")
        # Вбудований рушій — не HTTP-адреса: дописувати ``/v1`` до
        # ``native://blackchpok`` не можна, інакше стиль провайдера
        # визначався б за шляхом, а не за схемою.
        if url and url.lower().startswith(("native://", "inproc://", "blackchpok://")):
            self.base_url = url
        else:
            if url and not url.endswith("/v1") and "/v1/" not in url:
                url += "/v1"
            self.base_url = url or "http://127.0.0.1:1234/v1"
        self.temperature = max(0.0, min(2.0, float(self.temperature)))
        self.max_tokens = max(256, min(32_000, int(self.max_tokens)))
        self.timeout = max(10, min(1800, int(self.timeout)))
        return self


@dataclass
class UISettings:
    font_family: str = ""
    font_size: int = 12
    tab_size: int = 4
    word_wrap: bool = False
    show_line_numbers: bool = True
    highlight_current_line: bool = True
    sidebar_width: int = 300
    chat_width: int = 460
    context_width: int = 212
    chat_visible: bool = True
    context_visible: bool = True
    bottom_height: int = 200
    composer_height: int = 168
    bottom_visible: bool = False
    restore_session: bool = True
    #: Ширина центральної колонки діалогу. 0 = на всю ширину вікна.
    #: Обмеження лишається доступним для тих, кому зручніше вузька колонка.
    chat_max_width: int = 0
    #: Початковий вид робочої області: ``chat`` (діалог) або ``workspace``.
    #: Типово — ``workspace``: користувач одразу бачить і діалог, і редактор,
    #: а режим «лише чат» вмикається, коли потрібна концентрація.
    view: str = "workspace"
    #: Режим роботи агента (див. :mod:`blackchpok_ide.modes`).
    mode: str = "agent"
    #: Чи показана панель навігації після запуску.
    sidebar_visible: bool = True
    #: Тема інтерфейсу: ``light`` (cream, Cursor-стиль) або ``dark``.
    #: Типово — темна; вибір користувача зберігається в settings.json і
    #: відновлюється при наступному запуску.
    theme: str = "dark"

    def normalise(self) -> "UISettings":
        """Привести значення до відомих і сумісних із поточною версією."""
        clean = str(self.theme or "").strip().lower()
        self.theme = clean if clean in ("light", "dark") else "dark"
        # ── застаріла ширина діалогу ──────────────────────────────────────
        # До версії 1.7.2 чат стискався до 920 px і центрувався. Тепер він
        # має займати всю ширину, а 920 у збереженому settings.json — це
        # СТАРЕ значення, а не вибір користувача: воно перекривало новий
        # типовий 0 і чат лишався вузькою смужкою.
        try:
            width = int(self.chat_max_width or 0)
        except (TypeError, ValueError):
            width = 0
        # Рівно 920 — історичний дефолт: скидаємо до «на всю ширину».
        if width == 920:
            width = 0
        self.chat_max_width = width if width >= 480 else 0
        return self


@dataclass
class AgentSettings:
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    auto_approve_edits: bool = True
    confirm_commands: bool = False       # автономний режим: без підтверджень
    max_steps: int = 8
    offline_fallback: bool = True
    context_char_limit: int = 24_000
    use_skills: bool = True          # додавати увімкнені скіли в системний промпт
    queue_auto_run: bool = True      # виконувати чергу задач автоматично
    permission_mode: str = "workspace"   # read_only | workspace | full
    mode: str = "agent"              # chat | agent | code | plan | tools
    stream: bool = True              # показувати відповідь у міру генерації
    #: Виконувати незалежні читання паралельно (див. tool_orchestrator).
    #:
    #: Вимкнений у слабких/локальних серверах: один контекст моделі й так
    #: серіалізує запити, а паралельні читання дають виграш лише на диску.
    parallel_tools: bool = True
    #: Перевіряти аргументи викликів за схемою ДО виконання.
    #:
    #: Вимкнений лише для сумісності з дуже старими MCP-серверами, які
    #: віддають схеми без опису параметрів.
    validate_tool_arguments: bool = True
    #: Зберігати traces прогонів для вимірювання якості.
    save_traces: bool = True
    #: Пам'ять NEUROMESH бере участь у розумінні запиту.
    #:
    #: Вмикає два напрямки: читання (факти й обмеження проєкту потрапляють
    #: у контекст до запиту до моделі) і запис (підтверджені зміни
    #: запам'ятовуються). Вимкнений — поведінка як раніше: модель сама
    #: викликає ``memory_search``, якщо здогадається.
    memory_participates: bool = True
    #: Будувати план кроків із розуміння наміру (без запиту до моделі).
    #:
    #: Вимкнений для тих, кому заважає смуга етапів над полем вводу.
    auto_plan: bool = True


@dataclass
class McpSettings:
    """Підключення до MCP-серверів (stdio)."""

    enabled: bool = True
    auto_load_workspace: bool = True     # читати .mcp.json / .cursor/mcp.json робочої теки
    servers: list[str] = field(default_factory=list)   # імена вимкнених серверів
    #: Дозволити DOM-міст на ЗОВНІШНІХ сторінках (не лише власний Live
    #: Preview). Типово вимкнено: читання чужого сайту — це доступ до
    #: особистих даних у полях форми. Локальні адреси дозволені завжди.
    allow_external_page_inspection: bool = False


@dataclass
class EngineSettings:
    """Локальний рушій llama.cpp, яким керує сама IDE."""

    managed: bool = False          # True — сервер піднято нашим рушієм
    model_path: str = ""           # GGUF-файл, який запускали останнім
    port: int = 0                  # порт керованого сервера
    backend: str = ""              # cuda | rocm | vulkan | cpu
    auto_start: bool = True        # піднімати модель при старті IDE
    gpu_layers: int = -1           # -1 = визначити автоматично
    ctx_size: int = 0              # розмір вікна контексту (0 = авто з плану)
    #: Вивантажувати модель із відеокарти, коли користувач не працює.
    #: В автономному режимі це не діє: агент працює безперервно.
    unload_when_idle: bool = True
    #: Скільки секунд простою вважати «не працює» (див. :mod:`power`).
    idle_unload_seconds: int = 300
    #: Вбудований рушій у процесі IDE (``llama.dll``), без llama-server.
    #: Значення зберігаються, щоб після перезапуску підняти ту саму модель
    #: з тими самими параметрами.
    #:
    #: ТИПОВО ``True``. Модель працює ВСЕРЕДИНІ процесу IDE: ніяких
    #: сторонніх сервісів (LM Studio, Ollama, окремий llama-server) не
    #: потрібно. Старий шлях із зовнішнім ``llama-server`` лишається
    #: доступним як резервний і вмикається лише явно.
    native: bool = True
    native_model: str = ""         # шлях до GGUF, який вантажити у рушій
    native_gpu_layers: int = -1    # -1 = авто за метаданими моделі
    native_cache_type: str = ""    # "" = авто (q8_0/f16 за прогнозом)
    native_flash_attn: str = "auto"
    #: Знімати модель із пам'яті, коли IDE закривається (типово так).
    native_unload_on_exit: bool = True


@dataclass
class CloudSettings:
    """Підключення до хмарних агентів (DeepSeek, OpenAI тощо)."""

    provider: str = ""             # deepseek | openai | custom | ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    reasoning: bool = True         # дозволяти reasoning-моделі
    max_tokens: int = 8192
    temperature: float = 0.3
    last_check: str = ""           # коли востаннє перевіряли ключ
    last_status: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip())


@dataclass
class VoiceSettings:
    """Голосове керування агентом."""

    enabled: bool = True
    auto_send: bool = True          # надсилати розпізнане одразу
    speak_replies: bool = False     # озвучувати відповіді
    language: str = "uk-UA"
    whisper_dir: str = ""           # тека з whisper-cli.exe
    model_path: str = ""            # файл моделі whisper
    seconds: float = 5.0            # тривалість запису
    rate: int = 0                   # швидкість озвучення SAPI (-10..10)


@dataclass
class SocialAccount:
    """Один налаштований акаунт соцмережі."""

    values: dict[str, str] = field(default_factory=dict)

    def get(self, name: str, default: str = "") -> str:
        return str(self.values.get(name, default) or "")


@dataclass
class SocialSettings:
    """Ключі соцмереж, вписані в програмі (не в змінних середовища)."""

    accounts: dict[str, dict[str, str]] = field(default_factory=dict)

    def account(self, key: str) -> dict[str, str]:
        entry = self.accounts.get(key)
        return dict(entry) if isinstance(entry, dict) else {}

    def set_values(self, key: str, values: dict[str, str]) -> None:
        clean = {name: str(value).strip() for name, value in (values or {}).items()
                 if str(value or "").strip()}
        if clean:
            self.accounts[key] = clean
        else:
            self.accounts.pop(key, None)

    def configured(self, key: str) -> bool:
        return bool(self.account(key))


#: Замок для запису файлів стану. Потрібен, бо кілька потоків можуть
#: зберігати налаштування одночасно (UI-потік, фоновий агент, автозбереження).
#: Без нього 20 потоків билися за один ``.tmp``-файл: ``os.replace`` падав із
#: ``WinError 32`` («файл зайнятий іншим процесом») і ЖОДЕН запис не проходив.
_STATE_WRITE_LOCK = threading.RLock()


def write_json_atomic(target: Path, data: Any, *, indent: int = 2) -> Path:
    """Записати JSON так, щоб збій посеред запису не зіпсував файл.

    Навіщо. Звичайний ``write_text`` відкриває файл на запис і ОДРАЗУ його
    обрізає. Якщо живлення зникне посеред запису (або процес уб'ють),
    на диску лишиться обірваний JSON. ``Settings.load()`` це переживе
    (типові налаштування), але **налаштування користувача буде втрачено
    назавжди** — модель, ключ, робоча тека, нещодавні проєкти.

    Тому пишемо в сусідній ``.tmp`` і підміняємо через ``os.replace``.
    Ця операція атомарна на рівні файлової системи: читач бачить або
    старий файл цілком, або новий цілком, ніколи — половину.

    Ім'я тимчасового файлу унікальне (PID + поток + лічильник): інакше
    два потоки писали б в один ``.tmp`` і ``os.replace`` падав із
    ``WinError 32``. Запис серіалізується замком — так простіше й
    надійніше, ніж ловити гонки на самій файловій системі.
    """
    path = Path(target)
    with _STATE_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=indent)
        suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
        temporary = path.with_name(path.name + suffix)
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            # Не лишаємо сміття: якщо підміна не вдалась, тимчасовий файл
            # більше не потрібен.
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
    return path


def write_text_atomic(target: Path, text: str) -> Path:
    """Те саме для довільного тексту (журнали, списки рядків)."""
    path = Path(target)
    with _STATE_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
        temporary = path.with_name(path.name + suffix)
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
    return path


@dataclass
class Settings:
    workspace: str = ""
    llm: LLMSettings = field(default_factory=LLMSettings)
    ui: UISettings = field(default_factory=UISettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    engine: EngineSettings = field(default_factory=EngineSettings)
    mcp: McpSettings = field(default_factory=McpSettings)
    social: SocialSettings = field(default_factory=SocialSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    cloud: CloudSettings = field(default_factory=CloudSettings)
    shell: str = "cmd.exe /d /s /c"
    recent: list[str] = field(default_factory=list)
    first_run_done: bool = False
    #: Чи користувач справді вибирав теку проєкту.
    #:
    #: Потрібно, бо ``workspace`` типово дорівнює домашній теці: без цього
    #: прапорця «не вибрано нічого» й «свідомо вибрано домашню теку» —
    #: невиразні, і другий випадок назавжди блокував би чат.
    project_chosen: bool = False
    #: Постійні побажання користувача (мова, стиль, обмеження роботи).
    #:
    #: Зберігаються лише ті, які людина назвала прямо («завжди відповідай
    #: українською», «мінімальні правки»). Це НЕ профілювання особистості:
    #: список завжди можна побачити й очистити в налаштуваннях.
    preferences: list[dict[str, Any]] = field(default_factory=list)

    # ── читання / запис ─────────────────────────────────────────────────────
    @staticmethod
    def _only_known(cls_: type, data: dict[str, Any]) -> dict[str, Any]:
        """Лишити лише поля, які справді є в датакласі.

        Навіщо: ``settings.json`` може бути записаний НОВІШОЮ версією IDE
        (додали поле) — і після відкату на старішу версію читання падало з
        ``TypeError: LLMSettings.__init__() got an unexpected keyword
        argument``. Для користувача це виглядало як «IDE не запускається
        після оновлення», без жодної підказки.

        Раніше так фільтрували ЛИШЕ одне поле (``api_key_enc``), вручну.
        Тепер фільтр загальний: невідомі ключі ігноруються, відомі
        читаються. Дані не втрачаються — вони лишаються у файлі, доки
        його не перезаписано новішою версією.
        """
        try:
            known = {f.name for f in fields(cls_)}
        except (TypeError, AttributeError):
            return dict(data or {})
        return {key: value for key, value in (data or {}).items() if key in known}

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        target = path or settings_path()
        data: dict[str, Any] = {}
        if target.exists():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                LOG.warning("Не вдалось прочитати %s: %s", target, exc)
                loaded = {}
            # ``json.loads`` цілком законно повертає число, рядок, список або
            # null — якщо файл пошкоджено чи перезаписано чимось іншим.
            # Раніше результат одразу йшов у from_dict(), де викликався
            # ``data.get(...)``, і користувач отримував
            #   AttributeError: 'int' object has no attribute 'get'
            # ще до появи вікна. Тепер приймаємо лише словник.
            if isinstance(loaded, dict):
                data = loaded
            else:
                LOG.warning(
                    "Файл налаштувань %s має неочікуваний тип (%s) — "
                    "використано типові налаштування",
                    target, type(loaded).__name__)
        settings = cls.from_dict(data)
        if not settings.workspace:
            settings.workspace = str(Path.home())
        return settings

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        llm_data = data.get("llm") if isinstance(data.get("llm"), dict) else {}
        # ``api_key_enc`` — НЕ поле датакласу (це шифротекст у файлі), тож
        # його треба прибрати перед створенням LLMSettings, інакше
        # конструктор падає на невідомому аргументі й налаштування не
        # читаються зовсім.
        llm_fields = {key: value for key, value in llm_data.items()
                      if key not in ("api_key_enc",)}
        # Невідомі поля (з новішої версії IDE) відкидаємо, а не падаємо.
        llm = LLMSettings(**cls._only_known(LLMSettings, llm_fields))
        # ── Секрети: спершу зашифроване поле, потім (застаріле) відкрите ──
        # ``api_key_enc`` — шифротекст DPAPI. Якщо його немає, а ``api_key``
        # лежить відкритим текстом (стара версія), читаємо його як є: ключ
        # має працювати, а перешифрується він під час найближчого save().
        if llm_data.get("api_key_enc"):
            restored = secrets.decrypt(str(llm_data["api_key_enc"]))
            if restored:
                llm.api_key = restored
            elif not str(llm_data.get("api_key") or "").strip():
                # Нічого не прочитали — лишаємо порожнім, щоб агент чесно
                # сказав «ключ не заданий», а не стукав із сміттям.
                llm.api_key = ""
        ui = UISettings(**cls._only_known(
            UISettings, data.get("ui") if isinstance(data.get("ui"), dict) else {})).normalise()
        agent = AgentSettings(**cls._only_known(
            AgentSettings, data.get("agent") if isinstance(data.get("agent"), dict) else {}))
        engine_data = data.get("engine") if isinstance(data.get("engine"), dict) else {}
        engine = EngineSettings(**cls._only_known(EngineSettings, engine_data))
        # ── МІГРАЦІЯ: прапорець рушія й адреса мусять збігатися ────────────
        # У користувача, який увімкнув власний рушій у старій версії,
        # лишилась адреса ``http://127.0.0.1:8080/v1``, а рушій — ``native``.
        # Інтерфейс показував «вбудований», а агент ішов у мережу, де нічого
        # не слухає:
        #
        #   [WinError 10061] No connection could be made because the target
        #   machine actively refused it.
        #
        # Мігруємо ЛИШЕ тоді, коли адреса вказує на ВЛАСНИЙ КЕРОВАНИЙ сервер
        # IDE (порт збігається з ``engine.port`` або типовим 8080). Адреса
        # чужого сервісу (LM Studio 1234, Ollama 11434) — це СВІДОМИЙ вибір
        # користувача, її не чіпаємо: інакше міграція нищила б робочу
        # конфігурацію.
        if engine.native:
            current = str(getattr(llm, "base_url", "") or "")
            if _points_at_managed_server(current, engine):
                LOG.info("Адресу %s виправлено на вбудований рушій: він "
                         "увімкнений, а керований сервер не потрібен", current)
                llm.base_url = "native://blackchpok"
                llm.api_key = "local"
                llm.auto_detect = False
                # Без автозапуску модель не потрапить у рушій узагалі.
                if not engine.auto_start:
                    engine.auto_start = True
                    LOG.info("Автозапуск моделі повернено: увімкнено вбудований рушій")
        mcp_data = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
        mcp = McpSettings(
            enabled=bool(mcp_data.get("enabled", True)),
            auto_load_workspace=bool(mcp_data.get("auto_load_workspace", True)),
            servers=[str(name) for name in (mcp_data.get("servers") or []) if name],
            allow_external_page_inspection=bool(
                mcp_data.get("allow_external_page_inspection", False)),
        )
        cloud_data = data.get("cloud") if isinstance(data.get("cloud"), dict) else {}
        cloud_key = ""
        if cloud_data.get("api_key_enc"):
            cloud_key = secrets.decrypt(str(cloud_data["api_key_enc"]))
        if not cloud_key:
            cloud_key = str(cloud_data.get("api_key") or "")
        cloud = CloudSettings(
            provider=str(cloud_data.get("provider") or ""),
            api_key=cloud_key,
            base_url=str(cloud_data.get("base_url") or ""),
            model=str(cloud_data.get("model") or ""),
            reasoning=_as_bool(cloud_data.get("reasoning", True), True),
            max_tokens=max(256, min(200_000, _as_int(cloud_data.get("max_tokens"), 8192))),
            temperature=max(0.0, min(2.0, _as_float(cloud_data.get("temperature"), 0.3))),
            last_check=str(cloud_data.get("last_check") or ""),
            last_status=secrets.redact(str(cloud_data.get("last_status") or "")),
        )
        voice_data = data.get("voice") if isinstance(data.get("voice"), dict) else {}
        voice = VoiceSettings(
            enabled=_as_bool(voice_data.get("enabled", True), True),
            auto_send=_as_bool(voice_data.get("auto_send", True), True),
            speak_replies=_as_bool(voice_data.get("speak_replies"), False),
            language=str(voice_data.get("language") or "uk-UA"),
            whisper_dir=str(voice_data.get("whisper_dir") or ""),
            model_path=str(voice_data.get("model_path") or ""),
            seconds=max(0.5, min(120.0, _as_float(voice_data.get("seconds"), 5.0))),
            rate=max(-10, min(10, _as_int(voice_data.get("rate"), 0))),
        )
        social = SocialSettings()
        social_data = data.get("social") if isinstance(data.get("social"), dict) else {}
        accounts = social_data.get("accounts")
        if isinstance(accounts, dict):
            for key, entry in accounts.items():
                if isinstance(entry, dict):
                    social.set_values(str(key), entry)
        recent = [str(item) for item in (data.get("recent") or []) if item]
        preferences: list[dict[str, Any]] = []
        raw_prefs = data.get("preferences")
        if isinstance(raw_prefs, list):
            for entry in raw_prefs:
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("key") or "").strip()
                value = str(entry.get("value") or "").strip()
                if not key or not value:
                    continue
                preferences.append({
                    "key": key,
                    "value": value,
                    "said": str(entry.get("said") or ""),
                    "when": _as_float(entry.get("when"), 0.0),
                })
        return cls(
            workspace=str(data.get("workspace") or ""),
            llm=llm.normalise(),
            ui=ui,
            agent=agent,
            engine=engine,
            mcp=mcp,
            social=social,
            cloud=cloud,
            voice=voice,
            shell=str(data.get("shell") or "cmd.exe /d /s /c"),
            recent=recent[:12],
            first_run_done=_as_bool(data.get("first_run_done"), False),
            project_chosen=_as_bool(data.get("project_chosen"), False),
            preferences=preferences,
        )

    def to_dict(self) -> dict[str, Any]:
        """Словник для файлу. СЕКРЕТИ ШИФРУЮТЬСЯ, відкритий текст не пишеться.

        ``api_key`` у ``llm``/``cloud`` замінюється на ``api_key_enc``
        (DPAPI). Якщо шифрування недоступне, поле лишається ПОРОЖНІМ:
        краще попросити ключ знову, ніж покласти його у файл відкритим.
        """
        llm = asdict(self.llm)
        cloud = asdict(self.cloud)
        llm_key = str(llm.pop("api_key", "") or "")
        cloud_key = str(cloud.pop("api_key", "") or "")
        # Локальний ключ («local»/«lm-studio») — НЕ секрет: його пише сам
        # рушій, і він мусить лишитись у файлі, інакше після перезапуску
        # локальний сервер відповідав би 401.
        if llm_key.strip().lower() in ("local", "lm-studio", "none",
                                       "no-key", "not-needed"):
            llm["api_key"] = llm_key
            llm["api_key_enc"] = ""
        else:
            llm["api_key_enc"] = secrets.encrypt(llm_key)
        cloud["api_key_enc"] = secrets.encrypt(cloud_key)
        return {
            "workspace": self.workspace,
            "llm": llm,
            "ui": asdict(self.ui),
            "agent": asdict(self.agent),
            "engine": asdict(self.engine),
            "mcp": asdict(self.mcp),
            "social": asdict(self.social),
            "voice": asdict(self.voice),
            "cloud": cloud,
            "shell": self.shell,
            "recent": list(self.recent),
            "first_run_done": self.first_run_done,
            "project_chosen": self.project_chosen,
            "preferences": list(self.preferences),
            "version": APP_VERSION,
        }


    def save(self, path: Path | None = None) -> Path:
        """Записати налаштування на диск.

        Захист від тестів: якщо виставлено ``BLACKCHPOK_NO_SAVE=1``, запис
        у **типовий** файл користувача не робиться. Тести й скріншот-скрипти
        створюють ``Settings.load()`` і потім ненароком зберігають його —
        так у СПРАВЖНІЙ конфіг потрапляли ``engine.auto_start = False`` та
        інші значення, і локальна модель перестала запускатись сама.

        Явно переданий ``path`` завжди записується: тести, які перевіряють
        саме збереження й читання, мають працювати.
        """
        explicit = path is not None
        target = path or settings_path()
        if not explicit and os.environ.get("BLACKCHPOK_NO_SAVE", "").strip() in {
                "1", "true", "yes"}:
            LOG.info("Збереження налаштувань вимкнено (BLACKCHPOK_NO_SAVE)")
            return target
        try:
            # Атомарний запис: збій живлення посеред запису не має
            # знищити налаштування користувача (див. write_json_atomic).
            write_json_atomic(target, self.to_dict())
        except OSError as exc:
            LOG.warning("Не вдалось зберегти налаштування: %s", exc)
        return target

    # ── зручності ──────────────────────────────────────────────────────────
    def remember_workspace(self, folder: str) -> None:
        self.workspace = folder
        # Свідомий вибір теки — навіть якщо це домашня тека чи корінь диска.
        # Без прапорця такий вибір виглядав би як «нічого не вибрано».
        self.project_chosen = True
        if folder in self.recent:
            self.recent.remove(folder)
        self.recent.insert(0, folder)
        del self.recent[12:]


# ─────────────────────────────────────────────────────────────────────────────
# Сесія (відкриті вкладки, позиції курсора)
# ─────────────────────────────────────────────────────────────────────────────

def load_session() -> dict[str, Any]:
    path = session_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # UnicodeDecodeError — файл записано не в UTF-8 (обірваний запис,
        # чужий редактор, пошкоджений диск). ``read_text`` кидає його ДО
        # json.loads, тому раніше сесія ламала старт.
        return {}
    return data if isinstance(data, dict) else {}


def save_session(data: dict[str, Any]) -> None:
    path = session_path()
    try:
        write_json_atomic(path, data)
    except OSError as exc:
        LOG.warning("Не вдалось зберегти сесію: %s", exc)
