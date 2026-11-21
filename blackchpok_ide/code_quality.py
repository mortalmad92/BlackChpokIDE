"""Практики, які реально підвищують якість коду від ЛОКАЛЬНИХ моделей.

Модуль навмисно самодостатній (тільки stdlib), щоб його можна було
підключити в llm_client / stream_apply / task_executor без ризику
циклічних імпортів.

Що тут є:
  PRACTICES            - короткий чекліст (що саме допомагає і чому)
  sampling(kind)       - рекомендовані параметри семплінгу для коду
  system_prompt(...)   - системний промпт, заточений під малі моделі
  code_messages(...)   - складання запиту: карта репо + файли + формат правок
  EDIT_SPEC            - формат SEARCH/REPLACE (стабільніше за повний файл)
  parse_edits(text)    - витягнути блоки правок з відповіді моделі
  apply_edits(src, ed) - застосувати правки й повернути список проблем
  verify_python(src)   - швидка перевірка синтаксису без запису на диск
  build_report()       - текстовий звіт для панелі/логів

Ключова ідея: локальна модель помиляється не стільки в логіці, скільки в
ОБСЯЗІ (переписує файл цілком і губить код) і у ФОРМАТІ (ламає JSON/лапки).
Тому: малий промпт + явний формат правок + машинна перевірка після кожної
правки + повтор тільки з текстом помилки.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- практики

#: Кожен пункт: (id, що робити, навіщо/джерело)
PRACTICES: Tuple[Tuple[str, str, str], ...] = (
    (
        "small_prompt",
        "Тримати системний промпт коротким: роль, формат відповіді, 5-8 правил.",
        "Малі моделі (7-14B) губляться в довгих інструкціях; зайвий текст "
        "з'їдає контекст і підвищує плутанину форматів.",
    ),
    (
        "edit_not_rewrite",
        "Просити точкові SEARCH/REPLACE-правки, а не файл цілком.",
        "Генерація цілого файлу на 500+ рядків майже завжди обривається або "
        "мовчки видаляє сусідній код. Правка в 10 рядків - надійна.",
    ),
    (
        "repo_map",
        "Давати карту репо (файли + сигнатури функцій/класів), а не весь код.",
        "Дешевий RAG на AST: модель бачить, де що лежить, і не вигадує "
        "неіснуючі модулі (типова причина 'файлу немає на диску').",
    ),
    (
        "skeletons",
        "У контекст вставляти скелет файлу (def/class без тіл) + тіло лише "
        "тих функцій, які змінюємо.",
        "Зменшує контекст у 3-10 разів, при цьому зберігає контракти.",
    ),
    (
        "temperature_low",
        "Для коду: temperature 0.0-0.2, top_p 0.9, повтор з тим самим seed.",
        "Код - це задача з вузьким правильним розв'язком; високий T додає "
        "вигадані API. Повтор із тим самим seed дає відтворюваність.",
    ),
    (
        "stop_sequences",
        "Додавати stop-послідовності формату (наприклад '</edit>', '````').",
        "Модель перестає 'домальовувати' пояснення після коду - менше сміття "
        "в парсингу tool-call.",
    ),
    (
        "grammar",
        "Для tool-call/JSON - граматичне обмеження декодування (GBNF, "
        "outlines, llama.cpp grammar, SynCode).",
        "Синтаксично валідний вивід без повторів: див. SynCode та огляди "
        "constrained decoding.",
    ),
    (
        "compile_gate",
        "Після кожної правки - compile()/ast.parse() і, для Python, швидкий "
        "імпорт-чек; при помилці показати моделі ТІЛЬКИ трейсбек.",
        "Машинна перевірка замінює довіру до моделі; цикл 'помилка -> правка' "
        "з 1-2 ітерацій виправляє більшість дефектів.",
    ),
    (
        "one_step",
        "Один крок = одна дія (один файл / одна функція), з явним 'готово'.",
        "Багатокрокові плани в малих моделях розсипаються; вузький крок "
        "тримає фокус.",
    ),
    (
        "anchors",
        "У SEARCH-блоці вимагати 3+ рядки унікального контексту й точні "
        "відступи.",
        "Менше неоднозначних збігів при застосуванні патча; відсіює правки, "
        "що 'схожі, але не там'.",
    ),
    (
        "retrieval_error_log",
        "Перед генерацією підкидати минулі помилки по цих файлах з журналу "
        "спроб (evidence/trace).",
        "Модель не повторює ту саму помилку в межах сесії - найдешевший "
        "приріст якості.",
    ),
    (
        "tests_first",
        "Для нових функцій просити спершу сигнатуру + тест, тіло - потім.",
        "Тест фіксує контракт і дає автоматичний критерій 'готово'.",
    ),
    (
        "quant_choice",
        "Тримати модель у Q4_K_M..Q6_K, kv-cache q8, context >= 8k для "
        "патчів; не стискати до Q2-Q3.",
        "Нижче Q4 різко падає синтаксична акуратність - саме те, що критичне "
        "для редагування коду.",
    ),
)

#: Параметри семплінгу за типом роботи.
_SAMPLING: Dict[str, Dict[str, object]] = {
    "edit": {"temperature": 0.1, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.05},
    "new_file": {"temperature": 0.2, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.05},
    "explain": {"temperature": 0.4, "top_p": 0.95, "top_k": 60, "repeat_penalty": 1.0},
    "test": {"temperature": 0.15, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.05},
}

#: Стоп-послідовності, які обривають «балаканину» після коду.
STOP_SEQUENCES: Tuple[str, ...] = (
    "</edit>",
    "</file>",
    "</patch>",
    "\n```\n\n",
    "<|im_end|>",
)


def sampling(kind: str = "edit") -> Dict[str, object]:
    """Рекомендовані параметри семплінгу (копія, щоб можна було міняти)."""
    return dict(_SAMPLING.get(kind, _SAMPLING["edit"]))


# ---------------------------------------------------------------- промпт

EDIT_SPEC = """Формат відповіді - ТІЛЬКИ блоки правок, без пояснень:

<edit path="relative/path.py">
<<<<<<< SEARCH
точний фрагмент файлу (3+ рядки, з відступами як в оригіналі)
=======
новий фрагмент
>>>>>>> REPLACE
</edit>

Правила:
- SEARCH мусить точно існувати у файлі й бути унікальним.
- Не скорочуй код коментарями на кшталт "# ... решта без змін".
- Не змінюй рядки, яких не стосується задача.
- Якщо потрібен новий файл - один блок з порожнім SEARCH.
- Після останнього блоку напиши OK."""


def system_prompt(model_hint: str = "small") -> str:
    """Короткий системний промпт, заточений під малі локальні моделі."""
    base = (
        "Ти — інженер, що редагує реальний репозиторій. "
        "Відповідай мінімальними точковими змінами. "
        "Не вигадуй файлів, функцій і бібліотек, яких немає в контексті. "
        "Не переписуй файл цілком, якщо просять змінити фрагмент. "
        "Спершу перевір синтаксис подумки, потім віддай правку. "
        "Пиши код без пояснень, коментарі - тільки там, де логіка неочевидна."
    )
    if model_hint == "tiny":
        base += (
            " Ти мала модель: працюй ЛИШЕ з наданим фрагментом, "
            "не узагальнюй і не додавай нових функцій понад завдання."
        )
    return base + "\n\n" + EDIT_SPEC


def _tree_line(path: str, source: str, limit: int = 60) -> str:
    """Один рядок карти: import + сигнатури верхнього рівня."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return f"{path}: <не парситься>"
    parts: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(("async def " if isinstance(node, ast.AsyncFunctionDef) else "def ") + node.name)
        elif isinstance(node, ast.ClassDef):
            parts.append("class " + node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    parts.append(tgt.id)
    parts = parts[:limit]
    return f"{path}: " + (", ".join(parts) if parts else "<порожньо>")


def repo_map(files: Dict[str, str], max_files: int = 40) -> str:
    """Дешевий RAG: карта 'файл -> сигнатури' без повних тіл."""
    out = [_tree_line(p, s) for p, s in list(files.items())[:max_files]]
    return "\n".join(out)


def skeleton(source: str, keep_bodies: Iterable[str] = ()) -> str:
    """Скелет файлу: сигнатури без тіл; тіла лише для вказаних імен."""
    keep = set(keep_bodies)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    lines = source.splitlines()
    out: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno - 1
            head = lines[start]
            name = getattr(node, "name", "")
            if name in keep:
                end = getattr(node, "end_lineno", start + 1)
                out.extend(lines[start:end])
            else:
                indent = re.match(r"\s*", head).group(0)
                out.extend([head, indent + "    ..."])
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(lines[node.lineno - 1])
    return "\n".join(out)


def code_messages(
    task: str,
    files: Optional[Dict[str, str]] = None,
    *,
    map_text: Optional[str] = None,
    known_errors: Sequence[str] = (),
    model_hint: str = "small",
) -> List[Dict[str, str]]:
    """Скласти messages для локальної моделі: мінімум тексту, максимум фактів."""
    files = files or {}
    ctx: List[str] = []
    if map_text:
        ctx.append("КАРТА РЕПО:\n" + map_text)
    elif files:
        ctx.append("КАРТА РЕПО:\n" + repo_map(files))
    for path, src in files.items():
        ctx.append(f"ФАЙЛ {path}:\n```python\n{src}\n```")
    if known_errors:
        ctx.append("МИНУЛІ ПОМИЛКИ (не повторюй):\n" + "\n".join(f"- {e}" for e in known_errors))
    user = "ЗАВДАННЯ: " + task
    if ctx:
        user += "\n\n" + "\n\n".join(ctx)
    return [
        {"role": "system", "content": system_prompt(model_hint)},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------- правки

_EDIT_RE = re.compile(
    r'<edit\s+path="(?P<path>[^"]+)"\s*>\s*'
    r"<<<<<<<\s*SEARCH\s*\n(?P<search>.*?)\n?"
    r"=======\s*\n(?P<replace>.*?)\n?"
    r">>>>>>>\s*REPLACE\s*</edit>",
    re.S,
)


@dataclass
class Edit:
    path: str
    search: str
    replace: str
    raw: str = ""


@dataclass
class ApplyResult:
    ok: bool = True
    source: str = ""
    problems: List[str] = field(default_factory=list)


def parse_edits(text: str) -> List[Edit]:
    """Витягнути SEARCH/REPLACE-блоки. Толерантно до зайвих ```-огорож."""
    clean = re.sub(r"^\s*```[a-zA-Z0-9_+-]*\s*$", "", text, flags=re.M)
    edits: List[Edit] = []
    for m in _EDIT_RE.finditer(clean):
        edits.append(
            Edit(
                path=m.group("path").strip(),
                search=m.group("search"),
                replace=m.group("replace"),
                raw=m.group(0),
            )
        )
    return edits


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip("\n")


def apply_edits(source: str, edits: Sequence[Edit]) -> ApplyResult:
    """Застосувати правки по черзі; повернути проблеми замість винятків."""
    cur = source
    problems: List[str] = []
    for i, ed in enumerate(edits, 1):
        if not ed.search.strip():
            cur = ed.replace if ed.replace.endswith("\n") else ed.replace + "\n"
            continue
        needle = _normalize(ed.search)
        hay = _normalize(cur)
        if hay.count(needle) == 1:
            cur = hay.replace(needle, _normalize(ed.replace))
            continue
        if hay.count(needle) > 1:
            problems.append(f"правка {i} ({ed.path}): SEARCH не унікальний ({hay.count(needle)} збігів)")
            continue
        close = difflib.get_close_matches(needle, hay.split("\n\n"), n=1, cutoff=0.6)
        problems.append(
            f"правка {i} ({ed.path}): SEARCH не знайдено"
            + (f"; найближчий фрагмент: {close[0][:80]!r}" if close else "")
        )
    ok = not problems
    if ok and edits and cur.strip():
        check = verify_python(cur) if edits[0].path.endswith(".py") else (True, "")
        if not check[0]:
            problems.append("синтаксис після правок: " + check[1])
            ok = False
    return ApplyResult(ok=ok, source=cur, problems=problems)


def verify_python(source: str) -> Tuple[bool, str]:
    """compile() без запису на диск; повертає (ok, повідомлення)."""
    try:
        compile(source, "<model_output>", "exec")
        return True, ""
    except SyntaxError as exc:
        return False, f"{exc.msg} (рядок {exc.lineno})"
    except ValueError as exc:  # напр. нульові байти
        return False, str(exc)


def repair_prompt(task: str, problems: Sequence[str], bad: str) -> List[Dict[str, str]]:
    """Другий шанс: показати моделі ЛИШЕ помилки й попросити переписати правку."""
    return [
        {"role": "system", "content": system_prompt("tiny")},
        {
            "role": "user",
            "content": (
                "ЗАВДАННЯ: " + task
                + "\n\nТВОЯ ПОПЕРЕДНЯ ВІДПОВІДЬ:\n" + bad[:1500]
                + "\n\nПРОБЛЕМИ:\n" + "\n".join(f"- {p}" for p in problems)
                + "\n\nВиправ рівно ці проблеми. Формат: ті самі блоки <edit>."
            ),
        },
    ]


# ---------------------------------------------------------------- звіт

def build_report() -> str:
    """Короткий чекліст для панелі налаштувань / логів."""
    lines = ["ЯК ПІДВИЩИТИ ЯКІСТЬ КОДУ ВІД ЛОКАЛЬНОЇ МОДЕЛІ:"]
    for i, (pid, what, why) in enumerate(PRACTICES, 1):
        lines.append(f"{i:2d}. [{pid}] {what}")
        lines.append(f"    -> {why}")
    lines.append("")
    lines.append("Семплінг: " + json.dumps(sampling("edit"), ensure_ascii=False))
    lines.append("Стопи: " + ", ".join(STOP_SEQUENCES))
    return "\n".join(lines)


def _selftest() -> int:
    src = 'def a(x):\n    return x + 1\n\n\ndef b():\n    return a(1)\n'
    answer = (
        "```\n"
        '<edit path="m.py">\n'
        "<<<<<<< SEARCH\n"
        "def a(x):\n"
        "    return x + 1\n"
        "=======\n"
        "def a(x):\n"
        "    return x + 2\n"
        ">>>>>>> REPLACE\n"
        "</edit>\n```"
    )
    edits = parse_edits(answer)
    assert len(edits) == 1, edits
    res = apply_edits(src, edits)
    assert res.ok, res.problems
    assert "x + 2" in res.source
    bad = ApplyResult()
    bad = apply_edits(src, [Edit("m.py", "def z():\n    pass", "def z():\n    return 0")])
    assert not bad.ok and bad.problems
    assert verify_python("def f(:\n")[0] is False
    assert "pass" in skeleton("def f():\n    pass\n", ["f"])
    assert "..." in skeleton("def f():\n    return 1\n", [])
    assert "small_prompt" in build_report()
    print("selftest OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--report" in sys.argv:
        print(build_report())
    assert "pass" in skeleton("def f():\n    pass\n", ["f"])
    assert "..." in skeleton("def f():\n    return 1\n", [])
    assert "small_prompt" in build_report()
    else:
        raise SystemExit(_selftest())
