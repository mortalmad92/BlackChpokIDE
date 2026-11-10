"""Регресії етапу «стабілізація»: правило доказів і справжні перевірки.

Кожен тест тут виріс із ЗНАЙДЕНОГО дефекту в аудиті, а не з припущення.
Фіксуємо саме те, що було зламано, щоб воно не повернулось:

* правило «немає доказу — немає твердження» пропускало вигадку;
* small talk обходив правило доказів;
* обрізання за токенами не виявлялось;
* значок можливостей ставився без тесту;
* DOM-міст був відкритий для будь-якого сайту;
* наглядач MCP смикав сервер, що падає циклом;
* ``capture_region`` знімав область не того розміру.

Запуск: python -m unittest tests.test_stabilization_regressions -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-stab-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

from blackchpok_ide import evidence, model_verify, multiscale, permissions  # noqa: E402


class TestEvidenceRefusesSubstringNumbers(unittest.TestCase):
    """«12 файлів» не має підтверджуватись доказом «line 120».

    Дефект. ``_covers`` порівнював числа ЯК ПІДРЯДОК, тому вигадане число
    проходило перевірку, якщо траплялось усередині іншого числа в доказі.
    """

    def test_number_must_match_whole(self) -> None:
        items = [evidence.Evidence("read_file", True, "line 120 has TODO")]
        result = evidence.check("У проєкті 12 файлів", items)
        self.assertFalse(result.supported, result.summary())

    def test_same_number_in_evidence_passes(self) -> None:
        items = [evidence.Evidence("list_dir", True, "усього 12 файлів")]
        result = evidence.check("У проєкті 12 файлів", items)
        self.assertTrue(result.supported, result.summary())


class TestEvidenceNoSilentPass(unittest.TestCase):
    """Факт без жодного виклику інструмента — це вигадка, а не «Готово».

    Дефект. Якщо класифікатор не бачив запиту «про проєкт», а модель усе
    одно називала число, перевірка повертала ``supported=True``.
    """

    def test_fact_without_any_tool_is_unsupported(self) -> None:
        result = evidence.check("У проєкті 300 файлів", [])
        self.assertFalse(result.supported)
        self.assertTrue(result.unsupported)

    def test_plain_answer_is_still_fine(self) -> None:
        result = evidence.check("Готово.", [])
        self.assertTrue(result.supported)

    def test_opinion_is_not_a_claim(self) -> None:
        result = evidence.check("Раджу використати кеш.", [])
        self.assertTrue(result.supported)

    def test_opinion_prefix_does_not_hide_a_number(self) -> None:
        """«Потрібно знати: у проєкті 300 файлів» — усе одно факт."""
        result = evidence.check("Потрібно знати: у проєкті 300 файлів.", [])
        self.assertFalse(result.supported)


class TestEvidenceNeedsToolsWordBoundaries(unittest.TestCase):
    """Маркери «порт» і «стан» не мають спрацьовувати всередині слів."""

    def test_sport_site_is_not_a_port_question(self) -> None:
        self.assertFalse(evidence.needs_tools_for("зроби спорт-сайт"))

    def test_server_state_is_a_fact_question(self) -> None:
        self.assertTrue(evidence.needs_tools_for("який стан сервера"))

    def test_compare_is_a_fact_question(self) -> None:
        self.assertTrue(evidence.needs_tools_for("порівняй два скрипти"))

    def test_counting_is_a_fact_question(self) -> None:
        self.assertTrue(evidence.needs_tools_for("скільки файлів у проєкті"))


class TestVisualEvidenceCounts(unittest.TestCase):
    """Скріншот — це теж доказ про проєкт (пункт «зорова перевірка»)."""

    def test_screenshot_provides_evidence(self) -> None:
        items = [evidence.Evidence("capture_screen", True,
                                   "Скріншот 100×100: C:/a.png")]
        result = evidence.check("Панель видно", items,
                                requires_project_fact=True)
        self.assertTrue(result.has_project_evidence, result.summary())


class TestSmallTalkCannotBypassEvidenceRule(unittest.TestCase):
    """Коротке питання про факти не має йти шляхом «розмови».

    Дефект. Перевірка ``_is_small_talk()`` стояла ПЕРЕД правилом доказів,
    тож «скільки файлів?» з тілом до 200 символів могло піти без
    інструментів — умова правила була для цього класу мертвою.
    """

    def test_order_in_source(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._run)
        forced = source.index("forced_tools = evidence_module.needs_tools_for")
        small = source.index("if self._is_small_talk() and not forced_tools")
        self.assertLess(forced, small,
                        "правило доказів має стояти ДО перевірки розмови")

    def test_small_talk_guard_is_explicit(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._run)
        self.assertIn("and not forced_tools", source)


class TestTruncationByTokensIsDetected(unittest.TestCase):
    """Обрізання за ``finish_reason=length`` має визнаватись обрізанням."""

    def test_finish_reason_length_is_truncated(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._enforce_evidence)
        self.assertIn("finish_reason", source)
        self.assertIn("length", source)

    def test_last_step_boundary_is_not_always_truncated(self) -> None:
        """Межа кроків не має позначати ПОВНУ відповідь обрізаною."""
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._enforce_evidence)
        self.assertNotIn("step >= self.max_steps - 1", source)


class TestVisionVerificationNeedsEvidence(unittest.TestCase):
    """Зір не можна «підтвердити» без еталона або на відмові моделі."""

    def test_no_expected_means_no_pass(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="bchp-vv-"))
        image = folder / "t.png"
        image.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
            b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        client = model_verify.Client("http://x/v1", "m")
        result = model_verify.test_vision(client, image, expected=())
        self.assertFalse(result.ok,
                         "без еталона зір не може бути зеленим")

    def test_number_must_be_whole(self) -> None:
        self.assertTrue(model_verify._mentions_number("Відповідь: 5", 5))
        self.assertFalse(model_verify._mentions_number("25 яблук", 5))
        self.assertFalse(model_verify._mentions_number("150", 5))


class TestCudaTestExists(unittest.TestCase):
    """ТЗ вимагає окремий тест CUDA — і він має бути в прогоні."""

    def test_cuda_is_registered(self) -> None:
        import inspect

        from blackchpok_ide import model_verify

        self.assertTrue(callable(getattr(model_verify, "test_cuda", None)))
        source = inspect.getsource(model_verify.run_all)
        self.assertIn('"cuda"', source)

    def test_cuda_without_gpu_is_skipped_not_failed(self) -> None:
        class NoGpu:
            backend = "cpu"
            gpu_name = ""
            vram_gb = 0.0

        result = model_verify.test_cuda(NoGpu())
        self.assertEqual(result.status, model_verify.SKIPPED)


class TestDomBridgePermission(unittest.TestCase):
    """DOM-міст: локальна сторінка — так, зовнішня — лише з дозволом."""

    def _registry(self, url: str, *, allow: bool = False):
        from blackchpok_ide.agent_tools import ToolRegistry, ToolError

        class Session:
            def page_url(self):
                return url

        registry = ToolRegistry(ROOT)
        registry.cdp_provider = lambda: Session()
        registry.allow_external_page_inspection = allow
        return registry, ToolError

    def test_local_page_allowed(self) -> None:
        registry, _ = self._registry("http://127.0.0.1:8000/")
        self.assertIsNotNone(registry._session())

    def test_external_page_blocked_by_default(self) -> None:
        registry, error = self._registry("https://example.com/private")
        with self.assertRaises(error):
            registry._session()

    def test_external_page_allowed_with_opt_in(self) -> None:
        registry, _ = self._registry("https://example.com/", allow=True)
        self.assertIsNotNone(registry._session())


class TestScreenshotRectUsesSize(unittest.TestCase):
    """``capture_region`` має знімати область ЗАДАНОГО розміру.

    Дефект. ``rect`` передавався як ``(x, y, ширина, висота)``, а Win32
    чекає межі ``(left, top, right, bottom)``: область 300×200 виходила
    200×100, і ніщо про це не повідомляло.
    """

    def test_rect_from_size(self) -> None:
        from blackchpok_ide import screenshot

        self.assertEqual(screenshot.rect_from_size(100, 100, 300, 200),
                         (100, 100, 400, 300))

    def test_region_tool_passes_bounds(self) -> None:
        import inspect

        from blackchpok_ide.agent_tools import ToolRegistry

        source = inspect.getsource(ToolRegistry.capture_region)
        self.assertIn("rect_from_size", source)

    def test_region_size_matches_request(self) -> None:
        """Реальний знімок: розмір файлу має дорівнювати запитаному."""
        from blackchpok_ide import screenshot

        if not screenshot.IS_WINDOWS:
            self.skipTest("скріншоти лише на Windows")
        from blackchpok_ide.agent_tools import ToolRegistry

        registry = ToolRegistry(ROOT)
        out = registry.capture_region(0, 0, 200, 150)
        self.assertIn("200×150", out, out)


class TestMultiscaleLabelsUseCentre(unittest.TestCase):
    """Підпис ділянки має відповідати її центру, а не лівому верхньому куту."""

    def test_bottom_tile_is_not_top(self) -> None:
        label = multiscale._label_for(0, 416, 1024, 1440,
                                      box=(0, 416, 1024, 1440))
        self.assertNotIn("верх", label, label)

    def test_origin_size_in_caption(self) -> None:
        region = multiscale.Region("a.png", 0, 416, 1024, 1024,
                                   label="лівий низ",
                                   origin_width=3440, origin_height=1440)
        caption = multiscale.region_caption(region, total=8, index=5)
        self.assertIn("3440×1440", caption)
        self.assertIn("не розібрано", caption)

    def test_merge_report_keeps_coordinates(self) -> None:
        text = multiscale.merge_report([
            {"label": "лівий верх", "box": (0, 0, 1024, 1024),
             "text": "Кнопка «Зберегти»"},
            {"label": "правий низ", "box": (2416, 416, 3440, 1440),
             "text": "напис не розібрано"},
        ])
        self.assertIn("(0,0)", text)
        self.assertIn("(2416,416)", text)
        self.assertIn("Нерозбірливі", text)


class TestPermissionsBlockMcpWrites(unittest.TestCase):
    """Режим «лише читання» має закривати MCP-запис.

    Дефект. Порівнювався лише «хвіст» назви, а ``MCP_MUTATING`` містить
    назви з префіксом ``router:`` — тому ``mcp__router__save_rule``
    проходив у режимі лише читання.
    """

    def test_mcp_save_rule_blocked(self) -> None:
        decision = permissions.check_tool(
            "mcp__router__save_rule", {}, mode=permissions.READ_ONLY, root=ROOT)
        self.assertFalse(decision.allowed, decision.reason)

    def test_mcp_write_and_delete_blocked(self) -> None:
        for name in ("mcp__fs__write", "mcp__fs__delete"):
            with self.subTest(name=name):
                decision = permissions.check_tool(
                    name, {}, mode=permissions.READ_ONLY, root=ROOT)
                self.assertFalse(decision.allowed, decision.reason)

    def test_mcp_read_allowed(self) -> None:
        decision = permissions.check_tool(
            "mcp__fs__read", {}, mode=permissions.READ_ONLY, root=ROOT)
        self.assertTrue(decision.allowed, decision.reason)


class TestGpuFailureDetection(unittest.TestCase):
    """Типовий збій CUDA має впізнаватись, а успішний лог — ні."""

    def test_real_cuda_failures_detected(self) -> None:
        from blackchpok_ide import runtime

        for line in (
            "ggml_cuda_init: failed to initialize CUDA: no CUDA-capable device is detected",
            "Failed to load ggml-cuda.dll",
            "CUDA driver version is insufficient for CUDA runtime version",
            "CUDA error: out of memory",
        ):
            with self.subTest(line=line[:40]):
                self.assertTrue(runtime.is_gpu_failure(line), line)

    def test_healthy_log_is_not_a_failure(self) -> None:
        from blackchpok_ide import runtime

        for line in (
            "ggml_backend_cuda_init: found 1 CUDA devices",
            "load_backend: loaded CUDA backend from C:/x/ggml-cuda.dll",
            "cuda device 0: NVIDIA GeForce RTX 3060",
        ):
            with self.subTest(line=line[:40]):
                self.assertFalse(runtime.is_gpu_failure(line), line)


class TestNativeFailureIsNotSuccess(unittest.TestCase):
    """Повідомлення про збій власного рушія не має виглядати як успіх."""

    def test_prefix_differs_from_success(self) -> None:
        from blackchpok_ide import main_window as window

        prefix = window.NATIVE_FAILURE_PREFIX
        success = "власний рушій: qwen.gguf · ctx 8192"
        self.assertFalse(success.startswith(prefix),
                         "успіх не має вважатись збоєм")

    def test_startup_falls_back_to_server(self) -> None:
        import inspect

        from blackchpok_ide import main_window as window

        source = inspect.getsource(window.BlackChpokIDE._autostart_local_model)
        self.assertIn("NATIVE_FAILURE_PREFIX", source)


class TestMcpStartAfterModel(unittest.TestCase):
    """MCP має стартувати ПІСЛЯ моделі, а не раніше."""

    def test_order_in_startup(self) -> None:
        import inspect

        from blackchpok_ide import main_window as window

        source = inspect.getsource(window.BlackChpokIDE._startup)
        auto = source.index("_auto_setup_in_background")
        mcp = source.index("_load_mcp_if_not_started")
        self.assertLess(auto, mcp,
                        "автозапуск моделі має йти перед стартом MCP")

    def test_started_result_is_used(self) -> None:
        import inspect

        from blackchpok_ide import main_window as window

        source = inspect.getsource(window.BlackChpokIDE._after_auto_setup)
        self.assertIn('result.get("started")', source)


class TestMcpDiagnosticsReachable(unittest.TestCase):
    """Діагностика наглядача має бути доступна з панелі."""

    def test_panel_has_diagnostics_button(self) -> None:
        import inspect

        from blackchpok_ide import mcp_panel

        source = inspect.getsource(mcp_panel.McpPanel._build)
        self.assertIn("Діагностика", source)
        self.assertTrue(hasattr(mcp_panel.McpPanel, "show_diagnostics"))

    def test_panel_start_is_supervised(self) -> None:
        import inspect

        from blackchpok_ide import mcp_panel

        source = inspect.getsource(mcp_panel.McpPanel.load_from_workspace)
        self.assertIn("remember", source)


class TestWatchdogSuspectWindow(unittest.TestCase):
    """Сервер, що падає циклом, не має перезапускатись без паузи."""

    def test_recent_restart_is_not_retried(self) -> None:
        import time

        from blackchpok_ide import mcp_watch

        class Manager:
            servers = {}

            def add(self, config, start=True):  # pragma: no cover - не має викликатись
                raise AssertionError("здоровий сервер не чіпаємо")

        watcher = mcp_watch.Watcher(Manager())
        config = type("C", (), {"name": "s"})()
        watcher.remember([config])
        health = mcp_watch.Health(name="s", ok=False, status=mcp_watch.DEAD)
        watcher._restarted_at["s"] = time.time()
        self.assertFalse(watcher._recover("s", object(), health))
        self.assertIn("цикл падінь", health.last_error)


class TestDisclaimerShowsRealCount(unittest.TestCase):
    """Попередження має показати СПРАВЖНЮ кількість, а не лише докір.

    Наживо модель назвала 100/170/211/310 файлів при справжніх 118.
    Правило ловило вигадку, але користувач не дізнавався правильного
    числа — мусив питати ще раз.
    """

    def test_counts_extracted_from_tools(self) -> None:
        items = [
            evidence.Evidence(
                "list_dir", True,
                "blackchpok_ide — 121 записів (файлів 118, тек 3)\n"
                "Підсумок за типами: .py: 118"),
            evidence.Evidence("find_files", True, "a.py\n— усього: 141"),
        ]
        counts = dict((value, label) for label, value in
                      evidence.evidence_counts(items))
        self.assertIn("118", counts)
        self.assertIn("141", counts)
        # Мітка каже, ЗВІДКИ число: інакше 118 і 314 виглядають як
        # суперечність.
        self.assertIn("list_dir", counts["118"])

    def test_disclaimer_mentions_correct_count(self) -> None:
        items = [evidence.Evidence(
            "list_dir", True,
            "blackchpok_ide — 121 записів (файлів 118, тек 3)\n"
            "Підсумок за типами: .py: 118")]
        result = evidence.check("У теці є 100 Python-файлів.", items)
        note = evidence.disclaimer(result,
                                   known_counts=evidence.evidence_counts(items))
        self.assertIn("118", note)
        self.assertIn("не можна вірити", note)

    def test_truncated_listing_reports_total(self) -> None:
        """«показано 5 з 30» — загальна кількість, а не показана."""
        items = [evidence.Evidence(
            "find_files", True,
            "a.py\n… показано 5 з 30 збігів (ліміт 5).")]
        values = [value for _label, value in evidence.evidence_counts(items)]
        self.assertIn("30", values)


class TestCountClaimsRequireExactNumber(unittest.TestCase):
    """Кількість у відповіді мусить дорівнювати числу з доказу.

    Дефект (знайдено живим прогоном). Агент відповів «У теці
    blackchpok_ide є 170 Python-файлів», доказ мав `118`, і перевірка
    все одно казала «усі твердження мають доказ»: широкий збіг за словами
    спрацьовував тому, що в доказі була тека `blackchpok_ide`.

    Друга половина дефекту: формулювання «170 Python-файлів» узагалі не
    розпізнавалось як факт, бо шаблон вимагав число впритул до предмета.
    """

    def _evidence(self, count: int):
        return [evidence.Evidence(
            "find_files", True,
            f"blackchpok_ide/agent.py\n— усього: {count}")]

    def test_wrong_count_is_rejected(self) -> None:
        result = evidence.check("У теці blackchpok_ide є 170 Python-файлів.",
                                self._evidence(118))
        self.assertFalse(result.supported, result.summary())

    def test_right_count_is_accepted(self) -> None:
        result = evidence.check("У теці blackchpok_ide є 118 Python-файлів.",
                                self._evidence(118))
        self.assertTrue(result.supported, result.summary())

    def test_count_with_intervening_word_is_a_claim(self) -> None:
        """«170 Python-файлів» — це кількість, а не просто опис."""
        self.assertTrue(evidence.factual_claims(
            "У теці blackchpok_ide є 170 Python-файлів."))

    def test_advice_still_needs_no_proof(self) -> None:
        result = evidence.check("Раджу перевірити ці 3 функції.", [])
        # Порада з числом — усе ж твердження про кількість, і без доказу
        # вона не має виглядати підтвердженою.
        self.assertFalse(result.supported, result.summary())


class TestFindFilesReportsTruncation(unittest.TestCase):
    """Обрізаний список файлів не має виглядати як повний.

    Дефект. ``find_files`` мовчки обрізав результат на ``limit`` рядках,
    і модель отримувала рівно 200 шляхів. На запит «скільки Python-файлів?»
    вона назвала «211» — вигадане число, яке виглядало підтвердженим,
    бо доказ справді існував.
    """

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-ff-"))
        for index in range(30):
            (self.folder / f"mod_{index:02d}.py").write_text("x = 1\n",
                                                             encoding="utf-8")

    def test_truncation_is_explicit(self) -> None:
        from blackchpok_ide.agent_tools import ToolRegistry

        registry = ToolRegistry(self.folder)
        out = registry.call("find_files", {"pattern": "*.py", "limit": 5})
        self.assertTrue(out.ok, out.output)
        self.assertIn("показано 5 з 30", out.output)
        self.assertIn("30", out.output.splitlines()[-1])

    def test_limit_zero_returns_all(self) -> None:
        from blackchpok_ide.agent_tools import ToolRegistry

        registry = ToolRegistry(self.folder)
        out = registry.call("find_files", {"pattern": "*.py", "limit": 0})
        lines = [line for line in str(out.output or "").splitlines()
                 if line.strip().endswith(".py")]
        self.assertEqual(len(lines), 30)

    def test_path_narrows_search(self) -> None:
        from blackchpok_ide.agent_tools import ToolRegistry

        sub = self.folder / "sub"
        sub.mkdir()
        (sub / "only.py").write_text("y = 2\n", encoding="utf-8")
        registry = ToolRegistry(self.folder)
        out = registry.call("find_files",
                            {"pattern": "*.py", "path": "sub", "limit": 0})
        paths = [line for line in str(out.output or "").splitlines()
                 if line.strip().endswith(".py")]
        self.assertEqual(len(paths), 1, out.output)
        self.assertIn("only.py", out.output)


class TestRouterDoesNotConfuseSkillWithCount(unittest.TestCase):
    """«Скільки файлів?» не має маршрутизуватись у ``read_skill``.

    Дефект. Правило шукало підрядок «скіл», а це початок слова
    «скільки». Тому на «Скільки Python-файлів у теці?» агент читав
    інструкцію скіла замість того, щоб порахувати файли — і кількості
    не отримував ніколи.
    """

    def test_counting_goes_to_list_dir(self) -> None:
        from blackchpok_ide import tool_router

        for phrase in ("Скільки Python-файлів у теці blackchpok_ide?",
                       "Скільки .py файлів у теці?",
                       "скільки файлів у проєкті"):
            with self.subTest(phrase=phrase):
                tools = [hint.tool for hint in tool_router.confident(phrase)]
                self.assertIn("list_dir", tools)
                self.assertNotIn("read_skill", tools)

    def test_real_skill_questions_still_work(self) -> None:
        from blackchpok_ide import tool_router

        self.assertEqual(
            [h.tool for h in tool_router.confident("покажи скіл tests")],
            ["read_skill"])
        self.assertIn("list_skills",
                      [h.tool for h in tool_router.confident("які є скіли")])


class TestToolCatalogCoversNewTools(unittest.TestCase):
    """Модель мусить знати про візуальні та DOM-інструменти."""

    def test_every_schema_is_in_catalog(self) -> None:
        from blackchpok_ide import tool_router
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        names = {item["function"]["name"] for item in TOOL_SCHEMAS}
        catalog = {name for name, _w, _e in tool_router.TOOL_CATALOG}
        catalog |= {name for name, _w, _e in tool_router.MCP_CATALOG}
        self.assertEqual(sorted(names - catalog), [])

    def test_visual_tools_survive_small_context(self) -> None:
        """На вікні 8192 токенів візуальні схеми не мають зникати."""
        from blackchpok_ide import agent

        visual = ("capture_screen", "inspect_screenshot_regions",
                  "dom_tree", "dom_console", "crop_screenshot")
        for name in visual:
            with self.subTest(name=name):
                self.assertIn(name, agent.SCHEMA_PRIORITY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
