"""Наскрізна перевірка: код правки доходить від SSE-стріму до редактора.

Тут немає справжньої моделі — є підроблений OpenAI-сумісний сервер, який
віддає правку шматками SSE рівно так, як це робить llama.cpp. Перевіряємо
те, що не видно з модульних тестів: ланцюг

    SSE-чанк → llm_client.on_tool_args → agent.edit_delta → LiveEdit

справді працює, і людина бачить код у редакторі ДО виклику інструмента.

Запуск: python -m unittest tests.test_edit_streaming_e2e -v
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import tkinter as tk
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import editor, live_edit, llm_client, stream_apply, theme  # noqa: E402


#: Правка, яку «модель» віддає у відповіді — записана як JSON-рядок,
#: бо саме так вона приходить у аргументах інструмента.
NEW_CONTENT = "def add(a, b):\n    return a + b\n"


def _sse_chunks(name: str, arguments: str) -> list[bytes]:
    """Зібрати SSE-чанки OpenAI-формату з ВИКЛИКОМ інструмента.

    Аргументи ріжемо на дрібні шматки: справжній рушій віддає по 3–30
    символів, і саме на межі шматка найлегше зламати розбір.
    """
    chunks: list[bytes] = []
    first = {
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0, "id": "call_1", "type": "function",
                "function": {"name": name, "arguments": ""},
            }]},
            "finish_reason": None,
        }],
    }
    chunks.append(f"data: {json.dumps(first, ensure_ascii=False)}\n\n".encode("utf-8"))
    step = 7
    for index in range(0, len(arguments), step):
        piece = arguments[index:index + step]
        payload = {
            "choices": [{
                "delta": {"tool_calls": [{
                    "index": 0,
                    "function": {"arguments": piece},
                }]},
                "finish_reason": None,
            }],
        }
        chunks.append(
            f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
    tail = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    chunks.append(f"data: {json.dumps(tail)}\n\n".encode("utf-8"))
    chunks.append(b"data: [DONE]\n\n")
    return chunks


class _Handler(BaseHTTPRequestHandler):
    """Віддає заготовлений SSE-стрім на будь-який запит."""

    chunks: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802 - ім'я визначає http.server
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in self.chunks:
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    def log_message(self, *args) -> None:
        return


class TestStreamReachesEditor(unittest.TestCase):
    """Ланцюг «SSE → агент → редактор» від початку до кінця."""

    @classmethod
    def setUpClass(cls) -> None:
        arguments = json.dumps(
            {"path": "app.py", "content": NEW_CONTENT}, ensure_ascii=False)
        _Handler.chunks = _sse_chunks("write_file", arguments)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_client_reports_tool_args(self) -> None:
        """Перший крок ланцюга: chat_stream віддає шматки аргументів."""
        client = llm_client.LLMClient(self.base_url, "test-model", "k")
        seen: list[str] = []

        def on_tool_args(name: str, piece: str) -> None:
            self.assertEqual(name, "write_file")
            seen.append(piece)

        result = client.chat_stream([{"role": "user", "content": "зроби"}],
                                    on_tool_args=on_tool_args)
        self.assertTrue(seen, "on_tool_args не викликався жодного разу")
        self.assertTrue(result.tool_calls, "виклик інструмента не розібрано")
        joined = "".join(seen)
        self.assertIn("content", joined)
        self.assertIn("def add", joined)

    def test_content_grows_while_streaming(self) -> None:
        """Код має бути видно ЧАСТКОВО, ще до кінця стріму."""
        client = llm_client.LLMClient(self.base_url, "test-model", "k")
        watcher = stream_apply.ToolArgsWatcher()
        snapshots: list[str] = []

        def on_tool_args(name: str, piece: str) -> None:
            if watcher.name != name:
                new = stream_apply.ToolArgsWatcher.for_tool(name)
                if new is None:
                    return
                watcher.name = new.name
                watcher.field = new.field
                watcher.replaces = new.replaces
            watcher.feed(piece)
            if watcher.ready():
                snapshots.append(watcher.shown)

        client.chat_stream([{"role": "user", "content": "зроби"}],
                           on_tool_args=on_tool_args)
        self.assertGreaterEqual(len(snapshots), 2,
                                "код прийшов лише одним шматком наприкінці")
        self.assertTrue(snapshots[0].startswith("def"))
        self.assertEqual(snapshots[-1], NEW_CONTENT,
                         "назбиранe не збігається з тим, що надіслала модель")


class TestAgentEmitsEditDelta(unittest.TestCase):
    """Другий крок: агент перетворює аргументи на подію ``edit_delta``."""

    def test_agent_emits_edit_delta(self) -> None:
        from blackchpok_ide import agent as agent_module
        from blackchpok_ide import agent_tools

        folder = Path(os.environ.get("TEMP", ".")) / "bchp-e2e-agent"
        folder.mkdir(parents=True, exist_ok=True)
        runner = agent_module.AgentRunner(
            agent_tools.ToolRegistry(folder),
            agent_module.LLMSettings(),
            agent_module.AgentSettings(),
            folder,
        )
        events: list = []
        runner.events = type("Sink", (), {"put": lambda self, event: events.append(event)})()
        # Підмінюємо клієнт: жодної мережі, лише потрібні шматки.
        arguments = json.dumps({"path": "app.py", "content": NEW_CONTENT},
                               ensure_ascii=False)

        class FakeClient:
            def chat_stream(self, messages, *, on_tool_args=None, **kwargs):
                for index in range(0, len(arguments), 9):
                    on_tool_args("write_file", arguments[index:index + 9])
                return llm_client.ChatResult(content="", tool_calls=[], usage={})

        runner._ask(FakeClient(), [{"role": "user", "content": "зроби"}], [])
        kinds = [event.kind for event in events]
        self.assertIn("edit_delta", kinds,
                      "агент не повідомив про правку під час стріму")
        deltas = [event.data for event in events if event.kind == "edit_delta"]
        self.assertGreaterEqual(len(deltas), 2,
                                "прийшла лише одна подія — правка не росла")
        payload = deltas[-1]
        self.assertEqual(payload.get("path"), "app.py")
        self.assertEqual(payload.get("content"), NEW_CONTENT)
        self.assertTrue(payload.get("final"))
        # Перша подія МУСИТЬ бути коротшою за останню: інакше код
        # з'являвся б у редакторі стрибком, як було до змін.
        self.assertLess(len(deltas[0].get("content") or ""),
                        len(payload.get("content") or ""),
                        "перша подія вже містить увесь код")


class TestLiveEditShowsInEditor(unittest.TestCase):
    """Третій крок: подія справді малює правку у віджеті редактора."""

    def setUp(self) -> None:
        fonts = theme.Theme(tk.Tk())
        self.root = fonts.master if hasattr(fonts, "master") else None
        if self.root is None:
            self.root = tk._default_root  # noqa: SLF001 - тест створює вікно сам
        fonts.apply()
        self.editor = editor.CodeEditor(self.root, fonts, "app.py")
        self.editor.set_text("x = 1\n")
        self.editor.pack()

    def tearDown(self) -> None:
        for name in ("_ast_job", "_highlight_job"):
            job = getattr(self.editor, name, None)
            if job is not None:
                try:
                    self.editor.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _pump(self, seconds: float = 0.5) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                self.root.update()
            except tk.TclError:
                return
            time.sleep(0.01)

    def test_new_file_content_appears_in_editor(self) -> None:
        block = stream_apply.EditBlock(search="", replace=NEW_CONTENT,
                                       complete=True)
        live = live_edit.feed_block(self.editor, block)
        assert live is not None
        self._pump(0.6)
        self.assertIn("def add", self.editor.get_text(),
                      "новий вміст не з'явився в редакторі")
        live.cancel_timer()


if __name__ == "__main__":
    unittest.main(verbosity=2)
