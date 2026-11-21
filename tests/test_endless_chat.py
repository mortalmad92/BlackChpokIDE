"""Нескінченний чат: гаряча черга, автозвільнення вікна, авто-роутер.

Фіксують вимоги користувача (21.11.2026):

  «Гаряче додавання завдань в чат на льоту як для хмарних, так і локальних
   моделей з автоочищенням контексту і самонавчанням через довгострокову
   пам'ять. Очищаєш контекст шляхом перенесення в довгострокову пам'ять і
   вивільняєш для наступних дій, так до безкінечності роботи в чатах.»

  «Автоматичний роутер інструментів, щоб не брало всі інструменти без
   необхідності, а тільки необхідні при виконанні задачі.»

Що перевіряємо:

1. Роутер дає РІЗНІ набори для різних задач і завжди лишає шлях до решти
   інструментів (``run_tool``/``load_tools``).
2. Гаряча черга приймає запит під час роботи агента й віддає його по одному.
3. Автозвільнення вікна ПЕРЕНОСИТЬ контекст у пам'ять, а не викидає його.

Запуск: python -m unittest tests.test_endless_chat -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import tool_select  # noqa: E402

#: Реалістичний набір назв інструментів проєкту.
AVAILABLE = [
    "read_file", "write_file", "edit_file", "append_file", "list_dir",
    "search_text", "find_files", "run_command", "project_tree",
    "python_check", "git_status", "git_diff", "git_publish",
    "app_screenshot", "capture_screen", "window_screenshot",
    "web_screenshot", "web_inspect", "browser_open", "search_web",
    "memory_search", "memory_save", "rag_search", "rag_index",
    "find_tools", "load_tools", "run_tool", "social_post", "voice_speak",
    "bench_run", "inspect_screenshot_regions", "analyze_visual_difference",
]


class TestRouterNarrows(unittest.TestCase):
    """Роутер дає лише потрібні інструменти — але ніколи не нуль."""

    def test_conversation_gets_minimum(self) -> None:
        sel = tool_select.select_names(available=AVAILABLE, text="привіт",
                                       intent_type="converse")
        self.assertLessEqual(len(sel.names), 8,
                             f"на розмову пішло {len(sel.names)} інструментів")
        self.assertNotIn("git_publish", sel.names,
                         "для привітання не потрібні публікації")

    def test_never_empty(self) -> None:
        """Навіть на порожній запит лишається шлях до інструментів."""
        for text in ("", "абракадабра", "???"):
            with self.subTest(text=text):
                sel = tool_select.select_names(available=AVAILABLE, text=text)
                self.assertTrue(sel.names, "набір не має бути порожнім")

    def test_control_tools_always_present(self) -> None:
        """``run_tool`` — гарантія досяжності решти інструментів."""
        for text, intent in (("привіт", "converse"),
                             ("запусти тести", "run"),
                             ("виправ помилку", "edit")):
            with self.subTest(text=text):
                sel = tool_select.select_names(
                    available=AVAILABLE, text=text, intent_type=intent)
                for name in tool_select.CONTROL:
                    self.assertIn(name, sel.names,
                                  f"{name} зник — решта інструментів стала недосяжною")

    def test_profiles_differ_by_task(self) -> None:
        talk = tool_select.select_names(available=AVAILABLE, text="привіт",
                                        intent_type="converse")
        edit = tool_select.select_names(available=AVAILABLE,
                                        text="виправ помилку в server.py",
                                        intent_type="edit")
        run = tool_select.select_names(available=AVAILABLE,
                                       text="запусти тести",
                                       intent_type="run")
        self.assertNotEqual(talk.names, edit.names)
        self.assertIn("edit_file", edit.names)
        self.assertIn("run_command", run.names)
        self.assertLess(len(talk.names), len(edit.names),
                        "розмова має бути дешевшою за правку коду")

    def test_requested_tool_by_name_is_kept(self) -> None:
        """Якщо у фразі названо скріншот — інструменти знімка мусять бути."""
        sel = tool_select.select_names(
            available=AVAILABLE, text="зроби скріншот екрана",
            intent_type="inspect")
        self.assertTrue(
            {"capture_screen", "app_screenshot"} & set(sel.names),
            f"просили скріншот, а набору немає: {sel.names}")

    def test_unknown_names_are_ignored(self) -> None:
        """Роутер не вигадує назв, яких немає в реєстрі."""
        sel = tool_select.select_names(
            available=AVAILABLE, text="запусти тести й зроби каву",
            intent_type="run")
        self.assertTrue(set(sel.names) <= set(AVAILABLE), sel.names)

    def test_via_intent_hints(self) -> None:
        """Підказки ``tool_router`` також розширюють набір."""

        class Hint:
            tool = "memory_search"

        sel = tool_select.select_names(
            available=AVAILABLE, text="що ми вирішили раніше?",
            intent_type="converse", hints=[Hint()])
        self.assertIn("memory_search", sel.names)

    def test_limit_keeps_control_tools(self) -> None:
        """Обмеження кількості не сміє викинути ``run_tool``."""
        sel = tool_select.select_names(
            available=AVAILABLE, text="виправ і запусти", intent_type="edit",
            limit=6)
        self.assertLessEqual(len(sel.names), 6)
        for name in tool_select.CONTROL:
            self.assertIn(name, sel.names)

    def test_previous_turn_tools_survive(self) -> None:
        """Набір попереднього ходу лишається — завдання багатокрокове."""
        sel = tool_select.select_names(
            available=AVAILABLE, text="тепер перевір", intent_type="inspect",
            previous=["web_inspect"])
        self.assertIn("web_inspect", sel.names)


class TestHotQueue(unittest.TestCase):
    """Гаряче додавання: запит під час роботи не губиться."""

    def setUp(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        self.root.withdraw()
        fonts = theme.Theme(self.root)
        fonts.apply()
        self.panel = ChatPanel(self.root, fonts, Settings(),
                               ToolRegistry(ROOT))
        self.panel.pack()

    def tearDown(self) -> None:
        import gc

        self.panel = None
        gc.collect()
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_busy_agent_queues_instead_of_refusing(self) -> None:
        """Зайнятий агент не відмовляє — запит стає в чергу."""
        class BusyRunner:
            busy = True
            session = None

        self.panel.attach_runner(BusyRunner())
        started = self.panel._send("уточнення під час роботи")
        self.assertFalse(started, "робота ще не почалась — агент зайнятий")
        self.assertEqual(self.panel.hot_pending, 1,
                         "запит мусив потрапити в гарячу чергу")

    def test_queue_returns_in_order(self) -> None:
        class BusyRunner:
            busy = True
            session = None

        self.panel.attach_runner(BusyRunner())
        self.panel._send("перший")
        self.panel._send("другий")
        self.assertEqual(self.panel.take_hot_request(), "перший")
        self.assertEqual(self.panel.take_hot_request(), "другий")
        self.assertEqual(self.panel.take_hot_request(), "",
                         "черга має спорожніти")

    def test_queue_has_limit(self) -> None:
        from blackchpok_ide import chat_panel

        class BusyRunner:
            busy = True
            session = None

        self.panel.attach_runner(BusyRunner())
        for index in range(chat_panel.HOT_QUEUE_LIMIT + 3):
            self.panel._send(f"запит {index}")
        self.assertEqual(self.panel.hot_pending, chat_panel.HOT_QUEUE_LIMIT,
                         "черга не має рости безкінечно")


class TestContextFreeing(unittest.TestCase):
    """Автозвільнення ПЕРЕНОСИТЬ контекст у пам'ять, а не викидає."""

    def _runner(self, *, window: int = 4096, messages: int = 40):
        from blackchpok_ide import agent as agent_module
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import Settings

        settings = Settings()
        runner = agent_module.AgentRunner(
            ToolRegistry(ROOT), settings.llm, settings.agent, ROOT)
        runner.set_context_limit(window)
        for index in range(messages):
            runner.session.add_user(f"повідомлення {index} " + "текст " * 40)
            runner.session.add_assistant(
                {"role": "assistant", "content": f"відповідь {index} " + "дані " * 40})
        return runner

    def test_evicted_messages_reach_memory(self) -> None:
        runner = self._runner()
        archived: list[list] = []
        runner._archive_evicted_context = lambda items: archived.append(list(items))
        removed = runner._evict_oldest_for_compact(share=0.5)
        self.assertTrue(removed, "нічого не витіснено")
        self.assertTrue(archived, "витіснене НЕ пішло в пам'ять — контекст втрачено")
        self.assertEqual(len(archived[0]), len(removed))

    def test_freeing_shrinks_history(self) -> None:
        runner = self._runner()
        before = len(runner.session.messages)
        runner._archive_evicted_context = lambda items: None
        runner.auto_free_context()
        self.assertLess(len(runner.session.messages), before,
                        "вікно не звільнилось")

    def test_small_history_is_left_alone(self) -> None:
        """Коротку розмову не чіпаємо — звільняти нічого."""
        runner = self._runner(messages=3)
        before = len(runner.session.messages)
        runner._archive_evicted_context = lambda items: None
        self.assertEqual(runner.auto_free_context(), 0)
        self.assertEqual(len(runner.session.messages), before)

    def test_last_messages_survive(self) -> None:
        """Останні репліки лишаються: без них модель не знає, про що йдеться."""
        runner = self._runner()
        runner._archive_evicted_context = lambda items: None
        last = runner.session.messages[-1]
        runner._evict_oldest_for_compact(share=0.9)
        self.assertIn(last, runner.session.messages,
                      "витіснення з'їло останню репліку")

    def test_private_mode_writes_nothing(self) -> None:
        """Приватний режим: звільняємо, але НІЧОГО не пишемо в пам'ять."""
        runner = self._runner()
        runner.state.private = True
        bridge_calls: list = []
        runner.memory_bridge = type(
            "Bridge", (), {"archive_messages": lambda self, m, task="": bridge_calls.append(m)})()
        runner._evict_oldest_for_compact(share=0.5)
        self.assertEqual(bridge_calls, [],
                         "приватний режим не має писати в довгострокову пам'ять")


class TestScrollToBottomButton(unittest.TestCase):
    """Кнопка «вниз» по центру стрічки (вимога 21.11.2026).

    Потрібна в довгому чаті: користувач читає відповідь вище, а нові
    повідомлення приходять знизу. Раніше єдиним способом повернутись було
    смикати колесо або тягнути смугу прокрутки.
    """

    def setUp(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        self.root.geometry("900x500+40+40")
        fonts = theme.Theme(self.root)
        fonts.apply()
        host = tk.Frame(self.root)
        host.pack(fill="both", expand=True)
        self.panel = ChatPanel(host, fonts, Settings(), ToolRegistry(ROOT),
                               composer_parent=host)
        self.panel.pack(fill="both", expand=True)
        for index in range(25):
            self.panel._add_assistant(
                f"Повідомлення {index}: " + "текст для висоти " * 20)
        self.root.update_idletasks()
        for _ in range(8):
            self.root.update()

    def tearDown(self) -> None:
        import gc

        self.panel = None
        gc.collect()
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_button_exists(self) -> None:
        self.assertTrue(hasattr(self.panel, "scroll_to_bottom_btn"))
        self.assertTrue(self.panel.scroll_to_bottom_btn.winfo_exists())

    def test_hidden_when_already_at_bottom(self) -> None:
        """Кнопка не потрібна, коли прокручувати нічого."""
        self.panel._jump_to_bottom()
        self.root.update()
        self.assertFalse(self.panel.scroll_to_bottom_btn.winfo_ismapped(),
                         "кнопка висіла, хоч стрічка вже внизу")

    def test_appears_after_scrolling_up(self) -> None:
        self.panel.scroll.canvas.yview_moveto(0.0)
        self.root.update_idletasks()
        self.root.update()
        self.panel._update_bottom_button()
        self.root.update()
        self.assertTrue(self.panel.scroll_to_bottom_btn.winfo_ismapped(),
                        "прокрутили вгору — кнопка мусила з'явитись")

    def test_jump_returns_to_bottom(self) -> None:
        self.panel.scroll.canvas.yview_moveto(0.0)
        self.root.update()
        self.panel._jump_to_bottom()
        self.root.update()
        first, last = self.panel.scroll.canvas.yview()
        self.assertGreaterEqual(float(last), 0.99,
                                "прокрутка не дійшла до низу")
        self.assertFalse(self.panel.scroll_to_bottom_btn.winfo_ismapped(),
                         "після стрибка вниз кнопка мусила сховатись")


class TestContractSurvives(unittest.TestCase):
    """Механізми нескінченного чату не можна вирізати «за компанію».

    Цей клас — сторож контракту ``docs/ENDLESS_CHAT.md``. Він перевіряє
    НАЯВНІСТЬ методів і зв'язок між ними, а не деталі реалізації: мета —
    щоб майбутній рефакторинг не прибрав механізм мовчки.

    Історія: попередні агенти вже вирізали хардкодом відповідь моделі,
    забороняли інструменти в режимі «Чат» і викидали історію без
    архівування. Кожен пункт нижче — саме такий випадок.
    """

    def test_agent_keeps_context_freeing(self) -> None:
        from blackchpok_ide.agent import AgentRunner

        for name in ("auto_free_context", "_evict_oldest_for_compact",
                     "_archive_evicted_context", "_live_context_window",
                     "_select_schemas", "_answer_budget"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(AgentRunner, name),
                                f"{name} зник — контракт ENDLESS_CHAT.md порушено")

    def test_chat_panel_keeps_hot_queue(self) -> None:
        from blackchpok_ide.chat_panel import ChatPanel

        for name in ("_queue_hot", "take_hot_request", "_run_hot_next"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(ChatPanel, name),
                                f"{name} зник — гаряче додавання зламано")

    def test_eviction_calls_archive(self) -> None:
        """Витіснення ЗОБОВ'ЯЗАНЕ кликати архівування — інакше це втрата."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._evict_oldest_for_compact)
        self.assertIn("_archive_evicted_context", source,
                      "витіснення без архівування = втрата контексту")

    def test_auto_free_runs_before_each_turn(self) -> None:
        """Автозвільнення мусить бути в циклі ходу, а не лише в /стиснути."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._loop)
        self.assertIn("auto_free_context", source,
                      "автозвільнення прибрано з циклу — чат знову скінченний")

    def test_archive_uses_all_three_storages(self) -> None:
        """Хроніка + NEUROMESH + RAG — усі три, а не одне замість інших."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._archive_evicted_context)
        self.assertIn("digest", source, "хроніка зникла з архівування")
        self.assertIn("memory_bridge", source, "NEUROMESH зник з архівування")
        self.assertIn("_archive_to_rag", source, "RAG зник з архівування")

    def test_context_probe_is_off_main_thread(self) -> None:
        """Проба вікна не має блокувати відповідь (55 с на живому Deploy)."""
        import inspect

        from blackchpok_ide import agent as agent_module

        source = inspect.getsource(agent_module._start_live_probe)
        self.assertIn("threading.Thread", source,
                      "проба стала синхронною — відповідь знову чекатиме")

    def test_docs_contract_exists(self) -> None:
        """Документ-контракт лежить у репозиторії й згадує ключові механізми."""
        doc = ROOT / "docs" / "ENDLESS_CHAT.md"
        self.assertTrue(doc.exists(), "docs/ENDLESS_CHAT.md зник")
        text = doc.read_text(encoding="utf-8")
        for marker in ("автоочищення", "NEUROMESH", "RAG", "гаряче",
                       "самонавчання", "роутер"):
            with self.subTest(marker=marker):
                self.assertIn(marker.lower(), text.lower(),
                              f"контракт не згадує «{marker}»")


if __name__ == "__main__":
    unittest.main(verbosity=2)
