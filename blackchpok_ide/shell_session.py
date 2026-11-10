"""Постійна сесія командної оболонки — двигун вбудованого терміналу BlackChpok IDE.

Модуль не імпортує tkinter і безпечний для імпорту: усе, що потрібно графіці,
передається через колбеки ``on_output`` / ``on_exit``.

Ідея
----
Один довгоживучий процес оболонки (``cmd.exe`` на Windows, ``$SHELL`` на POSIX)
читає команди зі stdin. Щоб знати, коли команда завершилась і з яким кодом,
після неї дописуються два службові рядки::

    <команда користувача>
    echo __BCHPOK_CWD_<token>__%CD%              # де ми тепер
    echo __BCHPOK_DONE_<token>__%ERRORLEVEL%     # код виходу

Потік-читач неперервно читає stdout, вирізає ANSI, розпізнає маркери і складає
рядки у стан поточної команди. Ніякого ``wait()`` на весь процес — сесія
переживає скільки завгодно команд, а таймаут рахується лише на одну команду.

Особливості Windows, перевірені на реальному cmd.exe
----------------------------------------------------
* ``chcp 65001`` у piped-режимі псує **вхід**: кожен байт перетворюється на
  U+FFFD, тому будь-яка не-ASCII команда надсилається через тимчасовий
  UTF-8 ``.cmd``-файл (``call "file.cmd"``) — це єдиний надійний шлях.
  ASCII-команди йдуть прямо в stdin і зберігають звичайну семантику.
* Байт ``\x03`` (Ctrl+C) у pipe — інертний: cmd.exe реагує на нього лише з
  консоллю. Тому ``interrupt()`` надсилає ``CTRL_BREAK_EVENT`` і додатково
  завершує нащадків оболонки (окрім ``conhost.exe``) — саме це повертає
  керування за ~0.05 с, залишаючи саму оболонку живою.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Optional, Tuple

import logging

LOG = logging.getLogger("blackchpok.shell")

IS_WINDOWS = os.name == "nt"

#: Скільки рядків виводу тримаємо в пам'яті (більше не потрібно для Tk Text).
TRANSCRIPT_LIMIT = 4000

#: Префікси службових маркерів. У вивід для UI вони не потрапляють ніколи.
DONE_PREFIX = "__BCHPOK_DONE_"
CWD_PREFIX = "__BCHPOK_CWD_"

_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200

#: ANSI: CSI, OSC, кодування наборів символів і «обірвані» ESC-фрагменти,
#: які cmd.exe інколи лишає після себе.
ANSI_RE = re.compile(
    r"""
      \x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?      # OSC ... BEL / ST
    | \x1b\[[0-?]*[ -/]*[@-~]?                 # CSI (може бути без хвоста)
    | \x1b[()#][0-9A-Za-z]?                    # designation: (B, )0, #8
    | \x1b[NSOXcn]                             # ESC N/O/S/X/c/n
    | \x1b[@-Z\\-_]                            # решта двобуквених послідовностей
    | \x1b                                     # самотній ESC
    """,
    re.VERBOSE,
)

_DONE_RE = re.compile(re.escape(DONE_PREFIX) + r"([0-9a-z]{4,})__(?:(-?\d+))?")
_CWD_RE = re.compile(re.escape(CWD_PREFIX) + r"([0-9a-z]{4,})__(.*)$")

#: Запрошення cmd.exe: ``C:\шлях>`` або ``\\сервер\тека>``. ``(.*)`` — вивід
#: команди на тому самому рядку (cmd друкує його одразу після запрошення).
_PROMPT_RE = re.compile(r"^(?:[A-Za-z]:\\[^<>]*|[\\/]{2}[^<>]*)>(.*)$")

#: Запрошення PowerShell: ``PS C:\шлях>``.
_PS_PROMPT_RE = re.compile(r"^PS [A-Za-z]:[^<>]*>(.*)$")

_TIMEOUT_NOTE = "\n[команда не завершилась за {seconds:g} с — натисни ■, щоб перервати]"
_BUSY_NOTE = "попередня команда ще виконується"

#: Скидає ERRORLEVEL у 0 перед кожною командою: ``echo`` цього не робить, тому
#: без цього код попередньої невдачі «залипав» на наступних командах.
_ERRORLEVEL_RESET = "ver >nul"

#: Діалект оболонки: ``cmd``, ``powershell`` або ``posix``.
_KIND_CMD = "cmd"
_KIND_POWERSHELL = "powershell"
_KIND_POSIX = "posix"

#: PowerShell скидає ``$LASTEXITCODE`` перед командою, інакше код попередньої
#: невдачі «залипав» би; ``$?`` у PS 5.1 лишається істинним для native-процесів.
_POWERSHELL_RESET = "Remove-Variable -Name LASTEXITCODE -ErrorAction SilentlyContinue"


def strip_ansi(text: str) -> str:
    """Прибрати керуючі ANSI-послідовності, щоб текст був чистий для Tk Text."""
    if not text:
        return ""
    return ANSI_RE.sub("", text)


def _strip_prompt(text: str) -> str:
    """Зрізати запрошення оболонки з початку рядка маркера."""
    for pattern in (_PROMPT_RE, _PS_PROMPT_RE):
        match = pattern.match(text)
        if match is not None:
            return match.group(1)
    return text


def available_shell() -> str:
    """Повернути шлях до оболонки, яку буде використано за замовчуванням."""
    if IS_WINDOWS:
        comspec = os.environ.get("COMSPEC", "")
        if comspec and Path(comspec).exists():
            return comspec
        found = shutil.which("cmd.exe")
        return found or "cmd.exe"
    shell = os.environ.get("SHELL", "")
    if shell and Path(shell).exists():
        return shell
    return shutil.which("sh") or "/bin/sh"


def _popen_flags() -> int:
    """Прапорці постійної оболонки: без вікна, але у власній групі (Ctrl+Break)."""
    if not IS_WINDOWS:
        return 0
    return _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP


def _run_flags() -> int:
    """Прапорці одноразового запуску (``run_once``): тільки без вікна."""
    return _CREATE_NO_WINDOW if IS_WINDOWS else 0


class _Pending:
    """Стан однієї команди, яку зараз виконує оболонка."""

    __slots__ = ("token", "event", "code", "lines", "finished", "discard", "interrupted")

    def __init__(self, token: str, *, discard: bool = False) -> None:
        self.token = token
        self.event = threading.Event()
        self.code: Optional[int] = None
        self.lines: list[str] = []
        self.finished = False
        self.discard = discard
        self.interrupted = False


class ShellSession:
    """Одна постійна сесія оболонки з маркерним протоколом.

    ``run()`` можна кликати з будь-якого потоку: команди серіалізуються
    внутрішнім замком. Якщо попередня команда ще виконується, виклик **не
    чекає**, а одразу повертає ``(-2, "попередня команда ще виконується")`` —
    так UI ніколи не «залипає» на мертвому виклику.

    Колбеки ``on_output`` / ``on_exit`` викликаються з потоку-читача, тому UI
    має лише складати їх у ``queue.Queue`` і розбирати в головному потоці через
    ``after()``. Викликати ``run()`` / ``stop()`` зсередини колбека не можна —
    це взаємне блокування.
    """

    def __init__(
        self,
        cwd: Path,
        *,
        shell: str = "",
        on_output: Callable[[str], None] | None = None,
        on_exit: Callable[[int], None] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._cwd = Path(cwd)
        self._shell = shell
        self._on_output = on_output
        self._on_exit = on_exit
        self.timeout = float(timeout)

        self._process: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._pending: Optional[_Pending] = None
        self._lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()

        self._transcript: Deque[str] = deque(maxlen=TRANSCRIPT_LIMIT)
        self._history: list[str] = []
        self._echo_lines: set[str] = set()
        self._last_exit_code = 0
        self._unsynced = False
        self._temp_files: list[Path] = []
        self._pending_cwd: Optional[Path] = None
        self._skip_blank = False
        self._kind = _KIND_POSIX if not IS_WINDOWS else _KIND_CMD

    # ── властивості ────────────────────────────────────────────────────────
    @property
    def cwd(self) -> Path:
        """Поточна тека сесії (оновлюється з оболонки після кожної команди)."""
        return Path(self._cwd)

    @property
    def running(self) -> bool:
        """Чи живий процес оболонки."""
        process = self._process
        return process is not None and process.poll() is None

    @property
    def pid(self) -> int:
        """PID процесу оболонки (0, якщо сесію не запущено)."""
        process = self._process
        return int(process.pid) if process is not None else 0

    @property
    def history(self) -> list[str]:
        """Виконані команди, найновіша — остання."""
        return list(self._history)

    @property
    def transcript(self) -> Deque[str]:
        """Останні ~4000 рядків виводу (обмежена черга, поводиться як список)."""
        return self._transcript

    @property
    def last_exit_code(self) -> int:
        """Код виходу останньої завершеної команди."""
        return self._last_exit_code

    # ── запуск / зупинка ───────────────────────────────────────────────────
    def start(self) -> bool:
        """Запустити постійну оболонку. Повторний виклик нічого не змінює."""
        with self._lifecycle_lock:
            if self.running:
                return True
            self._retire_process()
            if not self._cwd.is_dir():
                self._cwd = Path.cwd()
            argv = self._build_argv()
            env = self._build_env()
            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(self.cwd),
                    env=env,
                    creationflags=_popen_flags(),
                    start_new_session=not IS_WINDOWS,
                )
            except (OSError, ValueError) as exc:
                self._append(f"[не вдалось запустити оболонку {argv[0]}: {exc}]")
                self._process = None
                return False
            self._process = process
            self._unsynced = False
            self._reader = threading.Thread(
                target=self._read_loop,
                args=(process,),
                name="bchpok-shell-reader",
                daemon=True,
            )
            self._reader.start()
            return process.poll() is None

    def stop(self, grace: float = 3.0) -> None:
        """Зупинити сесію. Ідемпотентно, ніколи не кидає винятків."""
        try:
            grace = max(0.1, float(grace))
        except (TypeError, ValueError):
            grace = 3.0
        try:
            with self._lifecycle_lock:
                pending = self._pending
                self._pending = None
                if pending is not None and not pending.finished:
                    pending.code = -1
                    pending.finished = True
                    pending.interrupted = True
                    pending.event.set()
                process = self._process
                self._process = None
                if process is None:
                    self._cleanup_temp_files()
                    return
                self._shutdown_process(process, grace)
                reader = self._reader
                self._reader = None
                if reader is not None and reader is not threading.current_thread():
                    try:
                        reader.join(timeout=grace)
                    except RuntimeError:
                        pass
                self._cleanup_temp_files()
        except Exception:  # noqa: BLE001 — stop() не має права падати
            LOG.debug("Помилка під час зупинки оболонки", exc_info=True)

    # ── виконання команд ───────────────────────────────────────────────────
    def run(self, command: str, *, timeout: float | None = None) -> tuple[int, str]:
        """Виконати команду в постійній сесії та дочекатись її кінця.

        Повертає ``(код_виходу, вивід_без_маркерів)``. Спеціальні коди:
        ``-1`` — таймаут або мертва оболонка, ``-2`` — сесія зайнята
        попередньою командою (виклик не блокується).
        """
        if command is None:
            return (-1, "[порожня команда]")
        text = command if isinstance(command, str) else str(command)
        if not text.strip():
            return (0, "")
        limit = self.timeout if timeout is None else float(timeout)
        if not self._run_lock.acquire(blocking=False):
            return (-2, _BUSY_NOTE)
        try:
            if not self.running and not self.start():
                return (-1, "[оболонка не запущена]")
            if self._pending_cwd is not None:
                self._apply_pending_cwd()
            if self._unsynced and not self._resync(min(limit, 5.0)):
                return (-1, "[сесія терміналу не відповідає — натисни ■]")
            return self._execute(text, limit)
        finally:
            self._run_lock.release()

    def set_cwd(self, path: Path) -> None:
        """Змінити робочу теку для наступних команд (ніколи не кидає)."""
        try:
            target = Path(path)
        except (TypeError, ValueError):
            self._append("[некоректний шлях до теки]")
            return
        try:
            exists = target.is_dir()
        except OSError:
            exists = False
        if not exists:
            self._append(f"[теки не існує: {target}]")
            return
        if not self.running:
            self._cwd = target
            self._pending_cwd = None
            return
        if not self._run_lock.acquire(blocking=False):
            # Команда ще виконується — перехід відкладемо, але не загубимо.
            self._pending_cwd = target
            self._append("[сесія зайнята — теку буде змінено після поточної команди]")
            return
        try:
            self._apply_pending_cwd(target)
        finally:
            self._run_lock.release()

    def _apply_pending_cwd(self, target: Optional[Path] = None) -> None:
        """Виконати ``cd`` у живій оболонці (виклик лише під ``_run_lock``)."""
        wanted = target if target is not None else self._pending_cwd
        if wanted is None:
            return
        self._pending_cwd = None
        quote = f'"{wanted}"'
        if self._kind == _KIND_CMD:
            command = f"cd /d {quote}"
        elif self._kind == _KIND_POWERSHELL:
            command = f"Set-Location -LiteralPath {quote}"
        else:
            command = f"cd {quote}"
        code, _ = self._execute(command, 15.0, record=False)
        if code != 0:
            self._append(f"[не вдалось перейти в теку: {wanted}]")
            return
        self._cwd = wanted

    def interrupt(self) -> None:
        """Перервати поточну команду, не вбиваючи саму оболонку. Не кидає."""
        try:
            pending = self._pending
            if pending is None or pending.finished:
                return
            with self._lock:
                pending.interrupted = True
            self._send_ctrl_break()
            self._terminate_descendants()
            if pending.event.wait(2.0):
                return
            with self._lock:
                if not pending.finished:
                    pending.code = -1
                    pending.finished = True
                    pending.event.set()
                if self._pending is pending:
                    self._pending = None
            self._unsynced = True
        except Exception:  # noqa: BLE001 — interrupt() не має права падати
            LOG.debug("Помилка під час переривання", exc_info=True)

    # ── виконання: начинка ─────────────────────────────────────────────────
    def _execute(self, command: str, timeout: float, *, record: bool = True) -> Tuple[int, str]:
        token = uuid.uuid4().hex[:10]
        pending = _Pending(token)
        with self._lock:
            self._pending = pending

        sent, batch = self._send_command(command, token)
        if not sent:
            self._drop_pending(pending)
            self._remove_temp(batch)
            return (-1, "[оболонка не приймає команди]")

        finished = pending.event.wait(timeout)
        if batch is not None:
            self._remove_temp(batch)
        if record:
            self._history.append(command)

        if not finished:
            # Команда не вклалася в таймаут: спершу пробуємо звільнити оболонку
            # (завершуємо нащадків), і лише якщо маркер так і не прийшов —
            # позначаємо сесію «розсинхронізованою» для наступного run().
            self._terminate_descendants()
            finished = pending.event.wait(2.0)
            self._drop_pending(pending)
            if not finished:
                self._unsynced = True
            output = self._join(pending.lines)
            if output:
                output += "\n"
            output += _TIMEOUT_NOTE.format(seconds=timeout)
            self._last_exit_code = -1
            return (-1, output)

        self._drop_pending(pending)
        output = self._join(pending.lines)
        code = pending.code if pending.code is not None else -1
        if pending.interrupted:
            output = (output + "\n" if output else "") + "[команду перервано користувачем]"
        self._last_exit_code = code
        return (code, output)

    def _send_command(self, command: str, token: str) -> Tuple[bool, Optional[Path]]:
        """Надіслати команду разом із маркерами.

        Повертає ``(успіх, тимчасовий .cmd або None)``. Не-ASCII команда на
        Windows іде через файл: piped ``chcp 65001`` псує такий stdin.
        """
        batch: Optional[Path] = None
        body = command.rstrip("\r\n")
        prefix = ""
        # Перелік рядків-лун збираємо локально й публікуємо одним присвоєнням:
        # потік-читач ітерує цю множину, тож мутувати її «на льоту» небезпечно.
        echo_lines: set[str] = set()
        if self._kind == _KIND_CMD:
            # ``echo`` не скидає ERRORLEVEL, тому код виходу «залипав» би від
            # попередньої команди. ``ver >nul`` скидає його в 0, не заважаючи
            # справжнім кодам помилок (перевірено: bad-команда дає 9009).
            prefix = _ERRORLEVEL_RESET + "\n"
            echo_lines.add(_ERRORLEVEL_RESET)
        elif self._kind == _KIND_POWERSHELL:
            # PowerShell 5.1 лишає ``$?`` істинним після невдалого native-процесу,
            # тому скидаємо ``$LASTEXITCODE``, а в маркері читаємо його першим.
            prefix = _POWERSHELL_RESET + "\n"
            echo_lines.add(_POWERSHELL_RESET)
        marker_text = self._marker_text(token)
        echo_lines.update(marker_text.splitlines())
        self._echo_lines = echo_lines

        if self._kind == _KIND_CMD and not body.isascii():
            # piped ``chcp 65001`` псує не-ASCII stdin, тому така команда йде
            # через тимчасовий UTF-8 .cmd-файл.
            batch = self._write_batch(body)
            if batch is not None:
                call_line = f'call "{batch}"'
                echo_lines.add(call_line)
                if not self._write(prefix + call_line + "\n"):
                    self._remove_temp(batch)
                    return (False, None)
            elif not self._write(prefix + body + "\n"):
                return (False, None)
        elif not self._write(prefix + body + "\n"):
            return (False, None)

        if not self._write(marker_text):
            self._remove_temp(batch)
            return (False, None)
        return (True, batch)

    def _marker_text(self, token: str) -> str:
        """Текст службових рядків для конкретного діалекту оболонки."""
        if self._kind == _KIND_CMD:
            cwd_line = f"echo {CWD_PREFIX}{token}__%CD%"
            done_line = f"echo {DONE_PREFIX}{token}__%ERRORLEVEL%"
            return cwd_line + "\n" + done_line + "\n"
        if self._kind == _KIND_POWERSHELL:
            code_expr = (
                "if ($LASTEXITCODE -ne $null) { $LASTEXITCODE } "
                "elseif ($?) { 0 } else { 1 }"
            )
            return (
                f'Write-Output "{CWD_PREFIX}{token}__$($PWD.ProviderPath)"; '
                f'Write-Output "{DONE_PREFIX}{token}__$({code_expr})"\n'
            )
        saved = f"__bchpok_rc_{token}=$?"
        cwd_line = f"printf '%s\\n' \"{CWD_PREFIX}{token}__$PWD\""
        done_line = f"printf '%s%s\\n' \"{DONE_PREFIX}{token}__\" \"${saved}\""
        return f"{saved}; {cwd_line}; {done_line}\n"

    def _write_batch(self, command: str) -> Optional[Path]:
        """Записати команду в тимчасовий UTF-8 ``.cmd`` — обхід вади piped 65001."""
        path: Optional[Path] = None
        try:
            handle, name = tempfile.mkstemp(prefix="bchpok_cmd_", suffix=".cmd")
            os.close(handle)
            path = Path(name)
            if not str(path).isascii():
                path.unlink(missing_ok=True)
                return None
            body = "@echo off\r\n" + "\r\n".join(command.splitlines()) + "\r\n"
            with open(path, "w", encoding="utf-8", newline="\r\n") as stream:
                stream.write(body)
            self._temp_files.append(path)
            return path
        except (OSError, ValueError):
            if path is not None:
                self._remove_temp(path)
            return None

    def _resync(self, budget: float) -> bool:
        """Дочекатись, поки оболонка повернеться до запрошення, і викинути хвіст."""
        token = uuid.uuid4().hex[:10]
        pending = _Pending(token, discard=True)
        with self._lock:
            self._pending = pending
        if self._kind == _KIND_CMD:
            line = f"echo {DONE_PREFIX}{token}__%ERRORLEVEL%\n"
        elif self._kind == _KIND_POWERSHELL:
            line = f'Write-Output "{DONE_PREFIX}{token}__0"\n'
        else:
            line = f"printf '%s%s\\n' \"{DONE_PREFIX}{token}__\" \"$?\"\n"
        if not self._write(line):
            self._drop_pending(pending)
            return False
        finished = pending.event.wait(max(0.5, budget))
        if not finished:
            self._terminate_descendants()
            finished = pending.event.wait(2.0)
        self._drop_pending(pending)
        self._unsynced = not finished
        return finished

    def _drop_pending(self, pending: _Pending) -> None:
        with self._lock:
            if self._pending is pending:
                self._pending = None

    # ── потік-читач ────────────────────────────────────────────────────────
    def _read_loop(self, process: subprocess.Popen[str]) -> None:
        stream = process.stdout
        try:
            if stream is not None:
                while True:
                    raw = stream.readline()
                    if raw == "":
                        break
                    self._handle_line(raw)
        except (OSError, ValueError):
            pass
        except Exception:  # noqa: BLE001 — читач не має вбивати застосунок
            LOG.warning("Збій читача виводу оболонки", exc_info=True)
        finally:
            self._handle_eof(process)

    def _handle_line(self, raw: str) -> None:
        text = strip_ansi(raw).rstrip("\r\n")

        # 0. cmd.exe в piped-режимі «лунає» натиснутий Enter порожнім рядком.
        #    Це не вивід команди, тому такий рядок не показуємо.
        if not text and self._skip_blank:
            self._skip_blank = False
            return

        # 1. Запрошення + ехо власної команди: не показуємо і не аналізуємо,
        #    інакше ``echo __BCHPOK_DONE_..._%ERRORLEVEL%`` спрацював би як маркер.
        match = _PROMPT_RE.match(text) or _PS_PROMPT_RE.match(text)
        rest = match.group(1) if match is not None else ""
        if match is not None and not rest.strip():
            self._skip_blank = True
            return
        if rest:
            stripped = rest.strip()
            if stripped in self._echo_lines or any(
                stripped.endswith(line) for line in self._echo_lines
            ):
                self._skip_blank = True
                return

        # 2. Маркери. Шукаємо їх і всередині рядка із запрошенням: cmd друкує
        #    вивід ``echo`` одразу після запрошення, а запрошення містить ``>``,
        #    тож частину перед маркером треба повернути як звичайний вивід.
        body, hit = self._split_marker(text, DONE_PREFIX, _DONE_RE)
        pending = self._pending
        if (
            hit is not None
            and pending is not None
            and not pending.finished
            and hit.group(1) == pending.token
        ):
            code_text = hit.group(2)
            try:
                pending.code = int(code_text) if code_text is not None else -1
            except ValueError:
                pending.code = -1
            with self._lock:
                pending.finished = True
            pending.event.set()
            leftover = _strip_prompt(body) if match is not None else body
            if leftover.strip():
                self._emit_output(leftover)
            return

        body, hit = self._split_marker(text, CWD_PREFIX, _CWD_RE)
        pending = self._pending
        if hit is not None and pending is not None and hit.group(1) == pending.token:
            self._absorb_cwd(hit.group(2))
            leftover = _strip_prompt(body) if match is not None else body
            if leftover.strip():
                self._emit_output(leftover)
            return

        # 3. Звичайний рядок виводу. Сюди ж потрапляє текст, що лише *схожий* на
        #    маркер (його надрукував сам користувач) — він має бути видно.
        self._emit_output(rest if match is not None else text)

    def _emit_output(self, clean: Optional[str]) -> None:
        """Показати рядок виводу користувачу (і додати його до результату)."""
        if clean is None:
            return
        self._append(clean)
        pending = self._pending
        if pending is not None and not pending.finished and not pending.discard:
            pending.lines.append(clean)

    @staticmethod
    def _split_marker(
        text: str, prefix: str, pattern: "re.Pattern[str]"
    ) -> tuple[str, Optional["re.Match[str]"]]:
        """Відділити все, що стоїть перед маркером.

        Повертає ``(залишок_рядка, збіг)``; ``збіг`` — ``None``, якщо маркера
        в рядку немає.
        """
        index = text.find(prefix)
        if index < 0:
            return (text, None)
        found = pattern.search(text)
        if found is None:
            return (text, None)
        return (text[:index], found)

    def _handle_eof(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._process is not process:
                return
            code = process.poll()
            pending = self._pending
            if pending is not None and not pending.finished:
                pending.code = code if isinstance(code, int) else -1
                pending.finished = True
                pending.event.set()
            self._reader = None
        if code is None:
            try:
                code = process.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                code = -1
        exited = code if isinstance(code, int) else -1
        self._append(f"[оболонка завершилась, код {exited}]")
        callback = self._on_exit
        if callback is not None:
            try:
                callback(exited)
            except Exception:  # noqa: BLE001 — колбек UI не має ламати сесію
                LOG.debug("Колбек завершення оболонки впав", exc_info=True)

    def _absorb_cwd(self, value: str) -> None:
        candidate = Path(value.strip().strip('"'))
        try:
            if candidate.is_dir():
                self._cwd = candidate
        except OSError:
            pass

    # ── переривання ────────────────────────────────────────────────────────
    def _send_ctrl_break(self) -> None:
        """Надіслати Ctrl+Break у групу процесу (там, де це підтримується)."""
        process = self._process
        if process is None:
            return
        if IS_WINDOWS:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError, AttributeError):
                pass
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
        except (OSError, ValueError, AttributeError):
            pass

    def _terminate_descendants(self) -> None:
        """Завершити нащадків оболонки — саме це спиняє роботу за ~0.05 с."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        if IS_WINDOWS:
            for child in _windows_descendants(process.pid):
                _windows_terminate(child)
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ValueError, AttributeError):
            pass

    # ── дрібниці ───────────────────────────────────────────────────────────
    def _build_argv(self) -> list[str]:
        """Побудувати командний рядок оболонки та визначити її діалект."""
        shell = (self._shell or "").strip()
        if not shell:
            shell = available_shell()
        name = Path(shell).name.lower() if shell else ""
        if IS_WINDOWS and name.startswith("cmd"):
            self._kind = _KIND_CMD
            return [shell, "/d", "/q", "/k", "chcp 65001>nul & prompt "]
        if IS_WINDOWS and ("powershell" in name or name in ("pwsh", "pwsh.exe")):
            self._kind = _KIND_POWERSHELL
            return [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"]
        self._kind = _KIND_POSIX
        return [shell]

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        return env

    def _write(self, text: str) -> bool:
        process = self._process
        if process is None or process.stdin is None:
            return False
        try:
            process.stdin.write(text)
            process.stdin.flush()
            return True
        except (OSError, ValueError, TypeError):
            return False

    def _append(self, line: str) -> None:
        self._transcript.append(line)
        callback = self._on_output
        if callback is not None:
            try:
                callback(line)
            except Exception:  # noqa: BLE001 — UI не має ламати читач
                pass

    def _join(self, lines: list[str]) -> str:
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(line.rstrip() for line in lines)

    def _remove_temp(self, path: Optional[Path]) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            self._temp_files.remove(path)
        except ValueError:
            pass

    def _cleanup_temp_files(self) -> None:
        for path in list(self._temp_files):
            self._remove_temp(path)

    def _shutdown_process(self, process: subprocess.Popen[str], grace: float) -> None:
        """Коректно погасити процес: stdin → terminate → kill. Ніколи не кидає."""
        stdin = process.stdin
        if stdin is not None and not stdin.closed:
            try:
                stdin.close()
            except (OSError, ValueError):
                pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=grace)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                try:
                    process.kill()
                    process.wait(timeout=grace)
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    pass
        for stream in (process.stdout, process.stdin):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

    def _retire_process(self) -> None:
        """Тихо відпустити попередній процес перед перезапуском."""
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.kill()
        except (OSError, ValueError):
            pass
        for stream in (process.stdout, process.stdin):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass


# ── Windows: перелік і завершення нащадків ─────────────────────────────────
def _windows_descendants(pid: int) -> list[int]:
    """PID усіх нащадків процесу (без ``conhost.exe`` і без самого себе)."""
    try:
        import ctypes
        import ctypes.wintypes as wintypes
    except (ImportError, OSError):
        return []

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
        kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    except (OSError, AttributeError):
        return []

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []

    children: dict[int, list[tuple[int, str]]] = {}
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    try:
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("mbcs", "replace")
            children.setdefault(int(entry.th32ParentProcessID), []).append(
                (int(entry.th32ProcessID), name)
            )
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    except (OSError, ValueError):
        pass
    finally:
        kernel32.CloseHandle(snapshot)

    found: list[int] = []
    queue = [int(pid)]
    seen = {int(pid), os.getpid()}
    while queue:
        current = queue.pop()
        for child, name in children.get(current, ()):
            if child in seen or name.lower() == "conhost.exe":
                continue
            seen.add(child)
            found.append(child)
            queue.append(child)
    return found


def _windows_terminate(pid: int) -> None:
    """Завершити один процес за PID (тихо, якщо він уже помер)."""
    try:
        import ctypes
        import ctypes.wintypes as wintypes
    except (ImportError, OSError):
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if not handle:
            return
        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, ValueError, AttributeError):
        return


# ── одноразовий запуск (резервний шлях) ────────────────────────────────────
def run_once(command: str, cwd: Path, timeout: float = 120.0) -> tuple[int, str]:
    """Виконати команду в окремій свіжій оболонці та повернути ``(код, вивід)``.

    Використовується як резервний шлях, коли постійна сесія недоступна:
    жодного стану між викликами не зберігається.
    """
    if not command or not str(command).strip():
        return (0, "")
    try:
        completed = subprocess.run(
            str(command),
            shell=True,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_run_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        text = strip_ansi(partial)
        if text and not text.endswith("\n"):
            text += "\n"
        return (-1, text + _TIMEOUT_NOTE.format(seconds=timeout))
    except (OSError, ValueError) as exc:
        return (-1, f"[не вдалось запустити команду: {exc}]")
    return (int(completed.returncode), strip_ansi(completed.stdout or ""))
