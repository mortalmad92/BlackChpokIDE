"""Діалект виклику інструментів, який очікує КОНКРЕТНА модель.

Проблема, яку закриває цей модуль, виміряна наживо (Ministral-3-14B, власний
рушій, GUI): користувач просить «зроби сайт», агент відповідає
«Модель повернула порожню відповідь», на диску нічого не з'являється.

Причина не в моделі. У шаблоні чату, який лежить у GGUF, записано рівно
один формат виклику, і в кожної родини він свій:

* Mistral / Ministral / Pixtral —::

      [AVAILABLE_TOOLS][{…схеми…}][/AVAILABLE_TOOLS]
      [TOOL_CALLS]write_file[ARGS]{"path": "a.py", "content": "…"}
      [TOOL_RESULTS]Записано a.py[/TOOL_RESULTS]

* Qwen / Hermes / DeepSeek —::

      <tools>{"type": "function", …}</tools>
      <tool_call>{"name": "write_file", "arguments": {…}}</tool_call>

* Інші — прохання відповісти JSON-об'єктом ``{"tool": …, "arguments": …}``.

Раніше IDE показувала моделі ЛИШЕ третій варіант — текстовий протокол
українською (:func:`model_profile.text_tool_protocol`), а ``[TOOL_CALLS]`` не
розумів жоден розбирач. Тому модель, яка слухняно відповідала СВОЇМ форматом,
виглядала як «порожня відповідь»: виклик не розпізнавався, текст викидався як
службовий, і агент зупинявся на нульовому кроці.

Модуль чистий: без tkinter, без мережі, без рушія. Лише текст.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

__all__ = [
    "Dialect",
    "DSML",
    "MISTRAL",
    "QWEN",
    "TEXT",
    "dialect_for_template",
    "dsml_block_end",
    "dsml_start",
    "extract_native_calls",
    "is_call_prefix",
    "strip_dsml",
    "strip_native_calls",
    "strip_pseudo_calls",
]

#: Родини, які просять схеми в ``[AVAILABLE_TOOLS]`` і звуть інструмент
#: маркером ``[TOOL_CALLS]``. Це шаблон Mistral 3 / Ministral.
MISTRAL = "mistral"
#: Родини з XML-обгортками ``<tools>`` і ``<tool_call>``. Це Qwen, Hermes,
#: DeepSeek і похідні.
QWEN = "qwen"
#: Власний XML-протокол DeepSeek: ``<|DSML| invoke name="…">``.
#:
#: Заміряно живим прогоном на хмарній ``deepseek-v4.1-flash`` (скріншот
#: користувача + ``chats.json``): модель повернула виклики не як
#: ``tool_calls`` і не як JSON у тексті, а СВОЇМ протоколом::
#:
#:     <|DSML| calls>
#:     <|DSML| invoke name="read_file">
#:     <|DSML| parameter name="path" string="true">calculator.py</|DSML| parameter>
#:     </|DSML| invoke>
#:     </|DSML| calls>
#:
#: Ніщо в IDE цього формату не розпізнавало: ``extract_tool_calls`` шукав
#: JSON, ``tool_dialect`` знав лише Mistral і Qwen. Тому виклик не
#: виконувався, а сам протокол ішов у чат як «відповідь» — користувач
#: бачив службовий XML замість роботи й відповіді людською мовою.
DSML = "dsml"
#: Немає власного формату — лишається текстовий протокол JSON.
TEXT = "text"

#: Маркер виклику Mistral: ``[TOOL_CALLS]ім'я[ARGS]{…}``.
#:
#: Ім'я навмисно вузьке (літери, цифри, ``_ . - :``): інакше «жадібний» збіг
#: з'їв би текст відповіді до наступного маркера.
_MISTRAL_CALL = re.compile(r"\[TOOL_CALLS\]\s*([A-Za-z_][\w.:\-]{0,63})\s*\[ARGS\]")

#: Скільки викликів в одній відповіді готові розібрати. Модель іноді видає
#: кілька ``[TOOL_CALLS]`` поспіль; більше двадцяти — це вже сміття.
_MAX_CALLS = 20

#: Роздільник у тегах DeepSeek. Живий прогін дав САМЕ ``U+FF5C``
#: (``｜DSML｜``), а документація показує ``U+007C``. Приймаємо обидва й
#: дозволяємо пробіли навколо: інакше один варіант розпізнавався б, а
#: другий знову протікав у чат.
_DSML_SEP = r"[|｜]\s*DSML\s*[|｜]"

#: Відкриття ``invoke`` з іменем інструмента.
_DSML_INVOKE_OPEN = re.compile(
    r"<\s*" + _DSML_SEP + r"\s*invoke\s+name\s*=\s*[\"']([^\"']*)[\"']\s*>",
    re.IGNORECASE)

#: Закриття ``invoke`` (або ``calls``) — межа аргументів одного виклику.
_DSML_INVOKE_CLOSE = re.compile(
    r"<\s*/\s*" + _DSML_SEP + r"\s*(?:invoke|calls)\s*>",
    re.IGNORECASE)

#: Один параметр: ``name="path" string="true">значення``.
#:
#: Значення шукаємо НЕ до наступного ``>``, а до закриття тега ``parameter``
#: (або до початку наступного параметра): у аргументах ``write_file``
#: лежить цілий файл із тегами HTML і фігурними дужками, і жадібний збіг
#: обірвав би його на першому ж ``>``.
_DSML_PARAM = re.compile(
    r"<\s*" + _DSML_SEP + r"\s*parameter\s+name\s*=\s*[\"']([^\"']*)[\"']([^>]*)>"
    r"(.*?)"
    r"(?=<\s*/\s*" + _DSML_SEP + r"\s*parameter\s*>"
    r"|<\s*" + _DSML_SEP + r"\s*parameter\b"
    r"|<\s*/\s*" + _DSML_SEP + r"\s*(?:invoke|calls)\s*>"
    r"|<\s*" + _DSML_SEP + r"\s*invoke\b"
    r"|$)",
    re.IGNORECASE | re.DOTALL)

#: Будь-який тег DSML — для очищення тексту й визначення протоколу.
_DSML_ANY_TAG = re.compile(r"<\s*/?\s*" + _DSML_SEP + r"[^>]*>", re.IGNORECASE)

#: Початок DSML у тексті (для стріму: такий хвіст НЕ показуємо).
_DSML_START = re.compile(r"<\s*/?\s*" + _DSML_SEP, re.IGNORECASE)

#: «Псевдо-виклик» — ім'я інструмента в тезі з одним аргументом усередині::
#:
#:     <run_command>echo ok</run_command>
#:     <read_file path="calc.py"/>
#:
#: Заміряно живим прогоном (зауваження власника проєкту): модель двічі
#: відповіла ``<run_command>echo ok</run_command>`` замість того, щоб
#: викликати інструмент. Це НЕ звичайний XML відповіді (напр. ``<div>``):
#: ім'я тега збігається з назвою реального інструмента, тому виклик
#: розпізнаємо й виконуємо, а тег із чату прибираємо.
#:
#: Значення тега стає аргументом ``command``/``path``/``query`` — тим
#: єдиним, який цей інструмент очікує (див. :data:`_SOLO_ARGUMENT`).
_PSEUDO_TAG_OPEN = re.compile(
    r"<\s*([A-Za-z_][\w.\-]{1,63})\s*([^<>]*?)(/?)>", re.IGNORECASE)

#: Який аргумент отримує інструмент, викликаний «голим» тегом.
#:
#: Беремо рівно те поле, яке інструмент реально приймає: інакше виклик
#: пройшов би перевірку імені й упав на перевірці аргументів.
_SOLO_ARGUMENT: dict[str, str] = {
    "run_command": "command",
    "run_shell": "command",
    "read_file": "path",
    "write_file": "path",
    "edit_file": "path",
    "append_file": "path",
    "list_dir": "path",
    "create_dir": "path",
    "delete_file": "path",
    "python_check": "path",
    "find_files": "pattern",
    "search_text": "query",
    "search_web": "query",
    "web_api": "url",
    "fetch_url": "url",
}


@dataclass(frozen=True)
class Dialect:
    """Що саме показати моделі й як читати її виклик."""

    kind: str = TEXT
    #: Літерал, яким шаблон відкриває опис інструментів (для журналу).
    opens: str = ""
    #: Літерал, яким шаблон відкриває виклик.
    call_marker: str = ""
    #: Причина рішення — для журналу й чесного пояснення.
    note: str = ""

    @property
    def native(self) -> bool:
        return self.kind in (MISTRAL, QWEN)

    # ── опис інструментів ────────────────────────────────────────────────
    def tools_block(self, tools: Sequence[dict[str, Any]]) -> str:
        """Описати інструменти ТИМ форматом, який розуміє ця модель.

        Для Mistral це справжній машинний формат: рушій не передає ``tools``
        у шаблон (у ``llama_chat_apply_template`` немає такого поля), тож
        блок додаємо в системний промпт власними руками.
        """
        items = [item for item in tools or () if isinstance(item, dict)]
        if not items:
            return ""
        if self.kind == MISTRAL:
            return ("[AVAILABLE_TOOLS]"
                    + json.dumps(list(items), ensure_ascii=False)
                    + "[/AVAILABLE_TOOLS]")
        if self.kind == QWEN:
            body = "\n".join(json.dumps(item, ensure_ascii=False) for item in items)
            return (
                "You may call one or more functions to assist with the user "
                "query.\nYou are provided with function signatures within "
                f"<tools></tools> XML tags:\n<tools>\n{body}\n</tools>\n\n"
                "For each function call, return a json object with function "
                "name and arguments within <tool_call></tool_call> XML tags:\n"
                '<tool_call>\n{"name": <function-name>, "arguments": '
                "<args-json-object>}\n</tool_call>"
            )
        return ""

    # ── виклик в історії розмови ─────────────────────────────────────────
    def call_text(self, name: str, arguments: str) -> str:
        """Виклик як ТЕКСТ — так його побачить модель у своїй же історії.

        Навіщо: ``LlamaChatMessage`` містить лише ``role`` і ``content``, тому
        ``tool_calls`` в історії просто зникають. Заміряно: у промпт другого
        кроку потрапляло ``[INST] … [/INST] </s> Записано a.py</s>`` — без
        виклику й без позначки, що це результат інструмента. Модель втрачала
        власну роботу й починала заново.
        """
        body = (arguments or "").strip() or "{}"
        if self.kind == MISTRAL:
            return f"[TOOL_CALLS]{name}[ARGS]{body}"
        if self.kind == QWEN:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {}
            payload = {"name": name, "arguments": parsed}
            return "<tool_call>\n" + json.dumps(payload, ensure_ascii=False) + "\n</tool_call>"
        return ""

    def result_text(self, content: str) -> str:
        """Результат інструмента у форматі моделі (порожньо — хай шаблон сам)."""
        body = str(content or "")
        if self.kind == MISTRAL:
            # Шаблон Ministral уже обгортає роль ``tool`` у ``[TOOL_RESULTS]``,
            # тому тут НЕ дублюємо: подвійна обгортка плутає модель.
            return body
        if self.kind == QWEN:
            # Шаблон Qwen обгортає в ``<tool_response>`` сам.
            return body
        return body

    # ── власний рендер промпту (коли шаблон рушія не справляється) ───────
    def render_history(self, messages: Sequence[dict[str, Any]]) -> str:
        """Зібрати промпт САМІ, без Jinja-шаблону рушія.

        Навіщо це потрібно, заміряно наживо на Ministral-3-14B. Вбудований
        ``llama_chat_apply_template`` (llama.cpp) для цього шаблону:

        * НЕ обгортає роль ``tool`` у ``[TOOL_RESULTS]``, хоч у шаблоні ця
          гілка є. Замірено:

              [INST] U [/INST] A</s> T</s>

          замість ``… A</s>[TOOL_RESULTS]T[/TOOL_RESULTS]``. Модель бачила
          результат інструмента як невідомий шматок тексту й не розуміла,
          що дію вже виконано;
        * не відкриває хід асистента в кінці (``add_assistant`` у шаблоні
          Mistral відсутній), тож промпт обривався на ``</s>``. Модель
          отримувала «продовж після eos» замість чистого початку відповіді
          — звідси порожні відповіді на другому кроці.

        Причина спільна для ВСІХ моделей: у C-структурі повідомлення є лише
        ``role`` і ``content`` — ні ``tools``, ні ``tool_calls`` туди не
        передаються. Тому шаблон Qwen, де є ``{% if message.tool_calls %}``,
        теж друкує голий текст без виклику й без результатів.

        Тому для відомих діалектів збираємо рівно те, що написано в шаблоні
        GGUF, але коректно.
        """
        if self.kind == MISTRAL:
            return self._render_mistral(messages)
        if self.kind == QWEN:
            return self._render_qwen(messages)
        return ""

    def _render_mistral(self, messages: Sequence[dict[str, Any]]) -> str:
        parts: list[str] = []
        rest = list(messages)
        if rest and str(rest[0].get("role") or "") == "system":
            system = str(rest[0].get("content") or "")
            parts.append(f"[SYSTEM_PROMPT]{system}[/SYSTEM_PROMPT]")
            rest = rest[1:]
        for message in rest:
            role = str(message.get("role") or "")
            body = str(message.get("content") or "")
            if role == "user":
                parts.append(f"[INST] {body} [/INST]")
            elif role == "assistant":
                text = body
                for call in message.get("tool_calls") or ():
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") or {}
                    text += self.call_text(str(function.get("name") or ""),
                                           str(function.get("arguments") or ""))
                parts.append(text + "</s>")
            elif role == "tool":
                parts.append(f"[TOOL_RESULTS]{body}[/TOOL_RESULTS]")
            elif role == "system":
                # Системний промпт уже надруковано вище; другий ламає шаблон.
                parts.append(f"[SYSTEM_PROMPT]{body}[/SYSTEM_PROMPT]")
        return "".join(parts)

    def _render_qwen(self, messages: Sequence[dict[str, Any]]) -> str:
        """ChatML за шаблоном Qwen, включно з викликами й результатами.

        Результати інструментів шаблон Qwen складає в ОДНЕ повідомлення
        користувача зі ``<tool_response>`` блоками — відтворюємо саме це,
        інакше модель не впізнає, що дію вже виконано.
        """
        parts: list[str] = []
        pending_results: list[str] = []

        def flush_results() -> None:
            if not pending_results:
                return
            joined = "\n".join(
                f"<tool_response>\n{body}\n</tool_response>"
                for body in pending_results)
            parts.append(f"<|im_start|>user\n{joined}<|im_end|>\n")
            pending_results.clear()

        for message in messages:
            role = str(message.get("role") or "")
            body = str(message.get("content") or "")
            if role == "tool":
                # Кілька результатів поспіль збираємо в одне повідомлення.
                pending_results.append(body)
                continue
            flush_results()
            if role == "system":
                parts.append(f"<|im_start|>system\n{body}<|im_end|>\n")
            elif role == "user":
                parts.append(f"<|im_start|>user\n{body}<|im_end|>\n")
            elif role == "assistant":
                text = f"<|im_start|>assistant\n{body}" if body else \
                    "<|im_start|>assistant"
                for call in message.get("tool_calls") or ():
                    if not isinstance(call, dict):
                        continue
                    text += "\n" + self.call_text(
                        str((call.get("function") or {}).get("name") or ""),
                        str((call.get("function") or {}).get("arguments") or ""))
                parts.append(text + "<|im_end|>\n")
        flush_results()
        # Хід асистента відкриваємо явно: без нього модель продовжує
        # попереднє повідомлення замість того, щоб почати відповідь.
        parts.append("<|im_start|>assistant\n")
        return "".join(parts)


def dialect_for_template(template: str) -> Dialect:
    """Визначити діалект із Jinja-шаблону чату моделі.

    Читаємо саме шаблон, а не назву файлу: назва бреше (той самий
    «qwen2.5-coder» буває з різними шаблонами), а шаблон — це буквально те,
    що рушій застосує до повідомлень.
    """
    body = template or ""
    if not body:
        return Dialect(kind=TEXT, note="у GGUF немає шаблону чату")
    has_mistral = "[TOOL_CALLS]" in body and "[AVAILABLE_TOOLS]" in body
    has_qwen = "<tools>" in body and "<tool_call>" in body
    if has_mistral and not has_qwen:
        return Dialect(kind=MISTRAL, opens="[AVAILABLE_TOOLS]",
                       call_marker="[TOOL_CALLS]",
                       note="шаблон Mistral: [AVAILABLE_TOOLS] + [TOOL_CALLS]")
    if has_qwen:
        return Dialect(kind=QWEN, opens="<tools>", call_marker="<tool_call>",
                       note="шаблон Qwen: <tools> + <tool_call>")
    if has_mistral:
        return Dialect(kind=MISTRAL, opens="[AVAILABLE_TOOLS]",
                       call_marker="[TOOL_CALLS]",
                       note="шаблон Mistral: [AVAILABLE_TOOLS] + [TOOL_CALLS]")
    return Dialect(kind=TEXT, note="власного формату інструментів у шаблоні немає")


def _arguments(value: Any) -> dict[str, Any]:
    """Аргументи моделі бувають об'єктом або рядком JSON."""
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


def extract_native_calls(
    text: str,
    known: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Витягти виклики у НАТИВНОМУ форматі моделі з тексту відповіді.

    Повертає список у форматі OpenAI ``tool_calls`` — його чекає решта IDE.
    ``known`` обмежує імена, щоб модель не «вигадувала» інструменти; якщо
    перелік не переданий, приймаємо будь-яке синтаксично правильне ім'я.

    Формати:

    * ``[TOOL_CALLS]write_file[ARGS]{"path": …}`` — Mistral/Ministral;
    * ``<tool_call>{"name": …, "arguments": {…}}</tool_call>`` — Qwen/Hermes.

    Чому ``raw_decode``, а не регулярка на дужки: у аргументах ``write_file``
    лежить ВЕСЬ файл із фігурними дужками CSS і лапками. ``\\{.*?\\}``
    обірвав би його на першій же дужці й перетворив би вміст файлу на
    обрізане сміття.
    """
    body = text if isinstance(text, str) else ""
    if not body.strip():
        return []
    allowed = {str(name) for name in (known or ()) if str(name).strip()}
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def accept(name: str, arguments: Any) -> None:
        clean = str(name or "").strip()
        if not clean or len(found) >= _MAX_CALLS:
            return
        if allowed and clean not in allowed:
            return
        data = _arguments(arguments)
        key = (clean, json.dumps(data, sort_keys=True, ensure_ascii=False))
        if key in seen:
            return
        seen.add(key)
        found.append({
            "id": f"call_{len(found)}",
            "type": "function",
            "function": {
                "name": clean,
                "arguments": json.dumps(data, ensure_ascii=False),
            },
        })

    # ── 1. Формат Mistral: маркер, ім'я, маркер, JSON ────────────────────
    position = 0
    while len(found) < _MAX_CALLS:
        match = _MISTRAL_CALL.search(body, position)
        if match is None:
            break
        try:
            data, end = decoder.raw_decode(body, match.end())
        except json.JSONDecodeError:
            # Обірваний JSON (модель спинилась посеред файлу). Далі шукати
            # нема сенсу: наступний маркер лежить УСЕРЕДИНІ цього JSON.
            position = match.end()
            continue
        accept(match.group(1), data)
        position = end

    # ── 2. Формат Qwen: <tool_call>{json}</tool_call> ────────────────────
    for inner in re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", body, re.DOTALL):
        for candidate in (inner, inner.strip("`"),
                          re.sub(r"^```(?:json)?|```$", "", inner).strip()):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("tool") or item.get("tool_name")
                arguments = item.get("arguments")
                if arguments is None:
                    arguments = item.get("parameters")
                if arguments is None:
                    function = item.get("function")
                    if isinstance(function, dict):
                        name = name or function.get("name")
                        arguments = function.get("arguments")
                accept(str(name or ""), arguments)
            break

    # ── 3. Власний протокол DeepSeek: <|DSML| invoke …> ──────────────────
    # Заміряно на хмарній deepseek-v4.1-flash: модель віддала три виклики
    # цим XML, і IDE не розпізнала ЖОДНОГО — виклики не виконались, а
    # протокол пішов у чат замість відповіді.
    for call_match in _DSML_INVOKE_OPEN.finditer(body):
        if len(found) >= _MAX_CALLS:
            break
        close = _DSML_INVOKE_CLOSE.search(body, call_match.end())
        inner = body[call_match.end():close.start() if close else len(body)]
        accept(call_match.group(1), _dsml_arguments(inner))

    # ── 4. «Псевдо-виклик» тегом: <run_command>echo ok</run_command> ─────
    # Заміряно живим прогоном (зауваження власника проєкту): модель двічі
    # відповіла текстом протоколу замість виклику. Виконуємо його як
    # справжній виклик — це те, що людина й просила.
    for match in _PSEUDO_TAG_OPEN.finditer(body):
        if len(found) >= _MAX_CALLS:
            break
        name = match.group(1)
        if not name.lower() in {key.lower() for key in _SOLO_ARGUMENT}:
            continue
        if allowed and name not in allowed:
            continue
        canonical = _canonical_tool(name, allowed)
        if not canonical:
            continue
        # Відкритий тег без пари <name …>значення</name> не чіпаємо:
        # нічого не виконуємо, доки не видно самого аргументу.
        if match.group(3):
            arguments: Any = _pseudo_arguments(canonical, "", match.group(2))
        else:
            closing = re.compile(r"</\s*" + re.escape(name) + r"\s*>",
                                 re.IGNORECASE)
            rest = body[match.end():]
            end = closing.search(rest)
            if end is None:
                continue
            arguments = _pseudo_arguments(canonical, rest[:end.start()],
                                          match.group(2))
        accept(canonical, arguments)

    return found


def _canonical_tool(name: str, allowed: set[str]) -> str:
    """Справжня назва інструмента за тегом (регістр може відрізнятись)."""
    for known in allowed or ():
        if known.lower() == name.lower():
            return known
    for known in _SOLO_ARGUMENT:
        if known.lower() == name.lower():
            return known
    return ""


def _pseudo_arguments(name: str, inner: str, attrs: str) -> dict[str, Any]:
    """Аргументи «голого» тега: атрибути + текст усередині.

    ``<read_file path="a.py"/>`` — беремо атрибут.
    ``<run_command>echo ok</run_command>`` — беремо текст як єдине поле,
    яке цей інструмент очікує (``command`` для ``run_command``).
    """
    arguments: dict[str, Any] = {}
    for key, value in re.findall(
            r"([A-Za-z_][\w.\-]*)\s*=\s*[\"']([^\"']*)[\"']", attrs or ""):
        arguments[str(key)] = str(value)
    body = str(inner or "").strip()
    if body:
        solo = _SOLO_ARGUMENT.get(name, "")
        # Текст у тегу — головний аргумент. Не перетираємо явний атрибут.
        if solo and solo not in arguments:
            arguments[solo] = body
        elif not arguments:
            arguments[solo or "text"] = body
    return arguments


def _dsml_arguments(inner: str) -> dict[str, Any]:
    """Аргументи з тіла ``invoke``: ``parameter name="…">значення``.

    Значення лишається РЯДКОМ або приводиться до типу, який модель
    позначила сама. ``string="true"`` — це підказка, що рядок не треба
    вгадувати: інакше ``"10"`` стало б числом, а ``path`` — ні.

    ``json="true"`` (трапляється в аргументах-об'єктах) розбираємо як
    JSON: модель так передає вкладені структури, і без розбору вони
    прийшли б рядком.
    """
    arguments: dict[str, Any] = {}
    for match in _DSML_PARAM.finditer(inner or ""):
        name = str(match.group(1) or "").strip()
        if not name:
            continue
        attrs = str(match.group(2) or "").lower()
        raw = str(match.group(3) or "")
        # Значення загортають у CDATA-подібні обгортки або екранують:
        # XML не дозволяє «<» у тексті, тож моделі іноді пишуть «&lt;».
        if "]]>" in raw:
            raw = raw.replace("<![CDATA[", "").replace("]]>", "")
        value: Any = raw
        if "string=\"true\"" not in attrs and "json=\"true\"" not in attrs:
            # Без підказки лишаємо рядок: тип вгадувати небезпечно —
            # ``"001"`` перетворилось би на ``1`` й зіпсувало шлях.
            value = raw
        elif "json=\"true\"" in attrs:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
        arguments[name] = value
    return arguments


def is_call_prefix(text: str) -> bool:
    """Чи текст — незавершений початок власного протоколу моделі.

    Потрібно стріму: поки модель друкує ``<|DSML|``, показувати це
    користувачу не можна (інакше в чаті миготів би шматок службового тегу
    перед кожним викликом). Перевірка навмисно терпима до ЧАСТКОВИХ
    маркерів: ``<``, ``<|``, ``<|D``, ``<|DSML| inv``.
    """
    body = (text or "").strip()
    if not body.startswith("<"):
        return False
    if _DSML_START.search(body):
        return True
    # Частковий маркер: порівнюємо початок із префіксами повного тега.
    head = body.upper().replace("｜", "|")
    return any(marker.startswith(head) for marker in _DSML_PREFIXES)


#: Повні початки тегів DSML — від найкоротшого до найдовшого. Потрібні,
#: щоб упізнати обірваний маркер (``<|DS``) ще до його завершення.
_DSML_PREFIXES: tuple[str, ...] = (
    "<", "<|", "<|D", "<|DS", "<|DSM", "<|DSML", "<|DSML|",
    "<|DSML| ", "<|DSML| C", "<|DSML| CALLS", "<|DSML| I",
    "<|DSML| INVOKE", "<|DSML| P", "<|DSML| PARAMETER", "<|DSML| /",
    "</", "</|", "</|D", "</|DS", "</|DSM", "</|DSML", "</|DSML|",
    "</|DSML| ", "</|DSML| I", "</|DSML| INVOKE", "</|DSML| P",
    "</|DSML| PARAMETER", "</|DSML| C", "</|DSML| CALLS",
)


def dsml_start(text: str) -> int | None:
    """Індекс ПЕРШОГО тега DSML у тексті (``None`` — протоколу немає)."""
    match = _DSML_START.search(text or "")
    return match.start() if match is not None else None


def dsml_stray_close(text: str) -> int | None:
    """Довжина самотнього закриття DSML на початку (``<``/``</|DSML| calls>``).

    Потрібно стріму: після того як виклик вирізано, у буфері лишається
    тільки закривний тег. Без цієї перевірки він ішов у чат окремими
    символами (``<``, ``</``, ``</|`` …).

    Повертає ``-1``, якщо блок виглядає як ПОЧАТОК тега, але ще не
    завершений (тоді стрім притримує весь буфер).
    """
    body = text or ""
    if not body:
        return None
    if not body.startswith("<"):
        return None
    match = re.match(r"<\s*/\s*" + _DSML_SEP + r"\s*(?:calls|invoke)\s*>",
                     body, re.IGNORECASE)
    if match is not None:
        return match.end()
    # Незавершене закриття на початку — тримаємо, доки не стане ясно.
    head = body.replace("\uff5c", "|").upper()
    if ">" not in head and re.match(r"<\s*/?\s*\|?D?S?M?L?", head):
        if any(marker.startswith(head.replace(" ", ""))
               for marker in ("</|DSML| CALLS>", "</|DSML| INVOKE>",
                              "</|DSML| PARAMETER>")):
            return -1
    return None


def dsml_block_end(text: str) -> int | None:
    """Довжина ЗАКРИТОГО блоку DSML на початку ``text`` (``None`` — ще ні).

    Потрібно стріму: поки модель друкує виклик, показувати його не можна,
    а віддавати текст треба якомога раніше. Закритим вважаємо блок із
    ``</|DSML| calls>``, а якщо зовнішньої обгортки немає — із
    ``</|DSML| invoke>``.
    """
    body = text or ""
    if not body:
        return None
    tail = re.compile(
        r"<\s*/\s*" + _DSML_SEP + r"\s*(?:calls|invoke)\s*>", re.IGNORECASE)
    match = tail.search(body)
    return match.end() if match is not None else None


def strip_pseudo_calls(text: str) -> str:
    """Прибрати з тексту «псевдо-виклики» тегом (``<run_command>…``).

    Прибираємо ЛИШЕ теги, чиє ім'я збігається з реальним інструментом.
    Звичайний XML відповіді (``<div>``, ``<svg>``) мусить лишитись: його
    користувач і просив показати.

    Причина, з якої це потрібно: модель відповідала
    ``<run_command>echo ok</run_command>`` замість виклику. Якщо виклик
    вдалося розпізнати й виконати, цей тег у чаті вже нічого не додає, а
    якщо НЕ вдалося — він тим більше не відповідь людині.
    """
    body = text if isinstance(text, str) else ""
    if not body or "<" not in body:
        return body
    for name in _SOLO_ARGUMENT:
        body = re.sub(
            r"<\s*" + re.escape(name) + r"\b[^<>]*?/>", "", body, flags=re.IGNORECASE)
        body = re.sub(
            r"<\s*" + re.escape(name) + r"\b[^<>]*?>[^<]*<\s*/\s*"
            + re.escape(name) + r"\s*>", "", body, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def strip_native_calls(text: str) -> str:
    """Прибрати з тексту виклики й обгортки, які вже стали ``tool_calls``.

    Потрібно, щоб користувач не читав у чаті
    ``[TOOL_CALLS]write_file[ARGS]{"path": …}`` замість відповіді. Аргументи
    ріжемо тим самим ``raw_decode``, що й розбір.

    Обірваний виклик теж прибираємо ЦІЛКОМ. Заміряно на скріншоті
    користувача: модель спинилась посеред аргументів (``finish_reason =
    length``), і в чаті лишалося ``let[ARGS]`` та уривок JSON із назвою
    файлу — службове сміття, яке нічого не означає для людини. Хвіст від
    маркера до кінця рядка — це завжди частина виклику, а не відповідь.
    """
    body = text if isinstance(text, str) else ""
    if not body:
        return ""
    decoder = json.JSONDecoder()
    out: list[str] = []
    position = 0
    while True:
        match = _MISTRAL_CALL.search(body, position)
        if match is None:
            out.append(body[position:])
            break
        out.append(body[position:match.start()])
        try:
            _data, end = decoder.raw_decode(body, match.end())
        except json.JSONDecodeError:
            # Обірваний JSON: далі в тексті може бути лише його хвіст.
            # Дописуємо залишок ПІСЛЯ останнього переводу рядка — так
            # звичайна відповідь після незавершеного виклику не губиться.
            tail = body[match.end():]
            cut = tail.rfind("\n\n")
            out.append(tail[cut + 2:] if cut >= 0 else "")
            position = len(body)
            break
        position = end
    body = "".join(out)
    body = re.sub(r"<tool_call>.*?</tool_call>", "", body, flags=re.DOTALL)
    body = re.sub(r"<tools>.*?</tools>", "", body, flags=re.DOTALL)
    body = re.sub(r"\[AVAILABLE_TOOLS\].*?\[/AVAILABLE_TOOLS\]", "", body,
                  flags=re.DOTALL)
    body = re.sub(r"\[TOOL_RESULTS\].*?\[/TOOL_RESULTS\]", "", body,
                  flags=re.DOTALL)
    # Незакритий хвіст службових маркерів (обрив посеред виклику).
    body = re.sub(r"\[/?TOOL_CALLS\].*$", "", body, flags=re.DOTALL)
    body = re.sub(r"\[/?AVAILABLE_TOOLS\].*$", "", body, flags=re.DOTALL)
    body = re.sub(r"\[ARGS\].*$", "", body, flags=re.DOTALL)
    body = strip_dsml(body)
    body = strip_pseudo_calls(body)
    return body.strip()


def strip_dsml(text: str) -> str:
    """Прибрати з тексту ВЕСЬ протокол DeepSeek (``<|DSML| …>``).

    Потрібно з двох причин:

    * користувач не має читати службовий XML замість відповіді — саме це
      сталося на скріншоті (три виклики в чаті, жодного файлу на диску);
    * обірваний виклик (модель спинилась посеред ``invoke``) теж треба
      прибрати: хвіст ``parameter name=…`` нічого не означає для людини.

    Прибираємо ВСЕ від першого тегу DSML, якщо в тексті немає закритої
    обгортки ``calls``: незакритий протокол — це завжди обірваний виклик,
    і звичайна відповідь після нього не збережеться моделлю.
    """
    body = text if isinstance(text, str) else ""
    if not body:
        return ""
    # Закритий блок: ріжемо рівно його, решту тексту лишаємо.
    body = re.sub(
        r"<\s*" + _DSML_SEP + r"\s*calls\s*>.*?<\s*/\s*" + _DSML_SEP + r"\s*calls\s*>",
        "", body, flags=re.IGNORECASE | re.DOTALL)
    # Окремі закриті invoke (модель іноді не ставить зовнішню обгортку).
    body = re.sub(
        r"<\s*" + _DSML_SEP + r"\s*invoke\b.*?<\s*/\s*" + _DSML_SEP + r"\s*invoke\s*>",
        "", body, flags=re.IGNORECASE | re.DOTALL)
    # Незакритий хвіст: від першого ж тегу DSML до кінця.
    match = _DSML_START.search(body)
    if match is not None:
        body = body[:match.start()]
    return body.strip()
