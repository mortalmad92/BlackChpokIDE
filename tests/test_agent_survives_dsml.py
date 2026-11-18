"""Наскрізний прогін агента, коли модель віддає виклик СВОЇМ протоколом.

Попередні тести перевіряють розбір окремо. Цей — те, що реально бачить
користувач: справжній ``AgentRunner``, справжні інструменти на диску й
справжній HTTP-сервер моделі, який відповідає протоколом DSML замість
``tool_calls``.

Навіщо саме так. Заміряно на скріншоті користувача: усі частини окремо
виглядали справними, а в чаті висів службовий XML, файли не створювались
і жоден інструмент не викликався. Перевіряти треба весь ланцюг.

Запуск:  python -m unittest tests.test_agent_survives_dsml -v
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent import AgentRunner  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide import response_engine  # noqa: E402

WIDE = "\uff5c"


def dsml_answer(tool: str, **params: str) -> str:
    """Відповідь моделі її власним протоколом (як у живому прогоні)."""
    inner = "".join(
        f'<{WIDE}DSML{WIDE} parameter name="{key}" string="true">{value}'
        f"</{WIDE}DSML{WIDE} parameter>\n"
        for key, value in params.items())
    return (f"<{WIDE}DSML{WIDE} calls>\n"
            f'<{WIDE}DSML{WIDE} invoke name="{tool}">\n'
            f"{inner}"
            f"</{WIDE}DSML{WIDE} invoke>\n"
            f"</{WIDE}DSML{WIDE} calls>")


class _DsmlModel(BaseHTTPRequestHandler):
    """Модель, яка НІКОЛИ не віддає ``tool_calls`` — лише свій протокол."""

    protocol_version = "HTTP/1.1"
    rounds: list[str] = []
    fail = False

    def log_message(self, *_args) -> None:
        pass

    def _send(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._send({"object": "list",
                        "data": [{"id": "dsml-coder", "object": "model"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if type(self).fail:
            self._send({"error": {"message": "boom"}}, 500)
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send({"error": "bad json"}, 400)
            return
        messages = payload.get("messages") or []
        # Скільки інструментів уже повернули результат — стільки ходів і було.
        done = sum(1 for m in messages if m.get("role") == "tool")
        type(self).rounds.append("tool" if done else "call")

        if done:
            text = "Готово: файли прочитано, ось короткий підсумок."
            message = {"role": "assistant", "content": text}
            finish = "stop"
        else:
            # КЛЮЧОВЕ: виклик у полі content, а не в tool_calls.
            message = {"role": "assistant",
                       "content": dsml_answer("list_dir", path=".")}
            finish = "stop"
        self._send({"id": "x", "object": "chat.completion", "created": 0,
                    "model": "dsml-coder",
                    "choices": [{"index": 0, "finish_reason": finish,
                                 "message": message}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                              "total_tokens": 15}})


def start_model() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DsmlModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def drain(runner: AgentRunner, limit: float = 60.0) -> list:
    """Дочекатись подій агента (він працює у власному потоці)."""
    import time

    events: list = []
    started = time.perf_counter()
    while time.perf_counter() - started < limit:
        item = runner.events.get(timeout=0.2) if not runner.events.empty() else None
        if item is None:
            # ``busy`` — властивість раннера (потік ще живий?).
            if not runner.busy and runner.events.empty():
                break
            continue
        events.append(item)
        if getattr(item, "kind", "") == "done":
            break
    while not runner.events.empty():
        events.append(runner.events.get())
    return events


class TestAgentExecutesProtocolCall(unittest.TestCase):
    """Головне: виклик із протоколу мусить РЕАЛЬНО виконатись."""

    def setUp(self) -> None:
        _DsmlModel.rounds = []
        _DsmlModel.fail = False
        self.server, self.base_url = start_model()
        self.folder = self._tmp()
        (self.folder / "calculator.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.folder / "run.py").write_text("print('hi')\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)

    def _tmp(self) -> Path:
        """Робоча тека ПРОЄКТУ, а не системний Temp.

        Навіщо саме так. ``tempfile.mkdtemp`` дає теку поза робочим
        простором, і під файловою пісочницею запис туди заборонено —
        тест падав би на ``PermissionError``, не перевіривши нічого.
        Тека в проєкті прибирається у ``tearDown``.
        """
        import uuid

        folder = ROOT / ".buildtmp" / f"dsml-e2e-{uuid.uuid4().hex[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _runner(self) -> AgentRunner:
        registry = ToolRegistry(self.folder)
        return AgentRunner(
            registry,
            LLMSettings(base_url=self.base_url, model="dsml-coder", timeout=30),
            AgentSettings(max_steps=4, offline_fallback=False),
            self.folder,
        )

    def test_tool_actually_runs(self) -> None:
        """Раніше виклик не виконувався взагалі — це головний дефект."""
        runner = self._runner()
        runner.start("покажи файли в проєкті")
        events = drain(runner)
        kinds = [event.kind for event in events]
        self.assertIn("tool_call", kinds,
                      f"інструмент не викликано; події: {kinds}")
        calls = [e for e in events if e.kind == "tool_call"]
        self.assertEqual(calls[0].data.get("name"), "list_dir")
        self.assertIn("tool_result", kinds)

    def test_protocol_never_reaches_the_chat(self) -> None:
        runner = self._runner()
        runner.start("покажи файли в проєкті")
        events = drain(runner)
        shown = "\n".join(
            str(event.text or "") for event in events
            if event.kind in ("assistant", "token"))
        self.assertNotIn("DSML", shown)
        self.assertNotIn("invoke", shown)
        self.assertNotIn("parameter", shown)

    def test_user_gets_a_human_answer(self) -> None:
        runner = self._runner()
        runner.start("покажи файли в проєкті")
        events = drain(runner)
        answers = [e for e in events if e.kind == "assistant" and e.text]
        self.assertTrue(answers, "користувач не отримав жодної відповіді")
        final = answers[-1].text
        self.assertTrue(final.strip())
        self.assertFalse(response_engine.looks_like_raw_protocol(final))


if __name__ == "__main__":
    unittest.main()
