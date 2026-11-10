"""Ядро власного рушія: завантаження моделі, генерація, streaming, скасування.

Це серце BLACKCHPOK NATIVE INFERENCE ENGINE. Тут немає жодного зовнішнього
сервера: модель вантажиться в пам'ять процесу IDE, а токени генеруються
викликами ``llama_decode``.

Ключові рішення, які варто знати при читанні коду:

* **Один контекст на модель.** llama.cpp не дає паралелити декодування в
  межах одного контексту, тому всі запити серіалізуються ``threading.Lock``.
  Паралелізм дається іншим: генерація крутиться у фоновому потоці, а UI
  отримує токени через callback.
* **Скасування — через abort callback рушія.** Просте «перестати читати
  потік» не зупиняє обчислення: llama_decode вже всередині. Тому
  ставимо колбек, який повертає ``True``, і рушій сам перериває граф.
* **KV-кеш переиспользується.** Другий запит у тому ж діалозі декодує
  тільки новий хвіст (див. :mod:`.kv`).
* **Нічого не вигадуємо про GPU.** Шари offload-яться рівно на стільки,
  скільки попросив виклик; фактичне використання VRAM показує телеметрія
  ``nvidia-smi``, а не наши слова.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from . import _abi, gguf, inspect as inspect_mod
from ._bindings import LlamaLibrary, NativeUnavailable, load_library
from .kv import CacheManager
from .sampling import (
    GrammarUnsupported,
    SamplerChain,
    SamplingParams,
    StopMatcher,
    flash_attn_value,
)
from .tokenizer import Tokenizer

LOG = logging.getLogger("blackchpok.native.engine")

#: Скільки разів пробуємо зменшити контекст, якщо рушій не зміг виділити пам'ять.
OOM_RETRIES = 3
#: Мінімальний контекст, нижче якого не опускаємось.
MIN_CTX = 512


class EngineError(RuntimeError):
    """Помилка рушія: модель не завантажена, декодування зірвалось тощо."""


class GenerationCancelled(EngineError):
    """Генерацію скасував користувач."""


@dataclass
class LoadOptions:
    """Параметри завантаження моделі в пам'ять."""

    n_ctx: int = 4096
    n_gpu_layers: int = 0
    n_batch: int = 512
    n_ubatch: int = 512
    n_threads: int = 0
    n_threads_batch: int = 0
    flash_attn: str = "auto"
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    offload_kqv: bool = True
    mmproj_path: str = ""
    embeddings: bool = False
    use_mmap: bool = True
    use_mlock: bool = False
    #: Тримати інструменти для localhost: доки вантажиться модель, IDE може
    #: показати прогрес, а не «зависнути».
    verify_tensors: bool = False
    #: MTP-шари (speculative) — вмикаємо лише якщо модель їх має.
    load_mtp: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_ctx": self.n_ctx,
            "n_gpu_layers": self.n_gpu_layers,
            "n_batch": self.n_batch,
            "n_ubatch": self.n_ubatch,
            "n_threads": self.n_threads,
            "n_threads_batch": self.n_threads_batch,
            "flash_attn": self.flash_attn,
            "cache_type_k": self.cache_type_k,
            "cache_type_v": self.cache_type_v,
            "offload_kqv": self.offload_kqv,
            "mmproj_path": self.mmproj_path,
            "embeddings": self.embeddings,
        }


@dataclass
class GenerationStats:
    """Виміряні числа одного запиту (не оцінки)."""

    prompt_tokens: int = 0
    generated_tokens: int = 0
    prefill_ms: float = 0.0
    decode_ms: float = 0.0
    total_ms: float = 0.0
    cached_tokens: int = 0
    cancelled: bool = False
    stopped_by: str = ""

    @property
    def tokens_per_second(self) -> float:
        if self.decode_ms <= 0 or self.generated_tokens <= 0:
            return 0.0
        return self.generated_tokens / (self.decode_ms / 1000.0)

    @property
    def prompt_tokens_per_second(self) -> float:
        fresh = max(0, self.prompt_tokens - self.cached_tokens)
        if self.prefill_ms <= 0 or fresh <= 0:
            return 0.0
        return fresh / (self.prefill_ms / 1000.0)

    @property
    def time_to_first_token_ms(self) -> float:
        return self.prefill_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "generated_tokens": self.generated_tokens,
            "prefill_ms": round(self.prefill_ms, 1),
            "decode_ms": round(self.decode_ms, 1),
            "total_ms": round(self.total_ms, 1),
            "cached_tokens": self.cached_tokens,
            "tokens_per_second": round(self.tokens_per_second, 2),
            "prompt_tokens_per_second": round(self.prompt_tokens_per_second, 2),
            "time_to_first_token_ms": round(self.time_to_first_token_ms, 1),
            "cancelled": self.cancelled,
            "stopped_by": self.stopped_by,
        }


@dataclass
class GenerationResult:
    """Повний результат генерації."""

    text: str = ""
    tokens: list[int] = field(default_factory=list)
    stats: GenerationStats = field(default_factory=GenerationStats)
    finish_reason: str = "stop"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tokens": self.tokens,
            "stats": self.stats.to_dict(),
            "finish_reason": self.finish_reason,
            "tool_calls": self.tool_calls,
            "model": self.model,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Завантажена модель
# ─────────────────────────────────────────────────────────────────────────────

class LoadedModel:
    """Модель у пам'яті + її словник і шаблон чату.

    Один екземпляр обслуговує один контекст. Перемикання моделі означає
    ``unload`` цієї та ``load`` нової — інакше VRAM/RAM подвоюються.
    """

    def __init__(self, lib: LlamaLibrary, path: Path, options: LoadOptions,
                 *, report: inspect_mod.ModelReport | None = None) -> None:
        self.lib = lib
        self.path = Path(path)
        self.options = options
        self.report = report
        self.handle = 0
        self.vocab = 0
        self.tokenizer: Tokenizer | None = None
        self.load_ms = 0.0
        self.loaded_at = 0.0
        self._load()

    # ── завантаження ──────────────────────────────────────────────────────
    def _load(self) -> None:
        lib = self.lib
        params = lib.llama_model_default_params()
        # ``-1`` в llama.cpp означає «усі шари + вихідний шар». Значення
        # рівне ``layer_count`` кладе на GPU лише блоки трансформера й
        # лишає lm_head на CPU — це помітно повільніше (25.6 проти 31.2
        # ток/с для 14B Q4_K_M). Тому нормалізуємо «всі шари» у ``-1``.
        layers = int(self.options.n_gpu_layers)
        if layers == 0:
            params.n_gpu_layers = 0
        elif layers < 0:
            params.n_gpu_layers = -1
        elif self.report is not None and self.report.layer_count and \
                layers >= self.report.layer_count:
            params.n_gpu_layers = -1
        else:
            params.n_gpu_layers = layers
        params.use_extra_bufts = True
        params.check_tensors = bool(self.options.verify_tensors)
        params.load_mtp = bool(self.options.load_mtp)
        params.load_mode = (_abi.LOAD_MODE["mmap"] if self.options.use_mmap
                            else _abi.LOAD_MODE["none"])
        if self.options.use_mlock:
            params.load_mode = _abi.LOAD_MODE["mmap_mlock"]
        started = time.perf_counter()
        handle = lib.llama_model_load_from_file(str(self.path).encode("utf-8"), params)
        self.load_ms = (time.perf_counter() - started) * 1000.0
        if not handle:
            raise EngineError(
                f"Рушій не зміг завантажити модель: {self.path.name}. "
                "Перевір цілісність файлу й вільну пам'ять.")
        self.handle = handle
        self.vocab = lib.llama_model_get_vocab(handle)
        self.tokenizer = Tokenizer(lib, self.vocab)
        self.loaded_at = time.time()

    # ── інформація ────────────────────────────────────────────────────────
    def describe(self) -> str:
        buffer = ctypes.create_string_buffer(512)
        self.lib.llama_model_desc(self.handle, buffer, 512)
        return buffer.value.decode("utf-8", "replace")

    @property
    def parameter_count(self) -> int:
        return int(self.lib.llama_model_n_params(self.handle))

    @property
    def layer_count(self) -> int:
        return int(self.lib.llama_model_n_layer(self.handle))

    @property
    def context_train(self) -> int:
        return int(self.lib.llama_model_n_ctx_train(self.handle))

    @property
    def chat_template(self) -> str:
        raw = self.lib.llama_model_chat_template(self.handle, None)
        return (raw or b"").decode("utf-8", "replace")

    def meta(self) -> dict[str, str]:
        """Метадані з рушія (не з файлу) — для діагностики."""
        lib = self.lib
        count = int(lib.llama_model_meta_count(self.handle))
        result: dict[str, str] = {}
        key_buffer = ctypes.create_string_buffer(256)
        value_buffer = ctypes.create_string_buffer(4096)
        for index in range(min(count, 200)):
            if lib.llama_model_meta_key_by_index(self.handle, index, key_buffer,
                                                 len(key_buffer)) < 0:
                continue
            if lib.llama_model_meta_val_str_by_index(self.handle, index, value_buffer,
                                                     len(value_buffer)) < 0:
                continue
            key = key_buffer.value.decode("utf-8", "replace")
            result[key] = value_buffer.value.decode("utf-8", "replace")
        return result

    def free(self) -> None:
        if self.handle:
            self.lib.llama_model_free(self.handle)
            self.handle = 0
            self.vocab = 0
            self.tokenizer = None

    def __del__(self) -> None:                       # pragma: no cover - страховка
        try:
            self.free()
        except Exception:                            # noqa: BLE001
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Контекст (одна сесія декодування)
# ─────────────────────────────────────────────────────────────────────────────

class EngineContext:
    """Контекст декодування: KV-кеш, потоки, скасування."""

    def __init__(self, model: LoadedModel) -> None:
        self.model = model
        self.lib = model.lib
        self.options = model.options
        self.handle = 0
        self.cache: CacheManager | None = None
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._aborted = False
        # Тримаємо посилання на C-колбек: інакше Python збере збирач сміття,
        # і рушій викличе звільнену пам'ять.
        self._abort_cb = _AbortCallback(self)
        self._create()

    def _create(self) -> None:
        lib = self.lib
        options = self.options
        ctx_params = lib.llama_context_default_params()
        ctx_params.n_ctx = int(options.n_ctx)
        ctx_params.n_batch = int(options.n_batch)
        ctx_params.n_ubatch = int(min(options.n_ubatch, options.n_batch))
        ctx_params.n_seq_max = 1
        ctx_params.n_threads = int(options.n_threads or max(1, os.cpu_count() or 4))
        ctx_params.n_threads_batch = int(options.n_threads_batch or ctx_params.n_threads)
        ctx_params.flash_attn_type = flash_attn_value(options.flash_attn)
        ctx_params.type_k = _abi.GGML_TYPE.get(options.cache_type_k, _abi.GGML_TYPE["f16"])
        ctx_params.type_v = _abi.GGML_TYPE.get(options.cache_type_v, _abi.GGML_TYPE["f16"])
        ctx_params.offload_kqv = bool(options.offload_kqv)
        ctx_params.embeddings = bool(options.embeddings)
        ctx_params.no_perf = False
        handle = lib.llama_init_from_model(self.model.handle, ctx_params)
        if not handle:
            raise EngineError(
                f"Не вдалось створити контекст на {options.n_ctx} токенів. "
                "Спробуй менший контекст або менший offload на GPU.")
        self.handle = handle
        self.cache = CacheManager(lib, handle, capacity=int(options.n_ctx))
        lib.llama_set_abort_callback(handle, self._abort_cb.pointer, None)

    # ── властивості ───────────────────────────────────────────────────────
    @property
    def n_ctx(self) -> int:
        return int(self.lib.llama_n_ctx(self.handle))

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set() or self._aborted

    def cancel(self) -> None:
        """Попросити рушій зупинити обчислення."""
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()
        self._aborted = False

    # ── декодування ───────────────────────────────────────────────────────
    def decode(self, tokens: list[int], *, start_pos: int = 0,
               last_logits: bool = True) -> bool:
        """Декодувати пакет токенів; ``False`` — скасовано."""
        if not tokens:
            return True
        batch_capacity = int(self.lib.llama_n_batch(self.handle)) or len(tokens)
        position = start_pos
        total = len(tokens)
        offset = 0
        while offset < total:
            chunk = tokens[offset:offset + batch_capacity]
            end = offset + len(chunk) >= total
            if not self._decode_chunk(chunk, position, last_logits=last_logits and end):
                return False
            position += len(chunk)
            offset += len(chunk)
        return True

    def _decode_chunk(self, tokens: list[int], position: int, *,
                      last_logits: bool) -> bool:
        lib = self.lib
        count = len(tokens)
        batch = lib.llama_batch_init(count, 0, 1)
        if not batch.token:
            raise EngineError("Не вдалось виділити пакет токенів.")
        try:
            for index, token in enumerate(tokens):
                batch.token[index] = token
                batch.pos[index] = position + index
                batch.n_seq_id[index] = 1
                batch.seq_id[index][0] = 0
                batch.logits[index] = 1 if (last_logits and index == count - 1) else 0
            batch.n_tokens = count
            code = int(lib.llama_decode(self.handle, batch))
        finally:
            lib.llama_batch_free(batch)
        if code == 0:
            return True
        if code == _abi.DECODE_ABORTED or self.cancelled:
            self._aborted = True
            return False
        raise EngineError(
            f"Декодування не вдалось (код {code}). Можливо, контекст переповнено "
            f"або бракує пам'яті.")

    def clear_cache(self) -> None:
        if self.cache is not None:
            self.cache.clear()

    def free(self) -> None:
        if self.handle:
            self.lib.llama_free(self.handle)
            self.handle = 0
            self.cache = None

    def __del__(self) -> None:                       # pragma: no cover
        try:
            self.free()
        except Exception:                            # noqa: BLE001
            pass


class _AbortCallback:
    """C-колбек скасування: доки Python-функція живе, рушій її викликає."""

    _PROTO = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)

    def __init__(self, context: EngineContext) -> None:
        self._context = context

        def _trampoline(_data: int) -> bool:          # noqa: ANN001 - C-сигнатура
            try:
                return bool(context.cancelled)
            except Exception:                        # noqa: BLE001 - не маємо падати в C
                return True

        self._callback = self._PROTO(_trampoline)

    @property
    def pointer(self) -> int:
        return ctypes.cast(self._callback, ctypes.c_void_p).value or 0


# ─────────────────────────────────────────────────────────────────────────────
# Фасад рушія
# ─────────────────────────────────────────────────────────────────────────────

class NativeEngine:
    """Єдина точка входу до рушія: load / generate / stream / embeddings.

    Приклад:

        engine = NativeEngine()
        info = engine.load("model.gguf", LoadOptions(n_ctx=8192, n_gpu_layers=99))
        for chunk in engine.generate_stream([{"role": "user", "content": "Привіт"}]):
            print(chunk.text)
    """

    def __init__(self) -> None:
        self._lib: LlamaLibrary | None = None
        self.model: LoadedModel | None = None
        self.context: EngineContext | None = None
        self._lock = threading.RLock()
        self._formatter: Any = None
        self._stats = {
            "loads": 0, "unloads": 0, "generations": 0,
            "tokens_generated": 0, "tokens_prompted": 0,
        }
        self.last_error = ""

    # ── бібліотека ────────────────────────────────────────────────────────
    @property
    def lib(self) -> LlamaLibrary:
        if self._lib is None:
            self._lib = load_library()
        return self._lib

    @property
    def available(self) -> bool:
        """Чи є рушій і чи він уміє GPU offload."""
        try:
            return bool(self.lib)
        except (NativeUnavailable, OSError):
            return False

    def library_info(self) -> dict[str, Any]:
        """Версія, системна інформація, пристрої — без завантаження моделі."""
        try:
            lib = self.lib
        except (NativeUnavailable, OSError) as exc:
            return {"ok": False, "error": str(exc), "devices": []}
        return {
            "ok": True,
            "version": lib.version(),
            "path": str(lib.path),
            "system": lib.system_info(),
            "supports_gpu_offload": lib.supports_gpu_offload,
            "devices": [device.to_dict() for device in lib.devices],
        }

    # ── життєвий цикл моделі ──────────────────────────────────────────────
    @property
    def loaded(self) -> bool:
        return self.model is not None and self.context is not None

    @property
    def model_path(self) -> str:
        return str(self.model.path) if self.model else ""

    def load(self, path: str | Path, options: LoadOptions | None = None, *,
             on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Завантажити модель; попередню вивантажити.

        Якщо рушій не зміг виділити пам'ять (OOM), контекст зменшується
        вдвічі й спроба повторюється — це краще, ніж показати користувачу
        помилку там, де вистачить меншого вікна.
        """
        target = Path(path)
        if not target.exists():
            raise EngineError(f"Файл моделі не знайдено: {target}")
        settings = options or LoadOptions()
        lib = self.lib
        if settings.n_ctx <= 0:
            settings.n_ctx = 4096
        if not settings.n_threads:
            settings.n_threads = max(2, min(os.cpu_count() or 4, 16))
            settings.n_threads_batch = settings.n_threads

        with self._lock:
            self.unload()
            report = None
            try:
                report = inspect_mod.inspect(target)
                if not report.layer_count and settings.n_gpu_layers:
                    LOG.debug("Немає метаданих шарів — offload лишаємо як є")
                if settings.n_ctx > (report.context_train or settings.n_ctx):
                    LOG.info("Запрошений контекст %d > тренувального %d",
                             settings.n_ctx, report.context_train)
            except gguf.GgufError as exc:
                LOG.warning("Метадані не прочитані: %s", exc)

            last_error: Exception | None = None
            attempt = settings.n_ctx
            for attempt_index in range(OOM_RETRIES):
                try:
                    if on_progress:
                        on_progress(
                            f"Завантажую модель у пам'ять "
                            f"({settings.n_gpu_layers} шарів на GPU, ctx {attempt})…")
                    model = LoadedModel(lib, target, _replace_ctx(settings, attempt),
                                        report=report)
                    context = EngineContext(model)
                    self.model, self.context = model, context
                    self._stats["loads"] += 1
                    self._formatter = None
                    info = self.describe()
                    LOG.info("Модель завантажена за %.1f с: %s",
                             model.load_ms / 1000.0, info["description"])
                    return info
                except (EngineError, NativeUnavailable) as exc:
                    last_error = exc
                    self.model = self.context = None
                    gc.collect()
                    if attempt_index + 1 >= OOM_RETRIES or attempt <= MIN_CTX:
                        break
                    shrunk = max(MIN_CTX, attempt // 2)
                    LOG.warning("Не вдалось з ctx %d: %s — пробую %d",
                                attempt, exc, shrunk)
                    if on_progress:
                        on_progress(f"Бракує пам'яті — пробую контекст {shrunk}.")
                    attempt = shrunk
            self.last_error = str(last_error or "невідома помилка")
            raise EngineError(f"Модель не завантажилась: {last_error}")

    def unload(self) -> bool:
        """Вивантажити модель і звільнити пам'ять.

        ── ЧОМУ НЕ ЛИШЕ ``self._lock`` ─────────────────────────────────────
        Генерація виконується у ФОНОВОМУ потоці агента й тримає
        ``context._lock`` (див. ``generate_stream`` і ``_decode_chunk``), а
        не ``engine._lock``. Тому ``unload`` із головного потоку (закриття
        вікна, простій, зміна моделі) звільняв контекст ПІД ЧАС декодування:

            D:/a/llama.cpp/src/llama-kv-cache.cpp:735:
            GGML_ASSERT(seq_id >= 0 && (size_t) seq_id < seq_to_stream.size())
            failed

        Це аварія ВСЬОГО процесу (0xC0000409), не виняток Python: вона
        вбивала IDE під час автономного режиму. Перевірено faulthandler-ом:
        потік ``Thread-13 (_run)`` у ``_decode_chunk`` і головний потік у
        ``EngineContext.free`` одночасно.

        Тепер порядок такий:

        1. просимо генерацію зупинитись (``cancel``) — інакше чекали б
           повний хід;
        2. беремо ``context._lock`` — дочікуємось, поки поточний
           ``llama_decode`` завершиться;
        3. лише тоді звільняємо.

        Порядок блокувань узгоджений зі всіма іншими місцями:
        ``engine._lock`` → ``context._lock``.
        """
        with self._lock:
            context = self.context
            model = self.model
            if context is not None:
                # 1. Зупинити роботу, яка вже йде.
                try:
                    context.cancel()
                except Exception:                  # noqa: BLE001
                    LOG.debug("Скасування перед вивантаженням не вдалось",
                              exc_info=True)
                # 2. Дочекатись завершення поточного декодування.
                lock = getattr(context, "_lock", None)
                if lock is not None:
                    with lock:
                        context.free()
                else:
                    context.free()
            if model is not None:
                model.free()
                self._stats["unloads"] += 1
            had = model is not None
            self.model = None
            self.context = None
            self._formatter = None
            if had:
                gc.collect()
            return had

    def describe(self) -> dict[str, Any]:
        """Опис завантаженої моделі (фактичні числа з рушія)."""
        model = self.model
        context = self.context
        if model is None or context is None:
            return {"loaded": False}
        tokenizer = model.tokenizer
        formatter = self.formatter
        return {
            "loaded": True,
            "path": str(model.path),
            "description": model.describe(),
            "parameters": model.parameter_count,
            "parameters_b": round(model.parameter_count / 1e9, 2),
            "layers": model.layer_count,
            "context_train": model.context_train,
            "context_actual": context.n_ctx,
            "vocab": tokenizer.size if tokenizer else 0,
            "chat_template": bool(model.chat_template),
            "uses_builtin_template": bool(getattr(formatter, "uses_builtin_template", False)),
            "native_tools": self.supports_native_tools,
            "gpu_layers": model.options.n_gpu_layers,
            "cache_type": model.options.cache_type_v,
            "flash_attn": model.options.flash_attn,
            "threads": model.options.n_threads,
            "load_ms": round(model.load_ms, 1),
            "kv": context.cache.stats() if context.cache else {},
        }

    # ── шаблон чату ───────────────────────────────────────────────────────
    @property
    def formatter(self):
        """Форматер чату для завантаженої моделі (створюється один раз)."""
        if self._formatter is None and self.model is not None:
            from .chatfmt import ChatFormatter

            self._formatter = ChatFormatter(self.lib, self.model.handle)
        return self._formatter

    @property
    def supports_native_tools(self) -> bool:
        from .chatfmt import has_native_tool_support

        model = self.model
        if model is None:
            return False
        return has_native_tool_support(model.chat_template)

    def render_chat(self, messages: list[dict], *,
                    add_assistant: bool = True) -> str:
        formatter = self.formatter
        if formatter is None:
            raise EngineError("Модель не завантажена.")
        return formatter.render(messages, add_assistant=add_assistant)

    # ── генерація ─────────────────────────────────────────────────────────
    def generate(self, messages: list[dict] | str, *,
                 params: SamplingParams | None = None,
                 tools: list[dict] | None = None,
                 on_text: Callable[[str], None] | None = None,
                 on_reasoning: Callable[[str], None] | None = None,
                 should_stop: Callable[[], bool] | None = None,
                 stop: tuple[str, ...] | None = None) -> GenerationResult:
        """Згенерувати відповідь (блокуюче); токени йдуть у ``on_text``."""
        result = GenerationResult(model=self.model_path)
        for chunk in self.generate_stream(
                messages, params=params, tools=tools, should_stop=should_stop,
                stop=stop):
            if chunk.text:
                result.text += chunk.text
                if on_text is not None:
                    on_text(chunk.text)
            if chunk.reasoning and on_reasoning is not None:
                on_reasoning(chunk.reasoning)
            if chunk.done:
                result.stats = chunk.stats
                result.finish_reason = chunk.finish_reason
                result.tokens = chunk.tokens
                result.tool_calls = chunk.tool_calls
        return result

    def generate_stream(self, messages: list[dict] | str, *,
                        params: SamplingParams | None = None,
                        tools: list[dict] | None = None,
                        should_stop: Callable[[], bool] | None = None,
                        stop: tuple[str, ...] | None = None) -> Iterator["StreamChunk"]:
        """Потокова генерація: кожен виклик ``next`` дає новий фрагмент."""
        model = self.model
        context = self.context
        if model is None or context is None:
            raise EngineError("Спочатку завантаж модель (load).")
        tokenizer = model.tokenizer
        if tokenizer is None:
            raise EngineError("У моделі немає словника.")

        settings = (params or SamplingParams()).normalised()
        if stop:
            settings.stop = tuple(stop) + tuple(settings.stop)

        prompt = self._prepare_prompt(messages, tools)
        prompt_tokens = tokenizer.encode(prompt, add_special=tokenizer.adds_bos)
        budget = context.n_ctx
        truncated_from_head = 0
        if len(prompt_tokens) >= budget:
            # Лишаємо місце під відповідь: інакше рушій відмовить у декодуванні.
            keep = max(1, budget - min(settings.max_tokens, max(64, budget // 4)))
            # Голова промпту — це СИСТЕМНИЙ промпт (роль, правила, списки
            # інструментів і обмежень). Відрізаючи її, ми мовчки позбавляли
            # модель інструкцій і дозволяли їй «вигадувати» поведінку.
            # Тому: (1) явно фіксуємо, СКІЛЬКИ відрізано; (2) зберігаємо
            # початок у статистиці, щоб викликач міг попередити людину.
            truncated_from_head = max(0, len(prompt_tokens) - keep)
            LOG.warning(
                "Промпт %d токенів не влазить у %d — відрізано %d токенів "
                "З ГОЛОВИ (там системний промпт і правила). Модель може "
                "втратити інструкції.",
                len(prompt_tokens), budget, truncated_from_head)
            prompt_tokens = prompt_tokens[-keep:]

        stats = GenerationStats(prompt_tokens=len(prompt_tokens))
        if truncated_from_head:
            # Не нова метрика, а чесний слід наявної: скільки втрачено.
            setattr(stats, "truncated_head_tokens", truncated_from_head)
        started = time.perf_counter()
        with context._lock:                            # noqa: SLF001 - спільний м'ютекс
            context.reset_cancel()
            skip = context.cache.prepare(prompt_tokens) if context.cache else 0
            # Випадок «промпт повністю в кеші»: декодувати нічого, але й
            # логітів для семплінгу тоді немає. Тому відкочуємось на один
            # токен назад і декодуємо його знову — це дешево й дає свіжі
            # логіти саме після останнього токена промпту.
            if skip >= len(prompt_tokens) and prompt_tokens:
                if context.cache is not None:
                    skip = context.cache.truncate(len(prompt_tokens) - 1)
                else:
                    skip = len(prompt_tokens) - 1
            stats.cached_tokens = skip
            fresh = prompt_tokens[skip:]
            prefill_started = time.perf_counter()
            ok = context.decode(fresh, start_pos=skip)
            stats.prefill_ms = (time.perf_counter() - prefill_started) * 1000.0
            if not ok:
                stats.cancelled = True
                stats.total_ms = (time.perf_counter() - started) * 1000.0
                self._stats["generations"] += 1
                yield StreamChunk(done=True, stats=stats, finish_reason="cancelled")
                return
            if context.cache is not None:
                context.cache.set_tokens(prompt_tokens)

            chain = SamplerChain(self.lib, settings,
                                n_vocab=tokenizer.size,
                                vocab=self.model.vocab if self.model else 0)
            # Декодер стріму притримує незавершені байти UTF-8. Без нього
            # кожен другий токен кирилиці давав ``��`` у відповіді: один
            # символ «є» розкладається на два токени, і жоден із них
            # окремо не є валідним UTF-8.
            from .tokenizer import StreamingDecoder

            decoder = StreamingDecoder(tokenizer, skip_special=True)
            matcher = StopMatcher(settings.stop)
            # Прибирає сирий JSON виклику з того, що бачить користувач.
            # ``known`` обмежує розбір відомими назвами інструментів, інакше
            # будь-яка фігурна дужка у відповіді вважалась би викликом.
            from .chatfmt import ToolCallParser

            known_tools = {
                str(item.get("function", {}).get("name") or "")
                for item in (tools or []) if isinstance(item, dict)
            } - {""}
            tool_parser = ToolCallParser(known=known_tools or None)
            produced: list[int] = []
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            grammar_fallback = ""
            decode_started = time.perf_counter()
            finish_reason = "length"
            try:
                for _ in range(settings.max_tokens):
                    if should_stop is not None and should_stop():
                        context.cancel()
                    if context.cancelled:
                        stats.cancelled = True
                        finish_reason = "cancelled"
                        break
                    try:
                        token = chain.sample(context.handle, -1)
                    except GrammarUnsupported as exc:
                        # Ця збірка рушія не обробила граматику. Краще
                        # продовжити без обмеження й СКАЗАТИ про це, ніж
                        # втратити весь процес IDE на C++-винятку.
                        LOG.warning("%s", exc)
                        grammar_fallback = str(exc)
                        chain.free()
                        settings.grammar = ""
                        chain = SamplerChain(self.lib, settings,
                                             n_vocab=tokenizer.size,
                                             vocab=self.model.vocab if self.model else 0)
                        try:
                            token = chain.sample(context.handle, -1)
                        except OSError as inner:
                            # Навіть без граматики семплер не працює —
                            # контекст уже зіпсовано винятком рушія.
                            stats.cancelled = True
                            finish_reason = "error"
                            grammar_fallback = (
                                f"Рушій зіпсував контекст після граматики: {inner}")
                            break
                    if tokenizer.is_eog(token):
                        finish_reason = "stop"
                        stats.stopped_by = tokenizer.token_text(token, skip_special=False)
                        break
                    try:
                        chain.accept(token)
                    except GrammarUnsupported as exc:
                        # ``accept`` падає на «літеральних» граматиках у цій
                        # збірці. Токен уже вибрано — приймаємо його й
                        # переходимо на ланцюжок без граматики.
                        LOG.warning("%s", exc)
                        grammar_fallback = str(exc)
                        chain.free()
                        settings.grammar = ""
                        chain = SamplerChain(self.lib, settings,
                                             n_vocab=tokenizer.size,
                                             vocab=self.model.vocab if self.model else 0)
                    produced.append(token)
                    piece = decoder.push(token)
                    if piece:
                        safe = matcher.feed(piece)
                        if safe:
                            # ``ToolCallParser`` прибирає з показу сирий
                            # JSON виклику: користувач має бачити пояснення,
                            # а виклик — виконуватись окремо. Раніше клас
                            # був оголошений і не використовувався, тому в
                            # стрімі протікав ``{"name": "read_file", …}``.
                            shown = tool_parser.feed(safe)
                            if shown:
                                text_parts.append(shown)
                                yield StreamChunk(text=shown)
                    if matcher.stopped:
                        finish_reason = "stop"
                        stats.stopped_by = matcher.matched
                        break
                    if not context.decode([token], start_pos=context.cache.length
                                          if context.cache else len(prompt_tokens) + len(produced)):
                        stats.cancelled = True
                        finish_reason = "cancelled"
                        break
                    if context.cache is not None:
                        context.cache.committed([token])
                else:
                    finish_reason = "length"
                # Залишок декодера — це або незавершений байт (тоді він
                # невалідний і нічого не додає), або хвіст, який стоп-метчер
                # притримував як можливий початок маркера.
                rest = decoder.flush()
                if rest:
                    safe_tail = matcher.feed(rest)
                    if safe_tail:
                        shown_tail = tool_parser.feed(safe_tail)
                        if shown_tail:
                            text_parts.append(shown_tail)
                            yield StreamChunk(text=shown_tail)
                tail = matcher.flush()
                if tail:
                    shown = tool_parser.feed(tail) + tool_parser.finish()
                else:
                    shown = tool_parser.finish()
                if shown and finish_reason != "stop":
                    text_parts.append(shown)
                    yield StreamChunk(text=shown)
            finally:
                stats.decode_ms = (time.perf_counter() - decode_started) * 1000.0
                chain.free()

        stats.generated_tokens = len(produced)
        stats.total_ms = (time.perf_counter() - started) * 1000.0
        self._stats["generations"] += 1
        self._stats["tokens_generated"] += stats.generated_tokens
        self._stats["tokens_prompted"] += stats.prompt_tokens

        full_text = "".join(text_parts)
        # ── ДЕ ШУКАТИ ВИКЛИК ──────────────────────────────────────────────
        # ``ToolCallParser`` ВИРІЗАЄ JSON-виклик із ``text_parts`` (щоб
        # користувач не бачив сирий JSON у стрімі). Тому ``full_text``
        # містить лише «безпечний» текст — і пошук виклику в ньому ніколи
        # нічого не знаходив: агент отримував ``tool_calls = []`` і
        # відповідав текстом замість роботи.
        #
        # ``tool_parser.text`` накопичує САМЕ той хвіст, який було
        # приховано, — там і лежить виклик.
        searchable = tool_parser.text or full_text
        tool_calls = self._extract_calls(searchable, tools, matcher.stopped)
        if tool_calls:
            finish_reason = "tool_calls"
        payload = StreamChunk(done=True, stats=stats, finish_reason=finish_reason,
                              tokens=produced, tool_calls=tool_calls,
                              text="", reasoning="".join(reasoning_parts))
        payload.grammar_fallback = grammar_fallback
        yield payload

    # ── допоміжне ─────────────────────────────────────────────────────────
    def _prepare_prompt(self, messages: list[dict] | str,
                        tools: list[dict] | None) -> str:
        if isinstance(messages, str):
            return messages
        payload = list(messages)
        if tools:
            from .chatfmt import tool_schemas_prompt

            hint = tool_schemas_prompt(tools)
            if hint:
                # Опис інструментів додаємо в системне повідомлення: так він
                # не губиться в історії й не дублюється на кожен хід.
                if payload and payload[0].get("role") == "system":
                    payload[0] = dict(payload[0])
                    payload[0]["content"] = str(payload[0].get("content") or "") + "\n\n" + hint
                else:
                    payload.insert(0, {"role": "system", "content": hint})
        return self.render_chat(payload, add_assistant=True)

    def _extract_calls(self, text: str, tools: list[dict] | None,
                       stop_marker: str) -> list[dict[str, Any]]:
        if not tools or not text:
            if not stop_marker:
                return []
        from .chatfmt import extract_tool_calls

        known = set()
        for tool in tools or ():
            function = tool.get("function") if isinstance(tool, dict) else None
            name = (function or tool or {}).get("name") if isinstance(tool, dict) else None
            if name:
                known.add(str(name))
        calls = extract_tool_calls(text, known=known or None)
        return [call.to_openai() for call in calls]

    # ── embeddings ────────────────────────────────────────────────────────
    def embed(self, texts: list[str], *, normalize: bool = True,
              batch_size: int = 8) -> list[list[float]]:
        """Локальні вектори тією самою моделлю (mean pooling).

        Чому mean pooling, а не «останній токен»: у генеративних моделях
        останній токен кодує насамперед «що буде далі», тому вектори
        різних тем виходили майже однаковими (перевірено: косинус між
        кодом і SQL був 0.90). Усереднення прихованих станів усіх токенів
        дає розділення, придатне для пошуку, і працює для будь-якої
        GGUF-моделі — без окремої embedding-моделі.
        """
        if not self.loaded:
            raise EngineError(
                "Для embeddings потрібна завантажена модель. "
                "Завантаж embedding-модель або скористайся тією самою.")
        model = self.model
        context = self.context
        tokenizer = model.tokenizer
        if model is None or context is None or tokenizer is None:
            raise EngineError("Модель не завантажена.")
        del batch_size
        vectors: list[list[float]] = []
        dim = int(self.lib.llama_model_n_embd(model.handle)) or 0
        if dim <= 0:
            raise EngineError("Модель не віддає розмірність прихованих станів.")
        # Кеш префікса (KV) розмови знищується embeddings-роботою: кожен
        # текст декодується з позиції 0, інакше приховані стани прийшли б із
        # чужого контексту. Це НЕМОЖЛИВО обійти в межах одного контексту,
        # тому чесно попереджаємо викликача: наступний хід агента
        # пере-прокладе весь промпт (prefill), а не перевикористає кеш.
        # Раніше це відбувалось мовчки, і «раптове» падіння швидкості після
        # запису в пам'ять виглядало незрозуміло.
        had_cache = bool(getattr(context, "cache", None)) and \
            not getattr(context.cache, "empty", False)
        if had_cache:
            LOG.info("Embeddings скидають KV-кеш: наступний хід пере-прочитає "
                     "промпт (це очікувано)")
        with context._lock:                            # noqa: SLF001
            self.lib.llama_set_embeddings(context.handle, True)
            try:
                for text in texts:
                    context.reset_cancel()
                    if context.cache:
                        context.cache.clear()
                    tokens = tokenizer.encode(text or "", add_special=True)
                    if len(tokens) > context.n_ctx:
                        tokens = tokens[: context.n_ctx]
                    if not tokens:
                        vectors.append([0.0] * dim)
                        continue
                    if not self._decode_all_outputs(context, tokens):
                        raise GenerationCancelled("Embeddings скасовано.")
                    summed = [0.0] * dim
                    used = 0
                    for index in range(len(tokens)):
                        raw = self.lib.llama_get_embeddings_ith(context.handle, index)
                        if not raw:
                            continue
                        for position in range(dim):
                            summed[position] += float(raw[position])
                        used += 1
                    if not used:
                        seq = self.lib.llama_get_embeddings_seq(context.handle, 0)
                        if seq:
                            summed = [float(seq[position]) for position in range(dim)]
                            used = 1
                    if not used:
                        vectors.append([0.0] * dim)
                        continue
                    vector = [value / used for value in summed]
                    vectors.append(_normalise(vector) if normalize else vector)
            finally:
                self.lib.llama_set_embeddings(context.handle, False)
                if context.cache:
                    context.cache.clear()
        return vectors

    def _decode_all_outputs(self, context: "EngineContext", tokens: list[int]) -> bool:
        """Декодувати промпт так, щоб рушій віддав прихований стан КОЖНОГО токена."""
        lib = self.lib
        count = len(tokens)
        batch = lib.llama_batch_init(count, 0, 1)
        if not batch.token:
            raise EngineError("Не вдалось виділити пакет токенів.")
        try:
            for index, token in enumerate(tokens):
                batch.token[index] = token
                batch.pos[index] = index
                batch.n_seq_id[index] = 1
                batch.seq_id[index][0] = 0
                batch.logits[index] = 1        # усі токени = виходи
            batch.n_tokens = count
            code = int(lib.llama_decode(context.handle, batch))
        finally:
            lib.llama_batch_free(batch)
        if code == 0:
            return True
        if code == _abi.DECODE_ABORTED or context.cancelled:
            return False
        raise EngineError(f"Декодування для embeddings не вдалось (код {code}).")

    # ── діагностика ───────────────────────────────────────────────────────
    def stats(self) -> dict[str, Any]:
        data = dict(self._stats)
        data.update(
            {
                "loaded": self.loaded,
                "model": self.model_path,
                "context": self.context.n_ctx if self.context else 0,
                "kv": self.context.cache.stats() if self.context else {},
                "last_error": self.last_error,
            }
        )
        return data

    def benchmark(self, *, prompt: str = "Поясни, що таке рекурсія, у трьох реченнях.",
                  max_tokens: int = 64, runs: int = 2) -> dict[str, Any]:
        """Заміряти швидкість на реальній генерації (без вигадок)."""
        if not self.loaded:
            raise EngineError("Спочатку завантаж модель.")
        params = SamplingParams(temperature=0.0, max_tokens=max_tokens,
                                top_k=1, top_p=1.0, min_p=0.0,
                                repeat_penalty=1.0).normalised()
        samples: list[dict[str, Any]] = []
        for run in range(max(1, runs)):
            if self.context is not None and self.context.cache is not None:
                self.context.cache.clear()
            result = self.generate(prompt, params=params)
            payload = result.stats.to_dict()
            payload["text"] = result.text[:200]
            payload["run"] = run + 1
            samples.append(payload)
        ttfts = sorted(item["time_to_first_token_ms"] for item in samples)
        speeds = sorted(item["tokens_per_second"] for item in samples)

        def percentile(values: list[float], share: float) -> float:
            if not values:
                return 0.0
            index = min(len(values) - 1, max(0, int(round(share * (len(values) - 1)))))
            return round(values[index], 2)

        return {
            "model": self.model_path,
            "gpu_layers": self.model.options.n_gpu_layers if self.model else 0,
            "context": self.context.n_ctx if self.context else 0,
            "runs": samples,
            "tokens_per_second": percentile(speeds, 0.5),
            "tokens_per_second_p50": percentile(speeds, 0.5),
            "tokens_per_second_p95": percentile(speeds, 0.95),
            "time_to_first_token_ms": percentile(ttfts, 0.5),
            "time_to_first_token_ms_p50": percentile(ttfts, 0.5),
            "time_to_first_token_ms_p95": percentile(ttfts, 0.95),
        }


@dataclass
class StreamChunk:
    """Один фрагмент потокової відповіді."""

    text: str = ""
    reasoning: str = ""
    done: bool = False
    stats: GenerationStats = field(default_factory=GenerationStats)
    finish_reason: str = ""
    tokens: list[int] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    #: Причина, чому граматику довелось знято (порожньо — граматика діяла
    #: або не задавалась). Порожній рядок означає «все гаразд».
    grammar_fallback: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


def _replace_ctx(options: LoadOptions, n_ctx: int) -> LoadOptions:
    """Копія параметрів із новим контекстом (для повторної спроби)."""
    return LoadOptions(
        n_ctx=n_ctx,
        n_gpu_layers=options.n_gpu_layers,
        n_batch=options.n_batch,
        n_ubatch=options.n_ubatch,
        n_threads=options.n_threads,
        n_threads_batch=options.n_threads_batch,
        flash_attn=options.flash_attn,
        cache_type_k=options.cache_type_k,
        cache_type_v=options.cache_type_v,
        offload_kqv=options.offload_kqv,
        mmproj_path=options.mmproj_path,
        embeddings=options.embeddings,
        use_mmap=options.use_mmap,
        use_mlock=options.use_mlock,
        verify_tensors=options.verify_tensors,
        load_mtp=options.load_mtp,
    )


def _normalise(vector: list[float]) -> list[float]:
    """L2-нормалізація: косинус тоді дорівнює скалярному добутку."""
    total = sum(value * value for value in vector) ** 0.5
    if total <= 0:
        return vector
    return [value / total for value in vector]


__all__ = [
    "EngineContext",
    "EngineError",
    "GenerationCancelled",
    "GenerationResult",
    "GenerationStats",
    "LoadOptions",
    "LoadedModel",
    "MIN_CTX",
    "NativeEngine",
    "OOM_RETRIES",
    "StreamChunk",
]
