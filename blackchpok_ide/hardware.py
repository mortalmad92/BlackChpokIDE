"""Визначення «заліза» і підбір моделі під нього.

Модуль не залежить від tkinter і не потребує сторонніх бібліотек: усе
читається зі stdlib (ctypes, winreg, shutil, os) та системних утиліт
(``nvidia-smi``, ``wmic``). Використовується майстром першого запуску і
панеллю «Хаб моделей», щоб користувач нічого не налаштовував вручну.

Головна ідея: порахувати, скільки гігабайтів «влізе» під модель, і обрати
найрозумнішу модель, яка ще поміщається з запасом.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger("blackchpok.hardware")

GB = 1024 ** 3

# Скільки VRAM лишаємо вільно: драйвер, робочий стіл, інші застосунки.
VRAM_RESERVE_GB = 1.0
# Резерв системної пам'яті, щоб не загнати Windows у swap.
RAM_RESERVE_GB = 3.0
# Частина вільної RAM, яку дозволяємо зайняти моделі.
RAM_SHARE = 0.75
# Накладні витрати рушія: граф обчислень, буфери, токенізатор.
RUNTIME_OVERHEAD_GB = 0.7
# Контексти, які пробуємо, від більшого до меншого.
CTX_LADDER = (16384, 12288, 8192, 6144, 4096, 2048)
# 4096 токенів — практичний мінімум: агент передає файли й результати інструментів.
MIN_CTX = 4096
#: «Усі шари на GPU» у термінах llama.cpp.
#:
#: ВАЖЛИВО: саме ``-1``, а не ``999``. Число, більше за кількість блоків,
#: нормалізується рушієм, але проходить через ``fit_params``, і при завеликому
#: запиті llama.cpp обриває завантаження:
#:
#:   W common_fit_params: failed to fit params to free device memory:
#:     n_gpu_layers already set by user to 999, abort
#:
#: Перевірено наживо на RTX 3060 12 ГБ: з ``--n-gpu-layers 999`` llama-server
#: не піднімається взагалі, з ``-1`` — 31 ток/с.
FULL_OFFLOAD = -1


# ─────────────────────────────────────────────────────────────────────────────
# Структури даних
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GpuInfo:
    """Одна відеокарта."""

    name: str = ""
    vram_gb: float = 0.0
    vendor: str = ""          # nvidia | amd | intel | ""
    backend: str = ""         # cuda | rocm | vulkan | ""
    driver: str = ""


@dataclass
class HardwareProfile:
    """Знімок заліза + похідні рекомендації."""

    os_name: str = ""
    arch: str = ""
    cpu_name: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    gpus: list[GpuInfo] = field(default_factory=list)
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0

    # ── похідні величини ───────────────────────────────────────────────────
    @property
    def best_gpu(self) -> GpuInfo | None:
        if not self.gpus:
            return None
        return max(self.gpus, key=lambda gpu: gpu.vram_gb)

    @property
    def vram_gb(self) -> float:
        gpu = self.best_gpu
        return gpu.vram_gb if gpu else 0.0

    @property
    def has_cuda(self) -> bool:
        return any(gpu.backend == "cuda" for gpu in self.gpus)

    @property
    def has_rocm(self) -> bool:
        return any(gpu.backend == "rocm" for gpu in self.gpus)

    @property
    def has_vulkan(self) -> bool:
        return any(gpu.backend == "vulkan" for gpu in self.gpus)

    @property
    def backend(self) -> str:
        """Найшвидший доступний бекенд для llama.cpp."""
        if self.has_cuda:
            return "cuda"
        if self.has_rocm:
            return "rocm"
        if self.has_vulkan:
            return "vulkan"
        return "cpu"

    @property
    def ram_budget_gb(self) -> float:
        """Скільки RAM можна віддати моделі, не загнавши систему у swap."""
        ram = self.ram_available_gb or self.ram_total_gb
        return round(max(0.0, min(ram - RAM_RESERVE_GB, ram * RAM_SHARE)), 1)

    @property
    def vram_budget_gb(self) -> float:
        """Скільки VRAM можна віддати моделі після резерву на робочий стіл."""
        if self.vram_gb <= 0:
            return 0.0
        return round(max(0.0, self.vram_gb - VRAM_RESERVE_GB), 1)

    @property
    def usable_gb(self) -> float:
        """Скільки ГБ ваг моделі реально влізе.

        Гібридний режим (частина шарів у VRAM, решта в RAM) дає суму обох
        бюджетів — але повільніше, ніж повністю у VRAM.
        """
        if self.vram_gb > 0:
            return round(self.vram_budget_gb + self.ram_budget_gb * 0.6, 1)
        return self.ram_budget_gb

    @property
    def full_gpu_gb(self) -> float:
        """Скільки ваг уміщається повністю у VRAM (найшвидший режим)."""
        return self.vram_budget_gb

    def summary(self) -> str:
        """Один рядок для панелі стану."""
        gpu = self.best_gpu
        gpu_text = f"{gpu.name} {gpu.vram_gb:.0f} ГБ" if gpu and gpu.vram_gb else "без GPU"
        ram = self.ram_available_gb or self.ram_total_gb
        return (
            f"{self.cpu_name or 'CPU'} · {ram:.0f} ГБ RAM · {gpu_text} · "
            f"до {self.usable_gb:.0f} ГБ під модель ({self.backend})"
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "usable_gb": self.usable_gb,
                "vram_budget_gb": self.vram_budget_gb,
                "ram_budget_gb": self.ram_budget_gb,
                "backend": self.backend,
                "vram_gb": self.vram_gb,
            }
        )

        return data


# ─────────────────────────────────────────────────────────────────────────────
# Визначення заліза
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 8) -> str:
    """Запустити утиліту і повернути stdout (порожній рядок при помилці)."""
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout or ""


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except (OSError, ImportError, IndexError):
            pass
    if sys.platform == "darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or platform.processor()
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _memory_gb() -> tuple[float, float]:
    """(всього, доступно) оперативної пам'яті в ГБ."""
    if sys.platform == "win32":
        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return status.ullTotalPhys / GB, status.ullAvailPhys / GB
        except (AttributeError, OSError):
            pass
    elif sys.platform == "darwin":
        total = _run(["sysctl", "-n", "hw.memsize"]).strip()
        try:
            return int(total) / GB, int(total) / GB * 0.75
        except ValueError:
            pass
    else:
        try:
            info: dict[str, str] = {}
            with open("/proc/meminfo", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    key, _, value = line.partition(":")
                    info[key.strip()] = value.strip()
            def kb(name: str) -> float:
                return float(info.get(name, "0 kB").split()[0]) * 1024
            return kb("MemTotal") / GB, kb("MemAvailable") / GB
        except (OSError, ValueError, IndexError):
            pass
    return 0.0, 0.0


def _nvidia_gpus() -> list[GpuInfo]:
    """Відеокарти NVIDIA через nvidia-smi (найточніші дані)."""
    output = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    gpus: list[GpuInfo] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            continue
        try:
            vram = float(parts[1]) / 1024
        except ValueError:
            vram = 0.0
        gpus.append(
            GpuInfo(
                name=parts[0],
                vram_gb=round(vram, 1),
                vendor="nvidia",
                backend="cuda",
                driver=parts[2] if len(parts) > 2 else "",
            )
        )
    return gpus


def _windows_registry_gpus() -> list[GpuInfo]:
    """Резервне визначення GPU через реєстр Windows."""
    gpus: list[GpuInfo] = []
    try:
        import winreg
    except ImportError:
        return gpus
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return gpus
    with root:
        index = 0
        while index < 32:
            try:
                sub_name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not sub_name.isdigit():
                continue
            try:
                sub = winreg.OpenKey(root, sub_name)
            except OSError:
                continue
            with sub:
                try:
                    name = str(winreg.QueryValueEx(sub, "DriverDesc")[0]).strip()
                except OSError:
                    continue
                vram = 0
                for value_name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                    try:
                        vram = int(winreg.QueryValueEx(sub, value_name)[0])
                        break
                    except (OSError, ValueError, TypeError):
                        continue
                if not name:
                    continue
                low = name.lower()
                if "basic display" in low or "remote display" in low or "basic render" in low:
                    continue
                vendor = ""
                backend = ""
                if "nvidia" in low:
                    vendor, backend = "nvidia", "cuda"
                elif "amd" in low or "radeon" in low or "ati " in low:
                    vendor, backend = "amd", "rocm"
                elif "intel" in low or "arc" in low:
                    vendor, backend = "intel", "vulkan"
                if not vendor:
                    vendor, backend = "unknown", "vulkan"
                gpus.append(
                    GpuInfo(
                        name=name,
                        vram_gb=round(vram / GB, 1) if vram else 0.0,
                        vendor=vendor,
                        backend=backend,
                    )
                )
    return gpus


def _merge_gpus(primary: Iterable[GpuInfo], secondary: Iterable[GpuInfo]) -> list[GpuInfo]:
    """Об'єднати списки GPU, віддаючи перевагу записам із відомим обсягом VRAM."""
    merged: dict[str, GpuInfo] = {}
    for gpu in [*secondary, *primary]:
        key = gpu.name.lower()
        previous = merged.get(key)
        if previous is None or gpu.vram_gb > previous.vram_gb:
            merged[key] = gpu
        elif previous and not previous.driver and gpu.driver:
            previous.driver = gpu.driver
    return list(merged.values())


def detect(path: Path | str | None = None) -> HardwareProfile:
    """Зібрати профіль заліза.

    ``path`` — тека, вільне місце якої перевіряємо (типово домашня тека).
    """
    total_ram, available_ram = _memory_gb()
    registry_gpus = _windows_registry_gpus() if sys.platform == "win32" else []
    gpus = _merge_gpus(_nvidia_gpus(), registry_gpus)

    threads = os.cpu_count() or 0
    profile = HardwareProfile(
        os_name=f"{platform.system()} {platform.release()}",
        arch=platform.machine(),
        cpu_name=_cpu_name(),
        cpu_cores=max(1, threads // 2) if threads else 0,
        cpu_threads=threads,
        ram_total_gb=round(total_ram, 1),
        ram_available_gb=round(available_ram, 1),
        gpus=gpus,
    )

    target = Path(path) if path else Path.home()
    try:
        usage = shutil.disk_usage(target)
        profile.disk_free_gb = round(usage.free / GB, 1)
        profile.disk_total_gb = round(usage.total / GB, 1)
    except OSError:
        pass
    LOG.info("Залізо: %s", profile.summary())
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Каталог рекомендованих моделей
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelChoice:
    """Запис каталогу: конкретний GGUF-файл, який ми вміємо завантажити."""

    repo: str
    filename: str
    label: str
    params_b: float
    approx_gb: float
    min_usable_gb: float
    note: str = ""
    # Скільки шарів у моделі — потрібно, щоб порахувати часткове вивантаження.
    layers: int = 28

    @property
    def ref(self) -> str:
        return f"{self.repo}/{self.filename}"

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"

    @property
    def short_name(self) -> str:
        """Ім'я файлу без розширення — його показує llama-server у /v1/models."""
        return self.filename.rsplit("/", 1)[-1].removesuffix(".gguf")


# Порядок — від найменшої до найбільшої.
# approx_gb    — розмір файлу ваг;
# min_usable_gb — мінімум доступної пам'яті, щоб модель тримала агентський контекст;
# layers       — кількість блоків трансформера (для розрахунку часткового offload).
MODEL_CATALOG: tuple[ModelChoice, ...] = (
    ModelChoice("Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF",
                "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf",
                "Qwen2.5-Coder 0.5B", 0.5, 0.46, 1.4, "дуже слабка, лише перевірити роботу", 24),
    ModelChoice("Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
                "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
                "Qwen2.5-Coder 1.5B", 1.5, 1.04, 2.2, "швидка, прості правки", 28),
    ModelChoice("Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
                "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
                "Qwen2.5-Coder 3B", 3.0, 1.96, 3.4, "баланс швидкості й якості", 36),
    ModelChoice("Qwen/Qwen3-4B-GGUF",
                "Qwen3-4B-Q4_K_M.gguf",
                "Qwen3 4B", 4.0, 2.33, 3.8, "новіше покоління, добре тримає інструменти", 36),
    ModelChoice("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
                "Qwen2.5-Coder 7B", 7.0, 4.36, 6.0, "найкращий вибір для 8 ГБ VRAM", 28),
    ModelChoice("Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
                "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
                "Qwen2.5-Coder 14B", 14.0, 8.37, 11.5, "сильна, комфортно з 12+ ГБ", 48),
    # Ministral 3 14B: менший файл за Qwen 14B (7.67 проти 8.37 ГБ), при цьому
    # має зір (Pixtral encoder) і нативний tool calling. Перевірено наживо на
    # RTX 3060 12 ГБ: зір читає дрібний текст інтерфейсу, tool_calls приходять
    # структурно. Проєктор лежить в ОФІЦІЙНОМУ репозиторії окремим файлом
    # (``…-BF16-mmproj.gguf``) — без нього модель буде текстовою.
    ModelChoice("mistralai/Ministral-3-14B-Instruct-2512-GGUF",
                "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf",
                "Ministral 3 14B Instruct", 14.0, 7.67, 11.0,
                "зір + інструменти; окремо є Reasoning-варіант", 40),
    ModelChoice("Qwen/Qwen2.5-Coder-32B-Instruct-GGUF",
                "qwen2.5-coder-32b-instruct-q3_k_m.gguf",
                "Qwen2.5-Coder 32B", 32.0, 14.84, 16.5, "майже рівень GPT-4o на коді, 24 ГБ", 64),
)


def kv_cache_gb(choice: ModelChoice, ctx: int) -> float:
    """Приблизний обсяг KV-кешу для контексту (fp16, GQA).

    Малі моделі зазвичай мають 4 KV-голови, великі — 8. Точні числа лежать
    у метаданих GGUF, але для вибору параметрів запуску достатньо цієї
    оцінки; похибка компенсується резервом RUNTIME_OVERHEAD_GB.
    """
    kv_heads = 4 if choice.params_b <= 8 else 8
    head_dim = 128
    bytes_per_token = choice.layers * kv_heads * head_dim * 2 * 2  # K+V, fp16
    return round(bytes_per_token * ctx / GB, 2)


def est_vram_gb(choice: ModelChoice, ctx: int, gpu_layers: int) -> float:
    """Скільки VRAM займе модель із заданим числом шарів на GPU.

    ``gpu_layers == -1`` — це «усі шари РАЗОМ із вихідним шаром» у
    термінах llama.cpp; будь-яке число ≥ ``layers`` теж означає повний
    offload (рушій його нормалізує).
    """
    share = (1.0 if gpu_layers < 0 or gpu_layers >= choice.layers
             else max(0.0, min(1.0, gpu_layers / max(choice.layers, 1))))
    weights = choice.approx_gb * share
    kv = kv_cache_gb(choice, ctx) * share
    return round(weights + kv + RUNTIME_OVERHEAD_GB, 2)


@dataclass(frozen=True)
class ModelFit:
    """Результат приміряння моделі до заліза."""

    choice: ModelChoice
    plan: "LaunchPlan"
    fits_vram: bool
    speed: str            # gpu | hybrid | cpu
    vram_needed_gb: float

    @property
    def is_speed_ok(self) -> bool:
        """Швидкість, з якою приємно працювати (не «кілька токенів за секунду»)."""
        return self.speed in {"gpu", "hybrid"}

    def describe(self) -> str:
        mode = {"gpu": "повністю на GPU", "hybrid": "частково на GPU", "cpu": "на CPU"}[self.speed]
        return f"{self.choice.label} · {mode} · {self.plan.ctx_size // 1024}K контекст"


def fit(profile: HardwareProfile, choice: ModelChoice, *,
        target_ctx: int = 0) -> ModelFit:
    """Приміряти модель: чи влізе, як швидко, з якими параметрами.

    ``target_ctx`` — скільки контексту просить користувач (0 = авто).
    Коли ваги не влазять разом із точним KV-кешем, план сам переходить на
    стиснутий кеш (``q8_0``), а далі — на кеш у RAM. Це дає більший
    контекст без переїзду всієї моделі в системну пам'ять.
    """
    threads = max(2, min(profile.cpu_threads or 4, 16))
    gpu = profile.best_gpu
    vram_budget = profile.vram_budget_gb
    ram_budget = profile.ram_budget_gb

    if not gpu or vram_budget <= 0:
        # Лише CPU: контекст тримаємо скромним, інакше генерація «повзе».
        ctx = _pick_ctx(choice, ram_budget, vram_budget=0.0)
        plan = LaunchPlan(gpu_layers=0, ctx_size=ctx, threads=threads,
                          flash_attn="off", batch=256, cache_type="q8_0")
        return ModelFit(choice, plan, False, "cpu", 0.0)
    # 1. Чи влізе повністю у VRAM? Спершу точний KV, далі стиснутий.
    #
    # Коли користувач просить БІЛЬШИЙ контекст, «перший, що влізе» — не
    # відповідь: 8192 влізе завжди, і саме він повертався б на запит 16384.
    # Тому беремо найбільший контекст, що задовольняє ціль.
    def _ladder() -> list[int]:
        """Контексти від більшого до меншого (стеля — те, що просить користувач)."""
        steps = [ctx for ctx in CTX_LADDER if ctx >= MIN_CTX]
        if target_ctx:
            steps = [ctx for ctx in steps if ctx <= target_ctx]
        return sorted(steps, reverse=True)

    # 1. Один прохід драбиною. На кожному кроці пробуємо розміщення кешу в
    #    порядку переваги: стиснутий KV у VRAM → точний KV у VRAM → KV у RAM.
    #
    # ЧОМУ q8_0 ПЕРШИЙ, а не f16: заміряно на справжньому сервері
    # (Qwen2.5-Coder-14B, RTX 3060 12 ГБ). При ОДНАКОВОМУ контексті 8K:
    #   f16  → 32.2 ток/с;  q8_0 → 31.6 ток/с  (різниця 2%, у межах шуму).
    # При 16K: f16 у 12 ГБ VRAM не влазить зовсім, і рушій тихо деградує до
    # 14 ток/с, тоді як q8_0 дає 31.7 ток/с. Тобто стиснутий кеш дає вдвічі
    # більший контекст за ту саму швидкість — це очевидно кращий вибір.
    extended = sorted(set(CTX_LADDER) | set(CTX_LADDER_RAM), reverse=True)
    for ctx in extended:
        if ctx < MIN_CTX:
            continue
        if target_ctx and ctx > target_ctx:
            continue
        # а) стиснутий KV (q8_0) у VRAM — той самий контекст, удвічі менше VRAM
        need_q8 = (choice.approx_gb + kv_cache_gb(choice, ctx) / 2
                   + RUNTIME_OVERHEAD_GB)
        if need_q8 <= vram_budget:
            plan = LaunchPlan(gpu_layers=FULL_OFFLOAD, ctx_size=ctx, threads=threads,
                              flash_attn="auto",
                              batch=512 if vram_budget >= 8 else 256,
                              cache_type="q8_0")
            return ModelFit(choice, plan, True, "gpu", round(need_q8, 2))
        # б) точний KV у VRAM — коли q8_0 чомусь не підходить, але влазить
        if est_vram_gb(choice, ctx, FULL_OFFLOAD) <= vram_budget:
            plan = LaunchPlan(gpu_layers=FULL_OFFLOAD, ctx_size=ctx, threads=threads,
                              flash_attn="auto",
                              batch=512 if vram_budget >= 8 else 256)
            return ModelFit(choice, plan, True, "gpu",
                            round(est_vram_gb(choice, ctx, FULL_OFFLOAD), 2))
        # в) ваги на GPU, KV-кеш у RAM — контекст, який у VRAM не влазить
        #
        # Це ДОРОГО: заміряно 20.7 ток/с проти 31.7 для кешу у VRAM (−35%).
        # Тому в режимі «авто» (target_ctx = 0) сюди не йдемо: краще віддати
        # 16K на повній швидкості, ніж 32K на третину повільніше. У RAM
        # переходимо лише коли користувач ЯВНО попросив більший контекст.
        if target_ctx and choice.approx_gb + RUNTIME_OVERHEAD_GB <= vram_budget:
            need_ram = kv_cache_gb(choice, ctx) / 2 + RUNTIME_OVERHEAD_GB
            if need_ram <= ram_budget:
                plan = LaunchPlan(gpu_layers=FULL_OFFLOAD, ctx_size=ctx, threads=threads,
                                  flash_attn="auto", batch=256,
                                  cache_type="q8_0", kv_in_ram=True)
                return ModelFit(choice, plan, True, "gpu",
                                round(choice.approx_gb + RUNTIME_OVERHEAD_GB, 2))

    # 2. Часткове вивантаження: ваги в RAM, скільки шарів — на GPU.
    if choice.approx_gb + RUNTIME_OVERHEAD_GB <= ram_budget:
        ctx = _pick_ctx(choice, ram_budget, vram_budget)
        kv = kv_cache_gb(choice, ctx)
        vram_for_weights = max(0.0, vram_budget - RUNTIME_OVERHEAD_GB - kv * 0.5)
        share = vram_for_weights / max(choice.approx_gb, 0.01)
        layers = int(choice.layers * min(1.0, share))
        # Хоча б половина шарів на GPU — інакше сенсу в гібриді немає.
        if layers >= max(4, choice.layers // 3):
            plan = LaunchPlan(gpu_layers=layers, ctx_size=ctx, threads=threads,
                              flash_attn="auto", batch=256, cache_type="q8_0")
            needed = est_vram_gb(choice, ctx, layers)
            return ModelFit(choice, plan, False, "hybrid", round(needed, 2))

    # 3. Не влізає з прийнятним контекстом.
    ctx = MIN_CTX
    plan = LaunchPlan(gpu_layers=0, ctx_size=ctx, threads=threads,
                      flash_attn="off", batch=256, cache_type="q8_0")
    return ModelFit(choice, plan, False, "cpu", 0.0)


def _pick_ctx(choice: ModelChoice, ram_budget: float, vram_budget: float) -> int:
    """Найбільший контекст із драбини, який ще вміщається у бюджети."""
    for ctx in CTX_LADDER:
        if ctx < MIN_CTX:
            break
        kv = kv_cache_gb(choice, ctx)
        if vram_budget > 0:
            need_vram = RUNTIME_OVERHEAD_GB + kv + min(choice.approx_gb, vram_budget)
            if need_vram <= vram_budget:
                return ctx
        else:
            if choice.approx_gb + kv + RUNTIME_OVERHEAD_GB <= ram_budget:
                return ctx
    return MIN_CTX


def recommend(profile: HardwareProfile) -> ModelChoice:
    """Обрати найрозумнішу модель, яка працює з прийнятною швидкістю.

    Правило просте і передбачуване: повністю на GPU краще, ніж частково;
    частково краще, ніж на CPU. Усередині одного режиму беремо найбільшу
    модель. Так користувач отримує максимум якості без «повзучого» чату.
    """
    fitted = [(fit(profile, choice), choice) for choice in MODEL_CATALOG]

    for speed in ("gpu", "hybrid"):
        candidates = [choice for result, choice in fitted if result.speed == speed]
        if candidates:
            return candidates[-1]

    # Лише CPU: дуже велика модель на процесорі дає 1–2 токени за секунду,
    # тому обмежуємо розмір залежно від обсягу пам'яті.
    cap = 8.0 if profile.ram_budget_gb >= 24 else 4.0
    cpu_ok = [choice for result, choice in fitted if result.speed == "cpu" and choice.params_b <= cap]
    return cpu_ok[-1] if cpu_ok else MODEL_CATALOG[0]


def alternatives(profile: HardwareProfile, limit: int = 4) -> list[ModelChoice]:
    """Варіанти навколо рекомендованої моделі: менша, обрана, більша."""
    best = recommend(profile)
    index = MODEL_CATALOG.index(best)
    low = max(0, index - 1)
    window = list(MODEL_CATALOG[low: low + limit])
    return window or [best]


# ─────────────────────────────────────────────────────────────────────────────
# Поради щодо параметрів запуску
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LaunchPlan:
    """Параметри, з якими варто запустити llama-server для цього заліза."""

    gpu_layers: int
    ctx_size: int
    threads: int
    flash_attn: str = "auto"
    batch: int = 512
    parallel: int = 1
    #: Тип KV-кешу. ``f16`` — точно, ``q8_0`` — удвічі менше VRAM,
    #: ``q4_0`` — учетверо менше (помітна втрата якості на довгих файлах).
    cache_type: str = "f16"
    #: Тримати KV-кеш у системній RAM замість VRAM.
    #:
    #: Це головний спосіб збільшити контекст, коли VRAM обмаль: ваги
    #: лишаються на відеокарті (швидка генерація), а кеш живе в RAM
    #: (64 ГБ замість 12). Плата — трохи повільніше читання довгого
    #: промпту, зате контекст можна підняти утричі.
    kv_in_ram: bool = False

    def args(self) -> list[str]:
        args = [
            "--n-gpu-layers", str(self.gpu_layers),
            "--ctx-size", str(self.ctx_size),
            "--threads", str(self.threads),
            "--batch-size", str(self.batch),
            "--parallel", str(self.parallel),
            "--flash-attn", self.flash_attn,
        ]
        cache = (self.cache_type or "f16").strip().lower()
        if cache in ("q8_0", "q4_0", "q5_1", "q5_0", "f16", "bf16"):
            # Окремо K і V: llama.cpp приймає обидва типи.
            args.extend(["--cache-type-k", cache, "--cache-type-v", cache])
        if self.kv_in_ram:
            # KV-кеш не вивантажуємо у VRAM — він лишається у RAM.
            args.append("--no-kv-offload")
        return args

    def summary(self) -> str:
        """Людський підпис плану (для панелі хабу)."""
        mode = "GPU" if self.gpu_layers < 0 or self.gpu_layers >= 999 else (
            f"гібрид {self.gpu_layers} шарів" if self.gpu_layers else "CPU")
        cache = "KV у RAM" if self.kv_in_ram else f"KV {self.cache_type}"
        return f"{mode} · {self.ctx_size // 1024}K · {cache}"

    @property
    def vram_hint(self) -> float:
        """Скільки VRAM план має зайняти (без моделі — лише кеш і буфери).

        Потрібно для замірів і для пояснення користувачу, чому один режим
        повільніший за інший.
        """
        return RUNTIME_OVERHEAD_GB


#: Скільки контексту пробуємо, коли KV-кеш можна тримати в RAM.
#:
#: Обмежуємо не пам'яттю (її 64 ГБ), а швидкістю: після ~32K читання
#: промпту стає помітно довшим, а локальній моделі стільки не потрібно —
#: агент передає файли фрагментами.
CTX_LADDER_RAM = (32768, 24576, 16384)


def fit_ctx_for_ram(profile: HardwareProfile, choice: ModelChoice,
                    *, target_ctx: int = 0) -> tuple[int, str, bool]:
    """Підібрати контекст, який реально влізе, з огляду на RAM.

    Повертає ``(ctx, cache_type, kv_in_ram)``.

    Логіка — не «дати максимум», а «дати стільки, щоб не втратити швидкість»:

    1. Якщо ваги + KV(f16) влазять у VRAM — беремо як є (найшвидший режим).
    2. Інакше пробуємо стиснути KV до ``q8_0``: він удвічі менший, і
       контекст 16K влізе у 12 ГБ VRAM разом із вагами 14B.
    3. Якщо й це не влазить — лишаємо ваги у VRAM, а KV виносимо в RAM
       (``--no-kv-offload``): контекст виростає до десятків тисяч токенів
       коштом трохи повільнішого читання промпту.

    ``target_ctx`` — що хоче користувач (0 = якомога більше).
    """
    vram = profile.vram_budget_gb
    ram = profile.ram_budget_gb
    want = int(target_ctx or 0)
    ladder = [want] if want else list(CTX_LADDER_RAM)
    ladder = [ctx for ctx in ladder if ctx >= MIN_CTX] or [MIN_CTX]

    if vram <= 0:
        # Без GPU контекст у RAM — єдиний варіант; обмежуємо бюджетом RAM.
        for ctx in ladder:
            need = choice.approx_gb + kv_cache_gb(choice, ctx) + RUNTIME_OVERHEAD_GB
            if need <= ram:
                return ctx, "q8_0", False
        return MIN_CTX, "q8_0", False

    # 1. Точний KV повністю у VRAM.
    for ctx in ladder:
        need = choice.approx_gb + kv_cache_gb(choice, ctx) + RUNTIME_OVERHEAD_GB
        if need <= vram:
            return ctx, "f16", False
    # 2. Стиснутий KV (q8_0) у VRAM.
    for ctx in ladder:
        need = (choice.approx_gb + kv_cache_gb(choice, ctx) / 2
                + RUNTIME_OVERHEAD_GB)
        if need <= vram:
            return ctx, "q8_0", False
    # 3. KV у RAM: ваги (8.4 ГБ для 14B) лишаються на GPU, кеш — у системній.
    for ctx in ladder:
        need_ram = kv_cache_gb(choice, ctx) / 2 + RUNTIME_OVERHEAD_GB
        if need_ram <= ram:
            return ctx, "q8_0", True
    return MIN_CTX, "q8_0", True


def plan_for(profile: HardwareProfile, choice: ModelChoice) -> LaunchPlan:
    """Готовий план запуску (скорочення для fit(...).plan)."""
    return fit(profile, choice).plan


__all__ = [
    "CTX_LADDER_RAM",
    "FULL_OFFLOAD",
    "GpuInfo",
    "HardwareProfile",
    "LaunchPlan",
    "ModelChoice",
    "ModelFit",
    "MODEL_CATALOG",
    "alternatives",
    "detect",
    "est_vram_gb",
    "fit",
    "fit_ctx_for_ram",
    "kv_cache_gb",
    "plan_for",
    "recommend",
]
