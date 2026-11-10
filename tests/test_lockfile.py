"""Файл-замок IDE: два запуски не мають ділити VRAM.

Вимога з docs/AUTOMATIC_RUNTIME.md §7: «Захист від двох копій IDE. Немає
файлу-замка: два запуски можуть підняти два сервери на різних портах».

Перевіряємо на СПРАВЖНІХ процесах: живий чужий процес має тримати замок,
мертвий — не має.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import lockfile  # noqa: E402


class LockTestCase(unittest.TestCase):
    """Ізолює теку даних, щоб не чіпати справжній ide.lock користувача."""

    def setUp(self) -> None:
        import tempfile

        self.home = Path(tempfile.mkdtemp(prefix="locktest-"))
        self._old_home = os.environ.get("BLACKCHPOK_HOME")
        os.environ["BLACKCHPOK_HOME"] = str(self.home)
        lockfile.clear_stale()

    def tearDown(self) -> None:
        import shutil

        lockfile.clear_stale()
        if self._old_home is None:
            os.environ.pop("BLACKCHPOK_HOME", None)
        else:
            os.environ["BLACKCHPOK_HOME"] = self._old_home
        shutil.rmtree(self.home, ignore_errors=True)

    # ── допомога ─────────────────────────────────────────────────────────
    def _write_lock(self, pid: int, workspace: str = "") -> Path:
        path = lockfile.lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"pid": pid, "started": time.time(),
                        "workspace": workspace, "exe": "test"}),
            encoding="utf-8",
        )
        return path

    def _live_process(self) -> subprocess.Popen:
        """Справжній живий процес (спить, доки його не вб'ють)."""
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


class TestAcquireAndRelease(LockTestCase):
    def test_acquire_creates_file_with_pid(self) -> None:
        lock = lockfile.Lock(workspace=str(ROOT))
        self.assertTrue(lock.acquire())
        try:
            self.assertTrue(lockfile.lock_path().exists())
            info = lockfile.read()
            self.assertIsNotNone(info)
            self.assertEqual(info.pid, os.getpid())
            self.assertEqual(info.workspace, str(ROOT))
        finally:
            lock.release()
        self.assertFalse(lockfile.lock_path().exists(), "файл лишився після release")

    def test_second_copy_refused_while_first_alive(self) -> None:
        """Жива чужа копія → acquire() каже «ні» і називає PID."""
        process = self._live_process()
        try:
            self._write_lock(process.pid, workspace="C:/other/project")
            lock = lockfile.Lock()
            self.assertFalse(lock.acquire(), "другу копію пустили")
            self.assertIsNotNone(lock.other)
            self.assertEqual(lock.other.pid, process.pid)
            self.assertIn("уже запущено", lock.error)
            self.assertIn(str(process.pid), lock.error)
            # замок не перезаписано нашим PID
            self.assertEqual(lockfile.read().pid, process.pid)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_stale_lock_of_dead_process_is_taken_over(self) -> None:
        """Мертвий PID (аварійне закриття) не блокує запуск."""
        process = self._live_process()
        dead_pid = process.pid
        process.terminate()
        process.wait(timeout=5)
        self._write_lock(dead_pid)

        lock = lockfile.Lock()
        self.assertTrue(lock.acquire(), "залишок замка заблокував запуск")
        try:
            self.assertEqual(lockfile.read().pid, os.getpid(),
                             "замок не перебрано на себе")
        finally:
            lock.release()

    def test_release_does_not_touch_foreign_lock(self) -> None:
        """release() не має зносити замок ІНШОГО живого процесу."""
        process = self._live_process()
        try:
            self._write_lock(process.pid)
            lock = lockfile.Lock()
            lock.release()             # ми замок не брали
            self.assertTrue(lockfile.lock_path().exists(),
                            "чужий замок знесено")
            self.assertEqual(lockfile.read().pid, process.pid)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_broken_file_is_not_a_lock(self) -> None:
        """Зіпсований файл не блокує запуск (читаємо як «замка немає»)."""
        path = lockfile.lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ це не json", encoding="utf-8")
        self.assertIsNone(lockfile.read())
        self.assertIsNone(lockfile.is_held_by_other())
        lock = lockfile.Lock()
        self.assertTrue(lock.acquire())
        lock.release()

    def test_clear_stale_removes_dead_but_keeps_live(self) -> None:
        process = self._live_process()
        try:
            self._write_lock(process.pid)
            self.assertFalse(lockfile.clear_stale(), "знесено замок живої копи")
            self.assertTrue(lockfile.lock_path().exists())
        finally:
            process.terminate()
            process.wait(timeout=5)
        # тепер PID мертвий — прибирання має спрацювати
        self.assertTrue(lockfile.clear_stale())
        self.assertFalse(lockfile.lock_path().exists())


class TestPidAlive(LockTestCase):
    def test_current_process_is_alive(self) -> None:
        self.assertTrue(lockfile._pid_alive(os.getpid()))

    def test_dead_process_is_not_alive(self) -> None:
        process = self._live_process()
        pid = process.pid
        process.terminate()
        process.wait(timeout=5)
        self.assertFalse(lockfile._pid_alive(pid))

    def test_zero_and_negative_are_not_alive(self) -> None:
        for pid in (0, -1, -999):
            self.assertFalse(lockfile._pid_alive(pid), f"PID {pid} визнано живим")


if __name__ == "__main__":
    unittest.main(verbosity=2)
