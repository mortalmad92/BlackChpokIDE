"""Самонавчання на ВИБОРІ РЕЖИМУ: помилка вибору стає правилом наступного разу.

Режим роботи агент обирає сам із тексту запиту (:func:`modes.auto_mode`).
Правила там детерміновані, і саме тому вони іноді помиляються: жива фраза
не завжди схожа на шаблон. Цей модуль закриває розрив між «режим обрано» і
«режим обрано ПРАВИЛЬНО».

Звідки береться сигнал помилки — не зі здогадів, а з самого ходу агента:

``чат без інструментів``
    Обрано «Чат», але запит вимагає фактів про проєкт. Агент чесно
    відповідає «перемкни режим на Агент» — це доведена помилка вибору.
``відмова дозволів``
    Обрано режим лише для читання, а робота вимагає запису файлу.
    ``permissions`` відхилив виклик — режим був замалий.
``балачка з інструментами``
    Обрано «Код»/«Агент», але запит — привітання чи подяка: агент
    запускав повний цикл там, де досить було відповісти текстом.

Що НЕ стає правилом:

* помилка, яку агент виправив у тому ж ході (це навик, не режим);
* таймаут/мережа — повтор лікує, правило не потрібне;
* приватний режим («не зберігай»);
* будь-яка правка, яка суперечить безпеці: «Чат» ніколи не обирається для
  запиту, що вимагає інструментів, навіть якщо так «навчились» раніше.

Правила живуть у звичайному JSON поруч із налаштуваннями: їх видно, їх
можна стерти, і вони не залежать від того, чи підключена пам'ять. Крім
того, кожна помилка окремо пишеться в NEUROMESH як урок — щоб модель теж
бачила висновок.

Модуль не тягне tkinter і не робить мережевих викликів: його можна
перевірити без вікна й без моделі.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "MAX_RULES",
    "MIN_PHRASE_CHARS",
    "ModeLearner",
    "ModeMistake",
    "normalise",
    "phrase_of",
    "reason_text",
]

LOG = logging.getLogger("blackchpok.mode_learning")

#: Скільки правил тримаємо. Більше — це вже не «навчання», а шум: правило
#: мусить відповідати конкретній повторюваній ситуації.
MAX_RULES = 60

#: Найкоротша фраза-ознака. Один-два символи («ок», «чи») збігаються з
#: половиною всіх запитів, і режим почав би «стрибати» без причини.
MIN_PHRASE_CHARS = 8

#: Сківльки слів у фразі-ознаці максимум. Довша фраза вже не повторюється
#: дослівно, і правило ніколи не спрацювало б.
MAX_PHRASE_WORDS = 6


def normalise(text: str) -> str:
    """Текст для порівняння: нижній регістр, без пунктуації й зайвих пробілів."""
    body = str(text or "").lower()
    body = re.sub(r"[«»\"'`’ʼ(){}\[\]<>.,!?;:—–\-/\\|]", " ", body)
    return " ".join(body.split())


def phrase_of(text: str) -> str:
    """Фраза-ознака запиту: кілька перших змістовних слів.

    Саме вона стає тригером правила. Беремо ПОЧАТОК фрази: людина формулює
    намір на початку («виправ помилку в…», «створи сайт…»), а хвіст
    щоразу інший.
    """
    words = normalise(text).split()
    return " ".join(words[:MAX_PHRASE_WORDS])[:64]


def reason_text(reason: str) -> str:
    """Людський опис причини помилки вибору режиму."""
    return {
        "need_tools": "запит вимагав інструментів, а режим їх вимикав",
        "denied": "робота вимагала запису, а режим дозволяв лише читання",
        "smalltalk": "це була розмова, а агент пішов працювати з файлами",
    }.get(str(reason or ""), str(reason or ""))


@dataclass
class ModeMistake:
    """Одне правило: «на таку фразу правильний режим — ось цей»."""

    phrase: str = ""
    #: Режим, який агент обрав помилково.
    chosen: str = ""
    #: Режим, який був потрібен.
    wanted: str = ""
    #: Код причини (``need_tools`` / ``denied`` / ``smalltalk``).
    reason: str = ""
    source: str = "самонавчання: власний хід"
    #: Скільки разів ця сама помилка повторилась.
    hits: int = 1
    #: Коли правило востаннє підтвердилось (unix time).
    last: float = field(default_factory=time.time)

    def describe(self) -> str:
        """Один рядок для журналу й панелі."""
        shown = self.phrase or "без фрази"
        return (f"«{shown}» → {self.wanted} "
                f"(обрано {self.chosen}: {reason_text(self.reason)})")

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase": self.phrase,
            "chosen": self.chosen,
            "wanted": self.wanted,
            "reason": self.reason,
            "source": self.source,
            "hits": int(self.hits),
            "last": float(self.last),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ModeMistake"]:
        if not isinstance(data, dict):
            return None
        phrase = str(data.get("phrase") or "").strip()
        wanted = str(data.get("wanted") or "").strip()
        if not phrase or not wanted:
            return None
        try:
            hits = max(1, int(data.get("hits") or 1))
        except (TypeError, ValueError):
            hits = 1
        try:
            last = float(data.get("last") or time.time())
        except (TypeError, ValueError):
            last = time.time()
        return cls(
            phrase=phrase,
            chosen=str(data.get("chosen") or "").strip(),
            wanted=wanted,
            reason=str(data.get("reason") or "").strip(),
            source=str(data.get("source") or "самонавчання: власний хід"),
            hits=hits,
            last=last,
        )


class ModeLearner:
    """Правила вибору режиму, виведені зі СПРАВЖНІХ помилок агента.

    ``path`` — файл правил. ``None`` означає «лише в пам'яті»: так модуль
    поводиться в тестах і коли налаштування недоступні.

    ``bridge`` — необов'язковий міст до пам'яті (``remember_fact``): кожна
    помилка стає ще й уроком NEUROMESH, щоб модель бачила висновок.
    """

    #: З якою впевненістю правило лягає в пам'ять.
    CONFIDENCE = 0.6

    def __init__(self, path: Any = None, *, enabled: bool = True,
                 bridge: Any = None) -> None:
        self.path = path
        self.enabled = bool(enabled)
        self.bridge = bridge
        self._rules: list[ModeMistake] = []
        self.loaded = False

    # ── файл ──────────────────────────────────────────────────────────────
    def load(self) -> "ModeLearner":
        self.loaded = True
        if self.path is None:
            return self
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self
        except OSError as exc:
            LOG.info("Правила режиму не прочитано: %s", exc)
            return self
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            LOG.info("Файл правил режиму пошкоджено — починаємо з нуля")
            return self
        items = data.get("rules") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return self
        rules = [ModeMistake.from_dict(item) for item in items]
        self._rules = [rule for rule in rules if rule is not None][:MAX_RULES]
        return self

    def save(self) -> bool:
        if self.path is None:
            return False
        if not self.loaded:
            # Не перезаписуємо чужий файл правилами, яких ми не читали:
            # інакше перший же запис стирає все, що було до запуску.
            self.loaded = True
        payload = {"version": 1, "rules": [rule.to_dict() for rule in self._rules]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            LOG.info("Правила режиму не збережено: %s", exc)
            return False
        return True

    # ── читання ───────────────────────────────────────────────────────────
    def rules(self) -> list[ModeMistake]:
        """Усі правила (найчастіші першими)."""
        return sorted(self._rules, key=lambda rule: (-rule.hits, -rule.last))

    def suggest(self, text: str) -> Optional[ModeMistake]:
        """Правило, що підходить до цього тексту (найдовша фраза перемагає).

        Найдовша — бо «виправ помилку» є окремим випадком «виправ», і
        конкретніше правило має перекривати загальне.
        """
        if not self.enabled or not self._rules:
            return None
        body = normalise(text)
        if not body:
            return None
        best: Optional[ModeMistake] = None
        for rule in self._rules:
            if not rule.phrase or rule.phrase not in body:
                continue
            if best is None or len(rule.phrase) > len(best.phrase):
                best = rule
        return best

    def apply(self, text: str, chosen: str, *,
              veto: Optional[Callable[[str, str], bool]] = None
              ) -> tuple[str, Optional[ModeMistake]]:
        """Скоригувати обраний режим правилом. Повертає (режим, правило).

        ``veto(mode, text)`` — запобіжник безпеки від самого викликача:
        якщо він забороняє цей режим для цього тексту, правило НЕ діє.
        Навчання не має права зробити агента небезпечнішим, ніж він був.
        """
        rule = self.suggest(text)
        if rule is None or not rule.wanted:
            return chosen, None
        if rule.wanted == chosen:
            # Правило вже виконане (напр. навчання спрацювало раніше).
            return chosen, None
        if veto is not None:
            try:
                if veto(rule.wanted, text):
                    LOG.debug("Правило режиму відхилено запобіжником: %s",
                              rule.describe())
                    return chosen, None
            except Exception:                        # noqa: BLE001
                LOG.debug("Запобіжник режиму впав — правило не діє",
                          exc_info=True)
                return chosen, None
        rule.hits += 1
        rule.last = time.time()
        return rule.wanted, rule

    # ── запис ─────────────────────────────────────────────────────────────
    def record(self, text: str, *, chosen: str, wanted: str, reason: str,
               source: str = "") -> Optional[ModeMistake]:
        """Запам'ятати помилку вибору. ``None`` — якщо вчитись нема чого."""
        if not self.enabled:
            return None
        chosen = str(chosen or "").strip().lower()
        wanted = str(wanted or "").strip().lower()
        if not chosen or not wanted or chosen == wanted:
            # «Помилка», у якій правильний режим збігається з обраним, —
            # не помилка. Такі записи лише роздували б список.
            return None
        phrase = phrase_of(text)
        if len(phrase) < MIN_PHRASE_CHARS:
            # Занадто загальна фраза: правило спрацювало б на все підряд.
            return None
        existing = self._find(phrase, wanted)
        if existing is not None:
            existing.hits += 1
            existing.last = time.time()
            existing.chosen = chosen
            existing.reason = str(reason or existing.reason)
            rule = existing
        else:
            rule = ModeMistake(
                phrase=phrase, chosen=chosen, wanted=wanted,
                reason=str(reason or ""),
                source=source or "самонавчання: власний хід")
            self._rules.append(rule)
            self._trim()
        self.save()
        self._remember(rule, text)
        return rule

    def _find(self, phrase: str, wanted: str) -> Optional[ModeMistake]:
        for rule in self._rules:
            if rule.phrase == phrase and rule.wanted == wanted:
                return rule
        return None

    def _trim(self) -> None:
        if len(self._rules) <= MAX_RULES:
            return
        self._rules.sort(key=lambda rule: (-rule.hits, -rule.last))
        del self._rules[MAX_RULES:]

    def _remember(self, rule: ModeMistake, text: str) -> None:
        """Записати висновок у пам'ять (якщо вона підключена)."""
        bridge = self.bridge
        if bridge is None:
            return
        remember = getattr(bridge, "remember_fact", None)
        if not callable(remember):
            return
        content = ("Урок (вибір режиму): на фразу «"
                   f"{rule.phrase}» правильний режим — {rule.wanted}, "
                   f"а не {rule.chosen}: {reason_text(rule.reason)}.")
        try:
            remember(content, kind="lesson", source=rule.source,
                     task=" ".join(str(text or "").split())[:120],
                     confidence=self.CONFIDENCE)
        except Exception:                            # noqa: BLE001
            LOG.debug("Урок режиму не записано", exc_info=True)

    def forget_all(self) -> int:
        """Стерти всі правила навчання. Повертає, скільки було."""
        count = len(self._rules)
        self._rules.clear()
        self.save()
        return count

    def describe(self) -> str:
        """Один рядок стану для панелі й журналу."""
        if not self.enabled:
            return "Самонавчання режиму вимкнене."
        count = len(self._rules)
        if not count:
            return "Самонавчання режиму: правил ще немає."
        top = self.rules()[0]
        return (f"Самонавчання режиму: {count} правил. "
                f"Найчастіше: {top.describe()}")

    def lines(self, limit: int = 8) -> list[str]:
        """Рядки для показу людині (панель, довідка, статус)."""
        return [rule.describe() for rule in self.rules()[:max(1, int(limit))]]


def learner_for(settings: Any = None, *, bridge: Any = None) -> ModeLearner:
    """Створити файловий навчач режиму за налаштуваннями застосунку."""
    enabled = True
    try:
        enabled = bool(getattr(getattr(settings, "agent", None),
                               "mode_learning", True))
    except Exception:                                # noqa: BLE001
        enabled = True
    path = None
    try:
        from .config import app_data_dir

        path = app_data_dir() / "mode_learning.json"
    except Exception:                                # noqa: BLE001
        path = None
    return ModeLearner(path, enabled=enabled, bridge=bridge).load()
