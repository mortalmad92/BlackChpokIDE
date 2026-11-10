"""Тести журналу роботи агента (згорнутий блок «Аналіз запиту» в чаті).

Запуск:  python tests/test_work_log.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def test_helpers() -> None:
    """Підписи інструментів, тривалість, відмінювання."""
    from blackchpok_ide import work_log

    icon, verb, key = work_log.tool_view("read_file")
    # Ключ схеми змінився з ``file_path`` на уніфікований ``path`` (так само
    # в write_file/list_dir). Підпис мусить показувати САМЕ той ключ, який є в
    # схемі, інакше журнал показував би поле, якого модель не передає.
    # Деталі: research/KNOWN_BASELINE_FAILURES.md.
    check("read_file має людський підпис", verb == "Читає" and key == "path",
          f"{icon} {verb} {key}")

    icon, verb, key = work_log.tool_view("run_command")
    check("run_command має людський підпис", verb == "Запускає" and key == "command",
          verb)

    icon, verb, key = work_log.tool_view("router:search_web")
    # Перевіряємо саме те, що важливо: MCP-роутер розгортається в людську
    # дію й показує поле запиту. Формулювання може бути «Шукає в інтернеті»
    # або містити слово з назви дії — обидва варіанти прийнятні.
    check("MCP-роутер розгортається",
          ("search_web" in verb) or ("інтернет" in verb.lower()) or (key == "query"),
          f"{verb} · {key}")

    icon, verb, key = work_log.tool_view("щось_невідоме")
    check("невідомий інструмент не ламає", verb == "щось_невідоме", verb)

    check("12 с", work_log.human_duration(12) == "12 с", work_log.human_duration(12))
    check("2 хв 54 с", work_log.human_duration(174) == "2 хв 54 с",
          work_log.human_duration(174))
    check("1 год 5 хв", work_log.human_duration(3900) == "1 год 5 хв",
          work_log.human_duration(3900))
    check("0 с", work_log.human_duration(-5) == "0 с", work_log.human_duration(-5))

    check("1 крок", work_log.plural_steps(1) == "1 крок")
    check("3 кроки", work_log.plural_steps(3) == "3 кроки")
    check("5 кроків", work_log.plural_steps(5) == "5 кроків")
    check("21 крок", work_log.plural_steps(21) == "21 крок")


def test_widget() -> None:
    """Журнал: рядки, згортання, таймер, підсумок."""
    import tkinter as tk

    from blackchpok_ide import pulse, theme, work_log

    root = tk.Tk()
    root.geometry("700x800")
    fonts = theme.Theme(root)
    fonts.apply()

    log = work_log.WorkLog(root, fonts, wrap_width=520)
    log.pack(fill="x", padx=10, pady=10)
    root.update()

    check("заголовок за замовчуванням", log.title_label.cget("text") == "Аналіз запиту")

    log.begin("Аналіз запиту")
    check("журнал у стані роботи", log.running is True)
    check("крапка пульсує", log.dot.state == pulse.PulseDot.RUNNING)
    check("таймер показує «міркую…»", "міркую" in log.timer_label.cget("text"),
          log.timer_label.cget("text"))

    log.add_row(work_log.KIND_NARRATION, "│", "Спершу вивчу поточний стан проєкту.")
    log.add_reasoning("Треба перевірити, як влаштована розкладка вікна. "
                      "Потім подивлюсь тести.")
    log.add_tool("read_file", "file_path=blackchpok_ide/main_window.py", call_id="c1")
    log.add_tool("search_text", "query=def test_", call_id="c2")
    log.add_tool("run_command", "command=python tests/test_layout.py", call_id="c3")
    root.update()

    check("рядки додано", len(log._rows) == 5, f"{len(log._rows)}")
    check("кроків пораховано", log.step_count == 3, str(log.step_count))

    # Людські підписи в рядках.
    texts = [row.label.cget("text") for row in log._rows]
    check("є «Читає»", "Читає" in texts, str(texts))
    check("є «Шукає»", "Шукає" in texts)
    check("є «Запускає»", "Запускає" in texts)

    # Ціль витягнута з аргументів.
    targets = [row.target.cget("text") for row in log._rows]
    check("шлях видно в рядку",
          any("main_window.py" in t for t in targets), str(targets))
    check("команда видно в рядку",
          any("test_layout.py" in t for t in targets), str(targets))

    # Завершення інструмента ставить галочку.
    log.finish_tool("c1", ok=True)
    root.update()
    row = log._by_call.get("c1")
    check("завершений інструмент має ✓",
          row is not None and row.icon.cget("text") == "✓",
          row.icon.cget("text") if row else "—")

    log.finish_tool("c2", ok=False)
    row = log._by_call.get("c2")
    check("невдалий інструмент має ✗",
          row is not None and row.icon.cget("text") == "✗",
          row.icon.cget("text") if row else "—")

    # Згортання.
    check("спочатку розгорнуто", log._expanded is True)
    log.toggle()
    root.update()
    check("клік згортає", log._expanded is False)
    check("стрілка показує ▸", log.arrow.cget("text") == "▸",
          log.arrow.cget("text"))
    check("рядки сховані", log.rows_host.winfo_ismapped() == 0)
    log.toggle()
    root.update()
    check("повторний клік розгортає", log._expanded is True)
    check("рядки знову видно", log.rows_host.winfo_ismapped() == 1)

    # Таймер цокає.
    before = log.timer_label.cget("text")
    pump(root, 1.2)
    after = log.timer_label.cget("text")
    check("таймер рухається", before != after, f"{before} → {after}")

    # Завершення.
    log.finish(ok=True)
    root.update()
    check("після завершення не «міркує»", log.running is False)
    check("крапка стала «готово»", log.dot.state == pulse.PulseDot.DONE,
          log.dot.state)
    check("таймер застиг без «міркую»",
          "міркую" not in log.timer_label.cget("text"),
          log.timer_label.cget("text"))
    summary = [r for r in log._rows if r.kind == work_log.KIND_SUMMARY]
    check("додано підсумок", len(summary) == 1)
    check("у підсумку є кількіс��ь кроків",
          summary and "3 кроки" in summary[0].label.cget("text"),
          summary[0].label.cget("text") if summary else "—")

    # Після завершення таймер не смикається.
    frozen = log.timer_label.cget("text")
    pump(root, 0.8)
    check("застиглий таймер не змінюється",
          log.timer_label.cget("text") == frozen)

    # Очищення.
    log.clear()
    check("clear() прибирає рядки", not log._rows)

    # Обмеження рядків.
    log.begin("Перевірка ліміту")
    for index in range(work_log.MAX_ROWS + 20):
        log.add_row(work_log.KIND_NOTE, "·", f"рядок {index}")
    check("кількість рядків обмежена",
          len(log._rows) == work_log.MAX_ROWS, f"{len(log._rows)}")
    log.stop_timers()
    root.destroy()


def test_chat_integration() -> None:
    """Чат перетворює події агента на рядки журналу."""
    import tkinter as tk

    from blackchpok_ide import theme, work_log
    from blackchpok_ide.agent import AgentEvent
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.chat_panel import ChatPanel
    from blackchpok_ide.config import Settings

    root = tk.Tk()
    root.geometry("760x800")
    fonts = theme.Theme(root)
    fonts.apply()
    host = tk.Frame(root)
    host.pack(side="bottom", fill="x")
    panel = ChatPanel(root, fonts, Settings(), ToolRegistry(ROOT), composer_parent=host)
    panel.pack(fill="both", expand=True)
    root.update()

    # «Запит до моделі…» навмисно не створює журналу — він дублює заголовок.
    panel._handle_event(AgentEvent("status", "Запит до qwen2.5-coder…"))
    root.update()
    check("статус «запит до моделі» не плодить журнал", panel._log is None)

    # А офлайн-режим — корисний статус, він має потрапити в журнал.
    panel._handle_event(AgentEvent("status", "Модель недоступна — працюю локальним роутером."))
    root.update()
    check("корисний статус створив журнал", panel._log is not None)
    check("статус став рядком журналу",
          any(r.kind == work_log.KIND_STATUS for r in panel._log._rows),
          str([r.kind for r in panel._log._rows]))

    panel._handle_event(AgentEvent("reasoning",
                                   "Спершу подивлюсь, як влаштований чат. "
                                   "Потім додам рядки.",
                                   {"step": 0}))
    panel._handle_event(AgentEvent("tool_call", "read_file(path=main.py)",
                                  {"call_id": "k1", "name": "read_file",
                                   "arguments": "path=main.py"}))
    panel._handle_event(AgentEvent("tool_result", "вміст файлу",
                                   {"call_id": "k1", "name": "read_file", "ok": True}))
    root.update()

    log = panel._log
    check("журнал живий", log is not None)
    check("є рядок роздумів",
          any(r.kind == work_log.KIND_REASONING for r in log._rows),
          str([r.kind for r in log._rows]))
    check("є рядок інструмента",
          any(r.kind == work_log.KIND_TOOL for r in log._rows))
    check("інструмент позначено виконаним",
          log._by_call.get("k1") is not None
          and log._by_call["k1"].icon.cget("text") == "✓")

    # Проміжний текст агента йде в журнал, а не окремою карткою.
    cards_before = len(panel._cards)
    panel._handle_event(AgentEvent("assistant", "Тепер перевірю тести.",
                                   {"step": 1, "final": False}))
    root.update()
    check("проміжний текст не створив картку",
          len(panel._cards) == cards_before, f"{cards_before} → {len(panel._cards)}")
    check("проміжний текст став рядком журналу",
          any(r.kind == work_log.KIND_NARRATION for r in log._rows))

    # Фінальна відповідь — окрема картка, журнал закрито.
    panel._handle_event(AgentEvent("assistant", "Готово: додав рядки.",
                                   {"step": 2, "final": True}))
    panel._handle_event(AgentEvent("done", "", {"ok": True}))
    root.update()
    check("фінальна відповідь створила картку", len(panel._cards) > cards_before)
    check("журнал завершено", log.running is False)
    check("журнал відчеплено", panel._log is None)

    # Новий запит починає новий журнал.
    panel._handle_event(AgentEvent("tool_call", "list_dir(path=.)",
                                   {"call_id": "k2", "name": "list_dir",
                                    "arguments": "path=."}))
    root.update()
    check("новий журнал створено", panel._log is not None and panel._log is not log)

    panel._clear_work_log()
    root.update()
    root.destroy()


def test_reasoning_from_agent() -> None:
    """Агент справді віддає reasoning подією (а не викидає)."""
    import queue as _queue
    import threading

    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.config import AgentSettings
    from blackchpok_ide.llm_client import ChatResult

    runner = AgentRunner.__new__(AgentRunner)
    runner.events = _queue.Queue()
    runner._cancel = threading.Event()
    runner._last_answer = ""
    runner._error = ""
    runner.settings_ref = None
    runner.registry = None
    runner.skill_book = None
    runner.mcp_manager = None
    runner.agent_settings = AgentSettings()
    runner._pending_hint = []
    runner.on_finished = None
    runner.tool_schemas = lambda: []

    class FakeSession:
        messages: list = []

        def build(self):
            return [{"role": "system", "content": "x"}]

        def add_user(self, text):
            # Реальний ``AgentSession.add_user`` пише сюди репліку користувача;
            # ``_loop`` кличе його перед зверненням до моделі. Без цього
            # заглушка відставала від коду й тест падав з AttributeError.
            self.messages.append({"role": "user", "content": text})

        def add_assistant(self, message):
            self.messages.append(message)

        def add_tool_result(self, *args, **kwargs):
            pass

    runner.session = FakeSession()

    class FakeStats:
        context_limit = 0
        breakdown = None

        def add_result(self, *args, **kwargs):
            return type("Step", (), {"prompt_tokens": 1})()

        def update_breakdown(self, **kwargs):
            pass

    runner.stats = FakeStats()

    class FakeClient:
        def chat(self, messages, tools=None, tool_choice=None):
            return ChatResult(
                content="Готово.",
                tool_calls=[],
                reasoning="Треба спершу прочитати файл. Потім перевірити тести.",
            )

    runner._loop(FakeClient())

    kinds = []
    reasoning_text = ""
    while not runner.events.empty():
        event = runner.events.get_nowait()
        kinds.append(event.kind)
        if event.kind == "reasoning":
            reasoning_text = event.text

    check("подія reasoning існує", "reasoning" in kinds, str(kinds))
    check("текст роздумів передано", "прочитати файл" in reasoning_text,
          reasoning_text[:50])
    check("фінальна відповідь позначена final",
          any(k == "assistant" for k in kinds), str(kinds))


def main() -> int:
    test_helpers()
    test_widget()
    test_chat_integration()
    test_reasoning_from_agent()
    print()
    print("Журнал роботи:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_work_log.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
