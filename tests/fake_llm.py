"""Мінімальний фейковий OpenAI-сервер для тестів агента.

Перевіряє повний цикл: запит → tool call → результат інструмента → відповідь.
Запуск:  python tests/fake_llm.py 8765 [--fail]
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

STATE: dict[str, Any] = {"calls": 0, "fail": False, "mode": "tools"}


def make_tool_response() -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "fake-coder",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {
                                "name": "list_dir",
                                "arguments": json.dumps({"path": "."}, ensure_ascii=False),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def make_final_response() -> dict[str, Any]:
    return {
        "id": "chatcmpl-2",
        "object": "chat.completion",
        "created": 0,
        "model": "fake-coder",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Готово: у теці є файли. Це відповідь після інструмента.",
                },
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 9, "total_tokens": 29},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:  # тихіше в тестах
        pass

    def _send(self, payload: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - ім'я зобов'язане бути таким
        if self.path.rstrip("/").endswith("/models"):
            self._send({"object": "list", "data": [{"id": "fake-coder", "object": "model"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if STATE["fail"]:
            self._send({"error": {"message": "fake failure"}}, 500)
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send({"error": "bad json"}, 400)
            return
        messages = payload.get("messages") or []
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        STATE["calls"] += 1
        if STATE["mode"] == "loop":
            self._send(make_tool_response())
        elif STATE["mode"] == "tools" and not has_tool_result:
            self._send(make_tool_response())
        else:
            self._send(make_final_response())


def start(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    STATE["fail"] = "--fail" in sys.argv
    server, actual = start(port)
    print(f"fake LLM на http://127.0.0.1:{actual}/v1", flush=True)
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
