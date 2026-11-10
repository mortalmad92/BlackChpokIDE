"""Тести перевірки реальних можливостей моделі.

Фіксують вимогу: зелений значок ставиться за ФАКТОМ тесту, а не за назвою
моделі чи наявністю файлу mmproj.

Запуск:
    python -m unittest tests.test_model_verify -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-verify-"))
os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import model_verify  # noqa: E402


def make_png(path: Path, width: int = 40, height: int = 30) -> Path:
    from blackchpok_ide import multiscale

    rgb = bytes([128]) * (width * height * 3)
    multiscale.write_png(path, width, height, rgb)
    return path


class FakeResponse(io.BytesIO):
    """Підміна HTTP-відповіді для ``urlopen``."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def chat_reply(content: str = "", tool_calls=None) -> bytes:
    return json.dumps({
        "choices": [{"message": {"content": content,
                                 "tool_calls": tool_calls or []}}],
    }).encode()


class TestToolCalling(unittest.TestCase):
    """Tool calling перевіряється СПРАВЖНІМ викликом."""

    def test_structured_call_passes(self) -> None:
        payload = chat_reply(tool_calls=[{
            "type": "function",
            "function": {"name": "get_server_time", "arguments": "{}"}}])
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload)):
            result = model_verify.test_tool_calling(client)
        self.assertTrue(result.ok, result.detail)
        self.assertIn("tool_call", result.evidence)

    def test_plain_text_fails(self) -> None:
        """Текст із назвою функції НЕ є успішним викликом."""
        payload = chat_reply(content="Я викликав би get_server_time.")
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload)):
            result = model_verify.test_tool_calling(client)
        self.assertFalse(result.ok,
                         "звичайний текст не має вважатись tool calling")
        self.assertIn("текстом", result.detail)

    def test_wrong_tool_fails(self) -> None:
        payload = chat_reply(tool_calls=[{
            "type": "function",
            "function": {"name": "some_other_tool", "arguments": "{}"}}])
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload)):
            result = model_verify.test_tool_calling(client)
        self.assertFalse(result.ok)


class TestVision(unittest.TestCase):
    """Зір перевіряється зображенням із відомим вмістом."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-vis-"))
        self.image = make_png(self.folder / "t.png")

    def test_vision_passes_when_content_matches(self) -> None:
        payload = chat_reply("На зображенні видно сірий квадрат.")
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload)):
            result = model_verify.test_vision(client, self.image,
                                              expected=("квадрат",))
        self.assertTrue(result.ok, result.detail)

    def test_vision_fails_on_generic_answer(self) -> None:
        """Загальні слова без згадки вмісту — зір не підтверджено."""
        payload = chat_reply("Я не можу аналізувати зображення.")
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload)):
            result = model_verify.test_vision(client, self.image,
                                              expected=("квадрат",))
        self.assertFalse(result.ok)
        self.assertIn("не підтверджено", result.detail)

    def test_missing_image_is_skipped_not_passed(self) -> None:
        client = model_verify.Client("http://x/v1", "m")
        result = model_verify.test_vision(client, self.folder / "nope.png")
        self.assertFalse(result.ok)
        self.assertIn("немає тестового зображення", result.detail)

    def test_image_actually_sent(self) -> None:
        """У запиті мусить бути image_url із base64, а не шлях."""
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["body"] = request.data
            return FakeResponse(chat_reply("квадрат"))

        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            model_verify.test_vision(client, self.image, expected=("квадрат",))
        body = json.loads(captured["body"].decode())
        content = body["messages"][0]["content"]
        self.assertIsInstance(content, list)
        kinds = [part.get("type") for part in content]
        self.assertIn("image_url", kinds)
        url = next(part["image_url"]["url"] for part in content
                   if part.get("type") == "image_url")
        self.assertTrue(url.startswith("data:image/png;base64,"))


class TestReasoningAndJson(unittest.TestCase):
    def test_reasoning_correct(self) -> None:
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(chat_reply("5"))):
            self.assertTrue(model_verify.test_reasoning(client).ok)

    def test_reasoning_wrong(self) -> None:
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(chat_reply("7"))):
            self.assertFalse(model_verify.test_reasoning(client).ok)

    def test_json_valid(self) -> None:
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(
                            chat_reply('{"status":"ok","count":3}'))):
            self.assertTrue(model_verify.test_json_output(client).ok)

    def test_json_inside_fence_is_accepted(self) -> None:
        client = model_verify.Client("http://x/v1", "m")
        text = '```json\n{"status":"ok","count":3}\n```'
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(chat_reply(text))):
            self.assertTrue(model_verify.test_json_output(client).ok)

    def test_json_invalid(self) -> None:
        client = model_verify.Client("http://x/v1", "m")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(chat_reply("ніякого json"))):
            self.assertFalse(model_verify.test_json_output(client).ok)


class TestReport(unittest.TestCase):
    def test_capabilities_mapping(self) -> None:
        report = model_verify.Report(model="m")
        report.results = [
            model_verify.Result("tool_calling", model_verify.PASSED),
            model_verify.Result("vision", model_verify.FAILED),
        ]
        caps = report.capabilities
        self.assertTrue(caps["tool_calling"])
        self.assertFalse(caps["vision"])

    def test_summary_counts(self) -> None:
        report = model_verify.Report(model="m")
        report.results = [
            model_verify.Result("a", model_verify.PASSED),
            model_verify.Result("b", model_verify.PASSED),
            model_verify.Result("c", model_verify.FAILED),
        ]
        self.assertIn("2 з 3", report.summary())

    def test_text_marks_status(self) -> None:
        report = model_verify.Report(model="m")
        report.results = [
            model_verify.Result("ok_one", model_verify.PASSED),
            model_verify.Result("bad_one", model_verify.FAILED),
            model_verify.Result("skip_one", model_verify.SKIPPED),
        ]
        text = report.text()
        self.assertIn("✓ ok_one", text)
        self.assertIn("✗ bad_one", text)
        self.assertIn("· skip_one", text)


class TestNoFalseGreen(unittest.TestCase):
    """Головна вимога: значок не можна ставити без тесту."""

    def test_skipped_is_not_ok(self) -> None:
        self.assertFalse(model_verify.Result("x").ok,
                         "«не перевірено» не має вважатись успіхом")

    def test_failed_is_not_ok(self) -> None:
        self.assertFalse(
            model_verify.Result("x", model_verify.FAILED).ok)

    def test_run_all_marks_failures(self) -> None:
        """Якщо сервер відповідає текстом — tool_calling мусить бути ✗."""
        client_payload = chat_reply(content="не буду")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(client_payload)):
            report = model_verify.run_all("http://x/v1", "m")
        self.assertFalse(report.capabilities["tool_calling"],
                         "без справжнього tool_call значок ставити не можна")


if __name__ == "__main__":
    unittest.main(verbosity=2)
