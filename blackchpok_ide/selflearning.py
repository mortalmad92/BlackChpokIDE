"""Самонавчання агента: власні помилки стають правилами наступного разу.

Чого тут НЕМАЄ і чому. Модуль не «тренує ваги» й не змінює модель: локальна
модель у пам'яті — необроблений GGUF, і жодного тренування під час роботи
не існує. Твердження «агент навчився на своїх помилках» тут означає рівно
те, що означає в реальній практиці агентних систем:

1. **спостереження** — під час ходу агент уже бачить, що вийшло: виклик
   упав, аргументи відхилено, той самий виклик повторено тричі, файл
   довелось переписати чотири рази, кроків не вистачило;
2. **висновок** — з цих фактів робиться коротке правило (урок) про
   КОНКРЕТНУ ситуацію;
3. **нагадування** — наступного разу, коли задача схожа, урок
   підкладається в контекст ДО того, як модель почне діяти.

Уроки живуть у NEUROMESH (тип ``lesson``): їх видно в панелі пам'яті, їх
можна підтвердити, виправити або видалити. Це принципово — «навчання», яке
не можна переглянути й виправити, це не навчання, а непередбачуваність.

Що НЕ стає уроком:

* випадкова помилка мережі (таймаут лікується повтором, а не правилом);
* одноразова невдача, яку модель уже виправила своїм наступним кроком;
* будь-що з приватного режиму («не зберігай»);
* вміст файлів — у пам'ять іде правило, а не код.

Модуль не тягне tkinter і не робить мережевих викликів: його можна
перевірити на підробленому місті пам'яті.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "Lesson",
    "NO_TESTS_ADVICE",
    "TurnFacts",
    "SelfLearning",
    "advice_chars",
    "describe_lessons",
    "extract_lessons",
    "format_lessons",
    "recall_limit",
]

LOG = logging.getLogger("blackchpok.selflearning")

#: Тип спогаду, у якому живе урок (див. ``pcmm.models.KINDS``).
LESSON_KIND = "lesson"

#: Скільки уроків максимум підкладаємо в контекст одного ходу (мале вікно).
RECALL_LIMIT = 4

#: Скільки уроків давати моделі з ВЕЛИКИМ вікном.
#:
#: Чотири уроки — це межа для локальної моделі на 8k, де кожен рядок
#: промпту дорогий. Хмарна модель із вікном 128k–1M може взяти значно
#: більше, і саме на довгих завданнях це важливо: чим більше висновків
#: модель бачить, тим рідше повторює вже виправлені помилки.
RECALL_LIMIT_LARGE = 16

#: З якого розміру вікна вмикається великий ліміт уроків.
LARGE_WINDOW_TOKENS = 100_000

#: Обрізання одного уроку в промпті (символи).
ADVICE_CHARS = 200

#: Обрізання одного уроку для великого вікна.
ADVICE_CHARS_LARGE = 600


def recall_limit(window: int = 0) -> int:
    """Скільки уроків підкладати моделі з таким вікном."""
    return RECALL_LIMIT_LARGE if int(window or 0) >= LARGE_WINDOW_TOKENS else RECALL_LIMIT


def advice_chars(window: int = 0) -> int:
    """Скільки символів поради віддавати для такого вікна."""
    return (ADVICE_CHARS_LARGE if int(window or 0) >= LARGE_WINDOW_TOKENS
            else ADVICE_CHARS)

#: Скільки уроків максимум записуємо за один хід (решта — шум).
WRITE_LIMIT = 3

#: Впевненість уроку, виведеного з ПІДТВЕРДЖЕНОГО результату інструмента.
#: Не 1.0: урок зроблено з одного випадку, і людина має мати змогу його
#: виправити (``memory_update`` / ``memory_feedback``).
OWN_CONFIDENCE = 0.55

#: Ознаки «мережевого» збою: правило з нього не виводять (повтор лікує).
_FLAKY_MARKERS = (
    "timeout", "timed out", "таймаут", "connection", "з'єднання", "econnrefused",
    "10054", "429", "503", "kill", "aborted", " скасовано",
)

#: Інструменти запису, для яких «переписав той самий файл кілька разів» —
#: сигнал, що треба ``edit_file`` замість ``write_file``.
_WRITE_TOOLS = ("write_file", "append_file", "edit_file")

#: Скільки повторних записів одного файлу вважати марнотратством.
REWRITE_LIMIT = 3

#: Скільки разів той самий виклик з тими самими аргументами — зациклення.
REPEAT_LIMIT = 2

#: Ознаки того, що тести не знайшли (``unittest`` віддає код 5).
_NO_TESTS_MARKERS = (
    "no tests ran", "ran 0 tests", "executed 0 tests",
)

#: Порада, яка лікує «нуль тестів» у цьому проєкті.
#:
#: Перевірено окремо перед тим, як це писати: у теці ``tests`` немає
#: ``__init__.py``, тому ``python -m unittest discover`` від кореня завжди
#: дає «Ran 0 tests» і код 5. З ``-s tests`` тести знаходяться. Модель
#: бачила код 5, вважала це збоєм і повторювала ту саму команду — за годину
#: живого прогону таких повторів було 21.
NO_TESTS_ADVICE = (
    "«Ran 0 tests» означає, що тека запуску неправильна, а не що тестів "
    "немає: запускай `python -m unittest discover -s tests -p \"test_*.py\" -v` "
    "або один модуль `python -m unittest tests.test_ім'я -v`. Не переписуй "
    "тестовий файл заради цього — його вміст на результат не впливає."
)


def _clip(text: str, limit: int) -> str:
    body = " ".join(str(text or "").split())
    return body if len(body) <= limit else body[: limit - 1] + "…"


def _is_flaky(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _FLAKY_MARKERS)


def _is_no_tests(text: str) -> bool:
    """Чи це «нуль тестів» (а не справжній збій тестів)."""
    low = (text or "").lower()
    return any(marker in low for marker in _NO_TESTS_MARKERS)


@dataclass
class Lesson:
    """Одне правило, виведене зі справжнього ходу агента."""

    #: Ситуація, у якій урок діє (словами, як її шукати в пам'яті).
    trigger: str = ""
    #: Що саме пішло не так.
    mistake: str = ""
    #: Що робити натомість.
    advice: str = ""
    #: Ознака джерела (для пояснення в пам'яті).
    source: str = "самонавчання: результат ходу"
    confidence: float = OWN_CONFIDENCE
    #: Як часто це траплялось у ЦЬОМУ ході (для ваги правила).
    times: int = 1

    def content(self) -> str:
        """Текст спогаду: його читає і модель, і людина в панелі пам'яті."""
        head = f"Урок ({self.trigger}): {self.advice}"
        if self.mistake:
            head += f" Причина: {self.mistake}"
        if self.times > 1:
            head += f" Траплялось {self.times} рази за хід."
        return head

    def prompt_line(self) -> str:
        """Рядок для контексту моделі (коротко: місце в промпті дороге)."""
        return f"- {self.advice}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "mistake": self.mistake,
            "advice": self.advice,
            "confidence": self.confidence,
            "times": self.times,
        }


@dataclass
class TurnFacts:
    """Факти завершеного ходу — саме з них робляться висновки.

    Окрема структура, а не сам раннер: правила перевіряються без моделі,
    без мережі й без вікна.
    """

    #: (назва інструмента, успіх, перший змістовний рядок виводу/помилки)
    calls: list[tuple[str, bool, str]] = field(default_factory=list)
    #: Файли, які справді змінились цього ходу.
    changed_files: list[str] = field(default_factory=list)
    #: Скільки разів агент правив синтаксис за цей хід.
    syntax_repairs: int = 0
    #: Чи модель питала дозвіл замість роботи.
    asked_permission: bool = False
    #: Скільки кроків використано і який був ліміт.
    steps: int = 0
    max_steps: int = 0
    #: Чи хід завершився успішно.
    ok: bool = True
    #: Мета словами (за нею урок шукатиметься наступного разу).
    goal: str = ""
    #: Тип наміру (create/edit/debug…).
    intent_type: str = ""

    def trigger_text(self) -> str:
        """Ознака ситуації: мета + тип наміру (для пошуку в пам'яті)."""
        goal = " ".join(str(self.goal or "").split())[:160]
        if goal and self.intent_type:
            return f"{self.intent_type}: {goal}"
        return goal or self.intent_type or "завдання"


def _repeat_pairs(calls: Sequence[tuple[str, bool, str]]) -> list[tuple[str, int]]:
    """Назви інструментів, які викликали поспіль із тим самим результатом."""
    counts: dict[tuple[str, str], int] = {}
    for name, _ok, text in calls:
        key = (str(name or ""), _clip(text, 80))
        counts[key] = counts.get(key, 0) + 1
    found: dict[str, int] = {}
    for (name, _text), count in counts.items():
        if count > REPEAT_LIMIT:
            found[name] = max(found.get(name, 0), count)
    return sorted(found.items(), key=lambda item: -item[1])


def _file_write_counts(files: Iterable[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for path in files or ():
        clean = str(path or "").strip()
        if clean:
            counts[clean] = counts.get(clean, 0) + 1
    return sorted(((path, count) for path, count in counts.items()
                   if count >= REWRITE_LIMIT), key=lambda item: -item[1])


def extract_lessons(facts: TurnFacts) -> list[Lesson]:
    """Вивести уроки з фактів ходу. Порожній список — «вчитись нема чого».

    Правила навмисно конкретні: загальні поради («пиши якісний код») у
    промпті нічого не змінюють, а місце займають.
    """
    trigger = facts.trigger_text()
    lessons: list[Lesson] = []
    calls = list(facts.calls or [])

    # ── 1. Зациклення на тому самому виклику ───────────────────────────────
    for name, count in _repeat_pairs(calls)[:2]:
        lessons.append(Lesson(
            trigger=trigger,
            mistake=f"той самий виклик «{name}» повторено {count} разів",
            advice=(f"Не повторюй «{name}» з тими самими аргументами: зміни "
                    f"аргументи, візьми інший інструмент або скажи, чого бракує."),
            confidence=0.7, times=count))

    # ── 2. Помилка інструмента, яку потім виправлено ───────────────────────
    # Правило має сенс лише тоді, коли модель СПРАВДІ виправилась: інакше
    # це просто збій, а не навик.
    failed = [(name, text) for name, ok, text in calls if not ok]
    succeeded = {name for name, ok, _text in calls if ok}
    for name, text in failed[:2]:
        if name not in succeeded or _is_flaky(text):
            continue
        lessons.append(Lesson(
            trigger=trigger,
            mistake=f"перший виклик «{name}» впав: {_clip(text, 120)}",
            advice=(f"«{name}» у цьому проєкті спершу впав — перевір "
                    f"аргументи й шлях перед викликом."),
            confidence=0.5))

    # ── 3. Синтаксис довелось правити ──────────────────────────────────────
    if facts.syntax_repairs > 0 and facts.changed_files:
        lessons.append(Lesson(
            trigger=trigger,
            mistake=(f"записаний код не компілювався "
                     f"({facts.syntax_repairs} раз(и) виправлень)"),
            advice=("Після запису Python-файлу одразу виклич python_check; "
                    "не звітуй «готово», поки синтаксис не перевірено."),
            confidence=0.65, times=facts.syntax_repairs))

    # ── 4. Модель питала дозвіл замість роботи ─────────────────────────────
    if facts.asked_permission:
        lessons.append(Lesson(
            trigger=trigger,
            mistake="модель спитала дозвіл замість виконання",
            advice=("Коли користувач просить створити річ — створюй файли "
                    "інструментами, а не пропонуй наступні кроки."),
            confidence=0.6))

    # ── 5. Кроків не вистачило ─────────────────────────────────────────────
    if facts.max_steps and facts.steps >= facts.max_steps and not facts.ok:
        lessons.append(Lesson(
            trigger=trigger,
            mistake=f"вичерпано ліміт кроків ({facts.steps} з {facts.max_steps})",
            advice=("Завдання такого розміру не вкладається в типовий ліміт "
                    "кроків: або розбий його на частини, або підвищ рівень "
                    "свободи дій у налаштуваннях."),
            confidence=0.5))

    # ── 6. Той самий файл переписували багато разів ────────────────────────
    for path, count in _file_write_counts(facts.changed_files)[:1]:
        lessons.append(Lesson(
            trigger=trigger,
            mistake=f"файл {path} записано {count} разів за хід",
            advice=(f"Для правок у наявному файлі ({path}) використовуй "
                    f"edit_file з точними old_string/new_string, а не повний "
                    f"перезапис."),
            confidence=0.55, times=count))

    # ── 7. «Тестів не знайдено» ────────────────────────────────────────────
    # Найдовший цикл у живих прогонах: команда віддає код 5, модель вважає
    # це збоєм, переписує тестовий файл і запускає ту саму команду знову.
    # Правило конкретне: причина — тека запуску, а не вміст файлу.
    empty_runs = sum(1 for name, ok, text in calls
                     if name == "run_command" and _is_no_tests(text))
    if empty_runs:
        lessons.append(Lesson(
            trigger=trigger,
            mistake=(f"команда тестів {empty_runs} раз(и) не знайшла жодного "
                     f"тесту (код 5, «Ran 0 tests»)"),
            advice=NO_TESTS_ADVICE,
            confidence=0.75, times=empty_runs))

    # ── 8. Файли змінювались, але мети кроку не досягнуто ──────────────────
    # Ознака «робота вхолосту»: один і той самий .py записано кілька разів,
    # а хід усе одно невдалий. Тоді проблема не в синтаксисі, а в тому, що
    # модель не змінює САМЕ те місце.
    if not facts.ok and facts.changed_files:
        thumb = _file_write_counts(facts.changed_files)
        if thumb:
            path, count = thumb[0]
            lessons.append(Lesson(
                trigger=trigger,
                mistake=(f"файл {path} перезаписано {count} разів, а крок "
                         f"так і не завершився"),
                advice=("Якщо правка не дає результату з першого разу — не "
                        "перезаписуй файл заново. Прочитай його (read_file), "
                        "переконайся, що змінюєш САМЕ потрібний рядок, і "
                        "перевір наслідок командою, а не на око."),
                confidence=0.7, times=count))

    return lessons[:WRITE_LIMIT]


def format_lessons(lessons: Sequence[Lesson]) -> str:
    """Готовий блок для промпту (порожній рядок, якщо уроків немає)."""
    if not lessons:
        return ""
    lines = ["Висновки з попередніх спроб (врахуй, щоб не повторити):"]
    for lesson in lessons:
        lines.append(lesson.prompt_line())
    return "\n".join(lines)


def describe_lessons(lessons: Sequence[Lesson]) -> str:
    """Один рядок для журналу: скільком правилам агент навчився цього разу."""
    if not lessons:
        return "Самонавчання: нових висновків немає."
    return f"Самонавчання: {len(lessons)} нових висновків записано в пам'ять."


class SelfLearning:
    """Зв'язка «факти ходу → уроки в пам'��ті → нагадування наступного разу».

    ``bridge`` — будь-який об'єкт із ``remember_fact`` і ``service.search``
    (такий, як :class:`memory_bridge.MemoryBridge`). Помилка пам'яті не має
    ламати хід: без неї агент працює як раніше, лише без нагадувань.
    """

    def __init__(self, bridge: Any = None, *, enabled: bool = True) -> None:
        self.bridge = bridge
        self.enabled = bool(enabled)
        #: Що вивчено в останньому ході (для журналу й панелі).
        self.last_lessons: list[Lesson] = []

    # ── доступність ───────────────────────────────────────────────────────
    def ready(self) -> bool:
        if not self.enabled or self.bridge is None:
            return False
        ready = getattr(self.bridge, "ready", None)
        if callable(ready):
            try:
                return bool(ready())
            except Exception:                        # noqa: BLE001
                return False
        return True

    # ── запис ─────────────────────────────────────────────────────────────
    def learn_turn(self, facts: TurnFacts) -> list[Lesson]:
        """Вивести уроки з ходу й запам'ятати їх. Повертає ЗАПИСАНІ уроки."""
        self.last_lessons = []
        if not self.enabled:
            return []
        lessons = extract_lessons(facts)
        if not lessons:
            return []
        if not self.ready():
            # Уроки пораховані, але пам'ять недоступна — не вдаємо успіх.
            LOG.debug("Уроки не записано: пам'ять недоступна")
            return []
        remembered = getattr(self.bridge, "remember_fact", None)
        if not callable(remembered):
            return []
        saved: list[Lesson] = []
        for lesson in lessons:
            try:
                ok = remembered(
                    lesson.content(), kind=LESSON_KIND,
                    source=lesson.source, files=list(facts.changed_files)[:5],
                    task=_clip(facts.goal, 120),
                    confidence=lesson.confidence)
            except Exception:                        # noqa: BLE001
                LOG.debug("Урок не записано", exc_info=True)
                continue
            if ok:
                saved.append(lesson)
        self.last_lessons = saved
        return saved

    # ── нагадування ───────────────────────────────────────────────────────
    def hints(self, text: str, *, limit: int = 0, task: str = "",
              window: int = 0) -> list[str]:
        """Що агент уже знає про схожі ситуації (рядки для промпту).

        ``limit=0`` (типово) означає «порахувати з вікна моделі»: локальна
        отримує чотири уроки, хмарна з великим вікном — до шістнадцяти.
        Раніше число було константою для всіх, і модель із вікном 1M
        бачила рівно стільки ж, скільки локальна на 8k.
        """
        if not self.ready():
            return []
        service = getattr(self.bridge, "service", None)
        search = getattr(service, "search", None)
        if not callable(search):
            return []
        query = " ".join(str(text or "").split())[:240]
        if not query:
            return []
        want = int(limit) if int(limit or 0) > 0 else recall_limit(window)
        want = max(1, want)
        try:
            result = search(query, limit=want, kinds=[LESSON_KIND], task=task)
        except TypeError:
            try:
                result = search(query, limit=want, kinds=[LESSON_KIND])
            except Exception:                        # noqa: BLE001
                return []
        except Exception:                            # noqa: BLE001
            return []
        hits: Any = result.get("hits") if isinstance(result, Mapping) else result
        cap = advice_chars(window)
        lines: list[str] = []
        for hit in hits or ():
            memory = hit.get("memory") if isinstance(hit, Mapping) else None
            if not isinstance(memory, Mapping):
                continue
            if str(memory.get("kind") or "") != LESSON_KIND:
                continue
            body = " ".join(str(memory.get("content") or "").split())
            if not body:
                continue
            # Из спогаду беремо саму пораду: «Урок (…): ПОРАДА Причина: …»
            advice = _advice_of(body, limit=cap)
            if advice and advice not in lines:
                lines.append(advice)
            if len(lines) >= want:
                break
        return lines


_ADVICE = re.compile(r"Урок\s*\([^)]*\)\s*:\s*(.+?)(?:\s+Причина:|\s+Траплялось|$)",
                     re.DOTALL)


def _advice_of(content: str, *, limit: int = ADVICE_CHARS) -> str:
    """Витягти пораду з тексту уроку (інакше — перше речення)."""
    match = _ADVICE.search(content or "")
    body = match.group(1) if match else (content or "")
    return _clip(body, max(80, int(limit or ADVICE_CHARS)))
