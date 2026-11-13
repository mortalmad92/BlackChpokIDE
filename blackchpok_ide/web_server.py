"""Запуск сайтів для тестування: визначення стеку й керування сервером.

IDE має сама зрозуміти, як запустити проєкт, щоб користувач не згадував
команди. Модуль підтримує типові стеки:

* **статика** — просто віддати теку (вбудований сервер, без залежностей);
* **Python** — Flask, FastAPI/uvicorn, Django, ``http.server``, ``main.py``;
* **Node.js** — ``npm run dev`` / ``npm start``, Vite, Next, Express;
* **PHP** — вбудований сервер ``php -S``;
* **Ruby** — Rails, Sinatra; **Go**, **Rust**, **.NET**.

Модуль не тягне tkinter і не запускає нічого при імпорті.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# ── Типи проєктів ────────────────────────────────────────────────────────────

STATIC = "static"
PYTHON = "python"
NODE = "node"
PHP = "php"
RUBY = "ruby"
GO = "go"
RUST = "rust"
DOTNET = "dotnet"
UNKNOWN = "unknown"

#: Позначки для інтерфейсу.
LABELS: dict[str, str] = {
    STATIC: "Статичний сайт",
    PYTHON: "Python",
    NODE: "Node.js",
    PHP: "PHP",
    RUBY: "Ruby",
    GO: "Go",
    RUST: "Rust",
    DOTNET: ".NET",
    UNKNOWN: "Невідомий",
}

ICONS: dict[str, str] = {
    STATIC: "🌐",
    PYTHON: "🐍",
    NODE: "🟩",
    PHP: "🐘",
    RUBY: "💎",
    GO: "🔵",
    RUST: "🦀",
    DOTNET: "🟣",
    UNKNOWN: "❓",
}


@dataclass
class Recipe:
    """Як запустити проєкт."""

    kind: str = STATIC
    command: list[str] = field(default_factory=list)
    cwd: str = ""
    port: int = 0
    entry: str = ""
    note: str = ""
    needs_reload: bool = True        # чи потрібна жива перезагрузка
    env: dict[str, str] = field(default_factory=dict)
    reason: str = ""                 # чому обрано саме це

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)

    @property
    def icon(self) -> str:
        return ICONS.get(self.kind, "❓")

    @property
    def command_text(self) -> str:
        return " ".join(self.command) if self.command else "(немає команди)"

    @property
    def ok(self) -> bool:
        return bool(self.command) or self.kind == STATIC


# ── Визначення стеку ────────────────────────────────────────────────────────

def _read(path: Path, limit: int = 8000) -> str:
    """Прочитати текст файлу, не кидаючи винятків.

    ``path`` приймається і рядком. Раніше виклик із рядком падав з
    ``AttributeError: 'str' object has no attribute 'read_text'``, якого
    ``except OSError`` НЕ ловить — тобто виняток летів у викликача замість
    того, щоб просто віддати порожній рядок. ``AttributeError`` тут така
    сама «файл недоступний», як і ``OSError``.
    """
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, AttributeError, TypeError):
        return ""


#: Теки, які НІКОЛИ не переглядаємо під час пошуку HTML.
#:
#: ``rglob`` по них — головна причина повільності: у цьому репозиторії
#: ``userdata`` і ``.buildtmp`` містять тисячі файлів, і ``detect()``
#: блокував інтерфейс на 0.7 с. Тепер пошук обмежений і за теками, і за
#: кількістю переглянутих записів.
_SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", ".venv", "venv", "__pycache__", ".git", ".hg", ".svn",
    "userdata", ".buildtmp", "build", "dist", ".quarantine", ".mcp_rag",
    "site-packages", ".mypy_cache", ".pytest_cache",
})

#: Скільки записів максимум переглядає пошук HTML.
_HTML_SCAN_LIMIT = 4000

#: Глибина, до якої заглиблюємось у підтеки.
_HTML_DEPTH = 3


def _find_html(root: Path, *, limit: int = 1) -> list[Path]:
    """Знайти HTML-файли в теці, НЕ обходячи весь диск.

    Обмеження за теками, глибиною й кількістю переглянутих записів
    роблять пошук передбачуваним: ``detect()`` викликається під час
    побудови панелі, тож він не має права «зависати».
    """
    found: list[Path] = []
    seen = 0
    # ``root`` приймається і рядком: ``iterdir`` у рядка немає, і виклик
    # падав з ``AttributeError`` (не ``OSError``, тож і ``except`` нижче
    # його не ловив).
    stack: list[tuple[Path, int]] = [(Path(root), 0)]
    while stack and len(found) < limit and seen < _HTML_SCAN_LIMIT:
        folder, depth = stack.pop(0)
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen >= _HTML_SCAN_LIMIT:
                break
            try:
                if entry.is_dir():
                    if (depth < _HTML_DEPTH
                            and entry.name.lower() not in _SKIP_DIRS
                            and not entry.name.startswith(".")):
                        stack.append((entry, depth + 1))
                    continue
            except OSError:
                continue
            if entry.suffix.lower() in (".html", ".htm"):
                found.append(entry)
                if len(found) >= limit:
                    break
    return found
#:
#: Головний випадок — MCP-сервер: у ньому є ``mcp.run()``, а в тексті
#: трапляються слова «Flask»/«FastAPI» (у підказках і рядках). Просте
#: згадування робило з нього «FastAPI-застосунок», і прев'ю падало з
#: ``FATAL: MCP_WORKSPACE не встановлено`` замість того, щоб сказати
#: «у цьому проєкті немає сайту».
_NOT_WEB_MARKERS: tuple[str, ...] = (
    "mcp.run(",
    "from mcp.",
    "import mcp",
    "MCPServer(",
    "tkinter",
    "PyInstaller",
    "argparse.ArgumentParser",
)

#: Справжні ознаки вебзастосунку — як ІМПОРТИ, а не як згадки.
#:
#: ``^from flask import`` / ``^import fastapi`` на початку рядка: так
#: виглядає реальний імпорт. Рядок «Se è un server web (Flask/FastAPI)»
#: у тексті під це не підходить і більше не вводить в оману.
_WEB_IMPORT_RE = re.compile(
    r"(?m)^\s*(?:from\s+(flask|fastapi|uvicorn|django|starlette|aiohttp\.web"
    r"|bottle|tornado\.web|pyramid|quart|sanic)\b"
    r"|import\s+(flask|fastapi|uvicorn|django|starlette|bottle|quart|sanic)\b)",
)

#: Ознаки, що скрипт сам піднімає сервер (``app.run()``, ``uvicorn.run``).
_SELF_SERVE_RE = re.compile(
    r"\.run\s*\([^)]*(?:host|port)\s*="
    r"|uvicorn\.run\s*\("
    r"|http\.server|HTTPServer\s*\(|socketserver"
    r"|serve_forever\s*\(",
)


def looks_like_web_app(code: str) -> tuple[bool, str]:
    """Визначити, чи файл справді піднімає вебсервер.

    Повертає ``(так/ні, причина)``. Причина потрібна для чесного
    пояснення: «MCP-сервер, а не сайт» краще за мовчазний запуск, який
    падає з незрозумілою помилкою.
    """
    body = code or ""
    low = body.lower()

    match = _WEB_IMPORT_RE.search(body)
    if match:
        return True, f"імпорт {(match.group(1) or match.group(2) or '').strip()}"

    for marker in _NOT_WEB_MARKERS:
        if marker.lower() in low:
            return False, (
                "це не сайт, а службовий скрипт "
                f"(«{marker}»): запускати його як вебзастосунок не можна")

    if _SELF_SERVE_RE.search(body):
        return True, "скрипт піднімає сервер сам"

    return False, "немає ознак вебзастосунку"


def _exists(root: Path, *names: str) -> Optional[Path]:
    """Перший наявний файл із переліку в теці.

    ``root`` приймається і рядком: ``settings.workspace`` — це рядок, і
    виклик із ним падав з ``TypeError: unsupported operand type(s) for /:
    'str' and 'str'`` замість того, щоб просто відповісти. ``detect``
    нормалізує теку сам, але ця функція публічна й викликається окремо.
    """
    root = Path(root)
    for name in names:
        target = root / name
        if target.exists():
            return target
    return None


def find_entry(root: Path, names: Iterable[str]) -> Optional[Path]:
    """Перший наявний файл із переліку (з підпапок теж).

    ``root`` може бути рядком — див. :func:`_exists`.
    """
    root = Path(root)
    for name in names:
        direct = root / name
        if direct.is_file():
            return direct
    for name in names:
        for found in root.glob(f"*/{name}"):
            if found.is_file() and not any(part in {".venv", "node_modules", "__pycache__"}
                                           for part in found.parts):
                return found
    return None


def detect(root: Path, *, preferred_port: int = 8000) -> Recipe:
    """Визначити, як запустити проєкт у цій теці."""
    root = Path(root)
    if not root.is_dir():
        return Recipe(kind=UNKNOWN, reason=f"Тека не існує: {root}")

    # ── Node.js
    package = root / "package.json"
    if package.is_file():
        package_text = _read(package, 20000)
        scripts = re.findall(r'"([\w:\-]+)"\s*:\s*"([^"]+)"', package_text)
        names = {name for name, _value in scripts}
        if "dev" in names:
            cmd = ["npm", "run", "dev"]
            if "vite" in package_text.lower():
                return Recipe(NODE, cmd, str(root), preferred_port, reason="Vite (npm run dev)")
            if "next" in package_text.lower():
                return Recipe(NODE, cmd, str(root), 3000, reason="Next.js (npm run dev)")
            return Recipe(NODE, cmd, str(root), preferred_port, reason="npm run dev")
        if "start" in names:
            return Recipe(NODE, ["npm", "start"], str(root), preferred_port,
                          reason="npm start")
        if "serve" in names:
            return Recipe(NODE, ["npm", "run", "serve"], str(root), preferred_port,
                          reason="npm run serve")

    # ── Python: Flask / FastAPI / Django
    #
    # Перевіряємо СПРАВЖНІ ознаки (імпорти й запуск сервера), а не згадки
    # слів у тексті: інакше MCP-сервер із рядком «Flask/FastAPI» у підказці
    # вважався вебзастосунком і прев'ю падало.
    for candidate in (root / "app.py", root / "main.py", root / "server.py",
                      root / "run.py", root / "wsgi.py", root / "asgi.py"):
        if not candidate.is_file():
            continue
        code = _read(candidate)
        is_web, why = looks_like_web_app(code)
        if not is_web:
            continue
        low = code.lower()
        if "fastapi" in low or "uvicorn" in low:
            return Recipe(PYTHON, [sys.executable, "-m", "uvicorn",
                                   f"{candidate.stem}:app",
                                   "--reload", "--port", str(preferred_port)],
                          str(root), preferred_port, candidate.name,
                          reason=f"FastAPI + uvicorn ({why})")
        if "flask" in low:
            return Recipe(PYTHON, [sys.executable, candidate.name], str(root),
                          preferred_port, candidate.name,
                          reason=f"Flask ({why})")
        if "django" in low or candidate.name == "manage.py":
            return Recipe(PYTHON, [sys.executable, "manage.py", "runserver",
                                   str(preferred_port)], str(root), preferred_port,
                          "manage.py", reason="Django runserver")
        return Recipe(PYTHON, [sys.executable, candidate.name], str(root),
                      preferred_port, candidate.name, reason=f"Python-сервер ({why})")

    manage = find_entry(root, ["manage.py"])
    if manage is not None:
        return Recipe(PYTHON, [sys.executable, "manage.py", "runserver",
                               str(preferred_port)], str(manage.parent), preferred_port,
                      "manage.py", reason="Django")

    # ── PHP
    index_php = find_entry(root, ["index.php"])
    if index_php is not None and shutil.which("php"):
        return Recipe(PHP, ["php", "-S", f"127.0.0.1:{preferred_port}", "-t", "."],
                      str(index_php.parent), preferred_port, "index.php",
                      reason="PHP вбудований сервер")

    # ── Ruby
    if _exists(root, "Gemfile") and shutil.which("ruby"):
        gemfile = _read(root / "Gemfile")
        if "rails" in gemfile.lower():
            return Recipe(RUBY, ["bundle", "exec", "rails", "server", "-p",
                                 str(preferred_port)], str(root), preferred_port,
                          reason="Rails")
        return Recipe(RUBY, ["ruby", "app.rb"], str(root), preferred_port, reason="Ruby")

    # ── Go / Rust / .NET
    if _exists(root, "go.mod") and shutil.which("go"):
        return Recipe(GO, ["go", "run", "."], str(root), preferred_port, reason="go run .")
    if _exists(root, "Cargo.toml") and shutil.which("cargo"):
        return Recipe(RUST, ["cargo", "run"], str(root), preferred_port, reason="cargo run")
    if list(root.glob("*.csproj")) and shutil.which("dotnet"):
        return Recipe(DOTNET, ["dotnet", "run"], str(root), preferred_port, reason="dotnet run")

    # ── Статика: index.html або будь-який .html
    index = find_entry(root, ["index.html", "index.htm"])
    if index is not None:
        return Recipe(STATIC, [], str(index.parent), preferred_port, index.name,
                      reason="Статичний HTML")

    html_files = _find_html(root, limit=1)
    if html_files:
        return Recipe(STATIC, [], str(html_files[0].parent), preferred_port,
                      html_files[0].name, reason="HTML-файли у проєкті")

    return Recipe(kind=UNKNOWN, reason="Не вдалось визначити, як запустити проєкт.")


# ── Порти ───────────────────────────────────────────────────────────────────

def free_port(preferred: int = 8000, *, attempts: int = 60) -> int:
    """Вільний TCP-порт, починаючи з ``preferred``."""
    for offset in range(max(1, attempts)):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, *, timeout: float = 30.0,
                  on_status: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """Чекати, поки порт почне відповідати."""
    deadline = time.monotonic() + timeout
    notified = 0.0
    while time.monotonic() < deadline:
        if port_busy(port):
            return True, f"Сервер на порту {port} відповідає."
        if on_status is not None and time.monotonic() - notified > 1.5:
            notified = time.monotonic()
            left = int(deadline - time.monotonic())
            on_status(f"Запускаю сервер… (лишилось ~{left} с)")
        time.sleep(0.25)
    return False, f"Сервер не відповів на порту {port} за {timeout:.0f} с."


# ── Сервер ──────────────────────────────────────────────────────────────────

class DevServer:
    """Запущений сервер проєкту (або вбудований статичний)."""

    def __init__(self, recipe: Recipe, *, on_output: Optional[Callable[[str], None]] = None) -> None:
        self.recipe = recipe
        self.port = recipe.port or free_port(8000)
        self.on_output = on_output
        self.process: Optional[subprocess.Popen[str]] = None
        self.output: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._static_thread: Optional[threading.Thread] = None
        self._static_server: Any = None
        self._log: list[str] = []

    # ── стан ───────────────────────────────────────────────────────────────
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def running(self) -> bool:
        if self.recipe.kind == STATIC:
            return self._static_server is not None
        return self.process is not None and self.process.poll() is None

    def tail(self, lines: int = 40) -> str:
        return "\n".join(self._log[-lines:])

    # ── запуск ─────────────────────────────────────────────────────────────
    def start(self) -> tuple[bool, str]:
        """Запустити сервер. Повертає (успіх, пояснення)."""
        if self.recipe.kind == STATIC:
            return self._start_static()
        if not self.recipe.command:
            return False, self.recipe.reason or "Немає команди для запуску."
        try:
            self.process = subprocess.Popen(
                self.recipe.command,
                cwd=self.recipe.cwd or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=self._env(),
                creationflags=_no_window(),
            )
        except FileNotFoundError:
            return False, f"Команду не знайдено: {self.recipe.command[0]}. Перевір, чи встановлено."
        except OSError as exc:
            return False, f"Не вдалось запустити: {exc}"

        self._thread = threading.Thread(target=self._read_output, args=(self.process,),
                                        daemon=True)
        self._thread.start()
        return True, f"Запущено: {self.recipe.command_text}"

    def _start_static(self) -> tuple[bool, str]:
        """Вбудований сервер статики (без зовнішніх залежностей)."""
        import functools
        import http.server
        import socketserver

        folder = Path(self.recipe.cwd or ".")
        if not folder.is_dir():
            return False, f"Тека не існує: {folder}"

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:  # тихіше
                self.server.log_messages.append(fmt % args)  # type: ignore[attr-defined]

            def guess_type(self, path):
                """Тип вмісту з кодуванням UTF-8 для тексту.

                Без явного ``charset`` браузер вгадує кодування сторінки й
                показує український текст кракозябрами: `SimpleHTTPRequest`
                віддає ``text/html`` без кодування, а типове для Windows
                вгадування — не UTF-8.
                """
                base = super().guess_type(path)
                if base.startswith("text/") or base in ("application/javascript",
                                                        "application/json",
                                                        "image/svg+xml"):
                    if "charset" not in base:
                        base = f"{base}; charset=utf-8"
                return base

            def end_headers(self) -> None:
                # Забороняємо кеш, щоб зміни було видно одразу.
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                super().end_headers()

        handler = functools.partial(Handler, directory=str(folder))

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            log_messages: list[str] = []

        try:
            server = Server(("127.0.0.1", self.port), handler)
        except OSError as exc:
            return False, f"Порт {self.port} зайнятий: {exc}"

        self._static_server = server
        self._static_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._static_thread.start()
        self._remember(f"Статичний сервер: {folder} на {self.url}")
        return True, f"Статичний сервер на {self.url}"

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("BROWSER", "none")     # не відкривати зовнішній браузер
        env.update({str(k): str(v) for k, v in (self.recipe.env or {}).items()})
        return env

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                text = line.rstrip("\n")
                self._remember(text)
                self.output.put(text)
                if self.on_output is not None:
                    try:
                        self.on_output(text)
                    except Exception:  # noqa: BLE001
                        pass
        except (OSError, ValueError):
            pass

    def _remember(self, line: str) -> None:
        self._log.append(line)
        if len(self._log) > 400:
            del self._log[:-300]

    # ── зупинка ────────────────────────────────────────────────────────────
    def stop(self, timeout: float = 6.0) -> None:
        """Зупинити сервер (ідемпотентно)."""
        if self._static_server is not None:
            try:
                self._static_server.shutdown()
                self._static_server.server_close()
            except Exception:  # noqa: BLE001
                pass
            self._static_server = None
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
        self.process = None

    def restart(self) -> tuple[bool, str]:
        self.stop()
        self.port = free_port(self.recipe.port or 8000)
        return self.start()


def _no_window() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


# ── Підказки для запуску ────────────────────────────────────────────────────

def missing_tools(recipe: Recipe) -> list[str]:
    """Яких програм бракує для запуску."""
    missing: list[str] = []
    if recipe.kind == STATIC:
        return missing
    if recipe.command:
        exe = recipe.command[0]
        if exe in {sys.executable, "python", "python3"}:
            return missing
        if shutil.which(exe) is None and not Path(exe).exists():
            missing.append(exe)
    return missing


def describe(recipe: Recipe) -> str:
    """Опис рецепта для інтерфейсу."""
    parts = [f"{recipe.icon} {recipe.label}"]
    if recipe.command:
        parts.append(recipe.command_text)
    if recipe.reason:
        parts.append(f"({recipe.reason})")
    return " · ".join(parts)


__all__ = [
    "DOTNET",
    "DevServer",
    "GO",
    "ICONS",
    "LABELS",
    "NODE",
    "PHP",
    "PYTHON",
    "RUBY",
    "RUST",
    "Recipe",
    "STATIC",
    "UNKNOWN",
    "describe",
    "detect",
    "find_entry",
    "free_port",
    "missing_tools",
    "port_busy",
    "wait_for_port",
]
