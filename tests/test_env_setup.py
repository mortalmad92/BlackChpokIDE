"""Тести перевірки середовища й майстра першого запуску.

Перевіряємо саме те, що ламається на чужій машині: відсутній пакет,
відсутня програма, немає pip (зібраний .exe), немає winget, збій установки.

Запуск: python -m unittest tests.test_env_setup -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import env_setup as env  # noqa: E402


class TestDeclaration(unittest.TestCase):
    """Описи того, що потрібно IDE."""

    def test_requirements_are_complete(self) -> None:
        for req in env.REQUIREMENTS:
            self.assertTrue(req.package, req)
            self.assertTrue(req.module, req)
            self.assertTrue(req.purpose, req)

    def test_tools_are_complete(self) -> None:
        for tool in env.TOOLS:
            self.assertTrue(tool.exe, tool)
            self.assertTrue(tool.label, tool)
            self.assertTrue(tool.purpose, tool)

    def test_git_is_declared_with_sources(self) -> None:
        """Git потрібен з двома шляхами: winget і сторінка завантаження."""
        git = next(tool for tool in env.TOOLS if tool.exe == "git")
        self.assertEqual(git.winget_id, "Git.Git")
        self.assertIn("git-scm.com", git.download_url)

    def test_core_requirements_are_required(self) -> None:
        names = {req.package for req in env.REQUIREMENTS if req.required}
        self.assertIn("openai", names)
        self.assertIn("mcp", names)

    def test_optional_requirements_are_optional(self) -> None:
        optional = {req.package for req in env.REQUIREMENTS if not req.required}
        self.assertIn("numpy", optional)
        self.assertIn("pillow", optional)

    def test_min_python_matches_project(self) -> None:
        self.assertEqual(env.MIN_PYTHON, (3, 11))


class TestChecks(unittest.TestCase):
    """Перевірка наявності."""

    def test_installed_modules_are_found(self) -> None:
        # ``sys`` точно є — це перевірка самого детектора, не середовища.
        self.assertTrue(env.module_available("sys"))
        self.assertTrue(env.module_available("json"))

    def test_missing_module_is_reported(self) -> None:
        self.assertFalse(env.module_available("такого_модуля_точно_немає_123"))

    def test_empty_module_is_false(self) -> None:
        self.assertFalse(env.module_available(""))

    def test_broken_package_is_not_available(self) -> None:
        """``find_spec`` може кинути на зламаному пакеті — не має валити IDE."""
        with mock.patch("importlib.util.find_spec", side_effect=ValueError("зламано")):
            self.assertFalse(env.module_available("будь_що"))

    def test_check_requirements_returns_row_per_package(self) -> None:
        rows = env.check_requirements()
        self.assertEqual(len(rows), len(env.REQUIREMENTS))

    def test_check_tools_returns_row_per_tool(self) -> None:
        rows = env.check_tools()
        self.assertEqual(len(rows), len(env.TOOLS))

    def test_installed_package_is_ok(self) -> None:
        req = (env.Requirement("os", "os", "перевірка", required=True),)
        rows = env.check_requirements(requirements=req)
        self.assertEqual(rows[0].state, env.STATE_OK)

    def test_missing_required_package_state(self) -> None:
        req = (env.Requirement("нема", "нема_такого_123", "перевірка", required=True),)
        rows = env.check_requirements(requirements=req)
        self.assertEqual(rows[0].state, env.STATE_MISSING)
        self.assertTrue(rows[0].required)

    def test_missing_optional_package_state(self) -> None:
        req = (env.Requirement("нема", "нема_такого_123", "перевірка", required=False),)
        rows = env.check_requirements(requirements=req)
        self.assertEqual(rows[0].state, env.STATE_OPTIONAL)
        self.assertFalse(rows[0].required)

    def test_missing_package_is_actionable_with_pip(self) -> None:
        req = (env.Requirement("нема", "нема_такого_123", "перевірка"),)
        with mock.patch.object(env, "pip_available", return_value=True):
            rows = env.check_requirements(requirements=req)
        self.assertTrue(rows[0].actionable)
        self.assertEqual(rows[0].install_kind, "pip")
        self.assertEqual(rows[0].install_target, "нема")

    def test_missing_package_not_actionable_without_pip(self) -> None:
        """У зібраному .exe pip немає — обіцяти установку не можна."""
        req = (env.Requirement("нема", "нема_такого_123", "перевірка"),)
        with mock.patch.object(env, "pip_available", return_value=False):
            rows = env.check_requirements(requirements=req)
        self.assertFalse(rows[0].actionable)
        self.assertEqual(rows[0].install_kind, "")

    def test_missing_tool_uses_winget_when_available(self) -> None:
        tool = (env.Tool("немає-такої", "Нема", "перевірка",
                         winget_id="X.Y", download_url="https://example.com/d"),)
        with mock.patch.object(env, "winget_available", return_value=True):
            rows = env.check_tools(tools=tool)
        self.assertEqual(rows[0].install_kind, "winget")
        self.assertEqual(rows[0].install_target, "X.Y")

    def test_missing_tool_falls_back_to_page_without_winget(self) -> None:
        tool = (env.Tool("немає-такої", "Нема", "перевірка",
                         winget_id="X.Y", download_url="https://example.com/d"),)
        with mock.patch.object(env, "winget_available", return_value=False):
            rows = env.check_tools(tools=tool)
        self.assertEqual(rows[0].install_kind, "")
        self.assertTrue(rows[0].actionable, "сторінка завантаження лишається")
        self.assertEqual(rows[0].download_url, "https://example.com/d")

    def test_present_tool_is_ok(self) -> None:
        tool = (env.Tool(sys.executable, "Python", "перевірка"),)
        rows = env.check_tools(tools=tool)
        # exe шукаємо через PATH, тож підміняємо детектор.
        with mock.patch.object(env, "tool_available", return_value=True):
            rows = env.check_tools(tools=tool)
        self.assertEqual(rows[0].state, env.STATE_OK)
        self.assertFalse(rows[0].actionable)


class TestSummary(unittest.TestCase):
    """Підсумки для заголовка майстра."""

    def _row(self, state: str, required: bool = True) -> env.ItemState:
        return env.ItemState(key="k", label="L", purpose="P",
                             state=state, required=required)

    def test_summary_counts(self) -> None:
        rows = [self._row(env.STATE_OK), self._row(env.STATE_MISSING),
                self._row(env.STATE_OPTIONAL, required=False)]
        stats = env.summary(rows)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["optional"], 1)

    def test_describe_missing(self) -> None:
        text = env.describe_problems([self._row(env.STATE_MISSING)])
        self.assertIn("Бракує", text)

    def test_describe_optional(self) -> None:
        text = env.describe_problems([self._row(env.STATE_OPTIONAL, required=False)])
        self.assertIn("Необов'язкові", text)

    def test_describe_all_present(self) -> None:
        text = env.describe_problems([self._row(env.STATE_OK)])
        self.assertIn("на місці", text)


class TestInstall(unittest.TestCase):
    """Установка: pip, winget і запасна сторінка."""

    def test_install_package_without_pip_is_honest(self) -> None:
        with mock.patch.object(env, "pip_available", return_value=False):
            result = env.install_package("numpy")
        self.assertFalse(result.ok)
        self.assertIn("pip", result.message)

    def test_install_package_success(self) -> None:
        with mock.patch.object(env, "pip_available", return_value=True), \
                mock.patch.object(env, "_run", return_value=(0, "Successfully installed")):
            result = env.install_package("numpy")
        self.assertTrue(result.ok)

    def test_install_package_failure_reports_output(self) -> None:
        with mock.patch.object(env, "pip_available", return_value=True), \
                mock.patch.object(env, "_run", return_value=(1, "ERROR: не знайдено")):
            result = env.install_package("numpy")
        self.assertFalse(result.ok)
        self.assertIn("не знайдено", result.message)

    def test_winget_without_winget_is_honest(self) -> None:
        with mock.patch.object(env, "winget_available", return_value=False):
            result = env.install_tool_with_winget("Git.Git", label="Git")
        self.assertFalse(result.ok)
        self.assertIn("winget", result.message)

    def test_winget_success(self) -> None:
        with mock.patch.object(env, "winget_available", return_value=True), \
                mock.patch.object(env, "_run", return_value=(0, "Installed")):
            result = env.install_tool_with_winget("Git.Git", label="Git")
        self.assertTrue(result.ok)

    def test_winget_already_installed_is_success(self) -> None:
        """Код «вже встановлено» — не помилка для користувача."""
        with mock.patch.object(env, "winget_available", return_value=True), \
                mock.patch.object(env, "_run",
                                  return_value=(1, "Package already installed")):
            result = env.install_tool_with_winget("Git.Git", label="Git")
        self.assertTrue(result.ok)
        self.assertIn("уже", result.message)

    def test_winget_failure_opens_page_in_embedded_browser(self) -> None:
        opened: list[str] = []
        item = env.ItemState(key="git", label="Git", purpose="diff",
                             state=env.STATE_OPTIONAL, install_kind="winget",
                             install_target="Git.Git",
                             download_url="https://git-scm.com/download/win")
        with mock.patch.object(env, "winget_available", return_value=True), \
                mock.patch.object(env, "_run", return_value=(1, "помилка")), \
                mock.patch("blackchpok_ide.browser_panel.open_url",
                           side_effect=lambda url: opened.append(url) or True):
            result = env.install_item(item)
        self.assertFalse(result.ok)
        self.assertTrue(result.opened_page)
        self.assertEqual(opened, ["https://git-scm.com/download/win"])

    def test_item_without_installer_opens_page(self) -> None:
        opened: list[str] = []
        item = env.ItemState(key="x", label="X", purpose="p",
                             state=env.STATE_OPTIONAL,
                             download_url="https://example.com/dl")
        with mock.patch("blackchpok_ide.browser_panel.open_url",
                        side_effect=lambda url: opened.append(url) or True):
            result = env.install_item(item)
        self.assertTrue(result.opened_page)
        self.assertEqual(opened, ["https://example.com/dl"])

    def test_item_without_any_route_is_reported(self) -> None:
        item = env.ItemState(key="x", label="X", purpose="p",
                             state=env.STATE_MISSING)
        result = env.install_item(item)
        self.assertFalse(result.ok)
        self.assertIn("немає способу", result.message)

    def test_already_present_item_is_skipped(self) -> None:
        item = env.ItemState(key="sys", label="sys", purpose="p", state=env.STATE_OK)
        result = env.install_item(item)
        self.assertTrue(result.ok)
        self.assertIn("уже є", result.message)

    def test_install_missing_skips_present(self) -> None:
        rows = [
            env.ItemState(key="a", label="A", purpose="p", state=env.STATE_OK),
            env.ItemState(key="b", label="B", purpose="p", state=env.STATE_MISSING),
        ]
        with mock.patch.object(env, "install_item",
                               return_value=env.StepResult("b", True, "ok")) as single:
            results = env.install_missing(rows)
        self.assertEqual(len(results), 1)
        single.assert_called_once()

    def test_install_missing_only_required(self) -> None:
        rows = [
            env.ItemState(key="b", label="B", purpose="p", state=env.STATE_MISSING,
                          required=True),
            env.ItemState(key="c", label="C", purpose="p", state=env.STATE_OPTIONAL,
                          required=False),
        ]
        with mock.patch.object(env, "install_item",
                               return_value=env.StepResult("b", True, "ok")):
            results = env.install_missing(rows, only_required=True)
        self.assertEqual(len(results), 1)

    def test_install_missing_reports_each_step(self) -> None:
        rows = [env.ItemState(key="b", label="B", purpose="p",
                              state=env.STATE_MISSING)]
        seen: list[str] = []
        with mock.patch.object(env, "install_item",
                               return_value=env.StepResult("b", True, "ok")):
            env.install_missing(rows, on_step=lambda item, res: seen.append(item.key))
        self.assertEqual(seen, ["b"])

    def test_broken_progress_callback_does_not_stop_install(self) -> None:
        def boom(_text: str) -> None:
            raise RuntimeError("навмисно")

        with mock.patch.object(env, "pip_available", return_value=True), \
                mock.patch.object(env, "_run", return_value=(0, "ok")):
            result = env.install_package("numpy", on_status=boom)
        self.assertTrue(result.ok)

    def test_run_handles_missing_command(self) -> None:
        code, output = env._run(["такої-команди-точно-немає"], timeout=5)
        self.assertNotEqual(code, 0)
        self.assertIn("не знайдено", output.lower())


class TestNoSystemBrowser(unittest.TestCase):
    """env_setup теж не має відкривати системний браузер."""

    def test_opens_via_browser_panel(self) -> None:
        text = (ROOT / "blackchpok_ide" / "env_setup.py").read_text(encoding="utf-8")
        self.assertIn("browser_panel.open_url", text)

    def test_open_page_uses_shared_opener(self) -> None:
        opened: list[str] = []
        with mock.patch("blackchpok_ide.browser_panel.open_url",
                        side_effect=lambda url: opened.append(url) or True):
            self.assertTrue(env._open_page("https://example.com", None))
        self.assertEqual(opened, ["https://example.com"])


class TestWizardSteps(unittest.TestCase):
    """Кроки майстра (без вікна)."""

    def test_steps_order(self) -> None:
        from blackchpok_ide.first_run import STEPS

        keys = [key for key, _label in STEPS]
        self.assertEqual(keys, ["hardware", "libs", "tools", "model"])

    def test_every_step_has_label(self) -> None:
        from blackchpok_ide.first_run import STEPS

        for key, label in STEPS:
            self.assertTrue(key)
            self.assertTrue(label.strip())

    def test_wizard_uses_place_window(self) -> None:
        text = (ROOT / "blackchpok_ide" / "first_run.py").read_text(encoding="utf-8")
        self.assertIn("place_window", text)

    def test_wizard_does_not_open_system_browser(self) -> None:
        text = (ROOT / "blackchpok_ide" / "first_run.py").read_text(encoding="utf-8")
        self.assertNotIn("webbrowser", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
