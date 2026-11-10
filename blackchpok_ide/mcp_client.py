"""Клієнт MCP (Model Context Protocol) для BlackChpok IDE — лише stdlib.

Транспорт — stdio: кожен рядок stdin/stdout є одним JSON-RPC 2.0 об'єктом.
Модуль не імпортує tkinter і безпечний для імпорту з тестів та консольних
перевірок (`python main.py --selftest`).

Можливості:

* запуск сервера як дочірнього процесу та ініціалізація (handshake);
* ``tools/list`` з пагінацією через ``cursor``;
* ``tools/call`` з перетворенням MCP-контенту на звичайний текст;
* перетворення MCP-інструментів на OpenAI-схеми з простором імен
  ``mcp__<сервер>__<інструмент>``;
* менеджер кількох серверів для UI.

Приклад::

    from blackchpok_ide.mcp_client import McpClient, McpServerConfig

    client = McpClient(McpServerConfig(name="fs", command="node", args=["fs.js"]))
    client.start()
    client.initialize()
    ok, text = client.call_tool("read_file", {"path": "a.txt"})
    client.stop()
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger("blackchpok.mcp")

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO: dict[str, str] = {"name": "BlackChpokIDE", "version": "1.0"}

STDERR_TAIL_LINES = 60
MAX_PAGES = 5
NAME_LIMIT = 64
NAMESPACE_PREFIX = "mcp__"

__all__ = [
    "CLIENT_INFO",
    "MAX_PAGES",
    "McpClient",
    "McpError",
    "McpManager",
    "McpServerConfig",
    "PROTOCOL_VERSION",
    "content_to_text",
    "namespaced_tool_name",
    "sanitize_server_name",
]


# ─────────────────────────────────────────────────────────────────────────────
# Допоміжні перетворення (усі терпимі до «сміття» у конфігурації)
# ─────────────────────────────────────────────────────────────────────────────


def _as_text(value: Any) -> str:
    """Перетворити будь-що на рядок без винятків."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _as_args(value: Any) -> list[str]:
    """Аргументи команди: список, рядок або щось інше."""
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = item if isinstance(item, str) else str(item)
            if text:
                result.append(text)
        return result
    if isinstance(value, str):
        return [part for part in value.split() if part]
    return []


def _as_env(value: Any) -> dict[str, str]:
    """Змінні середовища: лише dict, ключі та значення — рядки."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if key is None or item is None:
            continue
        result[str(key)] = item if isinstance(item, str) else str(item)
    return result


def _as_bool(value: Any, default: bool = True) -> bool:
    """Логічне значення з рядків/чисел; невідоме — ``default``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "так", "увімк", "вкл"}:
            return True
        if text in {"0", "false", "no", "off", "ні", "вимк", "викл"}:
            return False
    return default


def _sanitize(part: str) -> str:
    """Лишити в назві тільки ``[A-Za-z0-9_]``, стиснувши повтори ``_``."""
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(part))
    text = re.sub(r"_{2,}", "_", text)
    return text.strip("_")


def sanitize_server_name(name: str) -> str:
    """Безпечна частина назви сервера для простору імен інструментів."""
    return _sanitize(name) or "server"


def namespaced_tool_name(server: str, tool: str) -> str:
    """Побудувати ``mcp__<сервер>__<інструмент>`` (не довше 64 символів).

    За можливості зберігаються і префікс ``mcp__``, і назва інструмента;
    якщо місця бракує — спершу коротшає назва інструмента, потім сервера.
    """
    server_part = sanitize_server_name(server)
    tool_part = _sanitize(tool) or "tool"
    prefix = f"{NAMESPACE_PREFIX}{server_part}__"
    if len(prefix) + len(tool_part) <= NAME_LIMIT:
        return prefix + tool_part
    room = NAME_LIMIT - len(prefix)
    if room >= 1:
        return prefix + tool_part[:room]
    room = NAME_LIMIT - len(NAMESPACE_PREFIX) - 2 - 1
    server_part = server_part[: max(1, room)]
    prefix = f"{NAMESPACE_PREFIX}{server_part}__"
    room = NAME_LIMIT - len(prefix)
    if room <= 0:
        return prefix[:NAME_LIMIT]
    return prefix + tool_part[:room]


def content_to_text(content: Any) -> str:
    """Перетворити MCP ``content`` на простий текст для моделі/UI.

    Текстові елементи з'єднуються через новий рядок, інші типи описуються
    коротко: ``[image image/png]``, ``[resource file:///a.txt]`` тощо.
    """
    if content is None:
        return ""
    items = content if isinstance(content, list) else [content]
    parts: list[str] = []
    for item in items:
        if isinstance(item, str):
            if item:
                parts.append(item)
            continue
        if not isinstance(item, dict):
            text = str(item)
            if text:
                parts.append(text)
            continue
        kind = str(item.get("type") or "")
        if kind == "text":
            text = item.get("text")
            if text is None:
                continue
            text = text if isinstance(text, str) else str(text)
            if text:
                parts.append(text)
        elif kind == "image":
            parts.append(f"[image {item.get('mimeType') or 'unknown'}]")
        elif kind == "audio":
            parts.append(f"[audio {item.get('mimeType') or 'unknown'}]")
        elif kind == "resource":
            resource = item.get("resource")
            resource = resource if isinstance(resource, dict) else {}
            uri = resource.get("uri") or item.get("uri") or ""
            body = resource.get("text")
            if isinstance(body, str) and body:
                parts.append(f"[resource {uri}]\n{body}")
            else:
                parts.append(f"[resource {uri}]".strip())
        elif kind == "resource_link":
            parts.append(f"[resource_link {item.get('uri') or ''}]".strip())
        else:
            parts.append(f"[{kind or 'content'}]")
    return "\n".join(part for part in parts if part)


# ─────────────────────────────────────────────────────────────────────────────
# Конфігурація сервера
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class McpServerConfig:
    """Опис одного MCP-сервера (запис із mcp.json / налаштувань IDE)."""

    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    source: str = ""

    @classmethod
    def from_dict(cls, data: Any, name: str = "") -> "McpServerConfig":
        """Створити конфігурацію з dict, не падаючи на кривих даних."""
        source: dict[str, Any] = data if isinstance(data, dict) else {}
        config = cls()
        given_name = name.strip() if isinstance(name, str) else ""
        config.name = given_name or _as_text(source.get("name"))
        config.command = _as_text(source.get("command"))
        config.args = _as_args(source.get("args"))
        config.cwd = _as_text(source.get("cwd"))
        config.env = _as_env(source.get("env"))
        config.enabled = _as_bool(source.get("enabled"), default=True)
        config.source = _as_text(source.get("source"))
        return config

    def to_dict(self) -> dict[str, Any]:
        """Серіалізувати назад у dict (для збереження налаштувань)."""
        return {
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "cwd": self.cwd,
            "env": dict(self.env),
            "enabled": bool(self.enabled),
            "source": self.source,
        }

    @property
    def display(self) -> str:
        """Короткий людський підпис: ``назва · команда перший_аргумент``."""
        label = self.name.strip() or "(без назви)"
        command = self.command.strip()
        if command and self.args:
            command = f"{command} {self.args[0]}"
        elif not command:
            command = "(без команди)"
        return f"{label} · {command}"


class McpError(RuntimeError):
    """Помилка транспорту MCP: процес, таймаут, некоректна відповідь."""


class _Pending:
    """Очікувана відповідь на конкретний запит."""

    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: McpError | None = None


def _message_id(value: Any) -> int | None:
    """Нормалізувати ``id`` відповіді до int (наші id — int)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Клієнт одного сервера
# ─────────────────────────────────────────────────────────────────────────────


class McpClient:
    """Клієнт одного MCP-сервера через stdio.

    Потоки: один читає stdout (відповіді + шум), другий збирає stderr.
    Клас потокобезпечний: запити з різних робочих потоків IDE не плутаються.
    """

    def __init__(self, config: McpServerConfig, timeout: float = 30.0) -> None:
        if isinstance(config, McpServerConfig):
            self.config = config
        else:
            self.config = McpServerConfig.from_dict(config)
        try:
            self.timeout = max(0.1, float(timeout))
        except (TypeError, ValueError):
            self.timeout = 30.0

        self.server_info: dict[str, Any] = {}
        self.protocol_version: str = ""

        self._process: subprocess.Popen[str] | None = None
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._stderr_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._next_id = 0
        self._initialized = False
        self._dead = False
        self._dead_reason = ""
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._tools: list[dict[str, Any]] = []
        self._tool_names: dict[str, str] = {}

    # ── властивості ──────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        """Процес живий і рукостискання вже виконано."""
        process = self._process
        return bool(
            process is not None
            and process.poll() is None
            and self._initialized
            and not self._dead
        )

    @property
    def started(self) -> bool:
        """Процес запущено (навіть якщо initialize ще не викликали)."""
        process = self._process
        return process is not None and process.poll() is None

    @property
    def stderr_tail(self) -> list[str]:
        """Останні рядки stderr сервера (до 60)."""
        with self._stderr_lock:
            return list(self._stderr)

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Кеш інструментів; порожній до ``initialize``."""
        with self._lock:
            return list(self._tools)

    @property
    def namespace_prefix(self) -> str:
        """Префікс простору імен цього сервера, напр. ``mcp__fake__``."""
        return f"{NAMESPACE_PREFIX}{sanitize_server_name(self.config.name)}__"

    def full_tool_name(self, tool_name: str) -> str:
        """Повна (namespaced) назва інструмента для функцій моделі."""
        return namespaced_tool_name(self.config.name, tool_name)

    # ── запуск і зупинка ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Запустити дочірній процес і два потоки обслуговування.

        Багаторазовий виклик нічого не робить, якщо процес уже живий.
        """
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                return
        command = (self.config.command or "").strip()
        if not command:
            raise McpError(f"MCP-сервер «{self.config.display}»: не вказано команду запуску")

        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in (self.config.env or {}).items()})
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "cwd": self.config.cwd or None,
            "env": env,
        }
        if os.name == "nt":  # Windows: без вікна консолі
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        argv = [command, *[str(item) for item in self.config.args]]
        try:
            process = subprocess.Popen(argv, shell=False, **popen_kwargs)
        except (OSError, ValueError) as exc:
            raise McpError(
                f"Не вдалося запустити MCP-сервер «{self.config.display}»: {exc}"
            ) from exc

        with self._lock:
            self._process = process
            self._dead = False
            self._dead_reason = ""
            self._initialized = False
            self.server_info = {}
            self.protocol_version = ""
            self._tools = []
            self._tool_names = {}
            self._pending.clear()
            with self._stderr_lock:
                self._stderr.clear()

        reader = threading.Thread(
            target=self._reader_loop,
            args=(process.stdout,),
            name=f"mcp-stdout-{self.config.name or 'server'}",
            daemon=True,
        )
        drainer = threading.Thread(
            target=self._stderr_loop,
            args=(process.stderr,),
            name=f"mcp-stderr-{self.config.name or 'server'}",
            daemon=True,
        )
        self._threads = [reader, drainer]
        reader.start()
        drainer.start()

    def stop(self, grace: float = 3.0) -> None:
        """Зупинити сервер: terminate → kill, закрити канали, зібрати потоки.

        Ідемпотентний і ніколи не кидає винятків.
        """
        try:
            grace_seconds = max(0.05, float(grace))
        except (TypeError, ValueError):
            grace_seconds = 3.0
        label = self.config.name or "mcp"
        with self._lock:
            process = self._process
            self._process = None
            self._initialized = False
            if not self._dead:
                self._dead = True
                self._dead_reason = "клієнт зупинено"
        self._fail_pending(f"MCP-сервер «{label}» зупинено")

        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except OSError as exc:
                        LOG.debug("MCP: terminate не вдався: %s", exc)
                    try:
                        process.wait(timeout=grace_seconds)
                    except subprocess.TimeoutExpired:
                        # Не слухається — вбиваємо. Якщо й це не вдалось,
                        # процес лишиться сиротою і триматиме пам'ять, тож
                        # про це треба знати.
                        try:
                            process.kill()
                        except OSError as exc:
                            LOG.warning(
                                "MCP: сервер «%s» не завершився й не вбився: %s",
                                self.config.name or "mcp", exc)
                        try:
                            process.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            LOG.warning(
                                "MCP: сервер «%s» не завершився після kill",
                                self.config.name or "mcp")
            except OSError as exc:
                LOG.debug("MCP: завершення процесу: %s", exc)
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except (OSError, ValueError) as exc:
                    LOG.debug("MCP: потік не закрито: %s", exc)

        deadline = time.monotonic() + 1.5
        for thread in list(self._threads):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                thread.join(remaining)
            except RuntimeError:
                pass
        self._threads = []
        with self._lock:
            self._tools = []
            self._tool_names = {}

    # ── рукостискання і протокол ─────────────────────────────────────────────

    def initialize(self) -> dict[str, Any]:
        """MCP-handshake: ``initialize`` + нотифікація ``initialized``.

        Повертає ``serverInfo`` сервера. Повторний виклик нічого не робить.
        """
        if self._initialized:
            return dict(self.server_info)
        self._ensure_alive()
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        }
        result = self._request("initialize", params)
        if isinstance(result, dict):
            info = result.get("serverInfo")
            self.server_info = info if isinstance(info, dict) else {}
            version = result.get("protocolVersion")
            self.protocol_version = str(version) if version else PROTOCOL_VERSION
        else:
            self.server_info = {}
            self.protocol_version = PROTOCOL_VERSION
        # Нотифікація — JSON-RPC повідомлення БЕЗ "id", відповіді не чекаємо.
        self._notify("notifications/initialized")
        self._initialized = True
        try:
            self.refresh_tools()
        except McpError as exc:
            LOG.warning("MCP «%s»: tools/list не вдався: %s", self.config.name, exc)
        except Exception:  # noqa: BLE001 - дивна відповідь сервера не має валити initialize
            LOG.warning("MCP «%s»: tools/list не вдався", self.config.name, exc_info=True)
        return dict(self.server_info)

    def refresh_tools(self) -> list[dict[str, Any]]:
        """Оновити кеш інструментів через ``tools/list``."""
        tools = self.list_tools()
        with self._lock:
            self._tools = tools
        self._refresh_tool_names()
        return list(tools)

    def list_tools(self) -> list[dict[str, Any]]:
        """Отримати інструменти, достроково зупинившись після 5 сторінок."""
        collected: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(MAX_PAGES):
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            result = self._request("tools/list", params)
            if not isinstance(result, dict):
                break
            page_tools = result.get("tools")
            if isinstance(page_tools, list):
                collected.extend(item for item in page_tools if isinstance(item, dict))
            next_cursor = result.get("nextCursor")
            cursor = next_cursor if isinstance(next_cursor, str) and next_cursor else None
            if not cursor:
                break
        return collected

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> tuple[bool, str]:
        """Викликати інструмент сервера.

        Помилки рівня інструмента повертаються як ``(False, текст)``;
        ``McpError`` кидається лише для транспорту та таймаутів.
        """
        tool_name = str(name or "")
        if not tool_name:
            return False, "Порожня назва MCP-інструмента."
        args = arguments if isinstance(arguments, dict) else {}
        result = self._request("tools/call", {"name": tool_name, "arguments": args})
        if not isinstance(result, dict):
            return False, str(result)
        text = content_to_text(result.get("content"))
        if not text:
            structured = result.get("structuredContent")
            if structured is not None:
                try:
                    text = json.dumps(structured, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    text = str(structured)
        is_error = bool(result.get("isError"))
        if not text:
            text = "Інструмент не повернув тексту." if not is_error else "Інструмент повернув помилку без опису."
        return (not is_error, text)

    def tool_schemas(self) -> list[dict[str, Any]]:
        """OpenAI-схеми функцій для всіх інструментів сервера."""
        schemas: list[dict[str, Any]] = []
        for tool in self.tools:
            tool_name = str(tool.get("name") or "")
            if not tool_name:
                continue
            full_name = self.full_tool_name(tool_name)
            parameters = tool.get("inputSchema")
            if not isinstance(parameters, dict):
                parameters = {"type": "object", "properties": {}}
            description = tool.get("description")
            description = str(description) if description else (
                f"MCP-інструмент {tool_name} із сервера «{self.config.name or 'mcp'}»"
            )
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": full_name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        return schemas

    def call_namespaced(self, name: str, arguments: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Викликати інструмент за повним ім'ям ``mcp__сервер__інструмент``."""
        if not isinstance(name, str) or not name:
            raise McpError("Порожня назва MCP-інструмента.")
        prefix = self.namespace_prefix
        if not name.startswith(prefix):
            raise McpError(
                f"Інструмент «{name}» не належить MCP-серверу «{self.config.name or 'mcp'}»"
            )
        remainder = name[len(prefix):]
        with self._lock:
            tool_name = self._tool_names.get(name) or remainder
        if not tool_name:
            raise McpError(f"Не вдалося визначити інструмент за назвою «{name}»")
        return self.call_tool(tool_name, arguments)

    # ── внутрішнє: запити ────────────────────────────────────────────────────

    def _request(
        self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> Any:
        """Надіслати запит і дочекатися відповіді з id (або впасти швидко)."""
        self._ensure_alive()
        limit = self.timeout if timeout is None else max(0.1, float(timeout))
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            slot = _Pending()
            self._pending[request_id] = slot

        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._write(payload)
        except McpError:
            with self._lock:
                self._pending.pop(request_id, None)
            raise

        deadline = time.monotonic() + limit
        try:
            while not slot.event.is_set():
                if self._dead:
                    if slot.error is None:
                        slot.error = McpError(self._dead_text())
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpError(self._timeout_text(method, limit))
                slot.event.wait(min(0.1, remaining))
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if slot.error is not None:
            raise slot.error
        return slot.result

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """JSON-RPC нотифікація (без ``id``) — відповіді не буде."""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        """Записати один JSON-об'єкт одним рядком у stdin сервера."""
        data = json.dumps(payload, ensure_ascii=False)
        with self._write_lock:
            process = self._process
            if process is None or process.stdin is None:
                raise McpError(f"MCP-сервер «{self.config.name or 'mcp'}» вже зупинено.")
            try:
                process.stdin.write(data + "\n")
                process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise McpError(
                    f"Не вдалося надіслати запит MCP-серверу «{self.config.name or 'mcp'}»: {exc}"
                ) from exc

    def _safe_write(self, payload: dict[str, Any]) -> None:
        """Відповісти серверу, ігноруючи будь-які помилки каналу.

        Це відповідь на вхідний запит сервера (не наш виклик інструмента):
        якщо канал уже закритий, повідомляти нема кому. Але й мовчати не
        варто — без цього рядка неможливо зрозуміти, чому сервер чекає на
        відповідь, яку ми не надіслали.
        """
        try:
            self._write(payload)
        except McpError as exc:
            LOG.debug("MCP: відповідь серверу не надіслано: %s", exc)

    # ── внутрішнє: читання потоків ───────────────────────────────────────────

    def _reader_loop(self, stream: Any) -> None:
        """Читати stdout: відповіді за id, шум і нотифікації — пропускати."""
        try:
            if stream is not None:
                for raw in stream:
                    try:
                        self._handle_line(raw)
                    except Exception:  # noqa: BLE001 - фоновий потік не має падати
                        LOG.debug("MCP: помилка обробки рядка", exc_info=True)
        except (OSError, ValueError) as exc:
            # Потік закрився. Це нормальне завершення роботи сервера, але
            # саме воно пояснює, чому інструменти раптом стали недоступні:
            # без цього рядка в журналі була лише «тиша».
            if not self._dead:
                LOG.info("MCP: канал читання закрито (%s)", exc)
        finally:
            self._set_dead(self._exit_reason())

    def _handle_line(self, raw: Any) -> None:
        text = raw.strip() if isinstance(raw, str) else str(raw).strip()
        if not text:
            return
        try:
            message = json.loads(text)
        except ValueError:
            return  # сервер пише логи в stdout — це нормально
        if not isinstance(message, dict):
            return
        message_id = message.get("id")
        if message_id is not None and ("result" in message or "error" in message):
            key = _message_id(message_id)
            if key is None:
                return
            with self._lock:
                slot = self._pending.pop(key, None)
            if slot is None:
                return
            if message.get("error") is not None:
                slot.error = McpError(self._server_error_text(message.get("error")))
            else:
                slot.result = message.get("result")
            slot.event.set()
            return
        if "method" in message and message_id is not None:
            # Запит від сервера до клієнта — ми таких не підтримуємо.
            self._safe_write(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {
                        "code": -32601,
                        "message": "Клієнт BlackChpok IDE не підтримує цей метод",
                    },
                }
            )

    def _stderr_loop(self, stream: Any) -> None:
        """Збирати stderr у кільцевий буфер (останні 60 рядків)."""
        try:
            if stream is None:
                return
            for raw in stream:
                line = str(raw).rstrip("\r\n")
                if not line.strip():
                    continue
                with self._stderr_lock:
                    self._stderr.append(line)
        except (OSError, ValueError) as exc:
            # stderr — це діагностика самої серверної частини; коли він
            # закривається, причину збою вже не побачити ніде.
            LOG.debug("MCP: потік stderr закрито: %s", exc)

    def _exit_reason(self) -> str:
        process = self._process
        if process is None:
            return "клієнт зупинено"
        code: int | None = None
        try:
            code = process.poll()
        except Exception:  # noqa: BLE001
            code = None
        if code is None:
            return "сервер закрив потік відповідей"
        return f"процес завершився з кодом {code}"

    # ── внутрішнє: стани помилок ─────────────────────────────────────────────

    def _ensure_alive(self) -> None:
        process = self._process
        label = self.config.name or "mcp"
        if process is None:
            raise McpError(f"MCP-сервер «{label}» не запущено.")
        if self._dead:
            raise McpError(self._dead_text())
        if process.poll() is not None:
            # Процес помер, а потік stderr ще може дописувати хвіст — даємо йому
            # коротку мить, щоб повідомлення містило справжню причину.
            self._set_dead(self._exit_reason())
            self._await_stderr(0.2)
            raise McpError(self._dead_text())

    def _await_stderr(self, seconds: float) -> None:
        """Дочекатися, поки потік stderr допише хвіст (не більше ``seconds``)."""
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if any(thread.name.startswith("mcp-stderr") and thread.is_alive() for thread in self._threads):
                time.sleep(0.02)
                continue
            return

    def _set_dead(self, reason: str) -> None:
        with self._lock:
            if self._dead:
                return
            self._dead = True
            self._dead_reason = str(reason)
            self._initialized = False
            pending = list(self._pending.values())
            self._pending.clear()
        text = self._dead_text()
        for slot in pending:
            if not slot.event.is_set():
                slot.error = McpError(text)
                slot.event.set()

    def _fail_pending(self, message: str) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for slot in pending:
            if not slot.event.is_set():
                slot.error = McpError(message)
                slot.event.set()

    def _stderr_text(self, lines: int = 15) -> str:
        with self._stderr_lock:
            tail = list(self._stderr)[-lines:]
        return "\n".join(tail).strip()

    def _dead_text(self) -> str:
        label = self.config.name or "mcp"
        reason = self._dead_reason or "невідома причина"
        base = f"MCP-сервер «{label}» недоступний: {reason}"
        tail = self._stderr_text()
        return f"{base}\nОстанні рядки stderr:\n{tail}" if tail else base

    def _timeout_text(self, method: str, limit: float) -> str:
        label = self.config.name or "mcp"
        base = (
            f"Час очікування відповіді MCP-сервера «{label}» на «{method}» "
            f"вичерпано ({limit:g} с)."
        )
        tail = self._stderr_text()
        return f"{base}\nОстанні рядки stderr:\n{tail}" if tail else base

    def _server_error_text(self, error: Any) -> str:
        label = self.config.name or "mcp"
        if isinstance(error, dict):
            code = error.get("code", "?")
            message = error.get("message")
            message = str(message) if message else "без опису"
            return f"MCP-сервер «{label}» повернув помилку {code}: {message}"
        return f"MCP-сервер «{label}» повернув помилку: {error}"

    def _refresh_tool_names(self) -> None:
        with self._lock:
            tools = list(self._tools)
        mapping: dict[str, str] = {}
        for tool in tools:
            tool_name = str(tool.get("name") or "")
            if tool_name:
                mapping[self.full_tool_name(tool_name)] = tool_name
        with self._lock:
            self._tool_names = mapping


# ─────────────────────────────────────────────────────────────────────────────
# Менеджер кількох серверів (для UI та агента)
# ─────────────────────────────────────────────────────────────────────────────


def _stop_client_with_timeout(client: Any, timeout: float) -> bool:
    """Викликати ``client.stop()`` і дочекатися, не блокуючи назавжди.

    Навіщо окремий потік: ``stop()`` надсилає запит і чекає на відповідь
    сервера. Якщо сервер уже завис, цей виклик міг тягнутись десятки секунд
    і блокував закриття вікна IDE. Тепер чекаємо рівно ``timeout``.
    """
    import threading as _threading

    done = _threading.Event()
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            client.stop()
            box["ok"] = True
        except Exception as exc:  # noqa: BLE001 - причина йде в результат
            box["error"] = exc
            LOG.debug("зупинка MCP-клієнта впала", exc_info=True)
        finally:
            done.set()

    thread = _threading.Thread(target=_run, name="mcp-stop", daemon=True)
    thread.start()
    thread.join(timeout=max(0.1, float(timeout)))
    return bool(done.is_set() and box.get("ok"))


class McpManager:
    """Набір запущених MCP-серверів із наскрізним маршрутизацією викликів."""
    def __init__(self) -> None:
        self.servers: dict[str, McpClient] = {}
        self._status: dict[str, str] = {}
        self._lock = threading.RLock()
        #: Конфіги запущених серверів — потрібні watchdog'у для перезапуску.
        self._configs: dict[str, McpServerConfig] = {}
        #: Активний супервізор (якщо стеження ввімкнено).
        self._watching = None

    # ── конфігурація з файлів ────────────────────────────────────────────────

    @staticmethod
    def load_configs(paths: Iterable[Path | str]) -> list[McpServerConfig]:
        """Прочитати конфігурації з JSON-файлів, пропускаючи погані.

        Приймає формат ``{"mcpServers": {name: {...}}}`` і «голий» dict
        ``{name: {...}}``. Пізніші файли перекривають попередні за назвою.
        """
        found: dict[str, McpServerConfig] = {}
        for raw_path in paths or []:
            try:
                path = Path(raw_path)
            except (TypeError, ValueError):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, ValueError, UnicodeError):
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            inner = data.get("mcpServers")
            entries = inner if isinstance(inner, dict) else data
            for name, raw_config in entries.items():
                if not isinstance(name, str) or not isinstance(raw_config, dict):
                    continue
                config = McpServerConfig.from_dict(raw_config, name=name)
                config.source = str(path)
                found[name] = config
        return list(found.values())

    # ── запуск/зупинка ───────────────────────────────────────────────────────

    def start_all(self, configs: list[McpServerConfig]) -> dict[str, str]:
        """Запустити й ініціалізувати всі увімкнені сервери.

        Помилки окремих серверів не переривають решту; повертає статуси
        (``працює`` / ``не запустився: ...`` / ``вимкнено``).
        """
        statuses: dict[str, str] = {}
        for config in configs or []:
            if not isinstance(config, McpServerConfig):
                continue
            name = config.name.strip() or "mcp-server"
            if name in statuses:
                name = f"{name}-{len(statuses) + 1}"
            if not config.enabled:
                statuses[name] = "вимкнено"
                with self._lock:
                    self._status[name] = "вимкнено"
                continue
            client = McpClient(config)
            with self._lock:
                previous = self.servers.get(name)
                self.servers[name] = client
                # Конфіг запам'ятовуємо: без нього watchdog не зможе
                # перезапустити сервер, що помер.
                if not hasattr(self, "_configs"):
                    self._configs = {}
                self._configs[name] = config
            if previous is not None:
                previous.stop()
            try:
                client.start()
                client.initialize()
                text = "працює"
            except Exception as exc:  # noqa: BLE001 - один сервер не має ламати решту
                client.stop()
                text = f"не запустився: {self._short_error(exc)}"
                LOG.warning("MCP «%s»: %s", name, text)
            statuses[name] = text
            with self._lock:
                self._status[name] = text
        return statuses

    def stop_all(self, timeout: float = 5.0) -> dict[str, bool]:
        """Зупинити всі сервери й **дочекатися** цього.

        ``docs/MCP_SUPERVISOR.md`` §5: раніше «graceful shutdown із
        очікуванням — частково: ``stop_all`` у потоці без очікування».
        Тепер кожен сервер зупиняється з обмеженням часу, і результат
        видно: ``{ім'я: чи справді зупинився}``. Сервер, що завис, чесно
        позначений ``False``, а не виданий за зупинений.
        """
        self.stop_watchdog()
        with self._lock:
            clients = list(self.servers.values())
            names = list(self.servers)
            self.servers.clear()
            self._status.clear()
            self._configs.clear()
        results: dict[str, bool] = {}
        for name, client in zip(names, clients):
            results[name] = _stop_client_with_timeout(client, timeout)
            if not results[name]:
                LOG.warning("MCP «%s» не зупинився за %.0f с", name, timeout)
        return results

    # ── супервізор ───────────────────────────────────────────────────────────
    # ``docs/MCP_SUPERVISOR.md`` §5: health-check, ретрай із бекофом і
    # watchdog раніше були відсутні. Тепер вони живуть у
    # :mod:`blackchpok_ide.mcp_supervisor`, а менеджер лише делегує — щоб не
    # переписувати робочий транспорт і не ризикувати регресією.

    def _supervisor(self):
        """Створити супервізор поверх цього менеджера (ліниво)."""
        from .mcp_supervisor import MpcSupervisor

        return MpcSupervisor(McpClient)

    def health_check(self, name: str):
        """Перевірити один сервер по-справжньому.

        На відміну від :attr:`status`, не вірить рядку «працює», а питає
        ``tools/list`` і перевіряє придатність схем (§3 документа).
        """
        from .mcp_supervisor import HealthReport, schema_is_usable

        with self._lock:
            client = self.servers.get(name)
        report = HealthReport(name=name)
        if client is None:
            report.reason = "сервер не запущено"
            return report
        if not client.running:
            report.reason = "процес не працює"
            return report
        try:
            schemas = client.list_tools() or []
        except Exception as exc:  # noqa: BLE001 - причина йде у звіт
            report.reason = f"tools/list не відповів: {exc}"
            return report
        usable = [s for s in schemas if schema_is_usable(s)]
        report.tools = len(schemas)
        report.valid_schemas = len(usable)
        if not schemas:
            report.reason = "сервер не віддав жодного інструмента"
        elif not usable:
            report.reason = (f"{len(schemas)} схем, жодна не придатна")
        else:
            report.ok = True
            if len(usable) < len(schemas):
                report.reason = (f"придатних {len(usable)} з {len(schemas)} — "
                                 f"решту відкинуто")
        return report

    def health_check_all(self) -> dict:
        with self._lock:
            names = list(self.servers)
        return {name: self.health_check(name) for name in names}

    def start_watchdog(self, interval: float = 5.0) -> None:
        """Підняти стеження за процесами (перезапуск мертвих із бекофом)."""
        supervisor = self._supervisor()
        with self._lock:
            self._watching = supervisor
            configs = dict(getattr(self, "_configs", {}))
        for name, client in list(self.servers.items()):
            config = configs.get(name)
            if config is not None:
                supervisor._configs[name] = config
            supervisor._clients[name] = client
        supervisor.start_watchdog(interval=interval)

    def stop_watchdog(self) -> None:
        supervisor = getattr(self, "_watching", None)
        if supervisor is not None:
            supervisor.stop_watchdog()
            self._watching = None

    def add(self, config: McpServerConfig, start: bool = True) -> McpClient:
        """Приєднати сервер під час роботи IDE (за потреби — одразу запустити)."""
        name = config.name.strip() or "mcp-server"
        client = McpClient(config)
        with self._lock:
            previous = self.servers.get(name)
            self.servers[name] = client
        if previous is not None:
            previous.stop()
        if not config.enabled:
            with self._lock:
                self._status[name] = "вимкнено"
            return client
        if not start:
            with self._lock:
                self._status[name] = "не запущено"
            return client
        try:
            client.start()
            client.initialize()
            text = "працює"
        except Exception as exc:  # noqa: BLE001
            client.stop()
            text = f"не запустився: {self._short_error(exc)}"
            LOG.warning("MCP «%s»: %s", name, text)
        with self._lock:
            self._status[name] = text
        return client

    def remove(self, name: str) -> bool:
        """Від'єднати й зупинити сервер. ``True`` — якщо він існував."""
        with self._lock:
            client = self.servers.pop(name, None)
            self._status.pop(name, None)
        if client is None:
            return False
        client.stop()
        return True

    # ── інформація для UI ────────────────────────────────────────────────────

    @property
    def status(self) -> dict[str, str]:
        """Статуси серверів: ``працює`` / ``не запустився: ...`` / ``вимкнено``."""
        with self._lock:
            return dict(self._status)

    def get(self, name: str) -> McpClient | None:
        with self._lock:
            return self.servers.get(name)

    def running_servers(self) -> list[McpClient]:
        with self._lock:
            clients = list(self.servers.values())
        return [client for client in clients if client.running]

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Усі OpenAI-схеми всіх працюючих серверів."""
        schemas: list[dict[str, Any]] = []
        for client in self.running_servers():
            try:
                schemas.extend(client.tool_schemas())
            except Exception:  # noqa: BLE001 - кеш уже перевірений
                LOG.debug("MCP: не вдалося побудувати схеми", exc_info=True)
        return schemas

    def tool_catalog(self) -> list[dict[str, Any]]:
        """Плоский список інструментів для вікна налаштувань."""
        catalog: list[dict[str, Any]] = []
        for client in self.running_servers():
            server_label = client.config.name or "mcp"
            for tool in client.tools:
                tool_name = str(tool.get("name") or "")
                if not tool_name:
                    continue
                description = tool.get("description")
                catalog.append(
                    {
                        "server": server_label,
                        "name": tool_name,
                        "full_name": client.full_tool_name(tool_name),
                        "description": str(description) if description else "",
                    }
                )
        return catalog

    # ── маршрутизація викликів ───────────────────────────────────────────────

    def handles(self, name: str) -> bool:
        """Чи відповідає назва ``mcp__сервер__...`` живому серверу."""
        return self._match(name) is not None

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Викликати ``mcp__сервер__інструмент``; невідомі назви — ``(False, текст)``."""
        if not isinstance(name, str) or not name.strip():
            return False, "Порожня назва MCP-інструмента."
        client = self._match(name)
        if client is None:
            available = sorted(item["full_name"] for item in self.tool_catalog())[:8]
            hint = ", ".join(available) if available else "немає"
            return False, f"Невідомий MCP-інструмент «{name}». Доступні: {hint}."
        args = arguments if isinstance(arguments, dict) else {}
        try:
            return client.call_namespaced(name, args)
        except McpError as exc:
            return False, str(exc)

    def _match(self, name: str) -> McpClient | None:
        if not isinstance(name, str) or not name.startswith(NAMESPACE_PREFIX):
            return None
        best: McpClient | None = None
        best_length = -1
        for client in self.running_servers():
            prefix = client.namespace_prefix
            if name.startswith(prefix) and len(prefix) > best_length:
                best = client
                best_length = len(prefix)
        return best

    @staticmethod
    def _short_error(exc: BaseException) -> str:
        text = str(exc).strip().splitlines()
        first = text[0] if text else type(exc).__name__
        return first[:160]
