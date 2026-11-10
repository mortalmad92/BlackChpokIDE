"""Супервізор MCP: health-check, бекоф, watchdog, зупинка з очікуванням.

Вимоги з docs/MCP_SUPERVISOR.md §5. Перевіряємо поведінку, а не наявність
методів: сервер, що відповів на handshake, але має зламані схеми, має
вважатися НЕздоровим (саме ця пастка описана в §3 документа).
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import mcp_supervisor as sup  # noqa: E402


class FakeConfig:
    def __init__(self, name: str = "fake", enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled


class FakeClient:
    """Клієнт, чию поведінку задає тест.

    ``start_error`` / ``init_error`` — зірвати відповідний крок.
    ``schemas`` — що поверне ``list_tools()``.
    ``running`` керується вручну, щоб імітувати смерть процесу.
    """

    instances: list["FakeClient"] = []

    def __init__(self, config, *, start_error=None, init_error=None,
                 schemas=None, dies_after_list=False) -> None:
        self.config = config
        self.start_error = start_error
        self.init_error = init_error
        self._schemas = schemas if schemas is not None else [
            {"name": "tool_a", "inputSchema": {"type": "object", "properties": {}}},
        ]
        self.dies_after_list = dies_after_list
        self.running = False
        self.started = 0
        self.stopped = 0
        self.stop_hangs = False
        self.list_calls = 0
        FakeClient.instances.append(self)

    def start(self) -> None:
        if self.start_error:
            raise RuntimeError(self.start_error)
        self.running = True
        self.started += 1

    def initialize(self) -> dict:
        if self.init_error:
            raise RuntimeError(self.init_error)
        return {"ok": True}

    def list_tools(self):
        self.list_calls += 1
        if self.dies_after_list:
            self.running = False
        return list(self._schemas)

    def stop(self) -> None:
        self.stopped += 1
        if self.stop_hangs:
            time.sleep(10)
        self.running = False


def _factory(**kwargs):
    def make(config):
        return FakeClient(config, **kwargs)
    return make


GOOD_SCHEMA = {"name": "ok_tool", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}}}


class TestSchemaUsable(unittest.TestCase):
    def test_good_schema_is_usable(self) -> None:
        self.assertTrue(sup.schema_is_usable(GOOD_SCHEMA))

    def test_schema_without_name_rejected(self) -> None:
        self.assertFalse(sup.schema_is_usable({"inputSchema": {"type": "object"}}))

    def test_empty_name_rejected(self) -> None:
        self.assertFalse(sup.schema_is_usable({"name": "   ", "inputSchema": {}}))

    def test_schema_without_params_rejected(self) -> None:
        self.assertFalse(sup.schema_is_usable({"name": "x"}))

    def test_non_object_type_rejected(self) -> None:
        self.assertFalse(sup.schema_is_usable({"name": "x", "inputSchema": {"type": "string"}}))

    def test_parameters_alias_accepted(self) -> None:
        self.assertTrue(sup.schema_is_usable({"name": "x", "parameters": {"type": "object"}}))

    def test_not_a_dict_rejected(self) -> None:
        for value in (None, "text", 42, []):
            self.assertFalse(sup.schema_is_usable(value))


class TestHealthCheck(unittest.TestCase):
    def test_healthy_server_reports_ok_and_counts(self) -> None:
        supervisor = sup.MpcSupervisor(_factory(schemas=[GOOD_SCHEMA, GOOD_SCHEMA]))
        try:
            report = supervisor.start("s1", FakeConfig("s1"))
            self.assertTrue(report.ok, report.reason)
            self.assertEqual(report.tools, 2)
            self.assertEqual(report.valid_schemas, 2)
            self.assertIn("✓", report.text())
        finally:
            supervisor.stop_all()

    def test_handshake_ok_but_broken_schemas_is_unhealthy(self) -> None:
        """Пастка з §3: initialize відповів, а інструменти непридатні."""
        broken = [{"inputSchema": {"type": "object"}}]   # без імені
        supervisor = sup.MpcSupervisor(_factory(schemas=broken))
        try:
            report = supervisor.start("s2", FakeConfig("s2"), attempts=1)
            self.assertFalse(report.ok, "зламані схеми визнано здоровими")
            self.assertEqual(report.tools, 1)
            self.assertEqual(report.valid_schemas, 0)
            self.assertIn("не придатн", report.reason)
        finally:
            supervisor.stop_all()

    def test_server_without_tools_is_unhealthy(self) -> None:
        supervisor = sup.MpcSupervisor(_factory(schemas=[]))
        try:
            report = supervisor.start("s3", FakeConfig("s3"), attempts=1)
            self.assertFalse(report.ok)
            self.assertIn("жодного інструмента", report.reason)
        finally:
            supervisor.stop_all()

    def test_partially_valid_schemas_still_ok_but_flagged(self) -> None:
        supervisor = sup.MpcSupervisor(_factory(schemas=[GOOD_SCHEMA, {"bad": 1}]))
        try:
            report = supervisor.start("s4", FakeConfig("s4"))
            self.assertTrue(report.ok)
            self.assertEqual(report.valid_schemas, 1)
            self.assertIn("придатних 1 з 2", report.reason)
        finally:
            supervisor.stop_all()


class TestBackoff(unittest.TestCase):
    def test_backoff_delays_are_1_2_4(self) -> None:
        self.assertEqual(sup.BACKOFF, (1.0, 2.0, 4.0))

    def test_retries_with_backoff_then_gives_up(self) -> None:
        delays: list[float] = []
        factory = _factory(start_error="не запускається")
        supervisor = sup.MpcSupervisor(factory)
        try:
            report = supervisor.start("s5", FakeConfig("s5"), attempts=3,
                                      sleep=delays.append)
            self.assertFalse(report.ok)
            self.assertEqual(delays, [1.0, 2.0], f"затримки: {delays}")
            self.assertIn("старт", report.reason)
        finally:
            supervisor.stop_all()

    def test_retry_recovers_on_second_attempt(self) -> None:
        attempts: list[int] = []

        def factory(config):
            attempts.append(1)
            first = len(attempts) == 1
            return FakeClient(config,
                              start_error="перша спроба падає" if first else None)

        supervisor = sup.MpcSupervisor(factory)
        try:
            report = supervisor.start("s6", FakeConfig("s6"), attempts=3,
                                      sleep=lambda _s: None)
            self.assertTrue(report.ok, report.reason)
            self.assertEqual(len(attempts), 2)
        finally:
            supervisor.stop_all()

    def test_unhealthy_result_also_retries(self) -> None:
        """Піднявся, але health-check провалився → теж повтор."""
        calls: list[int] = []

        def factory(config):
            calls.append(1)
            bad = len(calls) == 1
            return FakeClient(config, schemas=[] if bad else [GOOD_SCHEMA])

        supervisor = sup.MpcSupervisor(factory)
        try:
            report = supervisor.start("s7", FakeConfig("s7"), attempts=2,
                                      sleep=lambda _s: None)
            self.assertTrue(report.ok, report.reason)
            self.assertEqual(len(calls), 2)
        finally:
            supervisor.stop_all()


class TestWatchdog(unittest.TestCase):
    def test_watchdog_restarts_dead_server(self) -> None:
        supervisor = sup.MpcSupervisor(_factory())
        try:
            report = supervisor.start("w1", FakeConfig("w1"))
            self.assertTrue(report.ok)
            client = supervisor.client("w1")
            self.assertTrue(client.running)

            client.running = False        # імітуємо смерть процесу
            supervisor.start_watchdog(interval=0.1)
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                current = supervisor.client("w1")
                if current is not None and current is not client and current.running:
                    break
                time.sleep(0.1)
            else:
                self.fail("watchdog не перезапустив сервер")
            self.assertTrue(supervisor.client("w1").running)
        finally:
            supervisor.stop_all()

    def test_watchdog_stops_cleanly(self) -> None:
        supervisor = sup.MpcSupervisor(_factory())
        try:
            supervisor.start("w2", FakeConfig("w2"))
            supervisor.start_watchdog(interval=0.1)
            thread = supervisor._watchdog
            self.assertIsNotNone(thread)
            supervisor.stop_watchdog()
            self.assertFalse(thread.is_alive(), "потік watchdog лишився живим")
            self.assertIsNone(supervisor._watchdog)
        finally:
            supervisor.stop_all()


class TestStopAll(unittest.TestCase):
    def test_stop_all_waits_and_reports(self) -> None:
        supervisor = sup.MpcSupervisor(_factory())
        try:
            supervisor.start("x1", FakeConfig("x1"))
            supervisor.start("x2", FakeConfig("x2"))
            results = supervisor.stop_all(timeout=3.0)
            self.assertEqual(results, {"x1": True, "x2": True})
            self.assertEqual(supervisor.names(), [], "клієнти не прибрано")
        finally:
            supervisor.stop_all(timeout=1.0)

    def test_stop_all_reports_server_that_hangs(self) -> None:
        """Сервер, що висить у stop(), має бути позначений як незупинений."""
        supervisor = sup.MpcSupervisor(_factory())
        try:
            supervisor.start("x3", FakeConfig("x3"))
            client = supervisor.client("x3")
            client.stop_hangs = True
            started = time.perf_counter()
            results = supervisor.stop_all(timeout=0.5)
            spent = time.perf_counter() - started
            self.assertFalse(results["x3"], "завислий сервер названо зупиненим")
            self.assertLess(spent, 3.0, f"stop_all чекав {spent:.1f} с")
        finally:
            pass

    def test_start_all_skips_disabled(self) -> None:
        supervisor = sup.MpcSupervisor(_factory())
        try:
            results = supervisor.start_all([FakeConfig("on", True),
                                            FakeConfig("off", False)])
            self.assertTrue(results["on"].ok)
            self.assertIn("вимкнено", results["off"].reason)
        finally:
            supervisor.stop_all()


if __name__ == "__main__":
    unittest.main(verbosity=2)
