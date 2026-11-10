"""Регресії рушія (Етап 4, 10.11.2026).

Тут — те, що ламалось у мості ``native/bridge.py`` і потоковому шляху
``NativeRuntime.generate_stream``. Перевірки не потребують завантаженої
моделі: вони дивляться на контракт і лічильники.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide.native import api, bridge  # noqa: E402


class TestStreamHasTimeout(unittest.TestCase):
    """Потоковий шлях мусить мати тайм-аут, як і блокуючий."""

    def test_generate_stream_accepts_timeout(self) -> None:
        params = inspect.signature(api.NativeRuntime.generate_stream).parameters
        self.assertIn(
            "timeout", params,
            "агент ходить саме через стрім — без timeout він міг чекати вічно")

    def test_generate_also_has_timeout(self) -> None:
        params = inspect.signature(api.NativeRuntime.generate).parameters
        self.assertIn("timeout", params)

    def test_stream_has_generator_exit_handling(self) -> None:
        """Покинутий генератор мусить знімати ``_pending``."""
        source = inspect.getsource(api.NativeRuntime.generate_stream)
        self.assertIn("GeneratorExit", source,
                      "без цього _pending лишається >0 і busy() вічний True")


class TestBridgeGoesThroughRuntime(unittest.TestCase):
    """Міст не має обходити чергу й телеметрію."""

    def test_chat_uses_runtime_generate(self) -> None:
        source = inspect.getsource(bridge.chat)
        self.assertIn("rt.generate(", source,
                      "прямий rt.engine.generate обходив busy() і _record")
        self.assertNotIn("rt.engine.generate(", source)

    def test_chat_stream_uses_runtime_stream(self) -> None:
        source = inspect.getsource(bridge.chat_stream)
        self.assertIn("rt.generate_stream(", source,
                      "прямий rt.engine.generate_stream обходив busy()")
        self.assertNotIn("rt.engine.generate_stream(", source)

    def test_busy_reads_pending(self) -> None:
        source = inspect.getsource(bridge.busy)
        self.assertIn("_pending", source)


class TestBridgeContract(unittest.TestCase):
    """Формат відповіді не змінився: його читає ``llm_client``."""

    def test_chat_signature_unchanged(self) -> None:
        params = list(inspect.signature(bridge.chat).parameters)
        for name in ("messages", "model", "tools", "temperature",
                     "max_tokens", "should_stop"):
            self.assertIn(name, params)

    def test_chat_stream_signature_unchanged(self) -> None:
        params = list(inspect.signature(bridge.chat_stream).parameters)
        for name in ("messages", "model", "tools", "temperature",
                     "max_tokens", "on_text", "on_reasoning", "should_stop"):
            self.assertIn(name, params)

    def test_usage_helper_accepts_dict_and_object(self) -> None:
        """``NativeRuntime.generate`` віддає словник, ``stats`` — об'єкт."""

        class FakeStats:
            def to_dict(self):
                return {"prompt_tokens": 5, "generated_tokens": 7,
                        "cached_tokens": 2}

        class FakeRuntime:
            pass

        from_dict = bridge._usage({"prompt_tokens": 5, "generated_tokens": 7},
                                  FakeRuntime())
        from_obj = bridge._usage(FakeStats(), FakeRuntime())
        self.assertEqual(from_dict["total_tokens"], 12)
        self.assertEqual(from_obj["total_tokens"], 12)
        self.assertEqual(from_obj["prompt_tokens_details"]["cached_tokens"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
