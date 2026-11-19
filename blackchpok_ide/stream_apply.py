"""Потокове застосування правок: модель пише код — файл змінюється на очах.

Навіщо цей модуль. Раніше правка з'являлась у редакторі ЛИШЕ після того,
як агент повністю сформував аргументи ``edit_file`` / ``write_file`` і
викликав інструмент. Тобто людина десятки секунд дивилась на «агент
працює», а код з'являвся одним стрибком — і не було видно, що саме
змінюється. У Cursor і Windsurf натомість видно, як рядки дописуються.

Що робимо тут. Модуль НЕ звертається до файлової системи й не знає про
tkinter — він лише перетворює потік тексту від моделі на послідовність
подій, а вікно їх показує. Три частини:

1. :class:`StreamParser` — скінченний автомат, який читає стрім шматками
   (``feed``) і розпізнає блоки правок:

       <<<<<<< SEARCH
       старий код
       =======
       новий код
       >>>>>>> REPLACE

   Маркер може прийти РОЗІРВАНИМ між двома шматками («<<<<<<< SE» +
   «ARCH»), тому парсер тримає хвіст, довжиною в найдовший маркер, і не
   віддає його назовні, поки не впевниться, що це не початок маркера.

2. :class:`EditStream` — стабільний пошук фрагмента у файлі (:func:`locate`)
   і «плавне» дописування: замість вставки всього результату одразу
   віддає його порціями по таймеру, адаптуючи розмір порції до того,
   скільки вже накопичилось.

3. :func:`locate` — знаходження старого фрагмента у вмісті файлу. Точний
   збіг, далі пробачення типових розбіжностей локальних моделей (лапки,
   відступи, пробіли в кінці рядків) — та сама логіка, що вже є в
   ``agent_tools._fuzzy_fragment``, але тут вона потрібна ДО виклику
   інструмента, щоб показати правку в редакторі.

Чому порціями, а не по символу. Оновлення ``tk.Text`` на кожен символ
коштує дорого (перерахунок розкладки, підсвітка, жолобок), а мережа
віддає шматки нерівномірно: то порожньо, то 50 символів одразу. Тому є
таймер (``tick_ms``), який забирає з буфера стільки символів, щоб буфер
не ріс швидше, ніж ми його показуємо.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

LOG = logging.getLogger("blackchpok.stream_apply")

__all__ = [
    "EditBlock",
    "EditStream",
    "StreamParser",
    "ToolArgsWatcher",
    "locate",
    "parse_blocks",
    "partial_string_field",
]

# ── Маркери протоколу ───────────────────────────────────────────────────────
#
# Формат узято з підходу «search/replace blocks», який моделі знають добре:
# він простіший за unified diff (не треба рахувати номери рядків, а локальні
# моделі в них помиляються майже завжди) і не вимагає переписувати файл.
MARK_SEARCH = "<<<<<<< SEARCH"
MARK_DIVIDER = "======="
MARK_REPLACE = ">>>>>>> REPLACE"

#: Усі маркери — для пошуку й для розрахунку «хвоста».
_MARKERS: tuple[str, ...] = (MARK_SEARCH, MARK_DIVIDER, MARK_REPLACE)

#: Найдовший маркер: стільки символів хвоста парсер може притримувати.
#: Маркер може прийти розірваним між шматками, і без цього запасу
#: «<<<<<<< SE» було б віддано назовні як звичайний текст.
_HOLD = max(len(marker) for marker in _MARKERS)


def _safe_end(raw: str, index: int) -> int:
    """До якої позиції текст можна віддавати назовні без ризику.

    Притримуємо ЛИШЕ той хвіст, який справді може виявитись початком
    маркера. Якщо жоден суфікс не збігається з початком маркера, віддаємо
    все одразу — інакше кожен короткий рядок коду чекав би на наступний
    шматок, і живий стрім виглядав би смиканим.
    """
    hold = 0
    # Довжина суфікса — від найдовшого можливого до одного символу.
    for size in range(min(len(raw) - index, _HOLD - 1), 0, -1):
        suffix = raw[len(raw) - size:]
        if any(marker.startswith(suffix) for marker in _MARKERS):
            hold = size
            break
    return len(raw) - hold


@dataclass
class EditBlock:
    """Одна знайдена правка: що замінити на що."""

    search: str = ""
    replace: str = ""
    #: Чи блок закінчено (прийшов ``>>>>>>> REPLACE``). Незакінчений блок
    #: показуємо як «пишеться», але не застосовуємо.
    complete: bool = False
    #: Рядок у файлі, де знайдено фрагмент. 0 — ще не знайдено.
    line: int = 0
    #: Чи фрагмент знайдено у поточному вмісті файлу.
    found: bool = False

    @property
    def search_lines(self) -> int:
        return len(self.search.splitlines())

    @property
    def replace_lines(self) -> int:
        return len(self.replace.splitlines())


class StreamParser:
    """Автомат, що читає стрім і витягує з нього блоки SEARCH/REPLACE.

    Використання::

        parser = StreamParser()
        for piece in stream:
            for block in parser.feed(piece):
                ...                  # блок оновився
        for block in parser.flush():
            ...                      # стрім закінчився

    ``feed`` віддає ЛИШЕ змінені блоки (той, у який щойно дописалось), а не
    весь список: під час стріму нас цікавить тільки поточний блок.

    Текст поза блоками не губиться — він доступний як :attr:`text`, щоб
    вікно могло показати звичайну відповідь агента.
    """

    def __init__(self) -> None:
        #: Текст поза блоками правок (прозова відповідь моделі).
        self.text = ""
        #: Усі блоки в порядку появи.
        self.blocks: list[EditBlock] = []
        #: Стан: ``outside`` | ``search`` | ``replace``.
        self._state = "outside"
        #: Текст поточного блоку (накопичується без маркерів).
        self._buffer: list[str] = []
        #: Хвіст, який може виявитись початком маркера — тримаємо до певнення.
        self._pending = ""
        #: Чи бачили бодай один маркер (щоб відрізнити «текст» від «правки»).
        self.saw_marker = False

    # ── публічний API ──────────────────────────────────────────────────────
    @property
    def current(self) -> Optional[EditBlock]:
        """Блок, у який зараз пишеться (None — поза блоками)."""
        return self.blocks[-1] if self.blocks else None

    @property
    def inside(self) -> bool:
        return self._state != "outside"

    def feed(self, piece: str) -> list[EditBlock]:
        """Додати шматок стріму. Повернути блоки, які змінились."""
        if not piece:
            return []
        changed: list[EditBlock] = []
        raw = self._pending + piece
        self._pending = ""
        index = 0
        length = len(raw)
        while index < length:
            # ── Поза блоками: шукаємо початок правки ───────────────────────
            if self._state == "outside":
                found = raw.find(MARK_SEARCH, index)
                if found < 0:
                    safe_end = _safe_end(raw, index)
                    if safe_end > index:
                        self.text += raw[index:safe_end]
                    self._pending = raw[safe_end:]
                    return changed
                self.text += raw[index:found]
                self.saw_marker = True
                self.blocks.append(EditBlock())
                changed.append(self.blocks[-1])
                self._buffer = []
                self._state = "search"
                index = found + len(MARK_SEARCH)
                continue
            # ── Усередині блоку: шукаємо наступний маркер ──────────────────
            next_mark, next_pos = self._next_marker(raw, index)
            if next_mark is None:
                safe_end = _safe_end(raw, index)
                if safe_end > index:
                    self._buffer.append(raw[index:safe_end])
                    self._touch(changed)
                self._pending = raw[safe_end:]
                return changed
            self._buffer.append(raw[index:next_pos])
            self._touch(changed)
            block = self.blocks[-1]
            if next_mark == MARK_DIVIDER:
                block.search = "".join(self._buffer).strip("\n")
                self._buffer = []
                self._state = "replace"
                index = next_pos + len(MARK_DIVIDER)
                continue
            if next_mark == MARK_REPLACE:
                if self._state == "replace":
                    block.replace = _clean_replace("".join(self._buffer))
                else:
                    # Маркер REPLACE без розділювача: модель забула «=======».
                    # Трактуємо накопичене як заміну (це частіше, ніж
                    # «порожній пошук»), інакше блок зникав би зовсім.
                    block.search = ""
                    block.replace = _clean_replace("".join(self._buffer))
                block.complete = True
                self._buffer = []
                self._state = "outside"
                index = next_pos + len(MARK_REPLACE)
                # ``_touch`` вище вже додав цей блок до ``changed``. Другий
                # ``append`` віддавав його вікну ДВІЧІ, і правка починалась
                # заново посеред стріму.
                if block not in changed:
                    changed.append(block)
                continue
            # MARK_SEARCH усередині блоку: модель почала новий блок, не
            # закривши попередній. Закриваємо попередній як незакінчений і
            # починаємо новий.
            block_as_is = self._finish_unclosed()
            if block_as_is is not None:
                changed.append(block_as_is)
            self.blocks.append(EditBlock())
            changed.append(self.blocks[-1])
            self._buffer = []
            self._state = "search"
            index = next_pos + len(MARK_SEARCH)
        return changed

    def flush(self) -> list[EditBlock]:
        """Стрім закінчився: віддати залишок (незакінчений блок або текст)."""
        changed: list[EditBlock] = []
        if self._pending:
            if self._state == "outside":
                self.text += self._pending
            else:
                self._buffer.append(self._pending)
            self._pending = ""
        if self._state != "outside":
            block = self._finish_unclosed()
            if block is not None:
                changed.append(block)
        return changed

    # ── внутрішнє ──────────────────────────────────────────────────────────
    @staticmethod
    def _next_marker(raw: str, start: int) -> tuple[Optional[str], int]:
        """Найближчий маркер від ``start``. (None, -1) — жодного."""
        best: tuple[Optional[str], int] = (None, -1)
        for marker in _MARKERS:
            position = raw.find(marker, start)
            if position < 0:
                continue
            if best[1] < 0 or position < best[1]:
                best = (marker, position)
        return best

    def _touch(self, changed: list[EditBlock]) -> None:
        """Позначити поточний блок зміненим (він щойно дописався)."""
        if not self.blocks:
            return
        block = self.blocks[-1]
        if block in changed:
            return
        changed.append(block)
    def _finish_unclosed(self) -> Optional[EditBlock]:
        """Закрити блок, у якому стрім обірвався (без ``>>>>>>> REPLACE``).

        Такий блок лишаємо як є: ``complete=False``. Вікно показує його
        приглушено й НЕ застосовує — краще нічого, ніж половина правки.
        """
        if not self.blocks:
            self._state = "outside"
            return None
        block = self.blocks[-1]
        body = "".join(self._buffer)
        if self._state == "replace":
            block.replace = _clean_replace(body)
        elif self._state == "search":
            block.search = body.strip("\n")
        self._buffer = []
        self._state = "outside"
        return block


def _clean_replace(body: str) -> str:
    """Прибрати один провідний і один кінцевий перевід рядка.

    Модель майже завжди ставить ``=======``\\ n і ``\\n`` перед
    ``>>>>>>> REPLACE``. Без цього кожна правка додавала б зайвий рядок.
    """
    text = body
    if text.startswith("\r\n"):
        text = text[2:]
    elif text.startswith("\n"):
        text = text[1:]
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    return text


def parse_blocks(text: str) -> list[EditBlock]:
    """Розібрати ГОТОВИЙ текст (не потік) — зручно для тестів і для
    відповіді, яку модель віддала без стріму."""
    parser = StreamParser()
    parser.feed(text or "")
    parser.flush()
    return parser.blocks


# ── Пошук фрагмента у файлі ─────────────────────────────────────────────────

def _skeleton(text: str) -> str:
    """«Скелет» тексту для пробачення розбіжностей: без пробілів і лапок."""
    flat = re.sub(r"\s+", "", text)
    flat = flat.replace('"', "'").replace("\u2019", "'").replace("`", "'")
    return flat


def locate(content: str, wanted: str) -> tuple[int, int, str]:
    """Знайти ``wanted`` у ``content``. Повернути (початок, кінець, текст).

    Три спроби, від найточнішої:

    1. точний збіг (найшвидший і найнадійніший);
    2. збіг без урахування ``\\r\\n`` проти ``\\n`` — файли на Windows;
    3. збіг за «скелетом» рядків — модель змінила лапки, відступи або
       пробіли в кінці.

    Кінець повертаємо ЗАВЖДИ в координатах ``content`` (а не ``wanted``):
    далі саме ним користується вікно, щоб підсвітити старий фрагмент.

    Якщо не знайдено нічого — ``(-1, -1, "")``.
    """
    if not wanted:
        return (-1, -1, "")
    position = content.find(wanted)
    if position >= 0:
        return (position, position + len(wanted), wanted)

    # ── Нормалізація кінців рядків ────────────────────────────────────────
    unified_content = content.replace("\r\n", "\n")
    unified_wanted = wanted.replace("\r\n", "\n")
    if unified_wanted != wanted:
        position = unified_content.find(unified_wanted)
        if position >= 0:
            # Перерахувати зсув у вихідному тексті неможливо дешево, тому
            # шукаємо справжній фрагмент за першим і останнім рядком.
            found = _locate_by_edges(content, wanted)
            if found is not None:
                return found
    elif "\r\n" in content:
        position = unified_content.find(unified_wanted)
        if position >= 0:
            found = _locate_by_edges(content, wanted)
            if found is not None:
                return found

    # ── Пробачення розбіжностей рядків ───────────────────────────────────
    found = _locate_by_skeleton(content, wanted)
    if found is not None:
        return found
    return (-1, -1, "")


def _locate_by_edges(content: str, wanted: str) -> Optional[tuple[int, int, str]]:
    """Пошук за першим і останнім непорожніми рядками.

    Використовується, коли вміст і запит різняться лише кінцями рядків:
    так ми знаходимо СПРАВЖНІЙ зріз ``content`` і повертаємо його текстом.
    """
    wanted_lines = [line for line in wanted.splitlines() if line.strip()]
    if not wanted_lines:
        return None
    first = wanted_lines[0].strip()
    last = wanted_lines[-1].strip()
    lines = content.splitlines(keepends=True)
    offsets: list[int] = []
    running = 0
    for line in lines:
        offsets.append(running)
        running += len(line)
    for start, line in enumerate(lines):
        if line.strip() != first:
            continue
        for end in range(start, len(lines)):
            if lines[end].strip() != last:
                continue
            begin_offset = offsets[start]
            end_offset = offsets[end] + len(lines[end])
            candidate = content[begin_offset:end_offset]
            # Кількість непорожніх рядків мусить збігатись: інакше це
            # випадковий збіг першого й останнього рядка деінде у файлі.
            if len([ln for ln in candidate.splitlines() if ln.strip()]) \
                    != len(wanted_lines):
                continue
            # Зріз беремо БЕЗ кінцевого переводу рядка, якщо його не було
            # в запиті: інакше підсвічувався б ще й наступний рядок.
            if not wanted.endswith(("\n", "\r")):
                end_offset = _trim_line_end(content, begin_offset, end_offset)
                candidate = content[begin_offset:end_offset]
            return (begin_offset, end_offset, candidate)
    return None


def _trim_line_end(content: str, begin: int, end: int) -> int:
    """Прибрати кінцевий ``\\n`` / ``\\r\\n`` із зрізу."""
    stop = end
    if stop > begin and content[stop - 1] == "\n":
        stop -= 1
    if stop > begin and content[stop - 1] == "\r":
        stop -= 1
    return stop


def _locate_by_skeleton(content: str, wanted: str) -> Optional[tuple[int, int, str]]:
    """Пошук вікном рядків із порівнянням «скелетів»."""
    wanted_lines = wanted.splitlines()
    if not wanted_lines:
        return None
    target_key = _skeleton(wanted)
    if len(target_key) < 8:
        # Закоротко: легко зачепити чужий рядок і показати неправдиву правку.
        return None
    lines = content.splitlines(keepends=True)
    offset = 0
    offsets: list[int] = []
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    span = len(wanted_lines)
    for start in range(0, max(1, len(lines) - span + 1)):
        window_end = start + span
        candidate = "".join(lines[start:window_end])
        if _skeleton(candidate) != target_key:
            continue
        begin_offset = offsets[start]
        end_offset = offsets[window_end - 1] + len(lines[window_end - 1])
        if not wanted.endswith(("\n", "\r")):
            end_offset = _trim_line_end(content, begin_offset, end_offset)
        return (begin_offset, end_offset, content[begin_offset:end_offset])
    return None


# ── Плавне дописування ──────────────────────────────────────────────────────

@dataclass
class EditStream:
    """Буфер, який віддає результат правки порціями.

    Замість «вставити 3 000 символів одним ``insert``» — віддавати їх
    шматками по таймеру. Розмір шматка адаптивний: якщо буфер виріс (модель
    пише швидше, ніж ми показуємо), беремо більше, щоб не відставати.
    """

    #: Скільки символів віддавати за один тік, коли буфер майже порожній.
    min_chunk: int = 2
    #: Стеля одного тіку: більше не потрібно, бо людина не побачить різниці.
    max_chunk: int = 48
    #: Скільки символів припадає на «частку буфера» (1/7 — як у Cursor).
    share: int = 7
    buffer: str = ""
    finished: bool = False

    def push(self, piece: str) -> None:
        self.buffer += piece or ""
        # Новий текст означає, що стрім ТРИВАЄ. Без цього прапорця
        # ``finished`` лишався True від попередньої порції, і наступний
        # шматок показався б одним символом, а решта застрягла б у буфері.
        if piece:
            self.finished = False

    def take(self) -> str:
        """Забрати наступну порцію (порожній рядок — показувати нічого)."""
        if not self.buffer:
            self.finished = True
            return ""
        size = max(self.min_chunk, len(self.buffer) // max(1, self.share))
        size = min(size, self.max_chunk, len(self.buffer))
        piece, self.buffer = self.buffer[:size], self.buffer[size:]
        if not self.buffer:
            self.finished = True
        return piece

    @property
    def pending(self) -> int:
        return len(self.buffer)


def preview_lines(block: EditBlock, *, width: int = 80) -> Iterable[str]:
    """Рядки для показу блоку в журналі (без застосування до файлу).

    Потрібно для випадку, коли фрагмент у файлі НЕ знайдено: людина бачить
    саме те, що модель збиралась замінити, замість порожнього місця.
    """
    if not block.complete:
        # Ще пишеться: показуємо те, що вже є, з позначкою «далі буде».
        for line in (block.replace or block.search).splitlines()[:6]:
            yield "+ " + _clip(line, width)
        return
    for line in block.search.splitlines()[:6]:
        yield "- " + _clip(line, width)
    for line in block.replace.splitlines()[:6]:
        yield "+ " + _clip(line, width)


def _clip(line: str, width: int) -> str:
    clean = line.rstrip()
    if len(clean) <= width:
        return clean
    return clean[:width - 1] + "…"


# ── Потік аргументів інструмента ────────────────────────────────────────────
#
# Другий, набагато частіший шлях правки: модель кличе ``edit_file`` /
# ``write_file``, і аргументи приходять шматками JSON. Саме тут видно код
# ДО того, як інструмент спрацює, — тобто можна показати правку в
# редакторі під час стріму, а не після нього.

#: Поля, значення яких — код, який варто показувати наживо.
EDIT_FIELDS: dict[str, tuple[str, ...]] = {
    "write_file": ("content",),
    "edit_file": ("new_string",),
    "append_file": ("content",),
}
#: Поле, яке треба знати ЗАЗДАЛЕГІДЬ, щоб знайти фрагмент для заміни.
SEARCH_FIELDS: dict[str, str] = {
    "edit_file": "old_string",
}


def partial_string_field(raw: str, field_name: str) -> tuple[str, bool]:
    """Витягти значення ще НЕ завершеного поля JSON-рядка.

    Повертає ``(значення, чи_завершене)``. Порожній рядок, якщо поля ще
    немає в накопиченому тексті.

    Навіщо це окремо від ``json.loads``. Аргументи інструмента приходять
    шматками по 5–40 символів, і ``json.loads`` на них падає майже завжди.
    Тут ми не розбираємо JSON, а лише знаходимо ``"content": "`` і читаємо
    рядок, розкодовуючи основні escape-послідовності. Цього досить, щоб
    показувати код у редакторі, а справжній розбір робить агент після
    завершення стріму.
    """
    if not raw or not field_name:
        return ("", False)
    needle = f'"{field_name}"'
    position = raw.find(needle)
    if position < 0:
        return ("", False)
    cursor = position + len(needle)
    # Між іменем поля й значенням стоїть ``:`` та можливі пробіли.
    while cursor < len(raw) and raw[cursor] in " \t\r\n:":
        cursor += 1
    if cursor >= len(raw):
        return ("", False)
    if raw[cursor] != '"':
        # Поле не рядкове (число, масив) — наживо показувати нічого.
        return ("", False)
    cursor += 1
    out: list[str] = []
    escape = False
    while cursor < len(raw):
        char = raw[cursor]
        cursor += 1
        if escape:
            escape = False
            if char == "n":
                out.append("\n")
            elif char == "t":
                out.append("\t")
            elif char == "r":
                out.append("\r")
            elif char == "u":
                # ``\uXXXX`` — забираємо 4 hex-символи, якщо вони вже прийшли.
                digits = raw[cursor:cursor + 4]
                if len(digits) < 4:
                    return ("".join(out), False)
                try:
                    out.append(chr(int(digits, 16)))
                except ValueError:
                    pass
                cursor += 4
            elif char == "/":
                out.append("/")
            else:
                # ``\"``, ``\\``, ``\b``, ``\f`` — сам символ.
                out.append(char)
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            return ("".join(out), True)
        out.append(char)
    # Рядок обірвався на межі шматка — це нормальний стан стріму.
    return ("".join(out), False)


def _json_object_closed(raw: str) -> bool:
    """Чи закрився об'єкт аргументів (фігурна дужка поза рядками).

    Простий підрахунок дужок тут не годиться: ``content`` містить код із
    власними ``{`` і ``}``. Тому проходимо рядок і пропускаємо все, що
    лежить усередині лапок.
    """
    depth = 0
    inside_string = False
    escape = False
    opened = False
    for char in raw:
        if escape:
            escape = False
            continue
        if char == "\\" and inside_string:
            escape = True
            continue
        if char == '"':
            inside_string = not inside_string
            continue
        if inside_string:
            continue
        if char == "{":
            depth += 1
            opened = True
        elif char == "}":
            depth -= 1
            if opened and depth <= 0:
                return True
    return False


@dataclass
class ToolArgsWatcher:
    """Стежить за аргументами інструмента й віддає код правки наживо.

    Один об'єкт — один виклик інструмента. ``feed`` кличеться на кожен
    шматок аргументів (як їх віддає ``chat_stream``), ``result`` повертає
    те, що вже можна показати в редакторі.

    Жива правка показується ЛИШЕ для інструментів, що пишуть код. Для
    ``read_file`` чи ``list_dir`` нічого не відбувається: це не правка, і
    показувати їхній вміст у редакторі як «зміну» було б неправдою.
    """

    name: str = ""
    path: str = ""
    #: Текст, який уже показано (щоб вікно вставляло лише приріст).
    shown: str = ""
    #: Фрагмент, який замінюється (``old_string`` для ``edit_file``).
    search: str = ""
    #: Чи потрібна заміна, а не дописування всього вмісту.
    replaces: bool = False
    #: Чи це ``write_file`` — інструмент переписує файл ЦІЛКОМ.
    whole_file: bool = False
    #: Поле, за яким стежимо.
    field: str = ""
    _raw: str = ""
    _path_done: bool = False
    _search_done: bool = False
    _done: bool = False

    @classmethod
    def for_tool(cls, name: str) -> Optional["ToolArgsWatcher"]:
        """Створити спостерігач, якщо інструмент пише код."""
        clean = str(name or "").strip()
        fields = EDIT_FIELDS.get(clean)
        if not fields:
            return None
        watcher = cls(name=clean)
        watcher.field = fields[0]
        watcher.replaces = clean in SEARCH_FIELDS
        # ``write_file`` переписує файл цілком: старого фрагмента немає,
        # і вікну треба знати про це, інакше новий вміст дописувався б
        # у кінець замість заміни.
        watcher.whole_file = clean == "write_file"
        return watcher

    # ── стрім ──────────────────────────────────────────────────────────────
    def feed(self, piece: str) -> None:
        """Додати шматок аргументів інструмента."""
        if self._done or not piece:
            return
        self._raw += piece
        if not self._path_done:
            value, complete = partial_string_field(self._raw, "path")
            if value:
                self.path = value
            self._path_done = complete and bool(value)
        if self.replaces and not self._search_done:
            value, complete = partial_string_field(self._raw, "old_string")
            if value:
                self.search = value
            self._search_done = complete and bool(value)
        value, complete = partial_string_field(self._raw, self.field)
        if value:
            self.shown = value
        # ``complete`` стосується ЛИШЕ значення поля. Виклик інструмента
        # вважаємо завершеним, лише коли закрилась фігурна дужка об'єкта:
        # інакше ``old_string`` міг прийти ПІСЛЯ ``new_string``, і ми б
        # оголосили правку готовою, не маючи фрагмента для заміни.
        if _json_object_closed(self._raw):
            self._done = True

    @property
    def finished(self) -> bool:
        return self._done

    def ready(self) -> bool:
        """Чи вже є що показувати: шлях і хоч якийсь код."""
        if not self.path or not self.shown:
            return False
        if self.replaces and not self.search:
            # Для заміни без старого фрагмента показувати нічого: невідомо,
            # що саме виділяти. Покажемо після завершення стріму.
            return False
        return True

    def block(self) -> EditBlock:
        """Поточний стан як блок правки (``complete`` — стрім закінчився)."""
        return EditBlock(search=self.search, replace=self.shown,
                         complete=self._done)
