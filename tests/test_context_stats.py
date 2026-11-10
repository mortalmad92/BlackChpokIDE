"""Тести статистики контексту: підрахунок із реальних відповідей сервера.

Запуск:  python tests/test_context_stats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import context_stats as cs  # noqa: E402
from blackchpok_ide.llm_client import ChatResult  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# Справжня відповідь llama.cpp b12129 (знята з локального сервера).
REAL_USAGE = {
    "completion_tokens": 6,
    "prompt_tokens": 42,
    "total_tokens": 48,
    "prompt_tokens_details": {"cached_tokens": 0},
}
REAL_TIMINGS = {
    "cache_n": 0, "prompt_n": 42, "prompt_ms": 1948.051,
    "prompt_per_token_ms": 46.38, "prompt_per_second": 21.56,
    "predicted_n": 6, "predicted_ms": 438.88,
    "predicted_per_token_ms": 87.78, "predicted_per_second": 11.39,
}


def test_from_result() -> None:
    result = ChatResult(content="Привіт", tool_calls=[], finish_reason="stop",
                        usage=REAL_USAGE)
    step = cs.StepStats.from_result(result, tool_calls=1, duration=2.4)
    check("вхідні токени з usage", step.prompt_tokens == 42, str(step.prompt_tokens))
    check("згенеровані токени", step.completion_tokens == 6)
    check("усього токенів", step.total_tokens == 48)
    check("виклики інструментів", step.tool_calls == 1)
    check("тривалість", step.duration == 2.4)

    with_speed = cs.StepStats.from_result({**REAL_USAGE, "timings": REAL_TIMINGS})
    check("швидкість генерації з timings",
          abs(with_speed.predicted_per_second - 11.39) < 0.01,
          f"{with_speed.predicted_per_second}")
    check("швидкість промпту з timings",
          abs(with_speed.prompt_per_second - 21.56) < 0.01)

    cached = cs.StepStats.from_result(
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 10, "total_tokens": 1010,
                   "prompt_tokens_details": {"cached_tokens": 800}}})
    check("кешовані токени з prompt_tokens_details", cached.cached_tokens == 800)

    alt = cs.StepStats.from_result(
        {"usage": {"prompt_tokens": 100, "input_tokens": 100,
                   "cache_read_input_tokens": 60}})
    check("альтернативне поле cache_read_input_tokens", alt.cached_tokens == 60)

    anon = cs.StepStats.from_result({"usage": {"prompt_n": 30, "predicted_n": 5}})
    check("llama.cpp-стиль prompt_n/predicted_n",
          anon.prompt_tokens == 30 and anon.completion_tokens == 5)

    empty = cs.StepStats.from_result(ChatResult(content="", tool_calls=[], usage=None))
    check("без usage — нулі, без винятку",
          empty.prompt_tokens == 0 and empty.completion_tokens == 0)

    junk = cs.StepStats.from_result({"usage": {"prompt_tokens": "багато", "completion_tokens": None}})
    check("сміття у полях не ламає розбір",
          junk.prompt_tokens == 0 and junk.completion_tokens == 0)


def test_accumulation() -> None:
    stats = cs.ContextStats()
    check("порожня статистика", stats.step_count == 0 and stats.total_tokens == 0)
    check("порожній рядок швидкості", stats.speed_text() == "— ток/с", stats.speed_text())

    stats.add_result({"usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                "total_tokens": 120,
                                "prompt_tokens_details": {"cached_tokens": 80}},
                      "timings": {"predicted_per_second": 25.0}},
                     tool_calls=2, duration=3.0)
    stats.add_result({"usage": {"prompt_tokens": 300, "completion_tokens": 40,
                                "total_tokens": 340,
                                "prompt_tokens_details": {"cached_tokens": 320}},
                      "timings": {"predicted_per_second": 30.0}},
                     tool_calls=1, duration=4.0)

    check("два кроки", stats.step_count == 2)
    check("сума вхідних токенів", stats.prompt_tokens == 400, str(stats.prompt_tokens))
    check("сума згенерованих", stats.completion_tokens == 60)
    check("сума кешованих", stats.cached_tokens == 400)
    check("усього токенів", stats.total_tokens == 460)
    check("виклики інструментів підсумовано", stats.tool_calls == 3)
    check("влучання в кеш 100%", round(stats.cache_hit_percent) == 100,
          f"{stats.cache_hit_percent}")
    check("швидкість — з останнього кроку", round(stats.speed) == 30, f"{stats.speed}")
    check("час роботи", stats.elapsed == 7.0 and stats.elapsed_text == "7 с")
    check("останній розмір контексту", stats.last_prompt_tokens == 300)

    stats.set_limit(8192)
    check("заповнення контексту", round(stats.fill_percent) == 4, f"{stats.fill_percent}")
    check("рядок заповнення", stats.fill_text().endswith("%"), stats.fill_text())

    line = stats.summary_line()
    check("підсумковий рядок містить кроки", "кроків: 2" in line, line)
    check("підсумковий рядок містить швидкість", "ток/с" in line, line)
    check("підсумковий рядок містить кеш", "кеш:" in line, line)

    tip = stats.detail_tooltip()
    check("підказка містить кеш", "Влучання в кеш" in tip)
    check("підказка містить контекст", "8 192" in tip.replace(",", ""), tip[-80:])

    stats.reset()
    check("скидання", stats.step_count == 0 and stats.tool_calls == 0
          and stats.last_prompt_tokens == 0)


def test_formatting() -> None:
    check("токени < 1000", cs.format_tokens(950) == "950", cs.format_tokens(950))
    check("токени тисячі", cs.format_tokens(12400) == "12,4 тис.", cs.format_tokens(12400))
    check("токени рівно тисяча", cs.format_tokens(1000) == "1 тис.", cs.format_tokens(1000))
    check("токени мільйони", cs.format_tokens(1_240_000) == "1,2 млн", cs.format_tokens(1_240_000))
    check("нуль токенів", cs.format_tokens(0) == "0")
    check("від'ємне значення не ламає", cs.format_tokens(-5) == "0")

    check("секунди", cs.format_duration(45) == "45 с")
    check("хвилини й секунди", cs.format_duration(125) == "2 хв 5 с", cs.format_duration(125))
    check("рівні хвилини", cs.format_duration(120) == "2 хв")
    check("години", cs.format_duration(3900) == "1 год 5 хв", cs.format_duration(3900))

    check("відсоток", cs.percent(50, 200) == 25.0)
    check("відсоток при нулі", cs.percent(5, 0) == 0.0)
    check("відсоток не перевищує 100", cs.percent(500, 100) == 100.0)


def test_no_usage_but_timing() -> None:
    """Сервер без usage, але з часом: швидкість рахуємо з тривалості."""
    stats = cs.ContextStats()
    stats.add(cs.StepStats(completion_tokens=100, duration=4.0))
    stats.add(cs.StepStats(completion_tokens=100, duration=4.0))
    check("швидкість із тривалості", round(stats.speed) == 25, f"{stats.speed}")


def test_estimates() -> None:
    # Раніше тут було «20 <= x <= 40» — це кодувало стару формулу
    # ``len(text)/3.5``, яку виправлено 10.11.2026. Перевірено на
    # СПРАВЖНЬОМУ tokenizer (Qwen2-VL): 100 символів кирилиці = 100 токенів,
    # тобто 1 символ ≈ 1 токен, а не 3.5. Єдина евристика проєкту
    # (``context_budget``) дає 62 + 6 = 68 — це ЧЕСНІШЕ за 28, бо стара
    # формула занижувала кількість токенів утричі для української мови.
    estimate = cs.estimate_tokens("а" * 100)
    check("оцінка токенів для кирилиці не занижена", 55 <= estimate <= 110,
          f"{estimate} (справжній tokenizer дає 100)")
    check("кирилиця дорожча за латиницю",
          cs.estimate_tokens("а" * 100) > cs.estimate_tokens("a" * 100),
          f"{cs.estimate_tokens('а' * 100)} vs {cs.estimate_tokens('a' * 100)}")
    check("оцінка порожнього", cs.estimate_tokens("") == 0)
    messages = [{"role": "user", "content": "привіт" * 10},
                {"role": "assistant", "content": "ок"}]
    estimate = cs.estimate_messages(messages)
    check("оцінка списку повідомлень > 0", estimate > 8, str(estimate))


def test_merge() -> None:
    a = cs.ContextStats()
    a.add_result({"usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}})
    a.set_limit(4096)
    b = cs.ContextStats()
    b.add_result({"usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22}})
    merged = cs.merge([a, b])
    check("об'єднання кроків", merged.step_count == 2)
    check("об'єднання токенів", merged.prompt_tokens == 30)
    check("об'єднання ліміту", merged.context_limit == 4096)


def test_unlimited_context() -> None:
    stats = cs.ContextStats()
    stats.add_result({"usage": {"prompt_tokens": 5000, "completion_tokens": 10,
                                "total_tokens": 5010}})
    check("без ліміту заповнення 0%", stats.fill_percent == 0.0)
    check("рядок заповнення без ліміту", stats.fill_text() == "0%")


def test_breakdown() -> None:
    tools = [
        {"type": "function", "function": {
            "name": "read_file", "description": "Прочитати файл",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Шлях"}}}}},
        {"type": "function", "function": {
            "name": "run_command", "description": "Виконати команду",
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string"}}}}},
    ]
    messages = [{"role": "user", "content": "привіт " * 200},
                {"role": "assistant", "content": "ок"}]

    breakdown = cs.split_context(system_prompt="ти агент " * 100, tools=tools,
                                 messages=messages, total_tokens=5000)
    check("розбивка: три складові", len(breakdown.parts) == 3)
    labels = [label for label, _ in breakdown.parts]
    check("розбивка: підписи",
          labels == ["Системна підказка", "Опис інструментів", "Повідомлення"],
          str(labels))
    check("розбивка: сума дорівнює реальному prompt_tokens",
          sum(tokens for _, tokens in breakdown.parts) == 5000,
          str(sum(tokens for _, tokens in breakdown.parts)))
    check("розбивка: усі частини > 0",
          all(tokens > 0 for _, tokens in breakdown.parts),
          str(breakdown.parts))
    check("розбивка: повідомлення найбільші",
          breakdown.messages_tokens > breakdown.system_tokens)
    check("розбивка: відсоток повідомлень",
          0 < breakdown.percent_of(breakdown.messages_tokens) <= 100,
          f"{breakdown.percent_of(breakdown.messages_tokens)}")
    check("розбивка: відсотки складаються у ~100",
          abs(sum(breakdown.percent_of(t) for _, t in breakdown.parts) - 100) < 1.0)

    empty = cs.split_context(total_tokens=0)
    check("порожня розбивка", empty.estimated_total == 0 and empty.total_tokens == 0)
    check("порожня розбивка: відсоток 0", empty.percent_of(0) == 0.0)

    # Масштабування не ламає пропорцій при великій розбіжності.
    off = cs.ContextBreakdown(10, 5, 100, 1000)
    scaled = off.scaled(1000)
    check("масштабування: сума = ціль",
          sum(t for _, t in scaled.parts) == 1000, str(scaled.parts))
    check("масштабування: порядок збережено",
          scaled.messages_tokens > scaled.system_tokens > scaled.tools_tokens)

    # Статистика оновлює розбивку разом із кроком.
    stats = cs.ContextStats()
    stats.add_result({"usage": {"prompt_tokens": 5000, "completion_tokens": 10,
                                "total_tokens": 5010}})
    stats.update_breakdown(system_prompt="ти агент " * 100, tools=tools, messages=messages)
    check("статистика: розбивка прив'язана до кроку",
          stats.breakdown.total_tokens == 5000, str(stats.breakdown.total_tokens))
    stats.reset()
    check("статистика: скидання розбивки",
          stats.breakdown.estimated_total == 0 and stats.breakdown.total_tokens == 0)


def test_tools_estimate() -> None:
    simple = cs.estimate_tools([{"function": {"name": "a", "description": "b"}}])
    check("оцінка інструментів > 0", simple > 0, str(simple))
    check("порожній перелік інструментів", cs.estimate_tools([]) == 0)
    bigger = cs.estimate_tools([
        {"function": {"name": "x", "description": "довгий опис " * 50,
                      "parameters": {"type": "object", "properties": {
                          f"p{i}": {"type": "string"} for i in range(10)}}}},
    ])
    check("більший опис дає більше токенів", bigger > simple, f"{bigger} > {simple}")


def main() -> int:
    test_from_result()
    test_accumulation()
    test_formatting()
    test_no_usage_but_timing()
    test_estimates()
    test_merge()
    test_unlimited_context()
    test_breakdown()
    test_tools_estimate()
    print()
    print("Статистика контексту:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_context_stats.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
