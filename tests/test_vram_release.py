"""Регресії на звільнення відеопам'яті при закритті IDE.

Скарга користувача (2026-11-09): «при закритті програми треба зробити щоб
закривався фоновий процес моделі, щоб я спокійно міг запускати свої ігри,
бо бачу щось грузить відеокарту».

Причина. ``llama-server`` тримає 8–11 ГБ VRAM. Зупинка існувала, але:

* стояла в КІНЦІ ``on_close`` — будь-який виняток вище або достроковий
  ``return`` лишав процес живим;
* не було обліку PID, тому після аварійного завершення (вбитий процес, збій)
  наступний запуск не знав про «сироту»;
* не було ``atexit``-хука.

Ці тести фіксують виправлену поведінку.

Запуск:
    python -m unittest tests.test_vram_release -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-vram-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

from blackchpok_ide import runtime  # noqa: E402


class TestProcessRegistry(unittest.TestCase):
    """Облік власних процесів у файлі PID."""

    def setUp(self) -> None:
        self._saved = runtime.pid_file_path()
        self._backup = self._saved.read_text(encoding="utf-8") if self._saved.exists() else None
        runtime._write_pid_file([])

    def tearDown(self) -> None:
        if self._backup is None:
            try:
                self._saved.unlink()
            except OSError:
                pass
        else:
            self._saved.write_text(self._backup, encoding="utf-8")

    def test_remember_and_forget(self) -> None:
        runtime.remember_process(4242, model="m.gguf", port=8080)
        entries = runtime._read_pid_file()
        self.assertEqual([item["pid"] for item in entries], [4242])
        self.assertEqual(entries[0]["model"], "m.gguf")

        runtime.forget_process(4242)
        self.assertEqual(runtime._read_pid_file(), [])

    def test_remember_is_idempotent(self) -> None:
        """Повторний запис того самого PID не дублює рядок."""
        runtime.remember_process(7, model="a")
        runtime.remember_process(7, model="b")
        entries = runtime._read_pid_file()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["model"], "b")

    def test_pid_file_survives_garbage(self) -> None:
        """Зіпсований файл не має ламати старт IDE."""
        runtime.pid_file_path().write_text("{ not json", encoding="utf-8")
        self.assertEqual(runtime._read_pid_file(), [])
        self.assertEqual(runtime.stale_processes(), [])

    def test_dead_pid_is_not_reported(self) -> None:
        """PID, якого вже немає, не вважається «сиротою»."""
        runtime.remember_process(999_999)
        self.assertEqual(runtime.stale_processes(), [])

    def test_pid_alive_own_process(self) -> None:
        self.assertTrue(runtime._pid_alive(os.getpid()))
        self.assertFalse(runtime._pid_alive(999_999))


class TestForeignProcessIsSafe(unittest.TestCase):
    """Чужий процес із «нашим» PID не можна вбивати."""

    def test_non_server_pid_is_not_ours(self) -> None:
        """Поточний Python-процес — не llama-server, отже не «наший»."""
        self.assertFalse(runtime._pid_is_our_server(os.getpid()),
                         "вбивати чужий процес за PID неприпустимо")

    def test_pid_zero_is_not_ours(self) -> None:
        self.assertFalse(runtime._pid_is_our_server(0))


class TestCleanupContract(unittest.TestCase):
    """Прибирання повертає число й не кидає винятків."""

    def setUp(self) -> None:
        self._saved = runtime.pid_file_path()
        self._backup = self._saved.read_text(encoding="utf-8") if self._saved.exists() else None
        runtime._write_pid_file([])

    def tearDown(self) -> None:
        if self._backup is None:
            try:
                self._saved.unlink()
            except OSError:
                pass
        else:
            self._saved.write_text(self._backup, encoding="utf-8")

    def test_cleanup_with_empty_registry(self) -> None:
        self.assertEqual(runtime.cleanup_stale_processes(), 0)

    def test_cleanup_with_dead_pid(self) -> None:
        runtime.remember_process(999_998)
        self.assertEqual(runtime.cleanup_stale_processes(), 0)
        # Запис про мертвий PID прибирається, щоб файл не ріс.
        self.assertEqual(runtime._read_pid_file(), [])


class TestClosePathOrder(unittest.TestCase):
    """Звільнення пам'яті мусить іти ДО збереження стану в ``on_close``.

    Раніше зупинка стояла в кінці й могла не виконатись через достроковий
    ``return`` (напр. «є незбережені файли») або виняток вище.
    """

    def test_release_before_saving_state(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8")
        body = source[source.index("def on_close"):]
        release_at = body.index("self._release_model_now()")
        save_at = body.index('save_session({"tabs"')
        self.assertLess(release_at, save_at,
                        "звільнення VRAM має бути ДО збереження стану: "
                        "інакше достроковий return лишає процес живим")

    def test_release_handles_all_runtimes(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8")
        body = source[source.index("def _release_model_now"):]
        body = body[:body.index("def _editor_event")]
        for marker in ("_managed_server", "model_hub", "native_runtime",
                       "cleanup_stale_processes"):
            self.assertIn(marker, body,
                          f"_release_model_now мусить зупиняти {marker}")

    def test_atexit_registered(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8")
        self.assertIn("atexit.register(self._release_model_now)", source,
                      "без atexit аварійне завершення лишить процес живим")

    def test_cleanup_on_startup(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8")
        self.assertIn("_cleanup_orphans_quietly", source,
                      "залишки попереднього запуску треба прибирати на старті")


class TestPortSafety(unittest.TestCase):
    """Рушій не має займати порт, який слухає інша програма.

    Реальний випадок на машині користувача: порт **8080 тримає Steam**
    (``steamwebhelper.exe``), 8090 — TorrServer. ``llama-server`` падав з
    «couldn't bind HTTP server socket», і IDE показувала «сервер не піднявся»
    без пояснення.
    """

    def test_busy_port_is_detected(self) -> None:
        import socket

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)
        try:
            self.assertTrue(runtime.port_is_busy(port),
                            f"порт {port} слухається, мусить вважатись зайнятим")
        finally:
            server.close()

    def test_free_port_is_not_busy(self) -> None:
        port = runtime.free_port(49_100)
        self.assertFalse(runtime.port_is_busy(port))

    def test_free_port_skips_busy_port(self) -> None:
        """free_port мусить пропустити зайнятий порт і взяти наступний."""
        import socket

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        busy = server.getsockname()[1]
        server.listen(1)
        try:
            chosen = runtime.free_port(busy)
            self.assertNotEqual(chosen, busy,
                                "зайнятий порт не можна віддавати рушію")
        finally:
            server.close()

    def test_start_reassigns_busy_port(self) -> None:
        """``LocalServer.start`` мусить перевести конфіг на вільний порт."""
        source = (ROOT / "blackchpok_ide" / "runtime.py").read_text(encoding="utf-8")
        body = source[source.index("class LocalServer"):]
        body = body[:body.index("def wait_ready")]
        self.assertIn("port_is_busy", body,
                      "старт мусить перевіряти, чи порт не зайнятий")


if __name__ == "__main__":
    unittest.main(verbosity=2)
