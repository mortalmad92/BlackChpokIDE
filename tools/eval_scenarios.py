"""Набір сценаріїв оцінювання агента українською мовою.

Це НЕ тести коду: тут перевіряється ПОВЕДІНКА — чи правильно агент
зрозумів намір, чи вибрав доречні інструменти, чи не вигадав результатів.
Кожен сценарій має очікування, які можна перевірити кодом, тож прогін
дає цифри, а не враження.

Категорії побудовані на реальних скаргах користувача:

A. Неофіційна людська мова — «зроби щоб воно працювало нормально».
B. Помилки й скорочення — «поправ роутер мсп».
C. Багатоповідомленнєві інструкції — три репліки, одна задача.
D. Межі завдання — не чіпати зайвого, не перепитувати відомого.
E. Вибір інструментів — правильний інструмент і правильні аргументи.
F. Якість відповіді — людський текст, код окремо, без протоколу.

Запуск без моделі (перевіряє лише детерміновані шари):
    .venv\\Scripts\\python.exe tools\\eval_scenarios.py

Запуск із моделлю (додає перевірку реальних відповідей):
    .venv\\Scripts\\python.exe tools\\eval_scenarios.py --live
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import (  # noqa: E402
    conversation,
    intent_engine,
    model_profile,
    response_engine,
    tool_specs,
)

__all__ = [
    "CATEGORIES",
    "Scenario",
    "SCENARIOS",
    "evaluate_intent",
    "run_all",
]


@dataclass
class Scenario:
    """Один сценарій: фраза, очікуваний намір і додаткові умови."""

    name: str
    category: str
    message: str
    #: Очікуваний тип повідомлення (intent_type).
    expect_intent: str = ""
    #: Попередні репліки — для перевірки контексту.
    history: list[str] = field(default_factory=list)
    #: Чи має агент поставити уточнення перед роботою.
    expect_clarify: bool = False
    #: Чи має агент питати НЕ ставити (для збоїв і огляду).
    expect_no_clarify: bool = False
    #: Обмеження, які мусять зберегтись.
    expect_constraints: list[str] = field(default_factory=list)
    #: Чимало інструментів доречні — перевіряємо підмножину назв.
    expect_tools: list[str] = field(default_factory=list)
    #: Тип попереднього наміру (для «і додай…»).
    previous_intent: str = ""
    #: Мова, якою має бути відповідь.
    expect_language: str = "uk"


#: Категорії з людськими назвами (для звіту).
CATEGORIES: dict[str, str] = {
    "A": "Неофіційна людська мова",
    "B": "Помилки та скорочення",
    "C": "Багатоповідомленнєві інструкції",
    "D": "Межі завдання й уточнення",
    "E": "Вибір інструментів",
    "F": "Якість відповіді",
}


SCENARIOS: list[Scenario] = [
    # ── A. Неофіційна людська мова ─────────────────────────────────────────
    Scenario(
        name="A1 просто «зроби нормально»",
        category="A",
        message="Зроби щоб воно працювало нормально",
        expect_intent=intent_engine.DEBUG,
        expect_no_clarify=True,
    ),
    Scenario(
        name="A2 файли не бачить",
        category="A",
        message="Він знову не бачить ті файли",
        expect_intent=intent_engine.DEBUG,
        expect_no_clarify=True,
    ),
    Scenario(
        name="A3 не зламай нічого",
        category="A",
        message="Прибери цю дурню, але нічого іншого не зламай",
        expect_intent=intent_engine.EDIT,
        expect_constraints=["не ламати наявну поведінку"],
    ),
    Scenario(
        name="A4 як минулого разу",
        category="A",
        message="Зроби як минулого разу, тільки швидше",
        history=["Перероби запуск локальної моделі"],
        expect_constraints=["не сповільнювати роботу"],
    ),
    Scenario(
        name="A5 не вигадуй файлів",
        category="A",
        message="Зроби щоб агент нормально бачив файли проєкту і не вигадував їх",
        expect_intent=intent_engine.EDIT,
        expect_constraints=["не вигадувати вміст файлів і результати"],
    ),
    Scenario(
        name="A6 стиль відповіді",
        category="A",
        message="завжди відповідай українською і коротко",
        expect_intent=intent_engine.CONVERSE,
    ),

    # ── B. Помилки та скорочення ───────────────────────────────────────────
    Scenario(
        name="B1 «поправ роутер мсп»",
        category="B",
        message="поправ роутер мсп",
        expect_intent=intent_engine.DEBUG,
    ),
    Scenario(
        name="B2 «ші само юзало інструменти»",
        category="B",
        message="зроби щоб ші само юзало інструменти",
        expect_intent=intent_engine.EDIT,
    ),
    Scenario(
        name="B3 «не паше»",
        category="B",
        message="чому воно знову не паше",
        expect_intent=intent_engine.DEBUG,
        expect_no_clarify=True,
    ),
    Scenario(
        name="B4 коротка команда",
        category="B",
        message="прожени тести",
        expect_intent=intent_engine.TEST,
        expect_tools=["run_command"],
    ),
    Scenario(
        name="B5 ціна в мережі",
        category="B",
        message="скільки коштує біткоїн",
        expect_intent=intent_engine.RESEARCH,
        expect_tools=["search_web"],
    ),

    # ── C. Багатоповідомленнєві інструкції ─────────────────────────────────
    Scenario(
        name="C1 три репліки про збереження",
        category="C",
        message="Тільки щоб старі не видалялись",
        history=["Перероби збереження чатів"],
        previous_intent=intent_engine.EDIT,
        expect_intent=intent_engine.EDIT,
        expect_constraints=["не видаляти наявні дані"],
    ),
    Scenario(
        name="C2 «і додай…» продовжує задачу",
        category="C",
        message="І додай автоматичне відновлення після перезапуску",
        history=["Перероби збереження чатів", "Тільки щоб старі не видалялись"],
        previous_intent=intent_engine.EDIT,
        expect_intent=intent_engine.EDIT,
    ),
    Scenario(
        name="C3 без сторонніх програм",
        category="C",
        message="Без сторонніх програм",
        history=["Перероби механізм запуску локальної моделі",
                 "І ще зроби щоб він автоматично визначав відеокарту"],
        previous_intent=intent_engine.EDIT,
        expect_constraints=["не додавати зовнішніх залежностей"],
    ),

    # ── D. Межі завдання й уточнення ───────────────────────────────────────
    Scenario(
        name="D1 «зроби краще» — питати",
        category="D",
        message="зроби краще",
        expect_clarify=True,
    ),
    Scenario(
        name="D2 «видали все зайве» — питати",
        category="D",
        message="видали все зайве",
        expect_clarify=True,
    ),
    Scenario(
        name="D3 конкретна задача — не питати",
        category="D",
        message="у файлі calc.py додай множення",
        expect_intent=intent_engine.CREATE,
        expect_no_clarify=True,
        expect_tools=["read_file", "edit_file"],
    ),
    Scenario(
        name="D4 розмова — без інструментів",
        category="D",
        message="привіт, як справи?",
        expect_intent=intent_engine.CONVERSE,
        expect_no_clarify=True,
    ),
    Scenario(
        name="D5 огляд — не питати",
        category="D",
        message="покажи що є в проєкті",
        expect_intent=intent_engine.INSPECT,
        expect_no_clarify=True,
    ),

    # ── E. Вибір інструментів ──────────────────────────────────────────────
    Scenario(
        name="E1 створення файлу",
        category="E",
        message="створи калькулятор на python",
        expect_intent=intent_engine.CREATE,
        expect_tools=["write_file", "python_check"],
    ),
    Scenario(
        name="E2 пошук у коді",
        category="E",
        message="найди де викликається master_agent_router",
        expect_intent=intent_engine.INSPECT,
        expect_tools=["search_text"],
    ),
    Scenario(
        name="E3 виправлення помилки",
        category="E",
        message="не працює кнопка збереження, виправ",
        expect_intent=intent_engine.DEBUG,
        expect_tools=["run_command", "read_file", "edit_file"],
    ),
    Scenario(
        name="E4 пояснення файлу",
        category="E",
        message="поясни що робить цей файл",
        expect_intent=intent_engine.INSPECT,
        expect_tools=["read_file"],
    ),

    # ── F. Якість відповіді ───────────────────────────────────────────────
    Scenario(
        name="F1 англійською — відповідь англійською",
        category="F",
        message="please fix the save button",
        expect_language="en",
    ),
    Scenario(
        name="F2 змішана мова",
        category="F",
        message="fix цю кнопку please",
        expect_language="mixed",
    ),
]


def evaluate_intent(scenario: Scenario) -> dict[str, Any]:
    """Прогнати один сценарій через детерміновані шари.

    Повертає словник із результатами перевірок: ``passed`` і список
    ``problems``. Модель тут не потрібна — намір, обмеження й уточнення
    визначаються кодом.
    """
    state = conversation.ConversationState()
    # Відтворюємо історію так само, як це робить агент.
    for text in scenario.history:
        state.observe_user_message(
            text, intent_engine.frame(text, previous_messages=state.recent))
    frame = intent_engine.frame(
        scenario.message,
        previous_messages=state.recent,
        previous_intent=(scenario.previous_intent or state.intent_type),
    )
    state.observe_user_message(scenario.message, frame)

    problems: list[str] = []
    if scenario.expect_intent and frame.intent_type != scenario.expect_intent:
        problems.append(
            f"намір {frame.intent_type}, очікували {scenario.expect_intent}")
    for wanted in scenario.expect_constraints:
        if wanted not in frame.constraints:
            problems.append(f"немає обмеження «{wanted}»")
    asks = intent_engine.needs_clarification(frame)
    if scenario.expect_clarify and not asks:
        problems.append("мав поставити уточнення, але не поставив")
    if scenario.expect_no_clarify and asks:
        problems.append("перепитує там, де має діяти сам")
    if scenario.expect_language and frame.language != scenario.expect_language:
        problems.append(
            f"мова {frame.language}, очікували {scenario.expect_language}")
    if scenario.expect_tools:
        missing = [name for name in scenario.expect_tools
                   if name not in frame.required_tools]
        # Для огляду доречні інструменти можуть бути ширші — тоді
        # достатньо, щоб модель бачила хоча б один із потрібних.
        if missing and len(missing) == len(scenario.expect_tools):
            problems.append("жодного доречного інструмента: "
                            + ", ".join(scenario.expect_tools))

    return {
        "name": scenario.name,
        "category": scenario.category,
        "passed": not problems,
        "problems": problems,
        "intent": frame.intent_type,
        "language": frame.language,
        "confidence": round(frame.confidence, 2),
        "risk": frame.risk_level,
        "clarify": asks,
        "constraints": list(frame.constraints),
        "tools": list(frame.required_tools),
    }


def evaluate_answer(scenario: Scenario, answer: str,
                    observations: Sequence[Any] = ()) -> dict[str, Any]:
    """Перевірити якість ГОТОВОЇ відповіді (коли модель уже відповіла).

    Використовується з ``--live``: тут перевіряється те, що бачить людина.
    """
    problems: list[str] = []
    if response_engine.looks_like_raw_protocol(answer):
        problems.append("у відповіді сирий протокол (JSON виклику тощо)")
    if response_engine.promises_action(answer):
        problems.append("відповідь — обіцянка дії замість результату")
    final = response_engine.final_answer(answer, observations, fallback=answer)
    if response_engine.looks_like_raw_protocol(final):
        problems.append("після очищення лишився протокол")
    return {"passed": not problems, "problems": problems, "answer": final}


def run_all(*, verbose: bool = True) -> dict[str, Any]:
    """Прогнати всі сценарії й повернути підсумок за категоріями."""
    results = [evaluate_intent(item) for item in SCENARIOS]
    by_category: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = by_category.setdefault(item["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        if item["passed"]:
            bucket["passed"] += 1
    passed = sum(1 for item in results if item["passed"])
    if verbose:
        for item in results:
            mark = "OK  " if item["passed"] else "FAIL"
            print(f"[{mark}] {item['category']} · {item['name']}")
            for problem in item["problems"]:
                print(f"        → {problem}")
        print()
        for code, name in CATEGORIES.items():
            bucket = by_category.get(code)
            if not bucket:
                continue
            print(f"{code}. {name}: {bucket['passed']}/{bucket['total']}")
        print()
        print(f"Разом: {passed}/{len(results)}")
    return {
        "passed": passed,
        "total": len(results),
        "by_category": by_category,
        "results": results,
    }


def profile_report() -> str:
    """Показати, які моделі отримають який формат виклику."""
    lines = ["Профілі моделей (перевірка адаптера):"]
    for name, url in (
        ("qwen2.5-coder-14b", "http://127.0.0.1:1234/v1"),
        ("tinyllama-1.1b", "http://127.0.0.1:1234/v1"),
        ("deepseek-r1-14b", "http://127.0.0.1:8080/v1"),
        ("", "native://blackchpok"),
    ):
        profile = model_profile.profile_for(name, url, context_window=8192)
        lines.append(f"- {profile.describe()}")
    return "\n".join(lines)


def spec_report() -> str:
    """Скільки інструментів описано й як вони розподілені за ризиком."""
    from blackchpok_ide.agent_tools import TOOL_SCHEMAS

    specs = tool_specs.specs_for_schemas(TOOL_SCHEMAS)
    counts: dict[str, int] = {}
    for spec in specs.values():
        counts[spec.risk] = counts.get(spec.risk, 0) + 1
    parts = [f"{risk}: {count}" for risk, count in sorted(counts.items())]
    return f"Інструментів описано: {len(specs)} (" + ", ".join(parts) + ")"


def main() -> int:
    print("=== Сценарії поведінки (без моделі) ===")
    summary = run_all()
    print()
    print(spec_report())
    print()
    print(profile_report())
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
