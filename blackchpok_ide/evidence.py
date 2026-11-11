"""Правило «немає доказу — немає твердження про проєкт».

Навіщо окремий модуль. Локальна модель регулярно відповідає впевнено там,
де не має жодних даних: «Знайдено 1 файл», «у проєкті 12 тестів», «функція
працює коректно». Користувач не може відрізнити факт від вигадки, бо обидва
виглядають однаково.

Правило просте:

    NO TOOL EVIDENCE — NO FACTUAL PROJECT CLAIM

Тобто будь-яке твердження про **реальний стан проєкту** (кількість файлів,
імена, вміст, наявність функцій, стан сервісів, результати тестів,
налаштування) дозволене ЛИШЕ тоді, коли в цьому ході був успішний виклик
інструмента, який це твердження підтверджує.

Модуль не залежить від tkinter і не робить мережевих викликів.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

LOG = logging.getLogger("blackchpok.evidence")

# ─────────────────────────────────────────────────────────────────────────────
# Що вважаємо «твердженням про проєкт»
# ─────────────────────────────────────────────────────────────────────────────

#: Слова, після яких у тексті зазвичай іде ФАКТ, а не думка.
#:
#: Наприклад: «у проєкті 37 .py файлів», «файл server.py містить …»,
#: «тести пройшли», «сервер запущено на порту 8080».
_FACTUAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Кількості: «37 файлів», «12 тестів», «5 помилок», а також
    # «170 Python-файлів», де між числом і предметом стоїть слово.
    # Раніше тут був ``\s*`` — і найприродніше формулювання «170
    # Python-файлів» НЕ розпізнавалось як факт, тож вигадана кількість
    # проходила перевірку взагалі без згадки.
    re.compile(r"\b\d{1,6}[^\n]{0,24}?"
               r"(?:файл|тест|рядк|помил|функці|клас|модул|папк|директор)\w*", re.I),
    # Твердження про вміст конкретного файлу.
    re.compile(r"\b(?:файл|модуль|скрипт)\s+[\w./\\-]+\.[A-Za-z0-9]{1,8}\b", re.I),
    # «у проєкті є / немає», «тести пройшли / впали».
    re.compile(r"\b(?:у проєкті|в проєкті|в теці|у теці)\s+(?:є|немає|знаход)", re.I),
    re.compile(r"\b(?:тести|перевірки|tests?)\s+(?:пройшл|проход|впал|failed|passed)", re.I),
    # Стан сервісів і налаштувань.
    re.compile(r"\b(?:сервер|модель|mcp|порт|конфіг|налаштуванн)\w*\s+"
               r"(?:запущ|працю|відповіда|піднят|встановлен|увімкнен|вимкнен)", re.I),
    # Явні «я перевірив / я подивився».
    re.compile(r"\b(?:я\s+)?(?:перевірив|подивився|прочитав|запустив|знайшов)\b", re.I),
)

#: Слова, які роблять речення ОЦІНКОЮ, а не фактом: такі твердження не
#: потребують доказу з інструмента.
_OPINION_MARKERS: tuple[str, ...] = (
    "рекоменд", "раджу", "краще", "варто", "можна", "пропоную", "на мою думку",
    "ймовірно", "схоже", "можливо", "приблизно", "орієнтовно", "як правило",
    "зазвичай", "у такому разі", "якщо", "потрібно", "треба", "слід",
)

#: Прямі факти, які НЕ глушаться маркерами оцінки. Вузько навмисно: лише
#: те, що можна перевірити інструментом і що легко вигадати.
_HARD_FACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Кількість перед іменником: «300 файлів», «12 тестів».
    re.compile(r"\b\d{1,6}\s*(?:файл|тест|рядк|помил|функці|клас|модул|папк)",
               re.I),
    # Ім'я файлу з розширенням.
    re.compile(r"\b[\w./\\-]+\.[A-Za-z0-9]{1,8}\b"),
    # Твердження про стан сервісу з портом.
    re.compile(r"\b(?:порт|port)\s*\d{2,5}\b", re.I),
)

#: Інструменти, які дають право на твердження про файли й структуру.
FILE_TOOLS: frozenset[str] = frozenset({
    "read_file", "list_dir", "search_text", "find_files", "project_tree",
    "write_file", "edit_file", "append_file", "create_file", "delete_file",
    "rename_file", "get_project_structure", "inspect_dependencies",
})

#: Інструменти, які дають право на твердження про запуск і тести.
RUN_TOOLS: frozenset[str] = frozenset({
    "run_command", "run_tests", "build_project", "python_check",
    "app_start", "app_stop", "app_status", "app_restart",
})

#: Інструменти, які дають право на твердження про стан сервісів.
SERVICE_TOOLS: frozenset[str] = frozenset({
    "app_status", "internet_status", "python_check",
})

#: Інструменти, які дають право на твердження про зображення й інтерфейс.
VISUAL_TOOLS: frozenset[str] = frozenset({
    "app_screenshot", "project_screenshot", "window_screenshot", "web_screenshot",
    "capture_screen", "capture_region", "capture_window", "capture_display",
    "capture_live_preview", "capture_browser_page", "crop_screenshot",
    "inspect_screenshot_regions", "get_screenshot_metadata",
    "get_image_dimensions", "compare_screenshots",
    "analyze_visual_difference", "analyze_image", "analyze_screenshot",
    "web_inspect", "web_console", "web_audit",
})


@dataclass
class Evidence:
    """Один факт, підтверджений інструментом."""

    name: str
    ok: bool
    output: str = ""
    error: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> str:
        return self.output if self.ok else self.error


@dataclass
class EvidenceCheck:
    """Результат перевірки відповіді проти доказів."""

    #: Твердження, які не підкріплені жодним успішним викликом.
    unsupported: list[str] = field(default_factory=list)
    #: Чи був хоч один успішний виклик інструмента в цьому ході.
    has_any_success: bool = False
    #: Чи стосувався якийсь успішний виклик проєкту (файли/запуск).
    has_project_evidence: bool = False
    #: Чи відповідь обрізана лімітом кроків або токенів.
    truncated: bool = False
    #: Загальна оцінка: чи можна показувати відповідь як фактичну.
    supported: bool = True

    @property
    def needs_disclaimer(self) -> bool:
        return bool(self.unsupported) or self.truncated

    def summary(self) -> str:
        if not self.has_any_success:
            return "жодного успішного виклику інструмента в цьому ході"
        if self.unsupported:
            return f"без доказу: {len(self.unsupported)} тверджень"
        return "усі твердження мають доказ"


# ─────────────────────────────────────────────────────────────────────────────
# Аналіз тексту
# ─────────────────────────────────────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    """Розбити текст на речення, не чіпаючи блоки коду."""
    body = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", body)
    return [part.strip() for part in parts if part.strip()]


def _looks_opinion(sentence: str) -> bool:
    """Чи це ОЦІНКА (порада), а не факт про проєкт.

    ВАЖЛИВО про порядок перевірок у :func:`factual_claims`: оцінка не
    потребує доказу ЛИШЕ тоді, коли в реченні немає жодного факт-патерну
    з числом або іменем файлу. Інакше «Потрібно знати: у проєкті 300
    файлів» проходило як порада, і вигадане число лишалось без докору.
    """
    low = sentence.lower()
    return any(marker in low for marker in _OPINION_MARKERS)


def _has_hard_fact(sentence: str) -> bool:
    """Чи є в реченні прямий факт (число з іменником або шлях до файлу).

    Саме такі речення не можна глушити маркерами оцінки: «на мою думку, у
    проєкті 300 файлів» — це все одно твердження про кількість.
    """
    for pattern in _HARD_FACT_PATTERNS:
        if pattern.search(sentence):
            return True
    return False


def factual_claims(text: str) -> list[str]:
    """Витягнути речення, які виглядають як твердження про реальний стан.

    Оцінки й поради («раджу використати кеш») відсіюються: вони не
    потребують доказу з інструмента. Але якщо в реченні є ПРЯМИЙ факт
    (кількість, ім'я файлу, стан сервісу) — воно лишається фактом навіть
    зі словами «потрібно» чи «на мою думку».
    """
    found: list[str] = []
    for sentence in _sentences(text):
        if len(sentence) < 8:
            continue
        if not any(pattern.search(sentence) for pattern in _FACTUAL_PATTERNS):
            continue
        if _looks_opinion(sentence) and not _has_hard_fact(sentence):
            continue
        found.append(sentence)
    return found


def _covers(sentence: str, evidence: Sequence[Evidence]) -> bool:
    """Чи підтверджує хоч один доказ це речення.

    Перевірка навмисно М'ЯКА: ми не беремося доводити семантичну
    відповідність (це робота моделі), але відсіюємо очевидні випадки, коли
    твердження не має жодного відношення до жодного результату інструмента.

    Числа порівнюються ЯК ЧИСЛА, а не підрядком. Раніше «у проєкті 12
    файлів» підтверджувалось доказом «line 120 has TODO» (бо «12» є
    підрядком «120»), і вигадане число виглядало доведеним.

    ОДНЕ ВИКЛЮЧЕННЯ — КІЛЬКІСТЬ. Якщо речення називає число з предметом
    («170 Python-файлів»), це мусить бути САМЕ ЦЕ ЧИСЛО в доказі. Раніше
    тут спрацьовував широкий збіг за словами, і вигадане «170» проходило
    перевірку лише тому, що в доказі була тека `blackchpok_ide`
    (перевірено наживо: справжня кількість — 118, агент назвав 170).
    """
    low = sentence.lower()
    claimed = _counted_numbers(low)
    for item in evidence:
        if not item.ok:
            continue
        body = item.body or ""
        if not body.strip():
            continue
        body_low = body.lower()
        body_numbers = set(re.findall(r"\b\d+\b", body_low))
        if claimed:
            # Кількість названо — потрібне точне число, інакше цей доказ
            # не підтверджує речення (хоч би скільки слів збігалось).
            if any(number in body_numbers for number in claimed):
                return True
            continue
        # 1. Будь-яке число з твердження як ОКРЕМЕ число в доказі.
        numbers = re.findall(r"\b\d+\b", low)
        if numbers and any(number in body_numbers for number in numbers):
            return True
        # 2. Ім'я файлу/шляху з твердження є в доказі.
        names = re.findall(r"[\w-]+\.(?:py|js|ts|html|css|json|md|txt|gguf)", low)
        if names and any(name in body_low for name in names):
            return True
        # 3. Слово-предмет із твердження є в доказі (широке покриття).
        words = {word for word in re.findall(r"[\w\u0400-\u04FF]{5,}", low)}
        if words and len(words & set(re.findall(r"[\w\u0400-\u04FF]{5,}", body_low))) >= 2:
            return True
        # 4. Доказ — короткий підсумок запуску (exit=0, OK, пройшло).
        if any(marker in body_low for marker in ("exit=0", "ok ", "passed", "успішно")):
            if any(word in low for word in ("тест", "перевір", "запуст", "пройшл")):
                return True
    return False


#: Число з предметом: «170 Python-файлів», «12 тестів», «3 помилки».
_COUNTED = re.compile(
    r"\b(\d{1,6})\s*(?:[\w-]*\s*)?"
    r"(?:файл|тест|рядк|помил|функці|клас|модул|папк|директор|запис)", re.I)


def _counted_numbers(sentence: str) -> set[str]:
    """Числа, які в реченні названі КІЛЬКІСТЮ чогось конкретного."""
    return {match.group(1) for match in _COUNTED.finditer(sentence or "")}


#: Кількість, ЯКУ НАЗВАВ САМ ІНСТРУМЕНТ: «усього: 118», «файлів 118»,
#: «.py: 118», «— 121 записів».
_EVIDENCE_COUNTS = (
    re.compile(r"усього\s*:?\s*(\d{1,6})", re.I),
    re.compile(r"файлів\s*:?\s*(\d{1,6})", re.I),
    re.compile(r"\bпоказано\s+(\d{1,6})\s+з\s+(\d{1,6})", re.I),
    re.compile(r"^[\w.\-]+:\s*(\d{1,6})\s*$", re.M),
    re.compile(r"—\s*(\d{1,6})\s*запис", re.I),
)


def evidence_counts(items: Iterable[Evidence]) -> list[tuple[str, str]]:
    """Кількості, які інструменти назвали САМІ: ``[(підпис, число)]``.

    Навіщо. Модель не вміє рахувати рядки у виводі — наживо вона назвала
    100, 170, 211 і 310 файлів при справжніх 118. Але інструмент уже
    містить готову кількість («Підсумок за типами: .py: 118»). Тож замість
    самих лише докорів показуємо користувачу СПРАВЖНЄ число з доказу.

    Підпис обов'язковий. Без нього два різні підсумки — «141 у теці з
    підтеками» і «314 по всьому проєкту» — виглядали як суперечність: у
    попередженні з'являлось «правильна кількість: 314», хоч питання було
    про теку з 118 файлами.
    """
    found: list[tuple[str, str]] = []
    for item in items:
        if not item.ok:
            continue
        body = item.body or ""
        # Підпис = назва інструмента + предмет (перший рядок): саме він
        # каже, ДО ЧОГО належить число. Без предмета «141» і «314»
        # виглядали як суперечність.
        subject = ""
        for line in body.splitlines():
            if line.strip():
                subject = line.strip().split("—")[0].strip()[:40]
                break
        tool = str(item.name or "інструмент")
        label = f"{tool}: {subject}" if subject else tool
        for pattern in _EVIDENCE_COUNTS:
            for match in pattern.finditer(body):
                # «показано 5 з 30» — беремо ЗАГАЛЬНУ кількість (30).
                value = match.group(match.lastindex or 1)
                if not value:
                    continue
                if any(value == existing for _label, existing in found):
                    continue
                found.append((label, value))
    return found


def check(
    answer: str,
    evidence: Iterable[Evidence] = (),
    *,
    truncated: bool = False,
    requires_project_fact: bool = False,
) -> EvidenceCheck:
    """Перевірити, чи підкріплені твердження відповіді доказами.

    ``requires_project_fact=True`` означає, що запит користувача стосувався
    реального стану проєкту (кількість файлів, вміст, тести). Тоді відповідь
    без жодного успішного виклику вважається непідтвердженою цілком.

    Тихий прохід закритий окремо: якщо в ході НЕ БУЛО жодного успішного
    виклику, а відповідь усе ж містить факт-патерн — вона непідтверджена,
    навіть коли запит не визнали «про проєкт». Раніше ``check("Готово.")``
    і ``check("У проєкті 300 файлів")`` без доказів обидва повертали
    ``supported=True``, якщо класифікатор не побачив запиту про факти.
    """
    items = list(evidence)
    result = EvidenceCheck(truncated=truncated)
    result.has_any_success = any(item.ok and item.body.strip() for item in items)
    result.has_project_evidence = any(
        item.ok and item.name in (FILE_TOOLS | RUN_TOOLS | SERVICE_TOOLS | VISUAL_TOOLS)
        and item.body.strip() for item in items)

    claims = factual_claims(answer or "")
    for claim in claims:
        if not _covers(claim, items):
            result.unsupported.append(claim)

    # Запит про проєкт, але жодного доказу — усе твердження безпідставне.
    if requires_project_fact and not result.has_project_evidence:
        result.supported = False
        if not result.unsupported:
            result.unsupported.append("(жодного виклику інструмента про проєкт)")
    elif result.unsupported:
        result.supported = False
    elif claims and not result.has_any_success:
        # Факт у відповіді без ЖОДНОГО успішного виклику — це вигадка,
        # навіть якщо запит не розпізнали як «про проєкт».
        result.supported = False
        result.unsupported.extend(
            claim for claim in claims if claim not in result.unsupported)
    if truncated and claims:
        result.supported = False
    return result


def disclaimer(result: EvidenceCheck, *, tool_hint: str = "",
               known_counts: Iterable[tuple[str, str]] = ()) -> str:
    """Коротке чесне попередження для показу над відповіддю.

    ``known_counts`` — кількості, які інструменти назвали самі, з підписом
    джерела. Якщо вони є, попередження не лише каже «твердження без
    доказу», а й показує справжнє число: модель погано рахує рядки, а
    інструмент — добре.
    """
    lines: list[str] = []
    counts: list[str] = []
    for item in known_counts:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            label, value = str(item[0]), str(item[1])
            counts.append(f"{value} ({label})" if label else value)
        elif item:
            counts.append(str(item))
    if not result.has_any_success:
        lines.append(
            "⚠ Ця відповідь не підтверджена даними з проєкту: "
            "у цьому ході не було жодного успішного виклику інструмента.")
    elif result.unsupported:
        shown = "; ".join(claim[:120] for claim in result.unsupported[:3])
        lines.append(
            f"⚠ Частина тверджень не має доказу в результатах інструментів: "
            f"{shown}")
        if counts:
            lines.append(
                "Кількості, які повернули інструменти: "
                + "; ".join(counts[:3])
                + ". Число в тексті вище — не з інструмента, тому йому не "
                  "можна вірити; уточни, який саме підсумок потрібен.")
    if result.truncated:
        lines.append(
            "⚠ Роботу зупинено лімітом кроків або контексту — перевірка "
            "не завершена, висновки можуть бути неповними.")
    if lines and tool_hint:
        lines.append(f"Щоб отримати факт, попроси: «{tool_hint}».")
    return "\n".join(lines)


def needs_tools_for(question: str) -> bool:
    """Чи вимагає запит фактів про проєкт (а не думки)."""
    if not question:
        return False
    # Приведення типу: ``question`` може прийти з моделі чи JSON не рядком
    # (локальні моделі здатні віддати число). Без нього тут падало
    # ``AttributeError`` у шляху перевірки доказів.
    if not isinstance(question, str):
        question = str(question)
    low = question.lower().strip()
    # Питання про свіжі дані з мережі — окремий шлях, не проєкт.
    if any(word in low for word in ("погода", "курс", "ціна", "новини", "коштує")):
        return False
    # Маркери з межами слів: без них «спорт-сайт» ставав запитом про «порт»,
    # «переустанови пакет» — про «стан», а «стандарт коду» — теж про «стан».
    # Через це агент ішов у повний цикл з інструментами на запити, які їх не
    # потребують, і навпаки — не доходив, коли факт справді треба.
    _WORD_MARKERS = (
        "стан", "порт", "тест", "тести", "пройшли", "запусти", "запустити",
        "конфіг", "вміст", "містить", "перелічи", "налаштування",
    )
    words = set(re.findall(r"[\w'-]+", low))
    if any(marker in words for marker in _WORD_MARKERS):
        return True
    markers = (
        "скільки", "скількома", "які файли", "яка структура", "структур",
        "що в файлі", "що у файлі", "прочитай", "покажи файли",
        "покажи список", "список файлів", "де знаход", "де леж",
        "чи є", "чи працює", "чи все", "компіл", "порівняй", "mcp", "версі",
    )
    if any(marker in low for marker in markers):
        return True
    # «стан» як частина слова теж рахуємо: «стан_сервера», «стан-health».
    return bool(re.search(r"(?:^|[^\w])стан(?:[^\w]|$)", low))


__all__ = [
    "Evidence",
    "EvidenceCheck",
    "FILE_TOOLS",
    "RUN_TOOLS",
    "SERVICE_TOOLS",
    "VISUAL_TOOLS",
    "check",
    "disclaimer",
    "evidence_counts",
    "factual_claims",
    "needs_tools_for",
]
