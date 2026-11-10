"""Сховище справжніх прогонів агента й метрики оцінювання.

Що тут зберігається і чого тут **немає**:

* зберігаються: тип запиту, розпізнаний намір, вибрані інструменти,
  валідність аргументів, результати, перевірки, фінальна відповідь,
  тривалість, кількість токенів;
* НЕ зберігається: прихований ланцюг міркувань моделі. Це і вимога
  безпеки, і практичність — міркування величезні й мінливі, а рішення
  й наслідки відтворювані.

Навіщо: без цього неможливо відповісти на питання «стало краще чи ні».
Метрики рахуються з тих самих подій, які агент і так генерує, тож
вимірювання не додає жодного зайвого запиту до моделі.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

LOG = logging.getLogger("blackchpok.traces")

__all__ = [
    "METRIC_HELP",
    "TurnTrace",
    "TraceStore",
    "aggregate",
    "format_report",
    "metric_values",
]

#: Скільки останніх прогонів тримаємо на диску.
KEEP_TRACES = 400

#: Версія формату — щоб старі файли читались і не ламали статистику.
FORMAT_VERSION = 1


@dataclass
class TurnTrace:
    """Один хід агента: від запиту користувача до фінальної відповіді."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    #: Розпізнаний намір (тип із :mod:`intent_engine`).
    intent_type: str = ""
    #: Мова запиту (uk/ru/en/mixed) — потрібна для метрик українською.
    language: str = "uk"
    #: Чи це продовження попереднього завдання.
    continuation: bool = False
    #: Скільки разів довелось уточнювати й чи уточнення було доречним.
    asked_clarification: bool = False
    clarification_useful: bool | None = None
    #: Інструменти у порядку виклику.
    tools: list[str] = field(default_factory=list)
    #: Скільки викликів відхилено через неправильні аргументи.
    rejected_calls: int = 0
    #: Скільки викликів впало.
    failed_calls: int = 0
    #: Скільки викликів повторили.
    retried_calls: int = 0
    #: Файли, які справді змінились.
    changed_files: list[str] = field(default_factory=list)
    #: Чи агент оголосив успіх без жодного доказу.
    false_success: bool = False
    #: Чи модель вигадала інструмент, якого немає.
    hallucinated_tool: bool = False
    #: Відповідь пройшла перевірку на «людськість» (текст, не протокол).
    human_readable: bool = True
    #: Чи був у відповіді markdown-код окремим блоком.
    has_code_block: bool = False
    #: Чи потрапив у відповідь сирий протокол.
    leaked_protocol: bool = False
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration: float = 0.0
    #: Оцінка користувача, якщо він її поставив (1..5 або "ok"/"bad").
    user_rating: str = ""
    #: Коротка мета словами (для відбору прикладів).
    goal: str = ""
    #: Стисла версія фінальної відповіді (без коду — він буває величезний).
    answer_head: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "id": self.id,
            "started_at": self.started_at,
            "intent_type": self.intent_type,
            "language": self.language,
            "continuation": self.continuation,
            "asked_clarification": self.asked_clarification,
            "clarification_useful": self.clarification_useful,
            "tools": list(self.tools),
            "rejected_calls": self.rejected_calls,
            "failed_calls": self.failed_calls,
            "retried_calls": self.retried_calls,
            "changed_files": list(self.changed_files),
            "false_success": self.false_success,
            "hallucinated_tool": self.hallucinated_tool,
            "human_readable": self.human_readable,
            "has_code_block": self.has_code_block,
            "leaked_protocol": self.leaked_protocol,
            "steps": self.steps,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "duration": round(self.duration, 3),
            "user_rating": self.user_rating,
            "goal": self.goal,
            "answer_head": self.answer_head[:600],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "TurnTrace | None":
        if not isinstance(data, dict):
            return None
        try:
            trace = cls(
                id=str(data.get("id") or uuid.uuid4().hex[:12]),
                started_at=float(data.get("started_at") or time.time()),
                intent_type=str(data.get("intent_type") or ""),
                language=str(data.get("language") or "uk"),
                continuation=bool(data.get("continuation")),
                asked_clarification=bool(data.get("asked_clarification")),
                rejected_calls=int(data.get("rejected_calls") or 0),
                failed_calls=int(data.get("failed_calls") or 0),
                retried_calls=int(data.get("retried_calls") or 0),
                false_success=bool(data.get("false_success")),
                hallucinated_tool=bool(data.get("hallucinated_tool")),
                human_readable=bool(data.get("human_readable", True)),
                has_code_block=bool(data.get("has_code_block")),
                leaked_protocol=bool(data.get("leaked_protocol")),
                steps=int(data.get("steps") or 0),
                prompt_tokens=int(data.get("prompt_tokens") or 0),
                completion_tokens=int(data.get("completion_tokens") or 0),
                duration=float(data.get("duration") or 0.0),
                user_rating=str(data.get("user_rating") or ""),
                goal=str(data.get("goal") or ""),
                answer_head=str(data.get("answer_head") or ""),
            )
        except (TypeError, ValueError):
            return None
        useful = data.get("clarification_useful")
        trace.clarification_useful = useful if isinstance(useful, bool) else None
        for key, attr in (("tools", "tools"), ("changed_files", "changed_files")):
            value = data.get(key)
            if isinstance(value, list):
                setattr(trace, attr, [str(item) for item in value if str(item)])
        return trace


# ─── Метрики ────────────────────────────────────────────────────────────────

#: Що саме означає кожна метрика — щоб звіт не був ребусом.
METRIC_HELP: dict[str, str] = {
    "tool_selection_accuracy": (
        "частка ходів, де жоден виклик не був відхилений і не вигаданий"),
    "tool_argument_validity": (
        "частка викликів із правильними аргументами"),
    "tool_execution_success": (
        "частка викликів, що завершились успішно"),
    "false_success_rate": (
        "частка ходів, де успіх оголошено без жодної зміни файлів"),
    "hallucinated_tool_rate": (
        "частка ходів із викликом неіснуючого інструмента"),
    "human_readability": (
        "частка відповідей без сирого протоколу й без обіцянок замість дії"),
    "clarification_precision": (
        "частка уточнень, які виявились доречними"),
    "clarification_recall": (
        "частка ходів, де уточнення було потрібне й було поставлене"),
    "avg_steps": "середня кількість кроків циклу на хід",
    "avg_tokens": "середня кількість токенів на хід",
    "avg_duration": "середня тривалість ходу в секундах",
}


def _ratio(part: int, total: int) -> float:
    return round(part / total, 3) if total else 0.0


def metric_values(traces: Sequence[TurnTrace]) -> dict[str, Any]:
    """Порахувати метрики зі збережених ходів.

    Усі метрики мають ЗРОЗУМІЛИЙ чисельник і знаменник; жодна не
    «покращується» сама по собі.
    """
    rows = [item for item in traces or () if item is not None]
    total = len(rows)
    if not total:
        return {key: 0.0 for key in METRIC_HELP}

    calls = sum(len(item.tools) for item in rows)
    rejected = sum(item.rejected_calls for item in rows)
    hallucinated = sum(1 for item in rows if item.hallucinated_tool)
    failed = sum(item.failed_calls for item in rows)
    clean_selection = sum(
        1 for item in rows if not item.hallucinated_tool and not item.rejected_calls)
    readable = sum(1 for item in rows if item.human_readable and not item.leaked_protocol)
    false_success = sum(1 for item in rows if item.false_success)
    asked = [item for item in rows if item.asked_clarification]
    useful = [item for item in asked if item.clarification_useful]
    needed = [item for item in rows if item.clarification_useful is not None]
    needed_true = [item for item in needed if item.clarification_useful]

    return {
        "tool_selection_accuracy": _ratio(clean_selection, total),
        "tool_argument_validity": _ratio(max(0, calls - rejected), calls),
        "tool_execution_success": _ratio(max(0, calls - failed), calls),
        "false_success_rate": _ratio(false_success, total),
        "hallucinated_tool_rate": _ratio(hallucinated, total),
        "human_readability": _ratio(readable, total),
        "clarification_precision": _ratio(len(useful), len(asked)),
        "clarification_recall": _ratio(
            sum(1 for item in needed_true if item.asked_clarification),
            len(needed_true)),
        "avg_steps": round(sum(item.steps for item in rows) / total, 2),
        "avg_tokens": round(
            sum(item.prompt_tokens + item.completion_tokens for item in rows) / total, 1),
        "avg_duration": round(sum(item.duration for item in rows) / total, 2),
    }


def aggregate(traces: Sequence[TurnTrace]) -> dict[str, Any]:
    """Метрики + розподіл за намірами й мовами (для порівняння конфігурацій)."""
    values = metric_values(traces)
    by_intent: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for item in traces or ():
        if item is None:
            continue
        by_intent[item.intent_type or "?"] = by_intent.get(item.intent_type or "?", 0) + 1
        by_language[item.language or "?"] = by_language.get(item.language or "?", 0) + 1
    return {
        "turns": len(traces or ()),
        "metrics": values,
        "by_intent": dict(sorted(by_intent.items())),
        "by_language": dict(sorted(by_language.items())),
    }


def format_report(summary: Mapping[str, Any]) -> str:
    """Звіт українською — те, що можна показати людині й покласти в docs."""
    metrics = summary.get("metrics") or {}
    lines = [f"Ходів у вибірці: {summary.get('turns', 0)}", ""]
    for key, help_text in METRIC_HELP.items():
        value = metrics.get(key, 0)
        if isinstance(value, float) and value <= 1.0 and key.startswith(
                ("tool_", "false_", "hallucinated_", "human_", "clarification_")):
            shown = f"{value * 100:.1f}%"
        else:
            shown = str(value)
        lines.append(f"- {key}: {shown} — {help_text}")
    by_intent = summary.get("by_intent") or {}
    if by_intent:
        lines += ["", "За намірами:"]
        lines += [f"- {name}: {count}" for name, count in by_intent.items()]
    by_language = summary.get("by_language") or {}
    if by_language:
        lines += ["", "За мовами:"]
        lines += [f"- {name}: {count}" for name, count in by_language.items()]
    return "\n".join(lines)


# ─── Сховище ────────────────────────────────────────────────────────────────

class TraceStore:
    """Файлове сховище прогонів (JSON Lines, стійке до пошкоджених рядків).

    Навмисно просте: один рядок — один хід. Пошкоджений рядок не ламає
    читання решти, а частковий запис у кінці файлу ігнорується.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else None
        self._cache: list[TurnTrace] | None = None

    @property
    def path(self) -> Path | None:
        return self._path

    def available(self) -> bool:
        """Чи можна писати (тека існує або створюється)."""
        if self._path is None:
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            LOG.debug("Тека для traces недоступна: %s", self._path.parent,
                      exc_info=True)
            return False

    # ── запис ─────────────────────────────────────────────────────────────
    def record(self, trace: TurnTrace) -> bool:
        """Дописати один хід. ``False`` — якщо записати не вдалось."""
        if trace is None or not self.available():
            return False
        try:
            line = json.dumps(trace.to_dict(), ensure_ascii=False)
        except (TypeError, ValueError):
            LOG.info("Хід не серіалізується — пропускаю", exc_info=True)
            return False
        try:
            with open(self._path, "a", encoding="utf-8") as handle:  # type: ignore[arg-type]
                handle.write(line + "\n")
        except OSError:
            LOG.info("Не вдалось записати хід у %s", self._path, exc_info=True)
            return False
        if self._cache is not None:
            self._cache.append(trace)
        self._trim_if_needed()
        return True

    def _trim_if_needed(self) -> None:
        """Обрізати файл до KEEP_TRACES останніх рядків."""
        if self._path is None:
            return
        try:
            lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        if len(lines) <= KEEP_TRACES * 1.5:
            return
        keep = lines[-KEEP_TRACES:]
        try:
            # Атомарна заміна: обрізання журналу не має лишити обірваний
            # файл, якщо процес уб'ють посеред запису.
            from .config import write_text_atomic

            write_text_atomic(self._path, "\n".join(keep) + "\n")
        except OSError:
            LOG.debug("Не вдалось обрізати traces", exc_info=True)
        if self._cache is not None and len(self._cache) > KEEP_TRACES:
            self._cache = self._cache[-KEEP_TRACES:]

    # ── читання ───────────────────────────────────────────────────────────
    def load(self, *, refresh: bool = False) -> list[TurnTrace]:
        """Прочитати всі збережені ходи (кеш після першого читання)."""
        if self._cache is not None and not refresh:
            return list(self._cache)
        traces: list[TurnTrace] = []
        if self._path is None:
            self._cache = traces
            return traces
        try:
            body = self._path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._cache = traces
            return traces
        for line in body.splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue      # пошкоджений рядок не має ламати статистику
            parsed = TurnTrace.from_dict(data)
            if parsed is not None:
                traces.append(parsed)
        self._cache = traces
        return list(traces)

    def summary(self) -> dict[str, Any]:
        return aggregate(self.load())

    def clear(self) -> None:
        """Видалити всі збережені ходи (явна дія користувача)."""
        if self._path is None:
            return
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            LOG.debug("Не вдалось очистити traces", exc_info=True)
        self._cache = []

    # ── приклади для навчання ─────────────────────────────────────────────
    def examples(self, *, good: bool = True, limit: int = 20) -> list[TurnTrace]:
        """Відібрати приклади для майбутнього донавчання.

        «Хороший» приклад — хід без вигаданих інструментів, без хибного
        успіху й із чистою відповіддю. «Поганий» — навпаки. Обидва потрібні:
        без негативних прикладів неможливо навчити агента НЕ робити так.
        """
        rows = self.load()
        if good:
            picked = [item for item in rows
                      if item.human_readable and not item.leaked_protocol
                      and not item.false_success and not item.hallucinated_tool]
        else:
            picked = [item for item in rows
                      if item.leaked_protocol or item.false_success
                      or item.hallucinated_tool or item.rejected_calls]
        return picked[-limit:]


# ─── Побудова ходу з подій агента ───────────────────────────────────────────

def trace_from_events(
    events: Iterable[Any],
    *,
    intent_type: str = "",
    language: str = "uk",
    goal: str = "",
    answer: str = "",
    duration: float = 0.0,
    known_tools: Iterable[str] | None = None,
) -> TurnTrace:
    """Зібрати хід із подій ``AgentEvent`` (без приватних міркувань).

    Тут свідомо НЕ беруться події ``reasoning`` і ``reasoning_token``:
    зберігаються рішення й наслідки, а не думки.

    ``known_tools`` — імена інструментів, які справді є в реєстрі: без
    цього неможливо відрізнити вигаданий виклик від справжнього.
    """
    from . import response_engine

    trace = TurnTrace(intent_type=intent_type, language=language, goal=goal,
                      answer_head=response_engine.preview_of(answer, 400),
                      duration=duration)
    known = {str(item) for item in (known_tools or ()) if str(item)}
    names: list[str] = []
    rejected = 0
    failed = 0
    steps = 0
    changed: list[str] = []
    for event in events or ():
        kind = str(getattr(event, "kind", "") or "")
        data = getattr(event, "data", {}) or {}
        if kind == "tool_call":
            name = str(data.get("name") or "")
            if name:
                names.append(name)
            steps += 1
        elif kind == "tool_result":
            name = str(data.get("name") or "")
            # Назву беремо й звідси: подія результату може прийти без
            # парної події виклику (автовиконання роутера, відновлений чат),
            # і тоді «перевірку виконано» не видно взагалі.
            if name and name not in names:
                names.append(name)
            ok = bool(data.get("ok", True))
            if not ok:
                failed += 1
            text = str(getattr(event, "text", "") or "")
            if text.startswith("Аргументи не прийнято"):
                rejected += 1
            if ok and name in ("write_file", "edit_file", "append_file"):
                match = re.search(r"([\w./\\-]+\.[A-Za-z0-9]{1,8})", text)
                if match:
                    found = match.group(1).replace("\\", "/")
                    if found not in changed:
                        changed.append(found)
    trace.tools = names
    trace.rejected_calls = rejected
    trace.failed_calls = failed
    trace.changed_files = changed
    trace.steps = steps
    trace.hallucinated_tool = bool(known) and any(
        name not in known for name in names)
    trace.leaked_protocol = response_engine.looks_like_raw_protocol(answer)
    trace.human_readable = bool(answer.strip()) and not trace.leaked_protocol
    trace.has_code_block = "```" in (answer or "")
    # Хибний успіх: агент щось стверджує, але жоден файл не змінився і
    # жодна перевірка не проходила. Саме цю метрику найлегше «покращити»
    # вдаванням — тому вона рахується лише за фактами подій.
    trace.false_success = bool(answer.strip()) and not changed and not any(
        name in ("run_command", "python_check") for name in names) and (
        trace.intent_type in ("create", "edit", "debug"))
    return trace


def merge_totals(traces: Sequence[TurnTrace]) -> dict[str, int]:
    """Сумарні лічильники (для рядка статистики в журналі)."""
    rows = [item for item in traces or () if item is not None]
    return {
        "turns": len(rows),
        "calls": sum(len(item.tools) for item in rows),
        "failed": sum(item.failed_calls for item in rows),
        "rejected": sum(item.rejected_calls for item in rows),
        "false_success": sum(1 for item in rows if item.false_success),
    }
