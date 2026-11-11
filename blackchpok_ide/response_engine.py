"""Людська відповідь: результати роботи → зрозумілий текст.

Проблема, яку закриває цей модуль, описана так: «не перетворюй кожну
відповідь на величезний набір незрозумілого коду, JSON або технічних
логів». Тобто між «модель щось відповіла» і «користувач це прочитав» має
стояти шар, який:

1. **прибирає внутрішній протокол** — сирі виклики інструментів, JSON
   аргументів, службові рамки, стектрейси без причини;
2. **збирає відповідь зі справжніх результатів**, коли модель промовчала:
   список файлів стає списком, довгий вивід — коротким блоком із лічильником;
3. **не дає оголосити успіх без доказу**: якщо жоден інструмент не
   підтвердив зміну, так і каже;
4. **тримає структуру** «що зроблено → що виявлено → де змінено → як
   перевірено → що лишилось», але не змушує до неї просте завдання.

Модуль чистий: без tkinter, без мережі. Усе перевіряється тестами.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from . import markdown_view
from .tool_orchestrator import Observation

__all__ = [
    "ResponseDraft",
    "answer_from_observations",
    "clarifying_question",
    "clean_for_chat",
    "explain_failure",
    "final_answer",
    "looks_like_raw_protocol",
    "strip_protocol",
]


# ─── Чищення тексту від внутрішнього протоколу ──────────────────────────────

#: Ознаки того, що рядок — це ВНУТРІШНІЙ протокол, а не відповідь людині.
_PROTOCOL_MARKERS: tuple[str, ...] = (
    '"tool_calls"', '"tool_call_id"', '"function_call"', '"arguments"',
    "tool_call>", "<function=", "<|im_start|>", "<|im_end|>",
    "[результат інструмента",
    "ПОМИЛКА: ",
)

#: Рядки-рамки, які додає сам агент для моделі.
_AGENT_FRAME_RE = re.compile(
    r"^\s*(?:"
    r"Контекст завдання \(не перепитуй це\)|"
    r"Що вже зрозуміло з прохання|"
    r"Що мається на увазі:|"
    r"Ти вже виконав інструменти|"
    r"Правило:|"
    r"Мета:|"
    r"Обмеження:|"
    r"Доступні дії IDE:"
    r")",
    re.MULTILINE,
)


def _balanced_json_spans(text: str) -> list[tuple[int, int]]:
    """Межі збалансованих JSON-об'єктів у тексті (для вирізання викликів)."""
    spans: list[tuple[int, int]] = []
    index = text.find("{")
    while index != -1:
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for position in range(index, len(text)):
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
                    end = position
                    break
        if end == -1:
            break
        spans.append((index, end + 1))
        index = text.find("{", end + 1)
    return spans


def _looks_like_call_payload(chunk: str) -> bool:
    """Чи це JSON-виклик інструмента (а не приклад даних у відповіді)."""
    low = chunk.lower()
    # ``tool_calls`` / ``tool_call_id`` — типова форма OpenAI-протоколу.
    # Без них модель із «сирим» викликом показувала користувачу службовий
    # JSON замість відповіді.
    if any(marker in low for marker in _PROTOCOL_MARKERS):
        return True
    return ('"name"' in low or '"tool"' in low or '"arguments"' in low) and (
        '"function"' in low or '"arguments"' in low or '"tool"' in low)


def strip_protocol(text: str) -> str:
    """Прибрати з тексту сирі виклики інструментів, теги й рамки агента.

    Робимо ЦЕ ДО показу в чаті: користувач не має бачити
    ``{"name": "read_file", "arguments": {...}}`` замість відповіді.
    """
    body = text or ""
    if not body.strip():
        return ""
    # 1. Службові теги моделей.
    body = re.sub(r"<tool_call>.*?</tool_call>", "", body, flags=re.DOTALL)
    body = re.sub(r"<tools>.*?</tools>", "", body, flags=re.DOTALL)
    body = re.sub(r"<\|?im_(start|end)\|?>", "", body)
    # 2. Рамки, які додає сам агент (вони для моделі, не для людини).
    lines = [line for line in body.splitlines()
             if not _AGENT_FRAME_RE.match(line)]
    body = "\n".join(lines)
    # 3. JSON-об'єкти, схожі на виклик інструмента.
    for start, end in reversed(_balanced_json_spans(body)):
        chunk = body[start:end]
        if _looks_like_call_payload(chunk):
            body = body[:start] + body[end:]
    # 4. Порожні блоки коду, що лишились від вирізаного виклику.
    body = re.sub(r"```[a-zA-Z]*\s*```", "", body)
    # 5. Обірвана «огорожа» коду: модель починає блок (```json) і
    # обривається, не закривши його. У чаті це виглядало як окреме
    # повідомлення «```json» без жодного змісту (заміряно живим прогоном).
    #
    # Прибираємо ЛИШЕ непарну огорожу: закритий блок коду — це справжній
    # вміст відповіді, його чіпати не можна (інакше з відповіді зникає код,
    # який користувач просив показати).
    lines = body.splitlines()
    fences = [index for index, line in enumerate(lines)
              if line.strip().startswith("```")]
    if len(fences) % 2:
        # Остання огорожа не має пари — вона й обірвана.
        drop = fences[-1]
        lines = lines[:drop] + lines[drop + 1:]
        body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def looks_like_raw_protocol(text: str) -> bool:
    """Чи текст — переважно внутрішній протокол (таке не показуємо)."""
    body = (text or "").strip()
    if not body:
        return False
    lowered = body.lower()
    if any(marker.lower() in lowered for marker in _PROTOCOL_MARKERS[:6]):
        return True
    cleaned = strip_protocol(body)
    # Якщо після чистки лишилось менше третини — це був протокол.
    return bool(body) and len(cleaned) < len(body) * 0.34


def clean_for_chat(text: str, *, limit: int = 0) -> str:
    """Фінальна підготовка тексту відповіді перед показом.

    ``limit`` — м'яке обмеження довжини для вузьких місць (журнал, підказка).
    Обрізаємо по межі речення, а не посеред слова.
    """
    body = strip_protocol(text)
    if limit and len(body) > limit:
        cut = body[:limit]
        for marker in (". ", "! ", "? ", "\n"):
            position = cut.rfind(marker)
            if position > limit * 0.6:
                return cut[: position + 1].rstrip() + "…"
        return cut.rstrip() + "…"
    return body


# ─── Відповідь із результатів інструментів ──────────────────────────────────

#: Скільки рядків довгого результату показуємо у відповіді.
PREVIEW_LINES = 12

#: Скільки елементів списку показуємо.
LIST_LIMIT = 25


@dataclass
class ResponseDraft:
    """Чернетка відповіді: що сказати, які файли згадати, чи був успіх."""

    text: str = ""
    changed_files: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    ok: bool = True

    def is_empty(self) -> bool:
        return not self.text.strip()


def _is_metadata_line(line: str) -> bool:
    """Службовий рядок ``list_dir``, а не елемент переліку.

    ``list_dir`` починає вивід двома рядками-підсумками:

        . — 35 записів (файлів 16, тек 19)
        Підсумок за типами: .bat: 6, .py: 6, …

    Вони не є файлами, і якщо рахувати їх у співвідношенні «скільки рядків
    схожі на файл», перелік перестає розпізнаватись як перелік. Саме через
    це ``list_dir`` показувався код-блоком, обрізаним до 12 рядків — і назви
    файлів (``main.py``, ``blackchpok_ide/``) до відповіді не потрапляли.
    """
    clean = line.strip(" \t-•*+")
    if not clean:
        return True
    if clean.startswith(("Підсумок за типами", "Усього", "Разом")):
        return True
    # «. — 35 записів (файлів 16, тек 19)»: шлях, тире, слово «записів».
    return "—" in clean and "запис" in clean.lower()


def _file_like(line: str) -> bool:
    """Чи рядок схожий на шлях або ім'я файлу (для переліку)."""
    clean = line.strip(" \t-•*+")
    if not clean or len(clean) > 200:
        return False
    head = clean.split("  ")[0].strip()
    if head.endswith(("/", "\\")):
        return True
    if " (" in clean and clean.rstrip().endswith(")"):
        head = clean.split(" (")[0].strip()
    if "/" in head or "\\" in head:
        return True
    if " " in head:
        return False
    # Приховані файли (``.gitignore``, ``.env``): у них немає основи ДО
    # крапки, тому звичайна перевірка «stem.suffix» дає stem="" і файл не
    # визнається. Це не дрібниця: саме через такий рядок перелік у корені
    # проєкту не розпізнавався, і відповідь ставала код-блоком.
    #
    # Умова саме «крапка на початку + щось після неї», а НЕ «≥2 крапок»:
    # ``.gitignore`` має рівно одну крапку.
    if head.startswith(".") and len(head) > 1 and "/" not in head and "\\" not in head:
        return True
    stem, dot, suffix = head.rpartition(".")
    return bool(dot and stem and 1 <= len(suffix) <= 6 and suffix.isalnum())


def looks_like_file_list(body: str) -> bool:
    """Чи результат — перелік файлів (тоді краще маркований список).

    Той самий критерій, що й у ``agent.AgentRunner._looks_like_file_list``,
    але тут — частина відповіді, а не перевірка в циклі агента.
    """
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    # Службові рядки не беремо до уваги: вони не файли й не мусять
    # «псувати відсоток».
    entries = [line for line in lines[:60] if not _is_metadata_line(line)]
    if len(entries) < 2:
        return False
    sample = entries[:40]
    hits = sum(1 for line in sample if _file_like(line))
    return hits >= max(2, len(sample) - 2)


def _clean_list_item(line: str) -> str:
    """Прибрати службові хвости з елемента переліку файлів.

    ``list_dir`` віддає «ім'я  (70,468 B)»: розмір потрібен агенту, а
    людині в переліку він лише заважає.
    """
    clean = line.strip(" \t-•*+")
    if "  (" in clean:
        head, _, tail = clean.partition("  (")
        if tail.rstrip().endswith(")"):
            size = tail.rstrip()[:-1].strip()
            # Лишаємо розмір у дужках лише якщо він справді інформативний.
            if size and any(char.isdigit() for char in size):
                return f"{head.strip()}  ·  {size}"
    return clean


def _format_result(observation: Observation, *, limit: int = LIST_LIMIT) -> str:
    """Один результат → людський фрагмент markdown."""
    title = observation.name or "інструмент"
    if not observation.ok:
        # Невдача — цитатою: причина мусить бути ВИДНО, але не як «стіна»
        # службового тексту. Цитата підказує, що це слова інструмента.
        reason = (observation.error or observation.output or "").strip()
        first = next((line.strip() for line in reason.splitlines() if line.strip()), "")
        if len(first) > 300:
            first = first[:299] + "…"
        return (f"**{title}** — не вдалось:\n\n> {first}" if first
                else f"**{title}** — не вдалось.")
    body = (observation.output or "").strip()
    if not body:
        return f"**{title}** — готово."
    lines = body.splitlines()
    if looks_like_file_list(body):
        # Службові рядки (підсумок «. — 35 записів», «Підсумок за типами»)
        # виносимо в підзаголовок, а не пунктами списку: це не файли, і
        # перелік з них починатись не має.
        meta = [line.strip() for line in lines if _is_metadata_line(line)]
        entries = [_clean_list_item(line) for line in lines
                   if line.strip() and not _is_metadata_line(line)]
        items = entries[:limit]
        shown = "\n".join(f"- {item}" for item in items)
        summary = meta[0] if meta else ""
        more = len(entries) - len(items)
        head = f"**{title}**" + (f" · {summary}" if summary else "")
        return head + f"\n\n{shown}" + (f"\n\n… ще {more}" if more > 0 else "")
    if len(lines) <= 3 and len(body) <= 240:
        single = " ".join(line.strip() for line in lines)
        return f"**{title}** · {single}"
    head = "\n".join(lines[:PREVIEW_LINES])
    tail = f"\n… (усього {len(lines)} рядків)" if len(lines) > PREVIEW_LINES else ""
    return f"**{title}**\n\n```\n{head}{tail}\n```"


def answer_from_observations(
    observations: Sequence[Observation],
    *,
    header: str = "",
) -> ResponseDraft:
    """Зібрати відповідь із спостережень, коли модель промовчала.

    Це не «заглушка»: тут справжні результати справжніх викликів,
    перекладені зі службового формату в зрозумілий текст.
    """
    rows = [item for item in observations if item is not None and not item.duplicate]
    if not rows:
        return ResponseDraft(text="", ok=False)

    changed: list[str] = []
    checks: list[str] = []
    unresolved: list[str] = []
    parts: list[str] = []

    for item in rows:
        if item.ok and item.name in ("write_file", "edit_file", "append_file"):
            match = re.search(r"([\w./\\-]+\.[A-Za-z0-9]{1,8})", item.output or "")
            name = match.group(1).replace("\\", "/") if match else ""
            if name and name not in changed:
                changed.append(name)
        if item.ok and item.name in ("python_check", "run_command"):
            first = next((line.strip() for line in (item.output or "").splitlines()
                          if line.strip()), "")
            if first:
                checks.append(clean_for_chat(first, limit=120))
        if not item.ok:
            unresolved.append(f"{item.name}: {clean_for_chat(item.error or '', limit=200)}")
        fragment = _format_result(item)
        if fragment:
            parts.append(fragment)

    if not parts:
        return ResponseDraft(text="", changed_files=changed, checks=checks, ok=False)

    lines: list[str] = []
    if header:
        lines.append(header)
    else:
        # Заголовок мусить відповідати ФАКТУ. Раніше крок, де ВСІ виклики
        # впали, починався зі слова «Готово», і користувач читав «Готово» з
        # переліком помилок нижче. Тепер це «Не вдалося», а частковий успіх
        # чесно називається «Виконано частково».
        any_ok = any(item.ok for item in rows)
        all_ok = all(item.ok for item in rows)
        if not any_ok:
            lines.append("Не вдалося виконати.")
        elif not all_ok:
            lines.append("Виконано частково.")
        else:
            lines.append("Готово. Результат:" if len(parts) == 1
                         else "Готово. Результати:")
    lines.append("")
    lines.append("\n\n".join(parts))

    if changed:
        lines += ["", "**Змінено файли:** " + ", ".join(f"`{name}`" for name in changed)]
    if checks:
        lines += ["", "**Перевірки:** " + "; ".join(checks)]
    if unresolved:
        lines += ["", "**Що не вдалося:**"]
        lines += [f"- {item}" for item in unresolved]

    return ResponseDraft(
        text="\n".join(lines).strip(),
        changed_files=changed,
        checks=checks,
        unresolved=unresolved,
        ok=any(item.ok for item in rows),
    )


# ─── Підсумкова відповідь ───────────────────────────────────────────────────

#: Ознаки обіцянки замість дії (короткі репліки моделі).
_PROMISE_MARKERS: tuple[str, ...] = (
    "спробую", "перевірю", "зараз ", "зроблю", "виправлю", "перероблю",
    "пошукаю", "подивлюсь", "подивлюся", "напишу", "внесу", "запущу",
    "let me", "i will", "i'll", "trying", "attempting",
)


#: Ствердження про ВЖЕ виконане — без доказу це така сама обіцянка.
#: «Я створив файл app.py і все працює» звучить як звіт, але якщо жоден
#: інструмент не викликався, файлу на диску немає. Користувач шукав його
#: й не знаходив — саме тому ці звороти перевіряються нарівні з майбутнім.
_DONE_MARKERS: tuple[str, ...] = (
    "я створив", "я створила", "я створив", "я додав", "я додала",
    "я виправив", "я виправила", "я змінив", "я змінила", "я написав",
    "я написала", "я видалив", "я видалила", "я запустив", "я запустила",
    "я перевірив", "я перевірила", "я встановив", "я встановила",
    "файл створено", "файл записано", "файл оновлено", "успішно створено",
    "успішно виконано", "все працює", "усе працює", "готово, файл",
    "i created", "i added", "i fixed", "i updated", "i wrote",
    "successfully created", "it works",
)


def promises_action(text: str) -> bool:
    """Чи це лише обіцянка дії або звіт без доказу.

    Довга відповідь із кодом або списком — це вже результат, навіть якщо
    в ній трапляється «перевірю». Обіцянка — коротка репліка без доказу.
    """
    body = (text or "").strip()
    if not body or len(body) > 400:
        return False
    if "```" in body or body.startswith(("-", "•", "1.", "2.", "**")):
        return False
    low = body.lower()
    return any(marker in low for marker in _PROMISE_MARKERS + _DONE_MARKERS)


def evidence_lines(observations: Sequence[Observation]) -> list[str]:
    """Рядки-докази: що САМЕ було виконано (для «не вигадуй успіх»)."""
    lines: list[str] = []
    for item in observations or ():
        if item is None or item.duplicate:
            continue
        status = "✓" if item.ok else "✗"
        verb = item.name or "дія"
        first = next((line.strip() for line in
                      (item.output if item.ok else item.error).splitlines()
                      if line.strip()), "")
        lines.append(f"{status} {verb}" + (f" — {clean_for_chat(first, limit=100)}"
                                          if first else ""))
    return lines


def final_answer(
    model_text: str,
    observations: Sequence[Observation],
    *,
    fallback: str = "",
    ask_model: bool = False,
) -> str:
    """Зібрати фінальну відповідь користувачу з того, що реально є.

    Порядок рішень:

    1. текст моделі, якщо він не порожній, не протокол і не обіцянка;
    2. інакше — відповідь із справжніх результатів інструментів;
    3. інакше — чесне пояснення, чому результату немає (``fallback``).

    ``ask_model`` лишається в сигнатурі для сумісності з викликами, які
    вже передають цей прапорець: рішення про повторний запит ухвалює
    цикл агента, а не форматування.
    """
    del ask_model
    cleaned = clean_for_chat(model_text)
    # ── Дії впали — слово моделі не робить їх успішними ────────────────────
    # Раніше перевірявся лише «протокол» і «обіцянка», а провал інструмента
    # не враховувався: на «Готово, файл створено» з `write_file → Відмовлено
    # в доступі` користувач бачив саме «Готово». Тепер провал перекриває
    # будь-яке твердження моделі про успіх.
    rows = [item for item in observations or () if item is not None]
    failed = [item for item in rows if not item.ok and not item.duplicate]
    produced = [item for item in rows if item.ok and item.output.strip()]
    if failed and not produced:
        return explain_failure(cleaned, observations)
    if cleaned and not looks_like_raw_protocol(cleaned) and not promises_action(cleaned):
        return cleaned
    draft = answer_from_observations(observations)
    if draft.text:
        return draft.text
    if cleaned:
        # Модель лише пообіцяла — але її слова можна показати як контекст
        # ТІЛЬКИ разом із чесним поясненням, що дії не було.
        return explain_failure(cleaned, observations)
    if fallback:
        return cleaned if not cleaned else fallback
    return explain_failure("", observations)


_TRACEBACK_RE = re.compile(
    r"^\s*(?:Traceback \(most recent call last\)|File \"[^\"]+\", line \d+|"
    r"\s+[\w.]+(?:Error|Exception|Warning):|During handling of the above)")


def _human_reason(reason: str) -> str:
    """Причина людською мовою: стектрейс згортаємо до суті.

    Користувачу не потрібні «File "x.py", line 12» — потрібна суть. Раніше
    стектрейс цілком потрапляв у відповідь, і замість причини людина
    читала п'ять рядків службового тексту.
    """
    text = (reason or "").strip()
    if not text:
        return "причина не вказана"
    if "Traceback (most recent call last)" not in text:
        return text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # 1. Рядок-виняток: «ValueError: щось» — без «File…» і без «Traceback…».
    for line in reversed(lines):
        if line.startswith(("Traceback", "File ", "During handling", "The above")):
            continue
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Exit)\b", line):
            return line
    # 2. Будь-який останній змістовний рядок.
    for line in reversed(lines):
        if not line.startswith(("Traceback", "File ", "During handling", "The above")):
            return line
    return "внутрішня помилка інструмента"


def explain_failure(model_text: str, observations: Sequence[Observation]) -> str:
    """Чесна відповідь, коли результату немає: що сталося й що робити."""
    rows = [item for item in observations or () if item is not None]
    failed = [item for item in rows if not item.ok and not item.duplicate]
    lines: list[str] = []
    if model_text:
        lines.append("Модель зупинилась на поясненні замість дії:")
        lines.append("")
        lines.append(f"> {clean_for_chat(model_text, limit=300)}")
        lines.append("")
    if failed:
        lines.append("Ці дії не вдалися:")
        for item in failed[:5]:
            reason = next((line.strip() for line in
                           (item.error or "").splitlines() if line.strip()), "")
            reason = _human_reason(reason)
            lines.append(f"- **{item.name}** — {clean_for_chat(reason, limit=200)}")
        lines.append("")
    if not rows:
        lines += ["Жоден інструмент не був викликаний, тому на диску нічого не "
                  "змінилося.", ""]
    lines += [
        "Що можна зробити:",
        "- сформулювати завдання конкретніше (що саме й де змінити);",
        "- перевірити, чи підключені потрібні інструменти;",
        "- вибрати іншу модель у шапці.",
    ]
    return "\n".join(lines).strip()


def clarifying_question(frame: Any) -> str:
    """Одне конкретне питання, коли справді бракує інформації.

    Правило: одне питання й варіанти відповіді, без «розкажіть детальніше».
    """
    missing = list(getattr(frame, "missing_information", ()) or ())
    files = list(getattr(frame, "referenced_files", ()) or ())
    features = list(getattr(frame, "referenced_features", ()) or ())
    risk = str(getattr(frame, "risk_level", "low"))
    goal = str(getattr(frame, "primary_goal", "") or "")

    if missing:
        what = missing[0]
        return (f"Уточніть, будь ласка, одне: {what}?\n\n"
                "Наприклад: назвіть файл або екран — і я одразу почну.")
    if risk in ("high", "critical") and not files and not features:
        subject = goal or "цю дію"
        return (f"Це незворотна дія: {subject}. Назвіть, будь ласка, що саме "
                "видалити або змінити — і я зроблю це точково.")
    return ""


def preview_of(text: str, limit: int = 120) -> str:
    """Один рядок для журналу роботи (без розмітки й без переносів)."""
    body = markdown_view.plain_text(clean_for_chat(text))
    body = " ".join(body.split())
    return body if len(body) <= limit else body[: limit - 1] + "…"


def as_json_note(observations: Sequence[Observation]) -> str:
    """Технічний підсумок для traces (НЕ для показу користувачу)."""
    rows: list[dict[str, Any]] = []
    for item in observations or ():
        if item is None:
            continue
        rows.append({
            "tool": item.name,
            "ok": item.ok,
            "attempts": item.attempts,
            "duration": round(item.duration, 3),
            "duplicate": item.duplicate,
            "rejected": item.rejected,
            "suspicious": list(item.suspicious),
        })
    return json.dumps(rows, ensure_ascii=False)


def summarise_checks(observations: Iterable[Observation]) -> str:
    """Рядок «що перевірено» для фінальної відповіді."""
    names: list[str] = []
    for item in observations or ():
        if item is None or not item.ok:
            continue
        if item.name in ("python_check", "run_command") and item.name not in names:
            names.append(item.name)
    return ", ".join(names)
