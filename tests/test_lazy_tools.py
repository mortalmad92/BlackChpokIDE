"""Лінивий реєстр інструментів і єдине джерело стану сервера.

Що саме перевіряємо — не «функції існують», а поведінку, заради якої
механізми написані:

* компактний реєстр містить УСІ інструменти, але повних схем у запиті
  небагато;
* кожен інструмент ДОСЯЖНИЙ: ``find`` → ``load`` → виклик через ``run``;
* ``load_tools`` справді додає схему до наступного запиту;
* кеш інвалідовується, коли реєстр змінюється;
* стан сервера має ОДНЕ джерело, і зміна моделі скидає похідні числа.

Запуск: python -m unittest tests.test_lazy_tools -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import server_state, tool_lazy  # noqa: E402
from blackchpok_ide.agent import AgentRunner  # noqa: E402
from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402


def _runner(*, ctx: int = 16384) -> AgentRunner:
    runner = AgentRunner(ToolRegistry(ROOT), LLMSettings(),
                         AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = True
    if ctx:
        runner.adopt_context_window(props_ctx=ctx)
    return runner


def _names(schemas) -> set[str]:
    return {item["function"]["name"] for item in schemas}


class TestCompactRegistry(unittest.TestCase):
    """Компактний реєстр: усі інструменти видно, схем у запиті — мало."""

    def test_every_tool_is_in_registry(self) -> None:
        runner = _runner()
        runner.tool_schemas()
        state = runner.tool_registry_state()
        # Реєстр мусить знати про ВСІ вбудовані інструменти.
        self.assertGreaterEqual(state["total"], len(TOOL_SCHEMAS),
                                f"реєстр знає лише {state['total']}")

    def test_few_schemas_are_sent(self) -> None:
        """Головна мета: схем у запиті значно менше, ніж інструментів."""
        runner = _runner(ctx=16384)
        sent = _names(runner.tool_schemas())
        total = runner.tool_registry_state()["total"]
        self.assertLess(len(sent), total,
                        "мали передавати не всі схеми")
        self.assertLessEqual(len(sent), 22,
                             f"запит усе ще завеликий: {sorted(sent)}")

    def test_core_tools_are_always_present(self) -> None:
        """Без ядра агент не працює — воно мусить бути в кожному запиті."""
        runner = _runner(ctx=8192)
        sent = _names(runner.tool_schemas())
        for name in ("read_file", "write_file", "edit_file", "list_dir",
                     "search_text", "run_command"):
            with self.subTest(tool=name):
                self.assertIn(name, sent)

    def test_control_tools_are_present(self) -> None:
        """Без них лінивість стала б «недоступністю»."""
        runner = _runner(ctx=8192)
        sent = _names(runner.tool_schemas())
        for name in tool_lazy.CONTROL_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, sent)

    def test_large_window_sends_everything(self) -> None:
        """Коли місця достатньо — жодної зайвої церемонії."""
        router = tool_lazy.LazyToolRouter(priority=())
        schemas = TOOL_SCHEMAS[:10]
        lazy = router.update(schemas, budget_tokens=1_000_000)
        self.assertFalse(lazy, "малий набір не потребує лінивості")
        self.assertEqual(len(router.eager_schemas()), len(schemas))


class TestLazyAccess(unittest.TestCase):
    """Усі інструменти лишаються доступними (жодного не «сховано»)."""

    def test_find_locates_tool_by_ukrainian_word(self) -> None:
        runner = _runner()
        runner.tool_schemas()
        result = runner.call_tool("find_tools", {"query": "скріншот"})
        self.assertTrue(result.ok, result.output)
        self.assertIn("screenshot", result.output.lower())

    def test_find_reports_when_nothing_matches(self) -> None:
        runner = _runner()
        runner.tool_schemas()
        result = runner.call_tool("find_tools", {"query": "zzzz-невідомо"})
        self.assertFalse(result.ok)
        self.assertIn("не знайдено", result.output)

    def test_load_adds_schema_to_next_request(self) -> None:
        """Завантажена схема справді потрапляє в набір для моделі."""
        runner = _runner()
        before = _names(runner.tool_schemas())
        target = "web_audit"
        self.assertNotIn(target, before,
                         "тест має сенс лише коли схеми ще немає")
        loaded = runner.call_tool("load_tools", {"names": [target]})
        self.assertTrue(loaded.ok, loaded.output)
        after = _names(runner.tool_schemas())
        self.assertIn(target, after,
                      "load_tools не додав схему до запиту")

    def test_load_reports_unknown_names(self) -> None:
        """Вигадана назва не має проходити мовчки."""
        runner = _runner()
        runner.tool_schemas()
        result = runner.call_tool("load_tools",
                                  {"names": ["вигаданий_інструмент"]})
        self.assertFalse(result.ok)
        self.assertIn("вигаданий_інструмент", result.output)

    def test_run_executes_tool_without_loaded_schema(self) -> None:
        """Ключова властивість: виклик можливий БЕЗ завантаження схеми."""
        folder = Path(ROOT / "userdata" / "models")
        runner = _runner()
        sent = _names(runner.tool_schemas())
        target = "list_dir"
        # list_dir — ядро, тож для перевірки беремо інструмент поза ядром.
        target = "list_screenshots"
        self.assertNotIn(target, sent)
        result = runner.call_tool("run_tool",
                                  {"name": target, "arguments": {"limit": 1}})
        self.assertTrue(result.ok, result.output)

    def test_run_rejects_control_tool_recursion(self) -> None:
        runner = _runner()
        runner.tool_schemas()
        result = runner.call_tool("run_tool", {"name": "run_tool",
                                               "arguments": {}})
        self.assertFalse(result.ok, "рекурсія через run_tool неприпустима")

    def test_run_reports_unknown_tool(self) -> None:
        runner = _runner()
        runner.tool_schemas()
        result = runner.call_tool("run_tool", {"name": "неіснуючий",
                                               "arguments": {}})
        self.assertFalse(result.ok)
        self.assertIn("немає в реєстрі", result.output)

    def test_run_goes_through_permission_check(self) -> None:
        """Обхідний шлях не має обходити режим дозволів."""
        from blackchpok_ide import permissions

        runner = _runner()
        runner.permission_mode = permissions.READ_ONLY
        runner.tool_schemas()
        result = runner.call_tool("run_tool", {
            "name": "write_file",
            "arguments": {"path": "lazy-forbidden.txt", "content": "x"}})
        self.assertFalse(result.ok, "запис мав бути заблокований у READ_ONLY")


class TestRegistryCache(unittest.TestCase):
    """Кеш схем: інвалідація й відсутність застарілих даних."""

    def test_registry_change_drops_missing_tool(self) -> None:
        router = tool_lazy.LazyToolRouter()
        schemas = [{"type": "function",
                    "function": {"name": f"tool_{i}", "description": "d",
                                 "parameters": {"type": "object",
                                                "properties": {}}}}
                   for i in range(60)]
        router.update(schemas, budget_tokens=100)
        self.assertTrue(router.lazy)
        router.activate(["tool_59"])
        self.assertTrue(router.knows("tool_59"))
        # Інструмент зник (MCP перезапустився без нього).
        router.update(schemas[:-1], budget_tokens=100)
        self.assertFalse(router.knows("tool_59"),
                         "застаріла назва лишилась у реєстрі")

    def test_invalidate_clears_state(self) -> None:
        router = tool_lazy.LazyToolRouter()
        schemas = [{"type": "function",
                    "function": {"name": "read_file", "description": "d",
                                 "parameters": {"type": "object",
                                                "properties": {}}}}]
        router.update(schemas)
        router.activate(["read_file"])
        router.invalidate(reason="тест")
        self.assertEqual(router.total_count, 0)
        self.assertEqual(router.eager_schemas(), [])

    def test_no_duplicate_schemas(self) -> None:
        runner = _runner()
        names = [item["function"]["name"] for item in runner.tool_schemas()]
        self.assertEqual(len(names), len(set(names)), "є дублікати схем")

    def test_agent_invalidate_rebuilds(self) -> None:
        runner = _runner()
        before = _names(runner.tool_schemas())
        runner.invalidate_tool_cache(reason="тест")
        after = _names(runner.tool_schemas())
        self.assertEqual(before, after, "після інвалідації набір має той "
                                        "самий склад")


class TestPriorities(unittest.TestCase):
    """Пріоритети: ядро важливіше, але нижчі рівні не зникають."""

    def test_core_has_lowest_tier(self) -> None:
        router = tool_lazy.LazyToolRouter()
        router.update(TOOL_SCHEMAS, budget_tokens=500)
        cards = {card.name: card for card in router.find("", limit=999)}
        self.assertEqual(cards["read_file"].tier, tool_lazy.TIER_CORE)
        self.assertGreater(cards["capture_screen"].tier,
                           tool_lazy.TIER_CORE)

    def test_low_tier_tools_still_reachable(self) -> None:
        """Пріоритет не означає видалення."""
        router = tool_lazy.LazyToolRouter()
        router.update(TOOL_SCHEMAS, budget_tokens=500)
        found = router.find("capture_screen", limit=3)
        self.assertTrue(any(card.name == "capture_screen" for card in found),
                        "інструмент нижчого рівня не знаходиться")

    def test_skills_are_external_even_when_in_priority(self) -> None:
        """Скіли мусять лишатись TIER_EXTERNAL, навіть якщо є в SCHEMA_PRIORITY.

        Регресія, знайдена 10.11.2026. ``_tier_of`` перевіряв ``_priority``
        РАНІШЕ за список зовнішніх назв. ``agent.SCHEMA_PRIORITY`` містить
        ``list_skills`` і ``read_skill`` (додано, щоб їх не відрізало
        обрізання схем), тому вони діставали рівень «проєкт». А
        ``eager_schemas`` додає лише ``TIER_EXTERNAL`` — і при лінивості
        скіли ТИХО ЗНИКАЛИ зі схем. ``test_features`` ловив це як
        «агент бачить інструменти скілів — 15 інструментів».
        """
        for name in ("list_skills", "read_skill", "publish_social"):
            router = tool_lazy.LazyToolRouter(priority=(name, "read_file"))
            router.update(TOOL_SCHEMAS, budget_tokens=400)
            self.assertEqual(
                router._tier_of(name), tool_lazy.TIER_EXTERNAL,
                f"{name} має бути зовнішнім, а не «проєктним»")


class TestServerState(unittest.TestCase):
    """Стан сервера: одне джерело, чесні поля, інвалідація."""

    def test_dead_server_is_reported(self) -> None:
        state = server_state.probe_server("http://127.0.0.1:9/v1",
                                         timeout=0.4)
        self.assertFalse(state.reachable)
        self.assertFalse(state.online)
        self.assertTrue(state.error)
        self.assertIn("недоступний", state.note())

    def test_empty_url_is_not_online(self) -> None:
        state = server_state.probe_server("", timeout=0.2)
        self.assertFalse(state.reachable)
        self.assertIn("адреса", state.error)

    def test_cache_invalidate_keeps_no_fresh_numbers(self) -> None:
        cache = server_state.ServerStateCache()
        cache.invalidate(reason="тест")
        state = cache.snapshot()
        self.assertEqual(state.context, 0,
                         "після інвалідації свіжого контексту немає")

    def test_model_matching_is_normalised(self) -> None:
        """Різні позначення того самого файлу — це та сама модель."""
        self.assertTrue(server_state._models_match(
            "Qwen2.5-Coder-14B-Instruct-Q4_K_M",
            "qwen2.5-coder-14b-instruct-q4_k_m"))
        self.assertTrue(server_state._models_match(
            "C:/models/qwen2.5-coder-14b-instruct-q4_k_m.gguf",
            "qwen2.5-coder-14b-instruct-q4_k_m"))
        self.assertFalse(server_state._models_match(
            "qwen2.5-coder-14b", "Qwen3VL-8B-Instruct"))

    def test_snapshot_never_blocks(self) -> None:
        """``snapshot`` — без мережі: це гарантія для потоку інтерфейсу."""
        cache = server_state.ServerStateCache()
        started = __import__("time").perf_counter()
        for _ in range(50):
            cache.snapshot()
        elapsed = __import__("time").perf_counter() - started
        self.assertLess(elapsed, 0.2, "snapshot робить щось повільне")


class TestControlToolLabels(unittest.TestCase):
    """Журнал показує дію, а не сирий ідентифікатор.

    Регресія з аудиту: інструмент реально виконувався, а IDE показувала
    «⚙ find_tools» посеред українського тексту.
    """

    def test_control_tools_have_ukrainian_labels(self) -> None:
        import re

        from blackchpok_ide.work_log import TOOL_VIEWS, tool_view

        for name in tool_lazy.CONTROL_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, TOOL_VIEWS, f"{name}: немає підпису")
                _icon, label, _key = tool_view(name)
                self.assertTrue(re.search(r"[\u0400-\u04FF]", label),
                                f"{name}: підпис не українською — {label}")

    def test_control_label_keys_exist_in_schema(self) -> None:
        """Ключ аргумента мусить бути в СПРАВЖНІЙ схемі."""
        from blackchpok_ide import tool_specs
        from blackchpok_ide.work_log import TOOL_VIEWS

        specs = tool_specs.specs_for_schemas(tool_lazy.control_schemas())
        for name in tool_lazy.CONTROL_TOOLS:
            key = TOOL_VIEWS[name][2]
            if not key:
                continue
            with self.subTest(tool=name):
                self.assertIn(key, specs[name].parameters,
                              f"{name}: ключа «{key}» немає у схемі")


class TestSingleModelIdentity(unittest.TestCase):
    """Одна модель — один підпис у ВСІХ місцях інтерфейсу.

    Регресія зі скріншота користувача: шапка й панель контексту показували
    ``qwen2.5-coder-14b``, а пігулка в куті, композер і статус —
    ``Ministral-3-14B``. Причина: три різні шляхи оновлення підписів і
    розбіжність ``llm.model`` проти ``engine.model_path``.
    """

    def test_settings_fields_must_agree(self) -> None:
        """Якщо модель вибрана, шлях до файлу не може вказувати на іншу."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._on_chat_model_pick)
        self.assertIn("_adopt_model_path_for", source,
                      "вибір моделі мусить узгоджувати шлях до файлу")

    def test_adopt_model_path_clears_foreign_path(self) -> None:
        """Чужий шлях очищається, а не лишається «на памʼять»."""
        from blackchpok_ide.config import Settings

        class _Stub:
            """Мінімальний стенд: лише те, що потрібно функції."""

            def __init__(self) -> None:
                self.settings = Settings()
                self.settings.engine.model_path = ""

        stub = _Stub()
        method = __import__(
            "blackchpok_ide.main_window", fromlist=["BlackChpokIDE"]
        ).BlackChpokIDE._adopt_model_path_for
        # Невідома назва (хмарна модель) не має лишати локальний шлях.
        stub.settings.engine.model_path = str(
            ROOT / "userdata" / "models" / "qwen2.5-coder-14b-instruct-q4_k_m.gguf")
        method(stub, "gpt-4o-mini")
        self.assertEqual(stub.settings.engine.model_path, "",
                         "шлях іншої моделі лишився після вибору хмари")

    def test_one_sync_updates_every_label(self) -> None:
        """``_sync_model_labels`` торкається шапки, пігулки й композера."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._sync_model_labels)
        for target in ("header_bar", "header", "chat"):
            with self.subTest(target=target):
                self.assertIn(target, source,
                              f"підпис {target} не оновлюється єдиною точкою")

    def test_startup_path_uses_single_sync(self) -> None:
        """Старт теж ставить підпис в УСІ місця, а не лише в композер.

        Саме через це пігулка сесії назавжди лишалась «модель не вибрана».
        """
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._on_model_changed)
        self.assertIn("_sync_model_labels", source,
                      "старт не синхронізує всі підписи моделі")


class TestBriefContextPanel(unittest.TestCase):
    """Панель контексту не повторює той самий факт кількома рядками."""

    def test_context_rows_are_few(self) -> None:
        import inspect

        from blackchpok_ide import context_panel

        source = inspect.getsource(context_panel.ContextPanel._paint_budget_detail)
        labels = source.count("tk.Label(")
        self.assertLessEqual(labels, 2,
                             f"бюджет малюється {labels} рядками — зайве")

    def test_registry_reason_not_duplicated(self) -> None:
        """Причина лінивості не дублює вже показані числа."""
        import inspect

        from blackchpok_ide import context_panel

        source = inspect.getsource(context_panel.ContextPanel._paint_registry)
        self.assertNotIn('registry.get("reason")', source,
                         "причина реєстру дублюється в панелі; достатньо чисел")


class TestProjectorDetection(unittest.TestCase):
    """Проєктор зору не може вважатись моделлю (жодним способом)."""

    def test_official_mistral_naming(self) -> None:
        from blackchpok_ide.model_hub import is_projector_path

        self.assertTrue(is_projector_path(
            "Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf"))
        self.assertTrue(is_projector_path(
            "C:/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf"))
        self.assertFalse(is_projector_path(
            "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
