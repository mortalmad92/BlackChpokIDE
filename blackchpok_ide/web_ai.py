"""Безкоштовні ШІ через вбудований браузер: чужа відповідь як другий голос.

Навіщо це потрібно. Локальна модель слабка саме там, де треба широких знань
або акуратного міркування, а платне API скорочується. Водночас у браузері
вже відкриваються безкоштовні чати (їхні вебверсії), і брати їхню відповідь
можна без ключа й без білінгу — так само, як це робить людина руками.

Що тут є:

1. **Реєстр провайдерів** (:data:`PROVIDERS`) — адреса, поля вводу й
   відповіді. Кожен провайдер описано СЕЛЕКТОРАМИ, а не «магією»: якщо сайт
   змінить розмітку, правиться один рядок.
2. **Опитування відповіді** (:func:`poll_answer`) — вебчат відповідає
   потоково, тому читаємо, доки текст не перестане змінюватись.
3. **Об'єднання кількох відповідей** (:func:`combine`) — не «взяти першу», а
   зібрати спільне й позначити розбіжності. Це те, що справді покращує
   роботу: одна модель помиляється впевнено, дві — рідше однаково.
4. **Запис у пам'ять** — те саме залізне правило, що й для ``search_web``:
   отримане знання лягає в NEUROMESH і доступне в інших чатах.

Чесно про межі. Це НЕ обхід захисту й не автоматизація входу: модуль працює
лише з тим браузером, який людина вже відкрила й де вона вже ввійшла, і не
зберігає жодних облікових даних. Якщо доступ до провайдера недоступний —
повертається чесна причина, а не вигадана відповідь.

Модуль не тягне tkinter: він працює з переданою CDP-сесією, тому його можна
перевірити підробленою сесією без жодного вікна й без мережі.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "Answer",
    "CONSENT_SELECTORS",
    "CONSENT_TEXTS",
    "Consensus",
    "Provider",
    "PROVIDERS",
    "ask",
    "combine",
    "dismiss_consent",
    "memories_for",
    "page_text_tail",
    "poll_answer",
    "provider",
    "provider_names",
    "read_answer",
    "submit_prompt",
]

LOG = logging.getLogger("blackchpok.web_ai")

#: Скільки секунд максимум чекаємо на відповідь у браузері.
ANSWER_TIMEOUT = 90.0

#: Як часто перечитуємо текст відповіді (секунди).
POLL_INTERVAL = 1.5

#: Скільки разів поспіль текст має не змінюватись, щоб вважати відповідь
#: завершеною. Два — бо стрімінг іноді «завмирає» на мілісекунди.
STABLE_ROUNDS = 3

#: Мінімальна довжина відповіді, щоб вважати її придатною.
MIN_ANSWER_CHARS = 40


@dataclass(frozen=True)
class Provider:
    """Один безкоштовний вебчат, до якого можна звернутись через браузер."""

    key: str
    label: str
    #: Адреса нового чату.
    url: str
    #: Селектор поля вводу (textarea, contenteditable тощо).
    input_selector: str
    #: Селектори блоків із відповіддю (найновіший — останній).
    answer_selector: str
    #: Чи потрібен вхід у акаунт (для честного повідомлення людині).
    needs_login: bool = True
    #: Чи можна надсилати Enter замість кліку (деякі сайти не мають кнопки).
    send_with_enter: bool = True

    def describe(self) -> str:
        login = "потрібен вхід" if self.needs_login else "без входу"
        return f"{self.label} ({login})"


#: Реєстр провайдерів.
#:
#: Селектори навмисно перелічені через кому: розмітка цих сайтів змінюється,
#: і запасний варіант майже завжди знаходиться. Якщо не знайшлось нічого —
#: повертається чесна причина «розмітка змінилась», а не порожній текст.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key="duckduckgo",
        label="DuckDuckGo AI Chat",
        url="https://duckduckgo.com/?q=DuckDuckGo+AI+Chat&ia=chat",
        input_selector="textarea, [contenteditable='true'], input[type='text']",
        answer_selector=("[data-testid='ai-chat-answer'], .ai-chat-answer, "
                         "div[class*='answer']"),
        needs_login=False,
    ),
    Provider(
        key="perplexity",
        label="Perplexity",
        url="https://www.perplexity.ai/",
        input_selector="textarea, [contenteditable='true']",
        answer_selector=("[data-testid='answer'], .prose, "
                         "div[class*='Answer']"),
    ),
    Provider(
        key="chatgpt",
        label="ChatGPT",
        url="https://chatgpt.com/",
        input_selector="#prompt-textarea, textarea, [contenteditable='true']",
        answer_selector="[data-message-author-role='assistant'], .markdown",
    ),
    Provider(
        key="gemini",
        label="Gemini",
        url="https://gemini.google.com/app",
        input_selector="rich-textarea [contenteditable='true'], textarea",
        answer_selector="message-content, .model-response-text",
    ),
)

_BY_KEY: dict[str, Provider] = {item.key: item for item in PROVIDERS}


def provider_names() -> list[str]:
    """Ключі доступних провайдерів (для налаштувань і журналу)."""
    return [item.key for item in PROVIDERS]


def provider(key: str) -> Provider | None:
    """Провайдер за ключем (``None``, якщо такого немає)."""
    return _BY_KEY.get(str(key or "").strip().lower())


@dataclass
class Answer:
    """Одна відповідь, отримана з браузера."""

    provider: str
    text: str = ""
    ok: bool = True
    error: str = ""
    seconds: float = 0.0

    def is_useful(self) -> bool:
        return self.ok and len(" ".join(self.text.split())) >= MIN_ANSWER_CHARS


@dataclass
class Consensus:
    """Результат об'єднання кількох відповідей."""

    text: str = ""
    #: Провайдери, чиї відповіді справді ввійшли.
    used: list[str] = field(default_factory=list)
    #: Провайдери, які не дали відповіді (з причиною).
    failed: list[str] = field(default_factory=list)
    #: Чи знайшлися розбіжності між відповідями.
    disagreement: bool = False

    def describe(self) -> str:
        parts = [f"відповідей: {len(self.used)}"]
        if self.failed:
            parts.append(f"не вдалось: {len(self.failed)}")
        if self.disagreement:
            parts.append("є розбіжності")
        return ", ".join(parts)


def _clean(text: str) -> str:
    body = " ".join(str(text or "").split())
    # Прибираємо типові «службові» хвости вебчатів: вони не є знанням.
    for suffix in ("Copy", "Regenerate", "Скопіювати", "Регенерувати",
                   "Share", "Поділитися"):
        if body.endswith(suffix):
            body = body[: -len(suffix)].strip()
    return body


#: Кнопки згоди/прийняття, які блокують чат.
#:
#: Перевірено наживо 21.11.2026: DuckDuckGo показує вікно «Натиснувши
#: «Продовжити», ви погоджуєтеся…» — запит вводився у поле, але не
#: надсилався, і агент чекав 90 секунд на відповідь, якої не буде.
#: Це не «обхід захисту»: ми натискаємо ту саму кнопку, яку натиснула б
#: людина, і лише для власного браузера користувача.
CONSENT_TEXTS: tuple[str, ...] = (
    "Продовжити", "Прийняти", "Прийняти все", "Погоджуюсь", "Згоден",
    "Accept", "Accept all", "I agree", "Continue", "Got it", "OK",
)

#: Селектори кнопок згоди (у порядку спроби).
CONSENT_SELECTORS: tuple[str, ...] = (
    "button[aria-label*='Accept']", "button[aria-label*='Прийняти']",
    "button[data-testid*='accept']", "button[class*='accept']",
    "button[class*='consent']", "button[class*='agree']",
)

#: Скільки секунд чекати після натискання згоди.
CONSENT_WAIT = 3.0


def dismiss_consent(session: Any, *, sleep: Callable[[float], None] = time.sleep) -> str:
    """Прибрати вікно згоди, якщо воно блокує чат.

    Повертає текст натиснутої кнопки (порожній рядок — вікна не було).
    Спершу пробуємо селектори, потім — кнопку за ТЕКСТОМ: саме так воно
    виглядає на DuckDuckGo (``<button>Продовжити</button>``).
    """
    # 1. Селектори.
    for selector in CONSENT_SELECTORS:
        try:
            if session.click_selector(selector):
                sleep(CONSENT_WAIT)
                return selector
        except Exception:                        # noqa: BLE001
            continue
    # 2. За текстом кнопки (точний збіг, без підрядків).
    for text in CONSENT_TEXTS:
        script = (
            "(function(){"
            "const want=" + repr(text) + ".toLowerCase();"
            "const nodes=document.querySelectorAll("
            "'button, [role=\"button\"], a');"
            "for(const node of nodes){"
            "const label=(node.innerText||node.textContent||'').trim().toLowerCase();"
            "if(label===want){node.click();return label;}}"
            "return '';})()"
        )
        try:
            clicked = session.evaluate(script)
        except Exception:                        # noqa: BLE001
            continue
        if clicked:
            sleep(CONSENT_WAIT)
            return str(clicked)
    return ""


def read_answer(session: Any, spec: Provider) -> str:
    """Прочитати поточний текст відповіді зі сторінки.

    Беремо ОСТАННІЙ знайдений блок: у вебчаті відповідей може бути кілька
    (історія), і саме останній належить поточному запиту.
    """
    script = (
        "(function(){"
        f"const nodes=document.querySelectorAll({spec.answer_selector!r});"
        "if(!nodes.length)return '';"
        "const last=nodes[nodes.length-1];"
        "return (last.innerText||last.textContent||'').trim();"
        "})()"
    )
    try:
        value = session.evaluate(script)
    except Exception:                            # noqa: BLE001
        LOG.debug("Відповідь із браузера не прочитано", exc_info=True)
        return ""
    return _clean(value if isinstance(value, str) else str(value or ""))


def page_text_tail(session: Any, *, limit: int = 700) -> str:
    """Останній текст сторінки — для чесної причини невдачі."""
    try:
        value = session.evaluate(
            "(function(){const b=document.body;if(!b)return '';"
            "return (b.innerText||'').slice(-"
            + str(max(100, int(limit))) + ");})()")
    except Exception:                            # noqa: BLE001
        return ""
    return _clean(value if isinstance(value, str) else str(value or ""))


def submit_prompt(session: Any, spec: Provider, prompt: str) -> bool:
    """Ввести запит у поле й надіслати його.

    Два кроки замість одного: ``click_selector`` фокусує поле, ``type_text``
    набирає текст, ``press_key`` надсилає. Саме так поводиться людина, і це
    працює навіть там, де кнопка «надіслати» з'являється лише після вводу.
    """
    body = str(prompt or "").strip()
    if not body:
        return False
    try:
        if not session.click_selector(spec.input_selector):
            return False
        if not session.type_text(body):
            return False
        if spec.send_with_enter:
            return bool(session.press_key("Enter"))
        return True
    except Exception:                            # noqa: BLE001
        LOG.debug("Запит у браузері не надіслано", exc_info=True)
        return False


def poll_answer(session: Any, spec: Provider, *,
                timeout: float = ANSWER_TIMEOUT,
                interval: float = POLL_INTERVAL,
                sleep: Callable[[float], None] = time.sleep) -> Answer:
    """Дочекатись відповіді: читаємо, доки текст не перестане змінюватись.

    ``sleep`` передається параметром — так тест перевіряє логіку без
    реального очікування (і без 90 секунд на прогін).
    """
    started = time.time()
    last = ""
    stable = 0
    while time.time() - started < timeout:
        sleep(interval)
        current = read_answer(session, spec)
        if current and current == last:
            stable += 1
            if stable >= STABLE_ROUNDS:
                return Answer(provider=spec.key, text=current,
                              seconds=round(time.time() - started, 1))
        else:
            stable = 0
        # ``last`` оновлюємо ЗАВЖДИ, коли прийшов непорожній текст: інакше
        # після таймауту поверталась порожнеча, хоч частину відповіді
        # браузер уже показав (перевірено тестом на частковій відповіді).
        if current:
            last = current
    if last:
        # Час вийшов, але текст є — віддаємо його з поміткою, що він може
        # бути неповним. Це краще, ніж порожнеча.
        return Answer(provider=spec.key, text=last, ok=True,
                      error="відповідь може бути неповною (таймаут)",
                      seconds=round(time.time() - started, 1))
    return Answer(provider=spec.key, ok=False,
                  error="відповіді не дочекались (розмітка змінилась або "
                        "потрібен вхід)",
                  seconds=round(time.time() - started, 1))


def ask(session: Any, spec: Provider, prompt: str, *,
        timeout: float = ANSWER_TIMEOUT,
        navigate: Callable[[str], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep) -> Answer:
    """Спитати один вебчат: відкрити, прибрати згоду, надіслати, дочекатись."""
    if navigate is not None:
        try:
            navigate(spec.url)
        except Exception:                        # noqa: BLE001
            return Answer(provider=spec.key, ok=False,
                          error="сторінку не відкрито")
    # ── Вікно згоди ───────────────────────────────────────────────────────
    # Перевірено наживо: без цього кроку запит лягав у поле, але не
    # надсилався, і агент чекав 90 секунд на відповідь, якої не буде.
    try:
        dismissed = dismiss_consent(session, sleep=sleep)
    except Exception:                            # noqa: BLE001
        dismissed = ""
    if dismissed:
        LOG.info("Вікно згоди закрито: %s", dismissed)
    if not submit_prompt(session, spec, prompt):
        return Answer(provider=spec.key, ok=False,
                      error="поле вводу не знайдено (розмітка змінилась або "
                            "потрібен вхід)")
    return poll_answer(session, spec, timeout=timeout, sleep=sleep)


#: Ознаки того, що дві відповіді суперечать одна одній.
_CONFLICT_WORDS = (
    "не ", "ні ", "never", "not ", "incorrect", "wrong", "помилк",
)

_NUMBER = re.compile(r"\d[\d\s.,]*")


def _numbers(text: str) -> set[str]:
    """Числа з тексту (нормалізовані) — головні «факти», які порівнюємо."""
    found: set[str] = set()
    for match in _NUMBER.findall(text or ""):
        clean = match.strip().strip(".,").replace(" ", "")
        if len(clean) >= 2:
            found.add(clean)
    return found


def combine(answers: Sequence[Answer], *,
            limit_chars: int = 1200) -> Consensus:
    """Об'єднати кілька відповідей у звіт для моделі.

    Навіщо не «взяти першу». Одна модель помиляється впевнено; дві різні —
    рідше помиляються ОДНАКОВО. Тому:

    * якщо відповідь одна — віддаємо її як є;
    * якщо кілька — беремо найдовшу як основу й додаємо те, чого в ній
      немає (за збігом чисел і ключових слів);
    * розбіжність у ЧИСЛАХ позначаємо окремо: саме на числах модель
      вигадує найвпевненіше.
    """
    useful = [item for item in answers if item.is_useful()]
    failed = [f"{item.provider}: {item.error or 'порожньо'}"
              for item in answers if not item.is_useful()]
    if not useful:
        return Consensus(failed=failed)

    usable = sorted(useful, key=lambda item: -len(item.text))
    base = usable[0]
    numbers = _numbers(base.text)
    conflicts: list[str] = []
    extras: list[str] = []
    for other in usable[1:]:
        other_numbers = _numbers(other.text)
        # Числа, яких немає в основі й немає в інших, — це саме та розбіжність,
        # через яку варто показати обидві відповіді.
        only_here = other_numbers - numbers
        if only_here and len(only_here) >= 1:
            conflicts.append(other.provider)
            extras.append(f"[{other.provider}] {other.text[:limit_chars]}")
        numbers |= other_numbers

    parts = [base.text[:limit_chars]]
    if extras:
        parts.append("Інші відповіді (є розбіжності — перевір):")
        parts.extend(extras)
    if conflicts:
        # Явно кажемо моделі, що тут треба перевірити, а не вірити наосліп.
        # Перевірка стоїть на ``conflicts``, а не на пошуку слів у тексті:
        # раніше слово «не» в самій відповіді скасовувало попередження, і
        # модель отримувала суперечливі числа без жодної позначки.
        parts.append("УВАГА: відповіді розходяться в числах або фактах. "
                     "Познач, чого не знаєш, і не вигадуй.")
    text = "\n\n".join(parts)
    return Consensus(text=text, used=[item.provider for item in useful],
                     failed=failed, disagreement=bool(conflicts))


def memories_for(consensus: Consensus) -> list[str]:
    """Твердження для довгострокової пам'яті (те саме залізне правило)."""
    if not consensus.text.strip():
        return []
    source = ", ".join(consensus.used) or "браузер"
    body = consensus.text.strip()
    if len(body) > 1200:
        body = body[:1199] + "…"
    return [f"Відповідь безкоштовного ШІ ({source}): {body}"]
