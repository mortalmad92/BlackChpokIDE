"""Адаптивний контекст: глибина пам'яті підбирається під сам запит.

Проблема, яку це вирішує. Два крайні режими однаково погані:

* **тримати все** — вікно накопичує мегабайти, кожен запит дорожчий, модель
  губиться в довгому діалозі;
* **чистити після кожного ходу** — дёшево, але ламається безперервний
  ланцюг: «зроби крок 2 на основі кроку 1» без кроку 1 у вікні.

Тут — третій шлях: ГЛИБИНА залежить від того, що саме просять.

============================  ==============  ===========================
що в запиті                    лишаємо        чому
============================  ==============  ===========================
«продовж», «далі», «і ще»      багато          це прямий ланцюг роботи
правка/лагодження              середньо        потрібен попередній код
питання-факт                   мало            досить пошуку в пам'яті
============================  ==============  ===========================

І головне: перенесене в пам'ять НЕ зникає. Воно доступне пошуком у тому
самому чаті, у новому чаті й після перезапуску — бо пам'ять у проєкті
спільна (``pcmm``), а не прив'язана до розмови.

Що модуль НЕ робить: не «тренує» модель і не змінює її ваги. «Кешування на
льоту» тут означає рівно те, що воно означає в реальних агентних системах:
готові факти й знахідки лежать у пам'яті й підкладаються в контекст без
повторного пошуку (див. :func:`cache_key` і ``MemoryBridge``).

Модуль чистий: без tkinter, без мережі, без стану між викликами.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

__all__ = [
    "DEPTH_DEEP",
    "DEPTH_MEDIUM",
    "DEPTH_MINIMAL",
    "DEPTH_SHALLOW",
    "DIGEST_EXTRA",
    "Depth",
    "Mode",
    "Plan",
    "RequestError",
    "choose",
    "cache_key",
    "describe",
    "describe_request",
    "is_continuation",
    "parse_request",
    "plan_from_model",
    "plan_from_request",
]

# ── Глибина: скільки минулого лишати у вікні ───────────────────────────────
DEPTH_MINIMAL = "minimal"      # лише поточний запит
DEPTH_SHALLOW = "shallow"      # останній обмін
DEPTH_MEDIUM = "medium"        # кілька останніх обмінів
DEPTH_DEEP = "deep"            # уся історія, що вміщається у вікно

#: Скільки повідомлень лишати у вікні для кожної глибини.
#:
#: Числа навмисно «людські»: обмін — це репліка й відповідь, тож 6 — це
#: три останні обміни, а не «шість абстрактних рядків».
DEPTH_KEEP: dict[str, int] = {
    DEPTH_MINIMAL: 2,
    DEPTH_SHALLOW: 4,
    DEPTH_MEDIUM: 8,
    # ``DEEP`` означає «не чіпати вікно»: звільнятиме лише звичайний
    # механізм 85%, коли історія справді переповниться.
    DEPTH_DEEP: 0,
}

#: Скільки рядків хроніки додатково підкладати в промпт для кожної глибини.
DIGEST_EXTRA: dict[str, int] = {
    DEPTH_MINIMAL: 0,
    DEPTH_SHALLOW: 4,
    DEPTH_MEDIUM: 12,
    DEPTH_DEEP: 24,
}

#: Ознаки ПРЯМОГО продовження роботи: тут контекст критичний.
_CONTINUE_WORDS: tuple[str, ...] = (
    "продовж", "продовжуй", "далі", "і ще", "те саме", "так само",
    "наступн", "допис", "дозапис", "продовження", "continue", "next step",
)

#: Ознаки ПРАВКИ/ЛАГОДЖЕННЯ: потрібен попередній код і рішення.
_EDIT_WORDS: tuple[str, ...] = (
    "виправ", "полагодь", "лагодь", "зміни", "онови", "додай", "прибери",
    "перейменуй", "рефактор", "fix", "edit", "refactor",
)

#: Ознаки ПИТАННЯ-ФАКТУ: досить пошуку, історія не потрібна.
_FACT_WORDS: tuple[str, ...] = (
    "ціна", "курс", "погода", "новини", "скільки", "коли", "яка версія",
    "що таке", "поясни", "price", "weather", "what is",
)

#: Слова-зв'язки, які нічого не кажуть про намір.
_STOP: frozenset[str] = frozenset({
    "цей", "ця", "це", "мені", "тобі", "треба", "можна", "якщо", "коли",
    "щоб", "буде", "було", "вони", "воно", "дуже", "тепер", "зараз",
})


@dataclass(frozen=True)
class Mode:
    """Один режим контексту."""

    key: str
    label: str
    hint: str


#: Доступні режими. ``auto`` — типовий: глибина підбирається під запит.
AUTO = Mode("auto", "Адаптивно", "глибина залежить від запиту")
FRESH = Mode("fresh", "Свіжий", "у вікні лише останній обмін")
FULL = Mode("full", "Повний", "історичне накопичення, звільнення при 85%")

MODES: tuple[Mode, ...] = (AUTO, FRESH, FULL)

_BY_KEY: dict[str, Mode] = {item.key: item for item in MODES}

_ALIASES: dict[str, str] = {
    "адаптивно": "auto", "адаптивний": "auto", "турбо": "auto",
    "turbo": "auto", "розумний": "auto",
    "свіжий": "fresh", "чистий": "fresh", "fresh_context": "fresh",
    "повний": "full", "весь": "full", "накопичення": "full",
}


def mode_for(key: str) -> Mode:
    """Режим за ключем (невідоме → ``auto``)."""
    clean = str(key or "").strip().lower().replace("-", "_")
    if clean in _BY_KEY:
        return _BY_KEY[clean]
    return _BY_KEY.get(_ALIASES.get(clean, ""), _BY_KEY["auto"])


def is_continuation(text: str) -> bool:
    """Чи просить фраза ПРОДОВЖИТИ почате (а не почати нове)."""
    low = " ".join(str(text or "").lower().split())
    if not low:
        return False
    return any(word in low for word in _CONTINUE_WORDS)


@dataclass
class Depth:
    """Висновок про глибину контексту для одного запиту."""

    level: str = DEPTH_SHALLOW
    #: Скільки повідомлень лишити у вікні після ходу (0 — не чіпати).
    keep: int = 4
    #: Скільки рядків хроніки додати в промпт.
    digest_extra: int = 4
    #: Чому саме так (для журналу й для людини).
    reason: str = ""

    def is_deep(self) -> bool:
        return self.level == DEPTH_DEEP


@dataclass
class Plan:
    """Повний план контексту на один хід."""

    mode: str = "auto"
    depth: Depth = field(default_factory=Depth)
    #: Шукати в пам'яті ПЕРЕД дією (завжди так у режимі ``auto``).
    recall: bool = True
    #: Записати хід у пам'ять ПІСЛЯ дії.
    remember: bool = True
    #: Що саме шукати додатково (продовження роботи, згадки рішень).
    queries: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return (f"{self.mode}/{self.depth.level}: лишити "
                f"{self.depth.keep or 'все'}, хроніка "
                f"+{self.depth.digest_extra}")


def choose(text: str, *, mode: str = "auto", intent_type: str = "",
           steps_used: int = 0, has_files: bool = False) -> Plan:
    """Вибрати глибину контексту під ЦЕЙ запит.

    ``mode`` — вибір людини: ``auto`` (адаптивно), ``fresh`` (завжди
    мінімум), ``full`` (ніколи не чистити).
    """
    chosen = mode_for(mode)
    if chosen.key == "fresh":
        depth = Depth(DEPTH_SHALLOW, DEPTH_KEEP[DEPTH_SHALLOW],
                      DIGEST_EXTRA[DEPTH_SHALLOW],
                      "режим «свіжий»: у вікні лише останній обмін")
        return Plan(mode=chosen.key, depth=depth,
                    queries=[_query_of(text)])
    if chosen.key == "full":
        depth = Depth(DEPTH_DEEP, 0, DIGEST_EXTRA[DEPTH_DEEP],
                      "режим «повний»: історія не чиститься")
        return Plan(mode=chosen.key, depth=depth,
                    queries=[_query_of(text)])

    low = " ".join(str(text or "").lower().split())
    continuation = is_continuation(low) or str(intent_type or "") in (
        " continue", "continue", "revise")
    editing = any(word in low for word in _EDIT_WORDS) or has_files
    factual = any(word in low for word in _FACT_WORDS)

    # ── Порядок важливий ───────────────────────────────────────────────────
    # Продовження перевіряємо ПЕРШИМ: фраза «далі виправ те, що почав»
    # містить і ознаку продовження, і ознаку правки, але контекст їй
    # потрібен найглибший.
    if continuation:
        depth = Depth(DEPTH_DEEP, DEPTH_KEEP[DEPTH_MEDIUM],
                      DIGEST_EXTRA[DEPTH_DEEP],
                      "просять продовжити — потрібен ланцюг роботи")
        queries = [_query_of(text), "що вже зроблено", "попередні рішення"]
        return Plan(mode=chosen.key, depth=depth, queries=queries)
    if steps_used >= 6:
        # Довгий хід: усередині одного завдання контекст критичний.
        depth = Depth(DEPTH_DEEP, DEPTH_KEEP[DEPTH_MEDIUM],
                      DIGEST_EXTRA[DEPTH_MEDIUM],
                      f"у ході вже {steps_used} кроків — тримаю більше")
        return Plan(mode=chosen.key, depth=depth,
                    queries=[_query_of(text)])
    if editing:
        depth = Depth(DEPTH_MEDIUM, DEPTH_KEEP[DEPTH_MEDIUM],
                      DIGEST_EXTRA[DEPTH_MEDIUM],
                      "правка/лагодження — потрібен попередній код")
        return Plan(mode=chosen.key, depth=depth,
                    queries=[_query_of(text), "попередні правки цих файлів"])
    if factual:
        depth = Depth(DEPTH_MINIMAL, DEPTH_KEEP[DEPTH_MINIMAL],
                      DIGEST_EXTRA[DEPTH_MINIMAL],
                      "питання-факт — досить пошуку в пам'яті")
        return Plan(mode=chosen.key, depth=depth,
                    queries=[_query_of(text)])
    depth = Depth(DEPTH_SHALLOW, DEPTH_KEEP[DEPTH_SHALLOW],
                  DIGEST_EXTRA[DEPTH_SHALLOW],
                  "звичайний запит — останні обміни")
    return Plan(mode=chosen.key, depth=depth, queries=[_query_of(text)])


def _query_of(text: str) -> str:
    """Запит для пам'яті: сам текст, скорочений до розумної довжини."""
    body = " ".join(str(text or "").split())
    return body[:240]


def cache_key(*, query: str, files: Sequence[str] = (),
              mode: str = "auto") -> str:
    """Ключ для «кешу на льоту»: однаковий запит → готова добірка.

    Навіщо. У довгому завданні модель часто повторює схожі запити («що в
    теці?», «де лежить черга?»). Повторний пошук по пам'яті й по диску
    коштує часу, а результат не змінюється, якщо не змінились файли.

    Ключ навмисно ДЕШЕВИЙ і стабільний: нормалізований текст (без регістру
    й зайвих пробілів), набір файлів і режим. Нічого не хешується «назавжди»:
    кеш живе один хід (див. ``AgentRunner._context_cache``).
    """
    body = " ".join(str(query or "").lower().split())
    names = ",".join(sorted(str(item).replace("\\", "/")
                            for item in files or () if str(item).strip()))
    return f"{mode}|{body[:200]}|{names}"


def describe(plan: Plan) -> str:
    """Один рядок для журналу й для людини."""
    return (f"Контекст: {plan.depth.reason}; у вікні "
            f"{plan.depth.keep or 'уся історія'} повідомлень, "
            f"хроніка +{plan.depth.digest_extra}.")


def modes() -> list[tuple[str, str]]:
    """Пари ``(ключ, підпис)`` для випадаючого списку в налаштуваннях."""
    return [(item.key, item.label) for item in MODES]


# ─────────────────────────────────────────────────────────────────────────────
# МОДЕЛЬ САМА ЗАПИТУЄ КОНТЕКСТ
# ─────────────────────────────────────────────────────────────────────────────
#
# Ідея користувача (21.11.2026): «а ще краще сама модель щоб робила запит і на
# її запит визначався контекст, вона ж знає скільки їй потрібно контексту для
# кожного запиту!».
#
# Це справді точніше за евристику: модель бачить своє завдання й знає, чи їй
# потрібен попередній код, чи досить останньої репліки. Тому їй дається
# ІНСТРУМЕНТ ``request_context``: вона каже, скільки минулого їй треба, і
# агент підкладає саме стільки — з вікна, хроніки та пам'яті.
#
# Обмеження навмисні:
# * модель може попросити БІЛЬШЕ, але не «нескінченно»: стеля — це вікно;
# * прохання не скасовує безпеку: приватний режим не пише в пам'ять;
# * якщо модель не попросила нічого — працює адаптивна евристика
#   (:func:`choose`), бо «мовчання» не має означати «позбавити контексту».

#: Скільки повідомлень максимум може попросити модель.
MAX_REQUESTED_MESSAGES = 60


class RequestError(ValueError):
    """Некоректний запит контексту від моделі."""


def parse_request(messages: Any = 0, *, need_history: bool = True,
                  need_memory: bool = True, query: str = "",
                  reason: str = "") -> Depth:
    """Розібрати запит моделі на контекст.

    ``messages`` — скільки останніх повідомлень лишити у вікні:

    * ``0`` — не чіпати вікно (уся історія, що вміщається);
    * додатне число — рівно стільки (обмежується
      :data:`MAX_REQUESTED_MESSAGES`).

    ``need_memory`` — підкласти факти з NEUROMESH/RAG за ``query``.
    ``need_history`` — чи потрібна хроніка (слід давнішого).
    """
    try:
        count = int(messages or 0)
    except (TypeError, ValueError) as exc:
        raise RequestError(f"messages має бути числом, а не {messages!r}") from exc
    if count < 0:
        raise RequestError("messages не може бути від'ємним")
    count = min(count, MAX_REQUESTED_MESSAGES)
    if count == 0:
        depth = Depth(DEPTH_DEEP, 0, DIGEST_EXTRA[DEPTH_DEEP],
                      reason or "модель попросила всю історію")
    else:
        # Визначаємо рівень за кількістю, щоб журнал і показник були зрозумілі.
        if count <= DEPTH_KEEP[DEPTH_MINIMAL]:
            level = DEPTH_MINIMAL
        elif count <= DEPTH_KEEP[DEPTH_SHALLOW]:
            level = DEPTH_SHALLOW
        else:
            level = DEPTH_MEDIUM
        extra = DIGEST_EXTRA[DEPTH_DEEP] if need_history else 0
        depth = Depth(level, count, extra,
                      reason or f"модель попросила {count} повідомлень")
    if not need_memory:
        depth.digest_extra = 0 if not need_history else depth.digest_extra
    return depth


def plan_from_request(depth: Depth, *, query: str = "",
                      mode: str = "auto") -> Plan:
    """План на основі прохання моделі (а не евристики)."""
    return Plan(mode=mode, depth=depth, recall=bool(depth.digest_extra),
                remember=True, queries=[query] if query else [])


def describe_request(depth: Depth) -> str:
    """Що саме модель попросила — для журналу й відповіді їй самій."""
    if depth.keep <= 0:
        return "уся історія, що вміщається у вікно"
    return f"останні {depth.keep} повідомлень"


def plan_from_model(request: Any, *, text: str = "",
                    mode: str = "auto") -> Plan:
    """План із СИРОГО аргументу інструмента ``request_context``.

    ``request`` — словник від моделі (може бути порожнім або некоректним).
    Будь-яка помилка тут не має ламати хід: повертаємо адаптивний план.
    """
    data = request if isinstance(request, dict) else {}
    try:
        depth = parse_request(
            data.get("messages", 0),
            need_history=bool(data.get("need_history", True)),
            need_memory=bool(data.get("need_memory", True)),
            query=str(data.get("query") or _query_of(text)),
            reason=str(data.get("reason") or ""))
    except RequestError:
        depth = Depth(DEPTH_DEEP, 0, DIGEST_EXTRA[DEPTH_DEEP],
                      "запит моделі некоректний — лишаю всю історію")
    return plan_from_request(depth, query=str(data.get("query")
                                              or _query_of(text)), mode=mode)
