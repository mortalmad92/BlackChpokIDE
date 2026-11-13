"""Жоден ключовий файл проєкту не має бути ЗАГЛУШКОЮ.

Історія дефекту. П'ять файлів було замінено трирядковими заглушками
(«pass»), і це не виявилось нічим, крім випадковості:

    agent_tools.py     1345 рядків у git →  9 рядків на диску (186 B)
    install.bat          45 →  3
    build_exe.bat        80 → 14
    dbg2.bat             80 → 14
    BlackChpokIDE.spec  158 → 20

Наслідки були не косметичні:

* ``server.py`` (MCP-сервер) не імпортувався ВЗАГАЛІ —
  ``ImportError: cannot import name 'AgentTools'``, тобто 48 маршрутів
  не працювали;
* ``tests/test_all_tools.py`` падав назавжди — 91 інструмент не
  перевірявся жодного разу;
* ``install.bat`` складався з трьох рядків замість справжнього
  встановлення залежностей.

Ці тести роблять таку підміну ВИДИМОЮ одразу: вони порівнюють розмір
файлу на диску з версією в git і перевіряють, що ключові модулі справді
містять обіцяні символи.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Модулі, без яких застосунок або MCP-сервер не працюють. Для кожного —
#: символ, який МУСИТЬ існувати.
CRITICAL_MODULES = {
    "blackchpok_ide/agent_tools.py": ("ToolRegistry", "TOOL_SCHEMAS"),
    "blackchpok_ide/language.py": ("polish", "normalise", "find_issues"),
    "blackchpok_ide/task_executor.py": ("TaskValidator", "QueueExecutor"),
    "blackchpok_ide/tool_router.py": ("route", "confident"),
    "blackchpok_ide/intent_engine.py": ("frame", "classify_message"),
    "blackchpok_ide/memory_bridge.py": ("MemoryBridge",),
    "blackchpok_ide/context_budget.py": ("resolve_window", "plan"),
}

#: Кореневі файли, які імпортує MCP-сервер. Їхня підміна ламає сервер
#: цілком, навіть якщо пакет IDE працює.
ROOT_MODULES = {
    "agent_tools.py": ("AgentTools", "apply_text", "self_test"),
    "rag_engine.py": ("LocalRAG",),
    "vibe_router.py": ("classify",),
}


class TestNoStubFiles(TestCase):
    """Ключові файли мусять містити обіцяні символи, а не «pass»."""

    def test_package_modules_have_symbols(self) -> None:
        for name, symbols in CRITICAL_MODULES.items():
            path = ROOT / name
            with self.subTest(module=name):
                self.assertTrue(path.is_file(), f"немає файлу {name}")
                body = path.read_text(encoding="utf-8", errors="replace")
                for symbol in symbols:
                    self.assertIn(f"{symbol}", body,
                                  f"{name} не містить «{symbol}» — можлива заглушка")
                # Справжній модуль не буває 10 рядків.
                self.assertGreater(len(body.splitlines()), 40,
                                   f"{name} підозріло короткий "
                                   f"({len(body.splitlines())} рядків)")

    def test_root_modules_importable(self) -> None:
        """Кореневі модулі MCP-сервера мусять імпортуватись."""
        import importlib

        for name, symbols in ROOT_MODULES.items():
            module_name = name.removesuffix(".py")
            with self.subTest(module=module_name):
                try:
                    module = importlib.import_module(module_name)
                except SystemExit as exc:  # pragma: no cover - server.py
                    self.fail(f"{module_name} завершується через SystemExit: {exc}")
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"{module_name} не імпортується: "
                              f"{type(exc).__name__}: {exc}")
                for symbol in symbols:
                    self.assertTrue(hasattr(module, symbol),
                                    f"{module_name} не має «{symbol}» — заглушка?")

    def test_no_file_shrunk_versus_git(self) -> None:
        """Файл на диску не може бути ВТРИЧІ меншим за версію в git.

        Саме так виглядала підміна: 1345 рядків → 9. Перевіряємо лише
        ``.py`` і лише коли git доступний (у розпакованій збірці його немає).
        """
        tracked = self._tracked_python_files()
        if not tracked:
            self.skipTest("git недоступний або файлів не відстежується")

        shrunk: list[str] = []
        for name in tracked:
            path = ROOT / name
            if not path.is_file():
                continue
            disk = path.stat().st_size
            head = self._git_size(name)
            if head and head > 500 and disk < head * 0.3:
                shrunk.append(f"{name}: {disk} B на диску проти {head} B у git")
        self.assertEqual(shrunk, [],
                         "файли замінено заглушками:\n  " + "\n  ".join(shrunk))

    @staticmethod
    def _tracked_python_files() -> list[str]:
        try:
            done = subprocess.run(
                ["git", "ls-files", "*.py"], cwd=str(ROOT),
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return []
        if done.returncode != 0:
            return []
        return [line.strip() for line in done.stdout.splitlines() if line.strip()]

    @staticmethod
    def _git_size(name: str) -> int:
        try:
            done = subprocess.run(
                ["git", "cat-file", "-s", f"HEAD:{name}"], cwd=str(ROOT),
                capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return 0
        try:
            return int((done.stdout or "0").strip())
        except ValueError:
            return 0


class TestServerRoutes(TestCase):
    """MCP-сервер мусить мати маршрути — інакше агент без інструментів."""

    def test_server_imports_with_workspace(self) -> None:
        import importlib
        import os

        previous = os.environ.get("MCP_WORKSPACE")
        os.environ["MCP_WORKSPACE"] = str(ROOT)
        try:
            module = importlib.import_module("server")
        except SystemExit:
            self.skipTest("server.py очікує іншого середовища запуску")
        finally:
            if previous is None:
                os.environ.pop("MCP_WORKSPACE", None)
            else:
                os.environ["MCP_WORKSPACE"] = previous
        routes = getattr(module, "_ROUTES", None)
        self.assertIsNotNone(routes, "server.py не має таблиці маршрутів")
        self.assertGreater(len(routes), 10,
                           f"маршрутів лише {len(routes)} — сервер неповний")


if __name__ == "__main__":
    main()
