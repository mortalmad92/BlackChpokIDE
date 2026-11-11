"""Runtime API BLACKCHPOK: єдина точка входу до рушія для решти IDE.

Ідея: і інтерфейс, і агент, і тести звертаються до одного об'єкта
:class:`NativeRuntime`, а не до ctypes-функцій напряму. Це дає:

* валідацію аргументів і зрозумілі помилки замість ``AttributeError``;
* контроль життєвого циклу моделі (одна модель у пам'яті);
* ліміт одночасних запитів і чергу замість «два декодування в одному
  контексті»;
* тайм-аути й скасування;
* логування кожного запиту з виміряними числами.

Назви операцій навмисно повторюють завдання (``list_models``,
``inspect_model``, ``load_model``, ``generate``, ``generate_stream``,
``cancel_generation``, ``tokenize``, ``detokenize``, ``count_tokens``,
``create_embeddings``, ``get_runtime_status``, ``get_gpu_status``,
``get_memory_status``, ``benchmark_model``).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from ..hardware import HardwareProfile, detect as detect_hardware
from . import inspect as inspect_mod
from ._bindings import NativeUnavailable
from .embeddings import EmbeddingService, EmbeddingUnavailable
from .engine import (
    EngineError,
    GenerationCancelled,
    GenerationResult,
    GenerationStats,
    LoadOptions,
    NativeEngine,
    StreamChunk,
)
from .manager import ModelEntry, ModelManager, ModelManagerError
from .sampling import SamplingParams

LOG = logging.getLogger("blackchpok.native.api")

#: Скільки запитів може чекати в черзі (решта — відмова з поясненням).
MAX_PENDING = 8
#: Типовий тайм-аут генерації (секунди).
DEFAULT_TIMEOUT = 600.0


class RuntimeError_(RuntimeError):
    """Помилка Runtime API."""


class RuntimeBusy(RuntimeError_):
    """Рушій зайнятий іншим запитом."""


@dataclass
class RequestStats:
    """Телеметрія одного виклику API."""

    operation: str
    started: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    ok: bool = True
    error: str = ""


class NativeRuntime:
    """Фасад рушія: моделі, генерація, вектори, статус, бенчмарк."""

    def __init__(self, *, manager: ModelManager | None = None,
                 engine: NativeEngine | None = None) -> None:
        self.manager = manager or ModelManager()
        self.engine = engine or NativeEngine()
        self._embedder: EmbeddingService | None = None
        self._requests: list[RequestStats] = []
        self._history_limit = 200
        self._pending = 0
        self._lock = threading.RLock()
        self._hardware: HardwareProfile | None = None
        self._hardware_at = 0.0
        self._generation: GenerationResult | None = None

    # ── залізо ────────────────────────────────────────────────────────────
    def hardware(self, *, refresh: bool = False) -> HardwareProfile:
        """Профіль заліза (кеш 60 с — ``nvidia-smi`` не безкоштовний)."""
        with self._lock:
            stale = (time.time() - self._hardware_at) > 60.0
            if self._hardware is None or refresh or stale:
                self._hardware = detect_hardware()
                self._hardware_at = time.time()
            return self._hardware

    def recommend(self) -> dict[str, Any]:
        """Що запускати на цьому залізі: модель, контекст, шари, batch."""
        from ..hardware import fit, recommend

        profile = self.hardware()
        choice = recommend(profile)
        plan = fit(profile, choice).plan
        return {
            "model": choice.label,
            "repo": choice.ref,
            "context": plan.ctx_size,
            "gpu_layers": plan.gpu_layers,
            "batch": plan.batch,
            "cache_type": plan.cache_type,
            "threads": plan.threads,
            "summary": plan.summary(),
            "hardware": profile.summary(),
        }

    # ── моделі ────────────────────────────────────────────────────────────
    def list_models(self, *, refresh: bool = True) -> dict[str, Any]:
        """Список локальних моделей із метаданими й прогнозами."""
        profile = self.hardware()
        summary = self.manager.summary(profile=profile) if refresh else {
            "folder": str(self.manager.folder),
            "count": 0, "total_gb": 0.0,
            "free_gb": 0.0, "models": [], "projectors": [],
        }
        summary["loaded"] = self.engine.model_path
        return summary

    def inspect_model(self, path_or_key: str) -> dict[str, Any]:
        """Детальні метадані моделі (без завантаження ваг)."""
        entry = self.manager.get(path_or_key)
        if entry is None:
            raise RuntimeError_(f"Модель не знайдено: {path_or_key}")
        report = inspect_mod.inspect(entry.path, profile=self.hardware())
        data = report.to_dict()
        data["entry"] = entry.to_dict()
        data["integrity"] = inspect_mod.verify_integrity(entry.path)
        return data

    def add_model(self, path: str, *, copy: bool = False) -> dict[str, Any]:
        return self.manager.add_local(path, copy=copy).to_dict()

    def delete_model(self, path_or_key: str, *, confirm: bool = False) -> dict[str, Any]:
        """Видалити модель; без ``confirm`` — відмова (файл не чіпаємо)."""
        if self.engine.model_path and \
                Path(self.engine.model_path).resolve() == Path(path_or_key).resolve():
            self.engine.unload()
        ok = self.manager.delete(path_or_key, confirm=confirm)
        return {"ok": ok, "confirmed": confirm, "path": path_or_key}

    def verify_model(self, path_or_key: str, *, expected_size: int = 0) -> dict[str, Any]:
        return self.manager.verify(path_or_key, expected_size=expected_size)

    def download_model(self, url: str, *, filename: str = "",
                       on_progress: Callable[[int, int], None] | None = None,
                       on_status: Callable[[str], None] | None = None,
                       cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
        if not str(url or "").startswith(("http://", "https://")):
            raise RuntimeError_("Адреса має починатися з http:// або https://")
        return self.manager.download(url, filename=filename, on_progress=on_progress,
                                     on_status=on_status, cancel=cancel)

    # ── життєвий цикл ─────────────────────────────────────────────────────
    @property
    def loaded(self) -> bool:
        return self.engine.loaded

    def load_model(self, path_or_key: str, *, ctx: int = 0, gpu_layers: int | None = None,
                   threads: int = 0, batch: int = 0, cache_type: str = "",
                   flash_attn: str = "", mmproj: str = "",
                   on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Завантажити модель із розумними типовими параметрами.

        Якщо параметри не задані, вони беруться з реальних метаданих моделі
        й поточного заліза (а не з «магічних» констант).
        """
        entry = self.manager.get(path_or_key)
        if entry is None:
            raise RuntimeError_(f"Модель не знайдено: {path_or_key}")
        report = inspect_mod.inspect(entry.path, profile=self.hardware(), ctx=ctx)
        options = LoadOptions(
            n_ctx=int(ctx or report.suggested_ctx or 4096),
            n_gpu_layers=int(report.suggested_gpu_layers if gpu_layers is None
                             else gpu_layers),
            n_batch=int(batch or report.suggested_batch or 512),
            n_ubatch=int(min(batch or report.suggested_batch or 512, 512)),
            n_threads=int(threads or report.suggested_threads or 0),
            flash_attn=flash_attn or "auto",
            cache_type_k=cache_type or report.kv_cache_type or "f16",
            cache_type_v=cache_type or report.kv_cache_type or "f16",
            offload_kqv=not report.kv_in_ram,
            mmproj_path=mmproj or entry.projector,
        )
        info = self.engine.load(entry.path, options, on_progress=on_progress)
        info["report"] = report.to_dict()
        self._embedder = EmbeddingService(
            self.engine,
            db_path=Path(self.manager.folder).parent / "neuromesh" / "vectors.db",
        )
        LOG.info("Модель у рушії: %s (ctx %s, GPU-шарів %s)",
                 entry.key, options.n_ctx, options.n_gpu_layers)
        return info

    def unload_model(self) -> dict[str, Any]:
        had = self.engine.unload()
        return {"unloaded": had}

    def switch_model(self, path_or_key: str, **kwargs: Any) -> dict[str, Any]:
        """Перемкнути модель: вивантажити поточну й завантажити нову."""
        self.engine.unload()
        return self.load_model(path_or_key, **kwargs)

    # ── генерація ─────────────────────────────────────────────────────────
    def generate(self, messages: list[dict] | str, *, params: dict | SamplingParams | None = None,
                 tools: list[dict] | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 on_text: Callable[[str], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Згенерувати відповідь (блокуюче) з тайм-аутом і телеметрією.

        Тайм-аут справді діє: він перетворюється у ``should_stop``, який
        рушій перевіряє на кожному токені й перериває обчислення. Раніше
        параметр приймався, але ігнорувався — тобто генерація могла
        тривати безкінечно, а виклик вважав, що захищений.
        """
        settings = self._params(params)
        deadline = (time.monotonic() + float(timeout)) if timeout and timeout > 0 else 0.0

        def _stop() -> bool:
            if should_stop is not None and should_stop():
                return True
            return bool(deadline) and time.monotonic() > deadline

        self._enter("generate")
        started = time.perf_counter()
        try:
            result = self.engine.generate(messages, params=settings, tools=tools,
                                         on_text=on_text, should_stop=_stop)
            self._generation = result
            payload = {
                "text": result.text,
                "tool_calls": result.tool_calls,
                "finish_reason": result.finish_reason,
                "stats": result.stats.to_dict(),
                "model": result.model,
            }
            if deadline and time.monotonic() > deadline:
                payload["timed_out"] = True
                payload["timeout_s"] = float(timeout)
            self._record("generate", started)
            return payload
        except EngineError as exc:
            self._record("generate", started, error=str(exc))
            raise
        finally:
            self._leave()

    def generate_stream(self, messages: list[dict] | str, *,
                        params: dict | SamplingParams | None = None,
                        tools: list[dict] | None = None,
                        timeout: float = DEFAULT_TIMEOUT,
                        should_stop: Callable[[], bool] | None = None,
                        known_tools: Iterable[str] | None = None
                        ) -> Iterator[dict[str, Any]]:
        """Потокова генерація; кожен елемент — словник для JSON-відповіді.

        Два захисти, яких раніше не було:

        * ``timeout`` — раніше потоковий шлях приймав лише ``should_stop``,
          тобто агент (який ходить саме через ``chat_stream``) міг чекати
          вічно. Тепер тайм-аут перетворюється в ``should_stop`` так само,
          як у блокуючому :meth:`generate`.
        * зняття ``_pending`` при ПОКИНУТОМУ генераторі. ``_enter``
          збільшує лічильник, а ``finally`` спрацьовує лише коли генератор
          дочитано або закрито. Якщо викликач кинув ітерацію (``break``,
          виняток, скасування) і не викликав ``close()``, лічильник
          лишався більше нуля **назавжди** — і ``bridge.busy()`` вічно
          повертав ``True``. Тепер ``GeneratorExit`` теж знімає лічильник.
        """
        settings = self._params(params)
        deadline = (time.monotonic() + float(timeout)) if timeout and timeout > 0 else 0.0

        def _stop() -> bool:
            if should_stop is not None and should_stop():
                return True
            return bool(deadline) and time.monotonic() > deadline

        self._enter("generate_stream")
        started = time.perf_counter()
        finished = False
        try:
            for chunk in self.engine.generate_stream(
                    messages, params=settings, tools=tools, should_stop=_stop,
                    known_tools=known_tools):
                if chunk.done:
                    finished = True
                    self._generation = GenerationResult(
                        text="", tokens=chunk.tokens, stats=chunk.stats,
                        finish_reason=chunk.finish_reason,
                        tool_calls=chunk.tool_calls,
                        model=self.engine.model_path)
                    self._record("generate_stream", started)
                    payload = {
                        "done": True,
                        "finish_reason": chunk.finish_reason,
                        "stats": chunk.stats.to_dict(),
                        "tool_calls": chunk.tool_calls,
                        "tokens": chunk.tokens,
                    }
                    if deadline and time.monotonic() > deadline:
                        payload["timed_out"] = True
                        payload["timeout_s"] = float(timeout)
                    yield payload
                else:
                    yield {"done": False, "text": chunk.text,
                           "reasoning": chunk.reasoning}
        except EngineError as exc:
            self._record("generate_stream", started, error=str(exc))
            raise
        except GeneratorExit:
            # Викликач покинув ітерацію — це нормальний шлях скасування,
            # а не помилка. Фіксуємо в телеметрії й виходимо.
            if not finished:
                self._record("generate_stream", started, error="перервано")
            raise
        finally:
            self._leave()

    def cancel_generation(self) -> dict[str, Any]:
        """Скасувати поточну генерацію (рушій зупинить обчислення)."""
        context = self.engine.context
        if context is None:
            return {"cancelled": False, "reason": "модель не завантажена"}
        context.cancel()
        return {"cancelled": True}

    # ── токени ────────────────────────────────────────────────────────────
    def tokenize(self, text: str, *, add_special: bool = True) -> dict[str, Any]:
        tokenizer = self._tokenizer()
        tokens = tokenizer.encode(text, add_special=add_special)
        return {"tokens": tokens, "count": len(tokens),
                "pieces": [tokenizer.token_text(token, skip_special=False)
                           for token in tokens[:512]]}

    def detokenize(self, tokens: Sequence[int], *, skip_special: bool = True) -> dict[str, Any]:
        tokenizer = self._tokenizer()
        return {"text": tokenizer.decode([int(token) for token in tokens],
                                        skip_special=skip_special)}

    def count_tokens(self, text: str, *, add_special: bool = False) -> dict[str, Any]:
        """Точний підрахунок токенів моделі (не оцінка по символах)."""
        engine = self.engine
        model = getattr(engine, "model", None)
        tokenizer = getattr(model, "tokenizer", None) if model else None
        if tokenizer is None:
            return {"count": 0, "exact": False,
                    "reason": "модель не завантажена — точний підрахунок неможливий"}
        return {"count": tokenizer.count(text, add_special=add_special), "exact": True,
                "vocab": tokenizer.size}

    def _tokenizer(self):
        model = getattr(self.engine, "model", None)
        tokenizer = getattr(model, "tokenizer", None) if model else None
        if tokenizer is None:
            raise RuntimeError_("Спочатку завантаж модель: tokenizer доступний лише з нею.")
        return tokenizer

    # ── embeddings ────────────────────────────────────────────────────────
    def create_embeddings(self, texts: Sequence[str], *,
                          use_cache: bool = True) -> dict[str, Any]:
        """Локальні вектори (без зовнішнього сервера)."""
        if isinstance(texts, str):
            texts = [texts]
        if self._embedder is None:
            if not self.engine.loaded:
                raise RuntimeError_("Для векторів потрібна завантажена модель.")
            self._embedder = EmbeddingService(self.engine)
        try:
            vectors = self._embedder.encode(list(texts), use_cache=use_cache)
        except EmbeddingUnavailable as exc:
            raise RuntimeError_(str(exc)) from exc
        return {
            "vectors": vectors,
            "count": len(vectors),
            "dim": len(vectors[0]) if vectors else 0,
            "model": self._embedder.model_tag,
            "stats": self._embedder.stats(),
        }

    @property
    def embedder(self) -> EmbeddingService | None:
        return self._embedder

    # ── статус ────────────────────────────────────────────────────────────
    def get_runtime_status(self) -> dict[str, Any]:
        """Повний стан рушія: модель, контекст, KV, швидкості, помилки."""
        info = self.engine.describe()
        info["library"] = self.engine.library_info()
        info["models"] = {"count": self.manager.summary()["count"],
                          "folder": str(self.manager.folder)}
        info["requests"] = [self._as_dict(item) for item in self._requests[-20:]]
        info["pending"] = self._pending
        return info

    def get_gpu_status(self) -> dict[str, Any]:
        """GPU: пристрої ggml + реальна VRAM через nvidia-smi."""
        info = self.engine.library_info()
        devices = info.get("devices", [])
        live = self._nvidia_smi()
        return {
            "devices": devices,
            "gpu_offload": bool(info.get("supports_gpu_offload")),
            "nvidia": live,
            "loaded_gpu_layers": (self.engine.model.options.n_gpu_layers
                                  if self.engine.model else 0),
        }

    @staticmethod
    def _nvidia_smi() -> list[dict[str, Any]]:
        """Живі дані NVIDIA (зайнята/вільна VRAM, завантаження)."""
        command = ["nvidia-smi",
                   "--query-gpu=name,memory.total,memory.used,memory.free,"
                   "utilization.gpu,temperature.gpu,driver_version",
                   "--format=csv,noheader,nounits"]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return []
        if completed.returncode != 0:
            return []
        gpus: list[dict[str, Any]] = []
        for line in (completed.stdout or "").splitlines():
            parts = [item.strip() for item in line.split(",")]
            if len(parts) < 7:
                continue
            try:
                gpus.append({
                    "name": parts[0],
                    "vram_total_mb": float(parts[1]),
                    "vram_used_mb": float(parts[2]),
                    "vram_free_mb": float(parts[3]),
                    "utilization_percent": float(parts[4]),
                    "temperature_c": float(parts[5]),
                    "driver": parts[6],
                })
            except ValueError:
                continue
        return gpus

    def library_info(self) -> dict[str, Any]:
        """Версія, системна інформація, пристрої — без завантаження моделі."""
        return self.engine.library_info()

    def get_memory_status(self) -> dict[str, Any]:
        """RAM процесу й системи + оцінка KV-кешу."""
        rss_mb = 0.0
        try:
            import resource              # type: ignore[import-not-found]

            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except ImportError:
            try:
                import ctypes
                from ctypes import wintypes

                class Counters(ctypes.Structure):
                    _fields_ = [("cb", wintypes.DWORD),
                                ("PageFaultCount", wintypes.DWORD),
                                ("PeakWorkingSetSize", ctypes.c_size_t),
                                ("WorkingSetSize", ctypes.c_size_t),
                                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                                ("PagefileUsage", ctypes.c_size_t),
                                ("PeakPagefileUsage", ctypes.c_size_t)]

                kernel32 = ctypes.windll.kernel32            # type: ignore[attr-defined]
                psapi = ctypes.windll.psapi                  # type: ignore[attr-defined]
                # Псевдо-дескриптор процесу дорівнює -1; без явного
                # ``restype=HANDLE`` ctypes обрізає його до 32 біт і виклик
                # ``GetProcessMemoryInfo`` повертає 0 (тобто «0 МБ»).
                kernel32.GetCurrentProcess.restype = wintypes.HANDLE
                psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                                       ctypes.c_void_p,
                                                       wintypes.DWORD]
                psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
                counters = Counters()
                counters.cb = ctypes.sizeof(Counters)
                handle = kernel32.GetCurrentProcess()
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters),
                                              counters.cb):
                    rss_mb = counters.WorkingSetSize / 1048576.0
            except Exception:            # noqa: BLE001
                rss_mb = 0.0
        profile = self.hardware()
        kv = {}
        if self.engine.context is not None and self.engine.context.cache is not None:
            kv = self.engine.context.cache.stats()
        return {
            "process_rss_mb": round(rss_mb, 1),
            "system_total_gb": profile.ram_total_gb,
            "system_available_gb": profile.ram_available_gb,
            "kv": kv,
            "context": self.engine.context.n_ctx if self.engine.context else 0,
        }

    def benchmark_model(self, *, runs: int = 2, max_tokens: int = 64,
                        prompt: str = "") -> dict[str, Any]:
        """Реальний бенчмарк завантаженої моделі."""
        if not self.engine.loaded:
            raise RuntimeError_("Спочатку завантаж модель.")
        kwargs: dict[str, Any] = {"runs": max(1, runs), "max_tokens": max(1, max_tokens)}
        if prompt:
            kwargs["prompt"] = prompt
        result = self.engine.benchmark(**kwargs)
        result["gpu"] = self.get_gpu_status().get("nvidia", [])
        result["memory"] = self.get_memory_status()
        return result

    # ── службове ──────────────────────────────────────────────────────────
    def shut_down(self) -> None:
        """Зупинити рушій (викликається при виході з IDE)."""
        try:
            self.engine.unload()
        except Exception:                            # noqa: BLE001
            LOG.debug("Вивантаження моделі при виході впало", exc_info=True)

    def _params(self, params: dict | SamplingParams | None) -> SamplingParams:
        if isinstance(params, SamplingParams):
            return params.normalised()
        if isinstance(params, dict):
            return SamplingParams.from_dict(params)
        return SamplingParams().normalised()

    def _enter(self, operation: str) -> None:
        with self._lock:
            if self._pending >= MAX_PENDING:
                raise RuntimeBusy(
                    f"Черга запитів переповнена ({MAX_PENDING}). "
                    "Зачекай завершення поточної генерації.")
            self._pending += 1

    def _leave(self) -> None:
        with self._lock:
            self._pending = max(0, self._pending - 1)

    def _record(self, operation: str, started: float, *, error: str = "") -> None:
        """Записати телеметрію запиту (і успіхи, і помилки).

        Раніше сюди потрапляли ЛИШЕ помилки (виклик був тільки в гілці
        ``except``), тому панель показувала «останній запит» лише тоді,
        коли щось зламалось — успішні генерації в журналі не з'являлись.
        """
        stats = RequestStats(operation=operation, ok=not error, error=error,
                            duration_ms=round((time.perf_counter() - started) * 1000.0, 1))
        with self._lock:
            self._requests.append(stats)
            if len(self._requests) > self._history_limit:
                self._requests = self._requests[-self._history_limit:]

    @staticmethod
    def _as_dict(stats: RequestStats) -> dict[str, Any]:
        return {
            "operation": stats.operation,
            "ok": stats.ok,
            "error": stats.error,
            "duration_ms": stats.duration_ms,
            "at": stats.started,
        }


__all__ = [
    "DEFAULT_TIMEOUT",
    "MAX_PENDING",
    "NativeRuntime",
    "RequestStats",
    "RuntimeBusy",
    "RuntimeError_",
]
