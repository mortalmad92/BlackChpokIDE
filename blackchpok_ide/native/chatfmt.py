"""Шаблони чату й адаптер tool calling для власного рушія.

llama.cpp уміє застосовувати Jinja-шаблон із метаданих GGUF
(``tokenizer.chat_template``). Це єдиний надійний спосіб отримати від
моделі те, що вона очікує: Qwen іде з ``<|im_start|>``, Llama 3 — з
``<|start_header_id|>``, Gemma — зі своїми маркерами.

Модуль дає:

* :class:`ChatFormatter` — рендер повідомлень через шаблон моделі;
* :func:`tool_schemas_prompt` — текстовий опис інструментів для моделей,
  які не мають нативного tool calling (безпечний адаптер: модель просять
  відповісти JSON-об'єктом, а розбір іде контрольовано);
* :func:`extract_tool_calls` — розбір тієї відповіді;
* :class:`ToolCallParser` — потоковий розбір, щоб не показувати
  користувачу сирий JSON замість відповіді.

Важливо: нативний формат інструментів підтримують далеко не всі моделі.
Тому ми не «вмикаємо» tool calling наосліп, а питаємо модель про
можливість (див. :mod:`.engine` → ``supports_native_tools``) і за потреби
переходимо на текстовий адаптер.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ._abi import LlamaChatMessage
from ._bindings import LlamaLibrary

LOG = logging.getLogger("blackchpok.native.chatfmt")

#: Запасні шаблони, коли в GGUF їх немає (у порядку переваги).
FALLBACK_TEMPLATES = {
    "chatml": (
        "{% for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}<|im_end|>\n"
        "{% endfor %}{% if add_assistant %}<|im_start|>assistant\n{% endif %}"
    ),
    "llama3": (
        "<|begin_of_text|>{% for m in messages %}<|start_header_id|>{{ m.role }}"
        "<|end_header_id|>\n\n{{ m.content }}<|eot_id|>{% endfor %}"
        "{% if add_assistant %}<|start_header_id|>assistant<|end_header_id|>\n\n{% endif %}"
    ),
    "plain": (
        "{% for m in messages %}{{ m.role }}: {{ m.content }}\n{% endfor %}"
        "{% if add_assistant %}assistant: {% endif %}"
    ),
}

#: Маркери архітектур → запасний шаблон.
_TEMPLATE_HINTS = (
    ("qwen", "chatml"),
    ("llama", "llama3"),
    ("mistral", "plain"),
    ("gemma", "chatml"),
    ("phi", "plain"),
    ("deepseek", "chatml"),
)


def guess_template(architecture: str, name: str = "") -> str:
    """Обрати запасний шаблон за архітектурою моделі."""
    haystack = f"{architecture} {name}".lower()
    for marker, template in _TEMPLATE_HINTS:
        if marker in haystack:
            return template
    return "chatml"


class ChatFormatter:
    """Рендер повідомлень у промпт конкретної моделі."""

    def __init__(self, lib: LlamaLibrary, model: int, *,
                 template: str = "", stop: tuple[str, ...] | None = None) -> None:
        self._lib = lib
        self._model = model
        self.template = template or self._detect_template()
        self.stop = tuple(stop or ()) or self._detect_stop()
        self._builtin_warning = False

    def _detect_template(self) -> str:
        raw = self._lib.llama_model_chat_template(self._model, None)
        if raw:
            return raw.decode("utf-8", "replace")
        # Немає шаблону в GGUF — беремо типовий для архітектури.
        self._builtin_warning = True
        return ""

    def _detect_stop(self) -> tuple[str, ...]:
        template = self.template or ""
        stops: list[str] = []
        for marker in ("<|im_end|>", "<|eot_id|>", "<|end_of_text|>", "</s>",
                       "<end_of_turn>", "<|endoftext|>"):
            if marker in template:
                stops.append(marker)
        return tuple(stops) or ("<|im_end|>", "<|endoftext|>", "</s>")

    @property
    def uses_builtin_template(self) -> bool:
        """Шаблон узято не з моделі, а зі запасного набору."""
        return not self.template

    def render(self, messages: list[dict], *, add_assistant: bool = True,
               template: str = "") -> str:
        """Застосувати шаблон до списку повідомлень.

        ``template`` — явний Jinja-рядок; якщо порожній, беремо шаблон
        моделі, а якщо його немає — запасний chatml.
        """
        chosen = template or self.template
        if not chosen or "{%" not in chosen:
            chosen = FALLBACK_TEMPLATES["chatml"]
        payload = [
            LlamaChatMessage(
                role=str(message.get("role") or "user").encode("utf-8"),
                content=str(message.get("content") or "").encode("utf-8"),
            )
            for message in messages
        ]
        array = (LlamaChatMessage * len(payload))(*payload) if payload else None
        # Рекомендований розмір буфера — 2× сумарна довжина повідомлень.
        wanted = 2 * sum(len(message.get("content") or "") for message in messages) + 1024
        size = max(1024, wanted)
        for _ in range(4):
            buffer = bytes(size)
            produced = int(self._lib.llama_chat_apply_template(
                chosen.encode("utf-8"), array, len(payload), add_assistant,
                buffer, size))
            if produced <= 0:
                LOG.debug("Шаблон не застосувався (%s) — беру chatml", produced)
                if chosen is not FALLBACK_TEMPLATES["chatml"]:
                    return self.render(messages, add_assistant=add_assistant,
                                       template=FALLBACK_TEMPLATES["chatml"])
                return self._manual_chatml(messages, add_assistant=add_assistant)
            if produced <= size:
                return buffer[:produced].decode("utf-8", "replace")
            size = produced + 64
        return self._manual_chatml(messages, add_assistant=add_assistant)

    @staticmethod
    def _manual_chatml(messages: list[dict], *, add_assistant: bool) -> str:
        """Останній рубіж: простий chatml без рушія."""
        parts = []
        for message in messages:
            role = str(message.get("role") or "user")
            parts.append(f"<|im_start|>{role}\n{message.get('content') or ''}<|im_end|>\n")
        if add_assistant:
            parts.append("<|im_start|>assistant\n")
        return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Text-based tool calling (безпечний адаптер)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_PROMPT_HEADER = (
    "Ти можеш викликати інструменти. Щоб викликати інструмент, відповідай ОДНИМ "
    "JSON-об'єктом без пояснень і без markdown:\n"
    '{"tool": "<назва інструмента>", "arguments": {<аргументи>}}\n'
    "Якщо інструмент не потрібен — відповідай звичайним текстом.\n\n"
    "Доступні інструменти:\n"
)

#: Регулярка на «схожий на виклик» JSON у відповіді моделі.
#:
#: Об'єкти з тексту навколо витягує :func:`_balanced_objects` (за глибиною
#: дужок); жадібна регулярка ``\{.*\}`` для цього не годиться — вона
#: захоплює хвіст після виклику.
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def tool_schemas_prompt(tools: list[dict]) -> str:
    """Текстовий опис інструментів для моделей без нативного tool calling."""
    if not tools:
        return ""
    lines = [TOOL_PROMPT_HEADER]
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            function = tool if isinstance(tool, dict) else {}
        name = str(function.get("name") or "")
        if not name:
            continue
        description = str(function.get("description") or "").strip()
        params = function.get("parameters") or {}
        properties = params.get("properties") if isinstance(params, dict) else {}
        required = set(params.get("required") or []) if isinstance(params, dict) else set()
        arg_bits = []
        for key, spec in (properties or {}).items():
            kind = ""
            if isinstance(spec, dict):
                kind = str(spec.get("type") or "")
            mark = "" if key in required else "?"
            arg_bits.append(f"{key}{mark}:{kind}" if kind else f"{key}{mark}")
        signature = ", ".join(arg_bits)
        lines.append(f"- {name}({signature}) — {description}")
    lines.append("")
    lines.append("Пам'ятай: тільки JSON-об'єкт у форматі "
                 '{"tool": "...", "arguments": {...}}.\n')
    return "\n".join(lines)


@dataclass
class ParsedToolCall:
    """Один розпізнаний виклик інструмента."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    error: str = ""

    def to_openai(self, call_id: str = "") -> dict[str, Any]:
        """Подати у форматі OpenAI ``tool_calls`` (його чекає решта IDE)."""
        return {
            "id": call_id or f"call_{abs(hash(self.name + self.raw)) % 10 ** 10}",
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


def _coerce_arguments(value: Any) -> dict[str, Any]:
    """Аргументи з моделі бувають рядком, об'єктом або порожніми."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _call_from_object(payload: dict[str, Any]) -> ParsedToolCall | None:
    """Витягти виклик із довільного JSON-об'єкта."""
    if not isinstance(payload, dict):
        return None
    # Формати, які реально зустрічаються в локальних моделях.
    name = payload.get("tool") or payload.get("name") or payload.get("tool_name")
    arguments = payload.get("arguments")
    if arguments is None:
        arguments = payload.get("parameters")
    if arguments is None:
        arguments = payload.get("args")
    function = payload.get("function")
    if isinstance(function, dict):
        name = name or function.get("name")
        arguments = arguments if arguments is not None else function.get("arguments")
    if not name or not isinstance(name, str):
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\-]{0,63}", name):
        return None
    return ParsedToolCall(name=name, arguments=_coerce_arguments(arguments),
                          raw=json.dumps(payload, ensure_ascii=False))


def _balanced_objects(text: str) -> list[str]:
    """Витягти всі збалансовані за дужками JSON-об'єкти з тексту.

    Чому не регулярка. ``re.compile(r"\\{.*\\}")`` жадібна: у рядку
    ``{"tool": "x"} Готово.`` вона бере від першої ``{`` до останньої ``}``
    і додає хвіст «Готово.», через що ``json.loads`` падає. А якщо модель
    пише ``{"tool": "a"} і ще {"tool": "b"}``, жадібний збіг злипається в
    одну невалідну купу. Тому рахуємо глибину дужок і беремо кожен
    завершений об'єкт окремо — з повагою до рядків у лапках.
    """
    found: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    found.append(text[start:index + 1])
                    start = -1
    return found


def _repair_json(text: str) -> str:
    """Полагодити типові вади JSON, які робить локальна модель.

    Головна й найчастіша: екранування апострофа (``\\'``). У JSON апостроф
    НЕ потребує екранування, а модель звикла до Python і пише
    ``"content": "input(\\'ім'я\\')"``. Такий текст непарситься, виклик
    відкидається, і файл не створюється — хоча модель усе зробила правильно
    (заміряно: «створи файл hello.py…» → порожня тека, у чаті сирий JSON).

    Прибираємо РІВНО ТЕ, ЩО ЗАВАЖАЄ, і не чіпаємо решту: лагодження має
    бути безпечним, інакше можна зіпсувати коректний вміст файлу.
    """
    if "\\'" not in text:
        return text
    return text.replace("\\'", "'")


def extract_tool_calls(text: str, *, known: set[str] | None = None) -> list[ParsedToolCall]:
    """Знайти виклики інструментів у текстовій відповіді моделі.

    ``known`` — перелік дозволених імен. Якщо переданий, усе інше
    відкидається: модель не має «вигадувати» інструменти.
    """
    if not text or not text.strip():
        return []
    candidates: list[str] = []
    for match in _JSON_BLOCK.finditer(text):
        candidates.append(match.group(1))
    # Збалансовані об'єкти — ОСНОВНЕ джерело: вони коректно відокремлюють
    # виклик від тексту навколо (``{"tool": "x"} Готово.``).
    candidates.extend(_balanced_objects(text))
    stripped = text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    # Кілька об'єктів поспіль (модель іноді віддає список).
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        candidates.extend(json.dumps(item, ensure_ascii=False) for item in parsed)
    calls: list[ParsedToolCall] = []
    for candidate in candidates:
        payload = None
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            # Друга спроба — після лагодження типового екранування.
            try:
                payload = json.loads(_repair_json(candidate))
            except json.JSONDecodeError:
                continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            call = _call_from_object(item)
            if call is None:
                continue
            if known is not None and call.name not in known:
                LOG.debug("Модель викликала невідомий інструмент %s", call.name)
                continue
            calls.append(call)
    # Прибираємо дублікати (та сама назва + ті самі аргументи).
    unique: list[ParsedToolCall] = []
    seen: set[tuple[str, str]] = set()
    for call in calls:
        key = (call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append(call)
    return unique


class ToolCallParser:
    """Потоковий розбір відповіді: текст відділяємо від JSON-виклику.

    Модель може спершу написати пояснення, а потім JSON. Користувачу
    треба показати пояснення, а виклик — виконати. Тому тримаємо
    «підозрілий» хвіст у буфері й не віддаємо його, доки не стане ясно,
    що це не початок JSON-об'єкта.
    """

    def __init__(self, *, known: set[str] | None = None,
                 dialect: Any = None) -> None:
        self.known = known
        self.text = ""
        #: Діалект інструментів моделі. Для Mistral потрібен окремий режим:
        #: виклик починається маркером ``[TOOL_CALLS]``, а не дужкою, тож
        #: звичайний пошук ``{`` показав би користувачу сирі аргументи.
        self.dialect = dialect
        self._buffer = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        """Повернути безпечний текст, який можна показати користувачу.

        Ховаємо ЛИШЕ те, що справді є викликом інструмента. Раніше
        приховувався будь-який JSON-об'єкт: відповідь моделі «ось план:
        ``[{"title": "a"}, {"title": "b"}]```» перетворювалась на
        ``[, ]`` — тобто вміст зникав, а дужки лишались. Саме через це
        планувальник отримував порожній масив від вбудованого рушія.
        """
        if not chunk:
            return ""
        self._buffer += chunk
        return self._drain()

    def _drain(self) -> str:
        """Віддати все, що вже точно не є викликом інструмента."""
        visible: list[str] = []
        while True:
            if self._inside:
                closed = self._close_if_complete()
                if closed is None:
                    break            # об'єкт ще не завершено — чекаємо
                self._inside = False
                if self._is_call(closed):
                    # Справжній виклик: ховаємо від користувача.
                    self.text += closed
                else:
                    # Звичайний JSON у відповіді — це ВМІСТ, показуємо.
                    visible.append(closed)
                continue
            # ── Маркер виклику в діалекті моделі ──────────────────────────
            # Три стани, і плутати їх не можна: «немає маркера» → звичайна
            # логіка з дужками; «оброблено» → буфер зсунуто, йдемо далі;
            # «тримати» → виклик ще не дописаний, чекаємо нових токенів.
            # Раніше «тримати» поверталось як «оброблено», і коли нічого не
            # з'їдалось (напр. прийшло лише ``[``), цикл крутився вічно.
            state, before = self._open_marker()
            if before:
                visible.append(before)
            if state == "hold":
                break
            if state == "handled":
                continue
            position = self._buffer.find("{")
            if position < 0:
                # Хвіст може бути початком JSON — тримаємо один символ.
                if self._buffer.endswith("`"):
                    break
                visible.append(self._buffer)
                self._buffer = ""
                break
            visible.append(self._buffer[:position])
            self._buffer = self._buffer[position:]
            self._inside = True
        return "".join(visible)

    def _open_marker(self) -> tuple[str, str]:
        """Обробити маркер виклику в діалекті моделі.

        Повертає ``(стан, текст_до_маркера)``:

        * ``("none", "")`` — маркера немає, далі працює логіка з дужками;
        * ``("hold", …)`` — виклик почався, але не дописаний: чекаємо токенів;
        * ``("handled", …)`` — виклик приховано, буфер зсунуто.

        Виклик Mistral має вигляд ``[TOOL_CALLS]write_file[ARGS]{…}``: дужка
        стоїть у СЕРЕДИНІ виклику, тому звичайна логіка показала б
        користувачу ім'я інструмента й сирі аргументи замість відповіді.
        """
        marker = getattr(self.dialect, "call_marker", "") if self.dialect else ""
        if marker != "[TOOL_CALLS]":
            return "none", ""
        index = self._buffer.find(marker)
        if index < 0:
            # Хвіст може бути ПОЧАТКОМ маркера (модель віддає його по
            # токенах: «[», «TOOL», «_CALLS]»). Притримуємо рівно стільки
            # символів, щоб не показати шматок службового тегу в чаті.
            keep = _partial_marker(self._buffer, marker)
            if not keep:
                return "none", ""
            visible = self._buffer[:-keep]
            self._buffer = self._buffer[-keep:]
            # Більше нічого не прийшло — далі чекаємо токенів.
            return "hold", visible
        visible = self._buffer[:index]
        rest = self._buffer[index + len(marker):]
        args_at = rest.find("[ARGS]")
        if args_at < 0:
            # Ім'я чи маркер аргументів ще не прийшли — тримаємо виклик.
            self._buffer = self._buffer[index:]
            return "hold", visible
        body_start = args_at + len("[ARGS]")
        try:
            _data, end = json.JSONDecoder().raw_decode(rest, body_start)
        except json.JSONDecodeError:
            # JSON ще не завершено (або він зламаний). Тримаємо далі — на
            # ``finish()`` все одно забере :func:`strip_native_calls`.
            self._buffer = self._buffer[index:]
            return "hold", visible
        self.text += self._buffer[index:index + len(marker) + end]
        self._buffer = rest[end:]
        return "handled", visible

    def _is_call(self, payload: str) -> bool:
        """Чи цей JSON-об'єкт є викликом інструмента."""
        try:
            calls = extract_tool_calls(payload, known=self.known)
        except Exception:  # noqa: BLE001 - розбір не має ламати стрім
            return False
        return bool(calls)

    def _close_if_complete(self) -> str | None:
        """Відрізати завершений об'єкт; ``None`` — він ще не завершений."""
        depth = 0
        in_string = False
        escaped = False
        for index, char in enumerate(self._buffer):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    closed = self._buffer[:index + 1]
                    self._buffer = self._buffer[index + 1:]
                    return closed
        if not self._buffer.strip():
            self._buffer = ""
            return ""
        return None

    def finish(self) -> str:
        """Завершити розбір: віддати залишок, якщо це не виклик."""
        tail = self._buffer
        self._buffer = ""
        if not tail:
            return ""
        # ── Обірваний виклик у діалекті моделі — НЕ показуємо ────────────
        # Замірено на скріншоті користувача: модель спинилась посеред
        # аргументів, і в чаті лишалося ``let[ARGS]`` з уривком JSON.
        # Маркер виклику в залишку означає, що це службовий текст, а не
        # відповідь: віддаємо те, що стоїть ДО маркера.
        marker = getattr(self.dialect, "call_marker", "") if self.dialect else ""
        if marker and marker in tail:
            head = tail[:tail.find(marker)]
            self.text += tail[len(head):]
            return head.strip()
        if extract_tool_calls(tail, known=self.known):
            return ""
        return tail

    @property
    def tool_payload(self) -> str:
        return self.text

    def calls(self) -> list[ParsedToolCall]:
        """Розпізнані виклики (після завершення стріму)."""
        return extract_tool_calls(self.text, known=self.known)

    def native_calls(self) -> list[dict[str, Any]]:
        """Виклики у ВЛАСНОМУ форматі моделі (``[TOOL_CALLS]``, ``<tool_call>``).

        Окремо від :meth:`calls`, бо той розуміє лише JSON-об'єкт. Виклик
        Mistral — не JSON, тож без цього методу рушій вважав його
        звичайним текстом, приховував із стріму й повертав ``tool_calls=[]``.
        """
        from .. import tool_dialect

        payload = self.text
        if not payload:
            return []
        return tool_dialect.extract_native_calls(payload, self.known)


def _partial_marker(text: str, marker: str) -> int:
    """Довжина хвоста ``text``, який є початком ``marker`` (0 — немає)."""
    limit = min(len(text), len(marker) - 1)
    for size in range(limit, 0, -1):
        if marker.startswith(text[-size:]):
            return size
    return 0


def has_native_tool_support(template: str) -> bool:
    """Чи шаблон моделі вміє нативні інструменти.

    Перевіряємо наявність змінної ``tools`` у Jinja-шаблоні — саме так
    llama.cpp дізнається, що модель підтримує tool calling (так роблять
    шаблони Qwen, Llama 3.1+, Hermes тощо).
    """
    if not template:
        return False
    lowered = template.lower()
    return "tools" in lowered and ("{%- if tools" in lowered or "{% if tools" in lowered
                                   or "tool_calls" in lowered)


__all__ = [
    "ChatFormatter",
    "FALLBACK_TEMPLATES",
    "ParsedToolCall",
    "TOOL_PROMPT_HEADER",
    "ToolCallParser",
    "extract_tool_calls",
    "guess_template",
    "has_native_tool_support",
    "tool_schemas_prompt",
]
