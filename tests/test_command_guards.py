"""Тести запобіжників команд агента.

Фіксують живий випадок, через який вони з'явились. Модель виконала

    python - > ui_contrast.tmp.txt 2>&1
    import itertools, sys
    …

Очікувалось «передати скрипт через stdin». Насправді ``python -`` не
отримав скрипта, вийшов у REPL і чекав на ввід. Таймаут 120 с спинив
виклик, але процес ПЕРЕЖИВ батька й писав помилки у файл ще 25 хвилин —
доки не набігло 3.5 ГБ.

Перевіряються три речі:

1. Така команда **не запускається** взагалі (пастка вводу розпізнана).
2. Запис у файл, що вже завеликий, **блокується**.
3. При таймауті гине **все дерево** процесів, а не лише оболонка.

Запуск: python -m unittest tests.test_command_guards -v
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import command_guard  # noqa: E402

#: Той самий рядок, що стався насправді.
INCIDENT = (
    'python - > ui_contrast.tmp.txt 2>&1\n'
    "import itertools, sys\n"
    "sys.path.insert(0, '.')\n"
    "print('contrast')\n"
)


class TestInputTrap(unittest.TestCase):
    """Команди, які чекатимуть на ввід, якого не буде."""

    def test_real_incident_is_detected(self) -> None:
        self.assertTrue(
            command_guard.input_trap(INCIDENT),
            "та сама команда, що виростила файл на 3.5 ГБ, мусить бути розпізнана")

    def test_hint_suggests_another_action(self) -> None:
        hint = command_guard.input_hint(INCIDENT)
        self.assertIn("write_file", hint,
                      "підказка мусить пропонувати записати скрипт у файл")
        self.assertIn("python tools/", hint)
        self.assertIn("Не повторюй", hint)

    def test_legit_python_dash_c_is_allowed(self) -> None:
        self.assertFalse(command_guard.input_trap('python -c "print(1)"'))

    def test_legit_script_file_is_allowed(self) -> None:
        self.assertFalse(command_guard.input_trap("python tools/ui_audit.py"))
        self.assertFalse(command_guard.input_trap("python -m unittest discover"))

    def test_piped_stdin_is_allowed(self) -> None:
        """``echo … | python -`` — дані справді прийдуть у stdin."""
        self.assertFalse(command_guard.input_trap("echo 'print(1)' | python -"))

    def test_pause_is_detected(self) -> None:
        self.assertTrue(command_guard.input_trap("pause"))
        self.assertTrue(command_guard.input_trap("timeout /t 30"))

    def test_empty_command_is_safe(self) -> None:
        self.assertFalse(command_guard.input_trap(""))
        self.assertFalse(command_guard.input_trap("   "))
        self.assertEqual(command_guard.input_hint(""), "")


class TestRedirectRisk(unittest.TestCase):
    """Перенаправлення виводу у файл."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-redir-"))

    def test_targets_are_found(self) -> None:
        self.assertEqual(command_guard.redirect_targets("dir > out.txt"),
                         [("out.txt", False)])
        self.assertEqual(command_guard.redirect_targets("dir >> log.txt"),
                         [("log.txt", True)])
        self.assertEqual(command_guard.redirect_targets('dir > "my file.txt"'),
                         [("my file.txt", False)])

    def test_nul_and_descriptors_are_not_files(self) -> None:
        self.assertEqual(command_guard.redirect_targets("dir > nul"), [])
        self.assertEqual(command_guard.redirect_targets("dir > /dev/null"), [])
        self.assertEqual(command_guard.redirect_targets("make 2>&1"), [])

    def test_small_file_is_allowed(self) -> None:
        target = self.folder / "small.log"
        target.write_bytes(b"x" * 1024)
        risk = command_guard.redirect_risk("echo hi > small.log", self.folder)
        self.assertIsNotNone(risk)
        assert risk is not None
        self.assertFalse(risk.oversized())

    def test_oversized_file_is_blocked(self) -> None:
        target = self.folder / "huge.log"
        target.write_bytes(b"x" * (command_guard.MAX_REDIRECT_BYTES + 1024))
        risk = command_guard.redirect_risk("echo hi > huge.log", self.folder)
        self.assertIsNotNone(risk)
        assert risk is not None
        self.assertTrue(risk.oversized(), "завеликий файл мусить бути заблокований")
        hint = command_guard.redirect_hint(risk)
        self.assertIn("МБ", hint)
        self.assertIn("видали файл", hint)

    def test_limit_can_be_lowered(self) -> None:
        """Обмеження налаштовується — тест не має писати 64 МБ."""
        target = self.folder / "mid.log"
        target.write_bytes(b"x" * 2048)
        risk = command_guard.redirect_risk("echo hi > mid.log", self.folder,
                                           limit=1024)
        self.assertIsNotNone(risk)
        assert risk is not None
        self.assertTrue(risk.oversized(1024))


class TestRunCommandGuards(unittest.TestCase):
    """Запобіжники через справжній інструмент ``run_command``."""

    def setUp(self) -> None:
        from blackchpok_ide.agent_tools import ToolRegistry

        self.folder = Path(tempfile.mkdtemp(prefix="bchp-runcmd-"))
        self.registry = ToolRegistry(self.folder)

    def test_incident_command_is_refused(self) -> None:
        started = time.time()
        result = self.registry.call("run_command",
                                    {"command": INCIDENT, "timeout": 5})
        elapsed = time.time() - started
        self.assertFalse(result.ok, "команда-пастка не має запускатись")
        # Текст підказки навмисно з ВЕЛИКИМИ літерами в слові ВВІД —
        # перевіряємо без урахування регістру, щоб тест не ламався від
        # правки тексту.
        self.assertIn("вводу", result.output.lower())
        self.assertLess(elapsed, 3.0,
                        "відмова мусить бути миттєвою, а не після таймауту")

    def test_oversized_target_is_refused(self) -> None:
        big = self.folder / "huge.log"
        big.write_bytes(b"x" * (command_guard.MAX_REDIRECT_BYTES + 1024))
        result = self.registry.call("run_command",
                                    {"command": "echo hi > huge.log"})
        self.assertFalse(result.ok)
        self.assertIn("уже займає", result.output)

    def test_normal_command_still_works(self) -> None:
        result = self.registry.call("run_command", {"command": "echo hello"})
        self.assertTrue(result.ok, result.output)
        self.assertIn("hello", result.output)
        self.assertIn("exit=0", result.output)

    def test_small_redirect_still_allowed(self) -> None:
        result = self.registry.call("run_command",
                                    {"command": "echo hi > small.log"})
        self.assertTrue(result.ok, result.output)
        self.assertTrue((self.folder / "small.log").exists())

    def test_growing_file_is_reported(self) -> None:
        """Команда відпрацювала, але файл виріс — модель має це побачити.

        УВАГА: команда успішна (``ok=True``) — блокувати нічого, бо файл
        ще в межах. Повідомлення мусить бути в ТЕКСТІ результату.
        """
        result = self.registry.call(
            "run_command",
            {"command": 'python -c "print(\'x\'*1500000)" > big.log'})
        if "python" not in result.output.lower() and not result.ok:
            self.skipTest(f"python недоступний: {result.output[:80]}")
        self.assertIn("УВАГА: файл", result.output)
        self.assertIn("МБ", result.output)
        # І файл справді виріс — повідомлення не вигадане.
        self.assertGreater((self.folder / "big.log").stat().st_size, 1_000_000)


class TestProcessTreeIsKilled(unittest.TestCase):
    """При таймауті гине ВСЕ дерево, а не лише оболонка.

    Це головна вимога: саме сиріт-нащадок писав 3.5 ГБ після того, як
    виклик уже вважався зупиненим.
    """

    def setUp(self) -> None:
        from blackchpok_ide.agent_tools import ToolRegistry

        self.folder = Path(tempfile.mkdtemp(prefix="bchp-kill-"))
        self.registry = ToolRegistry(self.folder)
        self.script = self.folder / "orphan_probe.py"
        # Довгоживучий процес-нащадок: саме він має загинути.
        self.script.write_text(
            "import time\nwhile True:\n    time.sleep(0.2)\n", encoding="utf-8")

    def _alive(self) -> list[int]:
        """PID процесів, що виконують наш скрипт."""
        try:
            out = subprocess.run(
                ["wmic", "process", "where", "name='python.exe'",
                 "get", "ProcessId,CommandLine"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            self.skipTest("wmic недоступний")
        found: list[int] = []
        for line in (out.stdout or "").splitlines():
            if "orphan_probe.py" not in line:
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                found.append(int(parts[-1]))
        return found

    def tearDown(self) -> None:
        # Не лишаємо сміття, навіть якщо тест провалився.
        for pid in self._alive():
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_descendant_does_not_survive_timeout(self) -> None:
        command = (f'start /b python "{self.script}" & '
                   "ping -n 60 127.0.0.1 > nul")
        result = self.registry.call("run_command",
                                    {"command": command, "timeout": 6})
        self.assertFalse(result.ok, "команда мусила впасти за таймаутом")
        self.assertIn("дочірніми процесами", result.output)
        # Даємо системі мить на закриття дескрипторів.
        time.sleep(1.5)
        self.assertEqual(
            self._alive(), [],
            "нащадок пережив таймаут — саме так файл ріс 25 хвилин після "
            "«зупинки» команди")


if __name__ == "__main__":
    unittest.main(verbosity=2)
