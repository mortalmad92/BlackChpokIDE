"""Пошкоджені файли стану не мають ламати старт IDE.

Той самий клас дефекту, що й у test_broken_queue, але для ВСІХ файлів, які
читаються при запуску: налаштування, сесія, трасування, чати, черга.

Реальні причини пошкодження: обірваний запис під час збою живлення, чужий
редактор, відкат на старішу версію, пошкоджений диск, файл записано не в
UTF-8.

Знайдено було три додаткові діри понад queue.json:
  · Settings.load()  — json.loads повертає число/рядок/список ->
    AttributeError: 'int' object has no attribute 'get';
  · load_session()   — UnicodeDecodeError на файлі не в UTF-8;
  · TraceStore       — те саме.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import chat_store, config, queue_engine, trace_store  # noqa: E402

#: Пошкоджений вміст, який міг лишитись на диску.
BROKEN_TEXT = {
    "порожній": "",
    "не json": "це не json",
    "обірваний": '{"a": [1,',
    "число": "42",
    "рядок": '"рядок"',
    "список": "[1,2,3]",
    "null": "null",
    "true": "true",
    "вкладені списки": "[[[[1]]]]",
    "глибоко вкладений": '{"a":{"b":{"c":[1,2,{"e":null}]}}}',
}
BROKEN_BYTES = b"\xff\xfe\x00\x00\xff\xff"


class StateFileCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="statefiles-"))
        self._old = os.environ.get("BLACKCHPOK_HOME")
        os.environ["BLACKCHPOK_HOME"] = str(self.home)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("BLACKCHPOK_HOME", None)
        else:
            os.environ["BLACKCHPOK_HOME"] = self._old
        shutil.rmtree(self.home, ignore_errors=True)

    def _write(self, path: Path, payload: str | None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if payload is None:
            path.write_bytes(BROKEN_BYTES)
        else:
            path.write_text(payload, encoding="utf-8")


class TestSettings(StateFileCase):
    def test_all_broken_payloads_load_defaults(self) -> None:
        for label, payload in BROKEN_TEXT.items():
            with self.subTest(case=label):
                self._write(config.settings_path(), payload)
                settings = config.Settings.load()
                self.assertIsInstance(settings, config.Settings)
                self.assertIsInstance(settings.llm.model, str)

    def test_non_utf8_settings_load_defaults(self) -> None:
        self._write(config.settings_path(), None)
        settings = config.Settings.load()
        self.assertIsInstance(settings, config.Settings)

    def test_valid_settings_still_read(self) -> None:
        self._write(config.settings_path(),
                    json.dumps({"llm": {"model": "робоча"}}, ensure_ascii=False))
        self.assertEqual(config.Settings.load().llm.model, "робоча")


class TestSession(StateFileCase):
    def test_all_broken_payloads_return_empty(self) -> None:
        for label, payload in BROKEN_TEXT.items():
            with self.subTest(case=label):
                self._write(config.session_path(), payload)
                result = config.load_session()
                self.assertIsInstance(result, dict)

    def test_non_utf8_session_returns_empty(self) -> None:
        self._write(config.session_path(), None)
        self.assertEqual(config.load_session(), {})

    def test_valid_session_reads(self) -> None:
        self._write(config.session_path(), json.dumps({"chat_id": "abc"}))
        self.assertEqual(config.load_session().get("chat_id"), "abc")


class TestTrace(StateFileCase):
    def test_non_utf8_trace_does_not_crash(self) -> None:
        path = self.home / "trace.jsonl"
        self._write(path, None)
        store = trace_store.TraceStore(path)
        # будь-який метод читання не має кидати
        for name in ("load", "entries", "recent", "summary", "examples"):
            method = getattr(store, name, None)
            if callable(method):
                try:
                    method()
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"{name}() упав: {type(exc).__name__}: {exc}")

    def test_broken_lines_are_skipped(self) -> None:
        path = self.home / "trace.jsonl"
        self._write(path, '{"ok": 1}\nне json\n[1,2]\n{"ok": 2}\n')
        store = trace_store.TraceStore(path)
        load = getattr(store, "load", None)
        if callable(load):
            load()          # не має кидати


class TestChats(StateFileCase):
    def test_all_broken_payloads_are_safe(self) -> None:
        for label, payload in BROKEN_TEXT.items():
            with self.subTest(case=label):
                path = self.home / "chats.json"
                self._write(path, payload)
                store = chat_store.ChatStore(path)
                load = getattr(store, "load", None)
                if callable(load):
                    load()

    def test_non_utf8_chats_are_safe(self) -> None:
        path = self.home / "chats.json"
        self._write(path, None)
        store = chat_store.ChatStore(path)
        load = getattr(store, "load", None)
        if callable(load):
            load()


class TestQueue(StateFileCase):
    def test_all_broken_payloads_are_safe(self) -> None:
        for label, payload in BROKEN_TEXT.items():
            with self.subTest(case=label):
                path = self.home / "queue.json"
                self._write(path, payload)
                queue = queue_engine.TaskQueue(path)
                self.assertEqual(queue.tasks, [], f"{label}: мали бути без завдань")

    def test_non_utf8_queue_is_safe(self) -> None:
        path = self.home / "queue.json"
        self._write(path, None)
        self.assertEqual(queue_engine.TaskQueue(path).tasks, [])


class TestEverythingTogether(StateFileCase):
    """Усі файли пошкоджені ОДНОЧАСНО — найгірший випадок."""

    def test_all_broken_at_once(self) -> None:
        self._write(config.settings_path(), "42")
        self._write(config.session_path(), None)
        self._write(self.home / "queue.json", "[1,2,3]")
        self._write(self.home / "chats.json", '"рядок"')
        self._write(self.home / "trace.jsonl", None)

        settings = config.Settings.load()
        self.assertIsInstance(settings, config.Settings)
        self.assertIsInstance(config.load_session(), dict)
        self.assertEqual(queue_engine.TaskQueue(self.home / "queue.json").tasks, [])
        chat_store.ChatStore(self.home / "chats.json")
        trace_store.TraceStore(self.home / "trace.jsonl")


if __name__ == "__main__":
    unittest.main(verbosity=2)
