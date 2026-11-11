"""Клієнт до LLM без зовнішніх залежностей (лише stdlib).

Три протоколи в одному клієнті — вибір за адресою (див.
:mod:`provider_adapters`):

* **OpenAI-сумісний** (``/chat/completions`` + ``Authorization: Bearer``):
  LM Studio, Ollama, llama.cpp server, vLLM, DeepSeek, OpenAI, OpenRouter,
  Groq, Mistral, Gemini-OpenAI-шлях, будь-який власний сервер;
* **Anthropic** (``/v1/messages`` + ``x-api-key``): справжній протокол із
  блоками ``tool_use``/``tool_result`` і власним SSE;
* **Gemini** (нативний ``:generateContent`` + ключ у запиті).

Уміє стрімінг, нативний tool calling і текстове відновлення викликів для
моделей, які не вміють нативного формату.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

from . import provider_adapters, secrets

LOG = logging.getLogger("blackchpok.llm")

# Типові локальні сервери: (назва, базовий URL)
KNOWN_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("LM Studio", "http://127.0.0.1:1234/v1"),
    ("LM Studio (1235)", "http://127.0.0.1:1235/v1"),
    ("Ollama", "http://127.0.0.1:11434/v1"),
    ("llama.cpp", "http://127.0.0.1:8080/v1"),
    ("vLLM", "http://127.0.0.1:8000/v1"),
)


def _is_local_url(url: str) -> bool:
    """Чи адреса веде на локальний сервер (для зрозумілої підказки).

    Тонка обгортка над :func:`provider_adapters.is_local_url` — ЄДИНОЮ
    реалізацією в проєкті. Раніше тут був власний список маркерів, а
    ``auto_setup`` мав інший (із 7 хостів), тож та сама адреса в різних
    частинах інтерфейсу класифікувалась по-різному.
    """
    from .provider_adapters import is_local_url as _shared

    return _shared(url)


def is_reasoning_model(model: str) -> bool:
    """Чи це «думаюча» модель (DeepSeek reasoner, o1/o3, QwQ…).

    Такі моделі не приймають temperature і окремо повертають reasoning_content.
    """
    low = (model or "").lower()
    if not low:
        return False
    markers = ("reasoner", "reasoning", "-r1", "o1-", "o3-", "o4-",
               "thinking", "qwq", "deepseek-r1", "glm-5", "flash-1017",
               "magistral", "marco-o")
    if any(marker in low for marker in markers):
        return True
    # Deploy віддає «думаючі» моделі без слова reasoner у назві —
    # напр. deepseek-ai/deepseek-v4.1-flash-1017 (reasoning_effort підтримується).
    if "deepseek-v4" in low or "deepseek-ai/deepseek" in low:
        return True
    return False


def _tool_names(tools: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for tool in tools or ():
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and function.get("name"):
            names.add(str(function["name"]))
    return names


def _recover_names(tools: list[dict[str, Any]] | None,
                   known: Iterable[str] | None) -> set[str]:
    """Імена для РОЗПІЗНАВАННЯ виклику в тексті.

    Навіщо окремо від ``tools``. У лінивому режимі агент передає моделі
    лише 17 «ядерних» схем із 50, а решту тримає доступними через
    ``run_tool``. Модель при цьому цілком може написати виклик
    інструмента, якого серед переданих схем немає:

        {"name": "search_web", "arguments": {"query": "ціна соняш"}}

    Раніше ``extract_tool_calls`` будував список імен ЛИШЕ з переданих
    схем, не знаходив ``search_web`` і повертав ``[]``. Далі агент бачив
    «порожню відповідь» і писав користувачу «Модель повернула порожню
    відповідь» — хоч модель насправді дала цілком осмислений виклик.

    Тепер розпізнавання спирається на ПОВНИЙ перелік відомих імен
    (``known``), а ``tools`` лишається тим, що реально пішло моделі.
    """
    names = _tool_names(tools)
    for name in known or ():
        text = str(name or "").strip()
        if text:
            names.add(text)
    return names


def _looks_like_tool_json(text: str, names: set[str]) -> bool:
    """Чи схожий накопичений текст на виклик інструмента, а не на відповідь.

    Локальні моделі віддають виклик у полі ``content`` у кількох обгортках:
    ``{"name": "list_dir", …}``, ``<tool_call>…</tool_call>`` і — як
    qwen2.5-coder із llama.cpp — ``<tools>…</tools>``. Користувач бачить
    сирий JSON замість відповіді, тому такі фрагменти притримуємо.

    Найважливіший випадок — ПОЧАТОК: поки прийшло лише ``{"na``, ім'я
    інструмента ще не видно. Раніше такий префікс одразу йшов у чат, і
    користувач бачив «{"na» перед справжньою відповіддю. Тому будь-який
    текст, що ПОЧИНАЄТЬСЯ з ``{`` чи службового тегу, притримуємо: якщо
    це справді звичайна відповідь, вона піде в чат наприкінці стріму
    (там виклик інструмента вже розпізнано).
    """
    body = (text or "").lstrip()
    if not body:
        return False
    if body.startswith("<"):
        # Будь-який службовий тег на початку: <tool_call>, <tools>, <function>.
        head_tag = body[:20].lower()
        if any(tag in head_tag for tag in ("<tool", "<function", "<function_call")):
            return True
        # Інші теги (напр. <div> у відповіді про HTML) — звичайний текст.
        return False
    if body.startswith("```json"):
        return True
    if not body.startswith("{"):
        return False
    # Початок JSON — це або виклик інструмента, або JSON у відповіді.
    # Розрізняємо їх лише тоді, коли вже видно ім'я інструмента; доти
    # притримуємо, щоб не показати обрізаний виклик.
    head = body[:300]
    if '"name"' not in head and '"tool"' not in head:
        return True
    return any(f'"{name}"' in head for name in names)


def extract_tool_calls(content: str, tools: list[dict[str, Any]],
                       known_names: Iterable[str] | None = None
                       ) -> list[dict[str, Any]]:
    """Витягти виклики інструментів із тексту відповіді.

    Малі моделі (1.5B–7B) часто ігнорують нативний формат і пишуть щось на
    кшталт ``{"name": "read_file", "arguments": {"path": "main.py"}}`` або
    ``<tool_call>{"name": ...}</tool_call>``. Розбираємо обидва варіанти й
    повертаємо у тому ж форматі, що й справжні tool_calls.

    ``known_names`` — ПОВНИЙ перелік імен інструментів, які взагалі існують.
    Потрібен для лінивого режиму: моделі передають частину схем, а викликати
    вона може будь-який інструмент (див. :func:`_recover_names`).
    """
    if not content:
        return []
    names = _recover_names(tools, known_names)
    if not names:
        return []

    payloads: list[Any] = []
    # 1. Явні теги <tool_call>…</tool_call>
    for match in re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", content, re.DOTALL):
        payloads.append(match.group(1))
    # 1б. Обгортка <tools>…</tools>, яку дає qwen2.5-coder у llama.cpp.
    for match in re.finditer(r"<tools>\s*(.*?)\s*</tools>", content, re.DOTALL):
        payloads.append(match.group(1))
    # 2. Блоки ```json … ``` (модель часто обгортає виклик у код)
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", content, re.DOTALL):
        payloads.append(match.group(1))
    # 3. Голий JSON-об'єкт у тексті
    if not payloads:
        payloads.append(content)

    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payloads:
        for candidate in _json_candidates(str(raw)):
            for call in _as_tool_calls(candidate, names):
                key = (call["function"]["name"] + "\u0000"
                       + call["function"]["arguments"])
                if key in seen:
                    continue
                seen.add(key)
                calls.append(call)

    for index, call in enumerate(calls):
        call["id"] = f"call_{index}"
    return calls


def _repair_json(text: str) -> str:
    """Полагодити типові огріхи локальних моделей у JSON.

    Найчастіше трапляється екранований апостроф ``\\'`` — у JSON такої
    послідовності не існує, і ``json.loads`` відкидає ВЕСЬ виклик
    інструмента. Модель при цьому вважає, що все зробила.
    """
    fixed = text.replace("\\'", "'")
    # \x, \s, \d тощо — невалідні екранування: лишаємо сам символ.
    fixed = re.sub(r'\\([^"\\/bfnrtu])', r"\1", fixed)
    # Обірваний хвіст після останньої коми.
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    return fixed


def _json_candidates(raw: str) -> Iterator[Any]:
    """Усі JSON-значення, які вдалось розпізнати в рядку."""
    text = raw.strip()
    if not text:
        return
    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass
    # Друга спроба: полагодити типові огріхи моделі (див. _repair_json).
    repaired = _repair_json(text)
    if repaired != text:
        try:
            yield json.loads(repaired)
            return
        except json.JSONDecodeError:
            pass
    # Шукаємо збалансовані об'єкти/масиви в довільному тексті.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for position in range(start, len(text)):
                char = text[position]
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if char == opener:
                    depth += 1
                elif char == closer:
                    depth -= 1
                    if depth == 0:
                        piece = text[start: position + 1]
                        try:
                            yield json.loads(piece)
                        except json.JSONDecodeError:
                            try:
                                yield json.loads(_repair_json(piece))
                            except json.JSONDecodeError:
                                pass
                        start = text.find(opener, position + 1)
                        break
            else:
                break


def _as_tool_call(candidate: Any, names: set[str]) -> dict[str, Any] | None:
    """Перетворити розібраний JSON на виклик інструмента (або None)."""
    calls = _as_tool_calls(candidate, names)
    return calls[0] if calls else None


def _as_tool_calls(candidate: Any, names: set[str]) -> list[dict[str, Any]]:
    """Усі виклики інструментів у розібраному JSON-значенні.

    Модель може покласти кілька викликів в один масив — їх треба виконати
    всі, а не лише перший.
    """
    if isinstance(candidate, list):
        result: list[dict[str, Any]] = []
        for item in candidate:
            result.extend(_as_tool_calls(item, names))
        return result
    if not isinstance(candidate, dict):
        return []

    # Варіанти: {"name": ..., "arguments": {...}} / {"tool": ...} /
    # {"function": {"name": ..., "arguments": ...}}
    function = candidate.get("function") if isinstance(candidate.get("function"), dict) else {}
    name = (candidate.get("name") or candidate.get("tool") or candidate.get("tool_name")
            or function.get("name") or "")
    if not isinstance(name, str) or name not in names:
        return []
    arguments = (candidate.get("arguments") or candidate.get("parameters")
                 or candidate.get("args") or function.get("arguments") or {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return [{
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }]


def image_message(text: str, images: Iterable[str | Path],
                  *, limit_mb: float = 8.0) -> dict[str, Any]:
    """Повідомлення з текстом і ЗОБРАЖЕННЯМИ (формат OpenAI vision).

    Навіщо окрема функція. Мультимодальна локальна модель бачить картинку
    лише тоді, коли вона передана як ``image_url`` з ``data:image/png;base64``.
    Шлях до файлу модель НЕ читає: раніше агент отримував «Скріншот
    збережено: C:\\…\\shot.png» і не міг подивитись, що там насправді.

    Великі знімки (4K-екран) стискаємо: base64 від 8 МБ — це понад 10 МБ
    у запиті, а локальний сервер такого не приймає. Тому зменшуємо через
    ``screenshot.reduce_png`` до розумного розміру.
    """
    parts: list[dict[str, Any]] = []
    body = (text or "").strip()
    if body:
        parts.append({"type": "text", "text": body})
    for item in images:
        path = Path(item) if not isinstance(item, Path) else item
        if not path.exists():
            LOG.debug("Зображення не знайдено: %s", path)
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        payload = raw
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        size_mb = len(raw) / (1024 ** 2)
        if size_mb > limit_mb:
            seen_png = _shrink_png(path, raw, limit_mb)
            if seen_png is not None:
                payload = seen_png
                mime = "image/png"
        encoded = base64.b64encode(payload).decode("ascii")
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        })
        LOG.info("Додано зображення до запиту: %s (%.2f МБ)",
                 path.name, len(payload) / (1024 ** 2))
    return {"role": "user", "content": parts}


def _shrink_png(path: Path, raw: bytes, limit_mb: float) -> Optional[bytes]:
    """Зменшити PNG до прийнятного розміру (через :mod:`screenshot`)."""
    try:
        from . import screenshot as shot
    except ImportError:
        return None
    target = path.with_name(f"{path.stem}.small.png")
    result = shot.shrink_png_file(path, target, limit_mb=limit_mb)
    if not result:
        return None
    try:
        return target.read_bytes()
    except OSError:
        return None


def strip_tool_json(content: str, tools: list[dict[str, Any]] | None = None) -> str:
    """Прибрати з відповіді текст, який ми вже перетворили на виклик.

    Прибираються:

    * ``<tool_call>…</tool_call>`` і ``<tools>…</tools>`` — службові теги;
    * блоки ```` ```json … ``` ```` з викликом;
    * «голі» JSON-об'єкти виклику — незалежно від того, чи є цей інструмент
      у списку СХЕМ.

    Останній пункт критичний. Раніше вирізались лише об'єкти, чия назва є в
    переданих схемах. Але локальна модель регулярно видумує назву, якої
    схеми не мають (напр. ``router:search_web``, коли MCP не підключено), —
    і тоді сирий JSON лишався в тексті відповіді. Користувач бачив у чаті
    ``{"name": "router:search_web", "arguments": …}`` замість відповіді
    (це видно на його скріншоті).
    """
    text = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL)
    # Обгортка <tools>…</tools> (qwen2.5-coder у llama.cpp) — теж службова.
    text = re.sub(r"<tools>.*?</tools>", "", text, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?\s*(?:\{.*?\}|\[.*?\])\s*```", "", text, flags=re.DOTALL)
    names = _tool_names(tools or [])
    # 1. Виклики відомих інструментів (точна перевірка за назвою).
    if names:
        text = _strip_balanced_objects(text, names)
    # 2. Виклики з НЕВІДОМОЮ назвою — за формою об'єкта.
    text = _strip_calls_by_shape(text)
    return text.strip()


#: Ознаки того, що JSON-об'єкт у тексті — це виклик інструмента, а не дані.
_CALL_KEY = re.compile(r'"(?:name|tool|tool_name|function)"\s*:')
_ARGS_KEY = re.compile(r'"(?:arguments|args|parameters|input)"\s*:')


def _strip_calls_by_shape(text: str) -> str:
    """Вирізати JSON-об'єкти, ЯКІ ЗА ФОРМОЮ є викликом інструмента.

    Умова навмисно вузька, щоб не знищити справжню відповідь із JSON:
    потрібні ОДНОЧАСНО ключ назви й ключ аргументів. Довільний JSON
    (конфіг, дані, приклад) такої пари майже ніколи не має.

    Прохід ОДИН, від початку до кінця: знайдені об'єкти вирізаються, решта
    тексту переноситься як є. Раніше тут був повторний скан того самого
    місця після вирізання — це зациклювало функцію назавжди.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        start = text.find("{", index)
        if start < 0:
            out.append(text[index:])
            break
        end = _balanced_end(text, start)
        if end is None or end <= start:
            # Незакритий об'єкт (обірвана відповідь) — лишаємо як є й виходимо.
            out.append(text[index:])
            break
        chunk = text[start:end]
        out.append(text[index:start])
        if _CALL_KEY.search(chunk) and _ARGS_KEY.search(chunk):
            # Це виклик — не показуємо. З'їдаємо і зайвий перевід рядка,
            # що лишився після нього, щоб у чаті не було порожнього рядка.
            index = end
            if index < length and text[index] == "\n":
                index += 1
            continue
        out.append(chunk)
        index = end
    return "".join(out)


def _strip_balanced_objects(text: str, names: set[str]) -> str:
    """Вирізати JSON-об'єкти виклику, балансуючи дужки й лапки."""
    name_pattern = re.compile(
        r'\{[^{}]*?"(?:name|tool|tool_name)"\s*:\s*"('
        + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        + r')"'
    )
    out: list[str] = []
    index = 0
    while index < len(text):
        match = name_pattern.search(text, index)
        if match is None:
            out.append(text[index:])
            break
        start = match.start()
        out.append(text[index:start])
        end = _balanced_end(text, start)
        index = end if end is not None else match.end()
    return "".join(out)


def _balanced_end(text: str, start: int) -> int | None:
    """Індекс після закривної дужки об'єкта, що починається з ``start``."""
    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(text)):
        char = text[position]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position + 1
    return None



class LLMError(RuntimeError):
    """Помилка спілкування з моделлю."""


def _human_error_body(body: str) -> str:
    """Зробити тіло помилки сервера читабельним для людини.

    Навіщо. Багато OpenAI-сумісних серверів віддають помилку з
    ``ensure_ascii=True`` — тобто замість кирилиці в тілі лежать
    escape-послідовності::

        {"error": {"message": "\\u043c\\u043e\\u0434\\u0435\\u043b\\u044c ..."}}

    Користувач бачив у діалозі саме ``\\u043c\\u043e...`` замість
    «модель впала: немає памʼяті» і не міг нічого зрозуміти.

    Розбираємо JSON і витягуємо людське повідомлення, якщо воно є. Якщо
    тіло не JSON — лишаємо як було (обрізане), щоб не втратити зміст.
    """
    text = (body or "").strip()
    if not text:
        return ""
    # Спершу пробуємо розібрати JSON завжди — навіть коли escape-послідовностей
    # немає. Інакше тіло на кшталт {"error": {"message": "текст"}} лишалось би
    # сирим JSON замість самого повідомлення (так і було: тест
    # test_plain_json_without_escape_is_readable це зловив).
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        # Не JSON — віддаємо як є. Розшифровуємо escape-послідовності, якщо
        # вони є, щоб користувач не бачив \u043c замість кирилиці.
        if "\\u" in text:
            try:
                return text.encode("utf-8").decode("unicode_escape")[:800]
            except (UnicodeDecodeError, ValueError):
                return text[:800]
        return text[:800]
    message = ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")
        elif isinstance(error, str):
            message = error
        if not message:
            message = str(data.get("message") or data.get("detail") or "")
    if not message:
        # JSON розібрався, але повідомлення немає — віддаємо
        # розшифрований текст, щоб не показувати escape-послідовності.
        try:
            return json.dumps(data, ensure_ascii=False)[:800]
        except (TypeError, ValueError):
            return text[:800]
    return message[:800]


def _merge_usage(target: dict[str, Any], incoming: dict[str, int]) -> None:
    """Доповнити лічильники токенів, не затираючи відомі значення.

    Стріми (Anthropic, Gemini) розносять лічильники по різних подіях:
    ``input_tokens`` приходить на старті, ``output_tokens`` — наприкінці.
    Просте ``update()`` затирало prompt-лічильник нулем, і статистика
    показувала «0 вхідних токенів» для цілком нормального запиту.
    """
    for key, value in (incoming or {}).items():
        try:
            number = int(value or 0)
        except (TypeError, ValueError):
            continue
        if number > 0 or key not in target:
            target[key] = number
    prompt = int(target.get("prompt_tokens") or 0)
    completion = int(target.get("completion_tokens") or 0)
    if prompt or completion:
        target["total_tokens"] = prompt + completion


def _safe_call(callback: Callable[..., None], *args: Any) -> None:
    """Викликати колбек стрімінгу, не даючи йому зірвати читання потоку."""
    try:
        callback(*args)
    except Exception:  # noqa: BLE001 - інтерфейс не має ламати генерацію
        LOG.debug("Колбек стрімінгу впав", exc_info=True)


def _parse_plain(body: str) -> "ChatResult":
    """Розібрати звичайну (не-SSE) відповідь сервера у :class:`ChatResult`."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise LLMError(f"Відповідь не JSON: {str(body)[:300]}") from exc
    try:
        choice = (data.get("choices") or [{}])[0]
    except (AttributeError, IndexError) as exc:
        raise LLMError(f"Неочікувана відповідь: {str(data)[:300]}") from exc
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict))
    normalised: list[dict[str, Any]] = []
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        normalised.append({
            "id": call.get("id") or f"call_{index}",
            "type": "function",
            "function": {
                "name": function.get("name", ""),
                "arguments": function.get("arguments", "{}"),
            },
        })
    return ChatResult(
        content=content,
        tool_calls=normalised,
        finish_reason=str(choice.get("finish_reason") or ""),
        usage=data.get("usage"),
        reasoning=str(message.get("reasoning_content") or "")[:4000],
    )


@dataclass
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]]
    finish_reason: str = ""
    usage: dict[str, Any] | None = None
    reasoning: str = ""

    def message(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        return payload


class LLMClient:
    """Мінімальний клієнт chat/completions з підтримкою tool calling."""

    def __init__(
        self,
        base_url: str,
        model: str = "",
        api_key: str = "lm-studio",
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: int = 300,
        reasoning_effort: str = "",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key or "lm-studio"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        # Протокол визначаємо ЗА АДРЕСОЮ: Anthropic має інший шлях і інші
        # заголовки, Gemini-нативний — ключ у рядку запиту. Раніше все йшло
        # як OpenAI, і «підтримка Anthropic» насправді давала 404.
        self.adapter = provider_adapters.for_url(self.base_url)

    @property
    def style(self) -> str:
        """Протокол провайдера: ``openai`` | ``anthropic`` | ``gemini``."""
        return self.adapter.style

    # ── HTTP ───────────────────────────────────────────────────────────────
    def _open(self, url: str, payload: dict[str, Any] | None, *, method: str = "POST"):
        """Відкрити з'єднання з правильними заголовками (спільне для всіх)."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
            if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in self.adapter.headers(self.api_key).items():
            request.add_header(name, value)
        return urllib.request.urlopen(request, timeout=self.timeout)

    def _request(self, path: str, payload: dict[str, Any] | None = None, *, method: str = "POST") -> Any:
        url = self.adapter.url(self.base_url, path.lstrip("/"), self.api_key)
        try:
            with self._open(url, payload, method=method) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = secrets.redact(
                exc.read().decode("utf-8", errors="replace")[:800])
            raise LLMError(f"HTTP {exc.code} від {url}: {_human_error_body(detail)}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(self._connection_error(url, exc.reason)) from exc
        except TimeoutError as exc:
            raise LLMError(f"Таймаут {self.timeout} с під час запиту до {url}") from exc
        if not body.strip():
            raise LLMError(f"Порожня відповідь від {url}")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Відповідь не JSON: {body[:300]}") from exc

    def _connection_error(self, url: str, reason: Any) -> str:
        """Зрозуміла підказка про з'єднання — ЗАЛЕЖНО від адреси.

        Раніше навіть для ``api.openai.com`` радилось «запусти LM Studio».
        Тепер підказка відповідає тому, куди саме не достукались.
        """
        if _is_local_url(url):
            return (f"Немає з'єднання з локальним сервером {url}. Перевір, чи він "
                    f"запущений (LM Studio → Developer → Start Server, або "
                    f"«Хаб моделей» → запустити модель). Деталі: {reason}")
        return (f"Немає з'єднання з {url}. Перевір інтернет, адресу API та "
                f"назву провайдера в налаштуваннях. Деталі: {reason}")

    # ── API ────────────────────────────────────────────────────────────────
    def list_models(self) -> list[str]:
        # Вбудований рушій: список береться з локальної теки моделей.
        if self.style == provider_adapters.EMBEDDED:
            from .native import bridge

            return bridge.list_models()
        payload = self._request(self.adapter.models_path, method="GET")
        items = payload.get("data") if isinstance(payload, dict) else payload
        models: list[str] = []
        for item in items or []:
            if isinstance(item, dict):
                name = item.get("id") or item.get("name") or item.get("displayName") or ""
            else:
                name = str(item)
            if name:
                models.append(name)
        return models

    def ping(self) -> tuple[bool, str]:
        if self.style == provider_adapters.EMBEDDED:
            from .native import bridge

            return bridge.ping()
        try:
            models = self.list_models()
        except LLMError as exc:
            return False, str(exc)
        if not models:
            return False, "Сервер відповів, але не показав жодної моделі."
        return True, f"Онлайн. Моделі: {', '.join(models[:6])}"

    def _use_embedded_default_model(self) -> bool:
        """Підставити модель для вбудованого рушія, якщо назви немає.

        Дефект, який це виправляє (заміряно на справжніх налаштуваннях):
        ``base_url`` = ``native://blackchpok``, ``model`` = порожній рядок —
        і КОЖЕН запит падав із «Модель не вибрана», хоч на диску лежало
        сім GGUF-файлів. Користувач бачив у чаті «модель недоступна» без
        жодної підказки, що модель треба лише ВИБРАТИ.

        Для ``native://`` назва моделі — це не адреса сервера, а шлях до
        файлу: рушій цілком здатен узяти завантажену або найбільшу
        локальну. Тому підставляємо її самі, а вже потім питаємо рушій.
        Порожню назву НЕ вигадуємо для HTTP-серверів: там вона справді
        обов'язкова.
        """
        if self.style != provider_adapters.EMBEDDED:
            return False
        try:
            from .native import bridge

            runtime = bridge.runtime()
        except Exception:  # noqa: BLE001 - без рушія підставляти нічого
            return False
        loaded = str(getattr(runtime, "model_path", "") or "").strip()
        if not loaded:
            try:
                loaded = str(bridge.pending_model() or "").strip()
            except Exception:  # noqa: BLE001
                loaded = ""
        if not loaded:
            try:
                entries = runtime.manager.local_models()
            except Exception:  # noqa: BLE001
                entries = []
            if entries:
                loaded = max(entries, key=lambda item: item.size_gb).key
        if not loaded:
            return False
        self.model = loaded
        LOG.info("Модель не була вибрана — вбудований рушій бере «%s»", loaded)
        return True

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream_callback: Callable[[str], None] | None = None,
        known_tools: Iterable[str] | None = None,
    ) -> ChatResult:
        if not self.model and not self._use_embedded_default_model():
            raise LLMError("Модель не вибрана. Відкрий Налаштування → Модель і натисни «Оновити список».")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        # Reasoning-моделі (DeepSeek reasoner, o1/o3) не приймають
        # temperature — інакше сервер відповідає 400.
        if not is_reasoning_model(self.model):
            payload["temperature"] = (self.temperature if temperature is None
                                      else temperature)
        # Рівень зусилля: OpenAI o-серія розуміє reasoning_effort, інші
        # ігнорують невідомі поля — тому додаємо лише коли задано.
        if self.reasoning_effort and self.reasoning_effort != "default":
            if self.reasoning_effort in {"none", "low", "medium", "high", "max"}:
                payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        # ── Не-OpenAI протокол: інший запит, інша відповідь ───────────────
        if self.style == provider_adapters.EMBEDDED:
            return self._chat_embedded(messages, tools=tools,
                                       temperature=temperature,
                                       max_tokens=max_tokens,
                                       stream_callback=stream_callback)
        if self.style == provider_adapters.ANTHROPIC:
            return self._chat_anthropic(messages, tools=tools,
                                        temperature=temperature,
                                        max_tokens=max_tokens)
        if self.style == provider_adapters.GEMINI:
            return self._chat_gemini(messages, tools=tools,
                                     temperature=temperature,
                                     max_tokens=max_tokens)

        data = self._request(self.adapter.chat_path, payload)
        try:
            choice = (data.get("choices") or [{}])[0]
        except (AttributeError, IndexError) as exc:
            raise LLMError(f"Неочікувана відповідь: {str(data)[:300]}") from exc
        message = choice.get("message") or {}
        # DeepSeek/OpenAI reasoning віддають «думки» окремим полем.
        reasoning = str(message.get("reasoning_content") or "")[:4000]
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        tool_calls = message.get("tool_calls") or []
        normalised: list[dict[str, Any]] = []
        for index, call in enumerate(tool_calls):
            function = call.get("function") or {}
            normalised.append(
                {
                    "id": call.get("id") or f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments", "{}"),
                    },
                }
            )
        if not normalised and tools and content:
            # Малі локальні моделі часто пишуть виклик інструмента текстом
            # (```json {"name": ..., "arguments": {...}} ```) замість
            # поля tool_calls. Без цього розбору агент просто «говорив би»
            # замість того, щоб працювати.
            recovered = extract_tool_calls(content, tools, known_tools)
            if recovered:
                normalised = recovered
                LOG.info("Виклик інструмента відновлено з тексту: %s",
                         ", ".join(call["function"]["name"] for call in recovered))
                content = strip_tool_json(content, tools)
        elif normalised and content:
            # Буває, що модель віддає і нативний tool_call, і його текстовий
            # дубль. Показувати користувачу сирий JSON виклику не можна:
            # на скріншоті користувача в чаті висів цілий ```json {...}```
            # з аргументами write_file замість нормальної відповіді.
            #
            # Умова «cleaned != strip_tool_json(content)» була хибною: вона
            # порівнювала результат із самим собою в іншій формі й майже
            # завжди давала False, тож очищення не застосовувалось.
            # Тепер: якщо після очищення текст змінився — беремо очищений.
            cleaned = strip_tool_json(content, tools)
            bare = strip_tool_json(content)
            if cleaned and cleaned != content:
                content = cleaned
            elif not cleaned and bare != content:
                content = bare
        if stream_callback and content:
            stream_callback(content)
        return ChatResult(
            content=content,
            tool_calls=normalised,
            finish_reason=choice.get("finish_reason", "") or "",
            usage=data.get("usage"),
            reasoning=reasoning if not is_reasoning_model(self.model) or reasoning else reasoning,
        )

    # ── Вбудований рушій BLACKCHPOK ─────────────────────────────────────────
    def _chat_embedded(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> ChatResult:
        """Запит до власного рушія (llama.dll у цьому ж процесі).

        Жодного HTTP і жодного стороннього застосунку: модель уже
        завантажена в пам'ять IDE, тож відповідь приходить із
        ``llama_decode``. Телеметрія (токени, швидкість) теж справжня —
        її дає рушій, а не оцінка.
        """
        from .native import bridge

        try:
            data = bridge.chat(
                messages,
                model=self.model,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                # Тайм-аут із налаштувань МУСИТЬ доходити до рушія: без нього
                # діяла типова стеля 600 с, і одна застрягла генерація
                # тримала потік агента десять хвилин (заміряно
                # ``tools/check_stability.py``).
                timeout=float(self.timeout or 0) or None,
            )
        except Exception as exc:                    # noqa: BLE001 - єдиний тип помилки
            raise LLMError(f"Вбудований рушій: {exc}") from exc
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        tool_calls = message.get("tool_calls") or []
        usage = data.get("usage") or {}
        if stream_callback and content:
            stream_callback(content)
        return ChatResult(
            content=content,
            tool_calls=list(tool_calls),
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=usage,
            reasoning="",
        )

    def _stream_embedded(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> ChatResult:
        """Потокова відповідь власного рушія (без SSE — просто callback'и)."""
        from .native import bridge

        try:
            data = bridge.chat_stream(
                messages,
                model=self.model,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                on_text=on_text,
                on_reasoning=on_reasoning,
                should_stop=should_stop,
            )
        except Exception as exc:                    # noqa: BLE001
            raise LLMError(f"Вбудований рушій: {exc}") from exc
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return ChatResult(
            content=str(message.get("content") or ""),
            tool_calls=list(message.get("tool_calls") or []),
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=data.get("usage") or {},
            reasoning="",
        )

    # ── Anthropic ──────────────────────────────────────────────────────────
    # ── стрімінг Anthropic ─────────────────────────────────────────────────
    def _stream_anthropic(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> "ChatResult":
        """Стрімінг Anthropic: події ``content_block_delta``.

        Формат інший, ніж в OpenAI: текст приходить у ``text_delta``,
        аргументи інструмента — у ``input_json_delta`` (частинами!), а сам
        виклик починається з ``content_block_start`` із ``tool_use``.
        Тому збираємо виклики за ``index`` блоку, а не за ``tool_calls``.
        """
        payload = provider_adapters.anthropic_payload(
            messages,
            model=self.model,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            temperature=self.temperature if temperature is None else temperature,
            tools=tools,
            stream=True,
        )
        url = self.adapter.url(self.base_url, self.adapter.chat_path, self.api_key)
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST")
        for name, value in self.adapter.headers(self.api_key).items():
            request.add_header(name, value)
        request.add_header("Accept", "text/event-stream")

        pieces: list[str] = []
        thoughts: list[str] = []
        #: index блоку → {id, name, arguments}
        blocks: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        usage: dict[str, Any] = {}
        saw_event = False

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    if should_stop is not None and should_stop():
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    saw_event = True
                    kind = str(data.get("type") or "")
                    if kind == "message_start":
                        _merge_usage(usage, provider_adapters.anthropic_usage(
                            data.get("message") or {}))
                        continue
                    if kind == "message_delta":
                        delta = data.get("delta") or {}
                        finish_reason = str(delta.get("stop_reason") or finish_reason)
                        # ``message_delta`` несе ЛИШЕ ``output_tokens``, а
                        # ``input_tokens`` приходить у ``message_start``.
                        # Тому ЗЛИВАЄМО, а не перезаписуємо: інакше
                        # prompt_tokens ставав 0 і статистика брехала.
                        _merge_usage(usage, provider_adapters.anthropic_usage(data))
                        continue
                    event = provider_adapters.anthropic_stream_delta(data)
                    if "text" in event:
                        piece = str(event["text"])
                        if piece:
                            pieces.append(piece)
                            if on_text is not None:
                                _safe_call(on_text, piece)
                    elif "reasoning" in event:
                        thought = str(event["reasoning"])
                        if thought:
                            thoughts.append(thought)
                            if on_reasoning is not None:
                                _safe_call(on_reasoning, thought)
                    elif "tool_start" in event:
                        start = event["tool_start"]
                        blocks[int(start.get("index", 0))] = {
                            "id": str(start.get("id") or ""),
                            "name": str(start.get("name") or ""),
                            "arguments": "",
                        }
                    elif "tool_args" in event:
                        args = event["tool_args"]
                        slot = blocks.setdefault(
                            int(args.get("index", 0)),
                            {"id": "", "name": "", "arguments": ""})
                        slot["arguments"] += str(args.get("delta") or "")
                    elif "tool_stop" in event:
                        continue
                    if kind == "error":
                        detail = (data.get("error") or {}).get("message") or str(data)
                        raise LLMError(f"Anthropic: {secrets.redact(str(detail))}")
        except urllib.error.HTTPError as exc:
            detail = secrets.redact(
                exc.read().decode("utf-8", errors="replace")[:800])
            raise LLMError(f"HTTP {exc.code} від {url}: {_human_error_body(detail)}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(self._connection_error(url, exc.reason)) from exc
        except TimeoutError as exc:
            raise LLMError(f"Таймаут {self.timeout} с під час запиту до {url}") from exc

        if not saw_event:
            # Стрім не прийшов — повторюємо звичайним запитом (як для OpenAI).
            return self._chat_anthropic(messages, tools=tools,
                                        temperature=temperature,
                                        max_tokens=max_tokens)
        calls = [
            {
                "id": slot["id"] or f"call_{index}",
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot["arguments"] or "{}",
                },
            }
            for index, slot in sorted(blocks.items()) if slot.get("name")
        ]
        return ChatResult(
            content="".join(pieces),
            tool_calls=calls,
            finish_reason=finish_reason,
            usage=usage or None,
            reasoning="".join(thoughts)[:4000],
        )

# ────────────────────────────────────────────────────────────────────────
    def _stream_gemini(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> "ChatResult":
        """Стрімінг Gemini: ``:streamGenerateContent?alt=sse``.

        Кожна подія — повний фрагмент ``candidates[0].content.parts``;
        ``functionCall`` приходить цілком (не частинами, як в OpenAI).
        """
        payload = provider_adapters.gemini_payload(
            messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            tools=tools,
        )
        path = provider_adapters.gemini_chat_path(self.model, stream=True)
        url = self.adapter.url(self.base_url, path, self.api_key)
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST")
        for name, value in self.adapter.headers(self.api_key).items():
            request.add_header(name, value)
        request.add_header("Accept", "text/event-stream")

        pieces: list[str] = []
        thoughts: list[str] = []
        calls: list[dict[str, Any]] = []
        finish_reason = ""
        usage: dict[str, Any] = {}
        saw_event = False

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    if should_stop is not None and should_stop():
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    saw_event = True
                    if data.get("error"):
                        detail = (data["error"] or {}).get("message") or str(data)
                        raise LLMError(f"Gemini: {secrets.redact(str(detail))}")
                    if data.get("usageMetadata"):
                        usage = provider_adapters.gemini_usage(data)
                    text, found, reason, thought = provider_adapters.gemini_result_split(data)
                    if reason:
                        finish_reason = reason
                    if thought:
                        thoughts.append(thought)
                        if on_reasoning is not None:
                            _safe_call(on_reasoning, thought)
                    if text:
                        pieces.append(text)
                        if on_text is not None:
                            _safe_call(on_text, text)
                    for call in found:
                        calls.append(call)
        except urllib.error.HTTPError as exc:
            detail = secrets.redact(
                exc.read().decode("utf-8", errors="replace")[:800])
            raise LLMError(f"HTTP {exc.code} від {url}: {_human_error_body(detail)}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(self._connection_error(url, exc.reason)) from exc
        except TimeoutError as exc:
            raise LLMError(f"Таймаут {self.timeout} с під час запиту до {url}") from exc

        if not saw_event:
            return self._chat_gemini(messages, tools=tools,
                                     temperature=temperature,
                                     max_tokens=max_tokens)
        return ChatResult(
            content="".join(pieces),
            tool_calls=calls,
            finish_reason=finish_reason,
            usage=usage or None,
            reasoning="".join(thoughts),
        )

    def _chat_anthropic(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        known_tools: Iterable[str] | None = None,
    ) -> "ChatResult":
        """Запит до ``/v1/messages`` Anthropic (справжній протокол)."""
        payload = provider_adapters.anthropic_payload(
            messages,
            model=self.model,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            temperature=self.temperature if temperature is None else temperature,
            tools=tools,
            stream=False,
        )
        data = self._request(self.adapter.chat_path, payload)
        if not isinstance(data, dict):
            raise LLMError(f"Неочікувана відповідь Anthropic: {str(data)[:300]}")
        if data.get("type") == "error":
            detail = (data.get("error") or {}).get("message") or str(data)[:300]
            raise LLMError(f"Anthropic: {secrets.redact(str(detail))}")
        content, calls, stop, thought = provider_adapters.anthropic_result_split(data)
        usage = provider_adapters.anthropic_usage(data)
        # Якщо модель не має нативного виклику — пробуємо текстовий розбір,
        # як і для OpenAI-сумісних: локальність протоколу тут не важлива.
        if not calls and tools and content:
            recovered = extract_tool_calls(content, tools, known_tools)
            if recovered:
                calls = recovered
                content = strip_tool_json(content, tools)
        return ChatResult(
            content=content,
            tool_calls=calls,
            finish_reason=stop,
            usage=usage,
            reasoning=thought,
        )

    # ── Gemini ─────────────────────────────────────────────────────────────
    def _chat_gemini(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        known_tools: Iterable[str] | None = None,
    ) -> "ChatResult":
        """Запит до нативного ``generateContent`` Gemini."""
        payload = provider_adapters.gemini_payload(
            messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            tools=tools,
        )
        path = provider_adapters.gemini_chat_path(self.model)
        data = self._request(path, payload)
        if not isinstance(data, dict):
            raise LLMError(f"Неочікувана відповідь Gemini: {str(data)[:300]}")
        if data.get("error"):
            detail = (data.get("error") or {}).get("message") or str(data)[:300]
            raise LLMError(f"Gemini: {secrets.redact(str(detail))}")
        content, calls, stop, thought = provider_adapters.gemini_result_split(data)
        usage = provider_adapters.gemini_usage(data)
        if not calls and tools and content:
            recovered = extract_tool_calls(content, tools, known_tools)
            if recovered:
                calls = recovered
                content = strip_tool_json(content, tools)
        return ChatResult(
            content=content,
            tool_calls=calls,
            finish_reason=stop,
            usage=usage,
            reasoning=thought,
        )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        known_tools: Iterable[str] | None = None,
    ) -> "ChatResult":
        """Стрімінг відповіді через SSE (``stream: true``).

        Повертає той самий :class:`ChatResult`, що й :meth:`chat`, але
        додатково викликає ``on_text`` на кожен шматок тексту й
        ``on_reasoning`` на кожен шматок роздумів. Так користувач бачить,
        як відповідь друкується, а не чекає мовчки.

        Якщо сервер не підтримує стрімінг (не віддає ``data:``), метод
        прозоро відкочується до звичайного запиту, тож поведінка не
        ламається на старих рушіях.
        """
        if not self.model and not self._use_embedded_default_model():
            raise LLMError("Модель не вибрана. Відкрий Налаштування → Модель і натисни «Оновити список».")

        # ── Не-OpenAI протокол: інший формат стріму ───────────────────────
        # Anthropic і Gemini віддають зовсім інші SSE-події, тому окремі гілки.
        # Раніше тут завжди формувався OpenAI-payload: до Anthropic ішов
        # запит із ``messages``/``stream_options`` (сервер відповідав 400),
        # а Gemini — на ``/chat/completions``, якого в нього немає.
        if self.style == provider_adapters.EMBEDDED:
            return self._stream_embedded(
                messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, on_text=on_text,
                on_reasoning=on_reasoning, should_stop=should_stop)
        if self.style == provider_adapters.ANTHROPIC:
            return self._stream_anthropic(
                messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, on_text=on_text,
                on_reasoning=on_reasoning, should_stop=should_stop)
        if self.style == provider_adapters.GEMINI:
            return self._stream_gemini(
                messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, on_text=on_text,
                on_reasoning=on_reasoning, should_stop=should_stop)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
            # Без цього llama.cpp не віддає usage у стрімі, і смуга
            # статистики показує 0 токенів замість реальних чисел.
            "stream_options": {"include_usage": True},
        }
        if not is_reasoning_model(self.model):
            payload["temperature"] = (self.temperature if temperature is None
                                      else temperature)
        if self.reasoning_effort and self.reasoning_effort != "default":
            if self.reasoning_effort in {"none", "low", "medium", "high", "max"}:
                payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        url = self.adapter.url(self.base_url, self.adapter.chat_path, self.api_key)
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST")
        for name, value in self.adapter.headers(self.api_key).items():
            request.add_header(name, value)
        request.add_header("Accept", "text/event-stream")

        pieces: list[str] = []
        thoughts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        saw_event = False
        #: Імена інструментів — щоб відрізнити виклик від звичайного тексту.
        names = _tool_names(tools or [])
        #: Скільки символів уже віддано в ``on_text`` (щоб не дублювати).
        shown = 0
        # usage приходить останнім чанком стріму (stream_options.include_usage).
        stream_usage: dict[str, Any] = {}
        # Тіло відповіді, якщо сервер проігнорував ``stream`` і прислав JSON.
        plain_body: list[str] = []

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                # ── Діагностика живого стріму ──────────────────────────────
                # Тримаємо ЧАС і кількість отриманих подій: без цього
                # «[WinError 10054] connection forcibly closed» нічого не
                # пояснював, і причину доводилось шукати навмання.
                streamed = 0
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if "event-stream" not in content_type:
                    # Сервер не вміє SSE — віддає звичайний JSON одним тілом.
                    plain_body.append(response.read().decode("utf-8", errors="replace"))
                for raw_line in response:
                    if plain_body:
                        break
                    if should_stop is not None and should_stop():
                        break
                    streamed += 1
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        saw_event = True
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    saw_event = True
                    # Останній чанк стріму несе usage (коли попросили
                    # stream_options.include_usage) — без нього статистика
                    # токенів завжди нульова.
                    chunk_usage = data.get("usage")
                    if isinstance(chunk_usage, dict) and chunk_usage:
                        stream_usage = chunk_usage
                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason") or finish_reason
                    text = delta.get("content")
                    if text:
                        pieces.append(text)
                        # Малі моделі шлють виклик інструмента як ТЕКСТ
                        # (`{"name": "list_dir", ...}`). Якщо віддавати це в
                        # чат одразу, користувач бачить сирий JSON замість
                        # відповіді. Тому текст назовні показуємо лише тоді,
                        # коли накопичене вже не може бути викликом.
                        accumulated = "".join(pieces)
                        if on_text is not None and not _looks_like_tool_json(
                                accumulated, names):
                            fresh = accumulated[shown:]
                            if fresh:
                                shown = len(accumulated)
                                _safe_call(on_text, fresh)
                    thought = delta.get("reasoning_content") or delta.get("reasoning")
                    if thought:
                        thoughts.append(str(thought))
                        if on_reasoning is not None:
                            _safe_call(on_reasoning, str(thought))
                    for item in delta.get("tool_calls") or ():
                        if not isinstance(item, dict):
                            continue
                        index = int(item.get("index") or 0)
                        slot = tool_calls.setdefault(
                            index, {"id": "", "name": "", "arguments": ""})
                        if item.get("id"):
                            slot["id"] = str(item["id"])
                        function = item.get("function") or {}
                        if function.get("name"):
                            slot["name"] = str(function["name"])
                        if function.get("arguments"):
                            slot["arguments"] += str(function["arguments"])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise LLMError(f"HTTP {exc.code} від {url}: {_human_error_body(detail)}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Немає з'єднання з {url}. Перевір, чи запущено локальний сервер "
                f"(LM Studio → Developer → Start Server). Деталі: {exc.reason}"
            ) from exc
        except ConnectionResetError as exc:
            # ── Найчастіший збій живого стріму ────────────────────────────
            # ``10054 An existing connection was forcibly closed by the
            # remote host`` — це НЕ ``urllib.error.URLError``, тому раніше
            # виняток летів наскрізь і виглядав як «стрибок» у агенті:
            #
            #   19:40:47 Стрімінг не вдався ([WinError 10054] …), повторюю
            #            звичайним запитом
            #
            # Найчастіші причини: рушій закрив слот (переповнений контекст
            # або модель вивантажено), або промпт перевищив ``--ctx-size``.
            # Тепер це ЧЕСНА помилка з поясненням, а не мовчазний збій: агент
            # показує причину, а не «модель не відповіла».
            raise LLMError(
                f"Сервер обірвав з'єднання під час стріму ({url}) "
                f"після {streamed} рядків. "
                f"Найчастіше це переповнений контекст (--ctx-size), "
                f"вивантаження моделі простоєм або надто довге мовчання "
                f"сервера. Деталі: {exc}") from exc
        except TimeoutError as exc:
            raise LLMError(f"Таймаут {self.timeout} с під час запиту до {url}") from exc

        if plain_body:
            # Сервер проігнорував stream. Розбираємо те, що вже отримали —
            # повторний запит подвоїв би навантаження й витрати токенів.
            return _parse_plain(plain_body[0])

        if not saw_event:
            # Порожній потік без жодної події: чесно повідомляємо про це,
            # не роблячи прихованого другого запиту.
            raise LLMError("Сервер не повернув ні стрім, ні звичайну відповідь.")

        content = "".join(pieces)
        normalised: list[dict[str, Any]] = []
        for index in sorted(tool_calls):
            slot = tool_calls[index]
            if not slot.get("name"):
                continue
            normalised.append({
                "id": slot.get("id") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot.get("arguments") or "{}",
                },
            })
        if not normalised and tools and content:
            recovered = extract_tool_calls(content, tools, known_tools)
            if recovered:
                normalised = recovered
                content = strip_tool_json(content, tools)
        elif normalised and content:
            # Той самий захист, що й у ``chat``: сирий JSON виклику не має
            # потрапляти в стрічку чату (див. коментар там).
            cleaned = strip_tool_json(content, tools)
            bare = strip_tool_json(content)
            if cleaned and cleaned != content:
                content = cleaned
            elif not cleaned and bare != content:
                content = bare

        # Частину тексту могли притримати (він скидався на виклик), але
        # виклику не стало — це звичайна відповідь, тож віддаємо залишок.
        if on_text is not None and not normalised and len(content) > shown:
            _safe_call(on_text, content[shown:])

        return ChatResult(
            content=content,
            tool_calls=normalised,
            finish_reason=finish_reason,
            usage=stream_usage or None,
            reasoning="".join(thoughts)[:4000],
        )

    # ── авто-визначення ────────────────────────────────────────────────────
    @classmethod
    def detect(cls, preferred_url: str = "", api_key: str = "lm-studio", timeout: int = 8) -> tuple[str, list[str]]:
        """Знайти перший живий локальний сервер. Повертає (url, моделі)."""
        candidates: list[str] = []
        if preferred_url:
            candidates.append(preferred_url.rstrip("/"))
        candidates.extend(url for _name, url in KNOWN_ENDPOINTS if url not in candidates)
        for url in candidates:
            probe = cls(url, api_key=api_key, timeout=timeout)
            try:
                models = probe.list_models()
            except LLMError:
                continue
            if models:
                return url, models
        return "", []

    @staticmethod
    def pick_model(models: list[str]) -> str:
        """Вибрати модель, яка найкраще підходить для коду з інструментами."""
        if not models:
            return ""
        priorities = ("coder", "qwen", "deepseek", "llama", "mistral", "ministral", "gpt", "claude", "gemma", "phi")
        for token in priorities:
            for name in models:
                if token in name.lower():
                    return name
        return models[0]

    def stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> Iterator[str]:
        """Простий стрімінг (без tool calling) для коротких відповідей."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }
        url = f"{self.base_url}/chat/completions"
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
        request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = ((data.get("choices") or [{}])[0].get("delta") or {})
                    text = delta.get("content")
                    if text:
                        yield text
        except urllib.error.URLError as exc:
            raise LLMError(f"Стрімінг недоступний: {exc}") from exc
