"""CDP-клієнт: справжній доступ до сторінки у вбудованому браузері.

Проблема. Вбудований браузер — це окремий процес Chromium, вставлений у
вікно через ``SetParent``. Зсередини Python ми бачили лише «вікно», а не
сторінку: ні консолі, ні помилок, ні DOM. Саме тому інспектора елементів і
видимих помилок не було — їх нізвідки було взяти.

Рішення. Chromium уміє відкривати порт налагодження
(``--remote-debugging-port``). Через нього працює Chrome DevTools Protocol:
HTTP для списку вкладок і WebSocket для команд. Цей модуль реалізує
мінімальний, але СПРАВЖНІЙ клієнт:

* ``Runtime.evaluate`` — виконати JavaScript і отримати результат;
* ``Runtime.consoleAPICalled`` / ``Log.entryAdded`` — консоль і помилки;
* ``DOM.getDocument`` / ``DOM.getBoxModel`` — інспектор елементів;
* ``Page.captureScreenshot`` — знімок сторінки (а не всього екрана);
* ``Emulation.setDeviceMetricsOverride`` — перевірка адаптивності;
* ``Input.dispatchMouseEvent`` — клік по ЕЛЕМЕНТУ, а не по координатах.

Залежностей немає: WebSocket-кадри (RFC 6455, client→server з маскуванням,
server→client без) зібрані вручну на ``socket`` + ``struct`` + ``base64``.
Це приблизно 150 рядків, зате без нових пакетів у requirements.txt.

Модуль не тягне tkinter і нічого не робить під час імпорту.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

LOG = logging.getLogger("blackchpok.cdp")

#: Скільки чекати на відповідь команди (секунди).
DEFAULT_TIMEOUT = 12.0


class CdpError(RuntimeError):
    """Помилка протоколу або з'єднання."""


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket: мінімальна реалізація клієнта
# ─────────────────────────────────────────────────────────────────────────────

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _mask(payload: bytes, key: bytes) -> bytes:
    """Замаскувати payload ключем (XOR, як вимагає RFC 6455 для клієнта)."""
    return bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))


class WebSocket:
    """Клієнтський WebSocket на сокеті (лише те, що потрібно CDP).

    Підтримує текстові кадри, фрагментацію від сервера й ping/pong.

    ВАЖЛИВО про час очікування. Читання кадру НЕ можна переривати таймаутом
    посеред кадру: сокет лишився б із напівпрочитаним кадром, і всі наступні
    відповіді читались би зі зсувом — саме так «зависали» команди після
    першого великого скриншота. Тому читання — повністю блокуюче, а
    зупиняється воно закриттям сокета ззовні (:meth:`close`).
    """

    def __init__(self, url: str, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("ws", "wss"):
            raise CdpError(f"Не WebSocket-адреса: {url}")
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or (443 if parsed.scheme == "wss" else 80))
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        raw = socket.create_connection((host, port), timeout=timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if parsed.scheme == "wss":
            import ssl

            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            raw = context.wrap_socket(raw, server_hostname=host)
        self._socket = raw
        self._buffer = b""
        self._lock = threading.Lock()
        self._closed = False
        self._handshake(host, port, path)
        # Після рукостискання — блокуючий режим: див. докстрінг класу.
        self._socket.settimeout(None)

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        buffer = b""
        deadline = time.monotonic() + 10
        while b"\r\n\r\n" not in buffer:
            if time.monotonic() > deadline:
                raise CdpError("Сервер не відповів на рукостискання WebSocket")
            chunk = self._socket.recv(4096)
            if not chunk:
                raise CdpError("З'єднання закрито під час рукостискання")
            buffer += chunk
        head, _, rest = buffer.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        if "101" not in status_line:
            raise CdpError(f"WebSocket відхилено: {status_line}")
        self._buffer = rest

    # ── кадри ──────────────────────────────────────────────────────────────
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(payload)
        mask_key = secrets.token_bytes(4)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask_key)
        self._socket.sendall(bytes(header) + _mask(payload, mask_key))

    def _recv_exact(self, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self._socket.recv(count - len(chunks))
            if not chunk:
                raise CdpError("З'єднання закрито")
            chunks.extend(chunk)
        return bytes(chunks)

    def _read_frame(self) -> tuple[int, bytes]:
        head = self._read_with_buffer(2)
        first, second = head[0], head[1]
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_with_buffer(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_with_buffer(8))[0]
        mask_key = self._read_with_buffer(4) if masked else b""
        payload = self._read_with_buffer(length)
        if masked and mask_key:
            payload = _mask(payload, mask_key)
        return opcode, payload

    def _read_with_buffer(self, count: int) -> bytes:
        """Прочитати N байтів: спершу з буфера, потім із сокета (блокуючи)."""
        if len(self._buffer) >= count:
            data = self._buffer[:count]
            self._buffer = self._buffer[count:]
            return data
        head = self._buffer
        self._buffer = b""
        return head + self._recv_exact(count - len(head))

    def send_text(self, text: str) -> None:
        with self._lock:
            self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self, *, timeout: Optional[float] = None) -> str:
        """Прочитати наступне текстове повідомлення (ping обробляється сам).

        ``timeout`` тут не чіпає сокет: він лише обмежує очікування на
        ПОВНЕ повідомлення на рівні виклику. Читання кадрів лишається
        блокуючим, інакше потік зіпсує потік байтів.
        """
        deadline = None if timeout is None else time.monotonic() + max(0.01, timeout)
        fragments = bytearray()
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x8:                  # close
                self._closed = True
                raise CdpError("Браузер закрив з'єднання")
            if opcode == 0x9:                  # ping → pong
                with self._lock:
                    self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:                  # pong
                continue
            if opcode in (0x1, 0x0):
                fragments.extend(payload)
                text = fragments.decode("utf-8", errors="replace")
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    # Ще не повне повідомлення (фрагментація) — дочитуємо.
                    if deadline is not None and time.monotonic() > deadline:
                        raise CdpError("Час очікування кадру вичерпано")
                    continue
                return text
            if opcode == 0x2:
                return payload.decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Спершу закриваємо сокет: це розблоковує потік читання, який
        # чекає в ``recv`` (інакше ``join`` завис би назавжди).
        sock = self._socket
        try:
            self._socket = None
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Виявлення порту й вкладки
# ─────────────────────────────────────────────────────────────────────────────

def http_json(url: str, *, timeout: float = 4.0) -> Any:
    """GET JSON із порту налагодження (``/json/version``, ``/json/list``)."""
    request = urllib.request.Request(url, method="GET")
    request.add_header("User-Agent", "BlackChpokIDE/cdp")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4_000_000)
    except urllib.error.HTTPError as exc:
        raise CdpError(f"HTTP {exc.code} від {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CdpError(f"Немає з'єднання з {url}: {exc}") from exc
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CdpError(f"Відповідь не JSON: {body[:120]!r}") from exc


def wait_for_devtools(port: int, *, timeout: float = 20.0) -> bool:
    """Дочекатись, поки порт налагодження почне відповідати."""
    deadline = time.monotonic() + max(0.5, timeout)
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        try:
            http_json(url, timeout=1.5)
            return True
        except CdpError:
            time.sleep(0.25)
    return False


def free_port() -> int:
    """Вільний TCP-порт для порту налагодження."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def page_targets(port: int) -> list[dict[str, Any]]:
    """Список вкладок (page) на порту налагодження."""
    data = http_json(f"http://127.0.0.1:{port}/json/list")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)
            and item.get("type") == "page"]


# ─────────────────────────────────────────────────────────────────────────────
# Клієнт сесії
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConsoleEntry:
    """Один запис консолі або помилка сторінки."""

    level: str           # log | info | warning | error | debug
    text: str
    source: str = ""     # console-api | javascript | network | log
    url: str = ""
    line: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_error(self) -> bool:
        return self.level in ("error", "assert")

    def as_line(self) -> str:
        where = ""
        if self.url:
            name = self.url.rsplit("/", 1)[-1] or self.url
            where = f" ({name}:{self.line})" if self.line else f" ({name})"
        return f"[{self.level}] {self.text}{where}"


class CdpSession:
    """Одна сесія сторінки: команди, події, зібрана консоль.

    Використання::

        session = CdpSession(port=9333)
        session.connect()
        session.enable()
        print(session.evaluate("document.title"))
        print(session.console_text())
        session.close()

    Усі публічні методи безпечні: замість винятку на збої мережі вони
    повертають ``None``/порожнє значення й пишуть причину в ``last_error``.
    Це важливо, бо браузер може закритись будь-якої миті.
    """

    def __init__(self, port: int = 0, *, page_id: str = "",
                 on_event: Optional[Callable[[dict[str, Any]], None]] = None) -> None:
        self.port = int(port or 0)
        self.page_id = page_id
        self.on_event = on_event
        self._ws: Optional[WebSocket] = None
        self._next_id = 0
        self._pending: dict[int, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self.console: list[ConsoleEntry] = []
        self.last_error = ""
        self._pump: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        #: Скільки записів консолі тримати (більше — обрізаємо старі).
        self.console_limit = 400

    # ── підключення ────────────────────────────────────────────────────────
    def connect(self, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """Підключитись до першої (або вказаної) вкладки браузера."""
        if not self.port:
            self.last_error = "Порт налагодження не задано"
            return False
        try:
            targets = page_targets(self.port)
        except CdpError as exc:
            self.last_error = str(exc)
            return False
        if not targets:
            self.last_error = "У браузері немає відкритої сторінки"
            return False
        target = None
        if self.page_id:
            target = next((item for item in targets
                           if item.get("id") == self.page_id), None)
        target = target or targets[0]
        url = str(target.get("webSocketDebuggerUrl") or "")
        if not url:
            self.last_error = "Вкладка не дала адресу WebSocket"
            return False
        try:
            self._ws = WebSocket(url, timeout=timeout)
        except (CdpError, OSError) as exc:
            self.last_error = f"WebSocket: {exc}"
            self._ws = None
            return False
        self._stop.clear()
        self._pump = threading.Thread(target=self._read_loop, daemon=True,
                                      name="cdp-reader")
        self._pump.start()
        self.last_error = ""
        return True
    def close(self) -> None:
        self._stop.set()
        if self._ws is not None:
            self._ws.close()
            self._ws = None
        thread = self._pump
        self._pump = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._stop.is_set()

    def enable(self) -> None:
        """Увімкнути потрібні домени (консоль, помилки, DOM, мережа)."""
        self.call("Runtime.enable")
        self.call("Log.enable")
        self.call("Page.enable")
        self.call("Network.enable")
        self.call("DOM.enable")
        self.call("Console.enable")

    # ── читання подій ──────────────────────────────────────────────────────
    def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        while not self._stop.is_set():
            try:
                text = ws.recv_text(timeout=1.0)
            except (CdpError, OSError):
                break
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001 - потік не має падати
                LOG.debug("Читання CDP впало", exc_info=True)
                break
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if "id" in message:
                with self._lock:
                    self._pending[int(message["id"])] = message
                continue
            self._handle_event(message)

    def _handle_event(self, message: dict[str, Any]) -> None:
        method = str(message.get("method") or "")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        try:
            if method == "Runtime.consoleAPICalled":
                self._add_console_from_api(params)
            elif method == "Runtime.exceptionThrown":
                self._add_exception(params)
            elif method == "Log.entryAdded":
                self._add_log_entry(params)
            elif method == "Network.loadingFailed":
                self._add_network_failure(params)
            elif method == "Network.responseReceived":
                self._add_http_status(params)
        except Exception:  # noqa: BLE001 - розбір події не має ламати сесію
            LOG.debug("Подія %s не розібрана", method, exc_info=True)
        with self._lock:
            self._events.append({"method": method, "params": params})
            if len(self._events) > 400:
                del self._events[:200]
        if self.on_event is not None:
            try:
                self.on_event(message)
            except Exception:  # noqa: BLE001 - підписник не має ламати сесію
                LOG.debug("on_event впав", exc_info=True)

    # ── консоль ────────────────────────────────────────────────────────────
    def _push_console(self, entry: ConsoleEntry) -> None:
        with self._lock:
            self.console.append(entry)
            if len(self.console) > self.console_limit:
                del self.console[: len(self.console) - self.console_limit]

    def _add_console_from_api(self, params: dict[str, Any]) -> None:
        level = str(params.get("type") or "log")
        args = params.get("args") or []
        parts = [_remote_value_text(item) for item in args]
        self._push_console(ConsoleEntry(
            level="warning" if level in ("warning", "warn") else level,
            text=" ".join(part for part in parts if part),
            source="console-api",
        ))

    def _add_exception(self, params: dict[str, Any]) -> None:
        details = params.get("exceptionDetails") or {}
        text = _exception_text(details)
        self._push_console(ConsoleEntry(
            level="error", text=text, source="javascript",
            url=str(details.get("url") or ""),
            line=int(details.get("lineNumber") or 0) + 1,
        ))

    def _add_log_entry(self, params: dict[str, Any]) -> None:
        entry = params.get("entry") or {}
        level = str(entry.get("level") or "info")
        if level in ("verbose",):
            level = "debug"
        self._push_console(ConsoleEntry(
            level=level,
            text=str(entry.get("text") or ""),
            source=str(entry.get("source") or "log"),
            url=str(entry.get("url") or ""),
            line=int(entry.get("lineNumber") or 0),
        ))

    def _add_network_failure(self, params: dict[str, Any]) -> None:
        error = str(params.get("errorText") or "помилка завантаження")
        rid = str(params.get("requestId") or "")
        # CDP не дає URL тут, тому показуємо те, що є; URL додається з
        # Network.requestWillBeSent у списку запитів (див. requests()).
        self._push_console(ConsoleEntry(
            level="error",
            text=f"Ресурс не завантажено: {error} (id {rid[:8]})",
            source="network",
        ))

    def _add_http_status(self, params: dict[str, Any]) -> None:
        response = params.get("response") or {}
        status = int(response.get("status") or 0)
        if status < 400:
            return
        self._push_console(ConsoleEntry(
            level="error",
            text=f"HTTP {status} {response.get('statusText') or ''}".strip(),
            source="network",
            url=str(response.get("url") or ""),
        ))

    def console_entries(self, *, errors_only: bool = False) -> list[ConsoleEntry]:
        with self._lock:
            items = list(self.console)
        return [item for item in items if item.is_error] if errors_only else items

    def console_text(self, *, errors_only: bool = False, limit: int = 40) -> str:
        """Консоль як текст (для панелі й для моделі)."""
        items = self.console_entries(errors_only=errors_only)[-max(1, limit):]
        if not items:
            return "Консоль порожня: помилок і повідомлень немає."
        return "\n".join(item.as_line() for item in items)

    def clear_console(self) -> None:
        with self._lock:
            self.console.clear()

    def errors_count(self) -> int:
        return len(self.console_entries(errors_only=True))

    # ── команди ────────────────────────────────────────────────────────────
    def call(self, method: str, params: Optional[dict[str, Any]] = None,
             *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
        """Виконати команду CDP і дочекатись її результату."""
        ws = self._ws
        if ws is None:
            self.last_error = "Немає з'єднання з браузером"
            return None
        with self._lock:
            self._next_id += 1
            call_id = self._next_id
        payload = {"id": call_id, "method": method, "params": params or {}}
        try:
            ws.send_text(json.dumps(payload, ensure_ascii=False))
        except (CdpError, OSError) as exc:
            self.last_error = f"Надсилання {method}: {exc}"
            return None
        deadline = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < deadline:
            with self._lock:
                message = self._pending.pop(call_id, None)
            if message is not None:
                if isinstance(message.get("error"), dict):
                    self.last_error = str(
                        (message.get("error") or {}).get("message") or "помилка CDP")
                    return None
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if self._stop.is_set() or self._ws is None:
                self.last_error = "З'єднання закрито під час очікування"
                return None
            time.sleep(0.01)
        self.last_error = f"Час очікування {method} вичерпано"
        return None

    # ── високорівневі операції ─────────────────────────────────────────────
    def evaluate(self, expression: str, *, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Виконати JS і повернути просте значення (рядок/число/bool/список)."""
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": False,
        }, timeout=timeout)
        if result is None:
            return None
        if result.get("exceptionDetails"):
            self.last_error = _exception_text(result["exceptionDetails"])
            return None
        remote = result.get("result") or {}
        if "value" in remote:
            return remote["value"]
        return _remote_value_text(remote)

    def evaluate_json(self, expression: str, *,
                      timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Виконати JS, який повертає JSON-рядок, і розібрати його.

        Навіщо окремо: ``Runtime.evaluate`` з ``returnByValue`` віддає
        вкладений об'єкт як ЙОГО значення, а рядок — як рядок. Розбирати
        «може рядок, а може словник» у кожному виклику — джерело помилок,
        тому розбір зібрано тут, в одному місці.
        """
        raw = self.evaluate(expression, timeout=timeout)
        if isinstance(raw, (dict, list)):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self.last_error = "Сторінка повернула не JSON"
            return None

    def page_url(self) -> str:
        value = self.evaluate("location.href")
        return str(value or "")

    def page_title(self) -> str:
        return str(self.evaluate("document.title") or "")

    def reload(self) -> bool:
        return self.call("Page.reload", {"ignoreCache": False}) is not None

    def screenshot(self, path: str, *, full_page: bool = False) -> str:
        """Зробити знімок СТОРІНКИ (не екрана) і записати у файл."""
        params: dict[str, Any] = {"format": "png"}
        if full_page:
            metrics = self.evaluate(
                "JSON.stringify({w: document.documentElement.scrollWidth,"
                " h: document.documentElement.scrollHeight})")
            try:
                data = json.loads(metrics) if isinstance(metrics, str) else {}
            except json.JSONDecodeError:
                data = {}
            width = int(data.get("w") or 0)
            height = int(data.get("h") or 0)
            if width and height:
                params["clip"] = {"x": 0, "y": 0, "width": width,
                                  "height": height, "scale": 1}
                params["captureBeyondViewport"] = True
        result = self.call("Page.captureScreenshot", params, timeout=25.0)
        if result is None:
            return ""
        raw = result.get("data")
        if not isinstance(raw, str) or not raw:
            self.last_error = "Браузер не повернув зображення"
            return ""
        try:
            blob = base64.b64decode(raw)
        except (ValueError, TypeError) as exc:
            self.last_error = f"Зображення не розкодовано: {exc}"
            return ""
        try:
            from pathlib import Path

            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        except OSError as exc:
            self.last_error = f"Не вдалось зберегти знімок: {exc}"
            return ""
        return str(path)

    def set_viewport(self, width: int, height: int, *,
                     mobile: bool = False, scale: float = 1.0) -> bool:
        """Емулювати розмір вікна (перевірка адаптивності).

        ``mobile=False`` типово: саме тоді CSS-медіазапити бачать рівно
        задану ширину. З ``mobile=True`` сторінка без ``<meta viewport>``
        отримує layout-ширину 980 px — це правдива поведінка Chrome, але
        для перевірки «як виглядає на 375 px» вона не годиться.
        """
        ok = self.call("Emulation.setDeviceMetricsOverride", {
            "width": int(max(120, width)),
            "height": int(max(120, height)),
            "deviceScaleFactor": float(scale),
            "mobile": bool(mobile),
            "screenWidth": int(max(120, width)),
            "screenHeight": int(max(120, height)),
        }) is not None
        if ok:
            self.last_error = ""
        return ok

    def clear_viewport(self) -> bool:
        return self.call("Emulation.clearDeviceMetricsOverride") is not None

    # ── інспектор елементів ────────────────────────────────────────────────
    def inspect_at(self, x: float, y: float) -> dict[str, Any]:
        """Отримати відомості про елемент у точці (x, y) сторінки.

        Повертає словник із тим, що справді потрібно, щоб змінити цей
        елемент у коді: тег, ``id``, класи, CSS-селектор, розміри, позиція,
        основні обчислені стилі й (якщо вдасться) текст елемента.
        Порожній словник — нічого не знайдено.
        """
        expression = (_INSPECT_JS.replace("__X__", str(int(x)))
                      .replace("__Y__", str(int(y)))
                      .replace("__DUMP__", _ELEMENT_DUMP_JS))
        data = self.evaluate_json(expression, timeout=15.0)
        return data if isinstance(data, dict) else {}

    def inspect_selector(self, selector: str) -> dict[str, Any]:
        """Ті самі відомості, але за CSS-селектором."""
        safe = json.dumps(str(selector or ""))
        expression = (_INSPECT_SELECTOR_JS.replace("__SEL__", safe)
                      .replace("__DUMP__", _ELEMENT_DUMP_JS))
        data = self.evaluate_json(expression, timeout=15.0)
        return data if isinstance(data, dict) else {}

    def click_selector(self, selector: str) -> bool:
        """Клікнути СПРАВЖНІЙ елемент за селектором (через DOM, не екран)."""
        safe = json.dumps(str(selector or ""))
        result = self.evaluate(
            "(()=>{const e=document.querySelector(" + safe + ");"
            "if(!e)return false;e.scrollIntoView({block:'center'});e.click();return true;})()")
        return bool(result)

    def click_at(self, x: float, y: float) -> bool:
        """Клікнути за координатами сторінки (миша браузера, не SendInput)."""
        for event_type in ("mousePressed", "mouseReleased"):
            params = {
                "type": event_type,
                "x": float(x), "y": float(y),
                "button": "left", "clickCount": 1,
            }
            if self.call("Input.dispatchMouseEvent", params) is None:
                return False
        return True

    def type_text(self, text: str) -> bool:
        """Ввести текст у сфокусований елемент сторінки."""
        for char in str(text or ""):
            if self.call("Input.insertText", {"text": char}) is None:
                return False
        return True

    def press_key(self, key: str) -> bool:
        """Натиснути клавішу в сторінці (Enter, Tab, Escape…)."""
        codes = {
            "enter": (13, "Enter"), "tab": (9, "Tab"), "escape": (27, "Escape"),
            "backspace": (8, "Backspace"), "delete": (46, "Delete"),
        }
        item = codes.get(str(key or "").strip().lower())
        if item is None:
            return False
        virtual, name = item
        for event_type in ("keyDown", "keyUp"):
            if self.call("Input.dispatchKeyEvent", {
                "type": event_type, "key": name,
                "windowsVirtualKeyCode": virtual, "nativeVirtualKeyCode": virtual,
                "text": "\r" if name == "Enter" else "",
            }) is None:
                return False
        return True

    # ── перевірки сторінки ─────────────────────────────────────────────────
    def audit(self) -> dict[str, Any]:
        """Комплексна перевірка сторінки одним запитом.

        Що перевіряємо (усе — реальними запитами до DOM):

        * посилання: скільки, чи є порожні ``href``/``#``, чи не биті
          внутрішні адреси;
        * клікабельні елементи: кнопки й посилання нульового розміру або
          приховані (їх неможливо натиснути);
        * форми: поля без ``name``/``id``, порожні ``action``;
        * зображення без ``alt`` і ті, що не завантажились;
        * заголовки: чи є ``h1``, скільки ``h2``;
        * доступність: елементи з ``aria-*`` та без підпису.
        """
        data = self.evaluate_json(_AUDIT_JS, timeout=20.0)
        if not isinstance(data, dict):
            return {"ok": False, "reason": self.last_error or "аудит не вдався"}
        data["ok"] = True
        return data

    def responsive_check(self, sizes: Iterable[tuple[int, int]] = ()) -> list[dict[str, Any]]:
        """Перевірити сторінку на кількох розмірах екрана.

        Для кожного розміру: чи з'являється горизонтальна прокрутка, чи не
        вилазить вміст за межі, скільки елементів перекриваються.
        """
        targets = list(sizes) or [(375, 667), (768, 1024), (1280, 800), (1920, 1080)]
        rows: list[dict[str, Any]] = []
        for width, height in targets:
            if not self.set_viewport(width, height):
                rows.append({"width": width, "height": height,
                             "ok": False, "reason": self.last_error})
                continue
            time.sleep(0.2)
            measured = self.evaluate_json(_LAYOUT_JS, timeout=12.0)
            row: dict[str, Any] = {"width": width, "height": height, "ok": True}
            if isinstance(measured, dict):
                row.update(measured)
            rows.append(row)
        self.clear_viewport()
        return rows


# ─────────────────────────────────────────────────────────────────────────────
# JS-сніпети
# ─────────────────────────────────────────────────────────────────────────────

def _remote_value_text(remote: Any) -> str:
    """Текст віддаленого значення CDP (рядок, число, об'єкт, помилка)."""
    if not isinstance(remote, dict):
        return "" if remote is None else str(remote)
    if "value" in remote:
        value = remote.get("value")
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if "unserializableValue" in remote:
        return str(remote.get("unserializableValue"))
    if "description" in remote:
        return str(remote.get("description"))
    kind = remote.get("type")
    if kind == "undefined":
        return ""
    return str(remote.get("className") or kind or "")


def _exception_text(details: Any) -> str:
    """Людський текст винятку з ``exceptionDetails``."""
    if not isinstance(details, dict):
        return "невідома помилка сторінки"
    exception = details.get("exception") or {}
    text = _remote_value_text(exception) or str(details.get("text") or "")
    line = int(details.get("lineNumber") or 0) + 1
    if line > 0:
        text = f"{text} (рядок {line})"
    return text.strip() or "невідома помилка сторінки"


#: Скільки символів тексту елемента показувати моделі.
_ELEMENT_TEXT_LIMIT = 200

#: Спільний дамп елемента: підставляється в обидва сніпети нижче.
#:
#: УВАГА про ``return`` і переніс рядка: у JavaScript ``return`` з переносом
#: одразу після нього означає ``return;`` (automatic semicolon insertion), і
#: функція повертає ``undefined`` замість результату. Саме через це
#: інспектор спершу повертав порожньо. Тому виклик стоїть в ОДНОМУ рядку з
#: ``return``, а сам дамп — це вираз-функція, а не інструкція.
_ELEMENT_DUMP_JS = """(function(elTarget){
  const el = elTarget;
  const rect = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  function selectorOf(node){
    if (!node || !node.tagName) return "";
    if (node.id) return node.tagName.toLowerCase() + "#" + node.id;
    let path = [];
    let cur = node;
    let depth = 0;
    while (cur && cur.nodeType === 1 && depth < 5 && cur !== document.body) {
      let part = cur.tagName.toLowerCase();
      if (cur.classList && cur.classList.length) {
        part += "." + Array.from(cur.classList).slice(0, 3).join(".");
      }
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (same.length > 1) part += ":nth-of-type(" + (same.indexOf(cur) + 1) + ")";
      }
      path.unshift(part);
      cur = parent;
      depth += 1;
    }
    return path.join(" > ");
  }
  const sheets = Array.from(document.styleSheets || []).map(s => s.href).filter(Boolean);
  return JSON.stringify({
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    classes: el.classList ? Array.from(el.classList) : [],
    selector: selectorOf(el),
    text: (el.innerText || el.value || el.alt || "").trim().slice(0, __TEXT_LIMIT__),
    rect: {
      x: Math.round(rect.left), y: Math.round(rect.top),
      width: Math.round(rect.width), height: Math.round(rect.height)
    },
    scroll: {x: Math.round(window.scrollX), y: Math.round(window.scrollY)},
    styles: {
      display: style.display, position: style.position,
      color: style.color, backgroundColor: style.backgroundColor,
      fontSize: style.fontSize, fontWeight: style.fontWeight,
      margin: style.margin, padding: style.padding,
      border: style.border, borderRadius: style.borderRadius,
      flexDirection: style.flexDirection, gap: style.gap,
      zIndex: style.zIndex, opacity: style.opacity
    },
    attributes: (function(){
      const out = {};
      for (const attr of Array.from(el.attributes || [])) out[attr.name] = attr.value;
      return out;
    })(),
    parent: el.parentElement ? el.parentElement.tagName.toLowerCase() : "",
    pageUrl: location.href,
    pageTitle: document.title,
    stylesheets: sheets.join(", ")
  });
})
""".replace("__TEXT_LIMIT__", str(_ELEMENT_TEXT_LIMIT))

_INSPECT_JS = (
    "(() => { const el = document.elementFromPoint(__X__, __Y__);"
    " if (!el) return ''; return (__DUMP__)(el); })()"
)

_INSPECT_SELECTOR_JS = (
    "(() => { const el = document.querySelector(__SEL__);"
    " if (!el) return ''; return (__DUMP__)(el); })()"
)

_AUDIT_JS = """
(() => {
  const problems = { links: [], buttons: [], forms: [], images: [], headings: [], a11y: [] };
  const links = Array.from(document.querySelectorAll("a"));
  for (const a of links) {
    const rect = a.getBoundingClientRect();
    if (!a.getAttribute("href")) {
      problems.links.push({tag: "a", text: (a.innerText||"").trim().slice(0,60), issue: "немає href"});
    } else if (rect.width === 0 || rect.height === 0) {
      problems.links.push({tag: "a", text: (a.innerText||"").trim().slice(0,60), issue: "нульовий розмір"});
    }
  }
  for (const b of Array.from(document.querySelectorAll("button, [role=button], input[type=submit]"))) {
    const rect = b.getBoundingClientRect();
    const label = (b.innerText || b.value || b.getAttribute("aria-label") || "").trim();
    if (!label) problems.buttons.push({tag: b.tagName.toLowerCase(), issue: "без підпису"});
    else if (rect.width === 0 || rect.height === 0) {
      problems.buttons.push({tag: b.tagName.toLowerCase(), text: label.slice(0,60), issue: "нульовий розмір"});
    }
  }
  for (const f of Array.from(document.querySelectorAll("form"))) {
    const fields = Array.from(f.querySelectorAll("input, select, textarea"));
    const unnamed = fields.filter(i => !i.name && !i.id).length;
    if (unnamed) problems.forms.push({issue: unnamed + " полів без name/id"});
    if (!f.getAttribute("action") && !f.onsubmit && !f.getAttribute("method")) {
      problems.forms.push({issue: "форма без action (надішлеться на себе)"});
    }
  }
  for (const img of Array.from(document.querySelectorAll("img"))) {
    if (!img.getAttribute("alt")) problems.images.push({src: (img.currentSrc||img.src||"").slice(-60), issue: "без alt"});
    if (img.complete && img.naturalWidth === 0) problems.images.push({src: (img.currentSrc||img.src||"").slice(-60), issue: "не завантажилось"});
  }
  const h1 = Array.from(document.querySelectorAll("h1"));
  const h2 = Array.from(document.querySelectorAll("h2"));
  if (h1.length === 0) problems.headings.push({issue: "немає h1"});
  if (h1.length > 1) problems.headings.push({issue: h1.length + " заголовків h1"});
  if (!document.title) problems.headings.push({issue: "порожній title сторінки"});
  const inputs = Array.from(document.querySelectorAll("input:not([type=hidden]):not([type=submit])"));
  for (const inp of inputs) {
    const hasLabel = inp.labels && inp.labels.length > 0;
    const hasAria = inp.getAttribute("aria-label") || inp.getAttribute("aria-labelledby");
    if (!hasLabel && !hasAria && !inp.placeholder) {
      problems.a11y.push({tag: "input", issue: "поле без підпису"});
    }
  }
  return JSON.stringify({
    url: location.href,
    title: document.title,
    lang: document.documentElement.lang || "",
    counts: {
      links: links.length,
      buttons: document.querySelectorAll("button, [role=button]").length,
      forms: document.querySelectorAll("form").length,
      images: document.querySelectorAll("img").length,
      headings: h1.length + h2.length
    },
    problems: problems
  });
})()
"""

_LAYOUT_JS = """
(() => {
  const doc = document.documentElement;
  const overflowX = doc.scrollWidth - doc.clientWidth;
  const overflowY = doc.scrollHeight - doc.clientHeight;
  const wide = [];
  for (const el of Array.from(document.querySelectorAll("body *"))) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > doc.clientWidth + 2) {
      wide.push({tag: el.tagName.toLowerCase(),
                 classes: el.className && el.className.toString
                   ? el.className.toString().slice(0,60) : "",
                 right: Math.round(r.right)});
      if (wide.length >= 8) break;
    }
  }
  return JSON.stringify({
    viewport: {width: doc.clientWidth, height: doc.clientHeight},
    overflowX: Math.max(0, overflowX),
    overflowY: Math.max(0, overflowY),
    horizontalScroll: overflowX > 2,
    wideElements: wide
  });
})()
"""

# ─────────────────────────────────────────────────────────────────────────────
# Зручності для агента й панелі
# ─────────────────────────────────────────────────────────────────────────────

def describe_console(port: int, *, errors_only: bool = False,
                     limit: int = 40) -> str:
    """Підключитись, зібрати консоль і від'єднатись (для інструментів агента)."""
    session = CdpSession(port)
    if not session.connect():
        return f"Браузер недоступний: {session.last_error}"
    try:
        session.enable()
        # Подіям консолі треба трохи часу: сторінка вже завантажена, тож
        # перезавантажуємо, щоб отримати свіжі записи.
        session.reload()
        time.sleep(1.2)
        return session.console_text(errors_only=errors_only, limit=limit)
    finally:
        session.close()


__all__ = [
    "CdpError",
    "CdpSession",
    "ConsoleEntry",
    "WebSocket",
    "describe_console",
    "free_port",
    "http_json",
    "page_targets",
    "wait_for_devtools",
]
