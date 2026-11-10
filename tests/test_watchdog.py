"""Watchdog рушія: IDE має помітити смерть llama-server сама.

Перевіряємо на СПРАВЖНЬОМУ процесі (python, що завершується), а не на мокі:
інакше тест доводив би лише те, що мок повертає те, що в нього заклали.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import runtime  # noqa: E402


def _make_server(process: subprocess.Popen) -> runtime.LocalServer:
    """LocalServer із підставленим живим процесом (без запуску llama-server)."""
    config = runtime.ServerConfig(model_path=str(ROOT / "main.py"), port=1)
    server = runtime.LocalServer(config)
    server.process = process
    return server


class TestWatchdogNoticesDeath(unittest.TestCase):
    def test_watchdog_reports_process_death(self) -> None:
        """Процес помирає сам → watchdog кличе on_died із причиною."""
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.4)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        server = _make_server(process)
        called = threading.Event()
        reasons: list[str] = []

        def _on_died(reason: str) -> None:
            reasons.append(reason)
            called.set()

        server.on_died = _on_died
        server.start_watchdog(interval=0.1)
        try:
            noticed = called.wait(timeout=5.0)
        finally:
            server.stop_watchdog()
            process.wait(timeout=5)

        self.assertTrue(noticed, "watchdog не помітив смерть процесу")
        self.assertEqual(len(reasons), 1, f"повідомлень: {len(reasons)}")
        self.assertIn("завершився", reasons[0])
        self.assertIn("код", reasons[0])
        self.assertTrue(server.died_reason, "причина не збережена")

    def test_watchdog_quiet_while_alive(self) -> None:
        """Поки процес живий — жодних повідомлень."""
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        server = _make_server(process)
        calls: list[str] = []
        server.on_died = calls.append
        server.start_watchdog(interval=0.1)
        try:
            time.sleep(0.8)
            self.assertEqual(calls, [], "watchdog завчасно повідомив про смерть")
            self.assertIsNone(process.poll(), "процес мав бути живий")
        finally:
            server.stop_watchdog()
            process.terminate()
            process.wait(timeout=5)

    def test_stop_ends_watchdog(self) -> None:
        """stop() прибирає потік — інакше він тримав би об'єкт живим."""
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        server = _make_server(process)
        server.start_watchdog(interval=0.1)
        thread = server._watchdog
        self.assertIsNotNone(thread)
        self.assertTrue(thread.is_alive())

        server.stop(timeout=5)
        self.assertIsNone(server._watchdog, "посилання на потік не прибрано")
        self.assertFalse(thread.is_alive(), "потік watchdog лишився живим")

    def test_no_repeat_notifications(self) -> None:
        """Одна смерть — одне повідомлення, навіть якщо почекати довше."""
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=5)          # уже мертвий до старту watchdog
        server = _make_server(process)
        calls: list[str] = []
        server.on_died = calls.append
        server.start_watchdog(interval=0.05)
        try:
            time.sleep(1.0)
        finally:
            server.stop_watchdog()
        self.assertEqual(len(calls), 1, f"повідомлень: {len(calls)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
