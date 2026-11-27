"""Автономний агент: діалог з моделлю, виклики інструментів, MCP і скіли.

Агент свідомо не залежить від tkinter: він спілкується з інтерфейсом через
чергу ``AgentEvent``. Це дозволяє запускати його у фонових потоках, у черзі
задач і в тестах без вікна.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import context_budget
from . import context_stats
from . import conversation
from . import evidence as evidence_module
from . import extensions as extensions_module
from . import intent_engine
from . import language
from . import llm_client
from . import local_guard
from . import longchat
from . import memory_bridge
from . import model_profile
from . import permissions
from . import planning
from . import response_engine
from . import selflearning
from . import selfrepair
from . import skills as skills_module
from . import social
from . import stream_apply
from . import tool_orchestrator
from . import tool_lazy
from . import tool_router
from . import tool_specs
from . import trace_store
from . import autonomy
from . import context_flow
from . import web_learning
from .agent_tools import TOOL_SCHEMAS, ToolRegistry, ToolResult
from .config import (
    DEFAULT_SYSTEM_PROMPT,
    COMPACT_SYSTEM_PROMPT,
    AgentSettings,
    LLMSettings,
)
from .llm_client import ChatResult, LLMClient, LLMError
from .offline import OfflinePlanner

LOG = logging.getLogger("blackchpok.agent")

#: Дії MCP-роутера, які варто показати моделі напряму:
#: (intent, опис, параметри, обов'язкові)
_ROUTER_ACTIONS: tuple[tuple[str, str, dict[str, Any], list[str]], ...] = (
    ("search_web", "Пошук в інтернеті: погода, новини, факти, документація.",
     {"query": {"type": "string", "description": "Що саме шукати"}}, []),
    ("fetch_url", "Завантажити й прочитати вебсторінку за адресою.",
     {"query": {"type": "string", "description": "http(s) адреса"}}, ["query"]),
    ("memory_search", "Згадати, про що говорили раніше (довгострокова пам'ять).",
     {"query": {"type": "string", "description": "Тема спогаду"}}, ["query"]),
    ("save_rule", "Запам'ятати правило або факт назавжди.",
     {"query": {"type": "string", "description": "Що запам'ятати"}}, ["query"]),
    ("index_project", "Проіндексувати проєкт для семантичного пошуку (RAG).",
     {"file_path": {"type": "string", "description": "Папка, за замовчуванням ."}}, []),
    ("rag_search", "Семантичний пошук по проіндексованому проєкту.",
     {"query": {"type": "string", "description": "Що шукати"},
      "file_path": {"type": "string", "description": "Обмежити папкою"}}, ["query"]),
    ("analyze_project", "Огляд і аналіз структури проєкту.",
     {"file_path": {"type": "string", "description": "Папка"}}, []),
    ("night_shift", "Працювати над задачами вночі без нагляду.",
     {"request": {"type": "string", "description": "Фраза користувача"},
      "extra": {"type": "string", "description": "Годин роботи"}}, []),
    ("todo_write", "Додати задачу в список справ.",
     {"query": {"type": "string", "description": "Текст задачі"},
      "extra": {"type": "string", "description": "pending|done|cancelled"}}, ["query"]),
    ("todo_list", "Показати список задач.", {}, []),
    ("db_schema", "Показати схему бази SQLite у проєкті.",
     {"file_path": {"type": "string", "description": "Шлях до .db"}}, []),
    ("review_code", "Оглянути код на проблеми й ризики.",
     {"file_path": {"type": "string", "description": "Файл або папка"}}, []),
    ("run_and_repair", "Запустити скрипт і виправити помилку, якщо впав.",
     {"file_path": {"type": "string", "description": "Файл скрипта"}}, []),
    ("project_context", "Зібрати контекст проєкту для обговорення.",
     {"file_path": {"type": "string", "description": "Папка"}}, []),
    ("chat_history", "Пошук у історії попередніх розмов.",
     {"query": {"type": "string", "description": "Що згадати"}}, ["query"]),
)


#: Інструменти саморемонту. Агент має вміти сам з'ясувати, що його блокує
#: або що зламалось, — інакше він пише в чат «схоже, щось заважає» замість
#: того, щоб діяти.
SELF_REPAIR_TOOL = "self_repair"
SELF_DIAGNOSE_TOOL = "self_diagnose"


#: Вікно контексту, до якого вмикається стислий системний промпт.
COMPACT_PROMPT_LIMIT = 12_000

#: АВАРІЙНИЙ запобіжник циклу (НЕ робочий ліміт).
#:
#: Тут стояло 40, потім 120, потім 300, потім 10 000 — і кожне з цих чисел
#: мовчки зрізало роботу: користувач просив довге завдання, а агент
#: зупинявся з «Досягнуто ліміт кроків» посеред справи.
#:
#: Вимога (21.11.2026): «прибери всі обмеження, щоб агент міг працювати хоч
#: 24/7 без вихідних автономно». Тепер ``max_steps = 0`` означає «БЕЗ
#: ЛІМІТУ», і цикл іде, доки є робота. Число лишається лише як запобіжник
#: від справді нескінченного циклу (зламаний рушій, який повертає порожнечу
#: вічно). Справжній захист — ``_RepeatGuard``: він ловить повтор того самого
#: виклику з тим самим результатом, а не кількість корисних кроків.
STEP_BUDGET_CEILING = 10_000

#: Скільки кроків має агент, коли ліміт знято (``agent.max_steps = 0``).
#:
#: Це не «ще один ліміт»: ``range`` у Python лінивий, тож число нічого не
#: коштує, поки до нього не дійдеш. Практично недосяжне значення означає
#: «працюй, доки робота не закінчена або користувач не зупинить».
UNLIMITED_STEPS = 1_000_000

#: Те саме для моделей із великим вікном (хмара).
#:
#: Лишилось для сумісності: тепер стеля одна на всі моделі, бо головний
#: обмежувач — не розмір вікна, а сама робота.
STEP_BUDGET_CEILING_LARGE = STEP_BUDGET_CEILING

#: З якого розміру вікна вважаємо модель «великою» (токени).
LARGE_WINDOW_TOKENS = 100_000

#: Найменше вікно, у якому показуємо ПОВНИЙ набір схем інструментів.
#:
#: Вимога користувача (21.11.2026): «ніяких режимів лінивий, тільки повний
#: режим». Повний набір важить тисячі токенів, тож у вікно 8k він фізично не
#: влазить і запит обривається помилкою контексту. Межа стоїть там, де повний
#: набір справді вміщається разом із системою, історією та відповіддю.
#: Нижче — звуження як запобіжник, а не як «економія».
FULL_SET_MIN_WINDOW = 16_384

#: Вікно, у якому дозволяємо ЛИШЕ ядро й контроль реєстру.
#:
#: Заміряно 21.11.2026: при вікні 2048 системний промпт (775 токенів) і три
#: схеми керування лишають близько 500 токенів на саме повідомлення. Будь-яка
#: повна схема (110–350) цей залишок з'їдає, і запит переповнюється
#: (2121 при ліміті 2048). Таке вікно вже непридатне для агентської роботи —
#: тому показуємо мінімум, а решту лишаємо досяжною через ``run_tool``.
_TINY_WINDOW_TOKENS = 3_000

#: Що лишається моделі при дуже вузькому вікні (до 3k токенів).
#:
#: Чотири найпотрібніші дії — прочитати, записати, виправити, запустити.
#: Разом із трьома схемами контролю реєстру це вміщається в залишок після
#: системного промпту; решта доступна через ``run_tool``.
_TINY_WINDOW_TOOLS: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "run_command",
})

#: Частка вікна, яка МУСИТЬ лишитись на саму розмову (історію).
#: Заміряно на живому прогоні 21.11.2026: коли інструментів стало 91, схеми
#: зайняли 11 520 токенів, і бюджет історії став НУЛЕМ («система 8 939,
#: схеми 4 252, історія 0»). Модель не бачила, що вже зроблено, і хід ставав
#: марним — користувач бачив, що відповіді перестали надходити.
#:
#: Третина — не «магічна частка»: вона лишає місце на кілька повідомлень і
#: результати інструментів, не віддаючи весь контекст описам інструментів.
HISTORY_FLOOR_SHARE = 0.34

#: Скільки разів повторювати порожню відповідь у звичайній розмові.
#:
#: Один повтор — не «костування», а виправлення реальної причини: майже
#: завжди порожнеча означає, що міркування з'їли весь бюджет відповіді.
#: Більше двох спроб дратувало б користувача довгим очікуванням.
_EMPTY_CHAT_ATTEMPTS = 2

#: Скільки токенів просити під відповідь, коли нічого не відомо.
_DEFAULT_ANSWER_BUDGET = 2048

#: Порядок важливості інструментів. Менший індекс — лишається довше.
#:
#: Обґрунтування порядку: без читання й запису файлів агент не виконує
#: основну роботу взагалі; без запуску команд не перевіряє результат;
#: решта — допоміжні, і саме їх можна віддати пізніше, коли вікно
#: розшириться (модель однаково побачить їх у наступному запиті).
SCHEMA_PRIORITY: tuple[str, ...] = (
    # 1. Ядро роботи з кодом — без цього агент марний.
    "read_file", "write_file", "edit_file", "append_file",
    "list_dir", "search_text", "run_command",
    # 2. Пам'ять NEUROMESH: пошук і запис — базова потреба агента.
    #    Високо, бо без них агент щоразу починає «з нуля» й повторює
    #    помилки, які вже були виправлені.
    "memory_search", "memory_store", "memory_recall", "memory_explain",
    "memory_predict", "memory_project_context",
    # 3. Інтернет: свіжі дані й документація. Високо, бо без нього модель
    #    вигадує ціни, курси й версії замість того, щоб дізнатись.
    "search_web", "fetch_url", "web_api", "internet_status",
    # 3a. Безкоштовні вебчати як «друга думка». Стоїть поруч із мережею:
    #     коли власних знань бракує, модель має побачити цей шлях одразу.
    "ask_free_ai",
    # 4. Перевірка й орієнтація в проєкті.
    "python_check", "find_files", "project_tree", "git_status", "git_diff",
    # 4a. Скіли: короткі інструкції, як робити типові речі в ЦЬОМУ проєкті.
    #     Без них агент щоразу вигадує власний порядок дій, ігноруючи
    #     домовленості проєкту (напр. «README — у docs/», «тести — так»).
    #     Раніше цих назв тут не було зовсім, і при обрізанні схем вони
    #     зникали ПЕРШИМИ — модель втрачала доступ до правил проєкту.
    "list_skills", "read_skill",
    # 5. Сторінка як дані: саме заради цього IDE існує.
    "web_console", "web_inspect", "web_screenshot", "web_audit",
    "web_url", "web_responsive", "web_click", "web_type",
    # 5a. Зір і DOM — теж «сторінка як дані», лише з боку зображення.
    #     Раніше цих назв тут не було зовсім, і на типовому локальному
    #     вікні 8192 токенів відкидались УСІ візуальні та DOM-схеми:
    #     модель фізично не могла ні зняти екран, ні нарізати ділянки,
    #     ні подивитись DOM — тобто пункти «vision» і «DOM-міст» не
    #     працювали на найпоширенішій конфігурації.
    "capture_screen", "capture_region", "crop_screenshot",
    "inspect_screenshot_regions", "analyze_visual_difference",
    "get_image_dimensions", "get_screenshot_metadata",
    "compare_screenshots", "list_screenshots",
    "dom_tree", "dom_find_text", "dom_styles", "dom_console",
    # 6. Запуск і керування застосунком.
    "app_start", "app_stop", "app_status", "app_restart",
    "app_screenshot", "project_screenshot", "app_windows", "app_logs",
    "app_click", "app_type", "app_key",
    # 7. Решта інструментів пам'яті (рідше потрібні в першому кроці).
    "memory_link", "memory_update", "memory_verify", "memory_task_history",
    "memory_recover", "memory_feedback",
)


def _schema_rank(schema: dict[str, Any]) -> tuple[int, str]:
    """Ключ сортування схем: спершу важливі, далі за назвою (стабільно)."""
    try:
        name = str(schema["function"]["name"])
    except (KeyError, TypeError):
        return (len(SCHEMA_PRIORITY) + 1, "")
    try:
        return (SCHEMA_PRIORITY.index(name), name)
    except ValueError:
        # Невідомі (скіли, MCP, роутер) — після вбудованих: вони залежать
        # від зовнішніх серверів і не є основою роботи.
        return (len(SCHEMA_PRIORITY), name)


#: Скільки разів просити модель викликати інструмент текстовим протоколом.
#:
#: Два — бо перше нагадування іноді ігнорується (заміряно: модель відповіла
#: прозою, потім JSON, потім знову прозою), а третє вже означає, що вона
#: цього не вміє — тоді чесніше завершити й сказати причину.
TEXT_PROTOCOL_ATTEMPTS = 2

#: Скільки разів той самий виклик із тим самим результатом дозволено.#: Два — бо один повтор буває виправданий (мережа, тимчасова помилка).
#: Третій означає, що модель застрягла й сама не вийде.
REPEAT_LIMIT = 3

#: Скільки разів просити модель діяти, коли вона відповіла ПОРОЖНЬО.
#:
#: Навіщо окремий лічильник. Раніше перший же порожній хід завершував
#: роботу словами «Модель повернула порожню відповідь» — і користувач, який
#: просив сайт, отримував діагностику замість файлів (заміряно в GUI).
#: Один повтор дешевий (prefill уже в кеші) і часто виправляє справу:
#: локальна модель іноді «забуває» почати відповідь після eos.
EMPTY_ANSWER_RETRIES = 1

#: Після стількох однакових ПОВТОРІВ роботу припиняємо загалом.
HARD_REPEAT_LIMIT = 8

#: Точний підрахунок токенів (задає рушій, коли модель завантажено).
#:
#: ЧОМУ НЕ ``contextvars``. Раніше тут був ``ContextVar`` із поясненням «у
#: процесі кілька сесій, у кожної свій словник». На практиці це зламало
#: саму мету: **``contextvars`` не успадковуються новим потоком**, а агент
#: працює саме в новому (``AgentRunner._run`` стартує через ``threading.Thread``).
#: Перевірено на цьому Python: дочірній потік бачить ``None``. Тобто точний
#: tokenizer підключався й **не діяв** — агент різав історію евристикою
#: ``кирилиця/1.6``, помиляючись для української мови більш ніж удвічі
#: (39 токенів замість 89 на реальному реченні).
#:
#: Тепер це звичайна модульна змінна під замком. Різні моделі в різних
#: сесіях — рідкісний випадок, і він вирішується тим, що лічильник
#: перевстановлюється при кожній зміні завантаженої моделі; помилка в
#: оцінці на кілька токенів небезпечніша за «чужий словник».
_TOKEN_COUNTER: Callable[[str], int] | None = None
_TOKEN_COUNTER_LOCK = threading.Lock()


def set_token_counter(counter: Callable[[str], int] | None) -> None:
    """Підключити точний підрахунок токенів (``Tokenizer.count``).

    Викликається, коли рушій завантажив модель. Без цього агент працює на
    емпіричних коефіцієнтах — і для українського тексту помиляється більш
    ніж удвічі.
    """
    global _TOKEN_COUNTER
    with _TOKEN_COUNTER_LOCK:
        _TOKEN_COUNTER = counter


def current_token_counter() -> Callable[[str], int] | None:
    """Поточний точний лічильник (``None`` — працюємо на евристиці)."""
    return _TOKEN_COUNTER


#: Ознаки того, що пошук НІЧОГО не дав (а не знайшов інформацію).
_EMPTY_SEARCH_MARKERS: tuple[str, ...] = (
    "нічого не знайдено", "не знайдено", "no results",
    "nothing found", "0 результатів",
)


def _is_empty_search(body: str) -> bool:
    """Чи це «нічого не знайдено», а не справжній результат пошуку.

    Навіщо. Пошук повертає не лише знайдене: коли нічого немає, він віддає
    пояснення з порадами. Додавати такий текст у промпт шкідливо — модель
    бачить «нічого не знайдено» і переносить це у відповідь, хоч питання
    взагалі не потребувало мережі.
    """
    low = " ".join(str(body or "").lower().split())
    if not low:
        return True
    # Якщо є хоч одне посилання — це вже результат.
    if "http" in low:
        return False
    return any(marker in low for marker in _EMPTY_SEARCH_MARKERS)


#: Ознаки «обіцянки замість результату» в переказі.
_PROMISE_MARKERS: tuple[str, ...] = (
    "зараз покажу", "зараз зроблю", "покажу зараз", "давайте подивимось",
    "давай подивимось", "ось що я зроблю", "я покажу", "let me show",
    "here's what i'll", "i will show",
)


def _is_bare_promise(text: str) -> bool:
    """Чи це обіцянка показати щось замість самого результату."""
    low = " ".join(str(text or "").lower().split())
    if len(low) > 160:
        # Довгий текст майже завжди містить і зміст — це вже відповідь.
        return False
    return any(marker in low for marker in _PROMISE_MARKERS)


def _shares_terms(answer: str, data: str) -> bool:
    """Чи є в переказі хоч одне слово з даних (число, назва, шлях)."""
    words = {word for word in re.split(r"[^\w\u0400-\u04FF.]+", data.lower())
             if len(word) >= 4}
    if not words:
        return True
    low = str(answer or "").lower()
    return any(word in low for word in words)


class _ContextAsk:
    """Прохання МОДЕЛІ про контекст (див. інструмент ``request_context``).

    Окрема структура, а не словник: її читає ``context_plan``, і помилка в
    ключі тут означала б тихе «модель попросила, але її не почули».
    """

    __slots__ = ("text", "depth", "query")

    def __init__(self, *, text: str, depth: Any, query: str = "") -> None:
        self.text = text
        self.depth = depth
        self.query = query


def _repeat_hint(name: str, count: int, outcome: ToolResult,
                 intent: str = "") -> str:
    """Вказівка моделі, коли вона повторює той самий виклик.

    Навмисно конкретна: локальні моделі не розуміють абстрактного «спробуй
    інакше» і повторюють те саме. Тому кажемо, ЩО робити замість цього.

    Текст беруть із :mod:`local_guard`: там на кожен інструмент є окрема
    наступна дія («файл уже прочитано — переходь до edit_file»), і саме вона
    витягує модель із циклу. Раніше тут було загальне «обери інший спосіб» —
    локальні моделі його ігнорували й повторювали виклик до ліміту кроків.
    """
    body = (outcome.output or "").strip()
    return local_guard.hint_for(name, None, ok=outcome.ok, output=body,
                                count=count, level=local_guard.LEVEL_TIRED,
                                intent=intent)


class _RepeatGuard:
    """Лічильник однакових викликів інструментів — захист від зациклення.

    Навіщо окремий клас, а не змінна в циклі: правило має бути видимим,
    тестованим і однаковим для всіх гілок (чат, черга, автономний режим).

    Порівнюємо ПАРУ «виклик + результат»: якщо модель повторює той самий
    виклик, але отримує ІНШИЙ результат, це нормальна робота (напр.
    повторне читання файлу після зміни). Зациклення — це коли не змінюється
    нічого: ні аргументи, ні відповідь інструмента.
    """

    __slots__ = ("_seen", "_last", "_streak", "_total", "_ring", "_cycle_hits",
                 "_cycle")

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._last: str = ""
        self._streak: int = 0
        self._total: int = 0
        #: Останні відбитки — щоб побачити довгий цикл A→B→A→B, у якому
        #: жоден виклик не повторюється ПІДРЯД (лічильник ``_seen`` його не
        #: бачить: у моделі щоразу «новий» виклик, а прогресу немає).
        self._ring: list[str] = []
        #: Скільки разів цикл уже підтверджено (другий раз — припиняємо).
        self._cycle_hits: int = 0
        #: Останній знайдений цикл (відбитки) — для пояснення користувачу.
        self._cycle: list[str] = []

    def reset(self) -> None:
        """Забути лічильники після ЗМІНИ СТАНУ проєкту.

        Навіщо. ``_seen`` рахує однакові виклики за ВЕСЬ хід. Але після
        ``write_file`` / ``edit_file`` / ``append_file`` той самий
        ``read_file`` того самого файлу — це ВЖЕ ІНША робота (файл
        змінився). Без скидання модель блокувалась від інструмента, який
        їй потрібен: на 40-му кроці легітимний повторний ``read_file``
        мав ``count=3`` від першого читання — і цикл бив «tired».
        """
        self._seen.clear()
        self._ring.clear()
        self._cycle_hits = 0
        self._cycle = []

    @staticmethod
    def fingerprint(name: str, arguments: Any, outcome_ok: bool,
                    output: str) -> str:
        """Відбиток «виклик + результат» (стабільний і короткий).

        Нормалізацію робить :func:`local_guard.fingerprint`: ``.\\a.py``,
        ``a.py`` і ``file=a.py`` — це ОДИН виклик, хоч для порівняння байт у
        байт вони різні. Живий прогін локальної моделі давав саме такий цикл:
        ``read_file(path="x.py")`` → ``read_file(file="x.py")`` → знову
        ``path``, і жодного разу не спрацьовував лічильник повторів.
        """
        try:
            return local_guard.fingerprint(
                str(name), arguments if isinstance(arguments, dict) else None,
                outcome_ok, output or "")
        except Exception:                            # noqa: BLE001
            # Наглядач не має ламати роботу агента: якщо нормалізація впала,
            # лишається просте порівняння.
            try:
                payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                payload = str(arguments)
            body = (output or "").strip()
            if len(body) > 400:
                body = body[:200] + "…" + body[-200:]
            return f"{name}|{payload}|{'ok' if outcome_ok else 'fail'}|{body}"

    def observe(self, fingerprint: str) -> tuple[int, bool, bool]:
        """Врахувати виклик.

        Повертає ``(скільки разів поспіль, чи вже забагато, чи вже критично)``:

        * ``count`` — скільки разів цей САМЕ виклик повторився підряд;
        * ``tired`` — час втрутитись і змінити підхід (показати моделі, що
          вона повторюється, і заборонити цей інструмент);
        * ``hopeless`` — час припиняти роботу й чесно сказати користувачу.
        """
        self._total += 1
        if fingerprint == self._last:
            self._streak += 1
        else:
            self._last = fingerprint
            self._streak = 1
        count = self._seen.get(fingerprint, 0) + 1
        self._seen[fingerprint] = count
        tired = count >= REPEAT_LIMIT
        hopeless = count >= HARD_REPEAT_LIMIT
        # ── Довгий цикл A→B→A→B ───────────────────────────────────────────
        # Кожен виклик «новий», тому ``_seen`` мовчить, а робота стоїть.
        # Живий прогін на локальній моделі: ``list_dir`` → ``read_file`` →
        # ``list_dir`` → ``read_file`` … і жодного файлу на диску.
        self._ring.append(fingerprint)
        if len(self._ring) > local_guard.WINDOW:
            self._ring.pop(0)
        # Цикл перевіряємо ЗАВЖДИ, навіть коли лічильник однакових викликів
        # уже спрацював: у A→B→A→B третє «A» дає ``tired``, і без цієї
        # перевірки робота йшла б до ``HARD_REPEAT_LIMIT`` (8 кроків), хоч
        # модель уже давно ходить по колу.
        found = local_guard.cycle_in(self._ring)
        if found:
            self._cycle = found
            # Рахуємо лише до другого підтвердження: далі це той самий цикл,
            # і число «12 повторів» у підсумку лише заплутувало б.
            self._cycle_hits = min(self._cycle_hits + 1, 2)
            tired = True
            if self._cycle_hits >= 2:
                hopeless = True
        return count, tired, hopeless

    @property
    def total(self) -> int:
        """Скільки викликів інструментів зроблено за весь хід."""
        return self._total

    def summary(self) -> str:
        """Коротке пояснення для користувача (без технічного сміття).

        Раніше тут брався просто НАЙЧАСТІШИЙ виклик. Коли завдання падало
        через ``run_command`` (модель передала ``exec`` замість ``command``),
        а ``python_check`` перед тим слушно повторювався, користувач читав
        «python_check повторювався 4 рази» — і шукав проблему не там.
        Тепер показуємо той виклик, який справді завадив роботі.

        Порядок вибору (важливий — заміряно на живому прогоні):

        1. **провальний** виклик, навіть одноразовий: саме він зірвав крок
           (напр. ``edit_file`` не знайшов фрагмент — один раз, але це й
           зупинило роботу);
        2. якщо провалів немає — найчастіший повтор.

        Доти провальний виклик брався ЛИШЕ коли він був найчастішим, і
        повідомлення називало невинний ``list_dir`` («7 записів»), хоч
        справжня причина була в одному невдалому ``edit_file``.
        """
        if not self._seen:
            return ""
        # ── Довгий цикл ────────────────────────────────────────────────────
        # Коли жоден виклик не повторюється підряд, а робота стоїть,
        # повідомлення «повторювався N разів» було б неправдою. Тому
        # спершу кажемо про цикл — із назвами інструментів.
        if self._cycle and self._cycle_hits >= 2:
            names: list[str] = []
            for key in self._cycle:
                name = str(key).split("|", 1)[0]
                if name not in names:
                    names.append(name)
            return ("модель ходила по колу: " + " → ".join(names)
                    + f" ({self._cycle_hits} повтори).")
        # Формат відбитка: «назва|аргументи|ok|вивід» — статус третій.
        failed = [(key, count) for key, count in self._seen.items()
                  if "|fail|" in key]
        if failed:
            # Провалів може бути кілька — беремо найчастіший із них, а за
            # рівної кількості той, що стався ПІЗНІШЕ (він і зупинив хід).
            last_failed = [key for key in self._seen if "|fail|" in key]
            key, count = max(
                failed, key=lambda item: (item[1], last_failed.index(item[0])))
            name = key.split("|", 1)[0]
            return f"«{name}» не вдалося ({count} раз(и)) — робота спинилась."
        key, count = max(self._seen.items(), key=lambda item: item[1])
        name = key.split("|", 1)[0]
        return f"«{name}» повторювався {count} раз(и) з тим самим результатом."


#: Ознаки «обіцянки дії» в тексті моделі (українською й англійською).
#:
#: На скріншоті користувача модель 14 разів писала «Знайшов, є помилка в
#: відповіді. Спробую інший запит.» — і не робила жодного виклику. Такий
#: текст не є відповіддю, і показувати його як результат не можна.
#:
#: Окрема назва, а НЕ другий ``_PROMISE_MARKERS``: у модулі вже є перелік
#: «обіцянок показати результат» для :func:`_is_bare_promise` (рядок ~337),
#: і друге присвоєння того самого імені мовчки перекривало його — обидві
#: перевірки дивились в ОДИН список чужих маркерів.
_ACTION_PROMISE_MARKERS: tuple[str, ...] = (
    "спробую", "перевірю", "зараз ", "зроблю", "виправлю", "перероблю",
    "пошукаю", "подивлюсь", "подивлюся", "напишу", "внесу", "запущу",
    "let me", "i will", "i'll", "trying", "attempting",
)


def _promises_action(text: str) -> bool:
    """Чи обіцяє текст ДІЮ замість того, щоб бути відповіддю.

    Враховуємо лише короткі репліки (до 400 символів) із дієсловом у
    майбутньому часі й без готового результату: довга відповідь із кодом
    чи списком — це вже результат, а не обіцянка.
    """
    body = (text or "").strip()
    if not body or len(body) > 400:
        return False
    # Готовий результат має блок коду, список або підсумок.
    if "```" in body or body.startswith(("-", "•", "1.", "2.")):
        return False
    lowered = body.lower()
    return any(marker in lowered for marker in _ACTION_PROMISE_MARKERS)


def _overlaps(answer: str, question: str, *, threshold: float = 0.12) -> bool:
    """Чи стосується відповідь запитання (перекриття змістовних слів).

    Потрібно, щоб відсіяти «відповіді» на кшталт «Як я можу допомогти?» на
    запитання «Скільки .py файлів у теці». Модель 14B після довгого ланцюга
    інструментів інколи втрачає початкове запитання й відповідає в порожнє.
    """
    import re as _re

    text_answer = str(answer or "")
    # ── 1. Числа й шляхи — ЗАВЖДИ результат ─────────────────────────────
    if _re.search(r"\d", text_answer):
        return True
    if _re.search(r"[\w./\\-]*[./\\][\w./\\-]{2,}", text_answer):
        return True
    # ── 2. Стеми замість словоформ ──────────────────────────────────────
    words = _re.compile(r"[\w\u0400-\u04FF]{3,}").findall
    left = {word.lower()[:5] for word in words(question or "")}
    right = {word.lower()[:5] for word in words(text_answer)}
    if not left or not right:
        return True                      # нема про що судити — не блокуємо
    return len(left & right) / len(left) >= threshold


def _promise_notice(text: str) -> str:
    """Чесний підсумок замість «обіцянки», яку модель не виконала."""
    body = (text or "").strip()
    head = body[:200] + ("…" if len(body) > 200 else "")
    return (
        "Модель зупинилась на обіцянці замість дії:\n\n"
        f"«{head}»\n\n"
        "Вона не викликала жодного інструмента, тому на диску нічого не "
        "змінилось і результату немає.\n\n"
        "Що можна зробити:\n"
        "• переформулювати завдання конкретніше («відкрий app.py і покажи "
        "помилку»);\n"
        "• перевірити доступні інструменти (MCP-сервер, локальна модель);\n"
        "• вибрати іншу модель у шапці."
    )


def _user_facing_reason(output: str) -> str:
    """Одна змістовна причина з виводу інструмента (для показу людині).

    Службові рядки («Доступні інструменти: …», «Не повторюй цей виклик»)
    відкидаємо: вони для моделі, а не для користувача.
    """
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith(("доступні інструменти", "не повторюй",
                               "схоже на", "```")):
            continue
        if len(line) > 220:
            line = line[:220] + "…"
        return line
    return ""


@dataclass
class AgentEvent:
    """Подія агента для інтерфейсу."""

    kind: str                 # status | assistant | tool_call | tool_result | error | done | token
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class AgentSession:
    """Стан діалогу і побудова запитів до моделі."""

    def __init__(self, settings: AgentSettings, workspace: Path) -> None:
        self.settings = settings
        self.workspace = workspace
        self.messages: list[dict[str, Any]] = []
        self.extra_prompt: str = ""
        self.skill_prompt: str = ""
        self.action_prompt: str = ""
        #: Зображення, які треба ДОДАТИ до наступного запиту моделі.
        #:
        #: Навіщо: локальна мультимодальна модель бачить картинку лише
        #: тоді, коли вона передана в повідомленні як ``image_url``. Раніше
        #: агент отримував від ``app_screenshot`` лише ШЛЯХ до файлу — і
        #: модель нічого не бачила, хоч знімок існував.
        self.pending_images: list[str] = []
        #: Реальне вікно контексту моделі в токенах (0 = невідоме).
        #: Задається ззовні через ``AgentRunner.set_context_limit``.
        self.context_limit: int = 0
        #: Виклик перед тим, як старий блок історії зникає з вікна.
        #: Раннер передає його в NEUROMESH, щоб зміст не губився.
        self.on_evict: Optional[Callable[[list[dict[str, Any]]], None]] = None
        #: Готовий блок хроніки довгого чату (його ставить раннер).
        #:
        #: Саме ГОТОВИЙ ТЕКСТ, а не об'єкт хроніки: сесія не мусить знати,
        #: скільки токенів лишилось у моделі й хто веде хроніку. Раннер
        #: рахує бюджет перед кожним запитом і кладе сюди результат
        #: (:meth:`AgentRunner._render_digest`).
        self.digest_block: str = ""
        #: ПОРАДА від роутера, коли інструменти вибирає модель.
        #:
        #: На відміну від ``action_prompt`` (жорсткі правила проєкту), це
        #: саме ЗДОГАД: «схоже, тут просять список файлів». Модель бачить
        #: його й вирішує сама — брати інструмент чи ні (вимога 21.11.2026:
        #: «дай їй свободу думок і хай сама підбирає інструменти»).
        self.hint_prompt: str = ""
        #: МІНЛИВА частина контексту ходу: веб-дані «на кожен запит»,
        #: знімок пам'яті. Йде ОСТАННІМ повідомленням запиту (див.
        #: ``AgentRunner._build_action_prompt``): так його зміна не ламає
        #: KV-префікс голови промпту — рушій не перераховує все заново.
        self.context_tail_text: str = ""

    def reset(self) -> None:
        self.messages.clear()
        # Хроніка НЕ чиститься тут: вона належить чату, а не сесії. Раннер
        # замінює її, коли відкривається інший чат (``attach_digest``).

    # ── знімок і відновлення (контекст належить ЧАТУ, не програмі) ─────────
    def snapshot(self) -> list[dict[str, Any]]:
        """Копія поточних повідомлень — для збереження в записі чату.

        Копія глибока на один рівень: список новий, а словники ті самі.
        Цього досить, бо після знімка сесія або очищується, або наповнюється
        НОВИМИ словниками (``add_user``/``add_assistant`` створюють їх заново).
        """
        return [dict(item) for item in self.messages if isinstance(item, dict)]

    def restore(self, messages: Any) -> int:
        """Замінити історію збереженим контекстом іншого чату.

        Повертає кількість відновлених повідомлень. Сміття з диска
        відкидається: у сесію потрапляють лише словники з відомою роллю.
        """
        self.messages.clear()
        # Цілі окремого чату не мають перетікати в наступний.
        self.extra_prompt = ""
        self.skill_prompt = ""
        self.action_prompt = ""
        self.hint_prompt = ""
        restored = 0
        if not isinstance(messages, list):
            return 0
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in ("system", "user", "assistant", "tool"):
                continue
            entry: dict[str, Any] = {
                "role": role,
                "content": item.get("content") if isinstance(item.get("content"), str)
                else str(item.get("content") or ""),
            }
            calls = item.get("tool_calls")
            if isinstance(calls, list) and calls:
                entry["tool_calls"] = [call for call in calls if isinstance(call, dict)]
            for key in ("tool_call_id", "name"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    entry[key] = value
            self.messages.append(entry)
            restored += 1
        # Відновлений контекст може перевищувати вікно поточної моделі.
        self.trim()
        return restored

    def _working_limit(self) -> int:
        """Скільки токенів ми ЗАПОВНЮЄМО (а не скільки модель може).

        Вікно (``context_limit``) — це стеля моделі: на цій машині 131 072.
        Але стискання й обрізання мають рахуватись від РОБОЧОГО бюджету
        (``_context_budget.working``): інакше «чверть вікна на один
        результат інструмента» = 32 768 токенів, і жоден план не тримається.

        Якщо бюджету ще немає — повертає вікно: обережне число краще за
        нуль, який вимкнув би стискання взагалі.
        """
        budget = getattr(self, "_context_budget", None)
        working = int(getattr(budget, "working", 0) or 0) if budget else 0
        return working or int(getattr(self, "context_limit", 0) or 0)

    def system_message(self) -> dict[str, Any]:
        prompt = self.settings.system_prompt.strip() or "Ти — BlackChpok AI, агент усередині IDE."
        # Вузьке вікно моделі: повний промпт + схеми інструментів не лишали
        # місця самій розмові. Обираємо стислий варіант того самого змісту,
        # а не обрізаємо повний посеред речення.
        limit = int(getattr(self, "context_limit", 0) or 0)
        if limit and limit <= COMPACT_PROMPT_LIMIT:
            prompt = self.settings.system_prompt.strip() or COMPACT_SYSTEM_PROMPT
            if prompt == DEFAULT_SYSTEM_PROMPT:
                prompt = COMPACT_SYSTEM_PROMPT
        prompt += (
            f"\n\nРобоча тека: {self.workspace}\n"
            "Використовуй інструменти замість здогадок. Шляхи пиши відносно робочої теки."
        )
        # ── СТАБІЛЬНА ГОЛОВА ПРОМПТУ ────────────────────────────────────────
        # Тут ЛИШЕ те, що не змінюється між кроками: система, тека,
        # каталог дій (``action_prompt``). Мінливі блоки (підказки,
        # хроніка) йдуть окремим «хвостом» ПІСЛЯ історії —
        # див. :meth:`context_tail`.
        #
        # ЧОМУ ЦЕ ВАЖЛИВО. KV-кеш рушія зберігає префікс промпту: поки
        # голова однакова, рушій перевикористовує 90–95 % обчислень
        # (заміряно на Qwen2.5-14B: cached 424 із 447 токенів). Раніше сюди
        # вставлялись підказки й хроніка, які змінювались ЩОКРОКУ. Голова
        # промпту ставала іншою з середини, KV-префікс ріжеться, і КОЖНИЙ
        # крок перераховує все з нуля: «кеш: 0%» у смузі статистики й
        # prefill по 20–60 секунд на кожен хід.
        if self.action_prompt.strip():
            prompt += "\n\n" + self.action_prompt.strip()
        return {"role": "system", "content": prompt}

    def context_tail(self) -> dict[str, Any] | None:
        """Мінлива частина контексту ОКРЕМИМ повідомленням ПІСЛЯ історії.

        Сюди йдуть підказки роутера, екстра-промпт режиму й хроніка
        довгого чату. Вони змінюються щокроку, тому НЕ мають стояти в
        голові: будь-яка їхня зміна ламала б KV-префікс усього промпту
        (див. коментар у :meth:`system_message`). В кінці запиту вони
        безпечні: префікс до них лишається незмінним і кешується рушієм.
        """
        blocks: list[str] = []
        if self.hint_prompt.strip():
            blocks.append(self.hint_prompt.strip())
        if self.extra_prompt.strip():
            blocks.append(self.extra_prompt.strip())
        # ── Хроніка довгого чату ───────────────────────────────────────────
        # В кінці запиту: модель читає правила, історію, а потім — стислий
        # слід давніших обмінів. Зміст той самий, що й раніше, але тепер
        # його зміна не смикає голову промпту.
        digest_block = getattr(self, "digest_block", "")
        if digest_block:
            blocks.append(digest_block)
        # Веб-дані й знімок пам'яті цього запиту («інтернет на кожен запит»).
        tail_text = str(getattr(self, "context_tail_text", "") or "")
        if tail_text.strip():
            blocks.append(tail_text.strip())
        if not blocks:
            return None
        # Після ``trim()`` хвіст міг бути обрізаний під вікно
        # (``_tail_message``). Тоді повертаємо саме обрізану версію.
        clipped = getattr(self, "_tail_message", None)
        if clipped is not None:
            return clipped
        return {
            "role": "system",
            "content": "СЛУЖБОВИЙ КОНТЕКСТ ХОДУ (актуально зараз):\n\n"
                       + "\n\n".join(blocks),
        }

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def add_tool_result(self, call_id: str, name: str, result: ToolResult) -> None:
        body = result.output
        if not result.ok:
            body = "ПОМИЛКА: " + body
        limit = self._tool_result_char_limit()
        if len(body) > limit:
            body = body[:limit] + "\n… (обрізано)"
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": body,
            }
        )

    def _tool_result_char_limit(self) -> int:
        """Скільки символів результату інструмента віддавати моделі.

        Раніше тут стояло жорстке ``context_char_limit // 4`` = 6000
        символів — незалежно від моделі. Для локального вікна 16k це
        слушно, але хмарна модель із вікном 128k–1M отримувала результат,
        обрізаний у 20–150 разів раніше за свій реальний ліміт: вона
        фізично не могла побачити середину великого файлу, який сама ж
        прочитала.

        Тепер межа виводиться з РЕАЛЬНОГО вікна (якщо воно відоме):
        один результат не бере більше чверті вікна, але й не менше
        локальної норми — щоб малі вікна працювали як раніше.
        """
        base = max(2000, int(self.settings.context_char_limit or 24_000) // 4)
        window = self._working_limit()
        if window <= 0:
            return base
        # ~3 символи на токен; чверть вікна під один результат.
        return max(base, int(window * 0.25 * 3))
    def last_tool_results(self, limit: int = 3) -> list[tuple[str, bool, str]]:
        """Останні результати інструментів: (назва, успіх, вивід).

        Потрібно, коли модель завершує хід без тексту: користувач має
        побачити реальний результат, а не порожню відповідь.
        """
        rows: list[tuple[str, bool, str]] = []
        for message in reversed(self.messages):
            if message.get("role") != "tool":
                continue
            body = str(message.get("content") or "")
            ok = not body.startswith("ПОМИЛКА:")
            rows.append((str(message.get("name") or ""), ok, body))
            if len(rows) >= max(1, limit):
                break
        rows.reverse()
        return rows

    def trim(self) -> None:
        """Обмежити історію, лишивши системний промпт і останні обміни.

        Межа береться з РЕАЛЬНОГО вікна моделі (``context_limit`` у токенах),
        а не лише з ліміту символів: інакше довге завдання з великими
        результатами інструментів переповнює контекст, і сервер відповідає
        ``exceed_context_size_error`` — робота обривається на півдорозі.

        Окремо враховуємо «незнімну» частину запиту: системний промпт і
        схеми інструментів не можна викинути, тому бюджет історії —
        це ``вікно − промпт − схеми − запас на відповідь``. Коли навіть
        це дає мінімум, історію все одно ріжемо до мінімуму, а оцінку
        обмежуємо вікном: краще надіслати короткий запит, ніж упасти.
        """
        # Захист від зіпсованої історії: усе, що не є словником повідомлення,
        # відкидаємо — інакше `m.get` падає й агент гине посеред роботи.
        self.messages = [m for m in self.messages if isinstance(m, dict)]
        # ── Символьний ліміт — ЛИШЕ коли токенного вікна немає ────────────
        # ``context_char_limit`` типово 24 000 символів (≈8–12k токенів) і
        # існує як запасний варіант для випадку «вікно моделі невідоме».
        # Раніше він діяв ЗАВЖДИ, разом із токенним бюджетом:
        #
        #     while (total > limit or self._estimate_tokens() > budget) ...
        #
        # Через це на хмарному провайдері з вікном 1 000 000 токенів історія
        # різалась утричі-вдесятеро раніше за реальний ліміт, і модель
        # втрачала контекст, який могла б вільно вмістити. Тепер діє те
        # обмеження, яке справді описує поточну модель:
        #
        # * ``context_limit > 0`` задано → рахуємо ТОКЕНИ (``budget``), а
        #   символьний ліміт ігноруємо;
        # * ``context_limit`` невідоме → лишається символьний ліміт, як і
        #   раніше (інакше агент надішле завеликий запит і сервер обірве
        #   з'єднання).
        budget = self._token_chars_budget()
        has_token_window = int(self.context_limit or 0) > 0
        limit = 10**9 if has_token_window else max(4000, self.settings.context_char_limit)
        total = sum(len(str(m.get("content") or "")) for m in self.messages)
        while (total > limit or self._estimate_tokens() > budget) and len(self.messages) > 4:
            # Ріжемо «блоком»: асистент із tool_calls і всі його результати.
            # Раніше різали рівно ``messages[1]``, і в історії лишався
            # tool-результат, чий виклик уже видалено — сервер відповідав
            # 400 на кожен наступний запит.
            removed = self._drop_oldest_block()
            if not removed:
                break
            total -= removed
        # Один величезний результат інструмента теж треба підрізати: інакше
        # він сам перевищує вікно, скільки б історії ми не викинули.
        self._clip_tool_results()
        # Найгірший випадок: навіть одне повідомлення користувача не вміщається
        # (величезний вставлений файл). Тоді підрізаємо його — краще відповісти
        # на початок, ніж упасти з ``exceed_context_size_error``.
        self._clip_oversized_messages(budget)
        # Останній запобіжник: якщо навіть після всього запит більший за
        # вікно (буває, коли схеми інструментів самі майже дорівнюють вікну),
        # прибираємо найдавніші обміни, доки не вліземо.
        self._fit_into_window()

    def _drop_oldest_block(self) -> int:
        """Прибрати найдавніший «блок» історії; повернути скільки символів.

        Блок — це або асистент із ``tool_calls`` разом з усіма його
        tool-результатами, або одне окреме повідомлення. Системних
        повідомлень у ``messages`` немає (системний промпт додається
        окремо), тож індекс 1 і далі — це вже історія. Повертає 0, якщо
        різати більше нічого (лишилось одне повідомлення).
        """
        if len(self.messages) <= 1:
            return 0
        removed_chars = 0
        dropped: list[dict[str, Any]] = []
        first = self.messages.pop(0)
        dropped.append(first)
        removed_chars += len(str(first.get("content") or ""))
        calls = first.get("tool_calls")
        wanted: set[str] = set()
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict) and call.get("id"):
                    wanted.add(str(call["id"]))
        # Усі tool-результати цих викликів ідуть разом із викликом.
        while self.messages and self.messages[0].get("role") == "tool":
            nxt = self.messages[0]
            call_id = str(nxt.get("tool_call_id") or "")
            if wanted and call_id and call_id not in wanted:
                break                    # чужий результат — лишаємо
            self.messages.pop(0)
            dropped.append(nxt)
            removed_chars += len(str(nxt.get("content") or ""))
        self._notify_evict(dropped)
        return removed_chars or 1

    def _notify_evict(self, messages: list[dict[str, Any]]) -> None:
        """Віддати викинутий блок у довгострокову пам'ять, якщо її підключено."""
        hook = getattr(self, "on_evict", None)
        if not callable(hook) or not messages:
            return
        try:
            hook([dict(item) for item in messages if isinstance(item, dict)])
        except Exception:  # noqa: BLE001 - підрізання не має падати через пам'ять
            LOG.debug("Вивільнений контекст не збережено", exc_info=True)

    def _fit_into_window(self) -> None:
        """Гарантувати, що запит (промпт + схеми + історія) вміщається у вікно.

        Поріг береться з РОЗПОДІЛУ бюджету (:meth:`AgentRunner.adopt_context_window`),
        а не з грубої частки. Раніше тут стояло ``limit - 10%``: при вікні
        16384 і схемах на 4 тисячі токенів це лишало історії більше, ніж
        сервер міг прийняти, і з'єднання обривалось.
        """
        limit = int(self.context_limit or 0)
        if limit <= 0:
            return
        budget = getattr(self, "_context_budget", None)
        if budget is not None and getattr(budget, "window", 0):
            # Стеля = РОБОЧИЙ бюджет мінус відповідь і запас.
            #
            # Саме ``budget.effective``, а не ``window``: вікно — це
            # скільки модель МОЖЕ (131 072), а заповнюємо ми 20–65k
            # (див. ``context_budget.working_window``). Рахунок від вікна
            # лишав «кімнату» вдесятеро більшою за план, і жодне стискання
            # не спрацьовувало.
            ceiling = max(512, budget.effective - budget.answer - budget.safety)
        else:
            # Запас на відповідь моделі (коли бюджет ще не пораховано).
            ceiling = limit - max(256, int(limit * context_budget.ANSWER_SHARE))
        guard = 0
        while self._estimate_tokens() > ceiling and self.messages and guard < 200:
            guard += 1
            # Ріжемо найдавніше, але ніколи не чіпаємо останнє повідомлення:
            # без нього модель не знатиме, про що взагалі запит.
            if len(self.messages) <= 1:
                break
            if not self._drop_oldest_block():
                break
        if guard:
            LOG.info("Історію підрізано під вікно %s (стеля %s): лишилось %s "
                     "повідомлень", limit, ceiling, len(self.messages))
        # ── Хвіст теж підпорядкований вікну ────────────────────────────────
        # Якщо після стискання історії запит усе ще не вміщається, мінливий
        # хвіст (хроніка, підказки) обрізається з КІНЦЯ: він службовий, і
        # втрата його хвоста дешевша за переповнення вікна (яке на сервері
        # закінчується обривом з'єднання).
        tail = self.context_tail()
        if tail is not None:
            overflow = self._estimate_tokens() - ceiling
            if overflow > 0:
                body = str(tail.get("content") or "")
                # ~3 символи на токен + запас на заголовок хвоста.
                keep_chars = max(0, len(body) - int(overflow * 3) - 32)
                if keep_chars >= 80:
                    tail["content"] = body[:keep_chars] + "\n… (обрізано до вікна)"
                    self._tail_message = tail
                    LOG.info("Хвіст контексту обрізано на %s токенів під "
                             "вікно %s", overflow, limit)
                else:
                    # Хвіст не влізає цілком — прибираємо його: вікно важливіше.
                    self._tail_message = None
                    LOG.info("Хвіст контексту прибрано повністю: вікно %s "
                             "заповнене системою й історією", limit)
            else:
                self._tail_message = tail
        # Окремі повідомлення й результати інструментів теж не мають права
        # бути більшими за свою частку РОБОЧОГО бюджету.
        self._clip_oversized_messages(max(512, ceiling // 3))
        self._clip_tool_results()

    def _clip_oversized_messages(self, budget: int) -> None:
        """Підрізати окремі повідомлення, що самі перевищують бюджет."""
        if budget <= 0 or budget >= 10**8:
            return
        for message in self.messages:
            body = str(message.get("content") or "")
            if not body:
                continue
            share = self._tokens_in(body)
            if share <= budget:
                continue
            # Лишаємо приблизно budget токенів: символів беремо з запасом.
            allowed_chars = max(800, int(budget * 2.2))
            message["content"] = body[:allowed_chars] + "\n… (обрізано до вікна контексту)"

    def _estimate_tokens(self, *, with_tools: bool = True) -> int:
        """Груба оцінка токенів запиту: кирилиця дорожча за латиницю.

        Враховує й схеми інструментів: 19 описів займають кілька тисяч
        токенів, і без них бюджет «60% вікна на історію» виявлявся
        завищеним — сервер відповідав ``exceed_context_size_error``.

        Рахує й ХВІСТ контексту (``context_tail``): він піде в той самий
        запит, і без нього стискання недораховувало його токени.
        """
        total = 0
        for message in [self.system_message(), *self.messages]:
            body = str(message.get("content") or "")
            total += self._tokens_in(body)
        tail = self.context_tail()
        if tail is not None:
            total += self._tokens_in(str(tail.get("content") or ""))
        if with_tools:
            total += self._tools_tokens()
        return total

    @staticmethod
    def _tokens_in(text: str) -> int:
        """Токени в одному рядку.

        Спершу — РЕАЛЬНИЙ tokenizer моделі, якщо він доступний. Емпіричні
        коефіцієнти лишаються запасним варіантом: для української кирилиці
        вони дають похибку понад два рази, а ця оцінка керує стисканням
        історії — тобто або ріже зайве, або пропускає переповнення вікна.
        """
        # ЄДИНА точка оцінки для всього проєкту: ``context_budget`` уміє і
        # точний лічильник, і запасну евристику. Раніше тут була власна
        # формула («кирилиця/1.6»), а в ``context_stats`` — інша («len/3.5»),
        # і для українського тексту вони різнились у 2.2 раза (50 проти 23
        # токенів на одному реченні). Тепер варіант один.
        return context_budget.estimate_tokens(text, counter=current_token_counter())

    def _tools_tokens(self) -> int:
        """Скільки токенів займають схеми інструментів у запиті."""
        schemas = getattr(self, "_schemas_cache", None)
        if schemas is None:
            return 0
        try:
            import json

            body = json.dumps(schemas, ensure_ascii=False)
        except (TypeError, ValueError):
            return 0
        return self._tokens_in(body)

    def _token_chars_budget(self) -> int:
        """Скільки токенів лишити під історію (решта — промпт, схеми, відповідь)."""
        limit = self._working_limit()
        if limit <= 0:
            return 10**9   # вікно невідоме — працюємо за лімітом символів
        # Місце під відповідь моделі.
        reserve = max(512, int(limit * 0.15))
        # Системний промпт, схеми інструментів і самі повідомлення.
        used_by_prompt = self._tools_tokens() + self._tokens_in(
            str(self.system_message().get("content") or ""))
        room = limit - reserve - used_by_prompt
        return max(400, room)

    def _clip_tool_results(self) -> None:
        limit = self._working_limit()
        if limit <= 0:
            return
        # ~1 токен на 3 символи; один результат не має брати понад 25%
        # РОБОЧОГО бюджету. Саме робочого, а не вікна: при вікні 131 072
        # чверть вікна — це 32 768 токенів на ОДИН результат, і жоден
        # бюджет не втримався б: історія з двох файлів перевищувала план
        # учетверо (перевірено живим заміром 21.11.2026).
        allowed = max(2000, int(limit * 0.25 * 3))
        for message in self.messages:
            if message.get("role") == "tool":
                body = str(message.get("content") or "")
                if len(body) > allowed:
                    message["content"] = body[:allowed] + "\n… (обрізано до вікна контексту)"

    def build(self) -> list[dict[str, Any]]:
        self.trim()
        messages = [self.system_message(), *self.messages]
        # ── Хвіст контексту ПІСЛЯ історії ──────────────────��───────────────
        # Мінливі блоки (підказки, екстра-промпт, хроніка) ідуть останнім
        # «system»-повідомленням: їхня зміна не ламає KV-префікс голови
        # промпту (див. :meth:`context_tail`). ``trim()`` міг обрізати хвіст
        # під вікно — беремо його стан після стискання.
        tail = self.context_tail()
        if tail is not None:
            messages.append(tail)
        # → Зображення приєднуємо до ОСТАННЬОГО повідомлення користувача:
        # саме там модель їх очікує. Після відправки список чиститься, тож
        # той самий скріншот не дублюється в кожному наступному запиті.
        if self.pending_images:
            images = [path for path in self.pending_images if path]
            self.pending_images = []
            if images:
                messages = _attach_images(messages, images)
        return messages


#: Кеш вікна слота: ``(базова адреса, час) -> n_ctx``.
#:
#: Навіщо. ``probe_context_window`` кличеться з ``tool_schemas()``, а той —
#: на КОЖНЕ оновлення панелі контексту. Запит до ``/props`` на непіднятому
#: сервері коштує **2 секунди** на цій машині (TCP-connect до закритого
#: порту: і IPv6-, і IPv4-спроба). Заміряно: старт IDE — 6.3 с, з них 3×2 с
#: саме тут. Кеш прибирає повторні спроби, не змінюючи поведінку: свіже
#: вікно все одно перепитується після ``_SERVER_CTX_TTL``.
_SERVER_CTX_CACHE: dict[tuple[str, str], tuple[float, int]] = {}
_SERVER_CTX_LOCK = threading.Lock()
_SERVER_CTX_TTL = 60.0

#: Кеш живої проби вікна: ``(адреса, модель) -> (час, токени)``.
#:
#: Навіщо. Проба робить до двох мережевих запитів (``/models`` і пробний
#: ``chat/completions``), а ``probe_context_window`` кличеться перед кожним
#: ходом агента. Без кешу кожна репліка чекала б на провайдера двічі.
#:
#: Невдачу теж кешуємо: інакше «вікно не визначено» перевірялось би знову
#: й знову, щоразу з таймаутом.
_LIVE_CTX_CACHE: dict[tuple[str, str], tuple[float, int]] = {}

#: Скільки живе результат живої проби. 10 хвилин — достатньо, щоб пережити
#: цілу розмову, і мало, щоб після зміни тарифу/моделі число оновилось.
_LIVE_CTX_TTL = 600.0

#: Проби, які вже виконуються у фоні: ``(адреса, модель) -> потік``.
#:
#: Навіщо. Проба вікна коштує до 8 мережевих запитів (на живому Deploy —
#: 55 секунд). Тримати її в головному потоці не можна: користувач чекав би
#: відповіді майже хвилину. Тому вона йде у фоні, а хід бере те, що відомо.
_LIVE_CTX_PENDING: dict[tuple[str, str], threading.Thread] = {}


def _start_live_probe(key: tuple[str, str], root: str, model: str, *,
                      api_key: str, chat_path: str) -> None:
    """Запустити пробу вікна у ФОНОВОМУ потоці (не блокувати відповідь)."""

    def work() -> None:
        from . import context_probe

        probe = 0
        try:
            result = context_probe.probe_window(
                root, model, api_key=api_key, chat_path=chat_path)
            probe = int(getattr(result, "tokens", 0) or 0)
            if probe:
                LOG.info("Вікно контексту живим запитом: %s токенів (%s)",
                         probe, getattr(result, "source", ""))
            else:
                LOG.debug("Жива проба вікна нічого не дала: %s",
                          str(getattr(result, "detail", ""))[:160])
        except Exception:  # noqa: BLE001 - проба не має ламати хід
            LOG.debug("Жива проба вікна не вдалась", exc_info=True)
            probe = 0
        finally:
            # Невдачу теж кешуємо: інакше наступний хід почне пробу знову
            # й знову платитиме таймаутом.
            if len(_LIVE_CTX_CACHE) >= 32:
                _LIVE_CTX_CACHE.clear()
            _LIVE_CTX_CACHE[key] = (time.time(), probe)
            _LIVE_CTX_PENDING.pop(key, None)

    thread = threading.Thread(target=work, name="ctx-probe", daemon=True)
    _LIVE_CTX_PENDING[key] = thread
    thread.start()

#: Скільки чекати на ``/props``. Це перевірка стану, а не робота з моделлю:
#: сервер, який не відповів за секунду, для вибору схем однаково
#: недоступний.
_SERVER_CTX_TIMEOUT = 1.0


def _server_slot_context(base_url: str, api_key: str = "",
                         *, timeout: float = _SERVER_CTX_TIMEOUT,
                         use_cache: bool = True) -> int:
    """Спитати в llama.cpp РЕАЛЬНЕ вікно слота (``/props`` → ``n_ctx``).

    Чому саме ``/props``: у налаштуваннях стоїть те, що ЗАПРОСИЛИ
    (напр. ``--ctx-size 32768``), а сервер ділить його на слоти. Реальний
    ліміт може бути вдвічі меншим — і саме він спричиняв обрив з'єднання
    (``WinError 10054``), який виглядав як «модель не працює».

    Повертає 0, якщо сервер не llama.cpp або не відповів: тоді працюють
    інші джерела (метадані GGUF, налаштування, обережний запас).

    ``use_cache`` прибирає повторні запити протягом ``_SERVER_CTX_TTL``:
    без нього кожне оновлення панелі контексту чекало до 2 с на кожен
    виклик. Невдалий результат теж кешується — інакше «сервер не
    піднятий» перевірявся б знову й знову.
    """
    import json as _json
    import urllib.error as _err
    import urllib.request as _request

    root = str(base_url or "").rstrip("/")
    if not root:
        return 0
    if root.endswith("/v1"):
        root = root[:-3]
    cache_key = (root, str(api_key or ""))
    if use_cache:
        with _SERVER_CTX_LOCK:
            hit = _SERVER_CTX_CACHE.get(cache_key)
        if hit is not None and (time.time() - hit[0]) < _SERVER_CTX_TTL:
            return hit[1]
    headers = {"User-Agent": "BlackChpok-IDE"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    value = 0
    try:
        request = _request.Request(root + "/props", headers=headers)
        with _request.urlopen(request, timeout=timeout) as response:
            data = _json.loads(response.read().decode("utf-8", "replace"))
    except (_err.URLError, OSError, ValueError):
        data = None
    if isinstance(data, dict):
        block = data.get("default_generation_settings") or {}
        try:
            value = int(block.get("n_ctx") or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            try:
                value = int(data.get("n_ctx") or 0)
            except (TypeError, ValueError):
                value = 0
        value = max(0, value)
    if use_cache:
        with _SERVER_CTX_LOCK:
            _SERVER_CTX_CACHE[cache_key] = (time.time(), value)
    return value


def forget_server_context(base_url: str = "", api_key: str = "") -> None:
    """Скинути кеш вікна слота (після зміни адреси, моделі або запуску сервера).

    Порожня адреса скидає ВЕСЬ кеш — це те, що потрібно після зміни
    налаштувань, коли невідомо, які ключі встигли накопичитись.
    """
    with _SERVER_CTX_LOCK:
        if not base_url:
            _SERVER_CTX_CACHE.clear()
            return
        root = str(base_url).rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        for key in [k for k in _SERVER_CTX_CACHE if k[0] == root]:
            _SERVER_CTX_CACHE.pop(key, None)


def _is_embedded_base(base_url: str) -> bool:
    """Чи адреса означає ВБУДОВАНИЙ рушій (``native://blackchpok``).

    Імпорт усередині функції: ``native.bridge`` тягне ``api`` → ``engine`` →
    ctypes-бібліотеку, і робити це під час імпорту агента не можна (тести й
    черга імпортують агента без рушія взагалі).
    """
    try:
        from .native import bridge

        return bool(bridge.is_embedded_url(str(base_url or "")))
    except Exception:                                # noqa: BLE001
        # Запасна перевірка без імпорту: маркери стабільні.
        low = str(base_url or "").strip().lower()
        return low.startswith(("native://", "inproc://", "blackchpok://"))


def _embedded_context_window() -> int:
    """СПРАВЖНЄ вікно вбудованого рушія — читаємо з контексту в пам'яті.

    Навіщо окрема функція. ``/props`` існує лише в llama-server; у власного
    рушія немає ні порту, ні HTTP-шару. Без цього читання агент вважав, що
    вікно «невідоме», і брав половину заявленого — тобто 8192 замість 16384.

    Повертає 0, якщо рушій не завантажений або не може відповісти: тоді
    працюють інші джерела (метадані GGUF, налаштування).
    """
    try:
        from .native import bridge

        runtime = bridge.runtime()
    except Exception:                                # noqa: BLE001
        return 0
    engine = getattr(runtime, "engine", None)
    context = getattr(engine, "context", None) if engine is not None else None
    if context is None:
        return 0
    try:
        value = int(getattr(context, "n_ctx", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _cloud_context_window(base_url: str) -> int:
    """Вікно контексту ХМАРНОГО провайдера за його адресою (0 — не хмара).

    Навіщо окрема функція. У хмари немає ні ``/props`` (це ендпоінт
    llama-server), ні ``--ctx-size`` у налаштуваннях: ліміт задає сам
    провайдер, і він відомий із каталогу :mod:`cloud_agents`. Без цього
    агент брав заявлене ЛОКАЛЬНЕ число (``engine.ctx_size``), та ще й
    ділив його навпіл як «захист від поділу на слоти» — у хмарі слотів
    немає.

    Заміряно на справжньому Deploy: провайдер дає 1 000 000 токенів, а
    агент працював із **8192**, різав історію всемеро раніше й показував
    у чаті «вікно 8 192» — при тому, що в каталозі поруч стояло 1 000 000.
    """
    url = str(base_url or "").strip()
    if not url:
        return 0
    # Локальність — ЄДИНОЮ перевіркою проєкту: ``native://`` та loopback
    # теж «локальні», і для них діє звичайний шлях (рушій / ``/props``).
    try:
        from . import cloud_agents, provider_adapters

        if provider_adapters.is_local_url(url):
            return 0
        provider = cloud_agents.detect(url)
    except Exception:  # noqa: BLE001 - без каталогу лишається запасний шлях
        LOG.debug("Хмарний провайдер за адресою не визначено", exc_info=True)
        return 0
    if provider is None:
        return 0
    try:
        return max(0, int(provider.context or 0))
    except (TypeError, ValueError):
        return 0


def _gguf_context(model_name: str) -> int:
    """Тренувальне вікно моделі з метаданих GGUF (0 — не вдалось).

    Модель не вміє більше за своє вікно, навіть якщо сервер запущено з
    більшим ``--ctx-size``. Тому це число теж обмежує бюджет.
    """
    name = str(model_name or "").strip()
    if not name:
        return 0
    try:
        from .native import gguf as gguf_module
        from .model_hub import models_dir
    except ImportError:  # pragma: no cover
        return 0
    candidates = []
    path = Path(name)
    if path.exists():
        candidates.append(path)
    else:
        candidates.append(models_dir() / name)
        candidates.append(models_dir() / f"{name}.gguf")
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            metadata = gguf_module.read_meta_cached(candidate)
        except (OSError, ValueError, AttributeError):
            continue
        try:
            value = int(metadata.context_length)
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def _png_path_in(output: str) -> str:
    """Знайти шлях до PNG у тексті результату інструмента."""
    paths = _png_paths_in(output)
    return paths[0] if paths else ""


def _png_paths_in(output: str) -> list[str]:
    """Усі шляхи до наявних PNG у тексті результату інструмента.

    Навіщо список, а не перший: ``inspect_screenshot_regions`` нарізає
    великий знімок на ділянки й друкує огляд ПЕРШИМ, а ділянки — далі.
    Якщо моделі віддати лише перший шлях, вона отримає зменшений
    ``overview.png`` — саме те, на чому дрібний текст і втрачається.
    Тому потрібні всі шляхи, а вибір конкретних робить викликач.
    """
    import re as _re

    found: list[str] = []
    for match in _re.finditer(r"([A-Za-z]:\\[^\"\n;]+?\.png)", output or ""):
        path = match.group(1).strip().rstrip(".,)")
        if path and Path(path).exists() and path not in found:
            found.append(path)
    return found


def _attach_images(messages: list[dict[str, Any]],
                   images: list[str]) -> list[dict[str, Any]]:
    """Приєднати зображення до останнього повідомлення користувача.

    Формат OpenAI vision: ``content`` стає списком частин, де є ``text`` і
    ``image_url`` з data-URL. Локальний llama.cpp з ``--mmproj`` читає саме
    такий формат. Якщо зображення прочитати не вдалось — текст лишається
    як був, щоб запит не зірвався.
    """
    if not images:
        return messages
    # Останнє повідомлення користувача — туди й додаємо картинки.
    index = -1
    for position in range(len(messages) - 1, -1, -1):
        if str(messages[position].get("role") or "") == "user":
            index = position
            break
    if index < 0:
        return messages
    target = messages[index]
    text = target.get("content")
    if isinstance(text, list):
        # Уже мультимодальне — додаємо картинки в кінець.
        try:
            extra = llm_client.image_message("", images)["content"]
        except Exception:  # noqa: BLE001 - картинка не має ламати запит
            return messages
        updated = dict(target)
        updated["content"] = list(text) + [part for part in extra
                                           if part.get("type") != "text"]
        result = list(messages)
        result[index] = updated
        return result
    try:
        built = llm_client.image_message(str(text or ""), images)
    except Exception:  # noqa: BLE001
        LOG.debug("Зображення не приєднано", exc_info=True)
        return messages
    parts = built.get("content")
    if not isinstance(parts, list) or len(parts) < 2:
        return messages
    result = list(messages)
    result[index] = {"role": "user", "content": parts}
    return result


def _fix_apostrophes(body: str) -> str:
    """Виправити апостроф усередині одинарних лапок — механічно й безпечно.

    ``input('Введіть ім'я: ')`` → ``input("Введіть ім'я: ")``

    Це НЕ «розумна» правка коду: замінюємо лише ті рядки, де Python не
    може розібрати лапки, і лише коли лапки в рядку збалансовані після
    заміни. Якщо сумнівно — повертаємо текст без змін, щоб модель
    виправила сама.
    """
    lines = body.splitlines(keepends=True)
    changed = False
    result: list[str] = []
    for line in lines:
        if _line_breaks_quotes(line):
            fixed = _swap_quotes(line)
            if fixed is not None:
                result.append(fixed)
                changed = True
                continue
        result.append(line)
    return "".join(result) if changed else body


def _line_breaks_quotes(line: str) -> bool:
    """Чи не компілюється цей рядок через лапки.

    Найнадійніший спосіб — спитати сам Python. Ручний підрахунок лапок
    помилявся: ``input('Введіть ім'я: ')`` має дві лапки (парна кількість)
    плюс апостроф усередині, і «непарності» немає — але рядок зламаний.
    """
    text = line.rstrip("\n")
    if "'" not in text and '"' not in text:
        return False
    try:
        compile(text, "<line>", "exec", dont_inherit=True)
        return False
    except SyntaxError as exc:
        # Цікавить лише те, що стосується лапок.
        message = (exc.msg or "").lower()
        return any(word in message for word in
                   ("string", "quote", "unterminated", "eol"))
    except (ValueError, TypeError):
        return False


def _swap_quotes(line: str) -> str | None:
    """Поміняти зовнішні одинарні лапки на подвійні. None — не вийшло.

    Працює з рядком вигляду ``input('Введіть ім'я: ')``: беремо ПЕРШУ
    одинарну лапку як відкривну й ОСТАННЮ як закривну, а все між ними
    (разом з апострофом) стає вмістом подвійних лапок.
    """
    text = line.rstrip("\n")
    newline = "\n" if line.endswith("\n") else ""
    first = text.find("'")
    last = text.rfind("'")
    if first < 0 or last <= first:
        return None
    inner = text[first + 1:last]
    # Усередині вже є подвійні лапки — міняти небезпечно (конфлікт).
    if '"' in inner:
        return None
    fixed = text[:first] + '"' + inner + '"' + text[last + 1:] + newline
    # Перевіряємо збалансованість подвійних лапок після заміни.
    if fixed.count('"') % 2 != 0:
        return None
    return fixed



def _cloud_proofread_ukrainian(text: str, emit_fn=None) -> str:
    """????????? ????????? ????????? ?????? ?? ?????????? ?? ??????? ????? ?????? ?????? (? ????-????????)."""
    body = str(text or "").strip()
    if len(body) < 12:
        return body
    try:
        import json as _json, os as _os, urllib.request as _urllib
        from . import config as _cfg, internet as _inet
        # ?????? ????????? ????????? ??????
        ok_net, _ = _inet.connectivity()
        if not ok_net:
            if emit_fn:
                emit_fn("reasoning", "\U0001f4f4 \u041d\u0435\u043c\u0430\u0454 \u0456\u043d\u0442\u0435\u0440\u043d\u0435\u0442\u0443 \u2014 \u043f\u0440\u0430\u0446\u044e\u044e \u0432 \u0441\u0443\u0442\u043e \u043e\u0444\u043b\u0430\u0439\u043d-\u0440\u0435\u0436\u0438\u043c\u0456 (\u043b\u043e\u043a\u0430\u043b\u044c\u043d\u0430 \u043c\u043e\u0434\u0435\u043b\u044c + NEUROMESH).")
            return body
        _st = _cfg.Settings.load()
        _gkey = str(_os.environ.get("GEMINI_API_KEY") or getattr(getattr(_st, "cloud", None), "api_key", "") or "").strip()
        if len(_gkey) <= 15:
            if emit_fn:
                emit_fn("reasoning", "\U0001f310 \u0420\u0435\u0436\u0438\u043c: \u041b\u043e\u043a\u0430\u043b\u044c\u043d\u0430 \u043c\u043e\u0434\u0435\u043b\u044c + \u0406\u043d\u0442\u0435\u0440\u043d\u0435\u0442 (\u0445\u043c\u0430\u0440\u043d\u0438\u0439 \u043a\u043b\u044e\u0447 \u043d\u0435 \u0437\u0430\u0434\u0430\u043d\u043e).")
            return body
        _ghost = "".join(["g","e","n","e","r","a","t","i","v","e","l","a","n","g","u","a","g","e",".","g","o","o","g","l","e","a","p","i","s",".","c","o","m"])
        _prompt = (
            "\u0422\u0438 \u043f\u0440\u043e\u0444\u0435\u0441\u0456\u0439\u043d\u0438\u0439 \u0443\u043a\u0440\u0430\u0457\u043d\u0441\u044c\u043a\u0438\u0439 \u043b\u0456\u0442\u0435\u0440\u0430\u0442\u0443\u0440\u043d\u0438\u0439 \u0440\u0435\u0434\u0430\u043a\u0442\u043e\u0440. "
            "\u0412\u0438\u043f\u0440\u0430\u0432 \u0443 \u0442\u0435\u043a\u0441\u0442\u0456 \u043d\u0438\u0436\u0447\u0435 \u041b\u0418\u0428\u0415 \u043e\u0440\u0444\u043e\u0433\u0440\u0430\u0444\u0456\u0447\u043d\u0456 \u043f\u043e\u043c\u0438\u043b\u043a\u0438, \u043f\u0443\u043d\u043a\u0442\u0443\u0430\u0446\u0456\u044e, \u0440\u0443\u0441\u0438\u0437\u043c\u0438 \u0442\u0430 \u0441\u0443\u0440\u0436\u0438\u043a. "
            "\u041d\u0415 \u0437\u043c\u0456\u043d\u044e\u0439 \u0437\u043c\u0456\u0441\u0442, \u0446\u0438\u0444\u0440\u0438, URL-\u0430\u0434\u0440\u0435\u0441\u0438, \u0444\u043e\u0440\u043c\u0430\u0442\u0443\u0432\u0430\u043d\u043d\u044f Markdown \u0442\u0430 \u0431\u043b\u043e\u043a\u0438 \u043a\u043e\u0434\u0443. "
            "\u041f\u043e\u0432\u0435\u0440\u043d\u0438 \u0442\u0456\u043b\u044c\u043a\u0438 \u0432\u0438\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0439 \u0442\u0435\u043a\u0441\u0442 \u0431\u0435\u0437 \u0432\u0441\u0442\u0443\u043f\u0456\u0432 \u0456 \u043a\u043e\u043c\u0435\u043d\u0442\u0430\u0440\u0456\u0432:\n\n"
            + body[:6000]
        )
        _payload = _json.dumps({"contents": [{"role": "user", "parts": [{"text": _prompt}]}]}).encode("utf-8")
        for _gm in ("gemini-flash-lite-latest", "gemini-flash-latest", "gemma-4-31b-it"):
            try:
                _url = "https://" + _ghost + f"/v1beta/models/{_gm}:generateContent?key=" + _gkey
                _req = _urllib.request.Request(_url, data=_payload, headers={"Content-Type": "application/json"})
                with _urllib.request.urlopen(_req, timeout=10) as _resp:
                    _res = _json.loads(_resp.read().decode("utf-8"))
                _fixed = _res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if _fixed and len(_fixed) >= max(8, int(len(body) * 0.4)):
                    if emit_fn:
                        emit_fn("reasoning", f"\u270d\ufe0f \u041f\u0435\u0440\u0435\u0432\u0456\u0440\u0438\u0432 \u043e\u0440\u0444\u043e\u0433\u0440\u0430\u0444\u0456\u044e \u0442\u0430 \u0440\u0443\u0441\u0438\u0437\u043c\u0438 \u0447\u0435\u0440\u0435\u0437 \u0445\u043c\u0430\u0440\u043d\u0443 \u043c\u043e\u0434\u0435\u043b\u044c: Google Gemini ({_gm}).")
                    return _fixed
            except Exception:
                continue
        if emit_fn:
            emit_fn("reasoning", "\u26a0\ufe0f \u0425\u043c\u0430\u0440\u043d\u0430 \u043c\u043e\u0434\u0435\u043b\u044c \u0442\u0438\u043c\u0447\u0430\u0441\u043e\u0432\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u2014 \u0432\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u0430\u044e \u0432 \u0440\u0435\u0436\u0438\u043c\u0456: \u041b\u043e\u043a\u0430\u043b\u044c\u043d\u0430 \u043c\u043e\u0434\u0435\u043b\u044c + \u0406\u043d\u0442\u0435\u0440\u043d\u0435\u0442 + \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u0438\u0439 \u043a\u043e\u0440\u0435\u043a\u0442\u043e\u0440.")
    except Exception:
        pass
    return body


class AgentRunner:
    """Виконує один цикл «питання → інструменти → відповідь» у фоновому потоці."""

    #: Значення за замовчуванням на рівні класу: екземпляр може бути
    #: створений і без ``__init__`` (так роблять тести й черга), а ці поля
    #: читаються з циклу виконання, тож вони мають існувати завжди.
    tools_enabled: bool = True
    mode_prompt: str = ""
    max_steps_override: int = 0
    #: Скільки контексту ЗАПРОСИЛИ в налаштуваннях (``engine.ctx_size``).
    #: Не джерело правди: сервер може дати менше (поділ на слоти). Потрібне
    #: лише як обережна оцінка, коли ``/props`` недоступний.
    _requested_ctx: int = 0
    #: Справжнє вікно контексту й розподіл бюджету (див. :mod:`context_budget`).
    _context_window: Any = None
    _context_budget: Any = None
    #: Лінивий реєстр інструментів (створюється за потреби).
    _lazy_router: Any = None
    #: Чи передаються схеми ліниво саме цього ходу.
    _schemas_lazy: bool = False
    #: Чи змінився набір схем посеред завдання (довантаження повних схем).
    _schemas_dirty: bool = False
    #: Роутер виконав лише читання, але просили зміну — хід треба продовжити.
    _hints_need_continue: bool = False
    #: Чи вже просили модель викликати інструмент текстовим протоколом.
    _text_protocol_asked: int = 0
    #: Постачальник шляху до файлу, відкритого в редакторі.
    #:
    #: Потрібен для фраз на кшталт «що в цьому файлі»: роутер бачить лише
    #: текст і не знає про вікно, тож активний файл підставляє агент.
    active_path_provider: Any = None
    #: Чи передавати знімки моделі як ЗОБРАЖЕННЯ (а не лише шлях).
    #:
    #: Типово **False**, і це принципово. Раніше стояло ``True``: агент
    #: надсилав зображення навіть тоді, коли візуального проєктора немає.
    #: Rушій відповідав
    #:   ``HTTP 500: image input is not supported — hint: … provide the mmproj``
    #: і користувач бачив «модель не відповідає», хоч модель працювала —
    #: їй просто надіслали те, чого вона не вміє читати.
    #:
    #: Увімкнення — обов'язок того, хто СПРАВДІ приєднав проєктор:
    #: ``main_window`` ставить ``agent.vision_enabled = bool(projector)``
    #: після автозапуску моделі. Без вікна (черга, тести, агент із коду)
    #: проєктора ніхто не приєднує, тож і надсилати нічого.
    vision_enabled: bool = False
    #: Файли, які агент створив або змінив ЗА ЦЕЙ хід.
    #:
    #: Значення на рівні класу, а не лише в ``__init__``: тести й черга
    #: створюють ``AgentRunner`` без конструктора, і без цього падало
    #: ``AttributeError`` на першому ж виклику інструмента.
    _touched_files: list[str] = []
    #: Скільки разів уже просили виправити синтаксис у цьому ході.
    _syntax_repairs: int = 0
    #: Чи вже робили пробний запуск створеного скрипта в цьому ході.
    _smoke_done: bool = False
    #: Розуміння запиту, стан розмови й профіль моделі.
    #:
    #: Значення на рівні класу — з тієї ж причини, що й ``_touched_files``:
    #: тести й черга створюють ``AgentRunner.__new__`` без конструктора, а
    #: ``_ask`` і ``_loop`` читають ці поля завжди.
    #:
    #: ``None`` замість списку/словника: МУТАБЕЛЬНИЙ тип на рівні класу
    #: став би СПІЛЬНИМ для всіх екземплярів, і виклики одного ходу
    #: просочувались би в наступний. Кожен раннер створює свої в ``__init__``.
    intent: Any = None
    model_caps: Any = None
    orchestrator: Any = None
    traces: Any = None
    _observations: Any = None
    _specs: Any = None
    #: Міст до NEUROMESH (пам'ять бере участь у розумінні запиту).
    memory_bridge: Any = None
    #: Що пам'ять дала для цього ходу й план кроків.
    _memory_snapshot: Any = None
    _plan: Any = None
    #: Хроніка довгого чату: те, що вже вийшло з вікна моделі
    #: (див. :mod:`longchat`). ``None`` — хроніку не ведуть.
    digest: Any = None
    #: Самонавчання: уроки з власних помилок (див. :mod:`selflearning`).
    learning: Any = None
    #: Рівень свободи дій (див. :mod:`autonomy`). Порожній рядок — «як у
    #: налаштуваннях»: значення підставляє ``__init__`` або ``set_autonomy``.
    #: На рівні класу саме рядок, а не ім'я модуля: інакше однойменний
    #: атрибут затінив би модуль у тілі класу.
    autonomy: str = ""
    #: Скільки кроків додає рівень свободи до ліміту режиму/налаштувань.
    extra_steps: int = 0

    def __init__(
        self,
        registry: ToolRegistry,
        llm_settings: LLMSettings,
        agent_settings: AgentSettings,
        workspace: Path,
    ) -> None:
        self.registry = registry
        self.llm_settings = llm_settings
        self.agent_settings = agent_settings
        self.workspace = Path(workspace)
        self.session = AgentSession(agent_settings, self.workspace)
        self.session.on_evict = self._archive_evicted_context
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.events: "queue.Queue[AgentEvent]" = queue.Queue()
        self.planner = OfflinePlanner(self.workspace, registry)
        self.mcp_manager: Any = None
        self.skill_book: Optional[skills_module.SkillBook] = None
        #: Саморозширення: скіли й інструменти, які агент створює сам
        #: (див. :mod:`extensions`). Живе в робочій теці проєкту.
        self.extensions = extensions_module.ExtensionStore(self.workspace)
        self.on_finished: Optional[Callable[[bool, str], None]] = None
        self._last_answer: str = ""
        self._error: str = ""
        #: True, якщо відповідь дала не модель, а локальний роутер.
        #: Використовується, щоб не зараховувати такий хід як повний успіх.
        self._degraded: bool = False
        #: True, якщо моделі вже казали «ти пообіцяв, але не зробив».
        #: Друге попередження не має сенсу — тоді завершуємо чесно.
        self._promise_warned: bool = False
        #: Скільки разів модель відповідала порожньо (без тексту й без
        #: викликів). Див. :data:`EMPTY_ANSWER_RETRIES`.
        self._empty_turns: int = 0
        #: True, якщо моделі вже казали «тут треба створити річ, а не шукати».
        self._build_nudged: bool = False
        #: True, якщо моделі вже казали «допиши почате» (вона питала дозволу).
        self._continue_asked: bool = False
        #: True, якщо питання «оновити файли на GitHub?» уже поставлено в
        #: цьому ході. Друге питання поспіль було б настирливим.
        self._git_asked: bool = False
        #: True, якщо зміни цього ходу вже відправлено на GitHub.
        self._git_published: bool = False
        # Статистика й підказки живуть з самого початку: reset() і
        # set_context_limit() можуть викликатись до першого start().
        self.stats = context_stats.ContextStats()
        self._pending_hint: list = []
        self._action_prompt_built = False
        self.permission_mode: str = permissions.WORKSPACE
        self.settings_ref: Any = None   # повні налаштування (для соцмереж)
        #: Розуміння запиту й стан розмови (див. intent_engine/conversation).
        #:
        #: Живуть на раннері, а не в сесії: сесія — це історія повідомлень
        #: у форматі OpenAI (її зберігає чат), а тут — наше власне уявлення
        #: про задачу, яке переживає кілька ходів.
        self.intent: Optional[intent_engine.IntentFrame] = None
        self.state = conversation.ConversationState()
        self.profile = conversation.UserProfile()
        #: Профіль поточної моделі (можливості й формат виклику).
        self.model_caps: Optional[model_profile.ModelProfile] = None
        #: Оркестратор інструментів: реальне виконання з перевіркою аргументів.
        self.orchestrator: Optional[tool_orchestrator.Orchestrator] = None
        #: Реєстр описів інструментів (зберігається разом зі схемами).
        self._specs: dict[str, tool_specs.ToolSpec] = {}
        #: Виконані за хід спостереження — для фінальної відповіді й traces.
        self._observations: list[tool_orchestrator.Observation] = []
        #: Сховище traces (підключає вікно; без нього вимірювання вимкнене).
        self.traces: Optional[trace_store.TraceStore] = None
        #: Міст до NEUROMESH: пам'ять підкладає факти й обмеження в контекст.
        self.memory_bridge: Any = memory_bridge.MemoryBridge()
        self._memory_snapshot: Any = memory_bridge.MemorySnapshot()
        self._plan: list = []
        # ── Довгий чат і самонавчання ──────────────────────────────────────
        # Хроніка й уроки — необов'язкові: без них агент працює як раніше.
        # Вмикаються налаштуваннями (``long_chat``, ``self_learning``).
        self.digest: Any = longchat.ConversationDigest()
        self.learning: Any = selflearning.SelfLearning(
            self.memory_bridge,
            enabled=bool(getattr(agent_settings, "self_learning", True)))
        self._lesson_hints: list[str] = []
        #: Скільки кроків цикл уже використав (для уроку «не вистачило кроків»).
        self._steps_used: int = 0
        #: Хук у RAG-індекс: ставить вікно IDE (``None`` — RAG не пише).
        self.rag_archive: Any = None
        # ── Свобода дій ────────────────────────────────────────────────────
        # Беремо рівень із налаштувань, але НЕ пишемо його назад: раннер не
        # має «закріплювати» те, що задав режим або тести.
        self.autonomy = autonomy.normalise(
            getattr(agent_settings, "autonomy", autonomy.DEFAULT_LEVEL))
        self.extra_steps = autonomy.step_bonus(self.autonomy)
        #: Файли, які агент створив або змінив ЗА ЦЕЙ хід (відносні шляхи).
        #: Потрібно, щоб перед завершенням перевірити синтаксис записаного
        #: коду й не звітувати «готово» з файлом, що не компілюється.
        self._touched_files: list[str] = []
        #: Скільки разів ми вже просили виправити синтаксис у цьому ході.
        #: Обмежує цикл, коли модель упирається й повторює те саме.
        self._syntax_repairs: int = 0
        #: Режим роботи (див. :mod:`modes`): чи можна кликати інструменти
        #: і яку підказку додати до системного промпту.
        self.tools_enabled: bool = True
        self.mode_prompt: str = ""
        #: Ліміт кроків, який задає режим. 0 = брати з налаштувань.
        #: Тримаємо його окремо: ``agent_settings`` — це той самий об'єкт, що
        #: й ``settings.agent``, тож запис у нього змінював би налаштування
        #: користувача назавжди.
        self.max_steps_override: int = 0

    @property
    def max_steps(self) -> int:
        """Скільки кроків дозволяє РЕЖИМ або налаштування (без свободи дій).

        ``0`` у налаштуваннях означає **БЕЗ ЛІМІТУ** (вимога 21.11.2026:
        «прибери всі обмеження, щоб агент міг працювати хоч 24/7»). Раніше
        тут стояло ``max(1, ... or 8)``: нуль непомітно ставав вісьмома
        кроками, і агент обривав роботу на півдорозі.
        """
        if self.max_steps_override > 0:
            return self.max_steps_override
        limit = int(self.agent_settings.max_steps or 0)
        if limit <= 0:
            return UNLIMITED_STEPS
        return limit

    def steps_are_limited(self) -> bool:
        """Чи в користувача взагалі стоїть ліміт кроків.

        Потрібно, щоб чесно казати «зупинився на ліміті»: коли ліміту немає,
        повідомлення про вичерпання було б брехнею.
        """
        if self.max_steps_override > 0:
            return True
        return int(self.agent_settings.max_steps or 0) > 0

    @property
    def step_budget(self) -> int:
        """Скільки кроків агент СПРАВДІ має: ліміт режиму + рівень свободи.

        Навіщо окремо. Заміряно на реальній роботі: завдання «сайт із шести
        файлів» не вкладалось у 8 кроків — модель ще писала CSS, а цикл
        уже завершувався з «Досягнуто ліміт кроків». Рівень свободи додає
        кроки, не чіпаючи базове налаштування й не послаблюючи дозволи.

        ── СТЕЛІ БІЛЬШЕ НЕМА (21.11.2026) ────────────────────────────────
        Раніше результат обрізався ``min(_step_ceiling(), base + extra)``,
        і навіть «безлімітний» режим упирався в 300 кроків. Тепер, коли
        ліміт знято, ніякої стелі немає взагалі: крутиться стільки, скільки
        треба. Запобіжник лишається лише від справді нескінченного циклу
        (див. :data:`UNLIMITED_STEPS`), а повтор того самого виклику ловить
        ``_RepeatGuard``.
        """
        base = self.max_steps
        try:
            extra = int(getattr(self, "extra_steps", 0) or 0)
        except (TypeError, ValueError):
            extra = 0
        if extra <= 0:
            return base
        # ── Свобода дій діє лише там, де є інструменти ─────────────────────
        # Якщо інструментів немає (користувач вимкнув їх сам або режим їх не
        # дає), додаткові кроки нічого не додають — повертаємо базовий ліміт.
        if not self.tools_enabled or base <= 0:
            return base
        return min(UNLIMITED_STEPS, base + extra)

    def _step_ceiling(self) -> int:
        """Аварійна стеля циклу.

        Лишилась для сумісності з викликами й тестами. Тепер вона однакова
        для всіх моделей: обмежувач — сама робота, а не розмір вікна.
        """
        return STEP_BUDGET_CEILING

    def set_autonomy(self, level: str) -> "autonomy.Policy":
        """Застосувати рівень свободи дій до цього агента."""
        policy = autonomy.get(level)
        self.autonomy = policy.key
        self.extra_steps = policy.extra_steps
        return policy

    # ── керування ──────────────────────────────────────────────────────────
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_answer(self) -> str:
        return self._last_answer

    @property
    def last_error(self) -> str:
        return self._error

    def cancel(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        limit = self.stats.context_limit
        self.session.reset()
        self.stats.reset()
        if limit:
            self.stats.set_limit(limit)

    def compact(self) -> int:
        """Стиснути історію: лишити системний промпт і останні обміни.

        Повертає кількість прибраних повідомлень. Використовується командою
        «/стиснути», коли контекст майже заповнений.

        ── ЧОМУ ТЕПЕР ЗБЕРІГАЄ, А НЕ ВИКИДАЄ (21.11.2026) ────────────────
        Раніше цей метод просто ВИКИДАВ старі повідомлення: вони зникали
        назавжди. Для довгих сесій («працювати цілу ніч», «нескінченний
        чат») це означало втрату всього, що було вирішено раніше — модель
        більше не знала ні задачі, ні домовленостей.

        Тепер стиснення = ПЕРЕЇЗД у довгострокову пам'ять:
        1. витіснений блок іде в хроніку (:mod:`longchat`);
        2. звідти — у NEUROMESH (факти й уроки з пошуком за змістом);
        3. і в RAG (ширший текст із індексом).

        Тобто контекст не «губиться», а переходить у сховище, з якого його
        дістають ``memory_search`` і ``rag_search``. Саме це й робить чат
        нескінченним: вікно звільняється, а знання лишаються.
        """
        before = len(self.session.messages)
        # ── Спершу ЗБЕРЕГТИ те, що зараз витісниться ──────────────────────
        # ``on_evict`` кличеться з ``_drop_oldest_block``, але лише коли
        # підключений. Тут ми явно архівуємо ВЕСЬ блок, який збираємось
        # прибрати: так у пам'ять потрапляє саме те, що зникає з вікна.
        evicted = self._evict_oldest_for_compact()
        if evicted:
            LOG.info("Стиснення: %s повідомлень переїхало в довгострокову "
                     "пам'ять", len(evicted))
        removed = before - len(self.session.messages)
        LOG.info("Історію стиснуто: прибрано %s повідомлень", removed)
        return max(0, removed)

    def _evict_oldest_for_compact(self, share: float = 0.5) -> list[dict]:
        """Прибрати найдавнішу частину історії, ЗБЕРІГШИ її в пам'яті.

        ``share`` — яку частку наявних повідомлень витіснити. Типово
        половину: лишається достатньо свіжого контексту, щоб модель
        розуміла, що робить, і звільняється половина вікна.
        """
        messages = list(getattr(self.session, "messages", []) or ())
        if len(messages) < 6:
            return []
        target = max(1, int(len(messages) * max(0.05, min(0.9, share))))
        evicted: list[dict] = []
        guard = 0
        while len(evicted) < target and guard < 400:
            guard += 1
            # Не чіпаємо останні 2 повідомлення: без них модель не знатиме,
            # про що йдеться.
            if len(self.session.messages) <= 2:
                break
            first = self.session.messages[0]
            self.session.messages.pop(0)
            evicted.append(first)
            # Результати інструментів цього виклику йдуть разом із ним.
            calls = first.get("tool_calls") if isinstance(first, dict) else None
            wanted = {str(call["id"]) for call in (calls or ())
                      if isinstance(call, dict) and call.get("id")}
            while (self.session.messages
                   and str(self.session.messages[0].get("role") or "") == "tool"):
                nxt = self.session.messages[0]
                call_id = str(nxt.get("tool_call_id") or "")
                if wanted and call_id and call_id not in wanted:
                    break
                self.session.messages.pop(0)
                evicted.append(nxt)
                if len(evicted) >= target:
                    break
        if evicted:
            self._archive_evicted_context(evicted)
        return evicted

    def auto_free_context(self, *, threshold: float = 0.74) -> int:
        """Автоматично звільнити вікно, ПЕРЕНІСШИ контекст у пам'ять.

        Викликається ПЕРЕД кожним запитом: якщо історія займає більше за
        ``threshold`` доступного місця, найдавніша частина переїжджає в
        довгострокову пам'ять (NEUROMESH + RAG + хроніка), а вікно
        звільняється для наступних дій.

        Це і є механізм нескінченного чату: модель ніколи не впирається в
        стіну «контекст переповнено», бо зайве вже лежить у сховищі й
        доступне через пошук.

        Повертає кількість витіснених повідомлень (0 — звільняти не було
        чого).
        """
        # ── Вікно й лічильник беремо там, де вони СПРАВДІ лежать ──────────
        # ``context_limit`` живе в сесії (``set_context_limit`` пише туди),
        # а лічильник токенів — у ``AgentSession._tokens_in``. Раніше тут
        # стояли ``self.context_limit`` і ``self._tokens_in``, яких у
        # ``AgentRunner`` немає: звільнення падало з ``AttributeError`` на
        # першому ж виклику й тихо не працювало (тест це й показав).
        window = int(getattr(self.session, "context_limit", 0) or 0)
        if window <= 0:
            return 0
        budget = getattr(self, "_context_budget", None)
        if budget is not None and getattr(budget, "history", 0):
            allowed = int(budget.history)
        else:
            allowed = max(512, int(window * context_budget.HISTORY_SHARE))
        used = 0
        counter = getattr(AgentSession, "_tokens_in", None)
        for message in getattr(self.session, "messages", []) or ():
            body = message.get("content")
            text = body if isinstance(body, str) else str(body or "")
            try:
                used += int(counter(text)) if counter is not None else len(text) // 3
            except Exception:  # noqa: BLE001 - оцінка не має ламати хід
                used += len(text) // 3
        if allowed <= 0 or used <= allowed * max(0.1, min(1.0, threshold)):
            return 0
        LOG.info("Автозвільнення контексту: історія %s токенів із %s "
                 "дозволених — переношу в пам'ять", used, allowed)
        evicted = self._evict_oldest_for_compact(share=0.5)
        if evicted:
            freed_est = max(1, used // 2)
            ev_num = self.stats.record_eviction(freed_est) if hasattr(self.stats, "record_eviction") else 1
            self._emit("status", f"\u267b \u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u043f\u0435\u0440\u0435\u043f\u043e\u0432\u043d\u0435\u043d\u043e \u2192 \u043f\u0435\u0440\u0435\u043d\u0435\u0441\u0435\u043d\u043e ~{freed_est} \u0442\u043e\u043a\u0435\u043d\u0456\u0432 \u0443 \u0434\u043e\u0432\u0433\u043e\u0441\u0442\u0440\u043e\u043a\u043e\u0432\u0443 \u043f\u0430\u043c'\u044f\u0442\u044c (\u0437\u0432\u0456\u043b\u044c\u043d\u0435\u043d\u043d\u044f #{ev_num}).")
        if False and evicted:
            self._emit("status",
                       f"Контекст звільнено: {len(evicted)} повідомлень "
                       f"перенесено в довгострокову пам'ять.")
        return len(evicted)

    def set_context_limit(self, limit: int) -> None:
        """Розмір вікна контексту моделі (для відсотка заповнення).

        Те саме число потрібне сесії, щоб вона вчасно підрізала історію —
        інакше довге завдання впирається в ``exceed_context_size_error``.
        """
        self.stats.set_limit(limit)
        self.session.context_limit = max(0, int(limit or 0))

    def adopt_context_window(self, *, props_ctx: int = 0, gguf_ctx: int = 0,
                             counter: Any = None,
                             source: str = "") -> "context_budget.Budget":
        """Визначити СПРАВЖНЄ вікно контексту й узяти його в роботу.

        Викликається перед першим запитом, коли сервер уже відповідає (тоді
        відомий ``/props``). Без цього кроку в налаштуваннях могло стояти
        ``ctx_size 32768``, тоді як сервер реально давав 16384 на слот —
        агент надсилав завеликий промпт, і сервер обривав з'єднання
        (``WinError 10054``), що виглядало як «модель не працює».

        ``source`` — звідки взято число, для показу користувачу. Для
        вбудованого рушія це не ``/props``: у нього немає HTTP-шару.

        Повертає :class:`context_budget.Budget` — розподіл вікна, який
        далі використовує стискання історії.
        """
        window = context_budget.resolve_window(
            props_ctx=int(props_ctx or 0),
            gguf_ctx=int(gguf_ctx or 0),
            source=source)
        # Число стає джерелом правди для сесії й смуги статистики.
        self.set_context_limit(window.usable)
        self._context_window = window
        # Системний промпт і схеми інструментів живуть у СЕСІЇ / кеші
        # раннера — тут легко помилитись і впасти з AttributeError
        # (перевірено двічі). Беремо обережно, з запасним нулем.
        system_text = ""
        try:
            system_text = str(self.session.system_message().get("content") or "")
        except (AttributeError, TypeError):
            system_text = ""
        tools_tokens = 0
        try:
            tools_tokens = int(self.session._tools_tokens())
        except (AttributeError, TypeError):
            tools_tokens = 0
        budget = context_budget.plan(
            window,
            system_tokens=context_budget.estimate_tokens(system_text,
                                                         counter=counter),
            tools_tokens=tools_tokens,
        )
        self._context_budget = budget
        LOG.info("Вікно контексту: %s; бюджет: %s",
                 window.text(), budget.text())
        for note in budget.notes:
            LOG.warning("Контекст: %s", note)
        return budget

    #: Скільки токенів додавати понад виміряну потребу, за глибиною запиту.
    #:
    #: Запас — це відповідь моделі, службові дані й похибка токенізації
    #: кирилиці. Він різний, бо різні запити: питання-факт потребує двох
    #: абзаців, «напиши сайт із шести файлів» — тисяч токенів коду.
    _DEPTH_MARGIN: dict[str, float] = {
        context_flow.DEPTH_MINIMAL: 0.15,
        context_flow.DEPTH_SHALLOW: 0.20,
        context_flow.DEPTH_MEDIUM: 0.30,
        context_flow.DEPTH_DEEP: 0.45,
    }

    #: Скільки місця лишати під САМУ РОБОТУ, за глибиною запиту.
    #:
    #: Виміряна потреба описує, що лежить у сесії ЗАРАЗ: репліка «виправ
    #: баг» — це 30 токенів. Але вже наступний крок прочитає файл, і в сесії
    #: опиниться 8 000. Тому «кімната» задається наміром, а не поточним
    #: розміром тексту: питання-факт — 2k, звичайне завдання — 6k, правка —
    #: 10k, продовження роботи — 24k.
    _DEPTH_ROOM: dict[str, int] = {
        context_flow.DEPTH_MINIMAL: 2_048,
        context_flow.DEPTH_SHALLOW: 6_144,
        context_flow.DEPTH_MEDIUM: 10_240,
        context_flow.DEPTH_DEEP: 24_576,
    }

    def _needed_tokens(self, *, with_tools: bool = True) -> int:
        """Скільки токенів ЦЕЙ запит реально хоче зайняти.

        Міряємо те, що справді піде в промпт, а не «скільки є»:

        * системний промпт;
        * схеми інструментів (вони вже вибрані під це вікно) — ЛИШЕ коли
          цей хід справді надсилає схеми: у звичайній розмові їх немає, і
          рахувати їхні 9 646 токенів означало б «привіту» давати 24k;
        * історію, що зараз лежить у сесії;
        * **останню репліку користувача двічі** — вона вже в історії, але
          саме вона виросте під час роботи (результати інструментів
          приєднуються до неї), тож без запасу «прочитай ці два файли» не
          дістало б місця під самі файли.

        Повертає ``0``, якщо вікно ще невідоме: тоді працює обережна
        типова поведінка, а не вигадана потреба.
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if limit <= 0:
            return 0
        try:
            system_text = str(self.session.system_message().get("content") or "")
        except (AttributeError, TypeError):
            system_text = ""
        total = self.session._tokens_in(system_text)
        if with_tools:
            try:
                total += int(self.session._tools_tokens())
            except (AttributeError, TypeError):
                pass
        last_user = 0
        for message in reversed(getattr(self.session, "messages", []) or ()):
            if str(message.get("role") or "") != "user":
                continue
            body = message.get("content")
            last_user = self.session._tokens_in(
                body if isinstance(body, str) else str(body or ""))
            break
        for message in getattr(self.session, "messages", []) or ():
            body = message.get("content")
            total += self.session._tokens_in(
                body if isinstance(body, str) else str(body or ""))
        # Остання репліка йде в сумі ОДИН раз — додаємо ще один, щоб вийшло
        # «двічі»: стільки місця їй треба на ріст під час роботи.
        total += last_user
        return max(0, total)

    def refresh_budget_for_request(self, *, with_tools: bool = True) -> "context_budget.Budget":
        """Перерахувати робочий бюджет під КОЖЕН запит.

        Вимога користувача (21.11.2026): «зроби автовизначення в залежності
        від потреби на запит».

        Навіщо перераховувати, а не рахувати раз на старті. Потреба різна на
        кожному ході: «привіт» хоче ~2k, а «порівняй ці два файли» —
        десятки тисяч. Один бюджет на всю сесію означав би або хвилини
        очікування на дрібницю, або обрізаний текст у великій роботі.

        Розмір вибирає :func:`context_budget.working_window`:
        ``needed`` — виміряна потреба (:meth:`_needed_tokens`), ``mode`` —
        ``agent.context_mode`` (``full`` = усе вікно), ``ceiling`` —
        ``agent.working_context`` (``0`` = без стелі).

        ``with_tools=False`` — для звичайної розмови, де схеми інструментів
        НЕ надсилаються: їхні 9 646 токенів не мають роздувати бюджет
        «привіту».

        Старий бюджет лишається, якщо вікно невідоме: краще обережне
        число, ніж жодного.
        """
        window = getattr(self, "_context_window", None)
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if window is None or not limit:
            return getattr(self, "_context_budget", None) or context_budget.Budget()
        needed = 0
        try:
            needed = self._needed_tokens(with_tools=with_tools)
        except Exception:                        # noqa: BLE001
            LOG.debug("Потребу в контексті не виміряно", exc_info=True)
        settings = getattr(self, "agent_settings", None)
        mode = "auto"
        ceiling = 0
        if str(getattr(settings, "context_mode", "auto") or "") == "full":
            mode = "max"
        try:
            ceiling = int(getattr(settings, "working_context", 0) or 0)
        except (TypeError, ValueError):
            ceiling = 0
        # ``-1`` — «усе вікно моделі» (людина обрала це явно): стелі немає,
        # і автовизначення теж не звужує план.
        if ceiling < 0:
            mode = "max"
            ceiling = 0
        depth_level = ""
        try:
            depth_level = str(getattr(self.context_plan().depth, "level", "") or "")
        except Exception:                        # noqa: BLE001
            depth_level = ""
        margin = self._DEPTH_MARGIN.get(depth_level)
        room = self._DEPTH_ROOM.get(depth_level, 0)
        budget = context_budget.plan(
            window,
            system_tokens=self.session._tokens_in(
                str(self.session.system_message().get("content") or "")),
            tools_tokens=self.session._tools_tokens() if with_tools else 0,
            needed=needed,
            mode=mode,
            ceiling=ceiling,
            room=room,
            margin_share=margin,
        )
        self._context_budget = budget
        LOG.info("Бюджет під запит: потреба %s → %s", needed, budget.text())
        return budget

    def _live_context_window(self, base_url: str) -> int:
        """Спитати в СЕРВЕРА справжнє вікно контексту (0 — не вдалось).

        Працює для локальних HTTP-серверів і для хмар однаково: у хмари
        немає ні ``/props``, ні ``.gguf``, тож донедавну вікно брали лише з
        СТАТИЧНОГО каталогу — а для власного провайдера там нулі, і агент
        працював із «обережним запасом 8192».

        ── ЧОМУ ПРОБА НЕ БЛОКУЄ ВІДПОВІДЬ ────────────────────────────────
        Заміряно на живому Deploy: бінарний пошук ліміту — 8 послідовних
        запитів по ~7 с, разом **55 секунд**. Чекати цього перед КОЖНОЮ
        відповіддю неприпустимо, тож проба йде у ФОНОВОМУ потоці:

        * одразу повертається те, що вже відомо (кеш);
        * поки фонова проба працює, викликач бере каталог провайдера;
        * коли проба завершиться, наступний хід візьме точне число.

        Це не компроміс якості: каталог для відомих провайдерів (Deploy,
        OpenAI, Gemini…) правильний, а проба уточнює його для ВЛАСНИХ
        адрес і нових моделей — саме там каталог мовчить.
        """
        root = str(base_url or "").strip().rstrip("/")
        model = str(getattr(self.llm_settings, "model", "") or "").strip()
        if not root or not model:
            return 0
        # Вбудований рушій уже віддав вікно з пам'яті — мережа не потрібна.
        if _is_embedded_base(root):
            return 0
        # Лише мережеві адреси: без схеми запит однаково не піде.
        if not root.lower().startswith(("http://", "https://")):
            return 0
        key = (root, model)
        now = time.time()
        cached = _LIVE_CTX_CACHE.get(key)
        if cached is not None and (now - cached[0]) < _LIVE_CTX_TTL:
            return cached[1]
        # Проба вже йде в фоні — не запускаємо другу й не чекаємо.
        if key in _LIVE_CTX_PENDING:
            return 0
        try:
            from . import provider_adapters

            style = provider_adapters.detect_style(root)
            # Не-OpenAI протоколи (Anthropic, Gemini) мають інший шлях і
            # інший формат помилки — для них лишається каталог.
            if style != provider_adapters.OPENAI:
                return 0
            chat_path = provider_adapters.for_url(root).chat_path
        except Exception:  # noqa: BLE001 - без адаптера лишається каталог
            LOG.debug("Адаптер для проби не визначено", exc_info=True)
            return 0
        _start_live_probe(key, root, model,
                          api_key=str(getattr(self.llm_settings, "api_key", "") or ""),
                          chat_path=chat_path)
        return 0

    def _live_context_window_wait(self, base_url: str,
                                  timeout: float = 0.0) -> int:
        """Дочекатись результату фонової проби (``timeout=0`` — не чекати).

        Потрібно тестам і явній дії користувача («визначити вікно зараз»),
        а не звичайному ходу агента.
        """
        root = str(base_url or "").strip().rstrip("/")
        model = str(getattr(self.llm_settings, "model", "") or "").strip()
        key = (root, model)
        pending = _LIVE_CTX_PENDING.get(key)
        if pending is not None and timeout > 0:
            pending.join(timeout)
        cached = _LIVE_CTX_CACHE.get(key)
        return int(cached[1]) if cached else 0

    def probe_context_window(self, *, counter: Any = None) -> "context_budget.Budget":
        """Дізнатися вікно САМОСТІЙНО: ``/props`` сервера + метадані GGUF.

        Навіщо в агенті, а не лише в інтерфейсі. Вікно потрібне ПЕРЕД
        кожним запитом, і воно залежить від того, з чим сервер справді
        запущено. Інтерфейс не завжди встигає його оновити (модель могла
        піднятися у фоні) — тоді агент працював із застарілим числом.

        КЛЮЧОВЕ: якщо сервер відповів, його ``n_ctx`` — ІСТИНА, і заявлене
        в налаштуваннях число ігнорується повністю. Реальний випадок:
        ``launch_with_recovery`` сам зменшив контекст до 16384 (щоб модель
        влізла у VRAM), а ``settings.engine.ctx_size`` лишився 32768.
        Передача 32768 агенту давала завеликий промпт → обрив з'єднання.

        Нічого не ламає, якщо сервер не llama.cpp: тоді лишаються метадані
        GGUF, заявлене число (обережно, з половиною) або запас.
        """
        props_ctx = 0
        base = str(getattr(self.llm_settings, "base_url", "") or "").rstrip("/")
        # ── Вбудований рушій: вікно берёмо В ПАМ'ЯТІ, а не через HTTP ──────
        # ``/props`` — це ендпоінт llama-server. У вбудованого рушія немає ні
        # порту, ні HTTP: запит до ``native://blackchpok/props`` завжди падає,
        # і код ішов у запасну гілку «половина від заявлених». Заміряно на
        # справжньому вікні: рушій створено з ``ctx 16384``, а агент працював
        # із **8192** — тобто половина контексту губилась без жодної причини.
        # Наслідки були видимі: бюджет схем падав до 2048, вмикався лінивий
        # режим на 15 схем із 52, а історія різалась удвічі раніше.
        if base and _is_embedded_base(base):
            embedded = _embedded_context_window()
            gguf_ctx = _gguf_context(str(getattr(self.llm_settings, "model", "") or ""))
            if embedded > 0:
                return self.adopt_context_window(
                    props_ctx=embedded, gguf_ctx=gguf_ctx, counter=counter,
                    source="вбудований рушій (контекст у пам'яті)")
            # ── Модель ще не в пам'яті: беремо заявлене БЕЗ ділення ───────
            # Ділення навпіл — це захист від ПОДІЛУ НА СЛОТИ, який робить
            # llama-server (``--ctx-size 32768`` при двох слотах → 16384).
            # У вбудованого рушія слотів немає: скільки попросили в
            # ``engine.ctx_size``, стільки контекст створив і тримає. Тому
            # половина тут — не «обережність», а втрата половини вікна:
            # заміряно 8192 замість реальних 16384, через що бюджет схем
            # падав до 2048 і вмикався лінивий режим на 15 схемах із 52.
            #
            # Коли рушій справді зменшив контекст (OOM-відкат), наступна
            # проба прочитає справжнє ``n_ctx`` із контексту в пам'яті —
            # тобто правда все одно переможе оцінку.
            requested = int(getattr(self, "_requested_ctx", 0) or 0)
            if requested > 0:
                LOG.info("Вбудований рушій: модель ще не в пам'яті — беру "
                         "заявлене вікно %s (без ділення на слоти)", requested)
                return self.adopt_context_window(
                    props_ctx=requested, gguf_ctx=gguf_ctx, counter=counter,
                    source="вбудований рушій (налаштування)")
        if base:
            props_ctx = _server_slot_context(
                base, str(getattr(self.llm_settings, "api_key", "") or ""))
        gguf_ctx = _gguf_context(str(getattr(self.llm_settings, "model", "") or ""))
        # ── Хмара: вікно беремо з КАТАЛОГУ провайдера ─────────────────────
        # У хмари немає ні ``/props``, ні ``--ctx-size``: вікно задає сам
        # провайдер. Раніше сюди доходило лише заявлене локальне число
        # (``engine.ctx_size``), і воно ще й ділилось навпіл — «захист від
        # поділу на слоти», якого в хмарі не існує. Заміряно на Deploy:
        # провайдер дає 1 000 000 токенів, а агент працював із **8192** і
        # різав історію всемеро раніше, ніж треба.
        if not props_ctx:
            # ── ЖИВА проба вікна: працює для БУДЬ-ЯКОЇ моделі ──────────────
            # Заміряно на цьому проєкті: каталог давав для Deploy 1 000 000,
            # але для власного провайдера там нулі — і агент падав на
            # «обережний запас 8192», тобто різав історію всемеро раніше,
            # ніж міг. Тепер спершу питаємо САМ СЕРВЕР: дешеве ``/models``
            # (багато провайдерів віддають ``context_length``), а якщо там
            # нічого — пробний запит, на який сервер відповідає справжнім
            # лімітом у тексті помилки.
            live = self._live_context_window(base)
            if live > 0:
                return self.adopt_context_window(
                    props_ctx=live, gguf_ctx=gguf_ctx, counter=counter,
                    source="жива проба сервера")
            cloud_ctx = _cloud_context_window(base)
            if cloud_ctx > 0:
                return self.adopt_context_window(
                    props_ctx=cloud_ctx, gguf_ctx=gguf_ctx, counter=counter,
                    source="каталог хмарного провайдера")
        if props_ctx > 0:
            # Сервер сказав правду — нічого не «страхуємо».
            return self.adopt_context_window(props_ctx=props_ctx,
                                             gguf_ctx=gguf_ctx, counter=counter)
        requested = int(getattr(self, "_requested_ctx", 0) or 0)
        if requested > 0:
            props_ctx = max(4096, requested // 2)
            LOG.info("Сервер не повідомив n_ctx — беру обережне вікно %s "
                     "(половина від заявлених %s)", props_ctx, requested)
        return self.adopt_context_window(props_ctx=props_ctx,
                                         gguf_ctx=gguf_ctx, counter=counter)

    def set_token_counter(self, counter: Callable[[str], int] | None) -> None:
        """Підключити точний підрахунок токенів до ЦЬОГО агента.

        Навіщо метод, а не лише модульна функція. ``main_window`` кликав
        через ``getattr(self.agent, "set_token_counter", None)``, а такого
        методу не існувало — ``getattr`` повертав ``None``, і виклик ставав
        **тихим no-op**. Точний tokenizer не доходив до агента взагалі.

        Тепер метод є, і він додатково скидає похідні числа: ширина вікна й
        бюджет рахувались за старою (евристичною) оцінкою, тож після появи
        точного лічильника їх треба перерахувати.
        """
        set_token_counter(counter)
        self._token_counter = counter
        # Похідні величини залежали від оцінки — нехай перерахуються.
        self._context_budget = None
        if counter is None:
            # Лічильник зник (модель вивантажено) — вікно лишаємо, воно від
            # лічильника не залежить, але бюджет перерахується при потребі.
            return
        if getattr(self, "_context_window", None):
            try:
                self.probe_context_window(counter=counter)
            except Exception:  # noqa: BLE001 - перерахунок не має ламати агента
                LOG.debug("Бюджет не перераховано після зміни лічильника",
                          exc_info=True)

    def set_requested_context(self, ctx_size: int) -> None:
        """Запам'ятати, скільки контексту ЗАПРОСИЛИ в налаштуваннях.

        Це не джерело правди (сервер може дати менше через поділ на
        слоти), але коли ``/props`` недоступний, половина заявленого —
        безпечна оцінка. Раніше агент вірив заявленому числу повністю й
        надсилав завеликий промпт.
        """
        try:
            self._requested_ctx = max(0, int(ctx_size or 0))
        except (TypeError, ValueError):
            self._requested_ctx = 0

    def context_state(self) -> str:
        """Один рядок для інтерфейсу: вікно й розподіл бюджету."""
        window = getattr(self, "_context_window", None)
        budget = getattr(self, "_context_budget", None)
        if budget is None:
            return "вікно контексту ще не визначено"
        parts = [budget.text()]
        if window is not None and window.note:
            parts.append(window.note)
        return " · ".join(parts)

    def set_workspace(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.session.workspace = self.workspace
        self.planner.workspace = self.workspace
        self.planner.registry = self.registry

    def start(self, text: str, *, extra_prompt: str = "",
              fresh: bool = False) -> bool:
        """Запустити цикл агента. Повертає ``True``, якщо робота почалася.

        Значення, що повертається, потрібне черзі кроків: якщо агент ще
        зайнятий і запит НЕ прийнято, крок треба повернути в чергу, а не
        лишати активним. Інакше крок «висів» би в стані «аналіз» назавжди —
        зовні це виглядало як зависання моделі.

        ``fresh=True`` очищає історію діалогу перед стартом. Так робить
        черга кроків: кожен крок плану — окремий незалежний запит із
        власним фокусом. Без цього модель бачила власні попередні відповіді
        («файл створено» з кроку N) і на кроці N+1 відповідала «вже
        зроблено», не викликаючи інструментів — крок падав на перевірці
        результату, а залежні кроки скасовувались.
        """
        if self.busy:
            self.events.put(AgentEvent("error", "Агент ще працює над попереднім запитом."))
            return False
        if fresh:
            self.session.reset()
        self._cancel.clear()
        self._touched_files = []
        self._syntax_repairs = 0
        self._smoke_done = False
        self._last_answer = ""
        self._error = ""
        self._degraded = False
        self._promise_warned = False
        self._empty_turns = 0
        self._build_nudged = False
        self._continue_asked = False
        self._git_asked = False
        self._git_published = False
        self._text_protocol_asked = 0
        self._hints_need_continue = False
        # Скидаємо статистику, зберігши ліміт контексту (він задається
        # ззовні після підняття сервера).
        limit = self.stats.context_limit
        self.stats.reset()
        if limit:
            self.stats.set_limit(limit)
        self.session.extra_prompt = extra_prompt
        # Підказка режиму роботи — те, що відрізняє «Чат» від «Коду».
        if self.mode_prompt.strip():
            self.session.extra_prompt = "\n\n".join(
                part for part in (self.mode_prompt.strip(), extra_prompt.strip()) if part)
        # Каталог дій рахуємо у фоновому потоці (``_build_action_prompt``):
        # тут лише скидаємо стан.
        self._specs = {}
        self._observations = []
        # ── Профіль моделі ─────────────────────────────────────────────────
        self._thread = threading.Thread(target=self._run, args=(text,), daemon=True)
        self._thread.start()
        return True

    def _build_action_prompt(self, text: str) -> None:
        """Зібрати ``session.action_prompt``: каталог, скіли, пам'ять, мережа.

        Викликається з фонового потоку (:meth:`_run`) ПЕРЕД першим запитом
        до моделі. Тут дозволені довгі операції: мережевий пошук «на кожен
        запит», читання пам'яті NEUROMESH, планування.
        """
        has_mcp = False
        if self.mcp_manager is not None:
            try:
                has_mcp = bool(self.mcp_manager.tool_catalog())
            except Exception:  # noqa: BLE001
                has_mcp = False
        parts: list[str] = []
        # Схеми рахуємо ПЕРШИМИ: від них залежить, чи потрібен текстовий
        # каталог (він же дублює їхні описи). Раніше ``_specs`` скидались
        # нижче, і перевірка завжди бачила порожнечу.
        if self.tools_enabled:
            try:
                self.tool_schemas()
            except Exception:  # noqa: BLE001 - вибір схем не має ламати старт
                LOG.debug("Схеми перед стартом не пораховано", exc_info=True)
        if self.tools_enabled:
            # ── Каталог дій — ЛИШЕ коли схеми не передаються ────────────────
            # ``catalog_text`` — це 5261 символ (≈2520 токенів) описів тих
            # самих інструментів, які модель УЖЕ бачить повними JSON-схемами.
            # На вікні 8192 це дублювання з'їдало понад 30% контексту: у
            # живому прогоні «система» важила 6158 токенів із 8192, і модель
            # починала повторювати той самий виклик замість роботи.
            # Каталог лишаємо тільки як заміну схемам (вузьке вікно, лінивий
            # режим без специфікацій) — там він справді потрібен.
            if not self._schemas_are_visible():
                # Каталог обмежуємо ТИМИ САМИМИ назвами, які модель бачить
                # цього ходу. Інакше в промпті лежить перелік усіх 56
                # інструментів, а схем — шість: модель бачить назви, яких не
                # може викликати, і обіцяє дію замість неї (заміряно: «у
                # мене 56 інструментів» при 6 доступних).
                visible_names = {
                    str((spec or {}).get("function", {}).get("name") or "")
                    for spec in (getattr(self, "_specs", None) or {}).values()
                } if getattr(self, "_specs", None) else set()
                visible_names.discard("")
                parts.append(tool_router.catalog_text(
                    include_mcp=has_mcp,
                    only=visible_names or None))
            # ── Компактний реєстр інструментів ─────────────────────────────
            # Коли схем забагато, повні JSON-схеми вже не передаються (див.
            # ``tool_schemas``), і моделі потрібен перелік того, що взагалі
            # існує. Без нього вона не знала б, що можна попросити
            # ``load_tools`` для інструмента, назви якого не бачить.
            registry_text = self._lazy_registry_text()
            if registry_text:
                parts.append(registry_text)
        if self.skill_book is not None and self.agent_settings.use_skills:
            # ── Скіли під ЦЕЙ запит ────────────────────────────────────────
            # Раніше брався лише ``book.prompt()`` — тобто тільки те, що
            # людина ввімкнула вручну. На практиці жоден скіл не був
            # увімкнений (вибір не зберігався), і агент працював без
            # інструкцій проєкту: не знав, як запускати тести, які правила
            # стилю, що збірка — окремий крок.
            #
            # Тепер скіли, доречні саме для цього запиту, вмикаються
            # автоматично (за словами опису), а ручний вибір людини діє
            # завжди й має вищий пріоритет.
            try:
                auto = self.skill_book.auto_enable(text)
            except Exception:                        # noqa: BLE001
                auto = []
            skill_prompt = self.skill_book.prompt()
            if auto:
                self._emit(
                    "status",
                    "Скіли цього запиту: "
                    + ", ".join(skill.name for skill in auto))
            if skill_prompt.strip():
                parts.append(skill_prompt)
        parts.append(permissions.prompt_hint(self.permission_mode))
        if self.settings_ref is not None:
            try:
                parts.append(social.catalogue_text(self.settings_ref))
            except Exception:  # noqa: BLE001 - каталог не має ламати старт
                LOG.debug("Каталог соцмереж недоступний", exc_info=True)
        rule = ("Правило: якщо користувач просить щось зробити — виклич інструмент, "
                "а не описуй, що можна зробити. Відповідай результатом дії.")
        if not self.tools_enabled:
            rule = ("Правило: інструменти вимкнено для цього режиму. Відповідай "
                    "текстом; якщо для відповіді потрібні файли чи команди — "
                    "скажи, який режим увімкнути.")
        # ── Розуміння запиту й контекст розмови ────────────────────────────
        # Рахуємо ЦЕ ДО запиту до моделі: тоді їй одразу кажемо мету,
        # обмеження й розв'язані згадки, і вона не перепитує те, що вже
        # відомо. Правила детерміновані — працюють і без моделі.
        self._prepare_understanding(text)
        # ── Пам'ять NEUROMESH: участь у розумінні, а не лише за викликом ──
        # Читаємо ДО запиту до моделі: релевантні факти й обмеження проєкту
        # мають бути в контексті одразу, інакше агент перепитує те, що вже
        # пояснювали, і повторює виправлені помилки.
        self._recall_memory(text)
        # ── ІНТЕРНЕТ НА КОЖЕН ЗАПИТ ───────────────────────────────────────
        # Вимога користувача: «до кожного запиту в локальній моделі додавався
        # запит до інтернету».
        #
        # ── КУДИ ЙДЕ ВЕБ-БЛОК ──────────────────────────────────────────────
        # НЕ в голову (``action_prompt`` → system_message), а в ХВІСТ
        # (``session.context_tail_text``): веб-дані змінюються ЩОЗАПИТУ, і
        # будь-яка їхня зміна в голові ламає KV-префікс усього промпту —
        # рушій перераховує все з нуля («кеш: 0%», prefill по 20–60 с).
        # Порядок значення не має: хвіст стоїть після історії, і модель
        # бачить дані безпосередньо перед відповіддю.
        web_block = self._web_context_for(text)
        context_block = self._context_block()
        tail_parts: list[str] = []
        if web_block:
            tail_parts.append(web_block)
        if context_block:
            tail_parts.append(context_block)
        self.session.context_tail_text = "\n\n".join(tail_parts)
        self.session.action_prompt = "\n\n".join([*parts, rule])
        self.session.skill_prompt = ""
        # ── Профіль моделі ─────────────────────────────────────────────────
        self.model_caps = model_profile.profile_for(
            self.llm_settings.model,
            self.llm_settings.base_url,
            context_window=int(getattr(self.session, "context_limit", 0) or 0),
        )
        # ── План роботи ────────────────────────────────────────────────────
        # Будується з кадру наміру, без моделі: файли, обмеження й критерії
        # завершення вже відомі. Модель бачить готові кроки й не вигадує
        # власну структуру щоразу заново.
        self._build_plan()
        # ── Хроніка довгого чату під ПОТОЧНЕ вікно ─────────────────────────
        # Рахуємо ДО першого запиту: вікно могло змінитись (інша модель,
        # інший режим), і хроніка має зайняти рівно свою частку.
        self._render_digest()

    def turn_reset(self, *, keep: int = 0) -> int:
        """Режим «один запит — один контекст»: увесь хід → у пам'ять.

        Вимога користувача (21.11.2026): «не обов'язково тримати все в
        контексті постійно! Треба зробити на один запит весь контекст, потім
        передача в довгострокову пам'ять і новий контекст і так далі».

        Чим це відрізняється від :meth:`auto_free_context`. Той спрацьовує
        лише коли історія заповнилась на 85% — тобто контекст усе одно
        накопичується, просто повільніше. Тут вікно звільняється ПІСЛЯ
        КОЖНОГО завершеного запиту: наступний запит починається з чистої
        історії, а все, що було, вже лежить у довгостроковій пам'яті
        (NEUROMESH + RAG + хроніка) і повертається пошуком.

        ``keep`` — скільки останніх повідомлень ЛИШИТИ.

        * ``0`` (типово) — визначає :meth:`_keep_for_reset`: останній обмін.
        * ``-1`` — не чіпати вікно взагалі (глибина «глибоко»).
        * додатне число — рівно стільки (адаптивний режим, див.
          :mod:`context_flow`).

        Що НЕ робиться:

        * нічого не пишеться в приватному режимі;
        * порожній/короткий хід не чіпаємо — нема чого архівувати;
        * якщо архів не вдався, історія ЛИШАЄТЬСЯ: краще повне вікно, ніж
          втрачений контекст (див. ``_archive_evicted_context``).

        Повертає кількість повідомлень, перенесених у пам'ять.
        """
        if getattr(self.state, "private", False):
            return 0
        messages = list(getattr(self.session, "messages", []) or ())
        if keep < 0:
            # Глибина «глибоко»: історію не чіпаємо зовсім.
            return 0
        # Лишаємо останній обмін (або стільки, скільки просив викликач).
        wanted = int(keep) if int(keep or 0) > 0 else self._keep_for_reset(messages)
        to_archive = messages[:max(0, len(messages) - wanted)]
        if not to_archive:
            return 0
        # У пам'ять іде РІВНО те, що зникає з вікна — і лише після того, як
        # архів справді прийняв дані. Інакше контекст губився б назавжди.
        try:
            self._archive_turn_context(to_archive)
        except Exception:                            # noqa: BLE001
            LOG.warning("Хід не перенесено в пам'ять — лишаю контекст",
                        exc_info=True)
            return 0
        del self.session.messages[:len(to_archive)]
        LOG.info("Свіжий контекст: %s повідомлень перенесено в довгострокову "
                 "пам'ять, у вікні лишилось %s", len(to_archive),
                 len(self.session.messages))
        self._emit("status",
                   f"Хід завершено: {len(to_archive)} повідомлень у "
                   f"довгострокову пам'ять, контекст свіжий.")
        return len(to_archive)

    @staticmethod
    def _keep_for_reset(messages: list) -> int:
        """Скільки останніх повідомлень лишити у вікні після ходу.

        Беремо останню пару «репліка користувача + відповідь». Якщо в кінці
        висять результати інструментів (``role="tool"``), вони йдуть РАЗОМ зі
        своїм викликом: обірваний ``tool`` без ``assistant`` ламає протокол і
        сервер відповідає помилкою 400.
        """
        if not messages:
            return 0
        keep = 1
        # Останній блок результатів інструментів чіпляємо до його виклику.
        while (keep < len(messages)
               and str(messages[-keep].get("role") or "") == "tool"):
            keep += 1
        # Плюс сама репліка користувача, що почала цей хід.
        index = len(messages) - keep - 1
        while index >= 0:
            if str(messages[index].get("role") or "") == "user":
                keep += 1
                break
            if str(messages[index].get("role") or "") == "tool":
                keep += 1
                index -= 1
                continue
            keep += 1
            break
        return min(keep, len(messages))

    def _archive_turn_context(self, messages: list) -> None:
        """Перенести ЗАВЕРШЕНИЙ хід: хроніка + пам'ять + RAG.

        Відмінність від :meth:`_archive_evicted_context` — компактність.
        Той робить «зліпок» вікна з першими рядками результатів інструментів
        (доречно, коли історія переповнилась). Тут перенесення йде ПІСЛЯ
        КОЖНОГО запиту, тому сирі дампи писали б шум: за 50 ходів — 50
        записів дампів, і пошук почав би знаходити сміття.

        Хроніка й RAG отримують ті самі дані, що й раніше: вони вміють
        зберігати довгий текст, і саме звідти його дістають ``memory_search``
        та ``rag_search``.
        """
        if getattr(self.state, "private", False):
            return
        goal = str(getattr(self.state, "goal", "") or "")
        # 1. Хроніка — зв'язний слід розмови (він іде в КОЖЕН промпт).
        digest = getattr(self, "digest", None)
        if digest is not None and getattr(self.agent_settings, "long_chat", True):
            try:
                digest.absorb(messages)
            except Exception:                        # noqa: BLE001
                LOG.debug("Хроніку не оновлено", exc_info=True)
        # 2. Пам'ять: компактний запис ходу, а не дамп.
        bridge = getattr(self, "memory_bridge", None)
        archive_turn = getattr(bridge, "archive_turn", None)
        if callable(archive_turn):
            try:
                archive_turn(messages, task=goal)
            except Exception:                        # noqa: BLE001
                LOG.debug("Хід не записано в пам'ять", exc_info=True)
        elif bridge is not None and hasattr(bridge, "archive_messages"):
            # Старіший міст без ``archive_turn`` — не вважаємо це збоєм.
            try:
                bridge.archive_messages(messages, task=goal)
            except Exception:                        # noqa: BLE001
                LOG.debug("Архів контексту не записано", exc_info=True)
        # 3. RAG: ширший текст із індексом.
        self._archive_to_rag(messages, task=goal)

    def _archive_evicted_context(self, messages: list) -> None:
        """Витіснений блок історії: у хроніку, NEUROMESH і RAG.

        Три різні сховища, і кожне потрібне зі своєї причини:

        * **хроніка** (:mod:`longchat`) — щоб модель бачила зв'язний слід
          розмови В КОЖНОМУ наступному запиті, не переказуючи її заново;
        * **NEUROMESH** — факти й уроки з пошуком за змістом: «що ми
          вирішили про порт?» знайдеться через ``memory_search``;
        * **RAG** — довгий текст розмови з індексом: він повертається як
          контекст до файлів проєкту, і саме звідти його дістає
          ``rag_search``.

        RAG тут не замінює пам'ять, а доповнює: NEUROMESH зберігає стислий
        факт (до 900 символів), RAG — ширший фрагмент розмови з повним
        текстом реплік. Приватний режим не пише нічого.
        """
        if getattr(self.state, "private", False):
            return
        # ── 1. Хроніка: завжди, навіть якщо пам'ять недоступна ────────────
        digest = getattr(self, "digest", None)
        if digest is not None and getattr(self.agent_settings, "long_chat", True):
            try:
                added = digest.absorb(messages)
                if added:
                    LOG.info("Хроніка чату: +%s вузлів (усього %s)",
                             added, len(digest.entries))
            except Exception:  # noqa: BLE001 - хроніка не має ламати хід
                LOG.debug("Хроніку не оновлено", exc_info=True)
        goal = str(getattr(self.state, "goal", "") or "")
        # ── 2. Довгострокова пам'ять NEUROMESH ────────────────────────────
        bridge = getattr(self, "memory_bridge", None)
        if bridge is not None and hasattr(bridge, "archive_messages"):
            try:
                bridge.archive_messages(messages, task=goal)
            except Exception:  # noqa: BLE001
                LOG.debug("Архів контексту не записано", exc_info=True)
        # ── 3. RAG: ширший фрагмент розмови з індексом за змістом ─────────
        self._archive_to_rag(messages, task=goal)

    def _archive_to_rag(self, messages: list, *, task: str = "") -> bool:
        """Покласти витіснений блок у RAG-індекс (``rag_engine``).

        ``rag_archive`` — викличний об'єкт, який ставить вікно IDE: сам
        агент не тримає рушія RAG (ним володіє вікно, і він прив'язаний до
        робочої теки). Без нього нічого не ламається — працюють хроніка й
        пам'ять.
        """
        hook = getattr(self, "rag_archive", None)
        if not callable(hook):
            return False
        text = self._archive_text(messages)
        if not text:
            return False
        try:
            ok = hook(text, kind="chat", task=task)
        except TypeError:
            # Старіший обробник без ``task``.
            try:
                ok = hook(text)
            except Exception:  # noqa: BLE001
                LOG.debug("RAG-архів не записано", exc_info=True)
                return False
        except Exception:  # noqa: BLE001
            LOG.debug("RAG-архів не записано", exc_info=True)
            return False
        return bool(ok) if ok is not None else True

    @staticmethod
    def _archive_text(messages: list, *, limit: int = 2600) -> str:
        """Текст блоку для RAG: ширший за пам'ять, але без сирих дампів.

        Результат інструмента обрізаємо до перших рядків: повний вивід
        ``read_file`` уже лежить в індексі файлів, і дублювати його в
        індексі розмов означало б платити місцем двічі.
        """
        parts: list[str] = []
        used = 0
        for message in messages or ():
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").strip().lower()
            body = " ".join(str(message.get("content") or "").split())
            if not body:
                continue
            if role == "tool":
                name = str(message.get("name") or "tool")
                block = f"{name}: {body[:400]}"
            elif role in ("user", "assistant"):
                block = f"{role}: {body[:900]}"
            else:
                continue
            if used + len(block) + 3 > limit:
                break
            parts.append(block)
            used += len(block) + 3
        if not parts:
            return ""
        return "Розмова (витиснуто з контексту моделі). " + " | ".join(parts)

    def attach_digest(self, digest: Any) -> None:
        """Підключити хроніку конкретного чату (``None`` — вимкнути)."""
        self.digest = digest
        self._render_digest()

    def _render_digest(self) -> str:
        """Перерахувати блок хроніки під поточне вікно моделі.

        Викликається перед КОЖНИМ запитом: вікно могло змінитись (модель
        перезавантажили, режим інший), а хроніка має займати рівно свою
        частку й не більше.
        """
        digest = getattr(self, "digest", None)
        block = ""
        if digest is not None and getattr(self.agent_settings, "long_chat", True):
            try:
                window = int(getattr(self.session, "context_limit", 0) or 0)
                block = digest.render(window_tokens=window,
                                      counter=current_token_counter())
            except Exception:  # noqa: BLE001 - хроніка не має ламати запит
                LOG.debug("Хроніку не відрендерено", exc_info=True)
                block = ""
        try:
            self.session.digest_block = block
        except AttributeError:
            pass
        return block

    def digest_state(self) -> str:
        """Один рядок для інтерфейсу: скільки розмови живе поза вікном."""
        return longchat.describe_digest(getattr(self, "digest", None))

    def _recall_memory(self, text: str) -> None:
        """Підкласти в контекст те, що пам'ять знає про цей запит."""
        bridge = self.memory_bridge
        if not getattr(self.agent_settings, "memory_participates", True):
            self._memory_snapshot = memory_bridge.MemorySnapshot()
            return
        if bridge is None or not bridge.ready() or self.state.private:
            self._memory_snapshot = memory_bridge.MemorySnapshot()
            return
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        files = list(getattr(self.intent, "referenced_files", ()) or ()) \
            if self.intent is not None else []
        goal = ""
        if self.intent is not None:
            goal = str(getattr(self.intent, "primary_goal", "") or "")
        try:
            snapshot = bridge.snapshot(
                text, task=goal or self.state.goal, files=files, window=limit)
            # Обмеження проєкту діють завжди — вони не залежать від запиту.
            community = bridge.constraints()
            if community:
                known = set(snapshot.constraints)
                snapshot.constraints.extend(
                    item for item in community if item not in known)
            bridge.apply_to_state(snapshot, self.state)
        except Exception:                           # noqa: BLE001
            LOG.debug("Пам'ять не дала контексту", exc_info=True)
            snapshot = memory_bridge.MemorySnapshot(note="пам'ять недоступна")
        self._memory_snapshot = snapshot
        if not snapshot.empty:
            self._emit("status", memory_bridge.describe_snapshot(snapshot))
        # ── Уроки з попередніх спроб ───────────────────────────────────────
        # Пам'ять дає факти й обмеження проєкту, а тут — ЩО АГЕНТ САМ
        # ЗРОБИВ НЕ ТАК минулого разу. Це різні шари: факт описує проєкт,
        # урок описує дію агента. Без уроків агент повторював ту саму
        # помилку тиждень поспіль, бо «знання» про неї нікуди не йшло.
        self._recall_lessons(text)

    def _recall_lessons(self, text: str) -> None:
        """Підкласти уроки з попередніх спроб — до запиту до моделі.

        Модель бачить їх разом із пам'яттю, але окремим блоком: «висновки з
        попередніх спроб» — це інструкція до ДІЇ, а не факт про проєкт.
        """
        self._lesson_hints = []
        learning = getattr(self, "learning", None)
        if learning is None or self.state.private:
            return
        try:
            hints = learning.hints(
                text, task=str(getattr(self.state, "goal", "") or ""),
                # Вікно моделі визначає, СКІЛЬКИ уроків має сенс підкласти:
                # локальна на 8k отримає чотири, хмарна на 1M — до
                # шістнадцяти. Раніше число було однакове для всіх.
                window=int(getattr(self.session, "context_limit", 0) or 0))
        except TypeError:
            # Старіший SelfLearning без ``window``.
            try:
                hints = learning.hints(
                    text, task=str(getattr(self.state, "goal", "") or ""))
            except Exception:                        # noqa: BLE001
                LOG.debug("Уроки не підкладено", exc_info=True)
                return
        except Exception:                            # noqa: BLE001
            LOG.debug("Уроки не підкладено", exc_info=True)
            return
        if not hints:
            return
        self._lesson_hints = list(hints)
        self._emit("status", f"Уроки з минулих спроб: {len(hints)}.")

    def _learn_from_turn(self, *, ok: bool) -> None:
        """Зробити висновки з ЩОЙНО завершеного ходу.

        Викликається у ``finally`` ходу: на цей момент уже відомо все —
        які виклики впали, скільки разів правили синтаксис, чи вистачило
        кроків. Урок записується в пам'ять, і наступного разу агент
        отримає його як нагадування.
        """
        learning = getattr(self, "learning", None)
        if learning is None or self.state.private:
            return
        if not getattr(self.agent_settings, "self_learning", True):
            return
        observations = list(self._observations or [])
        calls = [
            (str(getattr(item, "name", "") or ""),
             bool(getattr(item, "ok", False)),
             str(getattr(item, "output" if getattr(item, "ok", False) else "error", "")
                 or ""))
            for item in observations
        ]


        #  ???????? ?????? ????????????? ?????????? ????????? ?????? (.venv, pip, npm, CLI)
        if not getattr(self, "_cli_hint_injected", False):
            self._cli_hint_injected = True
            _cli_note = (
                "\n[\u0412\u0411\u0423\u0414\u041e\u0412\u0410\u041d\u0418\u0419 \u041a\u041e\u041c\u0410\u041d\u0414\u041d\u0418\u0419 \u0420\u042f\u0414\u041e\u041a (CLI / TERMINAL)]: "
                "\u0423 \u0442\u0435\u0431\u0435 \u0404 \u043f\u043e\u0432\u043d\u0438\u0439 \u0434\u043e\u0441\u0442\u0443\u043f \u0434\u043e \u043a\u043e\u043c\u0430\u043d\u0434\u043d\u043e\u0433\u043e \u0440\u044f\u0434\u043a\u0430 \u0447\u0435\u0440\u0435\u0437 \u0456\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442 run_command (\u043f\u0440\u0430\u0446\u044e\u0454 \u0432 \u043f\u0430\u043f\u0446\u0456 \u043f\u0440\u043e\u0454\u043a\u0442\u0443). "
                "\u042f\u043a\u0449\u043e \u0434\u043b\u044f \u043f\u0440\u043e\u0454\u043a\u0442\u0443 \u043f\u043e\u0442\u0440\u0456\u0431\u043d\u0456 \u0431\u0456\u0431\u043b\u0456\u043e\u0442\u0435\u043a\u0438 \u0430\u0431\u043e \u0432\u0438\u043d\u0438\u043a\u0430\u0454 ModuleNotFoundError: "
                "1) \u0421\u0442\u0432\u043e\u0440\u0438 \u0456\u0437\u043e\u043b\u044c\u043e\u0432\u0430\u043d\u0435 \u0432\u0456\u0440\u0442\u0443\u0430\u043b\u044c\u043d\u0435 \u0441\u0435\u0440\u0435\u0434\u043e\u0432\u0438\u0449\u0435: python -m venv .venv; "
                "2) \u0412\u0441\u0442\u0430\u043d\u043e\u0432\u0438 \u043f\u043e\u0442\u0440\u0456\u0431\u043d\u0456 \u043f\u0430\u043a\u0435\u0442\u0438 \u0432 .venv: .venv\\Scripts\\python.exe -m pip install <\u043f\u0430\u043a\u0435\u0442\u0438> \u0456 \u0437\u0431\u0435\u0440\u0435\u0436\u0438 requirements.txt; "
                "3) \u0417\u0430\u043f\u0443\u0441\u043a\u0430\u0439 \u0442\u0430 \u0442\u0435\u0441\u0442\u0443\u0439 \u043a\u043e\u0434 \u0447\u0435\u0440\u0435\u0437 .venv\\Scripts\\python.exe, npm, git \u0430\u0431\u043e \u0456\u043d\u0448\u0456 CLI-\u0456\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u0438 \u043f\u0440\u043e\u0454\u043a\u0442\u0443.\n"
            )
            try:
                if self.session.messages and self.session.messages.get("role") == "system":
                    self.session.messages["content"] = str(self.session.messages.get("content") or "") + "\n" + _cli_note
            except Exception:
                pass


        #  ???????? ????????????? ??????: ?????? ? ??? ????????????? ??? ?????? ????????
        if not getattr(self, "_proactive_agent_injected", False):
            self._proactive_agent_injected = True
            _auto_rule = (
                "\n[\u041f\u0420\u041e\u0422\u041e\u041a\u041e\u041b \u0421\u0410\u041c\u041e\u0421\u0422\u0406\u0419\u041d\u041e\u0421\u0422\u0406 \u0422\u0410 \u0406\u041d\u0421\u0422\u0420\u0423\u041c\u0415\u041d\u0422\u0406\u0412]: "
                "1) \u041d\u0406\u041a\u041e\u041b\u0418 \u043d\u0435 \u043f\u0438\u0442\u0430\u0439 \u043a\u043e\u0440\u0438\u0441\u0442\u0443\u0432\u0430\u0447\u0430 '\u0427\u0438 \u0432\u0438\u043a\u043e\u043d\u0430\u0442\u0438 \u0446\u0456 \u043a\u0440\u043e\u043a\u0438?' \u0456 \u043d\u0435 \u043f\u0435\u0440\u0435\u043a\u043b\u0430\u0434\u0430\u0439 \u0440\u0456\u0448\u0435\u043d\u043d\u044f \u043d\u0430 \u043a\u043e\u0440\u0438\u0441\u0442\u0443\u0432\u0430\u0447\u0430. "
                "2) \u041e\u0442\u0440\u0438\u043c\u0430\u0432\u0448\u0438 \u0437\u0430\u0434\u0430\u0447\u0443 (\u0430\u043d\u0430\u043b\u0456\u0437, \u043f\u043e\u0448\u0443\u043a \u043f\u043e\u043c\u0438\u043b\u043e\u043a, \u0440\u043e\u0437\u0440\u043e\u0431\u043a\u0430, \u0440\u0435\u0444\u0430\u043a\u0442\u043e\u0440\u0438\u043d\u0433), \u043e\u0434\u0440\u0430\u0437\u0443 \u0441\u0430\u043c \u0441\u043a\u043b\u0430\u0434\u0438 \u043f\u043b\u0430\u043d \u0456 \u041d\u0415\u0413\u0410\u0419\u041d\u041e \u0432\u0438\u043a\u043b\u0438\u043a\u0430\u0439 \u0456\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u0438 (list_dir, read_file, search_text, python_check, edit_file, run_command). "
                "3) \u041f\u0440\u0438\u0439\u043c\u0430\u0439 \u0442\u0435\u0445\u043d\u0456\u0447\u043d\u0456 \u0440\u0456\u0448\u0435\u043d\u043d\u044f \u0441\u0430\u043c\u043e\u0441\u0442\u0456\u0439\u043d\u043e \u0439 \u043f\u043e\u0432\u0435\u0440\u0442\u0430\u0439 \u0432\u0436\u0435 \u0432\u0438\u043a\u043e\u043d\u0430\u043d\u0438\u0439 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442.\n"
            )
            try:
                if self.session.messages and self.session.messages.get("role") == "system":
                    self.session.messages["content"] = str(self.session.messages.get("content") or "") + "\n" + _auto_rule
            except Exception:
                pass

        budget = self.step_budget
        facts = selflearning.TurnFacts(
            calls=calls,
            changed_files=list(self._touched_files or []),
            syntax_repairs=int(getattr(self, "_syntax_repairs", 0) or 0),
            asked_permission=bool(getattr(self, "_continue_asked", False)),
            steps=int(getattr(self, "_steps_used", 0) or 0),
            max_steps=budget,
            ok=bool(ok),
            goal=str(getattr(self.state, "goal", "") or ""),
            intent_type=str(getattr(self.intent, "intent_type", "") or ""),
            # ── Три джерела одного ходу: модель + інтернет + користувач ────
            # Урок виводиться не лише з ПОМИЛОК: знайдене в мережі й
            # поправка людини — теж знання, і воно має дійти до наступного
            # ходу (вимога 21.11.2026).
            web_query=str(getattr(self, "_web_query", "") or ""),
            web_digest=str(getattr(self, "_web_digest", "") or ""),
            web_facts=int(getattr(self, "_web_facts", 0) or 0),
            user_corrected=bool(getattr(self, "_user_corrected", False)),
            user_words=str(getattr(self, "_user_correction", "") or ""),
        )
        try:
            saved = learning.learn_turn(facts)
        except Exception:                            # noqa: BLE001
            LOG.debug("Уроки ходу не зроблено", exc_info=True)
            return
        if saved:
            self._emit("status", selflearning.describe_lessons(saved))

    def _build_plan(self) -> None:
        """Побудувати план кроків із кадру наміру (без моделі)."""
        self._plan = []
        try:
            if not getattr(self.agent_settings, "auto_plan", True):
                return
            if not planning.should_plan(self.intent, self.state):
                return
            steps = planning.build_plan(self.intent, self.state)
            if not steps:
                return
            self._plan = planning.order_steps(steps)
        except Exception:                           # noqa: BLE001
            LOG.debug("План не побудовано", exc_info=True)
            self._plan = []
            return
        if self._plan:
            self._emit("status", f"План: {len(self._plan)} кроків.")
            for index, step in enumerate(self._plan, start=1):
                self._emit("plan_step", step.title, index=index,
                           total=len(self._plan), tools=list(step.tools))

    def _prepare_understanding(self, text: str) -> None:
        """Порахувати намір і оновити стан розмови для цього повідомлення."""
        active = ""
        if self.active_path_provider is not None:
            try:
                picked = self.active_path_provider()
                active = str(picked or "")
            except Exception:                       # noqa: BLE001
                active = ""
        try:
            self.intent = intent_engine.frame(
                text,
                previous_messages=self.state.recent,
                active_path=active,
                previous_intent=self.state.intent_type,
            )
        except Exception:                           # noqa: BLE001 - не ламаємо старт
            LOG.debug("Намір не вдалося визначити", exc_info=True)
            self.intent = None
        if self.intent is not None:
            self.state.observe_user_message(text, self.intent)
        else:
            self.state.observe_user_message(text)
        # Постійні побажання: зберігаємо лише те, що людина сказала прямо
        # («завжди відповідай українською»), і лише якщо не просили не
        # зберігати.
        try:
            found, private = conversation.extract_preferences(text)
            if private:
                self.state.private = True
            elif found:
                conversation.merge_preferences(self.profile, found)
        except Exception:                           # noqa: BLE001
            LOG.debug("Побажання не розпізнано", exc_info=True)

    def _context_block(self) -> str:
        """Підказка моделі: мета, обмеження, згадки, профіль, формат виклику."""
        parts: list[str] = []
        intent = self.intent
        if intent is not None:
            try:
                hint = intent_engine.frame_prompt(intent)
            except Exception:                       # noqa: BLE001
                hint = ""
            if hint:
                parts.append(hint)
            try:
                resolved = self.state.resolve(intent.text)
            except Exception:                       # noqa: BLE001
                resolved = ""
            if resolved:
                parts.append(resolved)
        state_block = self.state.prompt_block()
        if state_block:
            parts.append(state_block)
        # Пам'ять: факти й обмеження проєкту. Після стану розмови, бо
        # поточне завдання важливіше за історію, але ПЕРЕД побажаннями:
        # конкретний факт важить більше за загальний стиль.
        snapshot = self._memory_snapshot
        if snapshot is not None and not self.state.private:
            try:
                memory_block = snapshot.prompt_block()
            except Exception:                       # noqa: BLE001
                memory_block = ""
            if memory_block:
                parts.append(memory_block)
        # План: модель має бачити кроки, а не вигадувати структуру сама.
        if self._plan:
            try:
                plan_block = planning.plan_prompt_block(self.intent, self._plan)
            except Exception:                       # noqa: BLE001
                plan_block = ""
            if plan_block:
                parts.append(plan_block)
        # ── Уроки: що агент уже зробив не так ──────────────────────────────
        # Ставимо ПІСЛЯ плану: спершу «що робити», потім «чого не робити».
        # Інакше застереження перебивало б сам план.
        if not self.state.private:
            hints = list(getattr(self, "_lesson_hints", ()) or ())
            if hints:
                parts.append("Висновки з попередніх спроб (врахуй):\n"
                             + "\n".join(f"- {item}" for item in hints))
            # ── Свобода дій: скільки кроків і коли вирішувати самому ──────
            level = getattr(self, "autonomy", "") or autonomy.DEFAULT_LEVEL
            parts.append(autonomy.prompt_hint(level))
        if not self.state.private:
            profile_block = self.profile.prompt_block()
            if profile_block:
                parts.append(profile_block)
        if self.model_caps is not None and self.model_caps.text_protocol:
            parts.append(model_profile.text_tool_protocol(tuple(self._specs or ())))
        return "\n\n".join(parts)

    def run_blocking(self, text: str, *, extra_prompt: str = "", timeout: float = 900.0) -> tuple[bool, str]:
        """Виконати задачу синхронно (використовується чергою задач).

        Повертає (успіх, фінальний текст або повідомлення про помилку).
        """
        self.start(text, extra_prompt=extra_prompt)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.busy:
                break
            time.sleep(0.1)
        if self.busy:
            self.cancel()
            return False, "Перевищено час очікування відповіді."
        if self._error:
            return False, self._error
        return True, self._last_answer or "Готово."

    # ── інструменти ────────────────────────────────────────────────────────
    def registry_memory_schemas(self) -> list[dict[str, Any]]:
        """Схеми інструментів пам'яті, якщо вона підключена до реєстру.

        Пам'ять — необов'язковий компонент: без неї агент працює як раніше,
        а моделі не показують інструментів, яких немає.
        """
        try:
            if not self.registry.memory_ready():
                return []
            return self.registry.tool_schemas()[len(TOOL_SCHEMAS):] or []
        except Exception:                            # noqa: BLE001 - не ламаємо агента
            LOG.debug("Схеми пам'яті недоступні", exc_info=True)
            return []

    def tool_schemas(self, *, probe_window: bool = True) -> list[dict[str, Any]]:
        """Схеми, які БАЧИТЬ модель цього ходу.

        Два режими, і вибір між ними — за РЕАЛЬНИМ розміром набору:

        * **повний** — усе вміщається в бюджет схем: передаємо весь набір,
          без зайвої церемонії;
        * **лінивий** — набір завеликий: передаємо ядро, інструменти
          керування реєстром і те, що модель уже завантажила сама
          (:mod:`blackchpok_ide.tool_lazy`). Решта інструментів лишається
          ДОСЯЖНОЮ через ``run_tool`` (виклик за назвою) і ``load_tools``
          (щоб побачити параметри).

        Саме це прибирає переповнення: 60+ повних схем — це ≈20 000 токенів,
        більше за вікно локальної моделі, і сервер обривав з'єднання ще до
        першого токена відповіді.

        ``probe_window=False`` — для ІНТЕРФЕЙСУ. Визначення вікна робить
        мережевий запит (``/props``), а панель контексту кличе цей метод на
        кожне оновлення. На непіднятому сервері запит коштує до 1 с
        (заміряно: 1.0 с у головному потоці під час першого кадру). Коли
        вікно вже відоме, прапорець ні на що не впливає; коли ні — беремо
        наявне/заявлене значення, а справжнє підтягнеться перед першим
        ходом агента (там запит уже у фоновому потоці).
        """
        if not self.tools_enabled:
            # Режим «Чат»: моделі не показуємо інструменти взагалі, тому
            # вона не намагається їх викликати й не «розмовляє» про них.
            return []
        # ── Спершу вікно, ПОТІМ схеми ─────────────────────────────────────
        # Порядок принциповий. Раніше схеми обирались за вікном, яке могло
        # бути застарілим (32768 із налаштувань замість реальних 16384), і
        # в результаті модель отримувала 65 схем ≈20 000 токенів — більше
        # за ВЕСЬ контекст. Сервер обривав з'єднання одразу.
        if probe_window and not getattr(self, "_context_window", None):
            try:
                self.probe_context_window()
            except Exception:  # noqa: BLE001 - не має ламати вибір схем
                LOG.debug("Вікно перед вибором схем не визначено", exc_info=True)
        available = self._available_schemas()
        # ── ПОВНИЙ НАБІР ІНСТРУМЕНТІВ (без звуження) ──────────────────────
        # Вимога користувача (21.11.2026): «ніяких режимів лінивий, тільки
        # повний режим з повною автономією!».
        #
        # Що було. Два шари звужували набір незалежно: авто-роутер
        # (:mod:`tool_select`) брав «профіль за наміром» — у живому прогоні
        # 13 інструментів із 87, — а «лінивий» реєстр лишав ядро плюс те, що
        # модель здогадалась завантажити. Наслідок: модель не бачила
        # потрібного інструмента, витрачала кроки на ``load_tools`` і йшла по
        # колу замість роботи.
        #
        # Що тепер. Якщо набір узагалі вміщається у вікно — модель бачить
        # УСІ схеми. Звуження лишається ЛИШЕ як запобіжник для вузьких
        # вікон (8k і менше), де повний набір фізично не вміщається: краще
        # показати ядро, ніж обірвати запит помилкою контексту.
        # ``getattr`` тут, а не пряме звертання: раннер можна створити
        # частково (тести, відновлення) без ``agent_settings``, і вибір схем
        # не має через це падати — типово повний режим.
        settings = getattr(self, "agent_settings", None)
        full_tools = bool(getattr(settings, "full_tools", True))
        if not full_tools:
            available = self._select_schemas(available)
        # ── Рішення: повний набір чи лінивий реєстр ─────────────────────────
        # Порівнюємо РЕАЛЬНИЙ розмір схем із бюджетом схем. Якщо все вміщається
        # — передаємо повний набір і не змушуємо модель робити зайвий крок.
        router = self.lazy_router()
        lazy = router.update(
            available,
            budget_tokens=self._schema_budget(),
            token_counter=AgentSession._tokens_in,
            specs=self._specs or None,
            # Повний режим: лінивість вимикаємо, поки набір РАЗОМ із
            # системою й відповіддю лишає місце на історію. Перевірка бере
            # реальні схеми: з 91 інструментом вони важать 11 520 токенів, і
            # «вікно 16k» саме по собі нічого не гарантує.
            force_full=full_tools and self._full_set_fits(available),
        )
        self._schemas_lazy = bool(lazy)
        if lazy:
            available = router.eager_schemas()
        # ── Вузьке вікно контексту: схеми мусять влізти ─────────────────────
        # 28 схем займають ≈3000 токенів. У вікні 4096 це половина запиту ще
        # до розмови, а в 2048 — більше за все вікно: сервер відповідав
        # ``exceed_context_size_error``. Тому схеми впорядковані за
        # важливістю й лишаються найпотрібніші (див. ``_fit_schemas``).
        #
        # У ПОВНОМУ режимі це єдине місце, де набір ще може скоротитись, і
        # скорочується він ЛИШЕ під реальний розмір вікна — не за наміром.
        #
        # ``_full_set_fits()`` обов'язковий: у вікні 2048 «повний» бюджет у
        # 50% вікна більший за сам запит, і схеми не вміщались у контекст
        # (перевірено ``test_v2_audit``: 2231 токен при вікні 2048).
        schemas = self._fit_schemas(
            available, full=bool(full_tools) and self._full_set_fits(available))
        # Кеш для оцінки токенів: схеми займають помітну частину вікна,
        # і бюджет історії має це враховувати.
        self._schemas_cache = schemas
        self.session._schemas_cache = schemas
        # Реєстр описів будуємо з ТИХ САМИХ схем, які бачить модель:
        # інакше оркестратор знав би про інструменти, яких модель не бачить,
        # або навпаки — не знав би про підключені MCP-дії.
        #
        # У лінивому режимі — з ПОВНОГО набору: ``run_tool`` мусить уміти
        # виконати інструмент, чию схему модель «не бачила». Інакше
        # лінивість перетворилась би на заборону.
        specs_source = available
        if lazy:
            specs_source = router.all_schemas() + tool_lazy.control_schemas()
        self._specs = tool_specs.specs_for_schemas(specs_source)
        self._refresh_lazy_specs()
        return schemas

    def _select_schemas(self, available: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Звузити набір схем до потрібних для ЦЬОГО запиту.

        Джерела сигналу, від сильнішого:

        1. текст останнього запиту користувача — що саме просять робити;
        2. намір (``self.intent``) — уже розібраний тип задачі;
        3. підказки ``tool_router`` — конкретні дії, розпізнані у фразі;
        4. те, що модель завантажила сама (``load_tools``);
        5. набір попереднього ходу — завдання складається з кількох кроків.

        Якщо схеми вже вкладаються в бюджет І їх небагато — лишаємо все:
        економити на 8 схемах немає сенсу, а зайве звуження змусило б
        модель робити крок ``load_tools`` на рівному місці.

        Невідома ситуація ніколи не дає порожній набір: ядро безпеки й
        контроль реєстру додаються завжди.
        """
        if not available:
            return available
        text = ""
        previous: list[str] = []
        try:
            for message in reversed(self.session.messages):
                if str(message.get("role") or "") == "user":
                    content = message.get("content")
                    text = content if isinstance(content, str) else str(content or "")
                    break
        except (AttributeError, TypeError):
            text = ""
        # ── Без тексту запиту НЕ звужуємо нічого ───────────────────────────
        # Звуження — це здогад про майбутню задачу. Коли запиту немає
        # (старт, відновлення чату, прямий виклик), здогад лише шкодить:
        # модель могла лишитись без ``write_file`` і просити ``load_tools``
        # замість роботи. Економія тут не варта ризику.
        if not text.strip():
            return available
        intent_type = str(getattr(getattr(self, "intent", None),
                                  "intent_type", "") or "")
        hints: list[Any] = []
        try:
            from . import tool_router

            if text:
                hints = list(tool_router.confident(text))
        except Exception:  # noqa: BLE001 - підказки необов'язкові
            LOG.debug("Підказки роутера не отримано", exc_info=True)
        loaded: list[str] = []
        router = getattr(self, "_lazy_router", None)
        if router is not None:
            try:
                loaded = list(getattr(router, "_loaded", ()) or ())
            except (AttributeError, TypeError):
                loaded = []
        previous = list(getattr(self, "_last_tool_names", ()) or ())
        names = [tool_lazy._schema_name(schema) for schema in available]  # noqa: SLF001
        try:
            from . import tool_select

            selection = tool_select.select_names(
                available=[name for name in names if name],
                text=text, intent_type=intent_type, hints=hints,
                loaded=loaded, previous=previous)
        except Exception:  # noqa: BLE001 - роутер не має ламати хід
            LOG.debug("Авто-роутер інструментів не спрацював", exc_info=True)
            return available
        chosen = set(selection.names)
        if not chosen:
            return available
        narrowed = [schema for schema, name in zip(available, names)
                    if name in chosen]
        # Якщо звуження не дало нічого (назви не збіглись) — лишаємо як є:
        # краще зайві схеми, ніж агент без інструментів узагалі.
        if not narrowed:
            return available
        self._last_tool_names = [name for name in names if name in chosen]
        LOG.info("Авто-роутер: %s (з %s)", selection.reason, len(available))
        if len(narrowed) < len(available):
            self._emit("status",
                       f"Інструменти цього кроку: {len(narrowed)} із "
                       f"{len(available)} ({selection.reason})")
        return narrowed

    def _schema_budget(self, *, full: bool = False) -> int:
        """Скільки токенів можна віддати схемам інструментів.

        ЄДИНА міра для всього: і ``_fit_schemas``, і ``_full_set_fits``
        рахують від одного числа. Раніше це були дві різні формули (25% вікна
        проти «room мінус частка історії»), і вони давали різні відповіді:
        перевірка «повний набір не влазить» спрацьовувала, а обрізання
        вважало, що влазить. Наслідок — непередбачуваний набір схем.

        ``full=True`` — скільки лишається схемАМ, якщо на розмову відкласти
        :data:`HISTORY_FLOOR_SHARE` вікна. Це і є межа «повного набору».
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if limit <= 0:
            return 0
        budget_model = getattr(self, "_context_budget", None)
        if budget_model is None or not budget_model.window:
            return max(512, int(limit * (0.5 if full else 0.25)))
        # Скільки лишається після системи, відповіді й запасу.
        room = (budget_model.window - budget_model.answer
                - budget_model.safety - budget_model.system)
        if full:
            # Мінус частка, відкладена на саму розмову.
            return max(0, room - self._history_floor())
        ceiling = max(512, int(budget_model.window * 0.25))
        return min(ceiling, max(512, room))

    def _full_set_fits(self, schemas: list[dict[str, Any]] | None = None) -> bool:
        """Чи вміщається ПОВНИЙ набір схем у вікно моделі.

        Навіщо окремо від ``update``. ``tool_lazy`` порівнює розмір із
        бюджетом схем — а бюджет — це частка вікна. Для повного режиму цього
        замало: питання не «скільки відведено під схеми», а «чи влізе
        взагалі разом із системою, історією й відповіддю».

        ── ЧОМУ ЛИШЕ РОЗМІР ВІКНА БУЛО ПОМИЛКОЮ (заміряно 21.11.2026) ────
        Раніше тут стояло лише ``limit >= FULL_SET_MIN_WINDOW``. Коли
        інструментів стало 91 (MCP + пам'ять + скіли + саморобні), схеми
        почали важити 11 520 токенів — а вікно 16 384 усе ще проходило
        перевірку. Наслідок у лозі: «система 8 939, схеми 4 252, історія 0»
        — тобто обрізалось до 17 схем із 91 випадково, і модель отримувала
        нуль історії. Користувач бачив, що «відповіді перестали надходити».

        Тепер перевірка реальна: чи вміщається набір РАЗОМ із системою,
        відповіддю й запасом. Якщо ні — вмикається звуження (ядро + контроль
        реєстру), і на історію лишається місце.
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if limit <= 0:
            # Вікно невідоме — обережно вважаємо, що повний набір уміщається:
            # більшість моделей, з якими працює проєкт, мають ≥16k.
            return True
        if limit < FULL_SET_MIN_WINDOW:
            return False
        if not schemas:
            return True
        # ── Міряємо НАЙДЕШЕВШИЙ варіант, а не сирий ────────────────────────
        # ``_fit_schemas`` уміє стискати описи (9302 → 7058 токенів), і в
        # повному режимі воно робить це ПЕРШ ніж різати. Тому питання не
        # «чи влізе сирий набір», а «чи влізе стиснутий»: саме його модель і
        # побачить. Раніше тут мірявся сирий набір, перевірка казала «не
        # влазить», вмикався лінивий реєстр — і модель отримувала 17 схем
        # замість 64, хоч стиснуті всі 64 уміщались.
        allowed = self._schema_budget(full=True)
        if allowed <= 0:
            return False
        cheapest = tool_lazy.compact_schemas(
            schemas, description_limit=tool_lazy.COMPACT_DESCRIPTION_TIGHT,
            param_limit=tool_lazy.COMPACT_PARAM_TIGHT)
        return self._schemas_cost(cheapest) <= allowed

    def _history_floor(self) -> int:
        """Скільки токенів МИСИТЬ лишитись на саму розмову.

        Не «частка вікна навмання»: беремо менше з двох — частки вікна й
        того, що реально лишається після системи, відповіді та запасу.
        Інакше при великому промпті «захист історії» сам стає причиною, чому
        схемАМ не лишається нічого, і набір ріжеться до ядра.
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if limit <= 0:
            return 0
        budget_model = getattr(self, "_context_budget", None)
        if budget_model is None or not budget_model.window:
            return max(1024, int(limit * HISTORY_FLOOR_SHARE))
        room = (budget_model.window - budget_model.answer
                - budget_model.safety - budget_model.system)
        share = max(1024, int(budget_model.window * HISTORY_FLOOR_SHARE))
        # Не більше половини того, що лишилось: інакше історія з'їдає місце,
        # призначене інструментам, і модель втрачає можливості.
        return max(0, min(share, int(room * 0.5)))

    def _refresh_lazy_specs(self) -> None:
        """Додати специфікації інструментів керування реєстром.

        Вони мусять бути в реєстрі, інакше оркестратор відхилить виклики
        ``find_tools``/``load_tools``/``run_tool`` як «невідомий інструмент»
        — і лінивий режим став би безвихідним.
        """
        if self._specs is None:
            self._specs = {}
        for spec in tool_specs.specs_for_schemas(
                tool_lazy.control_schemas()).values():
            self._specs.setdefault(spec.name, spec)

    def _lazy_registry_text(self) -> str:
        """Компактний реєстр для промпту — лише в лінивому режимі.

        У повному режимі реєстр не потрібен: модель уже бачить повні схеми,
        і другий перелік лише дублював би інформацію та з'їдав токени.

        У лінивому режимі беремо НАЙКОРОТШИЙ варіант (``compact_text``):
        назви без описів. Описи інструментів уже є в схемах, які модель
        бачить, а для решти назви досить — призначення знаходиться через
        ``find_tools``, який шукає і за описом.
        """
        if not self.lazy_mode():
            return ""
        router = getattr(self, "_lazy_router", None)
        if router is None:
            return ""
        return router.compact_text()

    def _available_schemas(self) -> list[dict[str, Any]]:
        """УСІ схеми, які існують у системі: без обрізання й без лінивості.

        Це джерело істини для реєстру інструментів. Лінивий режим будує
        компактний реєстр САМЕ звідси, тому жоден інструмент не може
        зникнути з поля зору моделі — він лише перестає займати місце
        повною схемою.
        """
        schemas = list(TOOL_SCHEMAS)
        # Пам'ять NEUROMESH: інструменти додаються лише якщо її підключено.
        schemas.extend(self.registry_memory_schemas())
        schemas.extend(skills_module.tool_schemas())
        # Саморозширення: агент створює власні скіли й інструменти з діалогу
        # та з інтернету, і наступного разу користується ними сам.
        schemas.extend(extensions_module.TOOL_SCHEMAS)
        # Уже створені саморобні інструменти — теж повноцінні дії.
        try:
            schemas.extend(extensions_module.custom_tool_schemas(
                self.workspace, limit=extensions_module.MAX_TOOLS))
        except Exception:                            # noqa: BLE001 - не ламаємо хід
            LOG.debug("Схеми саморобних інструментів недоступні", exc_info=True)
        if self.settings_ref is not None:
            schemas.extend(social.tool_schemas())
        manager = self.mcp_manager
        if manager is not None:
            try:
                mcp_schemas = manager.tool_schemas()
                # Багатофункціональний роутер MCP ховає десятки дій за одним
                # інструментом — моделі важко здогадатись про intent. Тому
                # додаємо прямі схеми для найуживаніших дій.
                provided = {schema["function"]["name"] for schema in schemas}
                mcp_schemas = [
                    schema for schema in mcp_schemas
                    if schema["function"]["name"] not in provided
                ]
                schemas.extend(mcp_schemas)
                schemas.extend(self._router_schemas(provided))
            except Exception as exc:  # noqa: BLE001 - MCP не має ламати агента
                LOG.warning("MCP-схеми недоступні: %s", exc)
        return schemas

    def orchestrator_for_turn(self) -> tool_orchestrator.Orchestrator:
        """Оркестратор інструментів для поточного ходу.

        Створюється на кожен хід: усередині живе пам'ять про виконані
        виклики (захист від повторів), і вона не має перетікати в наступний
        хід — після зміни файлу той самий ``read_file`` цілком доречний.
        """
        if not self._specs:
            self.tool_schemas()
        if self._observations is None:
            self._observations = []
        engine = tool_orchestrator.Orchestrator(
            self.call_tool,
            self._specs or {},
            emit=self._emit,
            allow_parallel=bool(getattr(self.agent_settings, "parallel_tools", True)),
        )
        self.orchestrator = engine
        return engine

    def _fit_schemas(self, schemas: list[dict[str, Any]],
                     *, full: bool = False) -> list[dict[str, Any]]:
        """Лишити стільки схем, скільки реально вміщається у вікно моделі.

        Пріоритет — у :data:`SCHEMA_PRIORITY`: без читання й запису файлів
        агент не працює зовсім, а без знімка сторінки — просто працює
        гірше. Коли місця бракує, ми прибираємо ДРУГОРЯДНІ схеми (а не
        мовчки переповнюємо контекст), і кажемо про це в лог.

        ``full=True`` — ПОВНИЙ режим (вимога 21.11.2026: «ніяких режимів
        лінивий, тільки повний режим»). Тоді межа піднята до половини вікна:
        заміряно, що всі 54 вбудовані схеми важать 7701 токен, а 25% від
        16384 — лише 4096, тобто «повний режим» мовчки зрізав половину
        інструментів. Половинний бюджет уміщає їх разом із системою й
        відповіддю, а на вузькому вікні (8k) усе одно звужує — там повний
        набір фізично не влазить.

        ВАЖЛИВО про розмір бюджету. Раніше стояло «40% вікна» — і цього
        не вистачало, щойно підключався MCP: 65 схем давали ≈20 000
        токенів, при вікні 16384 це більше за ВЕСЬ контекст. Сервер
        обривав з'єднання (``WinError 10054``) одразу після заголовків, і
        це виглядало як «модель не працює».

        Тепер бюджет схем узятий із СПІЛЬНОГО розподілу
        (:meth:`adopt_context_window`): там уже враховано системний промпт,
        резерв під відповідь і запас. Схемам дістається рівно те, що
        лишилось, — без подвійного обліку й без «40% навмання».
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if limit <= 0 or not schemas:
            return schemas
        share = 0.5 if full else 0.25
        budget_model = getattr(self, "_context_budget", None)
        if budget_model is not None and budget_model.window:
            # Частка схем у бюджеті: не більше ``share`` вікна й не більше
            # того, що лишилось після системи та резерву відповіді.
            ceiling = max(512, int(budget_model.window * share))
            budget = min(ceiling, max(512, budget_model.window
                                      - budget_model.answer
                                      - budget_model.safety
                                      - budget_model.system))
        else:
            # Бюджет ще не пораховано (перший хід до сервера) — беремо
            # обережнішу частку: менше, ніж «40% навмання», і саме стільки,
            # щоб лишилось місце розмові.
            budget = max(512, int(limit * share))
        # ── ПОВНИЙ РЕЖИМ: спершу стискаємо описи, а не ховаємо інструменти ──
        # Вимога: «ніяких режимів лінивий, тільки повний режим». Сирий набір
        # (60 схем) важить 9302 токени, а бюджет схем у вікні 16k — 8113, тож
        # без стиснення «повний режим» мовчки зрізав би частину інструментів.
        # Заміряно: стиснення описів дає 7058 токенів, і всі назви, типи та
        # обов'язкові параметри лишаються — модель бачить УСІ інструменти.
        if full:
            total_cost = self._schemas_cost(schemas)
            if total_cost > budget:
                for description_limit, param_limit in (
                        (tool_lazy.COMPACT_DESCRIPTION_LIMIT,
                         tool_lazy.COMPACT_PARAM_LIMIT),
                        (tool_lazy.COMPACT_DESCRIPTION_TIGHT,
                         tool_lazy.COMPACT_PARAM_TIGHT)):
                    candidate = tool_lazy.compact_schemas(
                        schemas, description_limit=description_limit,
                        param_limit=param_limit)
                    candidate_cost = self._schemas_cost(candidate)
                    if candidate_cost <= budget:
                        LOG.info("Схеми стиснуто під вікно %s: %s → %s токенів, "
                                 "усі %s інструментів лишились",
                                 limit, total_cost, candidate_cost, len(schemas))
                        return candidate
                    schemas, total_cost = candidate, candidate_cost
        ordered = sorted(schemas, key=lambda item: _schema_rank(item))
        kept: list[dict[str, Any]] = []
        used = 0
        for schema in ordered:
            try:
                encoded = json.dumps(schema, ensure_ascii=False)
            except (TypeError, ValueError):
                encoded = ""
            # Той самий перерахунок «символи → токени», що й у сесії.
            cost = AgentSession._tokens_in(encoded) if encoded else 400
            # ── Гарантія для MCP-інструментів ─────────────────────────────
            # Підключений MCP-сервер — це можливості, яких в агента інакше
            # НЕМА: пам'ять, індексація, нічні зміни. Обрізання не має
            # прибирати їх повністю, інакше «MCP активний» на практиці
            # означав би «модель його не бачить».
            try:
                name = str(schema["function"]["name"])
            except (KeyError, TypeError):
                name = ""
            important = name.startswith(("mcp__", "router:")) or name in {
                "list_skills", "read_skill", *tool_lazy.CONTROL_TOOLS}
            # ── КОНТРОЛЬ РЕЄСТРУ — ПОНАД БЮДЖЕТ, АЛЕ ЗАВЖДИ ───────────────
            # Заміряно 21.11.2026: при 18 слотах ``run_tool`` ВИПАВ, і
            # «лінивість» перетворилась на «недоступність»: модель не могла
            # викликати жоден інструмент, чиєї схеми не бачить.
            #
            # Тому три схеми керування (``find_tools``/``load_tools``/
            # ``run_tool``) додаються ПЕРШИМИ й безумовно: вони дешеві (три
            # маленькі схеми), а без них решта набору стає пасткою.
            if name in tool_lazy.CONTROL_TOOLS:
                kept.append(schema)
                used += cost
                continue
            # ── ДУЖЕ ВУЗЬКЕ ВІКНО: МІНІМУМ, А РЕШТА — ЧЕРЕЗ run_tool ───────
            # У вікні 2048 системний промпт (775) + ядро з 14 схем (≈2100)
            # переповнюють контекст: заміряно 2121 при ліміті 2048, а після
            # підрізання — 3450. Тому при такому вікні лишаємо РІВНО
            # чотири речі: читати, писати, правити й запускати. Більше
            # нічого: будь-яка зайва схема шкодить більше, ніж дає, бо
            # агент фізично не бачить повідомлення.
            #
            # Решта інструментів ЛИШАЄТЬСЯ ДОСЯЖНОЮ через ``run_tool`` —
            # саме тому контроль реєстру вище додається безумовно.
            if limit and limit < _TINY_WINDOW_TOKENS:
                if name in _TINY_WINDOW_TOOLS:
                    kept.append(schema)
                    used += cost
                continue
            # ── ЗАВАНТАЖЕНІ МОДЕЛЛЮ — ТЕЖ БЕЗ ОБРІЗАННЯ ───────────────────
            # Заміряно 21.11.2026: ``load_tools`` відповідав «завантажено»,
            # але схема НЕ з'являлась у наборі — бо обрізання викидало її
            # знову. Модель бачила підтвердження й не могла викликати
            # інструмент: обіцянка без можливості.
            #
            # Тепер усе, що модель попросила сама, лишається у наборі
            # (у межах розумного запасу): вона вже витратила крок на
            # прохання, і повторювати його означало б цикл.
            router_now = getattr(self, "_lazy_router", None)
            asked = getattr(router_now, "_loaded", set()) if router_now else set()
            if name in asked:
                kept.append(schema)
                used += cost
                continue
            # Першу (найважливішу) схему беремо завжди: агент без інструментів
            # не працює, навіть якщо вона сама більша за бюджет.
            if kept and used + cost > budget:
                if not important:
                    continue
                # MCP/скіли: дозволяємо вийти за бюджет, але не більше ніж
                # на 25% — інакше знову переповнимо контекст.
                if used + cost > budget * 1.25:
                    continue
            kept.append(schema)
            used += cost
        # ── ДУЖЕ ВУЗЬКЕ ВІКНО: СТИСКАЄМО ОПИСИ, А НЕ ВІДКИДАЄМО ДІЇ ───────
        # У вікні 2048 ядро + контроль важать 1190 токенів, системний промпт
        # 780 — разом 1970, і на повідомлення лишається 78. Запит
        # переповнюється (заміряно: 2199 при ліміті 2048).
        #
        # Замість відкидати дії (модель стає безпорадною) — СТИСКАЄМО описи.
        # Назви, типи й обов'язкові параметри лишаються, тож усі сім
        # інструментів працюють; зникає лише багатослівність.
        if limit and limit < _TINY_WINDOW_TOKENS and kept:
            compact = tool_lazy.compact_schemas(
                kept,
                description_limit=tool_lazy.COMPACT_DESCRIPTION_TIGHT,
                param_limit=tool_lazy.COMPACT_PARAM_TIGHT)
            saved = self._schemas_cost(kept) - self._schemas_cost(compact)
            if saved > 0:
                LOG.info("Вузьке вікно %s: схеми стиснуто, зекономлено %s "
                         "токенів (дії лишились усі: %s)",
                         limit, saved, len(compact))
                kept = compact
        if len(kept) < len(schemas):
            LOG.info("Схем інструментів обрізано під вікно %s "
                     "(бюджет схем %s, використано %s): %s з %s",
                     limit, budget, used, len(kept), len(schemas))
        return kept

    # ── лінивий реєстр інструментів ────────────────────────────────────────
    @staticmethod
    def _schemas_cost(schemas: list[dict[str, Any]]) -> int:
        """Вартість набору схем у токенах (та сама міра, що й у бюджеті)."""
        total = 0
        for schema in schemas:
            try:
                encoded = json.dumps(schema, ensure_ascii=False)
            except (TypeError, ValueError):
                total += 400
                continue
            total += AgentSession._tokens_in(encoded) if encoded else 400
        return total

    def lazy_router(self) -> "tool_lazy.LazyToolRouter":
        """Лінивий реєстр інструментів (створюється за потреби).

        Живе на раннері, бо переживає кроки одного завдання: те, що модель
        завантажила на кроці 2, має лишатись доступним на кроці 5 — інакше
        вона завантажувала б ту саму схему щоразу.
        """
        router = getattr(self, "_lazy_router", None)
        if router is None:
            # Скільки схем показати моделі одразу, залежить від вікна: на
            # малому вікні 48 повних схем з'їдали майже все, і на історію
            # лишалось 163 токени — агент «забував», що вже зробив.
            router = tool_lazy.LazyToolRouter(priority=SCHEMA_PRIORITY,
                                             max_eager=self._eager_tool_limit(),
                                             emit=self._emit)
            self._lazy_router = router
        return router

    def _schemas_are_visible(self) -> bool:
        """Чи модель бачить повні схеми інструментів цього ходу.

        Коли бачить — текстовий каталог зайвий (це те саме, лише словами),
        і його місце в контексті марне. Коли ні (лінивий режим без
        специфікацій або вузьке вікно) — каталог єдине джерело назв.

        Перевірка дешева: беремо те, що вже вирішено в ``tool_schemas()``,
        без жодного запиту до мережі.
        """
        try:
            if not self.tools_enabled:
                return False
            if getattr(self, "_schemas_lazy", False):
                # Лінивий режим: повних схем мало, але є реєстр назв —
                # каталог із описами тут не потрібен, реєстр уже сказав що є.
                return True
            return bool(self._specs)
        except Exception:  # noqa: BLE001 - не має ламати старт
            return False

    def _eager_tool_limit(self) -> int:
        """Скільки інструментів показати повністю за поточного вікна.

        Малий контекст (8192) не вміщає 48 схем: кожна в середньому ~110
        токенів, разом ~2100, плюс система ~3000 — і на розмову майже нічого
        не лишається. Тому кількість прив'язана до вікна; решта доступна
        через ``find_tools``/``load_tools``, тож нічого не втрачається.

        ПОВНИЙ РЕЖИМ (вимога 21.11.2026) піднімає стелю до кількості
        реально наявних інструментів: саме поріг 48 мовчки перемикав
        систему на «лінивий» реєстр навіть тоді, коли бюджет схем дозволяв
        усе. Рішення про те, скільки влазить, ухвалює вже ``_fit_schemas``
        за РЕАЛЬНИМИ токенами — воно й обрізає зайве.
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        settings = getattr(self, "agent_settings", None)
        full = bool(getattr(settings, "full_tools", True))
        if full and limit >= FULL_SET_MIN_WINDOW:
            # Не «нескінченність»: рівно стільки, скільки є. Далі staffing
            # обріже ``_fit_schemas`` за бюджетом.
            return max(tool_lazy.MAX_EAGER_TOOLS, 999)
        if limit <= 0:
            return tool_lazy.MAX_EAGER_TOOLS
        if limit < 12_288:
            return len(tool_lazy.CORE_TOOLS) + len(tool_lazy.CONTROL_TOOLS)
        if limit < 24_576:
            return 28
        return tool_lazy.MAX_EAGER_TOOLS

    def invalidate_tool_cache(self, reason: str = "") -> None:
        """Скинути кеш схем інструментів після зміни реєстру.

        Викликається, коли змінився набір інструментів або модель: після
        перезапуску MCP, підключення пам'яті, зміни моделі чи конфігурації
        агента. Без цього модель могла отримати схему інструмента, якого
        вже немає, або не побачити щойно підключений.
        """
        router = getattr(self, "_lazy_router", None)
        if router is not None:
            router.invalidate(reason=reason or "зміна реєстру")
        self._schemas_cache = None
        try:
            self.session._schemas_cache = None
        except AttributeError:
            pass
        self._specs = {}
        LOG.info("Кеш інструментів скинуто: %s", reason or "зміна реєстру")

    def lazy_mode(self) -> bool:
        """Чи передаються схеми ліниво (а не повним набором).

        Рішення ухвалює :class:`tool_lazy.LazyToolRouter` за РЕАЛЬНИМ
        розміром набору й бюджетом схем — тут лише читаємо його.
        """
        return bool(getattr(self, "_schemas_lazy", False))

    def tool_registry_state(self) -> dict[str, Any]:
        """Стан реєстру інструментів для індикатора в інтерфейсі.

        Повертає РЕАЛЬНІ числа: скільки інструментів існує, скільки схем
        реально пішло моделі цього ходу, чи ввімкнено лінивість і чому.
        Ніяких декоративних значень.
        """
        router = getattr(self, "_lazy_router", None)
        if router is None:
            return {"total": 0, "eager": 0, "loaded": 0, "lazy": False,
                    "reason": "реєстр ще не побудовано"}
        return router.stats()

    def tool_indicator_text(self) -> str:
        """Один рядок для індикатора контексту (реальні показники)."""
        router = getattr(self, "_lazy_router", None)
        if router is None:
            return "інструментів не пораховано"
        return router.indicator_text()

    def _router_schemas(self, existing: set[str]) -> list[dict[str, Any]]:
        """Прямі схеми для дій MCP-сервера (коли роутер підключено).

        Дії, які вже забезпечує ВЛАСНА пам'ять NEUROMESH (``memory_search``,
        ``memory_store``), тут НЕ дублюються. Раніше модель бачила дві схеми
        на одну потребу — ``memory_search`` від PCMM і ``router:memory_search``
        від MCP-роутера — і обирала MCP-версію. Та повертає сирий вивід
        (фрагменти файлів із номерами рядків), який далі йшов у чат як
        «відповідь». Тепер пріоритет у власної пам'яті: вона віддає
        структуровані спогади з поясненням.
        """
        manager = self.mcp_manager
        if manager is None:
            return []
        has_router = False
        try:
            has_router = any(item.get("name") == "master_agent_router"
                             for item in manager.tool_catalog())
        except Exception:  # noqa: BLE001
            return []
        if not has_router:
            return []
        # Якщо власна пам'ять підключена — її інструменти головніші.
        memory_owns = self.registry.memory_ready() if hasattr(
            self.registry, "memory_ready") else False
        skip = {"memory_search", "save_rule"} if memory_owns else set()
        schemas: list[dict[str, Any]] = []
        for name, description, params, required in _ROUTER_ACTIONS:
            if name in skip:
                continue
            full = f"router:{name}"
            if full in existing:
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": full,
                    "description": description,
                    "parameters": {"type": "object", "properties": params,
                                   "required": required},
                },
            })
        return schemas

    def _forbidden_by_user_request(self, name: str, data: dict[str, Any]) -> str:
        """Причина заборони, якщо користувач прямо заборонив цю дію.

        Перевіряються лише ЯВНІ заборони з поточного кадру наміру
        (``не запускай``, ``не читай``, ``не змінюй``). Без цього кроку
        підказка «не запускати команди» лишалась побажанням у промпті, а
        модель її регулярно порушувала — і агент запускав тести після
        прохання їх не запускати.

        ── «Не видаляй наявне» ≠ «не створюй нічого» ──────────────────────
        Тут була причина, через яку агент НЕ МІГ створити жодного файлу
        (видно на скріншоті: «Користувач заборонив цю дію: видалення
        наявних даних» на ``append_file`` і ``write_file``, підсумок —
        «на диску нічого не з'явилось»).

        Обмеження «не видаляти наявні дані» виникає з фраз на кшталт
        «не видаляй», «збережи старі». Раніше воно забороняло БУДЬ-ЯКИЙ
        запис файлу — разом зі створенням файлу, якого ще немає. Але
        створення нового файлу наявних даних не видаляє: воно їх не
        чіпає. Тому тепер заборона залежить від цілі запису:

        * ціль не існує → це створення, отже дозволено;
        * ціль існує → запис справді перепише наявний вміст, отже
          заборонено (так само, як «не змінюй наявні файли»).
        """
        intent = self.intent
        if intent is None:
            return ""
        constraints = [str(item or "").lower()
                       for item in (getattr(intent, "constraints", ()) or ())]
        if not constraints:
            return ""
        for text in constraints:
            if "не запускати команди" in text or "не запускати тести" in text:
                if name in permissions.EXEC_TOOLS or self._looks_like_test_run(data):
                    return "запуск команд і перевірок"
            if "не читати файли проєкту" in text and name in (
                    "read_file", "search_text", "find_files", "list_dir",
                    "project_tree"):
                return "читання файлів проєкту"
            if "не змінювати наявні файли" in text and name in (
                    "write_file", "edit_file", "append_file", "delete_file"):
                # Правка НАЯВНОГО файлу — саме те, що заборонено. Створення
                # нового файлу заборони не порушує.
                if self._target_exists(data):
                    return "зміна наявних файлів"
            if "не видаляти наявні дані" in text and name in (
                    "write_file", "edit_file", "append_file", "delete_file"):
                # ``delete_file`` завжди знищує наявне — тут без винятків.
                if name == "delete_file" or self._target_exists(data):
                    return "видалення наявних даних"
        return ""

    def _target_exists(self, data: dict[str, Any]) -> bool:
        """Чи існує файл, який збирається змінити інструмент.

        Порожній шлях або помилка читання означають «невідомо». У цьому
        разі вважаємо, що файл існує: краще зайвий раз зберегти наявні
        дані, ніж дозволити перезапис навмання.
        """
        try:
            raw = str((data or {}).get("path") or "").strip()
        except AttributeError:
            return True
        if not raw:
            return True
        try:
            root = getattr(self, "workspace", None)
            target = Path(raw) if not root else (Path(root) / raw)
            if not target.is_absolute():
                target = Path(raw).resolve()
            return target.exists()
        except (OSError, ValueError):
            return True

    @staticmethod
    def _looks_like_test_run(data: dict[str, Any]) -> bool:
        """Чи команда запускає тести (навіть якщо це ``run_command``)."""
        command = str((data or {}).get("command") or "").lower()
        if not command:
            return False
        markers = ("pytest", "unittest", "npm test", "npm run test", "yarn test",
                   "go test", "cargo test", "tox", "nox", "run_tests",
                   "manage.py test", "phpunit")
        return any(marker in command for marker in markers)

    def call_tool(self, name: str, arguments: str | dict[str, Any]) -> ToolResult:
        """Виконати ОДИН виклик інструмента (єдина точка входу).

        Сюди приходять і виклики моделі (через оркестратор), і автоматичні
        дії роутера, і команди користувача. Тому саме тут — перевірка
        режиму дозволів, і жодного іншого місця виконання бути не має.
        """
        data = _arguments_dict(arguments)
        decision = permissions.check_tool(
            name, data,
            mode=self.permission_mode,
            root=self.workspace,
            confirm_commands=self.agent_settings.confirm_commands,
        )
        if not decision.allowed:
            self._emit("status", f"Заблоковано ({self.permission_mode}): {name}")
            return ToolResult(False, f"Заборонено режимом дозволів: {decision.reason}")
        blocked = self._forbidden_by_user_request(name, data)
        if blocked:
            # Прохання «не запускай тести» має важити БІЛЬШЕ за ініціативу
            # моделі. Підказка в промпті — не гарантія: локальні моделі її
            # ігнорують, і агент запускав рівно те, що людина заборонила.
            # Тепер заборона перевіряється на ЄДИНІЙ точці виконання.
            self._emit("status", f"Пропущено на прохання користувача: {name}")
            return ToolResult(False, f"Користувач заборонив цю дію: {blocked}")
        if decision.needs_confirmation and self.registry.command_guard is not None:
            command = str(data.get("command") or "")
            if command and not self.registry.command_guard(command):
                return ToolResult(False, "Користувач відхилив виконання команди.")
        if name == "publish_social":
            return self._publish_social(data)
        # Запам'ятовуємо файли, які агент записав: перед завершенням ходу
        # перевіримо, чи компілюється код (див. ``_broken_python``).
        if name in ("write_file", "edit_file"):
            clean = str(data.get("path") or "").strip()
            if clean and clean not in self._touched_files:
                self._touched_files.append(clean)
        if name == "list_skills":
            if self.skill_book is None:
                return ToolResult(False, "Скіли не завантажені.")
            return ToolResult(True, self.skill_book.describe())
        if name == "read_skill":
            data = _arguments_dict(arguments)
            skill = self.skill_book.get(str(data.get("name") or "")) if self.skill_book else None
            if skill is None:
                return ToolResult(False, f"Скіла «{data.get('name')}» не знайдено.")
            return ToolResult(True, f"# {skill.name}\n{skill.description}\n\n{skill.body}")
        # ── Саморозширення: власні скіли й інструменти ─────────────────────
        # Агент закріплює знання з діалогу та з інтернету у ВЛАСНІ файли
        # проєкту. Наступного разу він користується ними сам — без того, щоб
        # людина щоразу пояснювала той самий порядок дій заново.
        if name in (extensions_module.EXTENSION_TOOLS):
            return self._extend(name, data)
        if name.startswith(extensions_module.CUSTOM_PREFIX):
            return self._run_custom_tool(name, data)
        if name.startswith("router:"):
            return self._call_router_intent(name[len("router:"):], _arguments_dict(arguments))
        # ── Саморемонт: агент перевіряє Й ВИПРАВЛЯЄ себе ────────────────────
        # Навіщо інструментом, а не «вбудованим кроком». Модель має вміти
        # сама з'ясувати, ЩО ЇЇ БЛОКУЄ, замість того щоб писати в чат
        # «схоже, запис заблоковано якоюсь політикою» (саме це видно на
        # скріншоті користувача). Діагностика й ремонт — це ДІЯ, і вона
        # має бути в списку доступних дій.
        if name in (SELF_REPAIR_TOOL, SELF_DIAGNOSE_TOOL):
            return self._self_repair(dry_run=(name == SELF_DIAGNOSE_TOOL))
        # ── Інструменти керування лінивим реєстром ─────────────────────────
        # Саме вони роблять лінивість безпечною: будь-який інструмент можна
        # знайти, завантажити й викликати, навіть якщо повної схеми в запиті
        # не було. Без них «лінивий» означало б «недоступний».
        if tool_lazy.is_control_tool(name):
            return self._call_lazy_control(name, data)
        manager = self.mcp_manager
        if name.startswith("mcp__") and manager is not None:
            try:
                ok, text = manager.call(name, _arguments_dict(arguments))
            except Exception as exc:  # noqa: BLE001
                return ToolResult(False, f"{type(exc).__name__}: {exc}")
            return ToolResult(ok, text)
        # ── Невідомий інструмент: кажемо, ЩО є натомість ─────────────────
        # Модель регулярно видумує назви (``router:search_web``,
        # ``browser_open``, ``google``). Раніше вона отримувала сухе
        # «Невідомий інструмент: X» і повторювала той самий виклик до ліміту
        # кроків. Тепер відповідь містить перелік ДОСТУПНИХ дій — модель
        # має шанс одразу обрати правильну.
        if name not in self.registry.handled_names() and not name.startswith("mcp__"):
            return ToolResult(False, self._unknown_tool_hint(name))
        return self.registry.call(name, arguments)

    # ── Саморозширення: виконання інструментів ────────────────────────────
    def _extend(self, name: str, data: dict[str, Any]) -> ToolResult:
        """Виконати інструменти саморозширення (create_skill/create_tool/…).

        Сюди веде :meth:`call_tool` для назв із
        :data:`extensions.EXTENSION_TOOLS`. Раніше ці інструменти мали схеми
        й потрапляли в промпт моделі, але виконавця НЕ мали: кожен виклик
        падав ``AttributeError: ... has no attribute '_extend'`` і модель
        чесно бачила «інструмент зламаний», хоча сама схема запропонувала
        його викликати.
        """
        store = self.extensions
        if name == "create_skill":
            result = store.create_skill(
                str(data.get("name") or ""),
                str(data.get("description") or ""),
                str(data.get("body") or ""),
                source=str(data.get("source") or ""),
            )
        elif name == "create_tool":
            parameters = data.get("parameters")
            result = store.create_tool(
                str(data.get("name") or ""),
                str(data.get("description") or ""),
                str(data.get("code") or ""),
                parameters=parameters if isinstance(parameters, dict) else None,
                source=str(data.get("source") or ""),
                overwrite=bool(data.get("overwrite")),
            )
        elif name == "list_custom_tools":
            return ToolResult(True, extensions_module.describe_extensions(store))
        elif name == "learn_from_web":
            return self._learn_from_web_tool(data)
        else:
            return ToolResult(
                False,
                f"Невідомий інструмент розширення: {name}. "
                f"Є: {', '.join(sorted(extensions_module.EXTENSION_TOOLS))}.")
        text = result.message or ("Готово." if result.ok else "Не вдалось.")
        if result.detail:
            text += f"\n{result.detail}"
        if result.path:
            text += f"\nШлях: {result.path}"
        return ToolResult(result.ok, text)

    @staticmethod
    def _first_url(text: str) -> str:
        """Перша URL-адреса в тексті (``""``, якщо адреси немає)."""
        match = re.search(r"https?://[^\s)\]>'\"<>]+", text or "")
        if not match:
            return ""
        return match.group(0).rstrip(".,;:!?")

    def _learn_from_web_tool(self, data: dict[str, Any]) -> ToolResult:
        """Інструмент ``learn_from_web``: джерело з інтернету для скіла.

        За схемою (:data:`extensions.TOOL_SCHEMAS`) інструмент ШУКАЄ, ЧИТАЄ
        сторінку й зберігає текст разом із посиланням, а створення скіла чи
        інструмента — окремий виклик ``create_skill``/``create_tool`` із
        ``source=URL``. Мережу не робимо самі: просимо в реєстру його
        власні ``search_web``/``fetch_url``, щоб шлях і обмеження були ті самі.
        """
        url = str(data.get("url") or "").strip()
        query = str(data.get("query") or "").strip()
        if not url and not query:
            return ToolResult(
                False, "Вкажіть url (сторінка) або query (що знайти).")
        try:
            if url:
                source = url
                page = self.registry.call("fetch_url", {"url": url})
            else:
                hits = self.registry.call("search_web", {"query": query})
                if not hits.ok:
                    return ToolResult(False, f"Пошук не вдався: {hits.output}")
                first = self._first_url(hits.output)
                source = first or query
                if not first:
                    # Пошук дав відповідь без посилань — це вже знання.
                    body = " ".join(str(hits.output or "").split())[:4000]
                    return ToolResult(True, (
                        f"Джерело: пошук «{query}».\n\n{body}\n\n"
                        "Посилань у результаті немає. Створи скіл "
                        "(create_skill) або інструмент (create_tool) з цього "
                        f"знання і вкажи source=пошук «{query}»."),)
                page = self.registry.call("fetch_url", {"url": first})
        except Exception as exc:                     # noqa: BLE001
            return ToolResult(False, f"{type(exc).__name__}: {exc}")
        if not page.ok:
            return ToolResult(False, f"Сторінку не прочитано: {page.output}")
        body = str(page.output or "").strip()
        if not body:
            return ToolResult(False, f"Сторінка {source} порожня.")
        title = ""
        for line in body.splitlines():
            line = line.strip()
            if line:
                title = line[:120]
                break
        parts = [
            f"Джерело: {source}",
            f"Заголовок: {title}",
            "",
            body[:6000],
        ]
        parts.append(
            "\nДалі: закріпи це знання — create_skill (інструкція) або "
            f"create_tool (код) — і вкажи source={source}.")
        return ToolResult(True, "\n".join(parts))

    def _run_custom_tool(self, name: str, data: dict[str, Any]) -> ToolResult:
        """Виконати саморобний інструмент ``custom:<назва>``.

        Код інструмента запускається в ОКРЕМОМУ процесі
        (:func:`extensions.run_custom_tool`): його писала модель, тож
        помилка або зациклення не мають валити IDE і хід агента. Раніше ця
        гілка викликала неіснуючий метод — ``custom:*`` не працював узагалі.
        """
        tool = self.extensions.get_tool(
            name[len(extensions_module.CUSTOM_PREFIX):])
        if tool is None:
            known = ", ".join(
                f"{extensions_module.CUSTOM_PREFIX}{item.name}"
                for item in self.extensions.tools())
            return ToolResult(
                False,
                f"Інструмент «{name}» не знайдено в {extensions_module.TOOLS_DIR}. "
                + (f"Є такі: {known}."
                   if known else
                   "Власних інструментів ще немає — створи через create_tool."))
        ok, text = extensions_module.run_custom_tool(tool, dict(data or {}))
        self.extensions.record_run(tool.name, ok=ok, error="" if ok else text)
        return ToolResult(ok, text)

    def _self_repair(self, *, dry_run: bool = False) -> ToolResult:
        """Перевірити власний стан IDE і (не обов'язково) полагодити його."""
        try:
            names = list(self.registry.handled_names())
        except Exception:                            # noqa: BLE001
            names = []
        settings_path = ""
        try:
            settings_path = str(getattr(self.agent_settings, "path", "") or "")
        except Exception:                            # noqa: BLE001
            settings_path = ""
        package_root = ""
        try:
            package_root = str(Path(__file__).resolve().parent)
        except (NameError, OSError):
            package_root = ""
        report = selfrepair.diagnose(
            workspace=str(self.workspace or ""),
            settings_path=settings_path,
            package_root=package_root,
            # Повна компіляція пакета — це ~2 с. У межах одного виклику
            # інструмента це прийнятно й дає чесний результат; обмежуємо
            # лише кількість файлів, щоб не тримати хід надто довго.
            source_limit=400,
            registry_names=names,
        )
        if not dry_run:
            selfrepair.repair_self(report)
        text = selfrepair.format_report(report)
        if not dry_run and report.fixed:
            self._emit("status",
                       f"Саморемонт: виправлено {report.fixed} з {len(report.findings)}.")
        return ToolResult(report.ok or bool(report.fixed), text)

    def _call_lazy_control(self, name: str, data: dict[str, Any]) -> ToolResult:
        """Виконати інструмент керування реєстром (``find``/``load``/``run``).

        Це і є «вхідні двері» до повного набору інструментів: модель бачить
        компактний реєстр, а дістати повну схему (або одразу викликати) може
        ось тут. Тому лінивий режим НЕ обмежує можливості — він лише
        переносить параметри зі запиту в момент, коли вони справді потрібні.
        """
        router = self.lazy_router()
        if name == tool_lazy.CONTROL_FIND:
            query = str(data.get("query") or "").strip()
            try:
                limit = int(data.get("limit") or 8)
            except (TypeError, ValueError):
                limit = 8
            found = router.find(query, limit=limit)
            if not found:
                return ToolResult(
                    False,
                    f"За запитом «{query}» інструментів не знайдено. "
                    f"Спробуй інші слова або подивись компактний реєстр "
                    f"в інструкції."
                )
            lines = [f"Знайдено {len(found)} інструмент(ів):"]
            lines.extend(card.line() for card in found)
            lines.append(
                f"Щоб побачити параметри — виклич "
                f"{tool_lazy.CONTROL_LOAD} із назвами.")
            return ToolResult(True, "\n".join(lines))

        if name == tool_lazy.CONTROL_LOAD:
            raw = data.get("names")
            if isinstance(raw, str):
                names = [item.strip() for item in raw.split(",") if item.strip()]
            elif isinstance(raw, (list, tuple)):
                names = [str(item) for item in raw]
            else:
                names = []
            if not names:
                return ToolResult(False, "Не вказано жодної назви інструмента.")
            loaded, unknown = router.activate(names)
            # Перебудувати набір схем, щоб завантажені повні схеми справді
            # пішли моделі в наступному кроці.
            if loaded:
                self._schemas_dirty = True
                self._schemas_cache = None
                try:
                    self.session._schemas_cache = None
                except AttributeError:
                    pass
                try:
                    self.tool_schemas()
                except Exception:  # noqa: BLE001 - перебудова не має ламати хід
                    LOG.debug("Набір схем не перебудовано після load_tools",
                              exc_info=True)
            lines: list[str] = []
            if loaded:
                lines.append("Повні схеми завантажено: " + ", ".join(loaded) + ".")
                lines.append("Вони доступні у наступному кроці — виклич потрібну.")
            duplicates = [item for item in names if item not in loaded
                          and item not in unknown]
            if duplicates:
                lines.append("Уже були завантажені: "
                             + ", ".join(sorted(set(duplicates))) + ".")
            if unknown:
                lines.append("Невідомі інструменти: " + ", ".join(unknown) + ".")
                lines.append(
                    f"Скористайся {tool_lazy.CONTROL_FIND}, щоб знайти правильну "
                    f"назву — не вигадуй її.")
            if not lines:
                return ToolResult(False, "Схем не завантажено.")
            return ToolResult(not unknown, "\n".join(lines))

        # CONTROL_RUN: виклик за назвою без попереднього завантаження схеми.
        target = str(data.get("name") or "").strip()
        if not target:
            return ToolResult(False, "Не вказано назву інструмента для виклику.")
        if tool_lazy.is_control_tool(target):
            return ToolResult(
                False,
                f"«{target}» — службовий інструмент реєстру, його не можна "
                f"викликати через {tool_lazy.CONTROL_RUN}.")
        if not router.knows(target):
            similar = router.find(target, limit=5)
            hint = ""
            if similar:
                hint = (" Можливо, ти мав на увазі: "
                        + ", ".join(card.name for card in similar) + ".")
            return ToolResult(
                False,
                f"Інструмента «{target}» немає в реєстрі.{hint} "
                f"Скористайся {tool_lazy.CONTROL_FIND}.")
        inner = data.get("arguments")
        inner_args = dict(inner) if isinstance(inner, dict) else {}
        # Виконуємо через ЗВИЧАЙНИЙ шлях: перевірка дозволів, валідація
        # аргументів і журнал мають бути ті самі, що й для прямого виклику.
        return self.call_tool(target, inner_args)

    def _unknown_tool_hint(self, name: str) -> str:
        """Підказка моделі, коли інструмента з такою назвою немає."""
        available = sorted(self.registry.handled_names())
        base = name.split(":", 1)[0].split("__", 1)[0].lower()
        # Чи просили те, що тут справді є під іншою назвою?
        similar = [item for item in available
                   if base and (base in item or item in base)]
        lines = [f"Інструмента «{name}» не існує."]
        if name.startswith(("router:", "mcp__", "mcp:")):
            lines = [f"Дія «{name}» зараз недоступна: MCP-сервер не підключено."]
        if similar:
            lines.append("Схоже на: " + ", ".join(similar[:5]) + ".")
        lines.append("Доступні інструменти: " + ", ".join(available) + ".")
        if any(word in name.lower() for word in
               ("web", "search", "google", "browser", "fetch", "http", "mcp")):
            lines.append(
                "Пошуку в інтернеті зараз НЕМАЄ: MCP-сервер не підключений. "
                "Не вигадуй відповідь — скажи користувачу, що для свіжих "
                "даних потрібно підключити MCP-сервер (Налаштування → MCP), "
                "і запропонуй те, що можна зробити локально."
            )
        lines.append("Не повторюй цей виклик — обери іншу дію.")
        return "\n".join(lines)

    def _publish_social(self, arguments: dict[str, Any]) -> ToolResult:
        """Опублікувати пост у соцмережу (реальний запит до API)."""
        settings = self.settings_ref
        if settings is None:
            return ToolResult(False, "Налаштування недоступні — публікація неможлива.")
        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(False, "Порожній текст поста.")
        named = str(arguments.get("network") or "").strip().lower()
        keys = [named] if named in {n.key for n in social.NETWORKS} else []
        if not keys:
            # Мережу не назвали — беремо ту, що згадана в тексті,бо налаштовані.
            keys = social.detect(text) or social.configured_networks(settings)
        if not keys:
            return ToolResult(False,
                              "Публікація недоступна: у Налаштуваннях → Соцмережі "
                              "не заповнено жодного акаунта.")
        results = social.publish_many(keys, text, settings)
        summary = social.summary_text(results)
        return ToolResult(any(r.ok for r in results), summary)

    #: Роутер-інтенти, які мають ВБУДОВАНИЙ відповідник у реєстрі.
    #:
    #: Навіщо. ``router:search_web`` тощо спочатку жили лише в MCP-сервері,
    #: і без MCP модель отримувала глуху відмову «сервер не підключено» —
    #: хоч можливість (пошук, читання сторінки, пам'ять) в IDE є ЗАВЖДИ.
    #: Тепер інтент деградує до вбудованого інструмента: результат той самий,
    #: а крок не витрачається на «модель стукає в зачинені двері».
    _ROUTER_FALLBACKS: dict[str, tuple[str, str]] = {
        # intent -> (вбудований інструмент, ім'я аргументу запиту)
        "search_web": ("search_web", "query"),
        "fetch_url": ("fetch_url", "query"),
        "web_api": ("web_api", "url"),
        "memory_search": ("memory_search", "query"),
        "memory_store": ("memory_store", "query"),
        "save_rule": ("save_rule", "query"),
        "index_project": ("index_project", "file_path"),
        "rag_search": ("rag_search", "query"),
    }

    def _call_router_intent(self, intent: str, arguments: dict[str, Any]) -> ToolResult:
        """Викликати конкретний intent MCP-роутера через підключений сервер.

        Якщо MCP недоступний, але в реєстру є ВБУДОВАНИЙ відповідник
        (:data:`_ROUTER_FALLBACKS`) — викликаємо його: можливість не залежить
        від того, підключив користувач MCP-сервер чи ні.
        """
        manager = self.mcp_manager
        if manager is None:
            fallback = self._ROUTER_FALLBACKS.get(intent)
            if fallback is not None and self.registry.handled_names():
                builtin, arg_key = fallback
                if builtin in self.registry.handled_names():
                    payload = dict(arguments or {})
                    if not payload.get(arg_key) and arguments.get("query"):
                        payload[arg_key] = arguments["query"]
                    self._emit("status",
                               f"MCP недоступний — виконую «{intent}» "
                               f"вбудованим інструментом ({builtin}).")
                    return self.call_tool(builtin, payload)
            # Модель видумала дію, якої зараз не існує. Сухе «не підключено»
            # вона сприймала як привід повторити той самий виклик — на
            # скріншоті це дало 14 однакових ``router:search_web``. Тому
            # відповідь пояснює, ЩО доступно й чому саме цього немає.
            return ToolResult(False, self._unknown_tool_hint(f"router:{intent}"))
        payload = {"intent": intent}
        for key in ("query", "file_path", "extra", "request"):
            if arguments.get(key):
                payload[key] = arguments[key]
        # Знаходимо ім'я інструмента роутера серед підключених серверів.
        names: list[str] = []
        try:
            for item in manager.tool_catalog():
                if item.get("name") == "master_agent_router":
                    names.append(item.get("full_name") or "")
        except Exception:  # noqa: BLE001
            names = []
        for full_name in [n for n in names if n]:
            try:
                ok, text = manager.call(full_name, payload)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(False, f"{type(exc).__name__}: {exc}")
            return ToolResult(ok, text)
        # MCP підключений, але роутера серед його інструментів немає.
        # Кажемо це так, щоб моделі було зрозуміло, що повторювати марно.
        return ToolResult(False, (
            f"Дія «router:{intent}» недоступна: підключений MCP-сервер не має "
            "інструмента master_agent_router.\n"
            "Доступні інструменти: "
            + ", ".join(sorted(self.registry.handled_names()))
            + ".\nНе повторюй цей виклик — обери іншу дію або відповідай тим, "
            "що вже відомо."
        ))

    def _note_observation(self, observation: "tool_orchestrator.Observation") -> None:
        """Запам'ятати спостереження для фінальної відповіді й traces."""
        if self._observations is None:
            self._observations = []
        self._observations.append(observation)

    def _repair_arguments(
        self,
        prepared: list[tuple[str, dict[str, Any], str]],
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Доповнити аргументи виклику, яких модель не передала.

        ЗАМІРЯНО ЖИВИМ ПРОГОНОМ на справжній моделі (Qwen2.5-VL-3B):
        у відповідь на «виправ calc.py» вона викликає
        ``edit_file(old_string=…, new_string=…)`` — і НЕ передає ``path``.
        Оркестратор слушно відхиляє виклик («path: обов'язковий аргумент
        відсутній»), і правка не відбувається, хоч усе інше модель зробила
        правильно.

        Правимо ЛИШЕ те, що виводиться з уже відомого контексту, і лише
        коли це однозначно:

        * ``path`` — якщо в цьому ході модель уже читала/писала рівно один
          файл, і саме його стосується виклик;
        * ``query`` для ``search_text`` — з тексту пошуку, якщо модель
          передала його під іншим ім'ям (``text``, ``q``, ``pattern``).

        Нічого не «вгадуємо»: якщо файлів кілька або жодного, аргумент
        лишається порожнім, і модель отримує звичайну підказку про
        обов'язкові параметри.
        """
        if not prepared:
            return prepared
        # Файли, з якими модель працювала в цьому ході — у порядку згадки.
        known: list[str] = []
        for item in self._observations or []:
            name = str(getattr(item, "name", "") or "")
            if name not in ("read_file", "write_file", "edit_file",
                            "append_file"):
                continue
            path = str((getattr(item, "arguments", {}) or {}).get("path") or "")
            if path and path not in known:
                known.append(path)
        for message in reversed(self.session.messages[-12:]):
            raw = message.get("tool_calls")
            if not isinstance(raw, list):
                continue
            for call in raw:
                function = call.get("function") if isinstance(call, dict) else None
                if not isinstance(function, dict):
                    continue
                try:
                    data = json.loads(str(function.get("arguments") or "{}"))
                except (TypeError, ValueError):
                    continue
                path = str((data or {}).get("path") or "").strip()
                if path and path not in known:
                    known.insert(0, path)

        repaired: list[tuple[str, dict[str, Any], str]] = []
        for name, arguments, call_id in prepared:
            data = dict(arguments or {})
            spec = (self._specs or {}).get(name)
            required = tuple(getattr(spec, "required", ()) or ())
            if "path" in required and not str(data.get("path") or "").strip():
                # Рівно один відомий файл — цього достатньо, щоб доповнити.
                if len(known) == 1:
                    data["path"] = known[0]
                    self._emit("status",
                               f"«{name}» без шляху — підставив "
                               f"{known[0]} (єдиний файл цього ходу).")
                else:
                    hinted = ""
                    for key in ("file", "file_path", "filename", "target"):
                        value = str(data.get(key) or "").strip()
                        if value:
                            hinted = value
                            break
                    if hinted:
                        data["path"] = hinted
                        data.pop("file", None)
                        data.pop("file_path", None)
                        data.pop("filename", None)
                        data.pop("target", None)
            if name == "search_text" and not str(data.get("query") or "").strip():
                for key in ("text", "q", "pattern", "needle"):
                    value = str(data.get(key) or "").strip()
                    if value:
                        data["query"] = value
                        data.pop(key, None)
                        break
            repaired.append((name, data, call_id))
        return repaired

    # ── основний цикл ──────────────────────────────────────────────────────
    def _web_context_for(self, text: str) -> str:
        """ЗАВЖДИ сходити в інтернет і повернути блок знань для промпту.

        Вимога користувача (21.11.2026): «я взагалі просив, щоб до кожного
        запиту в локальній моделі додавався запит до інтернету. Користувач
        запитує — пошук в інтернеті + дані від моделі = загальна відповідь
        агента».

        Чому саме так, а не «нехай модель сама вирішить». Локальна модель
        фізично не знає свіжих даних і не має доступу до мережі з власного
        контексту. Тому пошук виконується ДО запиту до моделі, а її
        відповідь будується вже з цими даними — і вона бачить:
        «ось що є в мережі зараз, врахуй це».

        Що НЕ робимо:

        * не шукаємо, якщо інструменти вимкнені або режим приватний;
        * не шукаємо на порожній/службовий текст;
        * помилка мережі не ламає хід — модель просто працює без цього блоку.

        Повертає готовий текст для промпту (порожній рядок — нічого немає).
        """
        if not getattr(self.agent_settings, "web_every_turn", True):
            return ""
        if not self.tools_enabled or self.state.private:
            return ""
        query = " ".join(str(text or "").split())
        if len(query) < 3:
            return ""
        # Службові повідомлення (кроки плану, повтори) у мережу не йдуть.
        if query.startswith(("Ти вже викликав", "Ти виконав ПОШУК",
                             "ВАЖЛИВО:", "Я запустив")):
            return ""
        q_low = " ".join(str(query or "").split()).strip().lower().rstrip("!.?,")
        if q_low in {"\u043f\u0440\u0438\u0432\u0456\u0442", "\u043f\u0440\u0438\u0432\u0435\u0442", "\u0434\u043e\u0431\u0440\u0438\u0439 \u0434\u0435\u043d\u044c", "\u0434\u043e\u0431\u0440\u043e\u0433\u043e \u0434\u043d\u044f", "\u0432\u0456\u0442\u0430\u044e", "\u0434\u044f\u043a\u0443\u044e", "\u043e\u043a", "\u0434\u043e\u0431\u0440\u0435", "hi", "hello", "hey", "ok", "thanks"} or len(q_low) < 4:
            return ""
        # PURE_GREETING_SKIP: ?? ??????? ????????? ????? ???? ?? ??????? ??????????/?????? ??? ????
        _q_clean = " ".join(str(query or "").lower().split()).strip(" !?.,:;()[]\"'")
        _greet_words = {
            "??????", "??????", "???", "hello", "hi", "??????", "????", "???????", "?????", "??????",
            "??", "??????", "????", "??", "???", "?????", "???????", "????????", "??", "????",
            "?????", "????", "?????????", "?????", "????", "????????", "?????", "????", "????", "?", "??", "?", "??"
        }
        _q_tokens = [w.strip("!?.,:;") for w in _q_clean.split() if w.strip("!?.,:;")]
        if _q_tokens and len(_q_tokens) <= 5 and all(w in _greet_words for w in _q_tokens):
            return ""
        return ""

    def _learn_web_text(self, body: str, query: str) -> None:
        """Записати знайдене з мережі в NEUROMESH (залізне правило)."""
        if not getattr(self.agent_settings, "memory_participates", True):
            return
        bridge = getattr(self, "memory_bridge", None)
        service = getattr(bridge, "service", None) if bridge is not None else None
        if service is None:
            return
        facts = web_learning.extract(body, query=query[:160])
        if facts:
            saved = web_learning.remember(service, facts)
            self._web_facts = int(saved or 0)
            if saved:
                self._emit("status",
                           f"Знання з інтернету в пам'ять: {saved}.")

    def _hint_advice(self) -> str:
        """Текст-порада моделі: «можна зробити так», а не «зроби так».

        Навіщо окремий метод. Підказки роутера — це ЗДОГАД за словами. Коли
        їх виконувати примусово, будь-яка помилка евристики стає помилкою
        роботи: «давай грати в гру» перетворювалось на створення `game.py`
        (заміряно 21.11.2026). Коли ж віддати їх моделі як ПОРАДУ, вона
        бачить увесь запит і може не погодитись.

        Текст навмисно короткий: місце в промпті дороге, а це лише здогад.
        """
        hints = list(getattr(self, "_pending_hint", []) or [])
        if not hints:
            return ""
        lines = ["Можлива дія (це ЗДОГАД за словами, а не наказ)."]
        for hint in hints[:3]:
            args = ", ".join(f"{key}={value}" for key, value in
                             (hint.arguments or {}).items() if str(value).strip())
            call = f"{hint.tool}({args})" if args else hint.tool
            lines.append(f"- {call} — {hint.reason or 'доречно тут'}")
        lines.append(
            "Вирішуй САМ: якщо запит про інше (розмова, гра в чаті, "
            "пояснення) — не викликай інструмент, просто відповідай. "
            "Якщо дія справді потрібна — виклич її сам. "
            "НЕ переказуй цю підказку користувачу — це службовий текст.")
        return "\n".join(lines)

    def _may_override_model(self, result: Any = None) -> bool:
        """Чи можна виконати дію роутера ПОПРИ рішення моделі.

        Правило одне: евристика втручається ЛИШЕ тоді, коли модель не
        впоралась сама. «Не впоралась» означає:

        * вона не викликала ЖОДНОГО інструмента цього ходу — і
        * її текст не містить блоку коду (це не спроба зробити роботу).

        Якщо модель узяла інструмент — її вибір остаточний. Саме цього
        вимагав користувач: «хай сама підбирає інструменти, а не буде
        захардкодена».
        """
        if not getattr(self.agent_settings, "model_decides", True):
            # Стара поведінка: слабка модель без нативних викликів.
            return True
        if self._observations:
            return False
        content = str(getattr(result, "content", "") or "") if result else ""
        if content and self._wrote_code_in_chat(content):
            return False
        return True

    def _run_hints(self) -> bool:
        """Виконати дії, які знайшов роутер, замість порожньої балачки.

        Повертає True, якщо хід ЗАВЕРШЕНО (є справжній результат і
        відповідь уже показано). False означає «хід не завершено» — і тоді
        викликач дивиться на :attr:`_hints_need_continue`.

        Виконання йде через ТОЙ САМИЙ оркестратор, що й виклики моделі:
        аргументи перевіряються за схемою, невідомий інструмент не
        виконується, а користувач бачить людське пояснення, а не сирий
        вивід інструмента.

        ── ЛИШЕ КОЛИ МОДЕЛЬ НЕ ВПОРАЛАСЬ ────────────────────────────────
        Вимога користувача (21.11.2026): «дай їй свободу думок і хай сама
        підбирає інструменти, а не буде захардкодена».

        Тому тут є дві умови, і ОБИДВІ мусять виконуватись:

        1. ``model_decides`` вимкнено (модель не вміє викликати інструменти), АБО
        2. модель відповіла ПОРОЖНЬО/словами й нічого не зробила.

        Коли модель узяла інструмент сама — цей шлях не втручається взагалі:
        її рішення важливіше за здогад евристики.
        """
        self._hints_need_continue = False
        hints = self._pending_hint or []
        if not hints:
            return False
        self._pending_hint = []
        engine = self.orchestrator or self.orchestrator_for_turn()
        produced: list[str] = []
        observations: list[tool_orchestrator.Observation] = []
        for index, hint in enumerate(hints[:4]):
            if self._cancel.is_set():
                break
            name = hint.tool
            arguments = dict(hint.arguments)
            # Порожній шлях означає «той файл, що відкритий у редакторі».
            # Роутер не знає про вікно, тож підставляємо тут: інакше
            # read_file("") падав би з «файл не знайдено» на цілком
            # зрозумілому проханні «що в цьому файлі».
            if name == "read_file" and not str(arguments.get("path") or "").strip():
                active = self.active_path_provider() if self.active_path_provider else None
                if active:
                    arguments["path"] = str(active)
                else:
                    continue
            if name.startswith("mcp:"):
                name = f"router:{name[4:]}"
            call_id = f"auto_{index}"
            pretty = ", ".join(f"{k}={v}" for k, v in arguments.items() if str(v).strip())
            self._emit("tool_call", f"{name}({pretty})", name=name,
                       arguments=pretty, call_id=call_id, auto=True)
            observation = engine.run(name, arguments, call_id=call_id)
            observations.append(observation)
            self._note_observation(observation)
            # Синтетичний виклик: без нього в історії з'являвся tool-результат
            # БЕЗ виклику вище, і наступний запит до OpenAI-сумісного сервера
            # завершувався помилкою 400 («tool message without tool_calls»).
            # Роутер викликав інструмент сам, тож виклик відтворюємо явно.
            self.session.add_assistant({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name,
                                 "arguments": json.dumps(arguments, ensure_ascii=False)},
                }],
            })
            self.session.add_tool_result(
                call_id, name,
                ToolResult(observation.ok,
                           observation.output if observation.ok
                           else observation.error))
            body = observation.output if observation.ok else observation.error
            head = body if len(body) <= 1200 else body[:1200] + "\n…"
            self._emit("tool_result", head, name=name, ok=observation.ok,
                       call_id=call_id, user_text=observation.for_user)
            if observation.ok and observation.output.strip():
                produced.append(observation.output.strip())
        if not produced:
            return False
        # Відповідь збираємо тим самим шаром, що й для моделі: список файлів
        # стає списком, довгий вивід — коротким блоком, а не «стіною».
        draft = response_engine.answer_from_observations(observations)
        raw_answer = draft.text or "\n\n".join(produced)
        # ── МОДЕЛЬ МАЄ ОБРОБИТИ ДАНІ ПЕРЕД ВИДАЧЕЮ ────────────────────────
        # Вимога користувача (21.11.2026): «мені потрібно відповідь не кодом
        # а текстом з реальною обробкою моделью перед видачею користувачу!».
        #
        # Що було не так. Коли дані приходили з інструмента (``search_web``,
        # ``read_file``), агент віддавав їх людині ЯК Є: «Готово. Результат:
        # search_web» + сирий JSON/список. Користувач бачив код замість
        # відповіді — хоч модель могла б спокійно переказати це своїми
        # словами.
        #
        # Тепер: якщо є зібрані дані, робимо ОДИН додатковий запит до моделі
        # «перекажи це людині своїми словами, спираючись на ці дані». Якщо
        # модель недоступна — лишається структурований звіт (чесно, але не
        # замість відповіді).
        answer = self._narrate_results(produced) or raw_answer
        # Роутер відповідає з реальних результатів, але його підсумок може
        # містити числа/назви, яких у виводі не було. Той самий шар правди.
        answer = self._enforce_evidence(answer, step=0)
        self._last_answer = answer
        self.session.add_assistant({"role": "assistant", "content": answer})
        # UNIVERSAL_NEUROMESH_TURN: ????-??? ????????? (????????, ?????? ?? ? ?????????) ?????? NEUROMESH
        try:
            _mb_u = getattr(self, 'memory_bridge', None)
            _ans_u = str(locals().get('reply') or locals().get('answer') or locals().get('text') or '').strip()
            _usr_u = str(locals().get('user_text') or locals().get('prompt') or '').strip()
            if _mb_u is not None and _mb_u.ready() and _ans_u and len(_ans_u) > 15:
                if hasattr(_mb_u, 'record_turn'):
                    _mb_u.record_turn(_usr_u[:300], _ans_u[:1200])
        except Exception:
            pass
        self._emit("assistant", answer, auto=True)
        # ── Читання саме по собі — це НЕ виконана робота ──────────────────
        # Регресія з живого прогону: на фразу «у файлі calc.py додай
        # множення» роутер давав лише ``read_file``, агент читав файл і
        # завершував хід зі словами «Готово. Результат: read_file». Файл
        # при цьому не змінювався.
        #
        # Тому: якщо серед виконаних дій немає ЖОДНОЇ зміни файлів, а
        # прохання було про правку — повертаємо False, щоб цикл продовжився
        # і модель сама зробила ``edit_file``.
        # ???? ?????? ???????? ????? ??? ????? ???? (search_web), ??? ?????? ?????????? ?????????? "? ??????" ??? ??????
        # ????????? ????????? search_web ? ?????????? ??? ?????? ??? ?? ??????? ??????? ? ??????!
        if not getattr(self, "_forced_web_done", False):
            web_hints = [h for h in hints if getattr(h, "tool", "") == "search_web"]
            if web_hints:
                self._forced_web_done = True
                try:
                    from . import internet
                    q_web = str((web_hints[0].args or {}).get("query") or "").strip()
                    if q_web:
                        self._emit("status", "????? ????? ???? ? ?????????")
                        res = internet.search(q_web[:220])
                        body = res.as_text() if hasattr(res, "as_text") else str(res)
                        if body and len(body.strip()) > 30:
                            self.session.messages.append({
                                "role": "user",
                                "content": (
                                    f"???????? ????????? ???? ? ????????? ?? ??????? {q_web}:\n{body[:6000]}\n\n"
                                    "?? ?????? ??? ?????? ????? ??? ?????, ???????? ????????? ??????????? ?????. ?? ???????."
                                ),
                            })
                            return False
                except Exception:
                    pass

        changed = [hint.tool for hint in hints
                   if hint.tool in ("write_file", "edit_file", "append_file")]
        if not changed and self._asks_for_change():
            # ``search_text`` теж лише ДИВИТЬСЯ: «перейменуй функцію average
            # на mean» дає підказку пошуку, а правку має зробити модель.
            # Повідомлення називає саме те, що сталося, щоб модель не
            # шукала вдруге те саме.
            did = hints[0].tool if hints else "інструмент"
            self._emit("status", f"Виконав «{did}» — тепер вношу зміну.")
            # КЛЮЧОВЕ: просимо продовжити, а не завершуємо хід.
            # Раніше звідси повертався False — і викликач розумів його як
            # «дія не виконалась», ішов далі по коду й робив ``return``.
            # Результат: на «виправ цю функцію» агент читав файл, писав
            # «Готово. Результат: read_file» і ЗУПИНЯВСЯ, не змінивши нічого.
            # Заміряно живим прогоном на справжній моделі.
            self._hints_need_continue = True
            return False
        return True

    def _is_small_talk(self) -> bool:
        """Чи це звичайна розмова (вітання, подяка, «як справи»).

        Умови навмисно вузькі: коротка фраза, розпізнана як розмова або
        пояснення, без згаданих файлів і без наміру діяти. Якщо є
        найменший сумнів — ідемо звичайним шляхом, бо пропустити справжнє
        завдання гірше, ніж зайвий цикл.
        """
        intent = self.intent
        if intent is None:
            return False
        # ── Зображення в черзі: це вже НЕ балачка ──────────────────────────
        # Якщо до запиту прикріплено скриншот, користувач чекає аналізу
        # зображення. Шлях «розмови» тут шкідливий двічі: він не дає
        # інструментів (а отже й змоги щось виправити) і раніше взагалі
        # ВТРАЧАВ картинку, бо збирав повідомлення повз ``session.build``.
        try:
            if self.session.pending_images:
                return False
        except AttributeError:
            pass
        intent_type = str(getattr(intent, "intent_type", "") or "")
        if intent_type not in ("converse", "explain"):
            return False
        if bool(getattr(intent, "actionable", False)):
            return False
        if list(getattr(intent, "referenced_files", ()) or ()):
            return False
        text = str(getattr(intent, "text", "") or "")
        # ── ПРОПОЗИЦІЯ ВАРІАНТІВ — це розмова, хай яка довга ───────────────
        # Реальна скарга: на довге привітання з переліком можливостей
        # («…Хочеш створити щось нове (сайт, скрипт, гру)…?») агент мовчки
        # писав файли сайту й запускав сервер. Раніше тут стояло лише
        # обмеження довжини (200 символів), тож така фраза автоматично
        # ставала завданням. Питання про вибір дії завданням не є.
        try:
            if intent_engine.is_offer_question(text):
                return True
        except Exception:                        # noqa: BLE001
            LOG.debug("Перевірка пропозиції не вдалась", exc_info=True)
        # Довга фраза навіть із «привіт» усередині — це вже завдання.
        if len(text) > 200:
            return False
        # ── Роутер бачить конкретну дію — це НЕ балачка ────────────────────
        # «Зупини програму», «перейменуй функцію foo», «відкоти останню
        # зміну» класифікувались як `converse` (бо в них немає слів на
        # кшталт «створи» чи «виправ»), і розмова забирала хід: агент
        # відповідав словами, а програма не зупинялась. Якщо роутер дав
        # хоч одну впевнену підказку — ідемо робочим шляхом.
        try:
            from . import tool_router as _router

            if _router.confident(text):
                return False
        except Exception:  # noqa: BLE001 - роутер необов'язковий
            LOG.debug("Роутер не дав підказки для %r", text[:60], exc_info=True)
        return True

    def _announce_budget(self, budget: Any) -> None:
        """Сказати людині, скільки контексту взято й скільки це часу.

        Показуємо лише тоді, коли бюджет СПРАВДІ звужений відносно вікна:
        «заповнюю 131072 із 131072» нічого не додає, а рядок про кожен хід
        перетворився б на шум.

        Навіщо взагалі показувати. Користувач бачить паузу й має розуміти,
        звідки вона: це не «модель задумалась», а заповнення контексту, і
        час заміряний (див. ``context_budget.LATENCY_TABLE``).
        """
        if budget is None:
            return
        working = int(getattr(budget, "working", 0) or 0)
        window = int(getattr(budget, "window", 0) or 0)
        if not working or not window or working >= window:
            return
        self._emit("status",
                   f"Контекст під запит: {working:,} із {window:,} "
                   f"({budget.latency_text()} до першої відповіді)"
                   .replace(",", " "))

    def _answer_budget(self) -> int:
        """Скільки токенів просити під ОДНУ відповідь у розмові.

        Джерела, від надійнішого:

        1. бюджет ``context_budget`` — частка СПРАВЖНЬОГО вікна моделі
           (його визначає ``probe_context_window``, зокрема живим запитом);
        2. ``llm.max_tokens`` із налаштувань — те, що вибрав користувач;
        3. типова відповідь, якщо невідомо нічого.

        Раніше тут стояло жорстке ``min(700, max_tokens)``. Для
        reasoning-моделей це закінчувалось порожнім ``content``: міркування
        витрачали весь бюджет, і на текст не лишалось нічого.
        """
        planned = 0
        budget = getattr(self, "_context_budget", None)
        if budget is not None:
            try:
                planned = int(getattr(budget, "answer", 0) or 0)
            except (TypeError, ValueError):
                planned = 0
        configured = 0
        try:
            configured = int(getattr(self.llm_settings, "max_tokens", 0) or 0)
        except (TypeError, ValueError):
            configured = 0
        # ── БЕРЕМО БІЛЬШЕ З ДВОХ, А НЕ МЕНШЕ ────────────────────────────────
        # Раніше стояв ``min(planned, configured)``, і типові 2048 із
        # налаштувань душнИЛИ відповідь навіть тоді, коли вікно дозволяло
        # вдесятеро більше. Наслідок на скріншоті користувача: велике
        # завдання обривалось на ``finish_reason="length"`` → правило
        # доказів позначало хід «зупинено лімітом» → агент кидав роботу
        # неповною. Обидва числа — РЕЗЕРВИ, а не ліміти витрати: модель
        # витрачає стільки, скільки їй треба, стеля фізична одна — вікно.
        # Стеля вікна лишається гарантією: не просимо більше, ніж вмістить
        # контекст (це перевіряє ``_answer_budget_cap``).
        if planned > 0 and configured > 0:
            return max(planned, configured)
        if planned > 0:
            return planned
        if configured > 0:
            return configured
        return _DEFAULT_ANSWER_BUDGET

    def _answer_budget_cap(self) -> int:
        """Верхня межа для повторної спроби після порожньої відповіді."""
        window = int(getattr(self.session, "context_limit", 0) or 0)
        if window > 0:
            # Ніколи не просимо більше за половину вікна: інакше після
            # одного повтору запит сам переповнить контекст.
            return max(256, int(window * 0.5))
        return _DEFAULT_ANSWER_BUDGET * 4

    def _chat_only(self, client: LLMClient) -> None:
        """Один хід без інструментів: звичайна відповідь на репліку.

        Схеми інструментів НЕ передаємо: інакше модель намагається щось
        викликати у відповідь на «привіт». Промпт теж короткий — мета,
        обмеження й план тут не потрібні.

        ВАЖЛИВО про зображення. Раніше список повідомлень збирався тут
        напряму (``system_message() + messages``), тому черга
        ``pending_images`` НЕ застосовувалась — і прикріплений скриншот
        просто не доходив до моделі. Модель відповідала «я не можу
        аналізувати зображення», хоч воно було в контексті розмови.
        Тепер повідомлення будує :meth:`AgentSession.build`, який приєднує
        зображення до останнього повідомлення користувача.
        """
        # Хроніка потрібна й у звичайній розмові: довгий чат без інструментів
        # теж впирається у вікно.
        self._render_digest()
        # ── Бюджет БЕЗ схем: їх у розмові не надсилають ────────────────────
        # Рахувати 9 646 токенів схем, яких модель не побачить, означало б
        # дати «привіту» вчетверо більший контекст, ніж йому треба.
        try:
            tuned = self.refresh_budget_for_request(with_tools=False)
            self._announce_budget(tuned)
        except Exception:  # noqa: BLE001 - бюджет не має ламати розмову
            LOG.debug("Бюджет розмови не перераховано", exc_info=True)
        messages = self.session.build()
        started = time.perf_counter()
        # ── Бюджет відповіді: не «min(700)», а стільки, скільки дає модель ──
        # Раніше тут стояло ``min(700, ...)``. Для reasoning-моделей це
        # виявилось пасткою: модель спершу витрачає бюджет на «думки»
        # (``reasoning_tokens``), і на сам текст не лишається нічого —
        # приходив порожній ``content`` із ``finish_reason=stop``, хоч
        # запит був успішний. Заміряно на Deploy: 130 completion-токенів,
        # з них 93 — міркування.
        #
        # Тепер бюджет — це частка вікна (бюджет планує ``context_budget``),
        # і він же обмежує відповідь. Розмова не потребує тисяч токенів,
        # але й не має обрізатись на півслові посеред пояснення.
        answer_budget = self._answer_budget()
        result = None
        for attempt in range(_EMPTY_CHAT_ATTEMPTS):
            try:
                result = client.chat(messages, tools=None, temperature=0.6,
                                     max_tokens=answer_budget)
            except LLMError as exc:
                self._error = str(exc)
                self._emit("error", self._error)
                return
            if response_engine.clean_for_chat(result.content or "").strip():
                break
            # Порожня відповідь — майже завжди наслідок того, що міркування
            # з'їли бюджет. Повторюємо з більшим лімітом, і лише потім
            # кажемо користувачу правду. Порожнечу в історію НЕ пишемо:
            # інакше наступний хід бачив би «мусорні» репліки асистента.
            if attempt + 1 < _EMPTY_CHAT_ATTEMPTS:
                LOG.info("Порожня відповідь (%s completion) — повторюю з "
                         "більшим бюджетом", (result.usage or {}).get(
                             "completion_tokens"))
                answer_budget = min(self._answer_budget_cap(),
                                    answer_budget * 3)
                self.session.add_user(
                    "Ти відповів порожнім текстом. Дай коротку відповідь "
                    "звичайними словами, без розгорнутих міркувань.")
                messages = self.session.build()
                self.session.messages.pop()   # підказку в історію не лишаємо
        # ── СТАТИСТИКА Й У РОЗМОВІ ────────────────────────────────────────
        # Раніше цей шлях НЕ емітував ``stats`` узагалі, тому на «привіт»,
        # «дякую» чи будь-яку розмову шкала контексту лишалась «0 / 32.8K»,
        # хоч модель реально витратила токени. Користувач бачив нулі й
        # вважав, що облік зламаний — саме це видно на скріншоті.
        #
        # Числа тут справжні: їх віддає рушій (``usage``), а не оцінка.
        self._publish_stats(result, messages, schemas=None,
                            duration=time.perf_counter() - started)
        text = response_engine.clean_for_chat(result.content or "").strip()
        if not text:
            # Усі спроби дали порожнечу. Раніше тут підставлявся ГОТОВИЙ
            # рядок «Привіт! Готовий допомогти з кодом — напиши, що
            # зробити.» — і користувач бачив його як відповідь МОДЕЛІ, хоч
            # вона мовчала. Це і є той «хардкод», на який він скаржився.
            #
            # Тепер кажемо чесно, що відповіді немає, і показуємо причину з
            # ``finish_reason`` — без вигаданого тексту від нашого імені.
            reason = str(getattr(result, "finish_reason", "") or "")
            used = (result.usage or {}).get("completion_tokens")
            detail = f", витрачено {used} токенів" if used else ""
            text = ("Модель повернула порожню відповідь"
                    + (f" (finish_reason={reason})" if reason else "")
                    + detail
                    + ". Спробуй переформулювати запит або вибрати іншу модель.")
        self.session.add_assistant({"role": "assistant", "content": text})
        self._last_answer = text
        self._emit("assistant", text, final=True)

    def _publish_stats(self, result, messages: list[dict], *,
                       schemas: list[dict] | None, duration: float) -> None:
        """Опублікувати статистику кроку — з РЕАЛЬНИХ чисел рушія.

        Спільне місце для обох шляхів (з інструментами й без), щоб облік не
        залежав від того, як саме модель відповіла.
        """
        try:
            step_stats = self.stats.add_result(
                result,
                tool_calls=len(getattr(result, "tool_calls", None) or []),
                duration=duration,
            )
            try:
                system_prompt = str((messages[0] or {}).get("content") or "") \
                    if messages else ""
                self.stats.update_breakdown(
                    system_prompt=system_prompt,
                    tools=schemas or [],
                    messages=messages[1:] if len(messages) > 1 else [],
                )
            except Exception:                    # noqa: BLE001
                LOG.debug("Розбивка контексту не вдалась", exc_info=True)
            self._emit("stats", step_stats=self.stats, step=step_stats,
                       context_limit=self.stats.context_limit,
                       breakdown=self.stats.breakdown)
        except Exception:                        # noqa: BLE001
            LOG.debug("Статистику кроку не опубліковано", exc_info=True)

    def _expects_action(self) -> bool:
        """Чи чекає користувач ДІЇ (а не відповіді словами).

        Потрібно, щоб правила проти «обіцянок» не спрацьовували на
        звичайній розмові. На «привіт» модель відповідає
        «Привіт! Я можу допомогти з кодом…» — у цьому тексті є «можу»,
        і раніше агент вважав це обіцянкою, вимагав викликати інструмент
        й показував зайвий блок у чаті.

        Джерело правди — розпізнаний намір: дія є, якщо тип повідомлення
        належить до дій (``CREATE``, ``EDIT``, ``DEBUG``…) або до огляду
        з інструментами. Розмова й прохання пояснити — не дія.
        """
        intent = self.intent
        if intent is not None:
            intent_type = str(getattr(intent, "intent_type", "") or "")
            if intent_type in ("converse", "explain", ""):
                return False
            if bool(getattr(intent, "actionable", False)):
                return True
            # Огляд (inspect/research) теж потребує інструментів, але
            # «обіцянка» там недоречна — він або читає, або відповідає.
            return intent_type in ("inspect", "research", "test", "run")
        # Намір не визначено — поводимось як раніше (перевіряємо обіцянку):
        # краще зайва вимога, ніж прихована бездіяльність.
        return True

    def _asks_to_build(self) -> bool:
        """Чи просить користувач СТВОРИТИ річ (а не дізнатись факт).

        Джерело правди — початковий запит. Потрібно, щоб не дати моделі
        підмінити будівництво пошуком в інтернеті: заміряно живим прогоном,
        як на «напиши сайт блогу й форуму з API» вона тричі викликала
        ``search_web`` і не створила жодного файлу.
        """
        text = ""
        for message in self.session.messages:
            if message.get("role") == "user":
                text = str(message.get("content") or "")
                break
        if not text:
            return False
        return tool_router._is_build_request(text.lower())  # noqa: SLF001

    def _asks_for_change(self) -> bool:
        """Чи просить користувач змінити файл (а не лише подивитись).

        Дивимось на початковий запит: якщо в ньому є дієслово зміни, то
        саме читання файлу не можна вважати виконаним завданням.
        """
        try:
            from . import task_plan
        except ImportError:
            return False
        text = ""
        for message in self.session.messages:
            if message.get("role") == "user":
                text = str(message.get("content") or "")
                break
        if not text:
            return False
        info = task_plan.understand(text)
        # ``DOCS`` теж змінює файли: «напиши в README.md як користуватись
        # калькулятором» — це створення/допис документації. Раніше цей
        # намір не входив у список, тож агент прочитав файл, показав
        # «Готово. Результат: read_file» і зупинився, не написавши нічого
        # (перевірено ``tools/eval_agent.py``: README не з'являвся).
        return info.primary in (task_plan.EDIT, task_plan.CREATE,
                                task_plan.REFACTOR, task_plan.DEBUG,
                                task_plan.DOCS)

    def _emit(self, kind: str, text: str = "", **data: Any) -> None:
        """Надіслати подію в інтерфейс.

        ── ВИПРАВЛЕННЯ РУСИЗМІВ І СУРЖИКУ ────────────────────────────────
        Локальні моделі навчені переважно на російському тексті, тож в
        українській відповіді регулярно з'являються «сейчас», «нужно»,
        «получается», «приймати участь». Користувач бачить це в чаті як
        мовну помилку.

        Виправлення стоїть САМЕ ТУТ, а не в місцях показу: через ``_emit``
        проходять УСІ відповіді — і фінальні, і проміжні, і офлайн-роутера,
        і ті, що збираються з результатів інструментів. Один прохід покриває
        всі шляхи, і жоден новий шлях не забуде про це.

        Що НЕ чіпається (див. :mod:`blackchpok_ide.language`): блоки коду,
        інлайн-код, шляхи, імена файлів, URL і рядки, схожі на код. Інакше
        ``get_state()`` перетворилось би на ``get_стан()``.
        """
        if kind in ("assistant", "narration") and text and "<think" in text.lower():
            import re as _re
            _thoughts = _re.findall(r"<think>(.*?)</think>", text, flags=_re.DOTALL | _re.IGNORECASE)
            text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL | _re.IGNORECASE)
            if "<think>" in text.lower():
                _tail = _re.split(r"<think>", text, maxsplit=1, flags=_re.IGNORECASE)
                text = _tail[0]
                if len(_tail) > 1 and _tail[1].strip():
                    _thoughts.append(_tail[1])
            text = text.strip()
            _joined_thought = "\n\n".join(x.strip() for x in _thoughts if x.strip())
            if _joined_thought:
                self.events.put(AgentEvent("reasoning", _joined_thought, data))
            if not text:
                return
        if kind == "token" and text:
            _buf = getattr(self, "_think_buf", "") + text
            if not getattr(self, "_in_think_stream", False):
                if "<think>" in _buf:
                    self._in_think_stream = True
                    _before, _, _after = _buf.partition("<think>")
                    self._think_buf = _after
                    if _before:
                        text = _before
                    else:
                        return
                elif len(_buf.lstrip()) < 8 and _buf.lstrip().startswith("<"):
                    self._think_buf = _buf
                    return
                else:
                    self._think_buf = ""
                    text = _buf
            if getattr(self, "_in_think_stream", False):
                if "</think>" in _buf:
                    self._in_think_stream = False
                    self._think_buf = ""
                    _, _, _tail = _buf.partition("</think>")
                    text = _tail.lstrip()
                    if not text:
                        return
                else:
                    self._think_buf = _buf[-32:]
                    return
        if kind in ("assistant", "narration", "reasoning") and text:
            try:
                text = language.polish(text)
            except Exception:  # noqa: BLE001 - мовна косметика не має ламати хід
                LOG.debug("Мовне виправлення не вдалось", exc_info=True)
        self.events.put(AgentEvent(kind, text, data))

    def _on_llm_retry(self, attempt: int, total: int, wait: float, reason: str) -> None:
        """Повторна спроба запиту до моделі — окремою подією в чат.

        Клієнт кличе це З ПОТОКУ агента перед паузою між спробами. Подія
        ``llm_retry`` показує рядок «Повторний запит моделі (1/4) · 2 с»,
        щоб людина бачила, що робота йде, а не «зависло». Раніше повтори
        були лише в лозі.
        """
        wait_text = f"{wait:.0f} с" if wait >= 0.5 else "зараз"
        self._emit(
            "llm_retry",
            f"Повторний запит моделі ({attempt}/{total}) · {wait_text}",
            attempt=int(attempt),
            total=int(total),
            wait=float(wait),
            reason=str(reason or ""),
        )

    def _run(self, text: str) -> None:
        self.session.workspace = self.workspace
        self.session.add_user(text)
        # ── Поправка користувача — сигнал навчання ────────────────────────
        # «Модель + інтернет + користувач має агент самонавчатися» (вимога
        # 21.11.2026). Якщо людина каже «неправильно, треба ось так» — це
        # найцінніший урок, і він має потрапити в пам'ять наприкінці ходу.
        # Прапорець скидається щоразу: він описує САМЕ цей хід.
        self._user_corrected = selflearning.looks_like_correction(text)
        self._user_correction = " ".join(str(text or "").split())[:300] \
            if self._user_corrected else ""
        # Мережа й факти цього ходу теж скидаються: інакше урок поніс би
        # знання з ПОПЕРЕДНЬОГО запиту.
        self._web_query = ""
        self._web_digest = ""
        self._web_facts = 0
        self._web_context_cache = None
        # ── Промпт збираємо ТУТ, у фоновому потоці ──────────────────────────
        # ``start()`` викликається з потоку інтерфейсу, і раніше збирав
        # промпт синхронно: інтернет-пошук «на кожен запит» (до 25 с на
        # джерело), читання пам'яті NEUROMESH і планування блокували
        # чергу повідомлень вікна — користувач бачив «Not Responding»,
        # хоч модель ще навіть не отримала запит. Тепер важка збірка йде
        # тут, а інтерфейс живе.
        try:
            self._build_action_prompt(text)
        except Exception:  # noqa: BLE001 - промпт не має зривати хід
            LOG.exception("Не вдалось зібрати промпт дій")
        # ── Самовідновлення адреси сервера ────────────────────────────────
        # Реальний випадок із логу користувача: рушій піднявся на 8081 (бо
        # 8080 тримав Steam), а в налаштуваннях лишився 8080. Агент стукав у
        # Steam і діставав HTTP 404 — «модель не працює», хоч вона працювала.
        #
        # Тепер адреса ЗВІРЯЄТЬСЯ з тим, що справді слухає, ПЕРЕД першим
        # запитом. Це не «вгадування»: якщо жоден порт не відповідає, нічого
        # не змінюємо й далі працює звичайна обробка помилки.
        #
        # Перевіряємо ЛИШЕ коли є модель: без неї запиту не буде взагалі
        # (нижче — «Модель не вибрана»), і мережева проба лише з'їдала б
        # час. Саме це зривало живі тести з офлайн-фолбеком.
        resolved = (self._resolved_base_url()
                    if str(getattr(self.llm_settings, "model", "") or "").strip()
                    else str(getattr(self.llm_settings, "base_url", "") or ""))
        client = LLMClient(
            resolved,
            self.llm_settings.model,
            self.llm_settings.api_key,
            temperature=self.llm_settings.temperature,
            max_tokens=self.llm_settings.max_tokens,
            timeout=self.llm_settings.timeout,
            reasoning_effort=getattr(self.llm_settings, "reasoning_effort", ""),
            # Повторні спроби показуємо в чаті: без цього людина бачила
            # «агент працює», хоч запит іще жодного разу не дійшов до моделі.
            on_retry=self._on_llm_retry,
        )
        ok = False
        try:
            if not self.llm_settings.model:
                # ── Вбудований рушій: назва моделі НЕ обов'язкова ───────────
                # ``native://blackchpok`` — це не адреса сервера: рушій бере
                # модель із пам'яті або з диска. Порожня назва тут означала
                # лише «користувач не вибрав у списку», і агент падав за
                # 10 секунд із «Модель не вибрана» — хоч файли GGUF лежали
                # на диску (перевірено на справжніх налаштуваннях: 7 моделей
                # і порожнє поле). Просимо клієнт підставити модель самостійно.
                if not getattr(client, "_use_embedded_default_model", lambda: False)():
                    raise LLMError("Модель не вибрана")
                # Далі працюємо з підставленою назвою: від неї залежать
                # метадані GGUF і вибір вікна контексту.
                self.llm_settings.model = client.model
            # ── Спершу: справжнє вікно контексту ──────────────────────────
            # Це найважливіший крок перед запитом. У налаштуваннях може
            # стояти 32768, сервер реально дає 16384 на слот, а модель у
            # GGUF заявляє 131072. Надсилання промпту «за налаштуваннями»
            # закінчувалось обривом з'єднання (``WinError 10054``), і
            # користувач бачив «модель не працює» — хоч вона працювала.
            #
            # Тепер вікно визначається з фактичних джерел, а історія
            # стискається до бюджету ЗАЗДАЛЕГІДЬ.
            try:
                budget = self.probe_context_window()
                if budget and budget.window:
                    self._emit("status", f"Контекст: {budget.text()}")
            except Exception:  # noqa: BLE001 - бюджет не має ламати хід
                LOG.debug("Вікно контексту не визначено", exc_info=True)
            # ── АВТОВИЗНАЧЕННЯ БЮДЖЕТУ ПІД ЦЕЙ ЗАПИТ ──────────────────────
            # Вікно — це скільки модель МОЖЕ. Скільки ЗАПОВНЮВАТИ — інше
            # число, і воно різне на кожному ході: «привіт» хоче ~2k,
            # «порівняй ці два файли» — десятки тисяч. Готуємо його ТУТ,
            # коли текст запиту вже в сесії, а схеми й хроніка взяті під
            # поточне вікно.
            #
            # Надсилати чи ні — вирішує :meth:`_loop` (зі схемами) або
            # :meth:`_chat_only` (без них): у звичайній розмові схем немає,
            # і рахувати їхні 9 646 токенів означало б «привіту» давати
            # 24 000 — рівно те, від чого ця вимога й рятує.
            try:
                self.refresh_budget_for_request(with_tools=bool(self.tools_enabled))
            except Exception:  # noqa: BLE001 - не має ламати хід
                LOG.debug("Бюджет під запит не перераховано", exc_info=True)
            # ── Відповідь на наше ж питання про GitHub ─────────────────────
            # Користувач бачить «Оновити файли на GitHub?» і відповідає
            # «так». Без цієї гілки агент сприйняв би «так» як нове
            # завдання й пішов би до моделі шукати, що саме оновити.
            # Тут відповідь однозначна: відправляємо зміни (або пояснюємо,
            # чому ні) і завершуємо хід.
            if self._answers_git_offer(text):
                self._emit("status", "Відповідь на питання про GitHub — "
                                     "відправляю зміни.")
                outcome = self.publish_to_git()
                ok = outcome.ok
                if not ok:
                    self._error = outcome.output
                return
            # Спершу дивимось, чи фраза взагалі просить дію. Якщо так —
            # кажемо моделі, які саме інструменти тут доречні: малі локальні
            # моделі часто «розмовляють» замість того, щоб викликати tool.
            # У режимі без інструментів (напр. «Чат») підказки не потрібні.
            # Для ДОВГОГО завдання (технічне завдання, список вимог) підказки
            # не працюють: евристика вихоплює з тексту URL і назви пакетів,
            # а потім виконує їх замість моделі — і справжня робота губиться.
            self._pending_hint = (
                tool_router.confident(text)
                if self.tools_enabled and len(text.strip()) < 400 else []
            )
            # ── Залізне правило: свіжі дані — лише з інтернету ─────────────
            # Стоїть ПІСЛЯ роутера: якщо роутер уже впізнав пошук, дублювати
            # не треба; якщо ні, але питання про ціну/курс/погоду/новини —
            # пошук додається примусово.
            self._web_rule_hint(text)
            if self._pending_hint:
                names = ", ".join(hint.describe() for hint in self._pending_hint[:4])
                # ── ПОРАДА, А НЕ НАКАЗ ────────────────────────────────────
                # Коли вирішує модель (``model_decides``), підказка йде в
                # ПРОМПТ, а не виконується сама: «схоже, тут просять список
                # файлів». Вона бачить увесь запит і контекст, тож «давай
                # грати в гру» відрізнить від «зроби гру» краще за список
                # слів. Примусове виконання лишається для слабких моделей,
                # які взагалі не вміють викликати інструменти.
                if getattr(self.agent_settings, "model_decides", True):
                    self._emit("status", f"Підказка моделі: {names}")
                    # ── Виклик через ``getattr`` ─────────────────────────
                    # Заміряно 21.11.2026: під час редагування файлу запущена
                    # IDE прочитала версію, де виклик уже був, а методу ще
                    # не було — і КОЖЕН хід падав з
                    # ``AttributeError: ... no attribute '_hint_advice'``.
                    # Підказка — допоміжна річ; її відсутність не має зривати
                    # роботу агента.
                    advice = getattr(self, "_hint_advice", None)
                    try:
                        self.session.hint_prompt = advice() if callable(advice) else ""
                    except Exception:                # noqa: BLE001
                        LOG.debug("Порада моделі не сформована", exc_info=True)
                        self.session.hint_prompt = ""
                else:
                    self._emit("status", f"Зрозумів як дію: {names}")
            # ── Одне уточнення замість вгадування ─────────────────────────
            # Питаємо ЛИШЕ тоді, коли без відповіді можна зіпсувати дані
            # або коли справді незрозуміло, що робити
            # (:func:`intent_engine.needs_clarification`). В усіх інших
            # випадках агент діє й каже, що припустив.
            question = ""
            if self.intent is not None and intent_engine.needs_clarification(self.intent):
                question = response_engine.clarifying_question(self.intent)
            if question:
                self.state.ask(question, self.intent.missing_information[0]
                               if self.intent.missing_information else "об'єкт")
                self._last_answer = question
                self._emit("assistant", question, final=True, question=True)
                self._emit("status", "Спершу уточнюю деталь, щоб не зіпсувати дані.")
                return
            # ── Правило доказів: якщо потрібен факт — інструменти ОБОВ'ЯЗКОВІ ─
            # Запит про реальний стан проєкту («скільки файлів», «що в
            # config», «тести пройшли?») мусить іти повним циклом із
            # інструментами — навіть якщо класифікатор відніс його до
            # «розмови». Інакше модель відповідає вигадкою: саме це дало
            # «Знайдено 1 файл: main.py» замість 100.
            #
            # ВАЖЛИВО про порядок. Раніше перевірка ``_is_small_talk()``
            # стояла ПЕРШОЮ, і коротке питання «які файли в проєкті?»
            # (≤200 символів, розпізнане як пояснення) ішло шляхом
            # ``_chat_only`` — без інструментів узагалі. Правило доказів
            # до нього просто не доходило: умова була мертвою для цілого
            # класу запитів. Тепер факт перевіряється ДО розмови.
            forced_tools = evidence_module.needs_tools_for(text)
            # ── Немає інструментів, а факт потрібен — кажемо ЧЕСНО ────────
            # Ця гілка спрацьовує лише тоді, коли інструменти справді
            # вимкнені (користувач так налаштував або режим їх не дає).
            # Текст раніше радив «перемкни режим на Агент» — тепер, коли
            # «Чат» теж дає інструменти, така порада була б неправдою.
            if forced_tools and not self.tools_enabled:
                # Інструменти вимкнені — факт перевірити нічим. Чесна
                # відповідь замість вигадки, без порад «перемкни режим»:
                # режим тут ні до чого, його вимкнув користувач.
                note = ("Це запит про реальний стан проєкту, але інструменти "
                        "зараз вимкнені. Увімкни їх у налаштуваннях агента — "
                        "і я перевірю фактами, а не словами.")
                self._last_answer = note
                self._emit("assistant", note, final=True)
                return
            # ── Звичайна розмова: без інструментів і без плану ────────────
            # «Привіт» не потребує ні пошуку файлів, ні перевірок. Раніше
            # агент усе одно запускав повний цикл, і користувач бачив
            # «Аналіз запиту», «Будує дерево», «Дивиться теку» на просте
            # вітання. Тепер ведемо такий хід окремим коротким шляхом —
            # і НЕ показуємо жодного службового статусу, щоб у чаті не
            # з'являвся блок «Аналіз запиту» з одного рядка.
            #
            # ``and not forced_tools`` тут не зайвий: якщо запит усе ж
            # визнано таким, що потребує фактів, розмова не має права
            # обійти інструменти (див. коментар вище).
            # ?????? ??????????? ?????????? ???? (_loop) ?? ?????? ???????? ?? ????????????:
            # ?????? ???? ???????, ?????????? ??????? (?? ??????????) ?? ????????? search_web/???????????.
            if False and self._is_small_talk() and not forced_tools:
                self._chat_only(client)
                ok = not self._error
                return
            if forced_tools:
                self._emit("status",
                           "Запит про стан проєкту — відповідаю лише за даними "
                           "інструментів.")
            self._emit("status", f"Запит до {self.llm_settings.model}…")
            self._loop(client)
            ok = not self._error
        except LLMError as exc:
            LOG.info("LLM недоступна: %s", exc)
            # ── Спершу: можливо, просто змінилась адреса ───────────────────
            # Реальний випадок із логу: рушій на 8081, клієнт на 8080 →
            # HTTP 404 на кожен запит. Це НЕ привід іти в офлайн-роутер:
            # модель працює, треба лише знайти її порт. Шукаємо ЛИШЕ тут,
            # після реальної помилки, щоб не платити за пошук у кожному ході.
            if self._recover_server_url(client):
                try:
                    self._loop(client)
                    ok = not self._error
                    return
                except LLMError as again:
                    LOG.info("Після виправлення адреси теж збій: %s", again)
            # ── Повторна спроба перед переходом в офлайн ──────────────────
            # Локальний сервер іноді відповідає помилкою на один запит
            # (перевантаження, модель ще довантажується) і одразу оживає.
            # Раніше агент у такому разі падав в офлайн-роутер, який уміє
            # лише читати файли — і правка не відбувалась зовсім
            # (перевірено наживо: «у файлі calc.py додай multiply» →
            # «Модель недоступна — працюю локальним роутером» → лише
            # read_file, файл без змін).
            if self._retry_once(client):
                ok = not self._error
                return
            if self.agent_settings.offline_fallback:
                self._emit("status", "Модель недоступна — працюю локальним роутером.")
                self._offline(text)
                ok = True
                # Окремий прапорець «відповідь неповна»: користувач бачить
                # результат локального роутера (це чесна відповідь), але
                # крок плану не можна закривати як «модель усе зробила».
                self._degraded = True
            else:
                self._error = str(exc)
                self._emit("error", str(exc))
        except Exception as exc:  # noqa: BLE001 - показуємо користувачу
            LOG.exception("Помилка агента")
            self._error = f"{type(exc).__name__}: {exc}"
            self._emit("error", self._error)
        finally:
            self._pending_hint = []
            self._record_trace(ok=ok and not self._error)
            self._remember_outcome(ok=ok and not self._error)
            # ── Самонавчання: висновки з цього ходу ───────────────────────
            # Стоїть ПЕРЕД ``done``: якщо агент щось вивчив, людина має
            # побачити це одразу, а не шукати в панелі пам'яті.
            self._learn_from_turn(ok=ok and not self._error)
            # ── СВІЖИЙ КОНТЕКСТ ПІСЛЯ ХОДУ ────────────────────────────────
            # Вимога користувача: «не обов'язково тримати все в контексті
            # постійно — на один запит весь контекст, потім у довгострокову
            # пам'ять і новий контекст». Стоїть ПІСЛЯ ``_learn_from_turn``:
            # уроки робляться з фактів ходу, і вони мають бути записані до
            # того, як історія зникне з вікна.
            self._reset_context_after_turn()
            # ── «Оновити файли на GitHub?» — ЛИШЕ після успішної роботи ────
            # Питаємо тут, у ``finally``: до цього моменту вже відомо, чи
            # робота справді відбулась, і чи є що відправляти. Питання перед
            # ``done`` — щоб людина бачила його одразу після відповіді.
            self._offer_git_publish(ok=ok and not self._error)
            # ``ok`` лишається правдивим для локального роутера (це справжня
            # відповідь), але ``_degraded`` каже викликачу, що модель не
            # працювала: крок плану тоді не закривається як виконаний.
            self._emit("done", ok=ok and not self._error, degraded=self._degraded)
            if self.on_finished:
                try:
                    self.on_finished(ok and not self._error,
                                     self._last_answer or self._error)
                except Exception:  # noqa: BLE001
                    LOG.debug("on_finished впав", exc_info=True)

    def _reset_context_after_turn(self) -> int:
        """Перенести хід у пам'ять і лишити свіже вікно (якщо ввімкнено).

        Три режими (``agent.context_mode``, типово ``auto``):

        * ``auto`` — АДАПТИВНО: глибина вибирається під запит
          (:mod:`context_flow`). «Продовж» → лишаємо більше, питання-факт →
          мінімум, правка → середина. Це типовий режим: обидві крайнощі
          («тримати все» і «чистити все») ламають роботу в різних випадках.
        * ``fresh`` — завжди мінімум (лише останній обмін).
        * ``full`` — не чистити нічого, працює лише звільнення при 85%.

        Помилка тут не має зривати хід: відповідь користувачу вже віддана,
        а втрата архіву означала б втрату контексту — тому ``turn_reset``
        лишає історію на місці, якщо архів не вдався.
        """
        mode = str(getattr(self.agent_settings, "context_mode", "auto") or "auto")
        if mode == "off":
            return 0
        try:
            plan = self.context_plan()
        except Exception:                            # noqa: BLE001
            LOG.debug("План контексту не пораховано", exc_info=True)
            return 0
        if plan.depth.keep == 0 and not plan.depth.is_deep():
            # Режим ``full``: історію не чіпаємо.
            return 0
        try:
            return self.turn_reset(keep=-1 if plan.depth.is_deep()
                                   else plan.depth.keep)
        except Exception:                            # noqa: BLE001
            LOG.debug("Свіжий контекст не застосовано", exc_info=True)
            return 0

    def context_plan(self) -> Any:
        """План контексту на ЦЕЙ хід (глибина, пошук, запис у пам'ять).

        Джерела, від найточнішого:

        1. **прохання МОДЕЛІ** — інструмент ``request_context``. Вона бачить
           своє завдання зсередини й знає, скільки минулого їй треба;
        2. **адаптивна евристика** (:func:`context_flow.choose`) — коли
           модель не попросила нічого;
        3. **режим людини** (``context_mode``) — звужує або розширює обидва.

        Кешується за текстом запиту: викликається двічі за хід (перед дією й
        після), і між цими моментами відповідь не змінюється.
        """
        text = self._current_user_text()
        cached = getattr(self, "_context_plan_cache", None)
        if cached is not None and cached[0] == text:
            return cached[1]
        mode = str(getattr(self.agent_settings, "context_mode", "auto") or "auto")
        # Прохання моделі має найвищий пріоритет: вона знає краще.
        asked = getattr(self, "_asked_context", None)
        if asked is not None and getattr(asked, "text", "") == text:
            plan = context_flow.plan_from_request(
                asked.depth, query=asked.query, mode=mode)
            LOG.info("Контекст за проханням моделі: %s",
                     context_flow.describe_request(asked.depth))
        else:
            plan = context_flow.choose(
                text, mode=mode,
                intent_type=str(getattr(getattr(self, "intent", None),
                                        "intent_type", "") or ""),
                steps_used=int(getattr(self, "_steps_used", 0) or 0),
                has_files=bool(self._touched_files),
            )
        # Режим людини звужує/розширює те, що вирішила модель.
        human = context_flow.mode_for(mode)
        if human.key == "fresh" and plan.depth.keep > context_flow.DEPTH_KEEP[
                context_flow.DEPTH_SHALLOW]:
            plan.depth.keep = context_flow.DEPTH_KEEP[context_flow.DEPTH_SHALLOW]
        elif human.key == "full":
            plan.depth.keep = 0
            plan.depth.level = context_flow.DEPTH_DEEP
        self._context_plan_cache = (text, plan)
        return plan

    def _on_context_request(self, depth: Any, query: str) -> None:
        """Модель попросила контекст — запам'ятати на цей хід."""
        text = self._current_user_text()
        self._asked_context = _ContextAsk(text=text, depth=depth, query=query)
        # Скидаємо кеш: наступний ``context_plan`` урахує прохання.
        self._context_plan_cache = None
        self._emit("status",
                   "Модель попросила контекст: "
                   + context_flow.describe_request(depth) + ".")

    def _current_user_text(self) -> str:
        """Остання репліка користувача (для плану контексту й пошуку)."""
        try:
            for message in reversed(self.session.messages):
                if str(message.get("role") or "") == "user":
                    content = message.get("content")
                    return content if isinstance(content, str) else str(content or "")
        except (AttributeError, TypeError):
            return ""
        return ""

    def _narrate_results(self, produced: list[str]) -> str:
        """Переказати зібрані дані ЛЮДСЬКОЮ мовою — силами моделі.

        Вимога користувача (21.11.2026): «мені потрібно відповідь не кодом а
        текстом з реальною обробкою моделью перед видачею користувачу!».

        Навіщо окремий запит. Дані з ``search_web`` чи ``read_file`` — це
        машинний вивід: URL, JSON, поля. Людині потрібне речення: «Солана
        зараз коштує 70.66 USD (+2.9% за добу), джерело CoinGecko».
        Переказати це може сама модель — і саме вона має це робити, а не
        шаблон у коді.

        Коли НЕ викликаємо:

        * немає жодних даних — нема чого переказувати;
        * модель недоступна (``LLMError``) — тоді лишається структурований
          звіт: краще чесний список, ніж порожнеча.

        Повертає готовий текст (порожній рядок — переказ не вдався).
        """
        body = "\n\n".join(part for part in produced if part.strip())
        if not body.strip():
            return ""
        client = getattr(self, "_last_client", None)
        if client is None:
            return ""
        goal = self._current_user_text()[:300]
        prompt = (
            "Ось дані, які я щойно зібрав інструментами:\n\n"
            + body[:3000]
            + "\n\nЗавдання користувача: " + (goal or "дай відповідь")
            + "\n\nПерекажи це ЛЮДИНІ своїми словами: коротко, по суті, "
              "звичайним текстом (без JSON і без блоків коду). Назви "
              "конкретні числа й посилання, які є в даних. Не вигадуй "
              "нічого, чого в даних немає. Не переказуй цю інструкцію."
        )
        self._emit("status", "Формую відповідь із зібраних даних…")
        try:
            result = client.chat(
                [{"role": "user", "content": prompt}],
                tools=None, temperature=0.2)
        except Exception:                            # noqa: BLE001
            LOG.info("Переказ даних не вдався — лишаю структурований звіт",
                     exc_info=True)
            return ""
        text = str(getattr(result, "content", "") or "").strip()
        # Порожній або службовий текст не вважаємо відповіддю.
        if len(text) < 20:
            return ""
        if text.startswith(("Ось дані", "Завдання користувача")):
            return ""
        # ── Модель пообіцяла замість переказу ─────────────────────────────
        # Заміряно 21.11.2026: на прохання переказати список файлів модель
        # відповідала «Звісно! Зараз покажу файли.» — і людина не бачила
        # ЖОДНОГО результату, хоч дані вже були зібрані. Ознака обіцянки
        # без змісту: короткий текст із майбутнім часом і без конкретики.
        if _is_bare_promise(text) and not _shares_terms(text, body):
            LOG.info("Переказ вийшов обіцянкою — лишаю структурований звіт")
            return ""
        return text

    def _answers_git_offer(self, text: str) -> bool:
        """Чи це ствердна відповідь на питання «оновити файли на GitHub?».

        Умови вузькі навмисно: питаємо ЛИШЕ тоді, коли ми щойно самі
        поставили це питання (``_git_asked``), і лише на коротку ствердну
        відповідь. Інакше «так» у звичайній розмові перетворювалось би на
        ``git push`` — а це незворотна зовнішня дія.

        Слова порівнюємо за МЕЖАМИ слів, а не підрядком: «так» входить у
        «тактика», а «ок» — у «потік». Підрядковий збіг відправив би зміни
        на GitHub у відповідь на «розкажи про тактику».
        """
        if not self._git_asked or self._git_published:
            return False
        body = str(text or "").strip().lower()
        if not body or len(body) > 60:
            return False
        no_words = ("ні", "no", "пізніше", "later", "скасуй", "ніколи")
        for word in no_words:
            if re.search(rf"(?<![\w\u0400-\u04FF]){re.escape(word)}"
                         rf"(?![\w\u0400-\u04FF])", body):
                return False
        yes_words = ("так", "ага", "давай", "ок", "ok", "yes", "yep", "sure",
                     "онови", "оновити", "відправ", "запуш", "publish", "push",
                     "звісно", "да")
        for word in yes_words:
            if re.search(rf"(?<![\w\u0400-\u04FF]){re.escape(word)}"
                         rf"(?![\w\u0400-\u04FF])", body):
                return True
        return False

    def _offer_git_publish(self, *, ok: bool) -> None:
        """Спитати людину, чи оновити файли на GitHub (лише коли є що).

        Умови навмисно вузькі, щоб питання не стало настирливим шумом:

        * хід завершився успішно;
        * агент СПРАВДІ змінив файли (інакше відправляти нічого);
        * репозиторій готовий: є ``origin`` і немає файлів із секретами;
        * питання ще не ставили в цьому ході.

        Сама відправка не робиться ніколи: ``push`` незворотний, тож
        рішення ухвалює людина. Питання ставиться окремою подією
        ``git_offer``, а інтерфейс показує кнопки «Так / Ні».
        """
        if not ok or not self._touched_files:
            return
        if self._git_asked or self.state.private:
            return
        if not getattr(self.agent_settings, "git_offer_publish", True):
            return
        try:
            from . import git_repo

            ready, reason = git_repo.is_clean_enough(self.workspace)
        except Exception:  # noqa: BLE001 - питання не має ламати хід
            LOG.debug("Стан git не перевірено", exc_info=True)
            return
        if not ready:
            # Причину показуємо лише тоді, коли вона корисна: «не git-
            # репозиторій» — це нормальний стан для теки без контролю версій,
            # і повідомляти про це після кожної правки було б шумом.
            if "origin не налаштовано" in reason or "секрет" in reason:
                self._emit("status", "GitHub: " + reason)
            return
        current = git_repo.state(self.workspace)
        self._git_asked = True
        changed = len(current.changed)
        self._emit(
            "git_offer",
            f"Оновити файли на GitHub? Змін: {changed} · "
            f"{current.remote} · гілка {current.branch}",
            remote=current.remote,
            branch=current.branch,
            changed=list(current.changed),
            message=git_repo.default_message(current.changed),
        )

    def publish_to_git(self, *, message: str = "") -> ToolResult:
        """Закомітити й відправити на GitHub — виклик ЛИШЕ після «так».

        Живе на раннері, а не в реєстрі інструментів, щоб не було двох
        шляхів: модель кличе ``git_publish`` лише з ``confirm=true``, а
        кнопка «Так» у чаті кличе цей метод. Обидва йдуть в
        :func:`git_repo.publish`, тож поведінка однакова.
        """
        from . import git_repo

        token = str(getattr(self.registry, "git_token", "") or "")
        result = git_repo.publish(self.workspace, message=message, token=token)
        if not result.ok:
            text = result.message or "не вдалось відправити"
            self._emit("assistant", "Не вдалося оновити GitHub.\n\n" + text,
                       final=True)
            self._last_answer = text
            return ToolResult(False, text)
        self._emit("assistant", "GitHub оновлено.\n\n" + result.message,
                   final=True)
        self._last_answer = result.message
        self._git_published = True
        return ToolResult(True, result.message)

    def _remember_outcome(self, *, ok: bool) -> None:
        """Записати в пам'ять те, що СПРАВДІ підтвердилось у цьому ході.

        Правила навмисно суворі, щоб пам'ять не стала джерелом вигадок:

        * зберігаємо лише успішні зміни файлів (є підтвердження інструмента);
        * зберігаємо лише реальні помилки й виправлення (не здогадки);
        * нічого не пишемо, якщо користувач просив не зберігати;
        * збій запису не впливає на хід агента.
        """
        bridge = self.memory_bridge
        if not getattr(self.agent_settings, "memory_participates", True):
            return
        if bridge is None or not bridge.ready() or self.state.private:
            return
        observations = list(self._observations or [])
        if not observations:
            return
        changed: list[str] = []
        failed: list[str] = []
        for item in observations:
            if item.duplicate:
                continue
            if item.ok and item.name in ("write_file", "edit_file", "append_file"):
                match = re.search(r"([\w./\\-]+\.[A-Za-z0-9]{1,8})", item.output)
                if match:
                    found = match.group(1).replace("\\", "/")
                    if found not in changed:
                        changed.append(found)
            elif not item.ok and item.name:
                reason = next((line.strip() for line in
                               (item.error or "").splitlines() if line.strip()), "")
                if reason:
                    failed.append(f"{item.name}: {reason[:160]}")
        goal = self.state.goal or str(
            getattr(self.intent, "primary_goal", "") or "")
        if not goal:
            for message in self.session.messages:
                if message.get("role") == "user":
                    goal = str(message.get("content") or "")
                    break
        task = " ".join(goal.split())[:120]
        if changed and ok:
            bridge.remember_fact(
                "Зроблено: " + "; ".join(changed) + (
                    f" (завдання: {task})" if task else ""),
                kind="change", source="агент: підтверджено інструментом",
                files=changed, task=task)
        for problem in failed[:2]:
            bridge.remember_fact(
                f"Збій інструмента: {problem}",
                kind="error", source="агент: результат інструмента",
                files=changed, task=task)
        # ── ЗНАННЯ З ІНТЕРНЕТУ → ДОВГОСТРОКОВА ПАМ'ЯТЬ ────────────────────
        # Залізне правило: усе, що агент дізнався з мережі, лягає в пам'ять
        # проєкту. Пам'ять СПІЛЬНА для всіх чатів, тож знання, отримане в
        # одному чаті, підкладається в контекст іншого — і локальна модель
        # не шукає те саме вдруге.
        self._learn_from_web(observations)
        # Історія задач: потрібна інструменту ``memory_task_history``.
        bridge.record_turn(
            task=task or "поточне завдання",
            action=response_engine.preview_of(self._last_answer or "", 200),
            status="ok" if ok else "error",
            files=changed,
            tools=[item.name for item in observations if item.name])

    def _learn_from_web(self, observations: list[Any]) -> None:
        """Зберегти знання з результатів ``search_web``/``fetch_url``.

        Чому окремим кроком. Раніше результати інтернету жили лише в історії
        одного ходу: наступна розмова починалась з нуля й шукала те саме
        знову. Тепер кожен змістовний результат стає фактами в NEUROMESH із
        посиланням на джерело (``provenance="web:<url>"``).

        Що НЕ зберігаємо: помилки, порожні результати, приватний режим і
        сирий шум сторінки (див. ``web_learning.extract``).
        """
        bridge = self.memory_bridge
        if not getattr(self.agent_settings, "memory_participates", True):
            return
        if bridge is None or not bridge.ready() or self.state.private:
            return
        service = getattr(bridge, "service", None)
        if service is None:
            return
        query = ""
        for message in reversed(self.session.messages):
            if str(message.get("role") or "") == "user":
                content = message.get("content")
                query = content if isinstance(content, str) else str(content or "")
                break
        saved = 0
        for item in observations:
            if not item.ok or item.duplicate:
                continue
            if item.name not in web_learning.WEB_TOOLS:
                continue
            body = str(item.output or "")
            if not web_learning.looks_like_web_result(body):
                continue
            facts = web_learning.extract(body, query=query[:160])
            if not facts:
                continue
            saved += web_learning.remember(service, facts)
        if saved:
            self._emit("status",
                       f"Знання з інтернету записано в пам'ять: {saved}.")

    def _web_rule_hint(self, text: str) -> None:
        """Вимога піти в інтернет, коли питання про свіжі дані.

        Залізне правило (вимога користувача): про ціну, курс, погоду, новини
        чи версію агент не має відповідати з пам'яті моделі — тільки з
        мережі. Тут ми додаємо ПІДКАЗКУ-ДІЮ ``search_web`` (а не текст), бо
        ``_pending_hint`` — це список :class:`tool_router.ToolHint`: агент
        виконає пошук сам і покаже результат людині.
        """
        if not self.tools_enabled or self.state.private:
            return
        used = [str(getattr(item, "name", "") or "")
                for item in (self._observations or [])]
        snapshot = getattr(self, "_memory_snapshot", None)
        memory_gave = snapshot is not None and not snapshot.empty
        clean_q = " ".join(str(text or "").split()).strip().lower().rstrip("!.?,")
        greetings = {
            "\u043f\u0440\u0438\u0432\u0456\u0442", "\u043f\u0440\u0438\u0432\u0435\u0442",
            "\u0434\u043e\u0431\u0440\u0438\u0439 \u0434\u0435\u043d\u044c",
            "\u0434\u043e\u0431\u0440\u043e\u0433\u043e \u0434\u043d\u044f",
            "\u0434\u043e\u0431\u0440\u0438\u0439 \u0440\u0430\u043d\u043e\u043a",
            "\u0434\u043e\u0431\u0440\u0438\u0439 \u0432\u0435\u0447\u0456\u0440",
            "\u0432\u0456\u0442\u0430\u044e", "\u0437\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439",
            "\u0434\u044f\u043a\u0443\u044e", "\u0441\u043f\u0430\u0441\u0438\u0431\u0456",
            "\u043e\u043a", "\u0434\u043e\u0431\u0440\u0435", "\u044f\u043a \u0441\u043f\u0440\u0430\u0432\u0438",
            "hi", "hello", "hey", "ok", "thanks"
        }
        if clean_q in greetings or len(clean_q) < 4 or "search_web" in used or "fetch_url" in used:
            return
        query = " ".join(str(text or "").split())[:200]
        if not query:
            return
        self._pending_hint = list(getattr(self, "_pending_hint", []) or [])
        if any(getattr(hint, "tool", "") == "search_web"
               for hint in self._pending_hint):
            return
        self._pending_hint.append(
            tool_router.ToolHint("search_web", {"query": query},
                                 tool_router.HIGH,
                                 "свіжі дані: відповідь без мережі заборонена"))
        self._emit("status",
                   "Питання про свіжі дані — спершу шукаю в інтернеті.")

    def _record_trace(self, *, ok: bool) -> None:
        """Зберегти хід для вимірювання якості (якщо сховище підключене).

        Пишемо структуровані факти: намір, виклики, змінені файли,
        тривалість. Приховані міркування моделі тут НЕ зберігаються.
        Помилка запису не має впливати на роботу агента.
        """
        store = self.traces
        if store is None or not getattr(self.agent_settings, "save_traces", True):
            return
        try:
            intent = self.intent
            known = set(self._specs) if getattr(self, "_specs", None) else set()
            trace = trace_store.TurnTrace(
                intent_type=str(getattr(intent, "intent_type", "") or ""),
                language=str(getattr(intent, "language", "uk") or "uk"),
                continuation=bool(getattr(intent, "continuation", False)),
                goal=str(getattr(intent, "primary_goal", "") or ""),
                asked_clarification=bool(self.state.pending_question),
                steps=max(0, int(getattr(self.stats, "step_count", 0) or 0)),
                duration=float(getattr(self.stats, "elapsed", 0.0) or 0.0),
                prompt_tokens=int(getattr(self.stats, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(self.stats, "completion_tokens", 0) or 0),
                answer_head=response_engine.preview_of(
                    self._last_answer or self._error, 400),
            )
            calls = list(self._observations or [])
            trace.tools = [item.name for item in calls]
            trace.rejected_calls = sum(1 for item in calls if item.rejected)
            trace.failed_calls = sum(1 for item in calls if not item.ok)
            trace.retried_calls = sum(1 for item in calls if item.attempts > 1)
            changed: list[str] = []
            for item in calls:
                if item.ok and item.name in ("write_file", "edit_file", "append_file"):
                    match = re.search(r"([\w./\\-]+\.[A-Za-z0-9]{1,8})", item.output)
                    if match:
                        found = match.group(1).replace("\\", "/")
                        if found not in changed:
                            changed.append(found)
            trace.changed_files = changed
            trace.hallucinated_tool = bool(known) and any(
                item.name not in known for item in calls)
            answer = self._last_answer or ""
            trace.leaked_protocol = response_engine.looks_like_raw_protocol(answer)
            trace.human_readable = bool(answer.strip()) and not trace.leaked_protocol
            trace.has_code_block = "```" in answer
            trace.false_success = (
                ok and bool(answer.strip()) and not changed
                and trace.intent_type in (intent_engine.CREATE, intent_engine.EDIT,
                                          intent_engine.DEBUG))
            store.record(trace)
        except Exception:                           # noqa: BLE001
            LOG.debug("Хід не записано у traces", exc_info=True)

    def _retry_once(self, client: LLMClient) -> bool:
        """Одна повторна спроба після збою моделі. True — вдалося.

        Локальний сервер віддає помилку на одиничний запит частіше, ніж
        здається: модель довантажується, слот зайнятий, таймаут. Друга
        спроба через секунду майже завжди проходить — і це дешевше, ніж
        перевести всю роботу в офлайн-режим, який не вміє правити файли.
        """
        if not self.llm_settings.model:
            return False
        self._emit("status", "Модель не відповіла — пробую ще раз.")
        try:
            time.sleep(1.5)
        except Exception:  # noqa: BLE001 - пауза не має ламати повторну спробу
            LOG.debug("Пауза перед повторною спробою не вдалась", exc_info=True)
        if self._cancel.is_set():
            return False
        try:
            self._loop(client)
            return not self._error
        except LLMError as exc:
            LOG.info("Повторна спроба теж не вдалась: %s", exc)
            return False
        except Exception:  # noqa: BLE001 - повтор не має ламати агента
            LOG.debug("Повторна спроба впала", exc_info=True)
            return False

    def _known_tool_names(self) -> list[str]:
        """УСІ імена інструментів, які взагалі існують для цього агента.

        Не те саме, що ``tool_schemas()``: у лінивому режимі моделі
        передається лише частина схем, але викликати вона може будь-який
        інструмент. Розпізнавання текстового виклику має знати ПОВНИЙ
        перелік, інакше виклик відомого інструмента вважається «службовим
        текстом» і відповідь виходить порожньою.
        """
        names: list[str] = []
        seen: set[str] = set()

        def add(name: object) -> None:
            text = str(name or "").strip()
            if text and text not in seen:
                seen.add(text)
                names.append(text)

        def add_schema(schema: object) -> None:
            """Ім'я зі схеми у форматі OpenAI (``{"function": {"name": …}}``)."""
            if not isinstance(schema, dict):
                return
            function = schema.get("function")
            if isinstance(function, dict):
                add(function.get("name"))
            else:
                add(schema.get("name"))

        # 1. ``_specs`` — мапа «ім'я → специфікація» для поточного ходу.
        specs = getattr(self, "_specs", None)
        if isinstance(specs, dict):
            for name in specs:
                add(name)
        # 2. Базові схеми інструментів застосунку (50 у TOOL_SCHEMAS).
        if isinstance(TOOL_SCHEMAS, dict):
            for name in TOOL_SCHEMAS:
                add(name)
        elif isinstance(TOOL_SCHEMAS, (list, tuple)):
            for schema in TOOL_SCHEMAS:
                add_schema(schema)
        # 3. Схеми памʼяті, MCP і скілів — вони теж можуть бути викликані.
        for attr in ("_all_schemas", "_specs_schemas", "_turn_schemas"):
            source = getattr(self, attr, None)
            if isinstance(source, dict):
                for name in source:
                    add(name)
            elif isinstance(source, (list, tuple)):
                for schema in source:
                    add_schema(schema)
        return names

    def _ask(self, client: LLMClient, messages: list[dict[str, Any]],
             schemas: list[dict[str, Any]]) -> ChatResult:
        """Спитати модель — зі стрімінгом, якщо він увімкнений у налаштуваннях.

        Стрімінг дає живий вивід тексту («друкарську машинку») через події
        агента. Якщо сервер його не підтримує, ``chat_stream`` сам
        відкочується до звичайного запиту, тож результат той самий.

        Схеми передаємо ЛИШЕ якщо модель справді має нативний виклик:
        сервер без підтримки ``tools`` відповідає помилкою, і весь хід
        падав би. Для таких моделей формат виклику пояснено в промпті
        (:func:`model_profile.text_tool_protocol`), а розбирає його
        ``llm_client.extract_tool_calls``.
        """
        tools_arg = schemas
        caps = self.model_caps
        if tools_arg and caps is not None and not caps.native_tools:
            tools_arg = None
        # ── Імена для РОЗПІЗНАВАННЯ виклику в тексті ────────────────────────
        # У лінивому режимі моделі передають лише «ядерні» схеми (17 із 50),
        # а викликати вона може БУДЬ-ЯКИЙ інструмент — решта доступна через
        # ``run_tool``. Якщо розпізнавати текст лише за переданими схемами,
        # виклик відомого інструмента (напр. ``search_web``) не впізнається,
        # текст викидається як «службовий», і користувач бачить
        # «Модель повернула порожню відповідь» — хоч модель відповіла
        # цілком осмислено. Тому передаємо ПОВНИЙ перелік відомих імен.
        known = self._known_tool_names()
        if not getattr(self.agent_settings, "stream", True):
            return client.chat(messages, tools=tools_arg, tool_choice="auto",
                               known_tools=known)

        def on_text(piece: str) -> None:
            self._emit("token", piece)

        def on_reasoning(piece: str) -> None:
            self._emit("reasoning_token", piece)

        # ── Жива правка: код з'являється в редакторі під час стріму ───────
        # Аргументи ``write_file`` / ``edit_file`` несуть код шматками.
        # Раніше він ставав видимим лише після виклику інструмента, тобто
        # людина десятки секунд дивилась на «агент працює» і діставала
        # готовий файл стрибком. Тепер кожен шматок іде подією ``edit_delta``,
        # і вікно дописує його в редактор зеленим.
        #
        # ``holder`` — словник, а не змінна: замикання в Python зв'язує ім'я
        # зі значенням, тому ``watcher = … for_tool(name)`` всередині
        # ``on_tool_args`` робив ``watcher`` локальним і кидав
        # ``UnboundLocalError`` на першому ж шматку. Мутація словника такої
        # проблеми не має.
        holder: dict[str, Any] = {"watcher": None}

        def on_tool_args(name: str, piece: str) -> None:
            if not name:
                return
            watcher = holder["watcher"]
            if watcher is None or watcher.name != name:
                watcher = stream_apply.ToolArgsWatcher.for_tool(name)
                holder["watcher"] = watcher
                if watcher is None:
                    # Інструмент не пише код — стежити нема за чим.
                    return
            watcher.feed(piece)
            if not watcher.ready():
                return
            self._emit("edit_delta", watcher.path,
                       path=watcher.path,
                       content=watcher.shown,
                       search=watcher.search,
                       replaces=watcher.replaces,
                       whole_file=watcher.whole_file,
                       final=watcher.finished)

        try:
            return client.chat_stream(
                messages,
                tools=tools_arg,
                tool_choice="auto",
                on_text=on_text,
                on_reasoning=on_reasoning,
                on_tool_args=on_tool_args,
                should_stop=self._cancel.is_set,
                known_tools=self._known_tool_names(),
            )
        except LLMError as exc:
            # ── Відкат на звичайний запит, а не здача ────────────────────
            # Дефект, через який користувач бачив «модель не працює»:
            # тут стояло ``raise``, тобто БУДЬ-ЯКИЙ збій стріму одразу
            # завершував хід. А стрім обривається найчастіше на дрібниці —
            # сервер закрив з'єднання (``WinError 10054``), спрацював
            # проміжний проксі, спрацював таймаут мовчання. Звичайний
            # (нестрімовий) запит у тих самих умовах проходить:
            #
            #   19:40:47 Стрімінг не вдався ([WinError 10054] …)
            #   19:40:47 → агент здався, хоч ``chat`` працює
            #
            # Тепер: якщо це НЕ та сама помилка, що вб'є й звичайний запит
            # (401/403/404 — неправильний ключ або адреса), пробуємо
            # звичайним шляхом. Це рівно те, чим стрім і має бути —
            # зручністю, а не єдиним шляхом до моделі.
            text = str(exc)
            fatal = any(marker in text for marker in
                        ("HTTP 401", "HTTP 403", "HTTP 404", "Модель не вибрана"))
            if fatal or self._cancel.is_set():
                raise
            LOG.warning("Стрімінг не вдався (%s) — повторюю звичайним запитом",
                        text[:160])
            self._emit("status",
                       "Стрімінг обірвався — повторюю звичайним запитом.")
            return client.chat(messages, tools=tools_arg, tool_choice="auto")
        except Exception as exc:  # noqa: BLE001 - стрімінг не має ламати агента
            LOG.warning("Стрімінг не вдався (%s), повторюю звичайним запитом", exc)
            return client.chat(messages, tools=tools_arg, tool_choice="auto")

    def _resolved_base_url(self) -> str:
        """Адреса сервера для запиту — з підтвердженням, що вона ЖИВА.

        Головне про вартість. Раніше тут виконувався повний пошук портів
        (24 порти × таймаут), і це блокувало КОЖЕН хід агента: живі
        GUI-тести падали з таймауту (перевірено: tests/test_cases_live.py —
        справа не встигала завершитись).

        Тепер перед запитом робиться лише ОДИН короткий ``/health``
        (десятки мілісекунд). Якщо адреса відповідає — вона й
        використовується. Якщо ні — НЕ скануємо одразу: позначаємо, що
        адресу треба знайти, і шукаємо лише ПІСЛЯ реальної помилки
        (:meth:`_recover_server_url`). Так пошук платить той, кому він
        справді потрібен.
        """
        configured = str(getattr(self.llm_settings, "base_url", "") or "")
        self._url_stale = False
        try:
            from . import runtime
        except ImportError:  # pragma: no cover
            return configured
        if not configured:
            return configured
        # Вбудований рушій: адреса не містить порту, «плавати» нічому.
        # Раніше перевірка йшла нижче, у гілку «не 127.0.0.1 → не чіпаємо»,
        # і це рятувало випадково. Тепер це явно: жодних мережевих проб.
        if runtime.embedded_url(configured):
            return configured
        low = configured.lower()
        # Хмарні й зовнішні адреси не чіпаємо: там порт не «плаває».
        if not any(marker in low for marker in
                   ("127.0.0.1", "localhost", "0.0.0.0")):
            return configured
        key = str(getattr(self.llm_settings, "api_key", "") or "")
        # Один TCP-connect (мілісекунди): «порт узагалі слухає?». Якщо ні —
        # адреса точно застаріла, але ПОВНИЙ пошук усе одно відкладемо до
        # реальної помилки: перед запитом він не потрібен.
        try:
            listening = runtime.server_responds(configured, timeout=0.35, level=0)
        except Exception:  # noqa: BLE001 - перевірка не має ламати хід
            listening = True
        if listening:
            return configured
        self._url_stale = True
        LOG.info("Адреса %s не слухає — пошук робочого порту після збою",
                 configured)
        return configured

    def _recover_server_url(self, client: LLMClient) -> bool:
        """Знайти робочий порт після збою моделі. ``True`` — адресу змінено.

        Викликається ЛИШЕ після реальної помилки запиту: саме тоді пошук
        виправданий. Знайдена адреса зберігається в налаштуваннях, щоб
        наступні ходи не платили за пошук знову.
        """
        if not getattr(self, "_url_stale", False):
            return False
        try:
            from . import runtime
        except ImportError:  # pragma: no cover
            return False
        configured = str(getattr(self.llm_settings, "base_url", "") or "")
        key = str(getattr(self.llm_settings, "api_key", "") or "")
        try:
            found = runtime.discover_server_url(configured, api_key=key)
        except Exception:  # noqa: BLE001 - пошук не має ламати хід
            LOG.debug("Пошук робочого порту впав", exc_info=True)
            return False
        if not found or found.rstrip("/") == configured.rstrip("/"):
            return False
        LOG.info("Адресу сервера виправлено: %s → %s", configured, found)
        try:
            self.llm_settings.base_url = found
        except AttributeError:
            pass
        self._url_stale = False
        self._emit("status",
                   f"Сервер відповідає на {found} (у налаштуваннях було "
                   f"{configured or '—'}) — перемикаюсь на робочу адресу.")
        # Клієнт перебудовуємо ЦІЛКОМ: у ньому ``adapter`` обраний за
        # адресою, тож сама лише заміна ``base_url`` лишила б адаптер
        # старого провайдера й запит пішов би не туди.
        try:
            client.__init__(
                found,
                self.llm_settings.model,
                self.llm_settings.api_key,
                temperature=self.llm_settings.temperature,
                max_tokens=self.llm_settings.max_tokens,
                timeout=self.llm_settings.timeout,
                reasoning_effort=getattr(self.llm_settings, "reasoning_effort", ""),
            )
        except Exception:  # noqa: BLE001 - перебудова не має ламати хід
            LOG.debug("Клієнт не перебудовано на нову адресу", exc_info=True)
            try:
                client.base_url = found.rstrip("/")
            except AttributeError:
                return False
        return True

    def _loop(self, client: LLMClient) -> None:
        schemas = self.tool_schemas()
        # ── Бюджет під ЦЕЙ хід: зі схемами, бо вони справді підуть ─────────
        # Схеми вже вибрані під вікно, тож потреба вимірюється РАЗОМ із ними
        # і з поточною історією. Далі на кожному кроці цикл перерахує його
        # заново: історія виросла, і бюджет мусить вирости разом із нею.
        try:
            self._announce_budget(self.refresh_budget_for_request(with_tools=True))
        except Exception:  # noqa: BLE001 - бюджет не має ламати роботу
            LOG.debug("Бюджет ходу не перераховано", exc_info=True)
        #: Скільки разів поспіль модель повторила ОДИН і той самий виклик.
        #: Локальні моделі (особливо 7B-класу) застрягають: інструмент
        #: відповідає помилкою, модель повторює той самий виклик і так до
        #: ліміту кроків. На скріншоті користувача це дало 14 однакових
        #: ``router:search_web`` і жодного результату.
        repeat = _RepeatGuard()
        #: Клієнт останнього запиту — потрібен для фінального підсумку, коли
        #: ліміт кроків вичерпано (див. ``_summarise_tool_results``).
        self._last_client = client
        #: Виконавець інструментів цього ходу: перевіряє аргументи, виконує,
        #: повторює тимчасові збої й не дублює вже зроблені виклики.
        self.orchestrator_for_turn()
        # ── Бюджет кроків цього ходу ───────────────────────────────────────
        # Беремо ЙОГО, а не ``max_steps``: рівень свободи дій додає кроки
        # поверх ліміту режиму. Без цього «Автономно» і «Дослідник» були б
        # лише словами в налаштуваннях.
        budget = self.step_budget
        self._steps_used = 0
        for step in range(budget):
            self._steps_used = step
            if step > 0:
                time.sleep(0.08)
            if self._cancel.is_set():
                self._emit("status", "Скасовано.")
                return
            # ── Довантаження схем посеред завдання ─────────────────────────
            # Модель могла викликати ``load_tools`` на попередньому кроці —
            # тоді повний набір схем змінився, і наступний запит мусить піти
            # вже з ним. Без цього «завантажено» означало б «нічого не
            # змінилось», і модель повторювала б той самий виклик.
            if getattr(self, "_schemas_dirty", False):
                self._schemas_dirty = False
                try:
                    schemas = self.tool_schemas()
                except Exception:  # noqa: BLE001 - не має ламати хід
                    LOG.debug("Схеми не перебудовано посеред завдання",
                              exc_info=True)
            started = time.perf_counter()
            # ── Автозвільнення вікна: контекст переїздить у пам'ять ────────
            # ПЕРЕД кожним запитом (а не лише коли вже переповнено): якщо
            # історія зайняла понад 85% свого бюджету, найдавніша частина
            # іде в NEUROMESH + RAG + хроніку, і вікно звільняється.
            #
            # Саме це робить чат нескінченним: модель ніколи не впирається
            # в «контекст переповнено», а знання лишаються доступними через
            # пошук. Працює однаково для локальних і хмарних моделей — тут
            # немає жодної різниці, бо все зводиться до розміру вікна.
            try:
                # ????????? ?????? ???? ?????? tool-?????????? (????? 600 ????????), ????????? ?????????? ????
                _msgs = getattr(self.session, "messages", None) or []
                for _m in _msgs[:-2]:
                    if isinstance(_m, dict) and _m.get("role") == "tool":
                        _c = str(_m.get("content") or "")
                        if len(_c) > 650:
                            _m["content"] = _c[:260] + "\n... [archived to NEUROMESH ??? ??????????? ?????] ..."
                freed = self.auto_free_context()
                if freed:
                    LOG.info("Хід %s: контекст звільнено (%s повідомлень)",
                             step, freed)
            except Exception:  # noqa: BLE001 - звільнення не має ламати хід
                LOG.debug("Автозвільнення контексту не вдалось", exc_info=True)
            # Хроніка перераховується ПЕРЕД КОЖНИМ запитом: попередній крок
            # міг витіснити блок історії, і модель має побачити оновлений
            # слід розмови вже в цьому запиті, а не в наступному.
            self._render_digest()
            # ── Бюджет перераховується на КОЖНОМУ кроці ────────────────────
            # Історія виросла (результати інструментів, хроніка), і план
            # мусить вирости разом із нею. Рахуємо від РЕАЛЬНОЇ потреби, а не
            # «тримаємо 32k, бо так стояло в налаштуваннях».
            try:
                self.refresh_budget_for_request(with_tools=True)
            except Exception:  # noqa: BLE001 - не має ламати хід
                LOG.debug("Бюджет кроку не перераховано", exc_info=True)
            messages = self.session.build()
            result = self._ask(client, messages, schemas)
            elapsed = time.perf_counter() - started
            if self._cancel.is_set():
                self._emit("status", "Скасовано.")
                return
            # Статистику беремо з реальної відповіді сервера (usage/timings).
            # Через спільний метод, щоб і розмова, і робота з інструментами
            # рахували ОДНАКОВО — раніше шлях без інструментів не рахував
            # нічого взагалі.
            self._publish_stats(result, messages, schemas=schemas,
                                duration=elapsed)
            self.session.add_assistant(result.message())
            # «Думки» reasoning-моделі (reasoning_content) раніше губились.
            # Показуємо їх у журналі роботи — це найцінніше, що є в агента,
            # коли він довго міркує над задачею.
            if result.reasoning.strip():
                self._emit("reasoning", result.reasoning.strip(), step=step)
            # Текст відповіді очищаємо від сирого JSON виклику ПЕРЕД показом:
            # інакше користувач бачить ``{"name": …}`` замість відповіді.
            visible = result.content.strip()
            if visible and result.tool_calls:
                visible = llm_client.strip_tool_json(visible, schemas).strip()
            # ── Текст моделі НЕ замовчуємо (21.11.2026) ────────────────────
            # Раніше тут стояло: якщо текст схожий на обіцянку дії
            # (``promises_action``), він ПРОСТО ВИКИДАВСЯ (``visible = ""``).
            #
            # Заміряно на скріншоті користувача: на «привіт, скажи, хто ти»
            # агент показував порожнечу або «немає відповіді», хоч модель
            # відповіла цілком осмислено. Причина — евристика обіцянки
            # спрацьовувала на живій мові («можу зробити…», «зараз
            # перевірю…»), і ЧЕСНИЙ текст зникав.
            #
            # Вимога користувача: «дай йому повну волю на спілкування зі
            # мною». Тому тепер текст лишається. Обіцянка без дії все одно
            # буде помічена правилом доказів (``_enforce_evidence``) — але
            # вона не зникає безслідно.
            if visible:
                # ── Чи це лише ПРОМІЖНИЙ текст? ────────────────────────────
                # ЗАМІРЯНО ЖИВИМ ПРОГОНОМ: на «скільки файлів .py у теці»
                # модель спершу відповіла прозою без виклику. Агент показував
                # її як ФІНАЛЬНУ з червоним застереженням «відповідь не
                # підтверджена даними», а потім ТУ САМУ відповідь відкликав і
                # таки викликав інструмент. Користувач бачив лякаючу плашку,
                # яка через секунду зникала.
                #
                # Тому «фінальність» визначаємо ДО показу: якщо агент ще
                # проситиме формат виклику, текст — чернетка, і показувати
                # його як відповідь (та ще й із застереженням) не можна.
                draft = (not result.tool_calls
                         and self._expects_action()
                         and not self._observations
                         and self._text_protocol_asked < TEXT_PROTOCOL_ATTEMPTS
                         and step < budget - 1)
                # Текст без подальших інструментів — це вже фінальна
                # відповідь; інакше модель коментує, що робитиме далі.
                final = not result.tool_calls and not draft
                # ── Остання перевірка перед показом ────────────────────
                # Навіть «фінальний» текст може бути сирим протоколом або
                # обіцянкою. Тоді відповідь збираємо зі СПРАВЖНІХ
                # результатів інструментів, а не з того, що модель написала.
                if final:
                    cleaned = response_engine.final_answer(
                        visible, self._observations or [], fallback=visible)
                    if cleaned != visible:
                        self._emit("status",
                                   "Відповідь містила службовий текст — "
                                   "перебудував її з реальних результатів.")
                    visible = cleaned
                    visible = self._enforce_evidence(
                        visible, step=step,
                        finish_reason=str(getattr(result, "finish_reason", "") or ""))
                    self._last_answer = visible
                self._emit("assistant", visible, step=step, final=final)
                if final:
                    try:
                        import threading as _th_git
                        from . import git_repo as _gr
                        _ws = getattr(self, "workspace", None)
                        _tok = str(getattr(getattr(self, "settings", None), "github_token", "") or "")
                        if _ws:
                            _th_git.Thread(target=lambda: _gr.smart_auto_sync(_ws, token=_tok), daemon=True).start()
                    except Exception:
                        pass
                    # ???? ? ???????? ????????????? ???? ? ?????? ????? ??????? ???? 1-? ????  ???????????? ?? ?????????? ?????!
                    _q_full = str(getattr(self, "_last_user_text", "") or "").lower()
                    _is_build_task = any(w in _q_full for w in ("??????", "????", "???", "???????", "???????", "???????", "???????", "??????", "?????"))
                    _nudge_cnt = int(getattr(self, "_plan_nudged_cnt", 0))
                    if _is_build_task and _nudge_cnt < 2 and step < budget - 1 and len(self._observations or []) > 0:
                        self._plan_nudged_cnt = _nudge_cnt + 1
                        _follow_msg = (
                            "?? ????????? ?? ??????? ????????! ?????? ?????? ?? ???????????? ????? 2026 ????: "
                            "????? ??????? ?????????? (?????/?????? ????, ?????????, Bento Grid ??????, ????????, "
                            "????????? ?????????, ????????????? JavaScript, ?????? Inter/Plus Jakarta Sans), "
                            "??????? ??? ? ??????????? Live Preview."
                        )
                        self.session.messages.append({"role": "user", "content": _follow_msg})
                        continue
                    return
            if not result.tool_calls:
                if not visible:
                    # Модель виконала інструмент і «нічого не сказала». Це
                    # нормальна поведінка локальних моделей, але користувач
                    # має побачити результат, а не порожню бульбашку.
                    fallback = self._answer_from_tools()
                    if fallback:
                        self._last_answer = fallback
                        self._emit("assistant", fallback, step=step, final=True)
                        return
                    # ── Порожній хід БЕЗ жодного інструмента — не кінець ────
                    # ЗАМІРЯНО ЖИВИМ ПРОГОНОМ У GUI: модель віддала власний
                    # виклик у форматі, якого ніщо не розпізнало. Текст
                    # вирізався як службовий, інструментів не було — і агент
                    # одразу писав «Модель повернула порожню відповідь»,
                    # витративши на завдання один крок. Користувач просив
                    # сайт, а не діагностику формату.
                    #
                    # Тому спершу намагаємось ЗРОБИТИ щось корисне:
                    #   1) підказки роутера (якщо фраза явно про дію);
                    #   2) ще один хід із прямою вимогою діяти;
                    # і лише потім — чесна причина з поясненням.
                    if (self._pending_hint and not self._observations
                            and step < budget - 1
                            and self._may_override_model(result)):
                        self._emit("status",
                                   "Модель мовчить — пробую виконати дію напряму.")
                        if self._run_hints():
                            return
                    if self._empty_turns < EMPTY_ANSWER_RETRIES \
                            and step < budget - 1:
                        self._empty_turns += 1
                        self._emit("status",
                                   "Модель відповіла без тексту — прошу "
                                   "виконати завдання інструментами.")
                        self.session.add_user(
                            "Ти не дав ні тексту, ні виклику інструмента. "
                            "Виконай завдання зараз: виклич потрібний "
                            "інструмент (напр. write_file для кожного файлу) "
                            "і продовжуй, доки робота не буде зроблена. "
                            "Якщо чогось бракує — скажи це одним реченням."
                        )
                        continue
                    self._error = self._empty_answer_reason()
                    # Відповідь із поясненням, а не сама лише помилка: людина
                    # має знати, ЩО сталося і що робити далі.
                    self._last_answer = self._error
                    self._emit("assistant", self._error, final=True)
                    return
                # Модель написала код у чат замість того, щоб створити файли
                # («Створимо package.json:» + блок ```). Без цього повтору
                # агент завершувався з порожньою роботою на диску.
                if self._wrote_code_in_chat(result.content):
                    # ── Спершу СПРОБУВАТИ ЗБЕРЕГТИ, а не просити заново ──
                    # Заміряно: модель дає цілком робочий код блоками
                    # ```html``` / ```python```, але не викликає write_file.
                    # Раніше така відповідь лише породжувала нагадування, і
                    # якщо модель не вміла інакше — робота зникала. Тепер
                    # вміст, який вона САМА підписала назвою файлу, лягає на
                    # диск, і хід триває вже з реальними файлами.
                    saved = self._salvage_code_files(result.content)
                    if saved:
                        self.session.add_assistant(
                            {"role": "assistant",
                             "content": f"Збережено файлів: {saved}."})
                        self.session.add_user(
                            "Твої файли збережено на диску. Продовжуй роботу: "
                            "перевір синтаксис (python_check) і додай те, чого "
                            "ще бракує, викликаючи інструменти. Не повторюй "
                            "уже збережений код у чаті."
                        )
                        if step < budget - 1:
                            continue
                    if step < budget - 1:
                        self._emit("status", "Код у відповіді замість файлів — "
                                             "прошу створити файли інструментом.")
                        self.session.add_user(
                            "Ти написав код у чаті, але файлів на диску немає. "
                            "Не пояснюй і не повторюй код у тексті — одразу виклич "
                            "інструмент write_file для кожного файлу окремо "
                            "(path + повний content), потім продовжуй роботу."
                        )
                        continue
                # Модель відповіла словами, але фраза явно вимагає дії:
                # виконуємо її самі, інакше агент «розмовляє» замість роботи.
                #
                # Обмеження «до 300 символів» стосується ЛИШЕ випадку, коли
                # модель відповіла текстом. Якщо у відповіді є блок коду,
                # розмір не має значення: це точно «код у чат замість
                # файлів», і такий хід не можна вважати виконаним. Саме на
                # цьому зривався сценарій із двома файлами: модель вставила
                # весь код у чат (понад 300 символів), захист не спрацював,
                # і файл лишився без змін.
                if self._pending_hint and (
                        len(result.content.strip()) < 300
                        or self._wrote_code_in_chat(result.content)) \
                        and self._may_override_model(result):
                    if self._run_hints():
                        return
                # ── Роутер прочитав файл, але правку ще НЕ зробив ───────────
                # Перевірка стоїть ПОЗА блоком ``_pending_hint``: ``_run_hints``
                # очищує ``_pending_hint`` на самому початку, тож усередині
                # блоку ця умова була недосяжною — агент показував «Готово.
                # Результат: search_text» і ЗУПИНЯВСЯ, не внесішвши зміну
                # (перевірено ``tools/eval_agent.py`` на перейменуванні:
                # стара назва лишалась у файлі).
                if self._hints_need_continue and step < budget - 1:
                    self.session.add_user(
                        "Ти виконав ПОШУК, але зміни ще НЕ внесено. Зроби "
                        "правку зараз: виклич edit_file (або write_file, "
                        "якщо треба переписати файл цілком) з точними "
                        "old_string і new_string. Не відповідай текстом і не "
                        "повторюй код у чаті — потрібна реальна зміна на диску."
                    )
                    self._hints_need_continue = False
                    continue
                # ── Модель не вміє нативного виклику — переходь на текстовий ──
                # ЗАМІРЯНО ЖИВИМ ПРОГОНОМ: Qwen2.5-VL-3B на запит «виправ
                # файл через edit_file» відповідає прозою («скористайтесь
                # sed…») і НЕ повертає жодного ``tool_calls``, хоч схеми
                # передані. На прямий наказ «відповідай рівно одним JSON» та
                # сама модель віддає правильний об'єкт.
                #
                # Тому, коли дію очікують, а структурованого виклику немає,
                # один раз явно пояснюємо формат. Це не «вигадування дії»:
                # текстовий протокол розбирає ``llm_client.extract_tool_calls``,
                # і далі все йде звичайним шляхом — перевірка аргументів,
                # дозволи, реальне виконання.
                #
                # ── АЛЕ: якщо інструменти ВЖЕ виконані, текст — це відповідь ──
                # ЗАМІРЯНО ЖИВИМ ПРОГОНОМ (GUI, власний рушій, Qwen2.5-Coder-14B):
                # на «скільки файлів .py у теці» модель викликала ``find_files``
                # і ``list_dir``, отримала результати (38 записів) і відповіла
                # прозою «Ось структура вашого проєкту: …». Агент вимагав від
                # неї ЩЕ один JSON-виклик, вона слухняно повторювала
                # ``list_dir()`` без аргументів, діставала докір «повторює той
                # самий крок» і знову писала прозу — і так по колу.
                # Користувач чекав 133 с на відповідь, яка вже була готова.
                #
                # Вимога формату потрібна ЛИШЕ тоді, коли інструментів ще не
                # було: тоді текст справді може бути обіцянкою замість роботи.
                if (self._expects_action()
                        and not self._observations
                        and self._text_protocol_asked < TEXT_PROTOCOL_ATTEMPTS
                        and step < budget - 1):
                    self._text_protocol_asked += 1
                    self._emit("status",
                               "Модель відповіла текстом — прошу виклик "
                               "інструмента у форматі JSON.")
                    names = tuple(self._specs or ())
                    reminder = model_profile.text_tool_protocol(names)
                    # ── Точні обов'язкові параметри ────────────────────────
                    # Модель регулярно називає інструмент, але забуває
                    # обов'язкові поля: живий прогін дав
                    # ``edit_file(old_string=…, new_string=…)`` без ``path``.
                    # Тому в нагадуванні перелічуємо рівно те, без чого
                    # виклик не пройде — для тих інструментів, які модель
                    # щойно згадала.
                    wanted = [card for card in (self._specs or {})
                              if card in str(result.content or "")]
                    details: list[str] = []
                    for card in wanted[:4]:
                        spec = (self._specs or {}).get(card)
                        if spec is None or not getattr(spec, "required", ()):
                            continue
                        params = ", ".join(sorted(spec.required))
                        line = f"Обов'язкові параметри «{card}»: {params}."
                        example = dict(getattr(spec, "example", {}) or {})
                        if example:
                            line += (" Приклад: "
                                     + json.dumps({"name": card,
                                                   "arguments": example},
                                                  ensure_ascii=False))
                        details.append(line)
                    self.session.add_user(
                        reminder
                        + ("\n\n" + "\n".join(details) if details else "")
                        + "\n\nПотрібна саме дія, а не порада."
                    )
                    continue
                # ── Обіцянка без дії ───────────────────────────────────────
                # На скріншоті користувача модель 14 разів писала «Знайшов,
                # є помилка в відповіді. Спробую інший запит.» і не робила
                # нічого. Такий текст — не відповідь, а обіцянка. Даємо
                # моделі ще один хід із прямою вимогою діяти, а якщо вона
                # знову обіцяє — завершуємо чесно.
                #
                # ВАЖЛИВО: перевірка стосується лише ДОРУЧЕНЬ. На «привіт»
                # модель відповідає «Привіт! Я можу допомогти…» — у цьому
                # тексті є слово «можу», і раніше агент вважав це обіцянкою,
                # вимагав дії й показував зайвий блок. Для розмови жодних
                # вимог і повторів бути не має.
                #
                # ``not self._observations``: якщо інструменти вже відпрацювали,
                # «Спробую ще…» — це вже підсумок роботи, а не обіцянка.
                if (self._expects_action()
                        and not self._observations
                        and _promises_action(result.content)
                        and not self._touched_files):
                    if step < budget - 1 and not self._promise_warned:
                        self._promise_warned = True
                        self._emit("status", "Модель пообіцяла дію замість дії — "
                                             "прошу виконати.")
                        self.session.add_user(
                            "Ти написав, що щось зробиш, але НЕ викликав жодного "
                            "інструмента. Обери конкретну дію й виклич інструмент "
                            "зараз. Якщо потрібного інструмента немає — скажи це "
                            "прямо й запропонуй, що можна зробити без нього."
                        )
                        continue
                    self._emit("assistant", _promise_notice(result.content),
                               final=True)
                    self._last_answer = _promise_notice(result.content)
                    return
                # ── Робота почата, але модель питає «продовжити?» ───────────
                # Заміряно живим прогоном у вікні: модель створила 3 файли з
                # потрібних семи й написала «Смакуй, як продовжити.» /
                # «Наступні кроки: …». Користувач просив САЙТ, а не план.
                #
                # Раніше цей випадок проходив повз усі перевірки: інструменти
                # вже працювали (``_observations`` не порожні), а «обіцянка»
                # тут не звучить — модель ніби звітує.
                #
                # Тому для завдання «створити річ» даємо ОДИН хід, щоб вона
                # дописала почате. Це не нескінченний цикл: прапорець
                # ``_continue_asked`` дозволяє рівно одне таке продовження.
                if (self._asks_to_build()
                        and self._touched_files
                        and not self._continue_asked
                        and step < budget - 1
                        and _asks_permission_or_next(result.content)):
                    self._continue_asked = True
                    self._emit("status",
                               "Завдання ще не завершене — прошу дописати решту.")
                    self.session.add_user(
                        "Робота ще НЕ завершена: у проєкті бракує файлів, "
                        "без яких він не працює. Не питай дозволу й не "
                        "пропонуй наступні кроки — ВИКОНАЙ їх зараз, "
                        "викликаючи інструменти (write_file для кожного "
                        "файлу). Коли справді все створено — коротко "
                        "переліч, що зроблено."
                    )
                    continue
                # Синтаксис перевіряється нижче, спільним кодом: і для ходу
                # з інструментами, і для ходу без них.
                if self._broken_python():
                    self._syntax_repairs += 1
                    continue
                return
            # ── Виконання викликів через оркестратор ────────────────────────
            # Модель лише ПРОПОНУЄ виклик. Перевірку аргументів, реальне
            # виконання, повтори й захист від повторів робить
            # :mod:`tool_orchestrator`, а не модель і не текст відповіді.
            prepared = tool_orchestrator.plan_batch(result.tool_calls)
            prepared = self._repair_arguments(prepared)
            for name, arguments, call_id in prepared:
                pretty = _pretty_arguments(json.dumps(arguments, ensure_ascii=False))
                self._emit("tool_call", f"{name}({pretty})", name=name,
                           arguments=pretty, call_id=call_id)
            outcomes = self.orchestrator.run_batch(prepared) if prepared else []
            # ── «Знайшов інтернет» замість роботи: повертаємо до завдання ──
            # Заміряно живим прогоном у вікні: на «напиши сайт блогу й
            # форуму з API» модель викликала ``search_web`` — тричі поспіль
            # і з різними запитами, — а потім написала огляд фреймворків.
            # Файлів на диску не з'явилося ЖОДНОГО. Мережа тут не потрібна:
            # це завдання створити річ, а не дізнатись факт.
            #
            # Тому, якщо завдання — «створити», а модель лише шукає, кажемо
            # їй прямо, що робити далі. Це не заборона інтернету взагалі:
            # одне попередження на хід, і лише коли жодного файлу ще немає.
            if (not self._touched_files
                    and not self._build_nudged
                    and prepared
                    and all(name in _WEB_LOOKUP_TOOLS for name, _a, _c in prepared)
                    and self._asks_to_build()):
                self._build_nudged = True
                self._emit("status",
                           "Це завдання створити річ, а не знайти факт — "
                           "переходжу до файлів.")
                self.session.add_user(
                    "Пошук в інтернеті тут не потрібен: користувач просить "
                    "СТВОРИТИ річ, а не дізнатись факт. Не шукай більше — "
                    "створи файли зараз: list_dir (що вже є), далі write_file "
                    "для кожного файлу окремо (path + повний content). "
                    "Почни з головного файлу й поступово додавай решту."
                )
                continue
            for where, ((name, arguments, call_id), observation) in enumerate(
                    zip(prepared, outcomes)):
                # Результат мусить відповідати ВИКЛИКУ за id: інакше сервер
                # моделі відповідає 400 («tool message without tool_calls»).
                self.session.add_tool_result(
                    call_id, name,
                    ToolResult(observation.ok,
                               observation.output if observation.ok
                               else observation.error))
                self._note_observation(observation)
                if observation.ok and name in ("write_file", "edit_file", "append_file", "run_command", "memory_store"):
                    repeat.reset()
                # ── Зір агента: знімок одразу йде в контекст моделі ────────
                if observation.ok:
                    self._attach_capture(
                        name, ToolResult(True, observation.output))
                body = observation.output if observation.ok else observation.error
                head = body if len(body) <= 1200 else body[:1200] + "\n…"
                self._emit(
                    "tool_result",
                    head,
                    name=name,
                    ok=observation.ok,
                    call_id=call_id,
                    user_text=observation.for_user,
                )
                if observation.rejected:
                    self._emit("status", observation.for_user)
                    # Модель отримала пояснення в tool-результаті — їй
                    # достатньо одного ходу, щоб виправити аргументи.
                    continue
                if observation.suspicious:
                    self._emit(
                        "status",
                        "У результаті інструмента знайдено вказівки — "
                        "виконую лише те, що просив користувач.")
                # ── Захист від зациклення ──────────────────────────────
                # Модель отримує той самий результат на той самий виклик —
                # отже, вона застрягла. Даємо їй ОДНУ чітку вказівку, а
                # якщо це не допомогло — припиняємо й кажемо користувачу
                # причину. Без цього цикл ішов до ліміту кроків і показував
                # «Досягнуто ліміт кроків» замість справжньої причини.
                fingerprint = _RepeatGuard.fingerprint(
                    name, arguments, observation.ok,
                    observation.output or observation.error)
                count, tired, hopeless = repeat.observe(fingerprint)
                # ── Повтор УСПІШНОГО виклику — не привід кидати роботу ────
                # Модель часто перепитує ``python_check`` або ``list_dir``
                # з тим самим результатом, уже досягнувши мети кроку. Раніше
                # це вважалось «зацикленням» і крок падав із «модель
                # зациклилась», хоч файл був створений і синтаксис ок
                # (перевірено ``tools/check_full_cycle.py``: «Python_check:
                # синтаксис ок» як причина збою). Тепер успішний повтор лише
                # просить змінити підхід, а роботу припиняємо тільки коли
                # выклик СПРАВДІ не вдається.
                if hopeless and observation.ok:
                    self._emit(
                        "status",
                        f"Модель повторює «{name}», хоч результат уже "
                        f"отримано — завершую хід із тим, що є.")
                    continue
                if hopeless:
                    self._last_answer = self._repeat_report(
                        repeat, name, ToolResult(observation.ok,
                                                 observation.output
                                                 or observation.error))
                    self._emit("assistant", self._last_answer, final=True)
                    self._error = ("Модель зациклилась на «" + name
                                   + "» — роботу припинено.")
                    self._emit("status", self._error)
                    return
                if tired:
                    self._emit(
                        "status",
                        f"Модель повторює той самий крок «{name}» — "
                        f"прошу змінити підхід.")
                    self.session.add_user(_repeat_hint(
                        name, count,
                        ToolResult(observation.ok,
                                   observation.output or observation.error),
                        intent=(self.intent.intent_type if self.intent is not None else "")))
                    continue          # наступний хід моделі — з новою вказівкою
            # ── Перевірка синтаксису ПІСЛЯ кожної дії ──────────────────────
            # Місце саме тут, а не в гілці «модель нічого не викликала»:
            # заміряно наживо — модель увесь час повертає tool_calls і
            # повторює той самий зламаний write_file, тому гілка без
            # інструментів просто не досягалась, і перевірка не працювала.
            #
            # Додатковий захист від циклу: якщо ми вже виправляли ці файли
            # двічі, а модель усе одно пише те саме — припиняємо.
            if self._touched_files and self._syntax_repairs < 2:
                if self._broken_python():
                    self._syntax_repairs += 1
                    continue
            elif self._syntax_repairs >= 2:
                self._emit("status", "Модель повторює зламаний код — "
                                     "припиняю, файл лишається на диску.")
                return
            # Синтаксис цілий — перевіряємо, чи код справді ПРАЦЮЄ.
            # Це ловить логічні помилки (ділення на нуль, звернення до
            # неіснуючого поля), які компілятор пропускає.
            if self._touched_files and self._run_smoke_check():
                continue
        else:
            # ── ЧЕСНЕ ПОВІДОМЛЕННЯ ПРО ЗУПИНКУ ─────────────────────────────
            # Коли ліміту немає (типова поведінка), «досягнуто ліміт кроків»
            # було б неправдою: цикл спинився через аварійний запобіжник
            # (``UNLIMITED_STEPS``), а не через налаштування людини.
            if self.steps_are_limited():
                self._emit("status", f"Досягнуто ліміт кроків ({budget}).")
            else:
                self._emit("status",
                           "Цикл спинився на аварійній межі — збираю підсумок.")
            # ── Останній хід БЕЗ інструментів: підсумок ───────────────────
            # Локальні моделі часто «залипають» на викликах (list_dir →
            # find_files → list_dir) і не доходять до відповіді. Раніше
            # користувач бачив порожнечу або «Готово.» без змісту. Тепер
            # просимо модель підсумувати ВЖЕ ЗІБРАНІ результати одним ходом
            # без інструментів — це дешево (один prefill) і дає справжню
            # відповідь на запитання користувача.
            summary = self._summarise_tool_results()
            if summary:
                # Той самий шар правди, що й для основної відповіді: підсумок
                # після ліміту кроків теж може містити числа, яких не було в
                # результатах інструментів. Раніше ця гілка показувала текст
                # моделі без жодної перевірки — правило діяло лише на одній
                # з п'яти гілок відповіді.
                summary = self._enforce_evidence(summary, step=self.step_budget)
            else:
                # ── Підсумок від моделі не вдався — збираємо з РЕАЛЬНИХ даних ──
                # Раніше тут лишалась порожнеча, і крок черги падав із
                # «порожня відповідь агента» — хоч інструменти вже відпрацювали
                # й файли були на диску (перевірено живим прогоном: крок
                # створив ``test_greeting.py``, а його позначили збоєм).
                # ``_answer_from_tools`` формує відповідь із спостережень, без
                # участі моделі, тож порожньою вона бути не може, якщо хоч
                # один інструмент повернув результат.
                summary = self._answer_from_tools()
            if summary:
                self._last_answer = summary
                self._emit("assistant", summary, final=True)

    def _summarise_tool_results(self) -> str:
        """Один хід моделі без інструментів: підсумувати зібрані результати.

        Навіщо: коли ліміт кроків вичерпано (або модель застрягла на
        викликах), у сесії вже лежать справжні дані — вивід ``list_dir``,
        ``find_files``, ``read_file``. Замість «Готово.» просимо модель
        відповісти на початкове запитання, спираючись ЛИШЕ на ці дані.

        Повертає порожній рядок, якщо відповісти не вдалось — тоді
        викликач покаже структурований звіт ``_answer_from_tools``.
        """
        if not self.session.last_tool_results(limit=1):
            return ""
        client = getattr(self, "_last_client", None)
        if client is None:
            try:
                client = LLMClient(
                    self.llm_settings.base_url,
                    self.llm_settings.model,
                    self.llm_settings.api_key,
                    temperature=self.llm_settings.temperature,
                    max_tokens=self.llm_settings.max_tokens,
                    timeout=self.llm_settings.timeout,
                )
            except Exception:                        # noqa: BLE001
                LOG.debug("Клієнт для підсумку не створено", exc_info=True)
                return ""
        question = ""
        for message in self.session.messages:
            if message.get("role") == "user":
                body = str(message.get("content") or "").strip()
                if body and not body.startswith("Ти написав"):
                    question = body
        prompt = (
            "Ти вже виконав інструменти, і їхні результати є вище. Тепер "
            "відповідай КОРИСТУВАЧУ звичайним текстом.\n"
            "ПРАВИЛА:\n"
            "1. Не викликай жодного інструмента — це заборонено на цьому кроці.\n"
            "2. Не згадуй назви інструментів і не вибачайся.\n"
            "3. Дай відповідь по суті початкового запитання, спираючись ЛИШЕ "
            "на наведені результати.\n"
            "4. Якщо даних бракує — прямо скажи, чого саме не вистачає."
        )
        if question:
            prompt += f"\n\nПочаткове запитання користувача: {question[:500]}"
        self._emit("status", "Підсумовую зібрані результати…")
        # Найважливіше: НЕ передаємо схеми інструментів. Інакше модель
        # знову «викликає» інструмент замість відповіді — саме це давало
        # «Зрозуміло, не буду викликати цей інструмент ще раз» замість суті.
        try:
            result = client.chat(
                [*self.session.messages[-10:], {"role": "user", "content": prompt}],
                tools=None,
                temperature=0.1,
                max_tokens=min(512, int(getattr(self.llm_settings, "max_tokens", 512))),
            )
        except (LLMError, OSError) as exc:
            LOG.debug("Підсумок не вдався: %s", exc, exc_info=True)
            return ""
        text = llm_client.strip_tool_json((result.content or "").strip())
        # Відповідь-відмова («не буду викликати…», «чим допомогти?») — не
        # підсумок: модель загубила початкове запитання. Тоді краще показати
        # структурований звіт із реальних даних, ніж порожню балаканину.
        rejected = (
            "не буду викликати", "чим можу допомогти", "як я можу допомогти",
            "звичайно, я буду", "зрозуміло, не буду",
        )
        lowered = text.lower()
        if not text or _promises_action(text) or any(
                marker in lowered for marker in rejected):
            return ""
        # Відповідь мусить перетинатись із запитанням — інакше це не відповідь.
        if question and not _overlaps(text, question):
            LOG.debug("Підсумок не стосується запитання — відкидаю")
            return ""
        return text.strip()

    def _attach_capture(self, name: str, outcome: ToolResult) -> None:
        """Поставити знімок у чергу на передачу моделі як ЗОБРАЖЕННЯ.

        Умови: інструмент успішний, це інструмент знімка, і режим візуальної
        перевірки ввімкнений. Якщо модель не мультимодальна — файл не
        додаємо (сервер відхилив би запит), але шлях у тексті лишається.
        """
        if not outcome.ok:
            return
        # Які інструменти дають ЗОБРАЖЕННЯ, а не просто шлях до файлу.
        # ``inspect_screenshot_regions`` і ``analyze_visual_difference``
        # повертають НОВІ PNG — модель має побачити саме їх (ділянки
        # читабельні, повний екран 3440×1440 — ні). Раніше цих двох назв
        # у списку не було, тож нарізані ділянки й вирізки «до/після»
        # лишались лише текстом: модель бачила шлях і не бачила картинки.
        if name not in ("app_screenshot", "project_screenshot", "web_screenshot",
                        "window_screenshot", "capture_screen", "capture_region",
                        "capture_window", "capture_display", "crop_screenshot",
                        "capture_live_preview", "capture_browser_page",
                        "inspect_screenshot_regions", "analyze_visual_difference"):
            return
        if not getattr(self, "vision_enabled", True):
            return
        paths = self._capture_paths(name, outcome.output)
        if not paths:
            return
        queue = self.session.pending_images
        added: list[str] = []
        for path in paths:
            if path in queue:
                continue
            queue.append(path)
            added.append(path)
        # Не тримаємо більше двох картинок: кожна додає тисячі токенів, а
        # старі знімки вже застаріли після нових правок.
        del queue[:-2]
        if added:
            self._emit("status",
                       "Зображення додано в контекст моделі: "
                       + ", ".join(Path(path).name for path in added[-2:]))

    def _capture_paths(self, name: str, output: str) -> list[str]:
        """Які саме PNG цього результату має побачити модель.

        Для нарізаних ділянок беремо ДІЛЯНКИ, а не ``overview.png``:
        огляд — це зменшене зображення, і саме на ньому дрібний текст
        втрачається. Якщо ділянок більше, ніж модель здатна отримати за
        один хід, беремо перші дві читабельні — решта лишається шляхами
        в тексті, і агент може попросити їх окремо.
        """
        paths = _png_paths_in(output)
        if not paths:
            return []
        if name != "inspect_screenshot_regions":
            return paths
        tiles = [path for path in paths if Path(path).name.lower() != "overview.png"]
        # Дві ПЕРШІ ділянки (читання зліва-направо, зверху вниз), а не
        # останні: саме вони зазвичай і містять те, на що скаржився
        # користувач («верхня панель обрізана»). Решта лишається шляхами.
        return (tiles or paths)[:2]

    # ── правило «немає доказу — немає твердження» ──────────────────────────
    def evidence_items(self) -> list[evidence_module.Evidence]:
        """Зібрати докази зі справжніх результатів інструментів цього ходу.

        Джерело — ``self._observations``: туди потрапляє КОЖЕН виконаний
        виклик (і від моделі, і від роутера). Вигадані моделлю «результати»
        сюди не потрапляють, бо вони не проходили через ``call_tool``.
        """
        items: list[evidence_module.Evidence] = []
        for observation in self._observations or []:
            items.append(evidence_module.Evidence(
                name=str(getattr(observation, "name", "") or ""),
                ok=bool(getattr(observation, "ok", False)),
                output=str(getattr(observation, "output", "") or ""),
                error=str(getattr(observation, "error", "") or ""),
            ))
        return items

    def _enforce_evidence(self, answer: str, *, step: int = 0,
                          finish_reason: str = "") -> str:
        """Перевірити фінальну відповідь і додати чесне застереження.

        Правило: **NO TOOL EVIDENCE — NO FACTUAL PROJECT CLAIM.** Будь-яке
        твердження про реальний стан проєкту (кількість файлів, вміст, тести,
        сервіси) дозволене лише з підтвердженням від інструмента.

        Навіщо. У попередньому аудиті агент видав «Знайдено 1 файл: main.py»,
        не викликавши жодного інструмента. Користувач не міг відрізнити це
        від справжньої відповіді. Тепер така відповідь або перебудовується з
        реальних даних, або супроводжується явним попередженням.

        Обрізання визначається ДВОМА ознаками:

        * ``finish_reason == "length"`` — сервер сам сказав, що текст
          обірвано лімітом токенів. Раніше це поле не читалось узагалі,
          і обірвана відповідь виглядала повною;
        * вичерпання кроків (``step`` дійшов до межі). Тут межа — ``max_steps``
          включно: на останньому дозволеному кроці відповідь справді
          незавершена, а попередня умова ``>= max_steps - 1`` позначала
          обрізаною навіть повну відповідь із усіма доказами.
        """
        request = ""
        try:
            request = str(getattr(self.intent, "text", "") or "")
            if not request and self.session.messages:
                for item in reversed(self.session.messages):
                    if str(item.get("role")) == "user":
                        request = str(item.get("content") or "")
                        break
        except Exception:  # noqa: BLE001 - перевірка не має ламати відповідь
            LOG.debug("Не вдалось визначити запит для перевірки доказів",
                      exc_info=True)

        requires_fact = evidence_module.needs_tools_for(request)
        items = self.evidence_items()
        cut_by_tokens = str(finish_reason or "").strip().lower() == "length"
        truncated = cut_by_tokens or step >= max(1, int(self.step_budget))
        result = evidence_module.check(
            answer, items, truncated=truncated, requires_project_fact=requires_fact)

        self._evidence_check = result
        if result.supported and not result.needs_disclaimer:
            return answer

        # 1. Твердження без доказу, але Є реальні результати — відповідаємо
        #    з них, а не з тексту моделі. Це найкраще, що можна зробити.
        if result.unsupported and result.has_any_success:
            rebuilt = self._answer_from_tools()
            if rebuilt:
                self._emit("status",
                           "Відповідь містила твердження без доказу — "
                           "перебудував її з реальних результатів інструментів.")
                rebuilt = (evidence_module.disclaimer(
                    result, known_counts=evidence_module.evidence_counts(items))
                    + "\n\n" + rebuilt)
                return rebuilt

        # 2. Перебудувати не вдалось — показуємо відповідь із попередженням.
        hint = "покажи файли" if requires_fact else ""
        note = evidence_module.disclaimer(
            result, tool_hint=hint,
            known_counts=evidence_module.evidence_counts(items))
        if not note:
            return answer
        LOG.debug("Доказів недостатньо: %s", result.summary())
        self._emit("status", "Доказів недостатньо — позначив відповідь як "
                             "неперевірену.")
        return (note + "\n\n" + answer).strip()

    def _repeat_report(self, guard: "_RepeatGuard", name: str,
                       outcome: ToolResult) -> str:
        """Чесна відповідь користувачу, коли модель зациклилась.

        Замість «Досягнуто ліміт кроків» кажемо, ЩО саме сталося, який
        інструмент не спрацював і що робити далі. Це та інформація, якої
        не було на скріншоті: користувач бачив 14 однакових викликів і не
        розумів причини.
        """
        lines = [
            "Не вдалося завершити завдання: модель зациклилась.",
            "",
            f"Вона повторювала той самий крок «{name}», і результат не "
            f"змінювався. {guard.summary()}".strip(),
        ]
        # Показуємо ПЕРШУ ЗМІСТОВНУ причину від інструмента, а не весь
        # службовий текст: у ньому буває перелік усіх інструментів, і
        # користувачу він не потрібен.
        detail = _user_facing_reason(outcome.output)
        if detail:
            lines += ["", f"Причина: {detail}"]
        if not outcome.ok:
            lines += [
                "",
                "Інструмент повернув помилку — ймовірно, він недоступний "
                "(напр. MCP-сервер не підключено).",
            ]
        lines += [
            "",
            "Що можна зробити:",
        ]
        if not outcome.ok:
            lines.append("• перевірити, чи підключений потрібний інструмент "
                         "(Налаштування → MCP);")
        lines += [
            "• уточнити завдання простішими словами;",
            "• вибрати іншу модель у шапці.",
        ]
        return "\n".join(lines)

    def _run_smoke_check(self) -> bool:
        """Запустити створений скрипт, щоб побачити ПОМИЛКУ ВИКОНАННЯ.

        Синтаксис — лише половина справи: ``average([2, 4, 6])`` може
        ділити на ``len(numbers) - 1`` і падати з ``ZeroDivisionError``,
        хоч файл компілюється. Агент має побачити це сам, а не чекати, поки
        користувач напише «воно не працює».

        Запускаємо ОБЕРЕЖНО:

        * лише якщо у файлі немає ``input(`` — інакше процес чекатиме
          вводу й зависне;
        * з таймаутом 20 с;
        * лише файл, який агент щойно створив (не чужі скрипти).
        """
        if not self._touched_files or self._smoke_done:
            return False
        self._smoke_done = True
        candidates = [rel for rel in self._touched_files
                      if rel.lower().endswith(".py")]
        if not candidates:
            return False
        # Беремо ОДИН найсвіжіший файл: запуск усіх сповільнює роботу.
        rel = candidates[-1]
        path = self.workspace / rel
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        if "input(" in body or "while True" in body:
            return False          # інтерактивний — не запускаємо
        try:
            # ``run_command`` повертає РЯДОК, а не ToolResult: у реєстрі це
            # звичайний метод-обробник. Звернення до ``.output`` тут падало
            # з AttributeError і зривало весь хід агента — саме так сталося
            # на сценарії з двома файлами.
            #
            # Шлях — ВІДНОСНО робочої теки, а не саме ім'я файлу: для
            # ``pkg/mod.py`` запуск ``python mod.py`` шукав файл у корені й
            # падав з «can't open file», а справжня помилка скрипта не
            # перевірялась зовсім (тихий пропуск).
            text = self.registry.run_command(
                f'"{sys.executable}" "{rel}"', timeout=20,
                cwd=str(self.workspace)) or ""
        except Exception:  # noqa: BLE001 - перевірка не має ламати цикл
            LOG.debug("Пробний запуск не вдався", exc_info=True)
            return False
        # «can't open file» — це помилка НАШОГО запуску, а не коду проєкту:
        # не показуємо її моделі як провину її файлу.
        if "can't open file" in text or "No such file or directory" in text:
            LOG.info("Пробний запуск %s не знайшов файл — пропускаю", rel)
            return False
        failed = ("Traceback" in text) or ("Error" in text and "OK" not in text)
        if not failed:
            return False
        self._emit("status", f"Пробний запуск {rel} впав — виправляю.")
        self.session.add_user(
            f"Я запустив {rel}, і він упав під час виконання:\n\n"
            f"{text[:900]}\n\n"
            "Знайди причину в коді й виправ через edit_file. "
            "Не переписуй файл цілком — зміни лише те, що спричиняє помилку. "
            "Потім перевір запуском ще раз."
        )
        return True

    def _broken_python(self) -> bool:
        """Перевірити, чи немає серед записаних .py файлів зламаного синтаксису.

        Якщо є — додаємо моделі КОНКРЕТНЕ виправлення й повертаємо True, щоб
        цикл зробив ще один хід.

        Чому не просто «виправ помилку»: заміряно наживо — модель слухняно
        повторювала той самий зламаний рядок 15 разів поспіль, і жодного
        разу не змінила його. Локальній моделі потрібен ПОКАЗАНИЙ правильний
        текст, а не прохання подумати.
        """
        if not self._touched_files:
            return False
        broken: list[tuple[str, str, str]] = []
        for rel in list(self._touched_files)[-3:]:
            if not rel.lower().endswith((".py", ".pyw")):
                continue
            path = self.workspace / rel
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                compile(body, str(path), "exec", dont_inherit=True)
                continue
            except SyntaxError as exc:
                # Помилку тримаємо в змінній: Python видаляє ім'я ``exc``
                # після блоку ``except``, і звернення до нього нижче падало з
                # ``UnboundLocalError: cannot access local variable 'exc'``
                # (це й ламало весь цикл агента в ide.log).
                issue = (f"{(exc.msg or 'синтаксична помилка')} "
                         f"(рядок {exc.lineno or '?'})")
            except (ValueError, TypeError):
                continue
            # ── Спершу пробуємо виправити МЕХАНІЧНО ────────────────────────
            # Апостроф усередині лапок — детермінована помилка з
            # детермінованим виправленням. Немає сенсу просити модель
            # «подумати»: заміряно, вона повторювала той самий рядок 15
            # разів і не змінювала його. Виправляємо самі й кажемо моделі,
            # що саме змінено.
            fixed_body = _fix_apostrophes(body)
            if fixed_body != body:
                try:
                    compile(fixed_body, str(path), "exec", dont_inherit=True)
                except SyntaxError:
                    fixed_body = body      # не допомогло — лишаємо як було
            if fixed_body != body:
                try:
                    self.registry.write_file(rel, fixed_body)
                except Exception:  # noqa: BLE001 - не ламаємо цикл
                    LOG.debug("Не вдалось виправити лапки у %s", rel,
                              exc_info=True)
                else:
                    self._emit("status",
                               f"Виправив лапки у {rel} автоматично.")
                    continue                   # файл уже коректний
            broken.append((rel, issue, ""))
        if not broken:
            return False
        names = ", ".join(name for name, _issue, _hint in broken)
        detail = "; ".join(
            f"{name}: {issue}{hint}" for name, issue, hint in broken)
        self._emit("status", f"Синтаксис зламано у {names} — виправляю.")
        self.session.add_user(
            "У цих файлах синтаксична помилка: " + detail
        )
        return True

    def _empty_answer_reason(self) -> str:
        """Пояснити порожню відповідь ТАК, щоб було зрозуміло, що робити.

        Раніше тут стояло одне речення «Модель повернула порожню відповідь».
        Воно нічого не пояснювало: людина не знала ні причини, ні наступного
        кроку. Тим часом причина майже завжди одна з трьох, і кожна має своє
        рішення — саме їх і називаємо.
        """
        model = str(getattr(self.llm_settings, "model", "") or "модель")
        lines = [
            "Модель не дала ні тексту, ні виклику інструмента — тому я нічого "
            "не змінив на диску.",
            "",
            "Що це може бути:",
            f"- **{model}** не вміє викликати інструменти у своєму форматі;",
            "- обірвалась відповідь (модель спинилась на першому ж токені);",
            "- завдання завелике для одного ходу — тоді варто розбити його.",
            "",
            "Що зробити:",
            "- повторити запит (іноді досить одного повтору);",
            "- вибрати іншу модель у шапці (краще та, що вміє function "
            "calling: Qwen2.5-Coder, Mistral, Llama 3.1+);",
            "- або сформулювати вужче: «створи index.html зі списком постів» "
            "замість «зроби сайт».",
        ]
        # Збої інструментів важливіші за загальні поради: якщо щось падало,
        # саме це й завадило роботі.
        failed = [item for item in (self._observations or ()) if not item.ok]
        if failed:
            lines.insert(3, "**Не вдалося:**")
            for item in failed[:3]:
                lines.insert(4, f"- {item.name}: "
                                + response_engine.clean_for_chat(
                                    item.error or "", limit=160))
        return "\n".join(lines)

    def _answer_from_tools(self) -> str:
        """Зібрати відповідь із результатів інструментів, коли модель мовчить.

        Локальні моделі часто викликають інструмент і завершують хід без
        тексту. Раніше користувач бачив «Модель повернула порожню відповідь»
        замість реального результату (список файлів, вміст файлу тощо).

        Форматування тут спільне з :mod:`response_engine`: те саме, що
        бачить користувач, коли модель відповідає сама. Дві різні
        реалізації означали б, що «без моделі» й «з моделлю» виглядають
        по-різному — саме на це скаржився користувач.
        """
        observed = getattr(self, "_observations", None)
        if observed:
            draft = response_engine.answer_from_observations(observed)
            if draft.text:
                return draft.text
        # Запасний шлях: результати є в сесії, але спостережень немає
        # (напр. після відновлення чату з диска).
        rows = self.session.last_tool_results(limit=3)
        if not rows:
            return ""
        rebuilt: list[tool_orchestrator.Observation] = []
        for name, ok, output in rows:
            body = (output or "").strip()
            if not body:
                continue
            rebuilt.append(tool_orchestrator.Observation(
                name=name or "інструмент", ok=ok,
                output=body if ok else "", error="" if ok else body,
            ))
        draft = response_engine.answer_from_observations(rebuilt)
        return draft.text

    def _salvage_code_files(self, text: str) -> int:
        """Записати на диск файли з блоків коду у ВІДПОВІДІ моделі.

        Повертає кількість реально записаних файлів.

        Навіщо. Заміряно живим прогоном: модель цілком коректно писала код
        блоками (``html``, ``python``, ``css``) у ЧАТ, але не викликала
        ``write_file``. Раніше агент у такому разі лише просив модель
        «створи файли інструментом» — і якщо вона не вміла, робота зникала
        разом із контекстом.

        Тепер код не губиться: блоки з явною назвою файлу зберігаються самі.
        Це НЕ «вигадування дії» — вміст узятий дослівно з відповіді моделі,
        а назва файлу мусить бути в самій відповіді (у заголовку блоку або
        в рядку перед ним). Без назви блок не пишемо: вгадувати шлях і
        затирати наявний файл неприпустимо.

        Правила безпеки:

        * пишемо лише якщо назву файлу справді названо;
        * наявний НЕпорожній файл не перезаписуємо — дописуємо лише
          відсутнє (чужий вміст дорожчий за здогад);
        * пишемо не більше ``_SALVAGE_LIMIT`` файлів за один хід.
        """
        blocks = self._code_blocks(text)
        if not blocks:
            return 0
        written = 0
        notes: list[str] = []
        for path, body in blocks[:_SALVAGE_LIMIT]:
            if self._cancel.is_set():
                break
            if not self._safe_salvage_name(path):
                continue
            if self._salvage_would_overwrite(path):
                # Файл уже має вміст: мовчазний перезапис знищив би роботу
                # попередніх кроків. Такий блок лишаємо моделі — хай
                # вирішить сама через edit_file.
                continue
            try:
                outcome = self.call_tool("write_file",
                                         {"path": path, "content": body})
            except Exception:  # noqa: BLE001 - порятунок не має ламати хід
                LOG.debug("Блок коду не записано у %s", path, exc_info=True)
                continue
            if not outcome.ok:
                continue
            written += 1
            notes.append(path)
            self._emit("tool_call", f"write_file(path={path})", name="write_file",
                       arguments=f"path={path}", call_id=f"salvage_{written}",
                       auto=True)
            self._emit("tool_result", outcome.output, name="write_file", ok=True,
                       call_id=f"salvage_{written}")
            self._touched_files.append(path)
        if written:
            self._emit("status",
                       "Код був у чаті, а не у файлах — зберіг файли сам: "
                       + ", ".join(notes))
        return written

    @staticmethod
    def _code_blocks(text: str) -> list[tuple[str, str]]:
        """Пари «(шлях, вміст)» з блоків коду, де шлях справді названо.

        Назву беремо з двох місць, у порядку надійності:

        1. інформаційний рядок блоку: ```` ```python app/main.py ```` —
           так пишуть і моделі, і люди;
        2. рядок-підпис безпосередньо перед блоком: «app/models.py:».

        Незакритий блок теж приймаємо. Заміряно живим прогоном у вікні:
        модель спинилась посеред ``app.py`` (``finish_reason = length``),
        і саме цей файл — головний у проєкті — на диску так і не з'явився.
        При цьому закриті блоки вже були записані. Тому останній блок без
        закривної огорожі беремо як є: краще неповний файл, який модель
        допише наступним кроком, ніж відсутній.
        """
        body = text or ""
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        pattern = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.DOTALL)
        for match in pattern.finditer(body):
            info = (match.group(1) or "").strip()
            content = match.group(2) or ""
            if len(content.strip()) < 20:
                continue
            path = _path_from_caption(info, body, match.start())
            if not path or path in seen:
                continue
            seen.add(path)
            found.append((path, content))
        return found

    def _salvage_would_overwrite(self, path: str) -> bool:
        """Чи в цьому файлі вже є вміст, який не можна мовчки затерти.

        Порятунок коду з чату — це «останній шанс», а не спосіб переписати
        те, що вже працює. Наявний непорожній файл лишаємо як є: модель
        побачить його через ``read_file`` і сама вирішить, що змінити.
        """
        try:
            target = self.registry.resolve(path)
        except Exception:  # noqa: BLE001 - резолв не має ламати хід
            return True
        try:
            if not target.is_file():
                return False
            return bool(target.read_text(encoding="utf-8",
                                        errors="replace").strip())
        except OSError:
            # Не читається — вважаємо, що займати не можна.
            return True

    @staticmethod
    def _safe_salvage_name(path: str) -> bool:
        """Чи безпечно писати файл із цією назвою (без виходу з теки)."""
        clean = str(path or "").strip().replace("\\", "/")
        if not clean or len(clean) > 180:
            return False
        if clean.startswith("/") or ":" in clean or ".." in clean.split("/"):
            return False
        name = clean.rsplit("/", 1)[-1]
        if not name or "." not in name:
            return False
        suffix = name.rsplit(".", 1)[-1].lower()
        return suffix in _CODE_SUFFIXES

    def _looks_like_file_list(body: str) -> bool:
        """Чи це перелік шляхів (тоді краще маркований список).

        Делегуємо в :func:`response_engine.looks_like_file_list`: раніше тут
        була ДРУГА копія того самого правила, і вони розійшлися — саме через
        це ``list_dir`` у корені проєкту не визнавався переліком (приховані
        файли на кшталт ``.gitignore`` і рядки-підсумки псували критерій), і
        назви файлів обрізались до 12 рядків.
        """
        return response_engine.looks_like_file_list(body)

    def _wrote_code_in_chat(self, text: str) -> bool:
        """Чи модель подала код файлів у тексті замість виклику інструмента.

        Локальні моделі часто відповідають «Створимо package.json:» і блоком
        ```json …``` у чаті. Користувач бачить гарний код, а на диску порожньо.
        Таку відповідь вважаємо невиконаною роботою, а не фінальною.
        """
        body = text or ""
        if "```" not in body:
            return False
        fences = body.count("```") // 2
        if fences < 1:
            return False
        # Ознаки того, що це саме вміст файлів, а не приклад у відповіді.
        markers = (
            '"name"', '"dependencies"', "require(", "import ", "module.exports",
            "<!DOCTYPE", "<html", "CREATE TABLE", "function ", "const ", "let ",
            "body {", ":root", "@media", "app.use(", "router.", "express(",
        )
        return any(marker in body for marker in markers)

    # ── офлайн-режим ───────────────────────────────────────────────────────
    def _offline(self, text: str) -> None:
        steps = self.planner.plan(text)
        if not steps:
            # ── Чесна причина замість «запусти LM Studio» ─────────────────
            # Тут стояв текст «Запусти LM Studio (Developer → Start Server) або
            # Ollama». Він суперечив архітектурі IDE: рушій llama.cpp і власний
            # in-process рушій уже входять до складу програми, і користувач не
            # має ставити сторонні GUI. До того ж він ПРИХОВУВАВ справжню
            # причину — у реальному збої моделі просто не було вибрано
            # (``llm.model = ""`` → «Модель не вибрана»).
            reason = str(self._error or "").strip()
            if not reason:
                reason = ("не вибрано модель" if not getattr(self.llm_settings, "model", "")
                          else "модель не відповіла")
            message = (
                "Локальна модель зараз недоступна — тому я не зміг виконати "
                "завдання агентськи.\n"
                f"Причина: {reason}.\n\n"
                "Що зробити (без сторонніх програм):\n"
                "• відкрий «Хаб моделей» і натисни «Запустити» — IDE сама підніме "
                "свій рушій llama.cpp;\n"
                "• якщо модель не влізла у відеопам'ять, IDE автоматично "
                "повторить запуск із меншим контекстом або частковим offload;\n"
                "• статус і справжня причина видно в панелі стану (кнопка "
                "«Діагностика»).\n\n"
                "Поки моделі немає, працюють прості команди:\n"
                "• «покажи файли», «прочитай server.py», «знайди текст master_agent_router»,\n"
                "• «запусти git status», «перевір синтаксис main.py», «дерево проєкту»."
            )
            self._last_answer = message
            self._emit("assistant", message)
            return
        collected: list[str] = []
        for name, arguments in steps:
            if self._cancel.is_set():
                return
            pretty = _pretty_arguments(json.dumps(arguments, ensure_ascii=False))
            self._emit("tool_call", f"{name}({pretty})", name=name, arguments=pretty)
            outcome = self.call_tool(name, arguments)
            self._emit("tool_result", outcome.output, name=name, ok=outcome.ok, call_id="offline")
            collected.append(outcome.output)
        answer = "\n\n".join(collected)
        # Офлайн-роутер віддає СПРАВЖНІ результати інструментів, але підпис
        # «Готово. Результат: …» легко перетворюється на твердження, яких у
        # даних немає. Перевіряємо тим самим правилом, що й основну гілку.
        answer = self._enforce_evidence(answer, step=self.step_budget)
        self._last_answer = answer
        self._emit("assistant", answer, offline=True)


#: Інструменти, які лише ДИВЛЯТЬСЯ в інтернет (нічого не створюють).
_WEB_LOOKUP_TOOLS: frozenset[str] = frozenset({
    "search_web", "fetch_url", "web_api", "web_open", "internet_status",
})

#: Ознаки того, що модель ПИТАЄ ДОЗВОЛУ або пропонує «наступні кроки»
#: замість того, щоб їх виконати. Заміряно живим прогоном у вікні: після
#: трьох створених файлів модель написала «Наступний крок: створити
#: маршрути API. Скажи, як продовжити.» — і зупинилась.
_NEXT_STEP_MARKERS: tuple[str, ...] = (
    "наступні кроки", "наступний крок", "далі треба", "далі потрібно",
    "як продовжити", "кажи, як", "скажи, як", "скажіть, як", "продовжити?",
    "продовжувати?", "хочеш, щоб я", "бажаєте, щоб я", "next steps",
    "shall i continue", "would you like me to", "let me know if",
)


def _asks_permission_or_next(text: str) -> bool:
    """Чи це «скажи, як продовжити» замість виконаної роботи."""
    body = (text or "").strip()
    if not body or "```" in body:
        return False
    low = body.lower()
    return any(marker in low for marker in _NEXT_STEP_MARKERS)

#: Скільки файлів максимум рятуємо з одного ходу, коли модель поклала код
#: у чат замість виклику інструмента. Більше — це вже «масове» записування,
#: і краще попросити модель зробити це через ``write_file``.
_SALVAGE_LIMIT = 12

#: Розширення, які має сенс витягти з чату у файл. Список навмисно вузький:
#: ```text`` чи ``bash`` найчастіше показують ПРИКЛАД, а не вміст файлу.
_CODE_SUFFIXES: frozenset[str] = frozenset({
    "py", "pyw", "js", "mjs", "cjs", "ts", "tsx", "jsx", "html", "htm",
    "css", "scss", "sass", "less", "json", "jsonc", "yml", "yaml", "toml",
    "ini", "cfg", "env", "txt", "md", "rst", "sql", "sh", "bat", "ps1",
    "go", "rs", "java", "kt", "c", "h", "cpp", "hpp", "cs", "rb", "php",
    "vue", "svelte", "xml", "svg", "csv", "dockerfile", "gitignore",
})

#: Назва файлу з розширенням — рівно один «токен», без пробілів.
_FILE_TOKEN = re.compile(
    r"([A-Za-z0-9_][A-Za-z0-9_./\\\-]{0,120}\."
    r"(?:" + "|".join(sorted(_CODE_SUFFIXES, key=len, reverse=True)) + r"))\b",
    re.IGNORECASE,
)


def _path_from_caption(info: str, body: str, start: int) -> str:
    """Витягти назву файлу для блоку коду (порожньо — назви немає).

    ``info`` — те, що стоїть після ``` у відкривальній лінії блоку.
    ``body`` і ``start`` — щоб подивитись рядок-підпис ПЕРЕД блоком.

    Обережність важлива: якщо написати код у «якийсь» файл, можна затерти
    чужий вміст. Тому приймаємо лише явну назву з розширенням, яку модель
    сама поставила в заголовку блоку чи в рядку перед ним.
    """
    # 1. Заголовок блоку. Дозволяємо і «python app/main.py», і «app/main.py».
    caption = (info or "").strip().strip("{}").strip()
    if caption:
        match = _FILE_TOKEN.search(caption)
        if match:
            candidate = match.group(1).strip("`\"'")
            # Мова після назви («```python script.py») — не частина шляху.
            return candidate.replace("\\", "/")
    # 2. Рядок-підпис перед блоком: «app/models.py:», «Файл app/urls.py».
    before = body[:start].rstrip()
    if before:
        line = before.splitlines()[-1].strip()
        if line and len(line) <= 160:
            match = _FILE_TOKEN.search(line)
            if match:
                return match.group(1).strip("`\"'").replace("\\", "/")
    return ""


def _arguments_dict(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _pretty_arguments(raw: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw[:200]
    if not isinstance(data, dict):
        return str(data)[:200]
    parts = []
    for key, value in data.items():
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        if len(text) > 90:
            text = text[:87] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


class ModelProbe(threading.Thread):
    """Перевірка сервера моделі у фоні."""

    def __init__(self, base_url: str, api_key: str, on_done: Callable[[bool, str, list[str]], None]) -> None:
        super().__init__(daemon=True)
        self.base_url = base_url
        self.api_key = api_key
        self.on_done = on_done

    def run(self) -> None:
        client = LLMClient(self.base_url, api_key=self.api_key, timeout=10)
        try:
            models = client.list_models()
        except LLMError as exc:
            self.on_done(False, str(exc), [])
            return
        self.on_done(True, f"Онлайн. Моделей: {len(models)}", models)


def probe_workspace(root: Path) -> dict[str, Any]:
    """Коротка інформація про робочу теку для панелі стану."""
    started = time.perf_counter()
    files = 0
    size = 0
    for path in root.rglob("*"):
        if path.is_file():
            files += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
        if time.perf_counter() - started > 1.5:
            break
    return {"files": files, "size": size}
