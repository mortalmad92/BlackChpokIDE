"""Перевірити, що агент справді ЗМІНЮЄ файли на диску (не лише читає).

Фейковий сервер віддає tool_call ``write_file``, а потім фінальну
відповідь. Тут перевіряється головна обіцянка застосунку: «агент править
справжні файли проєкту». Все відбувається в тимчасовій теці.

Запуск: ``python tools/probe_agent_writes.py`` — код виходу 1, якщо файл
не з'явився або вміст неправильний.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent import AgentRunner                    # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry             # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings    # noqa: E402

WANTED_NAME = "створено_агентом.py"
WANTED_CODE = "def додано():\n    return 'агент справді писав файл'\n"


def tool_response() -> dict:
    return {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{
            "index": 0, "finish_reason": "tool_calls",
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": "call_w", "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({"path": WANTED_NAME,
                                                 "content": WANTED_CODE},
                                                ensure_ascii=False),
                    },
                }],
            },
        }],
    }


def final_response() -> dict:
    return {
        "id": "c2", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant",
                        "content": f"Створив {WANTED_NAME} із функцією."},
        }],
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                       # noqa: N802
        self._send({"object": "list", "data": [{"id": "fake", "object": "model"}]})

    def do_POST(self) -> None:                      # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        messages = payload.get("messages") or []
        if any(m.get("role") == "tool" for m in messages):
            self._send(final_response())
        else:
            self._send(tool_response())


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="probe-writes-"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        runner = AgentRunner(
            ToolRegistry(workspace),
            LLMSettings(f"http://127.0.0.1:{port}/v1", "fake", "local", auto_detect=False),
            AgentSettings(max_steps=6, stream=False, confirm_commands=False),
            workspace,
        )
        runner.start("створи файл створено_агентом.py")
        deadline = time.time() + 25
        while time.time() < deadline and runner.busy:
            time.sleep(0.1)
        target = workspace / WANTED_NAME
        exists = target.exists()
        print("файл створено:", exists)
        if exists:
            content = target.read_text(encoding="utf-8")
            print("вміст правильний:", content == WANTED_CODE)
            print("перший рядок:", content.splitlines()[0] if content else "—")
        answer = getattr(runner, "last_answer", "") or getattr(runner, "_last_answer", "")
        print("відповідь:", str(answer)[:90])
        ok = exists and target.read_text(encoding="utf-8") == WANTED_CODE
        print("ЗАПИС:", "OK" if ok else "ПРОБЛЕМА")
        return 0 if ok else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
