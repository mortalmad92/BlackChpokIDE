"""Автоматичне регулювання контексту для БУДЬ-ЯКОЇ моделі.

Навіщо окремий модуль. Реальний збій, який користувач бачив як «модель не
працює»:

```
--ctx-size 32768            ← стільки попросили в IDE
n_ctx_slot = 16384          ← стільки РЕАЛЬНО дав сервер (ділить на слоти)
промпт = 8549 токенів
+ система, схеми інструментів, історія, відповідь…
→ сервер обриває з'єднання (WinError 10054)
```

Тобто число в налаштуваннях могло бути більшим за реальне вікно моделі.
Досі ніхто не звіряв ці числа, і агент надсилав промпт навмання.

Модуль робить три речі:

1. **Визначає справжнє вікно** — з ``/props`` (``n_ctx``), з метаданих GGUF,
   з налаштувань, зрешті — з безпечного запасу. Це джерело правди, а не
   «скільки попросили в налаштуваннях».
2. **Планує бюджет** — скільки лишити на систему, схеми інструментів,
   історію й відповідь, із запасом під похибку токенізації.
3. **Стискає запит до бюджету** — не «коли вже обірвалось», а ЗАЗДАЛЕГІДЬ.

Модуль не залежить від tkinter і не робить мережевих викликів: усе, що
потрібно з мережі, передає викликач (``measure``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

LOG = logging.getLogger("blackchpok.context_budget")

#: Найменше вікно, з яким ще можна працювати агентськи. Менше — це вже
#: не «малий контекст», а непрацездатна конфігурація: системний промпт і
#: схеми інструментів самі займають тисячі токенів.
MIN_USABLE_WINDOW = 2048

#: Розмір, до якого варто ЗАПОВНЮВАТИ вікно (а не лише мати).
#:
#: Різниця принципова, і вона заміряна 21.11.2026 на RTX 3060 + 64 ГБ RAM
#: (кеш KV у RAM, q8_0):
#:
#:   токенів   час першої відповіді   швидкість
#:      2 000            3.6 с          560 т/с
#:      8 000           12.2 с          654 т/с
#:     16 000           23.0 с          695 т/с
#:     32 000           68.7 с          466 т/с
#:     64 000          229.5 с          279 т/с
#:
#: Тобто вікно 131 072 СПРАВДІ працює й ніколи не переповнюється — але
#: заповнювати його повністю означало б чекати майже 4 хвилини на кожен
#: запит. Тому:
#:
#: * **вікно** (скільки модель може) — уся доступна пам'ять (131k+);
#: * **бюджет заповнення** (скільки реально тримаємо) — до 32 768.
#:
#: Решта не «втрачається»: вона переїжджає в довгострокову пам'ять
#: (NEUROMESH + RAG + хроніка) і повертається пошуком. Саме це й робить
#: роботу швидкою, не втрачаючи знань.
#:
#: Це ВЕРХНЯ межа «за замовчуванням», а не постійний розмір: скільки саме
#: заповнити — вирішує :func:`working_window` під КОЖЕН запит.
WORKING_WINDOW = 32_768

#: Крок округлення робочого бюджету.
#:
#: Навіщо округлення, а не «рівно скільки треба». По-перше, людині й
#: журналу зрозуміліше «16 384», ніж «13 517». По-друге, час першої
#: відповіді заміряний саме на круглих розмірах (:data:`LATENCY_TABLE`),
#: тож обіцянка «~23 с» лишається правдою. По-третє, близькі запити
#: отримують однаковий бюджет, і префікс промпту не перебудовується.
#:
#: Сам крок — 2 048, а не «густа драбина»: дрібніше округлення не змінює
#: відчуття швидкості, зате дає незрозумілі числа в рядку стану.
CONTEXT_STEP = 2_048

#: Скільки максимум відкладати під САМУ відповідь у РОЗПОДІЛІ бюджету.
#:
#: ``ANSWER_SHARE`` (25%) — це частка, але на вікні 131k вона давала 32k
#: «про запас», і сама ця частка роздувала робочий бюджет: «привіт»
#: отримував 73 с замість 20. Насправді резерв під відповідь НЕ впливає на
#: час до першого токена — час визначає розмір промпту. Тому резерв
#: обмежений зверху: 4 096 токенів вистачає на розгорнуту відповідь із
#: кодом, а реальна стеля відповіді однаково береться з ``llm.max_tokens``
#: (див. ``agent._answer_budget``).
ANSWER_RESERVE_CAP = 4_096

#: Заміряно 21.11.2026 (RTX 3060 + 64 ГБ RAM, кеш KV у RAM, q8_0):
#: ``(токенів у промпті, секунд до першого токена відповіді)``.
LATENCY_TABLE: tuple[tuple[int, float], ...] = (
    (2_000, 3.6),
    (8_000, 12.2),
    (16_000, 23.0),
    (32_000, 68.7),
    (64_000, 229.5),
)

#: Скільки додати понад виміряну потребу (відповідь, службові дані, похибка
#: токенізації кирилиці). Скільки саме — залежить від глибини запиту
#: (див. ``agent._DEPTH_MARGIN``): питання-факт не потребує запасу на код.
DEFAULT_MARGIN = 0.35

#: Скільки місця лишати під САМУ РОБОТУ, навіть якщо виміряна потреба мала.
#:
#: Навіщо це окреме число. Виміряна потреба — це те, що вже лежить у сесії
#: ЗАРАЗ: репліка «виправ баг» — це 30 токенів. Але наступний крок
#: прочитає файл, і в сесії опиниться вже 8 000 токенів. Якби бюджет
#: дорівнював виміряній потребі, кожен такий крок різався б під ніж.
#:
#: Тому мінімум «кімнати» задає ГЛИБИНА запиту (див.
#: ``agent._DEPTH_ROOM``): питання-факт — 2k, звичайний запит — 6k,
#: правка — 10k, продовження роботи — 24k.
MIN_ROOM = 1_024


def latency_seconds(tokens: int) -> float:
    """Скільки секунд приблизно чекати першу відповідь на такому промпті.

    Числа — заміряні (:data:`LATENCY_TABLE`), між точками — лінійна
    інтерполяція, далі — та сама крутизна, що й на останній ділянці. Це
    оцінка для людини («~14 с»), а не гарантія: швидкість залежить ще й
    від вільної VRAM та довжини самої відповіді.
    """
    size = max(0, int(tokens or 0))
    if size <= 0:
        return 0.0
    first_tokens, first_seconds = LATENCY_TABLE[0]
    if size <= first_tokens:
        return round(first_seconds * size / first_tokens, 1)
    for (left_tokens, left_seconds), (right_tokens, right_seconds) in zip(
            LATENCY_TABLE, LATENCY_TABLE[1:]):
        if size <= right_tokens:
            span = right_tokens - left_tokens
            share = (size - left_tokens) / span
            return round(left_seconds + (right_seconds - left_seconds) * share, 1)
    (last_tokens, last_seconds), = LATENCY_TABLE[-1:]
    (prev_tokens, prev_seconds), = LATENCY_TABLE[-2:-1]
    slope = (last_seconds - prev_seconds) / (last_tokens - prev_tokens)
    return round(last_seconds + (size - last_tokens) * slope, 1)


def _snap_up(target: int) -> int:
    """Підняти бюджет до найближчого кроку (:data:`CONTEXT_STEP`).

    Округлення ВГОРУ, а не вниз: краще дати на 2k більше, ніж обрізати
    запит, який щойно вліз. Стеля моделі й стеля людини застосовуються
    вже після цього (див. :func:`working_window`).
    """
    step = CONTEXT_STEP
    return max(step, ((max(0, int(target)) + step - 1) // step) * step)


def working_window(*, needed: int = 0, window: int = 0,
                   mode: str = "auto", ceiling: int = 0,
                   fixed: int = 0, room: int = 0,
                   margin_share: float | None = None) -> int:
    """Скільки контексту РЕАЛЬНО заповнювати — за потребою ЦЬОГО запиту.

    Вимога користувача (21.11.2026): «зроби автовизначення в залежності від
    потреби на запит користувача».

    Навіщо автовизначення, а не одне число. Вікно моделі на цій машині —
    131 072 токени (кеш KV у RAM), і в стіну «переповнено» агент не
    впирається ніколи. Але ЗАПОВНЕННЯ коштує часу прямо пропорційно
    (:data:`LATENCY_TABLE`): 2k — це 3.6 с, а 64k — майже 4 хвилини.
    Тримати 131k заради «привіт» — чекати хвилини на дрібницю; тримати 4k
    на «прочитай ці два файли й порівняй» — не мати потрібного тексту.

    ── ЯК РАХУЄТЬСЯ ──────────────────────────────────────────────────────
    Бюджет не може дорівнювати потребі: у ньому ще мусить лишитись місце
    під САМУ відповідь і запас на похибку токенізації
    (:data:`ANSWER_SHARE` + :data:`SAFETY_SHARE`). Тому до потреби додаємо
    резерв, а не масштабуємо її:

        fixed    = система + схеми інструментів      ← не стискається
        variable = max(needed − fixed, room) × (1 + запас)
        target   = fixed + variable + резерв         ← під відповідь

    ``room`` — гарантоване місце під САМУ роботу (за глибиною запиту).
    Виміряна потреба описує, що лежить у сесії ЗАРАЗ, а наступний крок
    додасть результати інструментів, тож без ``room`` бюджет дорівнював би
    поточній репліці й різав кожен наступний крок під ніж.

    Параметри:

    * ``needed`` — виміряна потреба; ``0`` = «невідомо» → обережна типова
      поведінка (:data:`WORKING_WINDOW`);
    * ``window`` — скільки модель МОЖЕ (її справжнє вікно);
    * ``mode`` — ``auto`` (типово), ``max`` (усе дозволене), ``fast``
      (не більше :data:`WORKING_WINDOW`);
    * ``ceiling`` — стеля від людини (``agent.working_context``; ``0`` —
      без стелі);
    * ``fixed`` — незмінна частина потреби (система + схеми);
    * ``room`` — мінімум місця під роботу;
    * ``margin_share`` — частка запасу на ріст роботи (за глибиною запиту).

    Ніколи не повертає більше за ``window`` і за ``ceiling``; ніколи не
    менше за :data:`MIN_USABLE_WINDOW` (менше — непрацездатна
    конфігурація: самі схеми інструментів займають тисячі токенів).
    """
    total = max(0, int(window or 0))
    if total <= 0:
        total = WORKING_WINDOW
    try:
        bound = int(ceiling or 0)
    except (TypeError, ValueError):
        bound = 0
    top = min(total, bound) if bound > 0 else total

    choice = str(mode or "auto").strip().lower()
    if choice in ("max", "full", "all"):
        return max(MIN_USABLE_WINDOW, top)
    if choice in ("fast", "fixed", "off"):
        return max(MIN_USABLE_WINDOW, min(top, WORKING_WINDOW))

    # ── auto ──────────────────────────────────────────────────────────────
    want = max(0, int(needed or 0))
    if want <= 0:
        # Потреба НЕВІДОМА (бюджет рахували до запиту): обережне типове
        # число, як до 21.11.2026. Це окрема вісь — «не міряли», а не
        # «міряли й вийшло мало», тому вона не входить у монотонність.
        return max(MIN_USABLE_WINDOW, min(top, WORKING_WINDOW))
    try:
        share = DEFAULT_MARGIN if margin_share is None else float(margin_share)
    except (TypeError, ValueError):
        share = DEFAULT_MARGIN
    share = min(1.0, max(0.0, share))
    structural = max(0, int(fixed or 0))
    # ── Потреба не буває МЕНШОЮ за незмінну частину ───────────────────────
    # ``needed`` міряє, що лежить у сесії. Якщо репліка коротка («привіт»),
    # виміряна потреба могла вийти меншою за самі схеми — і бюджет падав би
    # НИЖЧЕ за реально необхідне (перевірено: 1 000 токенів потреби давали
    # 12 288 при потребі 0 → 32 768, тобто більша потреба отримувала МЕНШЕ).
    want = max(want, structural)
    pinned = min(structural, want)
    minimum_room = max(MIN_ROOM, int(room or 0))
    variable = max(want - pinned, minimum_room) * (1.0 + share)
    reserve = int(min(ANSWER_RESERVE_CAP, max(512, (pinned + variable)
                                              * ANSWER_SHARE)))
    target = pinned + variable + reserve
    return max(MIN_USABLE_WINDOW, min(top, _snap_up(int(target) + 1)))



#: Вимкнути авто-визначення й заповнювати все вікно.
#:
#: Типово ``False``: розмір підбирається під запит
#: (:func:`working_window`). ``True`` — поведінка «завжди все вікно».
WORKING_LIMIT_OFF = False

#: Частка вікна під ВІДПОВІДЬ моделі. 25% — компроміс: локальні моделі
#: люблять довгі відповіді з кодом, і замалий резерв обрізав би їх посередині.
ANSWER_SHARE = 0.25

#: Частка вікна під ІСТОРІЮ діалогу (решта — система, схеми, відповідь).
#:
#: ЗВЕРНИ УВАГУ: це стеля, а не «скільки завжди віддати». Обчислюється вона
#: від ``room`` (те, що лишилось ПІСЛЯ системи, схем і відповіді), тому схеми
#: й історія не можуть одночасно забрати те саме місце. Саме через це раніше
#: при вікні 16k і 91 інструменті історія ставала НУЛЕМ.
HISTORY_SHARE = 0.55

#: Запас на похибку підрахунку токенів. Точний tokenizer є не завжди, а
#: українська кирилиця дає до 2× похибки в евристиці.
SAFETY_SHARE = 0.10

#: Скільки токенів додавати на службову обгортку кожного повідомлення
#: (роль, роздільники) — приблизно, але краще переоцінити.
PER_MESSAGE_OVERHEAD = 6


@dataclass
class Window:
    """Справжнє вікно контексту моделі та його походження.

    ``source`` — ЗВІДКИ число. Це принципово: користувач має бачити, чи це
    реальний ліміт сервера, чи обережна оцінка.
    """

    tokens: int = 0
    source: str = ""
    #: Модель сама повідомила ліміт (``/props``) — найнадійніше джерело.
    measured: bool = False
    note: str = ""

    @property
    def usable(self) -> int:
        return max(0, int(self.tokens))

    def text(self) -> str:
        if not self.tokens:
            return "вікно невідоме — працюю з обережним запасом"
        return f"{self.tokens:,} токенів ({self.source})".replace(",", " ")


@dataclass
class Budget:
    """Розподіл вікна під час одного запиту."""

    window: int = 0
    answer: int = 0
    history: int = 0
    tools: int = 0
    system: int = 0
    safety: int = 0
    #: Скільки токенів лишилось на власне повідомлення й результати.
    payload: int = 0
    #: Скільки ми ЗАПОВНЮЄМО (може бути менше за вікно — див.
    #: :func:`working_window`). ``0`` — як вікно.
    working: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def effective(self) -> int:
        """Розмір, від якого пораховані частки (вікно або робочий бюджет)."""
        return int(self.working or self.window)

    def latency_text(self) -> str:
        """Скільки приблизно чекати першу відповідь на цьому бюджеті."""
        return f"~{latency_seconds(self.effective):.0f} с"

    def text(self) -> str:
        parts = [f"вікно {self.window:,}"]
        if self.working and self.working != self.window:
            parts.append(f"заповнюю {self.working:,} ({self.latency_text()})")
        parts.extend([
            f"відповідь {self.answer:,}",
            f"історія {self.history:,}",
            f"інструменти {self.tools:,}",
            f"система {self.system:,}",
            f"запас {self.safety:,}",
        ])
        return " · ".join(parts).replace(",", " ")


def resolve_window(*, settings: Any = None, props_ctx: int = 0,
                   gguf_ctx: int = 0, model_params_b: float = 0.0,
                   source: str = "") -> Window:
    """Визначити справжнє вікно контексту з усіх доступних джерел.

    Пріоритет навмисний — від найнадійнішого до найобережнішого:

    1. ``props_ctx`` — що сервер САМ сказав (``/props`` → ``n_ctx``).
       Це єдине джерело, яке знає про поділ на слоти: ``--ctx-size 32768``
       при двох слотах дає ``n_ctx = 16384``, і саме це реальний ліміт.
    2. ``gguf_ctx`` — тренувальне вікно з метаданих моделі
       (``*.context_length``): навіть якщо сервер запущено з більшим
       числом, модель не вміє далі.
    3. налаштування IDE (``engine.ctx_size``) — те, що попросив користувач.
    4. обережний запас за розміром моделі.

    ``source`` — людська назва джерела для пункту 1. У вбудованого рушія
    немає ``/props``: там вікно читається з контексту в пам'яті, і писати
    «сервер /props» означало б збрехати користувачу про походження числа.
    """
    floor = MIN_USABLE_WINDOW
    if props_ctx and props_ctx > 0:
        tokens = int(props_ctx)
        # Модель не вміє більше за своє тренувальне вікно — не обманюємось.
        if gguf_ctx and gguf_ctx > 0:
            tokens = min(tokens, int(gguf_ctx))
        return Window(tokens=max(floor, tokens),
                      source=(source or "сервер /props"), measured=True)
    if gguf_ctx and gguf_ctx > 0:
        return Window(tokens=max(floor, int(gguf_ctx)),
                      source="метадані моделі", measured=True)
    requested = 0
    if settings is not None:
        try:
            requested = int(getattr(settings.engine, "ctx_size", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            requested = 0
    if requested > 0:
        return Window(tokens=max(floor, requested), source="налаштування IDE")
    # Нічого не відомо — беремо запас за розміром моделі. Велика модель
    # зазвичай має більше вікно, але обіцяти багато небезпечно.
    guess = 8192 if (model_params_b or 0) >= 7 else 16384
    LOG.info("Вікно контексту невідоме — беру обережний запас %s", guess)
    return Window(tokens=guess, source="обережний запас",
                  note="точне вікно невідоме: сервер не повідомив n_ctx")


def plan(window: Window | int, *, system_tokens: int = 0,
         tools_tokens: int = 0, needed: int = 0,
         mode: str = "auto", ceiling: int = 0, room: int = 0,
         margin_share: float | None = None) -> Budget:
    """Розподілити вікно: відповідь, історія, система, схеми, запас.

    ``payload`` — скільки токенів лишається на повідомлення й результати
    інструментів. Саме це число агент використовує для стискання, і саме
    його бракувало: раніше історія різалась за фіксованою формулою, яка не
    знала ні реального вікна, ні розміру схем.

    ── ВІКНО vs БЮДЖЕТ ЗАПОВНЕННЯ ────────────────────────────────────────
    ``total`` — скільки модель МОЖЕ тримати (до 131 072 на цій машині).
    ``working`` — скільки ми реально ЗАПОВНЮЄМО цього разу, і його обирає
    :func:`working_window` під сам запит: ``needed`` — виміряна потреба
    (система + схеми + історія + дані), ``room`` — мінімум під роботу,
    ``mode`` — вибір людини, ``ceiling`` — її стеля
    (``agent.working_context``).

    Без ``needed`` (0) розмір береться обережно — :data:`WORKING_WINDOW`:
    так було до 21.11.2026, і так лишається для викликів без виміру.
    """
    total = int(window.tokens if isinstance(window, Window) else window) or 0
    if total <= 0:
        return Budget()
    system = max(0, int(system_tokens))
    tools = max(0, int(tools_tokens))
    effective = working_window(needed=needed, window=total, mode=mode,
                               ceiling=ceiling, fixed=system + tools,
                               room=room, margin_share=margin_share)
    if WORKING_LIMIT_OFF:
        effective = total
    answer = max(256, int(effective * ANSWER_SHARE))
    safety = max(128, int(effective * SAFETY_SHARE))
    free = effective - answer - safety - system - tools
    if free < 256:
        # Схеми й система самі з'їли вікно: це чесна діагностика, а не
        # мовчазний збій. Викликач має зменшити набір інструментів.
        LOG.warning("Контекст переповнений службовими даними: вікно %s "
                    "(робоче %s), система %s, схеми %s",
                    total, effective, system, tools)
    # ── Історія не має права забрати ВСЮ кімнату ──────────────────────────
    # Коли службові дані з'їли майже все, ``free`` малий, і «частка вікна
    # на історію» дорівнювала б усьому залишку — тоді ``payload`` ставав
    # НУЛЕМ, тобто місця під саму репліку користувача не лишалось
    # (перевірено: «історія 4 470 · payload 0» — модель не бачила запиту).
    # Тому історія бере частку вікна, але не більше за те, що лишається
    # після гарантованого місця під поточне повідомлення.
    history_ceiling = max(0, free - MIN_ROOM) if free else 0
    history = max(0, min(int(effective * HISTORY_SHARE), history_ceiling))
    payload = max(0, free - history)
    budget = Budget(window=total, answer=answer, history=history,
                    tools=tools, system=system, safety=safety, payload=payload,
                    working=effective)
    if effective < total:
        budget.notes.append(
            f"заповнюю {effective} із вікна {total}: більший контекст "
            f"сповільнює відповідь ({latency_seconds(effective):.0f} с проти "
            f"{latency_seconds(total):.0f} с), решта знань — у пам'яті")
    if system + tools > effective * 0.5:
        budget.notes.append(
            f"службові дані {system + tools} токенів — понад половину "
            f"робочого бюджету {effective}")
    if free < 256:
        budget.notes.append(
            f"службові дані ({system + tools} токенів) майже з'їли вікно "
            f"{total}")
    if total < MIN_USABLE_WINDOW:
        budget.notes.append(
            f"вікно {total} замале для агентської роботи (мінімум "
            f"{MIN_USABLE_WINDOW})")
    return budget


def estimate_tokens(text: str, *, counter=None) -> int:
    """Оцінити токени рядка (точний лічильник, якщо є)."""
    body = str(text or "")
    if not body:
        return 0
    if counter is not None:
        try:
            exact = int(counter(body))
            if exact > 0:
                return exact + PER_MESSAGE_OVERHEAD
        except Exception:  # noqa: BLE001 - лічильник не має ламати оцінку
            LOG.debug("Точний підрахунок не вдався", exc_info=True)
    cyrillic = sum(1 for ch in body if "\u0400" <= ch <= "\u04FF")
    latin = len(body) - cyrillic
    return int(cyrillic / 1.6 + latin / 3.6) + PER_MESSAGE_OVERHEAD + 2


def fit_messages(messages: Iterable[dict[str, Any]], budget_tokens: int, *,
                 counter=None, keep_first: int = 1) -> list[dict[str, Any]]:
    """Обрізати історію так, щоб вона влізла в ``budget_tokens``.

    Зберігаємо:

    * перші ``keep_first`` повідомлень (системний контекст);
    * ОСТАННІ повідомлення — найсвіжіше завжди важливіше за давнє.

    Обрізаємо СЕРЕДИНУ, а не кінець: саме так розмова лишається зв'язною.
    """
    items = list(messages)
    if not items or budget_tokens <= 0:
        return items
    counts = [estimate_tokens(str(item.get("content") or ""), counter=counter)
              for item in items]
    total = sum(counts)
    if total <= budget_tokens:
        return items
    head = items[:keep_first]
    head_tokens = sum(counts[:keep_first])
    tail: list[dict[str, Any]] = []
    used = head_tokens
    for index in range(len(items) - 1, keep_first - 1, -1):
        if used + counts[index] > budget_tokens:
            break
        tail.insert(0, items[index])
        used += counts[index]
    if not tail and len(items) > keep_first:
        # Навіть одне повідомлення не влізає — лишаємо найсвіжіше, але
        # помічаємо це для викликача (він покаже користувачу).
        tail = [items[-1]]
    result = head + tail
    dropped = len(items) - len(result)
    if dropped:
        LOG.info("Історію стиснуто: -%s повідомлень (%s токенів бюджету)",
                 dropped, budget_tokens)
    return result


__all__ = [
    "ANSWER_RESERVE_CAP",
    "ANSWER_SHARE",
    "Budget",
    "CONTEXT_STEP",
    "DEFAULT_MARGIN",
    "HISTORY_SHARE",
    "LATENCY_TABLE",
    "MIN_ROOM",
    "MIN_USABLE_WINDOW",
    "SAFETY_SHARE",
    "WORKING_LIMIT_OFF",
    "WORKING_WINDOW",
    "Window",
    "estimate_tokens",
    "fit_messages",
    "latency_seconds",
    "plan",
    "resolve_window",
    "working_window",
]
