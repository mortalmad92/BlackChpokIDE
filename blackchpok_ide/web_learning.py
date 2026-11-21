"""Залізне правило: інтернет → знання → довгострокова пам'ять → інші чати.

Проблема, яку це вирішує. Локальна модель не має свіжих знань і не пам'ятає
нічого між чатами. Кожна нова розмова починається з нуля: агент знову шукає
те саме в інтернеті, знову отримує ті самі сторінки й знову їх забуває.
Плата за це — час, токени й повторні помилки.

Тут реалізовано три речі, і всі три — ОБОВ'ЯЗКОВІ, а не «як вийде»:

1. **Витяг знань із результату інструмента** (:func:`extract`). Результат
   ``search_web``/``fetch_url`` перетворюється на короткі твердження з
   джерелом (URL). Не «сирий дамп сторінки», а факти, які можна перевірити.
2. **Запис у пам'ять із міткою свіжості** (:func:`remember`). Кожен факт
   лягає в NEUROMESH із ``provenance="web:<url>"`` і типом ``fact``. Пам'ять
   у проєкті СПІЛЬНА для всіх чатів (окремої таблиці на чат немає), тому
   записане в одному чаті підкладається в контекст іншого через
   ``memory_bridge``.
3. **Обов'язковий пошук перед відповіддю** (:func:`needs_web`). Якщо питання
   про свіжі дані (ціна, курс, погода, версія, новини), а інтернет цього
   ходу не використовувався — це порушення правила, і агент має це знати.

Чому модуль окремий, а не «ще кілька рядків в agent.py». Правила перевіряються
тестами без моделі, без мережі й без tkinter: ``extract`` — чиста функція над
рядком, ``remember`` — над підробленим сервісом пам'яті.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

__all__ = [
    "KNOWLEDGE_KIND",
    "WebFact",
    "extract",
    "format_for_prompt",
    "looks_like_web_result",
    "needs_web",
    "remember",
    "web_tools_used",
]

LOG = logging.getLogger("blackchpok.web_learning")

#: Тип спогаду для знань з інтернету.
#:
#: ``fact`` (а не окремий тип) — свідомо: ваги пошуку вже знають цей тип, і
#: знання з мережі мають брати участь у звичайному пошуку нарівні з іншими
#: перевіреними фактами про проєкт.
KNOWLEDGE_KIND = "fact"

#: Інструменти, результати яких несуть знання ззовні.
WEB_TOOLS: tuple[str, ...] = ("search_web", "fetch_url", "web_api",
                              "web_open", "internet_status")

#: Скільки фактів максимум записуємо з одного результату (решта — шум).
MAX_FACTS = 4

#: Скільки символів лишаємо в одному факті.
FACT_CHARS = 400

#: Мінімальна довжина твердження: коротші — це заголовки й кнопки.
MIN_FACT_CHARS = 40

#: Ознаки свіжих даних — те, чого модель НЕ знає з тренування.
#:
#: Навмисно широко: краще зайвий раз пошукати, ніж вигадати ціну.
_FRESH_MARKERS: tuple[str, ...] = (
    "ціна", "ціни", "ціну", "коштує", "курс", "вартість", "price",
    "погода", "температура", "weather",
    "новини", "новина", "останні", "актуальн", "сьогодні", "зараз",
    "версія", "версії", "реліз", "оновлення", "release", "latest",
    "скільки коштує", "біткоїн", "bitcoin", "sol", "eth", "долар", "гривн",
    "акції", "stock", "курс валют",
)

#: Ознаки того, що знання вже є в пам'яті (шукати не обов'язково).
#:
#: Це не «дозвіл не шукати»: якщо пам'ять дала відповідь — агент може
#: відповісти одразу. Якщо ні — пошук обов'язковий.
_KNOWN_MARKERS: tuple[str, ...] = (
    "memory_search", "з пам'яті", "у пам'яті",
)

#: Рядки результату, які не є знанням (навігація, кнопки, реклама).
#:
#: Обидві мови: більшість сторінок і результатів пошуку приходять
#: англійською, і без англійських маркерів «Read more here» потрапляв у
#: пам'ять як факт (перевірено на реальному результаті).
_NOISE = (
    "cookie", "підписатися", "підписатись", "читати далі", "перейти до",
    "головна", "меню", "вхід", "реєстрація", "усі права захищені",
    "©", "copyright", "javascript", "увімкніть",
    "read more", "learn more", "click here", "sign in", "sign up",
    "subscribe", "privacy policy", "terms of service", "all rights reserved",
    "skip to content", "advertisement", "sponsored", "share this",
)


def _is_url_only(sentence: str) -> bool:
    """Чи речення — сама лише адреса (можливо, з парою слів навколо)."""
    stripped = re.sub(r"https?://\S+", "", sentence).strip(" .,:;-—|")
    return len(stripped.split()) < 4


@dataclass
class WebFact:
    """Одне твердження, витягнуте з результату інтернету."""

    text: str
    #: Звідки взято (URL або назва інструмента) — частина довіри до факту.
    source: str = ""
    #: Запит, який привів до цього факту (для пошуку в пам'яті).
    query: str = ""
    confidence: float = 0.6

    def content(self) -> str:
        """Текст спогаду: його читає і модель, і людина в панелі пам'яті."""
        body = str(self.text or "").strip()
        if self.source:
            return f"{body} (джерело: {self.source})"
        return body

    def provenance(self) -> str:
        return f"web:{self.source}" if self.source else "web"


def _urls(text: str) -> list[str]:
    """URL-адреси в тексті результату (у порядку появи)."""
    found = re.findall(r"https?://[^\s)\]>'\"<>]+", text or "")
    result: list[str] = []
    for url in found:
        clean = url.rstrip(".,;:!?")
        if clean not in result:
            result.append(clean)
    return result


def looks_like_web_result(text: str) -> bool:
    """Чи схоже це на результат пошуку/сторінки (а не на файл чи помилку)."""
    body = str(text or "").strip()
    if len(body) < MIN_FACT_CHARS:
        return False
    low = body.lower()
    if low.startswith(("✗", "помилка", "error", "traceback")):
        return False
    return bool(_urls(body)) or "http" in low


def _sentences(text: str) -> list[str]:
    """Розбити текст на речення (грубо, але достатньо для фактів)."""
    body = " ".join(str(text or "").split())
    if not body:
        return []
    parts = re.split(r"(?<=[.!?])\s+", body)
    return [part.strip() for part in parts if part.strip()]


def _is_noise(sentence: str) -> bool:
    low = sentence.lower()
    if any(marker in low for marker in _NOISE):
        return True
    # Сама лише адреса — не твердження.
    if re.fullmatch(r"https?://\S+", low):
        return True
    if _is_url_only(sentence):
        return True
    # Заголовок без дієслова: весь у великих літерах.
    #
    # Перевіряємо ЛИШЕ літери всередині, без першої: «Bitcoin price today is
    # 67,432 USD» починається з великої літери звичайно, і сувора перевірка
    # викидала найцінніше речення (перевірено на реальному результаті).
    letters = [ch for ch in sentence[1:] if ch.isalpha()]
    if letters and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.6:
        return True
    return False


def extract(text: str, *, source: str = "", query: str = "",
            limit: int = MAX_FACTS) -> list[WebFact]:
    """Витягти факти з результату ``search_web``/``fetch_url``.

    Що беремо:

    * речення зі змістом (не навігацію, не «підписатися», не суцільні
      заголовки великими літерами);
    * перші ``limit`` таких речень — решта майже завжди повторює те саме;

    Що НЕ беремо: сирий дамп сторінки. Пам'ять має містити твердження, які
    можна перевірити за джерелом, а не мегабайти HTML-тексту.
    """
    body = str(text or "")
    if not body.strip():
        return []
    urls = _urls(body)
    default_source = source or (urls[0] if urls else "")
    facts: list[WebFact] = []
    seen: set[str] = set()
    for sentence in _sentences(body):
        clean = " ".join(sentence.split())
        # Поріг довжини — знижений для речень із ЧИСЛАМИ: «Bitcoin price is
        # 67,432 USD» — це 33 символи, але саме те, за чим прийшли. Суворий
        # поріг 40 відсіював найцінніше (перевірено на реальному результаті).
        has_digits = any(ch.isdigit() for ch in clean)
        floor = 24 if has_digits else MIN_FACT_CHARS
        if len(clean) < floor:
            continue
        if _is_noise(clean):
            continue
        key = clean[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        if len(clean) > FACT_CHARS:
            clean = clean[: FACT_CHARS - 1].rstrip() + "…"
        facts.append(WebFact(text=clean, source=default_source, query=query))
        if len(facts) >= max(1, int(limit)):
            break
    return facts


def remember(service: Any, facts: Sequence[WebFact], *,
             confidence: float = 0.6) -> int:
    """Записати факти в довгострокову пам'ять. Повертає кількість записів.

    Помилка пам'яті не має ламати хід агента: без неї він працює як раніше,
    лише без накопичення знань.
    """
    if not facts:
        return 0
    store = getattr(service, "remember", None)
    if not callable(store):
        return 0
    saved = 0
    for fact in facts:
        content = fact.content()
        if not content.strip():
            continue
        try:
            store(content, kind=KNOWLEDGE_KIND, source="інтернет",
                  provenance=fact.provenance(),
                  confidence=max(0.0, min(1.0, float(confidence))),
                  tags=["інтернет", "знання"])
        except TypeError:
            # Старіший сервіс без частини параметрів.
            try:
                store(content, kind=KNOWLEDGE_KIND, source="інтернет")
            except Exception:                        # noqa: BLE001
                LOG.debug("Факт з інтернету не записано", exc_info=True)
                continue
        except Exception:                            # noqa: BLE001
            LOG.debug("Факт з інтернету не записано", exc_info=True)
            continue
        saved += 1
    return saved


def web_tools_used(tool_names: Iterable[str]) -> list[str]:
    """Які з інтернет-інструментів реально викликали цього ходу."""
    used: list[str] = []
    for name in tool_names or ():
        clean = str(name or "")
        if clean in WEB_TOOLS and clean not in used:
            used.append(clean)
    return used


def needs_web(text: str, *, used: Sequence[str] = (),
              memory_gave: bool = False) -> bool:
    """Чи ЗОБОВ'ЯЗАНИЙ агент піти в інтернет перед відповіддю.

    Залізне правило: про свіжі дані (ціна, курс, погода, новини, версія)
    відповідь без мережі заборонена — модель цього не знає, і вигадані
    цифри гірші за чесне «не знаю».

    ``memory_gave=True`` — пам'ять уже містила відповідь (тоді дублювати
    пошук не потрібно; але факт у пам'яті має бути свіжим, тому це лише
    дозвіл, а не обов'язок).
    """
    body = " ".join(str(text or "").lower().split())
    if not body:
        return False
    if web_tools_used(used):
        return False
    if memory_gave:
        return False
    return any(marker in body for marker in _FRESH_MARKERS)


def format_for_prompt(text: str, *, limit: int = MAX_FACTS) -> str:
    """Блок підказки моделі: «піди в інтернет і запиши знання».

    Використовується, коли правило спрацювало, а мережі цього ходу не було.
    Текст — для моделі: короткий, з прямою вимогою й нагадуванням записати.
    """
    del text
    return (
        "ОБОВ'ЯЗКОВО: у цьому запиті є свіжі дані (ціна, курс, погода, новини "
        "або версія). Модель цього не знає й вигадувати заборонено.\n"
        "1. Виклич search_web (або fetch_url на відоме джерело).\n"
        "2. Візьми цифри й дати ЛИШЕ з результату; додай посилання.\n"
        "3. Знайдене вже збережено в довгострокову пам'ять проєкту — "
        "наступного разу це буде доступно в інших чатах.")
