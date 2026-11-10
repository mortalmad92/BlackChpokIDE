"""Автоматичне регулювання контексту: регресії реального збою.

Що сталося насправді (лог користувача, відтворено):

```
--ctx-size 32768          ← попросили в IDE
launch_with_recovery → 16384   ← сам зменшив, щоб влізло у VRAM
settings.engine.ctx_size = 32768   ← ЛИШИЛОСЬ старим
65 схем інструментів ≈ 20 000 токенів
→ сервер обриває з'єднання (WinError 10054) одразу після заголовків
→ користувач бачить «модель не працює»
```

Після виправлення: вікно 32768 → 26 схем замість 65 → відповідь
«У теці blackchpok_ide є 120 файлів» (реально 120).

Ці тести фіксують:

* визначення СПРАВЖНЬОГО вікна з ``/props`` (а не з налаштувань);
* урахування метаданих GGUF (модель не вміє більше);
* розподіл бюджету на відповідь/історію/систему/схеми/запас;
* стискання історії до бюджету, а не «коли вже обірвалось»;
* обрізання схем під бюджет (65 → 26), із збереженням важливих;
* відкат на звичайний запит, коли стрім обірвався.

Запуск: python -m unittest tests.test_context_regulation -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-ctx-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

from blackchpok_ide import context_budget  # noqa: E402


class TestResolveWindow(unittest.TestCase):
    """Джерело правди — те, з чим сервер СПРАВДІ запущено."""

    def test_server_props_wins_over_settings(self) -> None:
        """``/props`` каже 16384, налаштування — 32768: віримо серверу.

        Саме ця розбіжність і ламала запити: агент надсилав промпт
        «за налаштуваннями», а сервер мав удвічі менше.
        """
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.engine.ctx_size = 32768
        window = context_budget.resolve_window(settings=settings,
                                               props_ctx=16384)
        self.assertEqual(window.tokens, 16384)
        self.assertTrue(window.measured)
        self.assertIn("props", window.source)

    def test_gguf_limits_server_window(self) -> None:
        """Модель не вміє більше за своє тренувальне вікно."""
        window = context_budget.resolve_window(props_ctx=131072,
                                               gguf_ctx=8192)
        self.assertEqual(window.tokens, 8192)

    def test_settings_used_when_server_silent(self) -> None:
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.engine.ctx_size = 8192
        window = context_budget.resolve_window(settings=settings)
        self.assertEqual(window.tokens, 8192)
        self.assertFalse(window.measured)

    def test_never_below_usable_minimum(self) -> None:
        window = context_budget.resolve_window(props_ctx=512)
        self.assertGreaterEqual(window.tokens,
                                context_budget.MIN_USABLE_WINDOW)

    def test_unknown_window_is_cautious(self) -> None:
        window = context_budget.resolve_window()
        self.assertGreater(window.tokens, 0)
        self.assertTrue(window.note, "невідоме вікно має бути позначене")


class TestBudgetPlan(unittest.TestCase):
    """Розподіл вікна: усе разом не перевищує вікно."""

    def test_parts_fit_inside_window(self) -> None:
        budget = context_budget.plan(16384, system_tokens=5000,
                                     tools_tokens=2000)
        total = (budget.answer + budget.history + budget.tools
                 + budget.system + budget.safety + budget.payload)
        self.assertLessEqual(total, 16384 + 1, budget.text())

    def test_answer_reserve_is_substantial(self) -> None:
        budget = context_budget.plan(16384)
        self.assertGreaterEqual(budget.answer, 256)
        self.assertGreaterEqual(budget.answer, int(16384 * 0.2))

    def test_overloaded_by_service_data_is_reported(self) -> None:
        """Якщо схеми й система самі з'їли вікно — це має бути видно."""
        budget = context_budget.plan(2048, system_tokens=1500,
                                     tools_tokens=1500)
        self.assertTrue(budget.notes, "переповнення службовими даними "
                                      "має бути позначене")

    def test_zero_window_gives_empty_budget(self) -> None:
        budget = context_budget.plan(0)
        self.assertEqual(budget.window, 0)


class TestFitMessages(unittest.TestCase):
    """Історія стискається ДО відправки, а не після обриву."""

    def test_long_history_is_trimmed(self) -> None:
        messages = [{"role": "user", "content": "слово " * 400}
                    for _ in range(20)]
        fitted = context_budget.fit_messages(messages, 2000)
        self.assertLess(len(fitted), len(messages))
        self.assertTrue(fitted, "хоч одне повідомлення мусить лишитись")

    def test_last_message_survives(self) -> None:
        """Найсвіже повідомлення — це сама задача, його губити не можна."""
        messages = [{"role": "user", "content": "старе " * 500}
                    for _ in range(10)]
        messages.append({"role": "user", "content": "САМА ЗАДАЧА"})
        fitted = context_budget.fit_messages(messages, 1200)
        self.assertIn("САМА ЗАДАЧА",
                      " ".join(str(item["content"]) for item in fitted))

    def test_short_history_untouched(self) -> None:
        messages = [{"role": "user", "content": "привіт"}]
        self.assertEqual(context_budget.fit_messages(messages, 8192), messages)


class TestEstimateTokens(unittest.TestCase):
    def test_cyrillic_costs_more_than_latin(self) -> None:
        cyr = context_budget.estimate_tokens("слово " * 100)
        lat = context_budget.estimate_tokens("word " * 100)
        self.assertGreater(cyr, lat)

    def test_exact_counter_used_when_given(self) -> None:
        result = context_budget.estimate_tokens("будь-що",
                                                counter=lambda _t: 42)
        self.assertGreaterEqual(result, 42)


class TestAgentUsesRealWindow(unittest.TestCase):
    """Агент визначає вікно сам і ріже схеми під нього."""

    def _runner(self, ctx_size: int = 32768):
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings, LLMSettings

        llm = LLMSettings()
        llm.model = "fake-model"
        llm.base_url = "http://127.0.0.1:9/v1"
        runner = AgentRunner(ToolRegistry(ROOT), llm, AgentSettings(), ROOT)
        runner.set_requested_context(ctx_size)
        return runner

    def test_window_adopted_from_props(self) -> None:
        runner = self._runner()
        budget = runner.adopt_context_window(props_ctx=16384, gguf_ctx=131072)
        self.assertEqual(budget.window, 16384)
        # Вікно живе в СЕСІЇ (звідти його читає смуга статистики й
        # стискання історії). У раннера окремого поля немає.
        self.assertEqual(runner.session.context_limit, 16384,
                         "сесія має отримати РЕАЛЬНЕ вікно, не з налаштувань")
        self.assertEqual(runner.stats.context_limit, 16384)

    def test_schemas_fit_into_budget(self) -> None:
        """65 схем не мають влазити у вікно 16K — зайві відкидаються."""
        runner = self._runner()
        runner.adopt_context_window(props_ctx=16384, gguf_ctx=131072)
        schemas = runner.tool_schemas()
        self.assertGreater(len(schemas), 0, "хоч якісь інструменти потрібні")
        self.assertLess(len(schemas), 65,
                        "схеми мусять бути обрізані під бюджет")

    def test_core_tools_survive_trimming(self) -> None:
        """Обрізання не має прибирати те, без чого агент не працює."""
        runner = self._runner()
        runner.adopt_context_window(props_ctx=16384, gguf_ctx=131072)
        names = {item["function"]["name"] for item in runner.tool_schemas()}
        for required in ("read_file", "write_file", "list_dir"):
            with self.subTest(tool=required):
                self.assertIn(required, names)

    def test_context_state_is_readable(self) -> None:
        runner = self._runner()
        runner.adopt_context_window(props_ctx=16384)
        state = runner.context_state()
        self.assertIn("вікно", state)
        self.assertIn("16", state.replace(" ", ""))


class TestStreamFallback(unittest.TestCase):
    """Обрив стріму не має завершувати хід — є звичайний запит."""

    def test_stream_failure_falls_back(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._ask)
        # Голий ``raise`` після LLMError — це і був дефект.
        self.assertNotIn("        except LLMError:\n            raise", source)
        self.assertIn("client.chat(messages", source)
        self.assertIn("fatal", source)

    def test_disconnect_is_explained(self) -> None:
        """``ConnectionResetError`` має стати зрозумілою помилкою."""
        import inspect

        from blackchpok_ide import llm_client

        source = inspect.getsource(llm_client.LLMClient.chat_stream)
        self.assertIn("ConnectionResetError", source)
        self.assertIn("обірвав", source)


class TestGgufContextReader(unittest.TestCase):
    """Вікно моделі читається з GGUF (не вгадується)."""

    def test_real_model_context(self) -> None:
        from blackchpok_ide import agent

        # Проєктор (mmproj) — не модель: у нього немає власного контексту,
        # і 0 для нього правильна відповідь. Беремо саме модель.
        models = [p for p in sorted((ROOT / "userdata" / "models").glob("*.gguf"))
                  if "mmproj" not in p.name.lower()]
        if not models:
            self.skipTest("немає GGUF-моделей")
        value = agent._gguf_context(str(models[0]))
        self.assertGreater(value, 0,
                           f"метадані {models[0].name} мусять читатись")

    def test_projector_has_no_context(self) -> None:
        """Проєктор зору — не модель, контексту в нього немає."""
        from blackchpok_ide import agent

        projectors = [p for p in (ROOT / "userdata" / "models").glob("*.gguf")
                      if "mmproj" in p.name.lower()]
        if not projectors:
            self.skipTest("немає файлів mmproj")
        self.assertEqual(agent._gguf_context(str(projectors[0])), 0)

    def test_missing_model_returns_zero(self) -> None:
        from blackchpok_ide import agent

        self.assertEqual(agent._gguf_context("no-such-model.gguf"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
