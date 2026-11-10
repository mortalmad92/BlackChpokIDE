"""Крихітний MCP-сервер для тестів BlackChpok IDE (лише stdlib).

Транспорт — stdio: один JSON-RPC 2.0 об'єкт на рядок. Сервер уміє:

* ``initialize`` — повертає ``protocolVersion`` і ``serverInfo``;
* ``notifications/initialized`` — тиха нотифікація (без відповіді);
* ``tools/list`` — два інструменти: ``echo`` і ``fail``;
* ``tools/call`` — виклик ``echo`` / ``fail``;
* на невідомий метод — JSON-RPC помилка ``-32601``.

На старті в stdout друкується рядок, що НЕ є JSON, — це перевірка того,
що клієнт терпить «шум» у потоці відповідей.

Запуск вручну::

    python tests/fake_mcp_server.py
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "fake-mcp", "version": "0.1"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Повертає переданий текст без змін.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Текст для повтору"}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "Завжди завершується помилкою (для перевірки isError).",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
    },
]

NOISE_LINE = "fake-mcp: сервер стартував, шумовий рядок у stdout (не JSON)"


def _result(request_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text_content(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text}]


def handle(message: Any) -> dict[str, Any] | None:
    """Обробити одне повідомлення. ``None`` — відповіді не буде (нотифікація)."""
    if not isinstance(message, dict):
        return _error(None, -32600, "Некоректний запит")
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params")
    params = params if isinstance(params, dict) else {}

    if method == "notifications/initialized":
        return None
    if request_id is None:
        return None  # будь-яка інша нотифікація — тихо

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVER_INFO),
            },
        )

    if method == "tools/list":
        return _result(request_id, {"tools": [dict(tool) for tool in TOOLS]})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        if name == "echo":
            text = arguments.get("text")
            text = text if isinstance(text, str) else ""
            return _result(
                request_id,
                {"content": _text_content(text), "isError": False},
            )
        if name == "fail":
            return _result(
                request_id,
                {"content": _text_content("навмисна помилка інструмента"), "isError": True},
            )
        return _error(request_id, -32602, f"Невідомий інструмент: {name}")

    return _error(request_id, -32601, f"Невідомий метод: {method}")


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Головний цикл: читати рядки, відповідати рядками."""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    sink.write(NOISE_LINE + "\n")
    sink.flush()
    for raw in source:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        try:
            reply = handle(message)
        except Exception as exc:  # noqa: BLE001 - сервер не має падати на тестах
            reply = _error(message.get("id"), -32603, f"Внутрішня помилка: {exc}")
        if reply is None:
            continue
        sink.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sink.flush()
    return 0


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
