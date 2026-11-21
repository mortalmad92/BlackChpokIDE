"""Терплячий наглядач за локальними моделями: ловить «застрягання» раніше.

НАВІЩО ОКРЕМИЙ МОДУЛЬ. Живі прогони локальних моделей (Ministral-3-14B,
Qwen2.5-VL-3B, власний рушій) показали три різні види зациклення, і кожен
виглядав для агента як «нормальна робота»:

1. **Той самий виклик.** ``read_file(path="task_executor.py")`` п'ять разів
   поспіль з тим самим результатом — модель «перечитує» замість того, щоб
   відповісти. Наявний :class:`agent._RepeatGuard` це ловить, але лише коли
   аргументи збігаються БАЙТ У БАЙТ.
2. **Майже той самий виклик.** ``read_file("task_executor.py")`` →
   ``read_file("./task_executor.py")`` → ``read_file("task_executor.py ")``.
   Для ``_RepeatGuard`` це три різні виклики, для людини — один і той самий.
3. **Довгий цикл A→B→A→B.** ``list_dir`` → ``read_file`` → ``list_dir`` →
   ``read_file``: жодного повтору підряд, а прогресу немає.

Модуль чистий: без tkinter, без мережі, без рушія і без залежностей від
``agent.py``. Тому його легко перевіряти тестами, а підключення зводиться до
одного виклику там, де агент уже рахує повтори.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "LEVEL_OK",
    "LEVEL_TIRED",
    "LEVEL_HOPELESS",
    "Signal",
    "StuckGuard",
    "cycle_in",
    "cycle_labels",
    "fingerprint",
    "hint_for",
    "normalise_arguments",
    "report",
    "tool_sequence_hint",
]

#: Рівні тривоги. ``TIRED`` — ще одна підказка моделі й новий хід;
#: ``HOPELESS`` — час чесно завершувати й казати причину користувачу.
LEVEL_OK = 0
LEVEL_TIRED = 1
LEVEL_HOPELESS = 2

#: Скільки однакових (після нормалізації) викликів вважаємо «застряганням».
TIRED_AFTER = 2
#: Після стількох — припиняємо роботу.
HOPELESS_AFTER = 5
#: Скільки останніх кроків тримаємо для пошуку довгих циклів.
WINDOW = 12
#: Скільки разів той самий цикл A→B→A має повторитись, щоб це вважалось
#: застряганням (2 повтори = 4 кроки, 3 повтори = 6 кроків).
CYCLE_REPEATS = 3
#: Скільки провалів того самого інструмента з РІЗНИМИ аргументами означають
#: «модель перебирає навмання» (напр. ``edit_file`` з різними ``old_string``).
BLIND_RETRIES = 4

#: Аргументи, які не впливають на суть виклику (косметика, різні імена того
#: самого поля). Їх відкидаємо перед порівнянням.
_NOISE_KEYS = frozenset({
    "timeout", "verbose", "encoding", "force", "dry_run", "dry-run",
    "pretty", "format", "overwrite", "replace_all", "all_matches",
})

#: Імена того самого аргументу в різних моделях: локальні моделі часто
#: плутають ``file`` із ``path`` — для людини це один виклик.
_ALIASES: dict[str, tuple[str, ...]] = {
    "path": ("path", "file", "filepath", "file_path", "filename", "target"),
    "query": ("query", "text", "q", "pattern", "needle", "search"),
    "content": ("content", "text_content", "new_text", "body"),
    "command": ("command", "cmd", "exec", "shell", "line"),
}

_SLASHES = re.compile(r"[\\/]+")


# ─────────────────────────────────────────────────────────────────────────────
# Нормалізація
# ─────────────────────────────────────────────────────────────────────────────

def _norm_path(value: str) -> str:
    """Один шлях — один вигляд (``.\\a.py`` і ``a.py`` мають збігтися)."""
    text = (value or "").strip().strip("'\"").replace("\\", "/")
    text = _SLASHES.sub("/", text)
    while text.startswith("./"):
        text = text[2:]
    return text.strip().casefold()


def _norm_scalar(value: Any) -> Any:
    if isinstance(value, str):
        text = " ".join(value.split())
        # Довгий текст (цілий файл у ``content``) порівнюємо за початком і
        # кінцем: переписування одного рядка всередині — це ВЖЕ інший виклик,
        # а от випадковий пробіл у кінці — ні.
        if len(text) > 400:
            return text[:200] + "…" + text[-200:]
        return text
    return value


def normalise_arguments(arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    """Привести аргументи до вигляду, придатного для порівняння.

    Що робимо:

    * відкидаємо шумові поля (``timeout``, ``encoding``…) і порожні значення;
    * зводимо різні імена одного аргументу до канонічного (``file`` → ``path``);
    * шляхи — до ``/`` без ``./`` і без регістру;
    * рядки — до одного пробілу між словами;
    * вкладені словники й списки сортуємо за ключем.
    """
    data = dict(arguments or {})
    canonical: dict[str, Any] = {}
    for key, value in data.items():
        name = str(key)
        if name in _NOISE_KEYS or value is None:
            continue
        target = name
        for canonical_name, aliases in _ALIASES.items():
            if name in aliases:
                target = canonical_name
                break
        if target in canonical:            # уже заповнено під канонічним ім'ям
            continue
        canonical[target] = value
    clean: dict[str, Any] = {}
    for name, value in canonical.items():
        if name == "path":
            text = _norm_path(str(value))
            if not text:
                continue
            clean[name] = text
            continue
        if name in ("query", "command", "content"):
            text = _norm_scalar(value)
            if text in ("", None) or (isinstance(text, str) and not text.strip()):
                continue
            clean[name] = text
            continue
        if isinstance(value, (dict, list)):
            try:
                clean[name] = json.dumps(value, ensure_ascii=False,
                                         sort_keys=True, default=str)
            except (TypeError, ValueError):
                clean[name] = str(value)
            continue
        item = _norm_scalar(value)
        if item in ("", None):
            continue
        clean[name] = item
    return clean


def fingerprint(name: str, arguments: Mapping[str, Any] | None, ok: bool,
                output: str = "") -> str:
    """Відбиток «виклик + результат», стійкий до косметичних відмінностей."""
    payload = json.dumps(normalise_arguments(arguments), ensure_ascii=False,
                         sort_keys=True, default=str)
    body = " ".join((output or "").split())
    if len(body) > 300:
        body = body[:150] + "…" + body[-150:]
    return f"{name}|{payload}|{'ok' if ok else 'fail'}|{body}"


# ─────────────────────────────────────────────────────────────────────────────
# Підказки моделі
# ─────────────────────────────────────────────────────────────────────────────

#: Для кожного інструмента — що робити ЗАМІСТЬ повтору. Локальна модель не
#: розуміє абстрактного «зміни підхід», тому кажемо конкретну наступну дію.
_NEXT_STEP: dict[str, str] = {
    "read_file": "Файл уже прочитано — його вміст вище. Не читай його знову: "
                 "переходь до правки (edit_file) або відповіді користувачу.",
    "read_files": "Ці файли вже прочитано — використай те, що маєш, і переходь "
                  "до правки або відповіді.",
    "list_dir": "Список уже отримано. Не повторюй огляд теки — візьми потрібний "
                "файл і працюй із ним.",
    "find_files": "Пошук уже дав результат. Обери файл зі знайдених і читай/"
                  "прав його, а не шукай те саме знову.",
    "search_text": "Збіги вже знайдено вище. Не шукай те саме — відкрий "
                   "знайдений файл і прав його.",
    "python_check": "Синтаксис уже перевірено. Якщо ок — переходь до наступного "
                    "файлу або відповідай; якщо ні — ВИПРАВ код, а не перевіряй "
                    "той самий файл знову.",
    "edit_file": "Правка не пройшла. Не повторюй той самий old_string: "
                 "перечитай файл і візьми ТОЧНИЙ фрагмент, або перепиши файл "
                 "цілком через write_file.",
    "write_file": "Запис не пройшов. Перевір шлях і права, а не повторюй той "
                  "самий вміст.",
    "run_command": "Команда вже відпрацювала з цим результатом. Не запускай її "
                   "знову — виправ причину або зміни саму команду.",
    "search_web": "Пошук уже дав результат. Не шукай те саме іншими словами — "
                  "використай знайдене або скажи, чого бракує.",
}

#: Загальна підказка, коли інструмент невідомий.
_GENERIC = ("Не повторюй цей виклик: результат не зміниться. Обери іншу дію "
            "або відповідай тим, що вже маєш.")


def hint_for(name: str, arguments: Mapping[str, Any] | None = None, *,
             ok: bool = True, output: str = "", count: int = 0,
             level: int = LEVEL_TIRED) -> str:
    """Конкретна вказівка моделі замість абстрактного «спробуй інакше»."""
    tool = str(name or "").strip()
    step = _NEXT_STEP.get(tool, _GENERIC)
    head = ""
    if count > 1:
        head = f"Ти викликав «{tool}» {count} раз(и) з тим самим результатом.\n"
    body = (output or "").strip()
    if len(body) > 300:
        body = body[:300] + "…"
    parts = [head + step]
    if body and not ok:
        parts.append("Відповідь інструмента:\n" + body)
    if level >= LEVEL_HOPELESS:
        parts.append("Якщо ця дія принципово недоступна — чесно скажи про це "
                     "користувачу й запропонуй, що можна зробити без неї.")
    else:
        parts.append("Зроби ОДНУ іншу дію — і саме зараз.")
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Наглядач
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    """Висновок наглядача після одного кроку."""

    level: int = LEVEL_OK
    count: int = 0
    #: Коротка причина для журналу й для користувача (без технічного сміття).
    reason: str = ""
    #: Готова підказка моделі (порожня, якщо все гаразд).
    hint: str = ""

    @property
    def stuck(self) -> bool:
        return self.level >= LEVEL_TIRED

    @property
    def hopeless(self) -> bool:
        return self.level >= LEVEL_HOPELESS


@dataclass
class StuckGuard:
    """Ковзне вікно кроків агента й три рівні тривоги.

    Використання::

        guard = StuckGuard()
        signal = guard.observe("read_file", {"path": "a.py"}, True, "…")
        if signal.stuck:
            session.add_user(signal.hint)
    """

    tired_after: int = TIRED_AFTER
    hopeless_after: int = HOPELESS_AFTER
    cycle_repeats: int = CYCLE_REPEATS
    blind_retries: int = BLIND_RETRIES
    window: int = WINDOW

    _counts: dict[str, int] = field(default_factory=dict)
    _steps: list[tuple[str, str, bool]] = field(default_factory=list)
    _fail_by_tool: dict[str, set[str]] = field(default_factory=dict)
    _total: int = 0

    # ── публічне ────────────────────────────────────────────────────────────

    def observe(self, name: str, arguments: Mapping[str, Any] | None = None,
                ok: bool = True, output: str = "") -> Signal:
        """Врахувати крок і сказати, чи модель застрягла."""
        self._total += 1
        tool = str(name or "").strip() or "?"
        key = fingerprint(tool, arguments, ok, output)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        self._steps.append((tool, key, bool(ok)))
        if len(self._steps) > max(self.window, 4):
            self._steps.pop(0)
        if not ok:
            args_key = json.dumps(normalise_arguments(arguments),
                                  ensure_ascii=False, sort_keys=True, default=str)
            self._fail_by_tool.setdefault(tool, set()).add(args_key)

        # 1. Короткий цикл A→B→A→B (кожен виклик різний, прогресу немає).
        #    Перевіряємо ПЕРШИМ: коли модель ходить по колу, лічильник
        #    однакових викликів теж спрацьовує (третє «A» у A→B→A→B→A→B), і
        #    повідомлення виходило неправдивим — «повторюється», хоч жодного
        #    повтору підряд не було.
        cycle = self._detect_cycle()
        if cycle:
            return Signal(LEVEL_TIRED, len(cycle),
                          "модель ходить по колу: " + " → ".join(cycle),
                          hint_for(tool, arguments, ok=ok, output=output,
                                   count=count, level=LEVEL_TIRED))
        # 2. Той самий виклик із тим самим результатом.
        if count >= self.hopeless_after:
            return Signal(LEVEL_HOPELESS, count,
                          f"«{tool}» повторювався {count} разів без змін",
                          hint_for(tool, arguments, ok=ok, output=output,
                                   count=count, level=LEVEL_HOPELESS))
        if count >= self.tired_after:
            return Signal(LEVEL_TIRED, count,
                          f"«{tool}» повторюється ({count})",
                          hint_for(tool, arguments, ok=ok, output=output,
                                   count=count, level=LEVEL_TIRED))
        # 3. Перебір навмання: той самий інструмент падає з різними аргументами.
        fails = len(self._fail_by_tool.get(tool, ()))
        if fails >= self.blind_retries:
            return Signal(
                LEVEL_TIRED, fails,
                f"«{tool}» падає {fails} рази з різними аргументами",
                hint_for(tool, arguments, ok=ok, output=output, count=fails,
                         level=LEVEL_TIRED)
                + "\n\nТи перебираєш варіанти навмання. Спершу прочитай те, що "
                  "треба змінити, і вже потім викликай інструмент.",
            )
        return Signal(LEVEL_OK, count)

    @property
    def total(self) -> int:
        """Скільки кроків модель зробила за весь хід."""
        return self._total

    def reset(self) -> None:
        """Забути історію (новий хід, нова задача)."""
        self._counts.clear()
        self._steps.clear()
        self._fail_by_tool.clear()
        self._total = 0

    def summary(self) -> str:
        """Одне речення для підсумку, коли роботу припинено."""
        if not self._counts:
            return ""
        key, count = max(self._counts.items(), key=lambda item: item[1])
        return f"«{key.split('|', 1)[0]}» повторювався {count} раз(и)."

    # ── внутрішнє ───────────────────────────────────────────────────────────

    def _detect_cycle(self) -> list[str]:
        """Знайти повторюваний цикл у вікні останніх кроків."""
        labels = [item[0] for item in self._steps]
        keys = [item[1] for item in self._steps]
        return cycle_labels(keys, labels, repeats=self.cycle_repeats)


def cycle_in(keys: Sequence[str], repeats: int = CYCLE_REPEATS) -> list[str]:
    """Чи ходить послідовність відбитків по колу (A→B→A→B→A→B).

    Повертає період циклу (список відбитків) або ``[]``. Усередині періоду
    відбитки мусять бути РІЗНІ: інакше це звичайний повтор, і його рахує
    лічильник однакових викликів.
    """
    need = max(2, int(repeats or 2))
    items = list(keys or [])
    for period in range(2, len(items) // need + 1):
        tail = items[-period * need:]
        first = tail[:period]
        if len(set(first)) != len(first):
            continue
        if all(tail[block * period:(block + 1) * period] == first
               for block in range(1, need)):
            return list(first)
    return []


def cycle_labels(keys: Sequence[str], labels: Sequence[str],
                 repeats: int = CYCLE_REPEATS) -> list[str]:
    """:func:`cycle_in`, але повертає людські назви (імена інструментів)."""
    items = list(keys or [])
    period = cycle_in(items, repeats)
    if not period:
        return []
    names: list[str] = []
    for key in period:
        for index, item in enumerate(items):
            if item == key and index < len(labels):
                names.append(str(labels[index]))
                break
    return names


def tool_sequence_hint(names: Sequence[str]) -> str:
    """Підказка для типової «безплідної» послідовності інструментів.

    Потрібна там, де агент уже знає послідовність, але ще не має відбитків
    (напр. планувальник черги хоче попередити модель заздалегідь).
    """
    chain = [str(item) for item in names if str(item).strip()]
    if not chain:
        return ""
    if chain[-1] in ("read_file", "read_files") and chain.count(chain[-1]) > 1:
        return hint_for(chain[-1], count=len(chain))
    return ""


def report(signals: Iterable[Signal]) -> str:
    """Скинути кілька сигналів в один короткий звіт (для журналу)."""
    rows = [item.reason for item in signals if item and item.reason]
    return "; ".join(rows)
