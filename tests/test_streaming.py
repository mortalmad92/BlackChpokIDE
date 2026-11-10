"""Тести стрімінгу: справжній SSE-сервер на localhost, без моків логіки.

Запуск:  python tests/test_streaming.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


class _SSEHandler(BaseHTTPRequestHandler):
    """Віддає справжній text/event-stream, як OpenAI-сумісний сервер."""

    def log_message(self, *_args):  # тишина в тестах
        return None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        wants_stream = bool(payload.get("stream"))
        self.send_response(200)
        if not wants_stream:
            # Той самий текст, що і зі стрімом: режим не має змінювати зміст.
            body = json.dumps({
                "choices": [{"message": {"content": "Готово: тест пройдено."},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def send(obj):
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()

        # Роздуми окремими шматками.
        for thought in ("Спершу ", "подивлюсь ", "файли."):
            send({"choices": [{"delta": {"reasoning_content": thought}}]})
            time.sleep(0.01)
        # Текст відповіді.
        for piece in ("Готово", ": ", "тест ", "пройдено."):
            send({"choices": [{"delta": {"content": piece}}]})
            time.sleep(0.01)
        send({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class _ToolCallHandler(_SSEHandler):
    """Сервер, що віддає виклик інструмента шматками (як справжній API)."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        json.loads(self.rfile.read(length) or b"{}")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
            self.wfile.flush()

        send({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_a", "function": {"name": "read_file", "arguments": ""}}
        ]}}]})
        send({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path": '}}
        ]}}]})
        send({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"main.py"}'}}
        ]}}]})
        send({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _serve(handler) -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/v1"


def test_stream_client() -> None:
    """LLMClient.chat_stream реально читає SSE."""
    from blackchpok_ide.llm_client import LLMClient

    server, url = _serve(_SSEHandler)
    try:
        client = LLMClient(url, model="test-model", api_key="x", timeout=10)
        texts: list[str] = []
        thoughts: list[str] = []
        result = client.chat_stream(
            [{"role": "user", "content": "привіт"}],
            on_text=texts.append,
            on_reasoning=thoughts.append,
        )
        check("стрім віддав текст", result.content == "Готово: тест пройдено.",
              repr(result.content))
        check("текст приходив шматками", len(texts) >= 3, f"{len(texts)} шматків")
        check("шматки склеюються у фінальний текст",
              "".join(texts) == result.content, repr("".join(texts)))
        check("роздуми прочитано", "подивлюсь" in result.reasoning,
              repr(result.reasoning))
        check("роздуми теж шматками", len(thoughts) >= 2, f"{len(thoughts)}")
        check("finish_reason збережено", result.finish_reason == "stop",
              result.finish_reason)
    finally:
        server.shutdown()


def test_tool_calls_in_stream() -> None:
    """Виклики інструментів, розірвані на шматки, збираються правильно."""
    from blackchpok_ide.llm_client import LLMClient

    server, url = _serve(_ToolCallHandler)
    try:
        client = LLMClient(url, model="test-model", api_key="x", timeout=10)
        result = client.chat_stream(
            [{"role": "user", "content": "читай"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )
        check("виклик інструмента складено", len(result.tool_calls) == 1,
              f"{len(result.tool_calls)}")
        if result.tool_calls:
            call = result.tool_calls[0]
            check("ім'я інструмента правильне",
                  call["function"]["name"] == "read_file", call["function"]["name"])
            check("аргументи склеєні зі шматків",
                  call["function"]["arguments"] == '{"path": "main.py"}',
                  call["function"]["arguments"])
            check("id збережено", call["id"] == "call_a", call["id"])
    finally:
        server.shutdown()


def test_fallback() -> None:
    """Сервер без підтримки стріму — прозоре відкочення до звичайного запиту."""
    from blackchpok_ide.llm_client import LLMClient

    class NoStreamHandler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return None

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            json.loads(self.rfile.read(length) or b"{}")
            # Ігноруємо stream: віддаємо звичайний JSON.
            body = json.dumps({
                "choices": [{"message": {"content": "звичайна відповідь"},
                             "finish_reason": "stop"}],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server, url = _serve(NoStreamHandler)
    try:
        client = LLMClient(url, model="test-model", api_key="x", timeout=10)
        result = client.chat_stream([{"role": "user", "content": "привіт"}])
        check("відкочення до звичайного запиту працює",
              result.content == "звичайна відповідь", repr(result.content))
    finally:
        server.shutdown()


def test_agent_emits_tokens() -> None:
    """Агент перетворює стрім на події token/reasoning_token."""
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.config import AgentSettings, LLMSettings

    server, url = _serve(_SSEHandler)
    try:
        settings = AgentSettings()
        settings.stream = True
        runner = AgentRunner.__new__(AgentRunner)
        import queue as _q

        runner.events = _q.Queue()
        runner._cancel = threading.Event()
        runner.agent_settings = settings
        runner.llm_settings = LLMSettings(base_url=url, model="test-model", api_key="x")

        from blackchpok_ide.llm_client import LLMClient

        client = LLMClient(url, model="test-model", api_key="x", timeout=10)
        result = runner._ask(client, [{"role": "user", "content": "привіт"}], [])

        kinds: list[str] = []
        while not runner.events.empty():
            kinds.append(runner.events.get_nowait().kind)

        check("агент віддав події token", "token" in kinds, str(set(kinds)))
        check("агент віддав reasoning_token", "reasoning_token" in kinds,
              str(set(kinds)))
        check("фінальний текст збережено",
              result.content == "Готово: тест пройдено.", repr(result.content))
    finally:
        server.shutdown()


def test_streaming_disabled() -> None:
    """Вимкнений стрімінг дає той самий результат, але без подій token."""
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.config import AgentSettings, LLMSettings
    from blackchpok_ide.llm_client import LLMClient

    server, url = _serve(_SSEHandler)
    try:
        settings = AgentSettings()
        settings.stream = False
        runner = AgentRunner.__new__(AgentRunner)
        import queue as _q

        runner.events = _q.Queue()
        runner._cancel = threading.Event()
        runner.agent_settings = settings

        client = LLMClient(url, model="test-model", api_key="x", timeout=10)
        result = runner._ask(client, [{"role": "user", "content": "привіт"}], [])

        kinds: list[str] = []
        while not runner.events.empty():
            kinds.append(runner.events.get_nowait().kind)

        check("без стрімінгу подій token немає", "token" not in kinds, str(set(kinds)))
        # Той самий текст, що й у стрімі (сервер віддає його в обох режимах).
        check("відповідь та сама, що зі стрімом", "Готово" in result.content,
              repr(result.content))
    finally:
        server.shutdown()


def test_chat_panel_stream() -> None:
    """Панель чату показує живий вивід і замінює його фінальною карткою."""
    import tkinter as tk

    from blackchpok_ide import theme
    from blackchpok_ide.agent import AgentEvent
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.chat_panel import ChatPanel
    from blackchpok_ide.config import Settings

    root = tk.Tk()
    root.geometry("760x700")
    fonts = theme.Theme(root)
    fonts.apply()
    host = tk.Frame(root)
    host.pack(side="bottom", fill="x")
    panel = ChatPanel(root, fonts, Settings(), ToolRegistry(ROOT), composer_parent=host)
    panel.pack(fill="both", expand=True)
    root.update()

    for piece in ("Привіт", ", ", "це ", "стрім."):
        panel._handle_event(AgentEvent("token", piece))
    panel._flush_stream()
    root.update()

    check("стрім створює тимчасову картку", panel._stream_card is not None)
    check("у картці видно накопичений текст",
          panel._stream_widget is not None
          and "Привіт" in panel._stream_widget.get("1.0", "end"))

    cards_before = len(panel._cards)
    panel._handle_event(AgentEvent("assistant", "Привіт, це стрім.",
                                   {"final": True, "step": 0}))
    root.update()

    check("тимчасову картку прибрано", panel._stream_card is None)
    check("лишилась одна фінальна картка", len(panel._cards) == cards_before,
          f"{cards_before} → {len(panel._cards)}")
    check("після завершення стрім неактивний", panel.streaming is False)

    # Скидання чату не має лишати залишків стріму.
    for piece in ("хвіст", " стріму"):
        panel._handle_event(AgentEvent("token", piece))
    panel.reset()
    root.update()
    check("reset() очищає стан стріму",
          not panel._stream_parts and panel._stream_card is None)

    root.destroy()


def main() -> int:
    test_stream_client()
    test_tool_calls_in_stream()
    test_fallback()
    test_agent_emits_tokens()
    test_streaming_disabled()
    test_chat_panel_stream()
    print()
    print("Стрімінг:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_streaming.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
