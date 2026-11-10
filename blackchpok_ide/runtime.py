"""Локальний рушій: авто-встановлення llama.cpp і керування llama-server.

Ідея «працює з коробки»: користувач не має ставити LM Studio чи Ollama.
IDE сама завантажує зібраний llama.cpp з GitHub (потрібний бекенд — CUDA,
Vulkan або CPU), розпаковує у власну теку й піднімає OpenAI-сумісний
``llama-server`` на вільному порту. Далі агент працює як звичайно.

Модуль не залежить від tkinter: прогрес віддається callback'ом.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import app_data_dir, find_data_dir
from .hardware import HardwareProfile, LaunchPlan, ModelChoice, fit
from .model_hub import USER_AGENT, Download, HubError, Progress, latest_runtime_releases

LOG = logging.getLogger("blackchpok.runtime")

DEFAULT_PORT = 8080
SERVER_EXE = "llama-server.exe" if os.name == "nt" else "llama-server"

#: Скільки портів сканувати від ``DEFAULT_PORT``.
#:
#: Було 24. Кожен закритий порт коштує ``PORT_PROBE_TIMEOUT`` (0.05 с), тож
#: 24 порти = 1.2 с простою. Реальні «чужі» запуски (другий екземпляр IDE,
#: LM Studio, llama.cpp) стоять на найближчих портах — 8 вистачає з
#: запасом, а ``live_server_ports()`` додає ще й власні відомі порти.
PORT_SCAN_RANGE = 8

#: Таймаут перевірки порту З'ЄДНАННЯМ (секунди).
#:
#: На Windows закритий локальний порт не відповідає одразу: система робить
#: спробу й чекає до таймауту. Заміряно на цій машині — ``connect_ex`` до
#: закритого порту коштує рівно стільки, скільки задано:
#: ``0.35 → 369 мс``, ``0.15 → 152 мс``, ``0.05 → 61 мс``.
#:
#: ``discover_server_url`` перебирає 24 порти, тож 0.35 с давало **8.3 с**
#: простою в головному потоці під час старту (заміряно профілером — це
#: був найбільший внесок у 6.3-секундний запуск). 0.05 с дає 1.5 с і при
#: цьому з запасом перекриває реальний «порт слухає, але повільний» випадок:
#: сервер, який не відповів на connect за 50 мс, все одно перевіряється
#: далі через ``server_responds`` з власним таймаутом.
PORT_PROBE_TIMEOUT = 0.05

# Ключ керованого сервера. Він однаковий для сервера й клієнта: якщо вони
# розійдуться, агент отримає 401 ще до першого запиту.
MANAGED_API_KEY = "local"


class EngineError(RuntimeError):
    """Помилка рушія: не встановлено, не запускається, немає моделі."""


# ─────────────────────────────────────────────────────────────────────────────
# Теки
# ─────────────────────────────────────────────────────────────────────────────

def runtime_dir() -> Path:
    """Куди розпаковуємо llama.cpp.

    Якщо рушій уже лежить у портативній теці ``userdata/runtime``, беремо її:
    інакше після збірки .exe програма не побачила б жодного рушія.
    """
    target = find_data_dir("runtime", marker=SERVER_EXE)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return target


def server_path() -> Path:
    return runtime_dir() / SERVER_EXE


def engine_installed() -> bool:
    return server_path().exists()


def engine_version() -> str:
    """Версія встановленого рушія (рядок із файлу-маркера)."""
    marker = runtime_dir() / "version.txt"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Вибір збірки під залізо
# ─────────────────────────────────────────────────────────────────────────────

def _is_arm64() -> bool:
    machine = platform.machine().lower()
    return machine in {"arm64", "aarch64"}


def backend_preference(profile: HardwareProfile | None) -> list[str]:
    """Порядок бекендів: від найшвидшого до сумісного.

    На Windows збірки llama.cpp не буває «з усім одразу», тому обираємо
    конкретний архів. Vulkan — універсальний варіант для будь-якої GPU
    (NVIDIA/AMD/Intel), CUDA — швидший, але лише для NVIDIA.
    """
    if profile is None:
        return ["vulkan", "cpu"] if not _is_arm64() else ["cpu"]
    order: list[str] = []
    if profile.has_cuda:
        order.append("cuda")
    if profile.has_rocm:
        order.append("rocm")
    if profile.gpus:
        order.append("vulkan")
    order.append("cpu")
    # Прибираємо дублікати, зберігаючи порядок.
    return list(dict.fromkeys(order))


def _asset_patterns(backend: str) -> list[str]:
    arch = "arm64" if _is_arm64() else "x64"
    if backend == "cpu":
        return [f"bin-win-cpu-{arch}.zip"]
    if backend == "cuda":
        # CUDA 13 новіша, 12.4 — ширша сумісність зі старими драйверами.
        return [
            f"bin-win-cuda-13.4-{arch}.zip",
            f"bin-win-cuda-12.4-{arch}.zip",
        ]
    if backend == "rocm":
        return [f"bin-win-rocm-*-{arch}.zip"]
    if backend == "vulkan":
        return [f"bin-win-vulkan-{arch}.zip"]
    return []


def _cudart_pattern(version: str) -> str:
    """Архів із runtime-бібліотеками CUDA (cublas, cudart).

    Збірка llama.cpp для CUDA їх не містить — без них llama-server просто не
    стартує на чистій машині, тому ставимо обидва архіви.
    """
    arch = "arm64" if _is_arm64() else "x64"
    return f"cudart-llama-bin-win-cuda-{version}-{arch}.zip"


def _match_asset(release: dict[str, Any], regex: re.Pattern[str], *, prefix: str) -> dict[str, Any] | None:
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if not name.startswith(prefix):
            continue
        if regex.search(name):
            return {
                "tag": release.get("tag", ""),
                "name": name,
                "size": int(asset.get("size") or 0),
                "url": str(asset.get("url") or ""),
            }
    return None


def choose_assets(releases: list[dict[str, Any]], backend: str) -> list[dict[str, Any]]:
    """Усі архіви, потрібні для бекенду (для CUDA — разом із cudart)."""
    patterns = _asset_patterns(backend)
    if not patterns:
        return []
    for release in releases:
        for pattern in patterns:
            regex = re.compile(pattern.replace(".", r"\.").replace("*", ".*") + "$")
            main = _match_asset(release, regex, prefix="llama-")
            if not main:
                continue
            chosen = [dict(main, backend=backend)]
            if backend == "cuda":
                # Версія береться з імені збірки: cuda-13.4 / cuda-12.4.
                version = re.search(r"cuda-([\d.]+)-", main["name"])
                if version:
                    cudart_regex = re.compile(_cudart_pattern(version.group(1)).replace(".", r"\.") + "$")
                    cudart = _match_asset(release, cudart_regex, prefix="cudart-")
                    if cudart:
                        chosen.append(dict(cudart, backend=backend, kind="cudart"))
            return chosen
    return []


def choose_asset(releases: list[dict[str, Any]], backend: str) -> dict[str, Any] | None:
    """Перший (основний) архів бекенду."""
    assets = choose_assets(releases, backend)
    return assets[0] if assets else None


def plan_engine_install(profile: HardwareProfile | None, *, releases: list[dict[str, Any]] | None = None
                        ) -> tuple[list[dict[str, Any]], list[str]]:
    """Спланувати встановлення: (архіви, список спроб).

    Повертає перший набір архівів, який реально існує в релізах, і перелік
    бекендів, які пробували — це корисно показати в журналі.
    """
    data = releases if releases is not None else latest_runtime_releases(limit=3)
    tried: list[str] = []
    for backend in backend_preference(profile):
        tried.append(backend)
        assets = choose_assets(data, backend)
        if assets:
            return assets, tried
    return [], tried



# ─────────────────────────────────────────────────────────────────────────────
# Встановлення
# ─────────────────────────────────────────────────────────────────────────────

class EngineInstall:
    """Завантаження і розпакування llama.cpp у фоновому потоці."""

    def __init__(
        self,
        asset: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        profile: HardwareProfile | None = None,
        on_progress: Callable[[Progress], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        if isinstance(asset, dict):
            self.assets: list[dict[str, Any]] = [asset]
        else:
            self.assets = list(asset or [])
        self.profile = profile
        self.on_progress = on_progress
        self.on_status = on_status
        self.download: Download | None = None
        self.error = ""
        self.installed_path = ""
        self._thread: threading.Thread | None = None

    @property
    def asset(self) -> dict[str, Any] | None:
        """Основний архів (для сумісності й показу в інтерфейсі)."""
        return self.assets[0] if self.assets else None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        if self.download:
            self.download.cancel()

    def run_blocking(self) -> bool:
        self._run()
        return not self.error

    def _status(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати встановлення
                LOG.debug("on_status впав", exc_info=True)

    def _run(self) -> None:
        try:
            assets = self.assets
            if not assets:
                self._status("Шукаю збірку llama.cpp на GitHub…")
                assets, tried = plan_engine_install(self.profile)
                self.assets = assets
                if not assets:
                    self.error = (
                        "Не знайшов збірку llama.cpp для цієї системи "
                        f"(пробував: {', '.join(tried) or 'нічого'})."
                    )
                    return

            for asset in assets:
                if not self._fetch_and_extract(asset):
                    return

            exe = server_path()
            if not exe.exists():
                found = next(runtime_dir().rglob(SERVER_EXE), None)
                if found is None:
                    self.error = "У архіві немає llama-server — можливо, збірка неповна."
                    return
                # Розпакували вкладену теку — піднімаємо вміст нагору.
                _flatten(found.parent)
            main = assets[0]
            (runtime_dir() / "version.txt").write_text(str(main.get("tag") or ""), encoding="utf-8")
            (runtime_dir() / "backend.txt").write_text(str(main.get("backend") or ""), encoding="utf-8")
            self.installed_path = str(server_path())
            self._status("Рушій готовий.")
            LOG.info("llama.cpp встановлено: %s (%s)", self.installed_path, main.get("tag"))
        except (HubError, OSError, zipfile.BadZipFile) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            LOG.exception("Встановлення рушія впало")
        except Exception as exc:  # noqa: BLE001 - показуємо користувачу
            self.error = f"{type(exc).__name__}: {exc}"
            LOG.exception("Встановлення рушія впало")

    def _fetch_and_extract(self, asset: dict[str, Any]) -> bool:
        size_mb = int(asset.get("size") or 0) / 1048576
        self._status(f"Завантажую {asset['name']} ({size_mb:.0f} МБ)…")
        zip_path = runtime_dir() / str(asset["name"])
        self.download = Download(
            str(asset["url"]),
            zip_path,
            on_progress=self.on_progress,
            expected_size=int(asset.get("size") or 0),
        )
        self.download.run_blocking()
        if self.download.error:
            self.error = self.download.error
            return False
        self._status(f"Розпаковую {asset['name']}…")
        self._extract(zip_path)
        zip_path.unlink(missing_ok=True)
        return True

    def _extract(self, zip_path: Path) -> None:
        target = runtime_dir()
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                name = member.filename
                # Захист від path traversal у zip-архіві.
                if name.startswith("/") or ".." in Path(name).parts:
                    LOG.warning("Пропускаю підозрілий шлях у архіві: %s", name)
                    continue
                archive.extract(member, target)



def _flatten(folder: Path) -> None:
    """Перенести вміст вкладеної теки у runtime_dir()."""
    root = runtime_dir()
    if folder.resolve() == root.resolve():
        return
    for item in folder.iterdir():
        destination = root / item.name
        try:
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination, ignore_errors=True)
                else:
                    destination.unlink()
            shutil.move(str(item), str(destination))
        except OSError as exc:
            LOG.warning("Не вдалось перемістити %s: %s", item, exc)
    try:
        folder.rmdir()
    except OSError:
        pass


def install_engine(profile: HardwareProfile | None = None, *,
                   on_progress: Callable[[Progress], None] | None = None,
                   on_status: Callable[[str], None] | None = None) -> EngineInstall:
    """Запустити встановлення у фоні й повернути об'єкт із прогресом."""
    job = EngineInstall(profile=profile, on_progress=on_progress, on_status=on_status)
    job.start()
    return job


# ─────────────────────────────────────────────────────────────────────────────
# Запуск сервера
# ─────────────────────────────────────────────────────────────────────────────

def port_is_busy(port: int, host: str = "127.0.0.1") -> bool:
    """Чи зайнятий порт ІНШОЮ програмою.

    Навіщо окрема перевірка, якщо є :func:`free_port`. ``free_port`` шукає
    вільний порт через ``bind``, але з ``SO_REUSEADDR`` на Windows це може
    «пропустити» порт, який уже слухає інша програма: bind проходить, а
    llama-server потім падає з ``couldn't bind HTTP server socket``.

    Реальний випадок на цій машині: порт **8080 тримає Steam**
    (``steamwebhelper.exe``), а 8090 — TorrServer. Сервер мовчки не
    стартував.

    Перевіряємо З'ЄДНАННЯМ: якщо порт слухають — connect вдасться.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(PORT_PROBE_TIMEOUT)
        return sock.connect_ex((host, int(port))) == 0


def free_port(preferred: int = DEFAULT_PORT, *, attempts: int = 40) -> int:
    """Вільний TCP-порт, починаючи з ``preferred``."""
    for offset in range(attempts):
        port = preferred + offset
        # Спершу — чи не слухає там хтось інший (Steam, TorrServer, LM Studio).
        if port_is_busy(port):
            LOG.info("Порт %s зайнятий іншою програмою — беру наступний", port)
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    # Останній шанс: нехай система видасть будь-який вільний порт.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ─────────────────────────────────────────────────────────────────────────────
# Облік власних процесів: щоб не лишати «сиріт», які тримають VRAM
# ─────────────────────────────────────────────────────────────────────────────

#: Файл із PID керованих рушіїв. Потрібен, щоб після аварійного завершення
#: (вбитий процес, закрите вікно консолі, збій) наступний запуск міг знайти
#: й прибрати «сироту», яка інакше тримає гігабайти відеопам'яті.
PID_FILE = "managed-servers.json"

#: Скільки живих PID пам'ятаємо. Більше не потрібно: одночасно працює одна
#: модель (або кілька при перемиканні).
MAX_TRACKED = 8


def pid_file_path() -> Path:
    return runtime_dir() / PID_FILE


def _read_pid_file() -> list[dict[str, Any]]:
    """Прочитати збережений список процесів (стійко до сміття)."""
    path = pid_file_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _write_pid_file(entries: list[dict[str, Any]]) -> None:
    try:
        pid_file_path().write_text(
            json.dumps(entries[-MAX_TRACKED:], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        LOG.debug("Не вдалось записати %s", PID_FILE, exc_info=True)


def remember_process(pid: int, *, model: str = "", port: int = 0) -> None:
    """Записати PID рушія, яким керує IDE."""
    if not pid:
        return
    entries = [item for item in _read_pid_file() if int(item.get("pid") or 0) != int(pid)]
    entries.append({"pid": int(pid), "model": str(model), "port": int(port),
                    "started": time.time()})
    _write_pid_file(entries)


def forget_process(pid: int) -> None:
    """Прибрати PID зі списку (після штатної зупинки)."""
    if not pid:
        return
    entries = [item for item in _read_pid_file() if int(item.get("pid") or 0) != int(pid)]
    _write_pid_file(entries)


def _pid_alive(pid: int) -> bool:
    """Чи існує процес із таким PID (без сторонніх бібліотек)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # OpenProcess із PROCESS_QUERY_LIMITED_INFORMATION: 0x1000.
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # type: ignore[attr-defined]
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _pid_is_our_server(pid: int) -> bool:
    """Чи це САМЕ наш llama-server, а не чужий процес із тим самим PID.

    Критично для безпеки: PID після перезавантаження може дістатись іншій
    програмі. Вбивати її не можна. Тому перевіряємо ім'я виконуваного файлу.
    """
    if not _pid_alive(pid):
        return False
    if os.name != "nt":
        return True                     # на інших ОС обмежуємось наявністю PID
    try:
        # КОДУВАННЯ. ``tasklist`` на локалізованій Windows віддає вивід у
        # кодуванні OEM (cp866/cp1251), а не UTF-8. Спроба прочитати його як
        # UTF-8 кидала ``UnicodeDecodeError`` усередині потоку й прибирання
        # мовчки не працювало — процес лишався живим із 9 ГБ VRAM. Тому
        # передаємо ``errors="replace"`` і явне кодування.
        output = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=8,
            encoding="oem", errors="replace",
            creationflags=_no_window())
    except (OSError, subprocess.SubprocessError, LookupError, ValueError):
        # Немає ``oem`` кодування (не Windows-консоль) — пробуємо без нього.
        try:
            output = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=8,
                errors="replace", creationflags=_no_window())
        except (OSError, subprocess.SubprocessError):
            return False
    text = (output.stdout or "").lower()
    return SERVER_EXE.lower() in text


def stale_processes() -> list[dict[str, Any]]:
    """Записи про процеси, які ще живі (кандидати на прибирання)."""
    alive: list[dict[str, Any]] = []
    for item in _read_pid_file():
        pid = int(item.get("pid") or 0)
        if not pid:
            continue
        try:
            if _pid_is_our_server(pid):
                alive.append(item)
        except Exception:  # noqa: BLE001 - один запис не має ламати список
            LOG.debug("Перевірка pid=%s не вдалась", pid, exc_info=True)
    return alive


def live_server_ports() -> list[dict[str, Any]]:
    """Порти ЖИВИХ рушіїв, які ми самі запускали.

    Навіщо окрема функція. Порт, на який клієнт шле запити, має
    визначатись ФАКТИЧНО, а не з налаштувань: у реальному лозі користувача
    сервер піднявся на **8081** (бо 8080 тримав Steam), а ``llm.base_url``
    лишився ``8080`` — і кожен запит діставав HTTP 404. Тепер є кому
    спитати «на якому порту ти справді слухаєш».

    Повертає ``[{"pid", "port", "model", "started"}]`` лише для живих
    записів із заповненим портом.
    """
    found: list[dict[str, Any]] = []
    for item in stale_processes():
        port = int(item.get("port") or 0)
        if port <= 0:
            continue
        found.append({"pid": int(item.get("pid") or 0),
                      "port": port,
                      "model": str(item.get("model") or ""),
                      "started": float(item.get("started") or 0.0)})
    return found


def discover_server_url(preferred: str = "", *, api_key: str = "") -> str:
    """Знайти АКТИВНУ адресу локального сервера, слухаючи порти.

    Порядок пошуку:

    1. адреса з налаштувань, якщо вона СПРАВДІ відповідає;
    2. будь-який живий порт, який ми записали під час запуску;
    3. сканування діапазону навколо :data:`DEFAULT_PORT` на
       ``/health`` і ``/v1/models`` (інший запуск IDE, LM Studio тощо).

    Повертає ``"http://127.0.0.1:<порт>/v1"`` або ``""``, якщо нічого не
    слухає. Саме ця функція усуває клас помилок «порт змінився, а клієнт
    цього не знає».
    """
    candidates: list[int] = []

    def _from_url(text: str) -> int:
        match = re.search(r":(\d{2,5})(?:/|$)", str(text or ""))
        return int(match.group(1)) if match else 0

    preferred_port = _from_url(preferred)
    if preferred_port:
        candidates.append(preferred_port)
    for item in live_server_ports():
        port = int(item["port"])
        if port not in candidates:
            candidates.append(port)
    # Діапазон навколо типового порту — на випадок «чужий» запуск.
    # Вужче, ніж було (24 → 8): кожен закритий порт коштує PORT_PROBE_TIMEOUT,
    # а «чужий» сервер майже завжди стоїть на сусідніх портах, не на +23.
    for offset in range(0, PORT_SCAN_RANGE):
        port = DEFAULT_PORT + offset
        if port not in candidates:
            candidates.append(port)
    for port in candidates:
        if port <= 0 or not port_is_busy(port):
            continue
        url = f"http://127.0.0.1:{port}/v1"
        if server_responds(url, api_key=api_key):
            return url
    return ""


#: Кеш результату ``server_responds``: ``url -> (час, відповів?)``.
#:
#: Функція викликається перед кожним ходом агента І під час старту
#: (``_reconcile_server_url``). На непіднятому сервері ``level=2`` робить до
#: ТРЬОХ HTTP-спроб, і кожна на цій машині впирається в таймаут: заміряно
#: **4.6 с** у головному потоці на старті. Результат «сервер не відповів»
#: теж кешуємо — інакше та сама перевірка повторюється щосекунди.
_SERVER_RESPONDS_CACHE: dict[str, tuple[float, bool]] = {}
_SERVER_RESPONDS_TTL = 20.0
_SERVER_RESPONDS_LOCK = threading.Lock()


def server_responds(base_url: str, *, api_key: str = "",
                    timeout: float = 1.5, level: int = 2,
                    use_cache: bool = True) -> bool:
    """Чи відповідає OpenAI-сумісний сервер саме на цьому порту.

    Саме ця перевірка відрізняє «порт зайнятий» (Steam, TorrServer) від
    «порт зайнятий НАШИМ рушієм». Без неї клієнт стукав у Steam і діставав
    HTTP 404.

    ``level`` керує тим, СКІЛЬКИ запитів робити — це важливо для
    швидкості, бо ця функція викликається перед кожним ходом агента:

    * ``0`` — один TCP-connect: «порт слухає?» без HTTP (мілісекунди);
    * ``1`` — лише ``/health`` (llama-server віддає ``{"status":"ok"}``
      навіть із ``--api-key``);
    * ``2`` — повний набір: ``/health``, ``/v1/models`` з ключем, без ключа.

    Порядок у ``level=2`` навмисний: ``/health`` відкритий навіть із
    ``--api-key``, тому це найдешевший спосіб упізнати наш рушій. Коди
    401/403 вважаються успіхом — сервер Є, лише ключ інший; для виявлення
    порту це те, що потрібно (перевірено на живому рушії: ``/v1/models``
    без ключа дає 401, а ``/health`` — 200).
    """
    url = str(base_url or "").rstrip("/")
    if not url:
        return False
    cache_key = f"{url}|{api_key}|{level}"
    if use_cache:
        with _SERVER_RESPONDS_LOCK:
            hit = _SERVER_RESPONDS_CACHE.get(cache_key)
        if hit is not None and (time.time() - hit[0]) < _SERVER_RESPONDS_TTL:
            return hit[1]
    answer = _server_responds_uncached(url, api_key=api_key, timeout=timeout,
                                       level=level)
    if use_cache:
        with _SERVER_RESPONDS_LOCK:
            _SERVER_RESPONDS_CACHE[cache_key] = (time.time(), answer)
    return answer


def forget_server_responds(base_url: str = "") -> None:
    """Скинути кеш ``server_responds`` (після запуску/зупинки сервера)."""
    with _SERVER_RESPONDS_LOCK:
        if not base_url:
            _SERVER_RESPONDS_CACHE.clear()
            return
        prefix = str(base_url).rstrip("/")
        for key in [k for k in _SERVER_RESPONDS_CACHE if k.startswith(prefix)]:
            _SERVER_RESPONDS_CACHE.pop(key, None)


def _server_responds_uncached(url: str, *, api_key: str, timeout: float,
                              level: int) -> bool:
    origin = url[:-3] if url.endswith("/v1") else url
    host_port = re.sub(r"^https?://", "", origin)
    host = host_port.split("/")[0]
    hostname, _, port_text = host.partition(":")
    try:
        port = int(port_text or (443 if origin.startswith("https://") else 80))
    except ValueError:
        return False
    if level <= 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((hostname, port)) == 0
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _try(target: str, *, with_key: bool) -> bool:
        hdrs = dict(headers) if with_key else {"User-Agent": USER_AGENT}
        try:
            request = urllib.request.Request(target, headers=hdrs)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return 200 <= int(getattr(response, "status", 200)) < 300
        except urllib.error.HTTPError as exc:
            return int(exc.code) in (401, 403)
        except (urllib.error.URLError, OSError, ValueError):
            return False

    if _try(f"{origin}/health", with_key=False):
        return True
    if level < 2:
        return False
    if _try(f"{origin}/v1/models", with_key=True):
        return True
    return _try(f"{origin}/v1/models", with_key=False)


def cleanup_stale_processes() -> int:
    """Зупинити рушії, що лишились від попередніх запусків IDE.

    Навіщо. Якщо IDE закрилась аварійно (вбитий процес, збій, закрите вікно
    консолі), ``llama-server`` продовжує тримати гігабайти VRAM. Користувач
    бачить «щось грузить відеокарту» і не може запустити гру.

    Безпека: зупиняємо ЛИШЕ ті PID, які ми самі записали, і лише якщо
    виконуваний файл справді ``llama-server``. Чужі процеси не чіпаємо.
    """
    removed = 0
    survivors: list[dict[str, Any]] = []
    for item in _read_pid_file():
        pid = int(item.get("pid") or 0)
        if not pid:
            continue
        try:
            ours = _pid_is_our_server(pid)
        except Exception:  # noqa: BLE001 - облік не має падати
            LOG.debug("Перевірка pid=%s не вдалась", pid, exc_info=True)
            ours = False
        if not ours:
            continue                    # процес уже помер — запис не потрібен
        LOG.info("Прибираю залишковий рушій попереднього запуску: pid=%s model=%s",
                 pid, item.get("model") or "?")
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10,
                           creationflags=_no_window())
            removed += 1
        except (OSError, subprocess.SubprocessError):
            LOG.debug("Не вдалось зупинити pid=%s", pid, exc_info=True)
            survivors.append(item)
    # Лишаємо у файлі тільки ті записи, які прибрати не вдалось: наступний
    # запуск спробує ще раз.
    _write_pid_file(survivors)
    return removed


@dataclass
class ServerConfig:
    """Параметри запуску llama-server."""

    model_path: str
    port: int = DEFAULT_PORT
    host: str = "127.0.0.1"
    plan: LaunchPlan | None = None
    api_key: str = MANAGED_API_KEY
    alias: str = ""
    extra_args: list[str] = field(default_factory=list)
    #: Файл візуального проєктора (``mmproj-*.gguf``). Потрібен, щоб
    #: мультимодальна модель СПРАВДІ бачила зображення: без ``--mmproj``
    #: llama.cpp приймає картинку в запиті, але модель її не бачить.
    mmproj_path: str = ""
    #: Скільки токенів мінімум відводити на одне зображення.
    #:
    #: ВАЖЛИВО: це не «чим більше, тим краще». Кожен проєктор має власний
    #: ``image_max_pixels``, і його перевищення робить модель
    #: незавантажуваною з помилкою ``image_max_pixels … is less than
    #: image_min_pixels``. Перевірено наживо: Ministral 3 14B працює з 1024 і
    #: НЕ працює з 1600. 1024 — безпечне значення для типових проєкторів.
    image_min_tokens: int = 1024

    def command(self) -> list[str]:
        args = [
            str(server_path()),
            "--model", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "--api-key", self.api_key,
            "--jinja",                 # шаблони чату й tool calling з GGUF-метаданих
            "--no-webui",              # веб-інтерфейс не потрібен, лише API
        ]
        if self.mmproj_path:
            mmproj = Path(self.mmproj_path)
            if mmproj.exists():
                args.extend(["--mmproj", str(mmproj)])
                # ── Токени на зображення: межа задається ПРОЄКТОРОМ ────────
                # Більше токенів = краще читається дрібний текст. АЛЕ кожен
                # проєктор має власний ``image_max_pixels``, і перевищення
                # робить модель НЕЗАВАНТАЖУВАНОЮ:
                #
                #   clip_init: failed to load model '…mmproj.gguf':
                #   load_hparams: image_max_pixels (802816) is less than
                #   image_min_pixels (1605632)
                #
                # Перевірено наживо: для Ministral 3 14B ``--image-min-tokens
                # 1600`` дає саме цю помилку й сервер не стартує взагалі.
                # Тому беремо безпечне значення 1024 і дозволяємо перекрити
                # його явним налаштуванням лише за потреби.
                args.extend(["--image-min-tokens", str(self.image_min_tokens)])
            else:
                LOG.warning("Файл проєктора не знайдено: %s — модель буде "
                            "без зору", mmproj)
        if self.alias:
            # Без alias /v1/models віддає повний шлях до файлу — його незручно
            # показувати в рядку моделі IDE.
            args.extend(["--alias", self.alias])
        if self.plan:
            args.extend(self.plan.args())
        args.extend(self.extra_args)
        return args


class LocalServer:
    """Керування процесом llama-server: старт, перевірка готовності, стоп."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.process: subprocess.Popen | None = None
        self.log_path = runtime_dir() / "server.log"
        self._log_handle: Any = None
        # ── Watchdog ───────────────────────────────────────────────────────
        # Раніше смерть llama-server помічалась лише за наступною помилкою
        # запиту: користувач бачив «немає з'єднання» замість причини.
        # Тепер окремий потік стежить за процесом і повідомляє про смерть.
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        #: Хто отримає звістку про смерть процесу (підпис, деталі).
        self.on_died: Callable[[str], None] | None = None
        #: Остання причина смерті — щоб панель могла її показати.
        self.died_reason = ""
        self._died_reported = False

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}/v1"

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        exe = server_path()
        if not exe.exists():
            raise EngineError("Рушій llama.cpp не встановлено. Спершу встанови його.")
        model = Path(self.config.model_path)
        if not model.exists():
            raise EngineError(f"Файл моделі не знайдено: {model}")

        # Шлях до моделі робимо АБСОЛЮТНИМ. Рушій стартує з теки
        # ``runtime_dir()``, тому відносний шлях (``userdata\\models\\x.gguf``)
        # він шукав би всередині неї й падав із «failed to load model» —
        # хоча файл на місці. Перевірка ``model.exists()`` цього не ловила:
        # вона виконується з робочою текою IDE, а не рушія.
        model = model.resolve()
        if str(model) != str(self.config.model_path):
            self.config.model_path = str(model)

        # ── Порт: не займати чужий ─────────────────────────────────────────
        # Якщо порт уже слухає інша програма (напр. Steam на 8080 або
        # TorrServer на 8090), llama-server падає з «couldn't bind HTTP server
        # socket» ще до завантаження моделі. Раніше це виглядало як «сервер не
        # піднявся» без пояснення. Тепер беремо наступний вільний порт і
        # повідомляємо про це.
        if port_is_busy(self.config.port, self.config.host):
            old = self.config.port
            new = free_port(old + 1)
            LOG.warning("Порт %s зайнятий — рушій стартує на %s", old, new)
            self.config.port = new

        command = self.config.command()
        # Шляхи з пробілами Windows ламає, якщо передавати список через shell,
        # тому запускаємо напряму (shell=False) — це надійніше й безпечніше.
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._log_handle = open(self.log_path, "w", encoding="utf-8", errors="replace")
        LOG.info("Старт рушія: %s", " ".join(command))
        self.process = subprocess.Popen(
            command,
            cwd=str(runtime_dir()),
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creation,
        )
        # Запам'ятовуємо PID: якщо IDE закриється аварійно, наступний запуск
        # прибере цей процес і звільнить відеопам'ять (див.
        # :func:`cleanup_stale_processes`).
        try:
            remember_process(self.process.pid, model=str(model),
                             port=int(self.config.port or 0))
        except Exception:  # noqa: BLE001 - облік не має ламати запуск
            LOG.debug("PID рушія не збережено", exc_info=True)

    def wait_ready(self, timeout: float = 180.0,
                   on_status: Callable[[str], None] | None = None) -> tuple[bool, str]:
        """Чекати, поки сервер почне відповідати на /v1/models."""
        deadline = time.monotonic() + timeout
        url = f"{self.config.host and self.base_url}/models"
        # Статус оновлюємо не частіше ніж раз на 5 с: інакше рядок у панелі
        # перемальовується щосекунди й виглядає як зависання.
        next_status = 0.0
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                tail = self.tail_log(20)
                return False, f"Процес завершився (код {self.process.returncode}).\n{tail}"
            try:
                request = urllib.request.Request(url, method="GET")
                request.add_header("Authorization", f"Bearer {self.config.api_key}")
                request.add_header("User-Agent", USER_AGENT)
                with urllib.request.urlopen(request, timeout=3) as response:
                    if response.status == 200:
                        return True, "Сервер готовий."
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            now = time.monotonic()
            if on_status and now >= next_status:
                next_status = now + 5.0
                left = int(deadline - now)
                on_status(f"Завантажую модель у пам'ять… (лишилось ~{left} с)")
            time.sleep(1.0)
        return False, f"Сервер не відповів за {timeout:.0f} с.\n{self.tail_log(20)}"

    # ── Watchdog ──────────────────────────────────────────────────────────
    def start_watchdog(self, interval: float = 2.0) -> None:
        """Стежити за процесом і повідомити, якщо він помре.

        ``AUTOMATIC_RUNTIME.md`` §7: «Якщо ``llama-server`` помре під час
        роботи, IDE це помітить лише за наступною помилкою запиту.
        Автоматичного перезапуску немає». Перезапуск лишаємо користувачу
        (він може хотіти іншу модель), але **факт смерті** тепер видно
        одразу: панель отримує причину й хвіст журналу.

        Потік — демон, тому не тримає застосунок живим; ``stop()`` його
        зупиняє. Повторних повідомлень немає (``_died_reported``).
        """
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        process = self.process
        if process is None:
            return
        self._watchdog_stop.clear()
        self._died_reported = False
        self.died_reason = ""

        def _watch() -> None:
            while not self._watchdog_stop.wait(interval):
                try:
                    code = process.poll()
                except OSError:
                    return
                if code is None:
                    continue
                if self._died_reported:
                    return          # уже повідомили
                self._died_reported = True
                tail = self.tail_log(15)
                reason = (f"Рушій завершився сам (код {code}). "
                          f"Модель більше не відповідатиме.")
                self.died_reason = reason
                LOG.warning("%s\n%s", reason, tail)
                callback = self.on_died
                if callback is not None:
                    try:
                        callback(reason)
                    except Exception:  # noqa: BLE001 - звіт не має ламати потік
                        LOG.debug("on_died впав", exc_info=True)
                return

        self._watchdog = threading.Thread(
            target=_watch, name="llama-watchdog", daemon=True)
        self._watchdog.start()

    def stop_watchdog(self) -> None:
        """Зупинити стеження (викликається зі ``stop()``)."""
        self._watchdog_stop.set()
        thread = self._watchdog
        self._watchdog = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def stop(self, timeout: float = 10.0) -> None:
        self.stop_watchdog()
        process = self.process
        pid = int(process.pid) if process is not None else 0
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    # Останній рубіж: вбиваємо дерево процесів. Без цього
                    # llama-server міг лишитись живим і тримати VRAM.
                    if pid:
                        try:
                            subprocess.run(
                                ["taskkill", "/PID", str(pid), "/T", "/F"],
                                capture_output=True, timeout=10,
                                creationflags=_no_window())
                        except (OSError, subprocess.SubprocessError):
                            LOG.debug("taskkill не вдався для pid=%s", pid)
        self.process = None
        if pid:
            try:
                forget_process(pid)
            except Exception:  # noqa: BLE001
                LOG.debug("PID не прибрано", exc_info=True)
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def tail_log(self, lines: int = 40) -> str:
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(content.splitlines()[-lines:])


#: Ознаки того, що збій стався в GPU-бекенді, а не в самій моделі.
#:
#: Це принципово: якщо файл моделі пошкоджений або архітектура невідома,
#: повторювати запуск із меншим offload марно. А якщо «не влізло у VRAM» —
#: саме зменшення offload і допомагає.
GPU_FAILURE_MARKERS: tuple[str, ...] = (
    "cuda error", "cuda_error", "out of memory", "outofmemory",
    "failed to allocate", "cudamalloc", "cublas", "device memory",
    "hip error", "vulkan error", "vk_error",
    "erroroutofdevicememory", "insufficient memory",
    # ── реальні повідомлення llama.cpp / ggml ──────────────────────────────
    # Перевірено на справжніх рядках: без цих маркерів типовий збій CUDA
    # («no CUDA-capable device is detected», «Failed to load ggml-cuda.dll»,
    # «CUDA driver version is insufficient») НЕ визнавався GPU-збоєм, і
    # агент навіть не пробував CPU-fallback — робив одну спробу й здавався.
    #
    # Маркери навмисно вужчі за «cuda device» і «ggml_backend_cuda»: ці
    # рядки бувають і в УСПІШНОМУ лозі («ggml_backend_cuda_init: found 1
    # CUDA devices»), і тоді справжній запуск вважався б збоєм.
    "failed to initialize cuda", "no cuda-capable", "cuda-capable device is detected",
    "failed to load ggml-cuda", "failed to load cuda", "cuda runner failed",
    "cuda driver version", "driver version is insufficient",
    "unable to init cuda", "no capable devices", "no suitable gpu",
    "gpu not supported", "ggml_cuda_init: failed",
)

#: Ознаки того, що СПЕЦИФІЧНО зір спричинив збій завантаження.
#:
#: Найчастіше це ``--image-min-tokens`` понад ``image_max_pixels`` проєктора.
#: Лікується запуском БЕЗ проєктора (модель стане текстовою) — краще так,
#: ніж взагалі без моделі.
MMPROJ_FAILURE_MARKERS: tuple[str, ...] = (
    "failed to load clip", "clip_init", "mtmd", "mmproj",
    "image_max_pixels", "image_min_pixels", "failed to load multimodal",
)


def is_mmproj_failure(text: str) -> bool:
    """Чи збій стався через візуальний проєктор."""
    low = (text or "").lower()
    return any(marker in low for marker in MMPROJ_FAILURE_MARKERS)


def is_gpu_failure(text: str) -> bool:
    """Чи схоже повідомлення на збій відеопам'яті / GPU-бекенду."""
    low = (text or "").lower()
    return any(marker in low for marker in GPU_FAILURE_MARKERS)


def recovery_steps(profile: HardwareProfile | None,
                   choice: ModelChoice) -> list[LaunchPlan]:
    """План Б: від найкращого до найнадійнішого.

    Порядок саме такий, бо кожен крок втрачає швидкість:

    1. авто-план (може бути повний offload);
    2. менше контексту — головний споживач VRAM після ваг;
    3. частковий offload (половина шарів на GPU);
    4. мінімальний offload (чверть шарів);
    5. чистий CPU — повільно, але працює завжди.

    Раніше після невдалого старту агент просто здавався: ``server.stop()`` і
    повідомлення «сервер не піднявся». Користувач лишався без моделі, хоча
    та сама модель чудово працює з меншим контекстом.
    """
    plans: list[LaunchPlan] = []
    if profile is None:
        return plans
    # 1–2. Штатний план і зменшений контекст.
    base = fit(profile, choice)
    plans.append(base.plan)
    for target in (8192, 4096):
        if target < base.plan.ctx_size:
            smaller = fit(profile, choice, target_ctx=target).plan
            if not any(_same_plan(smaller, plan) for plan in plans):
                plans.append(smaller)
    # 3–4. Частковий offload: ваги лишаються в RAM, частина шарів — на GPU.
    #
    # Контекст беремо НЕ більший за найскромніший попередній крок: інакше
    # «крок відновлення» вимагав би більше пам'яті, ніж крок, який щойно
    # впав, — і план Б рухався б назад. Інваріант перевіряє
    # ``test_plan_requirements_do_not_grow``.
    threads = max(2, min(profile.cpu_threads or 4, 16))
    hybrid_ctx = min(4096, base.plan.ctx_size)
    for share in (0.5, 0.25):
        layers = max(1, int(choice.layers * share))
        plans.append(LaunchPlan(gpu_layers=layers, ctx_size=hybrid_ctx,
                                threads=threads, flash_attn="auto", batch=256,
                                cache_type="q8_0"))
    # 5. Останній рубіж — без GPU.
    plans.append(LaunchPlan(gpu_layers=0, ctx_size=min(4096, base.plan.ctx_size),
                            threads=threads, flash_attn="off", batch=256,
                            cache_type="q8_0"))
    unique: list[LaunchPlan] = []
    for plan in plans:
        if not any(_same_plan(plan, seen) for seen in unique):
            unique.append(plan)
    return unique


def _layer_rank(plan: LaunchPlan, total_layers: int) -> int:
    """Скільки шарів план реально кладе на GPU, у порівнянних числах.

    ``gpu_layers = -1`` означає «усі шари разом із lm_head» — у llama.cpp це
    НАЙБІЛЬШИЙ offload, а не найменший. Порівнювати ``-1`` з числами напряму
    не можна: ``-1 < 24`` дало б хибний висновок, ніби повний offload дешевший
    за гібрид.
    """
    if plan.gpu_layers < 0:
        return max(total_layers, 1)
    return plan.gpu_layers


def _same_plan(left: LaunchPlan, right: LaunchPlan) -> bool:
    return (left.gpu_layers == right.gpu_layers and left.ctx_size == right.ctx_size
            and left.cache_type == right.cache_type)


def launch_with_recovery(
    model_path: Path | str,
    *,
    choice: ModelChoice,
    profile: HardwareProfile | None = None,
    alias: str = "",
    mmproj_path: str = "",
    port: int | None = None,
    on_status: Callable[[str], None] | None = None,
    wait_timeout: float = 300.0,
) -> tuple[list[LocalServer], str]:
    """Підняти llama-server, автоматично знижуючи вимоги після збою.

    Повертає ``(сервери, повідомлення)``. У списку лишається ЩОЙНО запущений
    сервер (попередні вже зупинені); порожній список означає, що не вдалось
    жодного разу, а в повідомленні — справжня причина останньої спроби.
    """
    def status(text: str) -> None:
        if on_status:
            try:
                on_status(text)
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати запуск
                LOG.debug("on_status впав", exc_info=True)

    steps = recovery_steps(profile, choice)
    if not steps:
        steps = [LaunchPlan(gpu_layers=0, ctx_size=4096, threads=4,
                            flash_attn="off", cache_type="q8_0")]
    detail = ""
    for index, plan in enumerate(steps):
        use_port = port if port is not None else free_port(DEFAULT_PORT)
        mode = plan.summary()
        if index:
            status(f"Повторюю запуск простіше: {mode} (спроба {index + 1}/{len(steps)})")
        else:
            status(f"План запуску: {mode}")
        config = ServerConfig(model_path=str(model_path), port=use_port, plan=plan,
                              alias=alias, mmproj_path=mmproj_path)
        server = LocalServer(config)
        try:
            server.start()
        except (EngineError, OSError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            server.stop()
            continue
        ok, note = server.wait_ready(timeout=wait_timeout, on_status=on_status)
        if ok:
            return [server], f"{mode} · порт {use_port}"
        detail = note
        server.stop()
        # ── Збій через проєктор зору: перезапуск БЕЗ нього ────────────────
        # Напр. ``--image-min-tokens`` перевищив ``image_max_pixels``
        # проєктора. Текстова модель корисніша за відсутню.
        if mmproj_path and is_mmproj_failure(note) and index == 0:
            status("Зір не піднявся — запускаю модель без проєктора "
                   "(текстовий режим).")
            LOG.warning("Проєктор не завантажився, повторюю без нього: %s",
                        note.splitlines()[-3:] if note else "")
            config = ServerConfig(model_path=str(model_path), port=use_port,
                                  plan=plan, alias=alias, mmproj_path="")
            retry = LocalServer(config)
            try:
                retry.start()
            except (EngineError, OSError) as exc:
                detail = f"{type(exc).__name__}: {exc}"
                retry.stop()
                continue
            ok2, note2 = retry.wait_ready(timeout=wait_timeout, on_status=on_status)
            if ok2:
                return [retry], f"{mode} · без зору · порт {config.port}"
            detail = note2
            retry.stop()
            continue
        # Помилка не про пам'ять (немає файлу, погана архітектура) — інші
        # плани теж не допоможуть, не марнуємо час користувача.
        if not is_gpu_failure(note):
            LOG.info("Збій не пов'язаний із GPU — повторювати простіше не буду: %s",
                     note.splitlines()[-1] if note else "")
            break
    return [], detail


# ─────────────────────────────────────────────────────────────────────────────
# Повний автозапуск: рушій + модель
# ─────────────────────────────────────────────────────────────────────────────

class AutoLauncher:
    """Один крок «з коробки»: перевірити рушій, поставити, підняти сервер.

    Використовується майстром першого запуску. Усі етапи — у фоні, прогрес
    і статуси йдуть через callback'и, щоб вікно не «замерзало».
    """

    def __init__(
        self,
        profile: HardwareProfile,
        choice: ModelChoice,
        model_path: Path,
        *,
        on_status: Callable[[str], None] | None = None,
        on_progress: Callable[[Progress], None] | None = None,
    ) -> None:
        self.profile = profile
        self.choice = choice
        self.model_path = Path(model_path)
        self.on_status = on_status
        self.on_progress = on_progress
        self.server: LocalServer | None = None
        self.error = ""
        self.base_url = ""

    def run_blocking(self, *, install_engine_too: bool = True) -> bool:
        try:
            if not engine_installed():
                if not install_engine_too:
                    self.error = "Рушій llama.cpp не встановлено."
                    return False
                self._status("Встановлюю рушій llama.cpp…")
                job = EngineInstall(profile=self.profile, on_progress=self.on_progress, on_status=self.on_status)
                if not job.run_blocking():
                    self.error = job.error or "Не вдалось встановити рушій."
                    return False

            if not self.model_path.exists():
                self.error = f"Немає файлу моделі: {self.model_path}"
                return False

            plan = fit(self.profile, self.choice).plan
            port = free_port(DEFAULT_PORT)
            config = ServerConfig(model_path=str(self.model_path), port=port, plan=plan)
            self.server = LocalServer(config)
            self._status(f"Запускаю модель {self.choice.label} на порту {port}…")
            self.server.start()
            ok, detail = self.server.wait_ready(on_status=self.on_status)
            if not ok:
                self.error = detail
                self.server.stop()
                return False
            # Стеження за процесом: якщо рушій помре під час роботи, панель
            # дізнається про це одразу, а не за наступною помилкою запиту.
            self.server.on_died = self._on_server_died
            self.server.start_watchdog()
            self.base_url = self.server.base_url
            self._status(f"Модель готова: {self.base_url}")
            return True
        except (EngineError, HubError, OSError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            LOG.exception("Автозапуск впав")
            return False
        except Exception as exc:  # noqa: BLE001 - показуємо користувачу
            self.error = f"{type(exc).__name__}: {exc}"
            LOG.exception("Автозапуск впав")
            return False

    def stop(self) -> None:
        if self.server:
            self.server.stop()

    def _on_server_died(self, reason: str) -> None:
        """Рушій помер сам — сказати користувачу причину, а не «немає з'єднання»."""
        self.error = reason
        self.base_url = ""
        self._status(
            f"{reason} Натисни «Запустити модель», щоб підняти її знову."
        )

    def _status(self, text: str) -> None:
        LOG.info("%s", text)
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                LOG.debug("on_status впав", exc_info=True)


__all__ = [
    "AutoLauncher",
    "EngineError",
    "EngineInstall",
    "LocalServer",
    "MANAGED_API_KEY",
    "ServerConfig",
    "backend_preference",
    "choose_asset",
    "choose_assets",
    "engine_installed",
    "engine_version",
    "free_port",
    "install_engine",
    "is_gpu_failure",
    "launch_with_recovery",
    "plan_engine_install",
    "recovery_steps",
    "runtime_dir",
    "server_path",
]

