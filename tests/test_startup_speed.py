"""Тести швидкого запуску й видимості прихованих збоїв.

Дві речі, які тут зафіксовано:

1. **Панель «Зміни» не блокує запуск.** Раніше її конструктор синхронно
   обходив усі `.bak` (311 файлів = 4.8 с), тобто 85% часу старту
   припадало на роботу до першої появи вікна.
2. **Приховані збої не зникають безслідно.** У коді багато місць, де
   виняток ковтається; без лічильника «кнопка не працює» неможливо
   діагностувати.

Запуск: python -m unittest tests.test_startup_speed -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import diff_stats, safe  # noqa: E402


class TestDiffCache(unittest.TestCase):
    """Кеш diff за (mtime, size)."""

    def setUp(self) -> None:
        import shutil

        diff_stats.clear_cache()
        self.root = Path(tempfile.mkdtemp())
        self._cleanup = lambda: shutil.rmtree(self.root, ignore_errors=True)

    def tearDown(self) -> None:
        self._cleanup()
        diff_stats.clear_cache()

    def _make_pair(self, index: int, *, lines: int = 40) -> Path:
        target = self.root / f"m{index}.py"
        old = "\n".join(f"def f{j}(x): return x + {j}" for j in range(lines))
        target.write_text(old + f"\n# зміна {index}\n", encoding="utf-8")
        (self.root / f"m{index}.py.bak").write_text(old, encoding="utf-8")
        return target

    def test_second_scan_is_faster(self) -> None:
        for index in range(60):
            self._make_pair(index)
        started = time.perf_counter()
        first = diff_stats.detect_changes(self.root)
        t1 = time.perf_counter() - started
        started = time.perf_counter()
        second = diff_stats.detect_changes(self.root)
        t2 = time.perf_counter() - started
        self.assertEqual(len(first.files), 60)
        self.assertEqual(first.summary_text, second.summary_text)
        # Кеш має давати прискорення; запас у 1.5x, щоб тест не був крихким
        # на повільній машині.
        self.assertLess(t2, t1 / 1.5, f"{t1*1000:.0f} мс → {t2*1000:.0f} мс")

    def test_changed_file_is_recalculated(self) -> None:
        target = self._make_pair(0)
        diff_stats.detect_changes(self.root)
        # Змінюємо файл — diff має перерахуватись, а не взятись із кешу.
        content = target.read_text(encoding="utf-8")
        target.write_text(content + "# ще один рядок\n" * 5, encoding="utf-8")
        after = diff_stats.detect_changes(self.root)
        self.assertEqual(len(after.files), 1)
        self.assertGreaterEqual(after.files[0].added, 6)

    def test_deleted_target_is_cached_but_correct(self) -> None:
        target = self._make_pair(0)
        diff_stats.detect_changes(self.root)
        target.unlink()
        after = diff_stats.detect_changes(self.root)
        self.assertEqual(len(after.files), 1)
        self.assertEqual(after.files[0].status, "deleted")

    def test_clear_cache_resets(self) -> None:
        self._make_pair(0)
        diff_stats.detect_changes(self.root)
        diff_stats.clear_cache()
        after = diff_stats.detect_changes(self.root)
        self.assertEqual(len(after.files), 1)

    def test_cache_does_not_change_result(self) -> None:
        for index in range(20):
            self._make_pair(index)
        first = diff_stats.detect_changes(self.root)
        second = diff_stats.detect_changes(self.root)
        self.assertEqual([f.path for f in first.files], [f.path for f in second.files])
        self.assertEqual([f.total for f in first.files], [f.total for f in second.files])


class TestChangesPanelAsync(unittest.TestCase):
    """Панель не блокує конструктор."""

    def test_refresh_uses_thread(self) -> None:
        import inspect
        import textwrap

        from blackchpok_ide import changes_panel

        source = textwrap.dedent(inspect.getsource(changes_panel.ChangesPanel.refresh))
        self.assertIn("Thread", source, "скан має йти у фоні")

    def test_constructor_does_not_scan_synchronously_by_default(self) -> None:
        import inspect
        import textwrap

        from blackchpok_ide import changes_panel

        source = textwrap.dedent(inspect.getsource(changes_panel.ChangesPanel.__init__))
        # Дозволено лише гілку `if self.synchronous:` — вона для тестів.
        self.assertIn("synchronous", source)
        self.assertIn("_empty(", source, "панель має одразу сказати «обчислюю»")

    def test_hidden_window_gets_synchronous_scan(self) -> None:
        """Тести й скриншоти створюють вікно через withdraw()."""
        import inspect
        import textwrap

        from blackchpok_ide import changes_panel

        source = textwrap.dedent(
            inspect.getsource(changes_panel.ChangesPanel._starts_hidden))
        self.assertIn("winfo_viewable", source)


class TestFailureRegistry(unittest.TestCase):
    """Реєстр прихованих збоїв."""

    def setUp(self) -> None:
        safe.clear_failures()

    def tearDown(self) -> None:
        safe.clear_failures()

    def test_starts_empty(self) -> None:
        self.assertEqual(safe.failure_count(), 0)
        self.assertEqual(safe.failures(), [])

    def test_call_records_failure(self) -> None:
        def boom() -> None:
            raise ValueError("навмисно")

        safe.call(boom, where="перевірка")
        self.assertEqual(safe.failure_count(), 1)
        stamp, where, kind, text = safe.failures()[0]
        self.assertEqual(where, "перевірка")
        self.assertEqual(kind, "ValueError")
        self.assertIn("навмисно", text)

    def test_call_returns_default(self) -> None:
        def boom() -> None:
            raise RuntimeError("збій")

        result = safe.call(boom, where="x", default="запасне")
        self.assertEqual(result, "запасне")

    def test_call_quiet_also_records(self) -> None:
        def boom() -> None:
            raise OSError("диск")

        safe.call_quiet(boom, where="тихо")
        self.assertEqual(safe.failure_count(), 1)

    def test_listener_is_notified(self) -> None:
        seen: list[int] = []
        listener = seen.append
        safe.on_failure(listener)
        try:
            def boom() -> None:
                raise ValueError("x")

            safe.call(boom, where="a")
            safe.call(boom, where="b")
        finally:
            safe.forget_listener(listener)
        self.assertEqual(seen, [1, 2])

    def test_broken_listener_does_not_break_recording(self) -> None:
        def bad(_count: int) -> None:
            raise RuntimeError("підписник зламався")

        safe.on_failure(bad)
        try:
            def boom() -> None:
                raise ValueError("x")

            safe.call(boom, where="a")
        finally:
            safe.forget_listener(bad)
        self.assertEqual(safe.failure_count(), 1)

    def test_registry_is_capped(self) -> None:
        for index in range(safe.MAX_REMEMBERED + 30):
            safe.record_failure(f"дія {index}", ValueError(str(index)))
        self.assertEqual(safe.failure_count(), safe.MAX_REMEMBERED)

    def test_clear_resets_count(self) -> None:
        safe.record_failure("x", ValueError("y"))
        safe.clear_failures()
        self.assertEqual(safe.failure_count(), 0)

    def test_success_is_not_recorded(self) -> None:
        safe.call(lambda: 42, where="успіх")
        self.assertEqual(safe.failure_count(), 0)


class TestStartupBudget(unittest.TestCase):
    """Конструктор вікна не має робити важку роботу."""

    def test_no_synchronous_file_walk_in_build(self) -> None:
        """`_build_sidebar` не має кликати `detect_changes` напряму."""
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE._build_sidebar))
        self.assertNotIn("detect_changes", source)

    def test_skills_and_tools_refresh_deferred(self) -> None:
        """Панелі, що читають файли, оновлюються після побудови."""
        for name in ("skills_panel.py", "tools_panel.py"):
            text = (ROOT / "blackchpok_ide" / name).read_text(encoding="utf-8")
            self.assertIn("self.after(0, self.refresh)", text,
                          f"{name}: refresh має бути відкладеним")


class TestToolCatalogComplete(unittest.TestCase):
    """Каталог для моделі згадує всі інструменти.

    Регресія: 8 із 19 схем були відсутні в каталозі, тож модель не знала
    про живе тестування застосунку й обирала дії навмання.
    """

    def test_every_schema_is_in_catalog(self) -> None:
        from blackchpok_ide import tool_router
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        catalog = {name for name, _when, _example in tool_router.TOOL_CATALOG}
        missing = sorted(names - catalog)
        self.assertEqual(missing, [], f"немає в каталозі: {missing}")

    def test_catalog_has_no_phantoms(self) -> None:
        """Каталог не обіцяє інструментів, яких немає."""
        from blackchpok_ide import tool_router
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        # Скіли живуть окремим модулем, тому додаються до відомих.
        known = names | {"list_skills", "read_skill"}
        catalog = {name for name, _when, _example in tool_router.TOOL_CATALOG}
        extra = sorted(catalog - known)
        self.assertEqual(extra, [], f"каталог обіцяє неіснуючі: {extra}")

    def test_catalog_text_mentions_app_tools(self) -> None:
        from blackchpok_ide import tool_router

        text = tool_router.catalog_text(include_mcp=False)
        self.assertIn("app_start", text)
        self.assertIn("app_screenshot", text)


class TestNoGlobalChdir(unittest.TestCase):
    """Процес не змінює свою робочу теку.

    ``os.chdir`` впливає на весь процес: це ламає паралельне використання
    пакета й робить поведінку залежною від порядку дій.
    """

    def test_set_workspace_does_not_chdir(self) -> None:
        """Перевіряємо СПРАВЖНІЙ виклик, а не згадку в комментарі."""
        import ast
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE.set_workspace))
        tree = ast.parse(source)
        calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                calls.append(func.attr)
        self.assertNotIn("chdir", calls,
                         "set_workspace не має змінювати теку всього процесу")

    def test_no_chdir_anywhere_in_package(self) -> None:
        offenders = []
        for path in (ROOT / "blackchpok_ide").glob("*.py"):
            if "os.chdir(" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [], f"os.chdir у: {offenders}")


class TestSubprocessTimeouts(unittest.TestCase):
    """Блокуючі виклики мають ``timeout``."""

    def test_subprocess_run_has_timeout(self) -> None:
        import ast

        offenders = []
        targets = list((ROOT / "blackchpok_ide").glob("*.py")) + [ROOT / "server.py"]
        for path in targets:
            if not path.exists():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute)
                        and func.attr in ("run", "call", "check_output")):
                    continue
                owner = func.value
                if not (isinstance(owner, ast.Name) and owner.id == "subprocess"):
                    continue
                if not any(keyword.arg == "timeout" for keyword in node.keywords):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], f"subprocess без timeout: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
