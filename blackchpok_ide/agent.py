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
from . import intent_engine
from . import llm_client
from . import memory_bridge
from . import model_profile
from . import permissions
from . import planning
from . import response_engine
from . import skills as skills_module
from . import social
from . import tool_orchestrator
from . import tool_lazy
from . import tool_router
from . import tool_specs
from . import trace_store
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


#: Вікно контексту, до якого вмикається стислий системний промпт.
COMPACT_PROMPT_LIMIT = 12_000

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
REPEAT_LIMIT = 2

#: Після стількох однакових ПОВТОРІВ роботу припиняємо загалом.
HARD_REPEAT_LIMIT = 4

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


def _repeat_hint(name: str, count: int, outcome: ToolResult) -> str:
    """Вказівка моделі, коли вона повторює той самий виклик.

    Навмисно конкретна: локальні моделі не розуміють абстрактного «спробуй
    інакше» і повторюють те саме. Тому кажемо, ЩО робити замість цього.
    """
    body = (outcome.output or "").strip()
    if len(body) > 300:
        body = body[:300] + "…"
    if not outcome.ok:
        return (
            f"Інструмент «{name}» уже відповів ПОМИЛКОЮ {count} рази "
            f"поспіль, і ти повторюєш той самий виклик. Це не спрацює.\n\n"
            f"Відповідь інструмента:\n{body}\n\n"
            "Не викликай цей інструмент знову. Обери інший спосіб: інший "
            "інструмент, інші аргументи або відповідай користувачу тим, що "
            "справді відомо, і чесно скажи, чого зробити не вдалося."
        )
    return (
        f"Ти вже викликав «{name}» з тими самими аргументами {count} рази "
        f"поспіль, і результат не змінився:\n{body}\n\n"
        "Не повторюй цей самий виклик. Або переходь до наступного кроку, "
        "або відповідай користувачу тим, що вже маєш."
    )


class _RepeatGuard:
    """Лічильник однакових викликів інструментів — захист від зациклення.

    Навіщо окремий клас, а не змінна в циклі: правило має бути видимим,
    тестованим і однаковим для всіх гілок (чат, черга, автономний режим).

    Порівнюємо ПАРУ «виклик + результат»: якщо модель повторює той самий
    виклик, але отримує ІНШИЙ результат, це нормальна робота (напр.
    повторне читання файлу після зміни). Зациклення — це коли не змінюється
    нічого: ні аргументи, ні відповідь інструмента.
    """

    __slots__ = ("_seen", "_last", "_streak", "_total")

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._last: str = ""
        self._streak: int = 0
        self._total: int = 0

    @staticmethod
    def fingerprint(name: str, arguments: Any, outcome_ok: bool,
                    output: str) -> str:
        """Відбиток «виклик + результат» (стабільний і короткий)."""
        try:
            payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            payload = str(arguments)
        # Довгий вивід (файл на тисячу рядків) не має ламати порівняння —
        # беремо початок і кінець, цього досить, щоб відрізнити різні дані.
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
        return count, tired, hopeless

    @property
    def total(self) -> int:
        """Скільки викликів інструментів зроблено за весь хід."""
        return self._total

    def summary(self) -> str:
        """Коротке пояснення для користувача (без технічного сміття)."""
        if not self._seen:
            return ""
        top = max(self._seen.items(), key=lambda item: item[1])
        name = top[0].split("|", 1)[0]
        return f"«{name}» повторювався {top[1]} раз(и) з тим самим результатом."


#: Ознаки «обіцянки дії» в тексті моделі (українською й англійською).
#:
#: На скріншоті користувача модель 14 разів писала «Знайшов, є помилка в
#: відповіді. Спробую інший запит.» — і не робила жодного виклику. Такий
#: текст не є відповіддю, і показувати його як результат не можна.
_PROMISE_MARKERS = (
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
    return any(marker in lowered for marker in _PROMISE_MARKERS)


def _overlaps(answer: str, question: str, *, threshold: float = 0.12) -> bool:
    """Чи стосується відповідь запитання (перекриття змістовних слів).

    Потрібно, щоб відсіяти «відповіді» на кшталт «Як я можу допомогти?» на
    запитання «Скільки .py файлів у теці». Модель 14B після довгого ланцюга
    інструментів інколи втрачає початкове запитання й відповідає в порожнє.
    """
    import re as _re

    words = _re.compile(r"[\w\u0400-\u04FF]{3,}").findall
    left = {word.lower() for word in words(question or "")}
    right = {word.lower() for word in words(answer or "")}
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

    def reset(self) -> None:
        self.messages.clear()

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
        if self.action_prompt.strip():
            prompt += "\n\n" + self.action_prompt.strip()
        if self.extra_prompt.strip():
            prompt += "\n\n" + self.extra_prompt.strip()
        return {"role": "system", "content": prompt}

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def add_tool_result(self, call_id: str, name: str, result: ToolResult) -> None:
        body = result.output
        if not result.ok:
            body = "ПОМИЛКА: " + body
        limit = max(2000, self.settings.context_char_limit // 4)
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
        limit = max(4000, self.settings.context_char_limit)
        total = sum(len(str(m.get("content") or "")) for m in self.messages)
        budget = self._token_chars_budget()
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
        first = self.messages.pop(0)
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
            removed_chars += len(str(nxt.get("content") or ""))
        return removed_chars or 1

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
        if budget is not None and budget.window:
            # Стеля = вікно мінус відповідь, запас і службові дані.
            ceiling = max(512, budget.window - budget.answer - budget.safety)
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
        # Окремі повідомлення й результати інструментів теж не мають права
        # бути більшими за свою частку вікна.
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
        """
        total = 0
        for message in [self.system_message(), *self.messages]:
            body = str(message.get("content") or "")
            total += self._tokens_in(body)
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
        limit = int(self.context_limit or 0)
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
        limit = int(self.context_limit or 0)
        if limit <= 0:
            return
        # ~1 токен на 3 символи; один результат не має брати понад 25% вікна.
        allowed = max(2000, int(limit * 0.25 * 3))
        for message in self.messages:
            if message.get("role") == "tool":
                body = str(message.get("content") or "")
                if len(body) > allowed:
                    message["content"] = body[:allowed] + "\n… (обрізано до вікна контексту)"

    def build(self) -> list[dict[str, Any]]:
        self.trim()
        messages = [self.system_message(), *self.messages]
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
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.events: "queue.Queue[AgentEvent]" = queue.Queue()
        self.planner = OfflinePlanner(self.workspace, registry)
        self.mcp_manager: Any = None
        self.skill_book: Optional[skills_module.SkillBook] = None
        self.on_finished: Optional[Callable[[bool, str], None]] = None
        self._last_answer: str = ""
        self._error: str = ""
        #: True, якщо відповідь дала не модель, а локальний роутер.
        #: Використовується, щоб не зараховувати такий хід як повний успіх.
        self._degraded: bool = False
        #: True, якщо моделі вже казали «ти пообіцяв, але не зробив».
        #: Друге попередження не має сенсу — тоді завершуємо чесно.
        self._promise_warned: bool = False
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
        """Скільки кроків робити: ліміт режиму або налаштування."""
        if self.max_steps_override > 0:
            return self.max_steps_override
        return max(1, int(self.agent_settings.max_steps or 8))

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
        """
        before = len(self.session.messages)
        # Жорстке обмеження: лишаємо приблизно третину звичайного ліміту.
        self.session.settings = self.agent_settings
        original = self.agent_settings.context_char_limit
        try:
            self.agent_settings.context_char_limit = max(2000, original // 3)
            self.session.trim()
        finally:
            self.agent_settings.context_char_limit = original
        removed = before - len(self.session.messages)
        LOG.info("Історію стиснуто: прибрано %s повідомлень", removed)
        return max(0, removed)

    def set_context_limit(self, limit: int) -> None:
        """Розмір вікна контексту моделі (для відсотка заповнення).

        Те саме число потрібне сесії, щоб вона вчасно підрізала історію —
        інакше довге завдання впирається в ``exceed_context_size_error``.
        """
        self.stats.set_limit(limit)
        self.session.context_limit = max(0, int(limit or 0))

    def adopt_context_window(self, *, props_ctx: int = 0, gguf_ctx: int = 0,
                             counter: Any = None) -> "context_budget.Budget":
        """Визначити СПРАВЖНЄ вікно контексту й узяти його в роботу.

        Викликається перед першим запитом, коли сервер уже відповідає (тоді
        відомий ``/props``). Без цього кроку в налаштуваннях могло стояти
        ``ctx_size 32768``, тоді як сервер реально давав 16384 на слот —
        агент надсилав завеликий промпт, і сервер обривав з'єднання
        (``WinError 10054``), що виглядало як «модель не працює».

        Повертає :class:`context_budget.Budget` — розподіл вікна, який
        далі використовує стискання історії.
        """
        window = context_budget.resolve_window(
            props_ctx=int(props_ctx or 0),
            gguf_ctx=int(gguf_ctx or 0))
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
        if base:
            props_ctx = _server_slot_context(
                base, str(getattr(self.llm_settings, "api_key", "") or ""))
        gguf_ctx = _gguf_context(str(getattr(self.llm_settings, "model", "") or ""))
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
        # Каталог дій: щоб модель знала, що взагалі вміє, і не «розмовляла»
        # замість виклику інструмента.
        has_mcp = False
        if self.mcp_manager is not None:
            try:
                has_mcp = bool(self.mcp_manager.tool_catalog())
            except Exception:  # noqa: BLE001
                has_mcp = False
        parts: list[str] = []
        if self.tools_enabled:
            parts.append(tool_router.catalog_text(include_mcp=has_mcp))
            # ── Компактний реєстр інструментів ─────────────────────────────
            # Коли схем забагато, повні JSON-схеми вже не передаються (див.
            # ``tool_schemas``), і моделі потрібен перелік того, що взагалі
            # існує. Без нього вона не знала б, що можна попросити
            # ``load_tools`` для інструмента, назви якого не бачить.
            registry_text = self._lazy_registry_text()
            if registry_text:
                parts.append(registry_text)
        if self.skill_book is not None and self.agent_settings.use_skills:
            skill_prompt = self.skill_book.prompt()
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
        context_block = self._context_block()
        if context_block:
            parts.append(context_block)
        self.session.action_prompt = "\n\n".join([*parts, rule])
        self.session.skill_prompt = ""
        #: Схеми для цього ходу (потрібні, щоб знати, які інструменти є).
        self._specs = {}
        self._observations = []
        if self.tools_enabled:
            self.tool_schemas()
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
        self._thread = threading.Thread(target=self._run, args=(text,), daemon=True)
        self._thread.start()
        return True

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
        # ── Рішення: повний набір чи лінивий реєстр ─────────────────────────
        # Порівнюємо РЕАЛЬНИЙ розмір схем із бюджетом схем. Якщо все вміщається
        # — передаємо повний набір і не змушуємо модель робити зайвий крок.
        router = self.lazy_router()
        lazy = router.update(
            available,
            budget_tokens=self._schema_budget(),
            token_counter=AgentSession._tokens_in,
            specs=self._specs or None,
        )
        self._schemas_lazy = bool(lazy)
        if lazy:
            available = router.eager_schemas()
        # ── Вузьке вікно контексту: схеми мусять влізти ─────────────────────
        # 28 схем займають ≈3000 токенів. У вікні 4096 це половина запиту ще
        # до розмови, а в 2048 — більше за все вікно: сервер відповідав
        # ``exceed_context_size_error``. Тому схеми впорядковані за
        # важливістю й лишаються найпотрібніші (див. ``_fit_schemas``).
        schemas = self._fit_schemas(available)
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

    def _schema_budget(self) -> int:
        """Скільки токенів відведено під схеми інструментів.

        Береться зі СПІЛЬНОГО розподілу бюджету (:meth:`adopt_context_window`),
        щоб схеми не обліковувались двічі — і не «40% навмання».
        """
        limit = int(getattr(self.session, "context_limit", 0) or 0)
        if limit <= 0:
            return 0
        budget_model = getattr(self, "_context_budget", None)
        if budget_model is not None and budget_model.window:
            ceiling = max(512, int(budget_model.window * 0.25))
            return min(ceiling, max(512, budget_model.window
                                    - budget_model.answer
                                    - budget_model.safety
                                    - budget_model.system))
        return max(512, int(limit * 0.25))

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
        """
        if not self.lazy_mode():
            return ""
        router = getattr(self, "_lazy_router", None)
        if router is None:
            return ""
        return router.catalog_text()

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

    def _fit_schemas(self, schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Лишити стільки схем, скільки реально вміщається у вікно моделі.

        Пріоритет — у :data:`SCHEMA_PRIORITY`: без читання й запису файлів
        агент не працює зовсім, а без знімка сторінки — просто працює
        гірше. Коли місця бракує, ми прибираємо ДРУГОРЯДНІ схеми (а не
        мовчки переповнюємо контекст), і кажемо про це в лог.

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
        budget_model = getattr(self, "_context_budget", None)
        if budget_model is not None and budget_model.window:
            # Частка схем у бюджеті: не більше чверті вікна й не більше
            # того, що лишилось після системи та резерву відповіді.
            ceiling = max(512, int(budget_model.window * 0.25))
            budget = min(ceiling, max(512, budget_model.window
                                      - budget_model.answer
                                      - budget_model.safety
                                      - budget_model.system))
        else:
            # Бюджет ще не пораховано (перший хід до сервера) — беремо
            # обережні 25%: менше, ніж «40% навмання», і саме стільки, щоб
            # лишилось місце розмові.
            budget = max(512, int(limit * 0.25))
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
        if len(kept) < len(schemas):
            LOG.info("Схем інструментів обрізано під вікно %s "
                     "(бюджет схем %s, використано %s): %s з %s",
                     limit, budget, used, len(kept), len(schemas))
        return kept

    # ── лінивий реєстр інструментів ────────────────────────────────────────
    def lazy_router(self) -> "tool_lazy.LazyToolRouter":
        """Лінивий реєстр інструментів (створюється за потреби).

        Живе на раннері, бо переживає кроки одного завдання: те, що модель
        завантажила на кроці 2, має лишатись доступним на кроці 5 — інакше
        вона завантажувала б ту саму схему щоразу.
        """
        router = getattr(self, "_lazy_router", None)
        if router is None:
            router = tool_lazy.LazyToolRouter(priority=SCHEMA_PRIORITY,
                                             emit=self._emit)
            self._lazy_router = router
        return router

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
        if name.startswith("router:"):
            return self._call_router_intent(name[len("router:"):], _arguments_dict(arguments))
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

    def _call_router_intent(self, intent: str, arguments: dict[str, Any]) -> ToolResult:
        """Викликати конкретний intent MCP-роутера через підключений сервер."""
        manager = self.mcp_manager
        if manager is None:
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
    def _run_hints(self) -> bool:
        """Виконати дії, які знайшов роутер, замість порожньої балачки.

        Повертає True, якщо хід ЗАВЕРШЕНО (є справжній результат і
        відповідь уже показано). False означає «хід не завершено» — і тоді
        викликач дивиться на :attr:`_hints_need_continue`.

        Виконання йде через ТОЙ САМИЙ оркестратор, що й виклики моделі:
        аргументи перевіряються за схемою, невідомий інструмент не
        виконується, а користувач бачить людське пояснення, а не сирий
        вивід інструмента.
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
        answer = draft.text or "\n\n".join(produced)
        # Роутер відповідає з реальних результатів, але його підсумок може
        # містити числа/назви, яких у виводі не було. Той самий шар правди.
        answer = self._enforce_evidence(answer, step=0)
        self._last_answer = answer
        self.session.add_assistant({"role": "assistant", "content": answer})
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
        changed = [hint.tool for hint in hints
                   if hint.tool in ("write_file", "edit_file", "append_file")]
        if not changed and self._asks_for_change():
            self._emit("status", "Прочитав файл — тепер вношу зміну.")
            # КЛЮЧОВЕ: читача просимо продовжити, а не закінчуємо хід.
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
        # Довга фраза навіть із «привіт» усередині — це вже завдання.
        return len(text) <= 200

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
        messages = self.session.build()
        started = time.perf_counter()
        try:
            result = client.chat(messages, tools=None, temperature=0.6,
                                 max_tokens=min(700, int(self.llm_settings.max_tokens)))
        except LLMError as exc:
            self._error = str(exc)
            self._emit("error", self._error)
            return
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
            # Локальні моделі іноді мовчать на вітання. Це не помилка —
            # краще коротка чесна відповідь, ніж «порожня відповідь».
            text = "Привіт! Готовий допомогти з кодом — напиши, що зробити."
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
        return info.primary in (task_plan.EDIT, task_plan.CREATE,
                                task_plan.REFACTOR, task_plan.DEBUG)

    def _emit(self, kind: str, text: str = "", **data: Any) -> None:
        self.events.put(AgentEvent(kind, text, data))

    def _run(self, text: str) -> None:
        self.session.workspace = self.workspace
        self.session.add_user(text)
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
        )
        ok = False
        try:
            if not self.llm_settings.model:
                raise LLMError("Модель не вибрана")
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
            if self._pending_hint:
                names = ", ".join(hint.describe() for hint in self._pending_hint[:4])
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
            if forced_tools and not self.tools_enabled:
                # Режим «Чат»: інструментів немає за задумом. Чесна відповідь
                # замість вигадки.
                note = ("Це запит про реальний стан проєкту, але зараз увімкнено "
                        "режим «Чат» без інструментів. Перемкни режим на «Агент», "
                        "і я перевірю фактами.")
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
            if self._is_small_talk() and not forced_tools:
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
        # Історія задач: потрібна інструменту ``memory_task_history``.
        bridge.record_turn(
            task=task or "поточне завдання",
            action=response_engine.preview_of(self._last_answer or "", 200),
            status="ok" if ok else "error",
            files=changed,
            tools=[item.name for item in observations if item.name])

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

        try:
            return client.chat_stream(
                messages,
                tools=tools_arg,
                tool_choice="auto",
                on_text=on_text,
                on_reasoning=on_reasoning,
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
        for step in range(self.max_steps):
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
                # ── «Спробую ще раз» між однаковими викликами ──────────
                # На скріншоті користувача ця фраза повторилась 14 разів і
                # засмітила чат. Якщо модель лише обіцяє дію й одразу
                # викликає той самий інструмент — це шум, а не відповідь.
                if visible and response_engine.promises_action(visible):
                    LOG.debug("Приховано обіцянку між викликами: %s", visible[:80])
                    visible = ""
            if visible:
                # Текст без подальших інструментів — це вже фінальна
                # відповідь; інакше модель коментує, що робитиме далі.
                final = not result.tool_calls
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
                    self._error = "Модель повернула порожню відповідь."
                    self._emit("error", self._error)
                    return
                # Модель написала код у чат замість того, щоб створити файли
                # («Створимо package.json:» + блок ```). Без цього повтору
                # агент завершувався з порожньою роботою на диску.
                if step < self.max_steps - 1 and self._wrote_code_in_chat(result.content):
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
                        or self._wrote_code_in_chat(result.content)):
                    if self._run_hints():
                        return
                    # Роутер прочитав файл, але правку ще не зробив. Хід НЕ
                    # завершено: просимо модель внести зміну конкретним
                    # інструментом. Без цього агент зупинявся після читання
                    # й відповідав «Готово. Результат: read_file», хоч файл
                    # лишався незміненим (перевірено живим прогоном).
                    if self._hints_need_continue and step < self.max_steps - 1:
                        self.session.add_user(
                            "Файл прочитано, але зміни ще НЕ внесено. Зроби "
                            "правку зараз: виклич edit_file (або write_file, "
                            "якщо треба переписати файл цілком) з точними "
                            "old_string і new_string зі щойно прочитаного "
                            "вмісту. Не відповідай текстом і не повторюй код "
                            "у чаті — потрібна реальна зміна на диску."
                        )
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
                if (self._expects_action()
                        and self._text_protocol_asked < TEXT_PROTOCOL_ATTEMPTS
                        and step < self.max_steps - 1):
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
                if (self._expects_action()
                        and _promises_action(result.content)
                        and not self._touched_files):
                    if step < self.max_steps - 1 and not self._promise_warned:
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
                                   observation.output or observation.error)))
                    break          # наступний хід моделі — з новою вказівкою
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
            self._emit("status", f"Досягнуто ліміт кроків ({self.max_steps}).")
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
                summary = self._enforce_evidence(summary, step=self.max_steps)
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
        truncated = cut_by_tokens or step >= max(1, int(self.max_steps))
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

    @staticmethod
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
        answer = self._enforce_evidence(answer, step=self.max_steps)
        self._last_answer = answer
        self._emit("assistant", answer, offline=True)


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
