"""HTTP-стаби, які віддають СПРАВЖНІЙ SSE у форматі Anthropic і Gemini.

Навіщо окремий модуль: ``tests_dsml_stubs`` піднімає сервер на справжньому
сокеті, тож перевіряється весь шлях клієнта — заголовки, розбір подій і
фільтр протоколу, — а не лише окрема функція.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler


def _sse(events: list[dict]) -> bytes:
    return b"".join(b"data: " + json.dumps(event, ensure_ascii=False).encode()
                    + b"\n\n" for event in events)


class _Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    #: Шматки тексту, які «віддає модель».
    PIECES: tuple[str, ...] = ()

    def log_message(self, *_args) -> None:
        pass

    def _send(self, events: list[dict]) -> None:
        body = _sse(events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._send(self.events())


class AnthropicStub(_Base):
    """``content_block_delta`` зі ``text_delta`` — так віддає Anthropic."""

    def events(self) -> list[dict]:
        events: list[dict] = [{"type": "message_start",
                               "message": {"usage": {"input_tokens": 5}}}]
        for piece in self.PIECES:
            events.append({"type": "content_block_delta", "index": 0,
                           "delta": {"type": "text_delta", "text": piece}})
        events.append({"type": "message_delta",
                       "delta": {"stop_reason": "end_turn"},
                       "usage": {"output_tokens": 9}})
        return events


class GeminiStub(_Base):
    """``candidates[0].content.parts`` — так віддає Gemini."""

    def events(self) -> list[dict]:
        return [{"candidates": [{"content": {"parts": [{"text": piece}]},
                                 "finishReason": "STOP"}]}
                for piece in self.PIECES]


def anthropic_handler(pieces: list[str]) -> type[AnthropicStub]:
    return type("AnthropicHandler", (AnthropicStub,), {"PIECES": tuple(pieces)})


def gemini_handler(pieces: list[str]) -> type[GeminiStub]:
    return type("GeminiHandler", (GeminiStub,), {"PIECES": tuple(pieces)})
