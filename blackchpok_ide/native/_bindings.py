"""Завантаження llama.cpp як бібліотеки та прив'язка сигнатур.

Головна ідея: BLACKCHPOK IDE НЕ запускає сторонній застосунок і не потребує
llama-server. Вона сама вантажить ``llama.dll`` (і сусідні ``ggml*.dll``) у
власний процес через ctypes і викликає інференс напряму.

Чому ctypes, а не окремий сервер:

* немає другого процесу, отже немає «сирітських» серверів і портів;
* streaming і скасування генерації працюють у пам'яті, без HTTP;
* tokenizer, embeddings, KV-кеш — усе під контролем IDE.

Модуль нічого не знає про моделі: він лише дає об'єкт :class:`LlamaLibrary`,
через який :mod:`.engine` викликає C-функції.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Iterable

from . import _abi

LOG = logging.getLogger("blackchpok.native.bindings")

#: Імена бібліотек рушія, які мають лежати в одній теці.
LLAMA_DLL = "llama.dll" if os.name == "nt" else "libllama.so"
GGML_DLLS = ("ggml.dll", "ggml-base.dll") if os.name == "nt" else ("libggml.so",)


class NativeUnavailable(RuntimeError):
    """Рушій не встановлено або бібліотеку не вдалось завантажити."""


class BackendDevice:
    """Один обчислювальний пристрій (CPU/CUDA), який бачить ggml."""

    __slots__ = ("index", "name", "description", "kind", "memory_free", "memory_total")

    def __init__(self, index: int, name: str, description: str, kind: str,
                 memory_free: int = 0, memory_total: int = 0) -> None:
        self.index = index
        self.name = name
        self.description = description
        self.kind = kind
        self.memory_free = memory_free
        self.memory_total = memory_total

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "memory_free_mb": round(self.memory_free / 1048576, 1),
            "memory_total_mb": round(self.memory_total / 1048576, 1),
        }

    def __repr__(self) -> str:                      # pragma: no cover - діагностика
        return (f"BackendDevice({self.name!r}, kind={self.kind!r}, "
                f"{self.memory_total / 1048576:.0f} MiB)")


# ─────────────────────────────────────────────────────────────────────────────
# Пошук бібліотек
# ─────────────────────────────────────────────────────────────────────────────

def runtime_dir() -> Path:
    """Тека рушія (та сама, що заповнює :mod:`..runtime`).

    Імпорт усередині функції: ``runtime`` тягне ``model_hub`` і ``config``,
    а цей модуль має лишатися придатним до імпорту навіть тоді, коли
    конфігурація недоступна (наприклад, у дуже ранньому старті).
    """
    from ..runtime import runtime_dir as _runtime_dir

    return _runtime_dir()


def find_library(root: Path | None = None) -> Path | None:
    """Знайти ``llama.dll`` у теці рушія."""
    base = Path(root) if root else runtime_dir()
    candidate = base / LLAMA_DLL
    if candidate.exists():
        return candidate
    for hit in base.rglob(LLAMA_DLL):
        return hit
    return None


def _register_dll_dir(folder: Path) -> None:
    """Дозволити Windows шукати залежні DLL у теці рушія.

    ``os.add_dll_directory`` діє лише на ``LoadLibraryEx`` із прапорцем
    пошуку; ggml вантажить бекенди сам, тому додатково кладемо теку в
    ``PATH`` — саме так знаходяться ``cublas64_*.dll`` і ``cudart64_*.dll``,
    без яких CUDA-бекенд мовчки не піднімається.
    """
    if os.name != "nt":
        return
    folder_text = str(folder)
    try:
        os.add_dll_directory(folder_text)
    except (AttributeError, OSError):
        LOG.debug("add_dll_directory недоступний", exc_info=True)
    current = os.environ.get("PATH", "")
    if folder_text not in current.split(os.pathsep):
        os.environ["PATH"] = folder_text + os.pathsep + current


# ─────────────────────────────────────────────────────────────────────────────
# Прив'язка сигнатур
# ─────────────────────────────────────────────────────────────────────────────

#: Опис функцій llama.dll: ім'я → (restype, argtypes). ``None`` = c_void_p.
_LLAMA_SIGNATURES: dict[str, tuple[object, list[object]]] = {
    "llama_backend_init": (None, []),
    "llama_backend_free": (None, []),
    "llama_log_set": (None, [ctypes.c_void_p, ctypes.c_void_p]),
    "llama_print_system_info": (ctypes.c_char_p, []),
    "llama_time_us": (ctypes.c_int64, []),
    "llama_max_devices": (ctypes.c_size_t, []),
    "llama_supports_gpu_offload": (ctypes.c_bool, []),
    "llama_version": (ctypes.c_char_p, []),
    "llama_model_default_params": (_abi.LlamaModelParams, []),
    "llama_context_default_params": (_abi.LlamaContextParams, []),
    "llama_sampler_chain_default_params": (_abi.LlamaSamplerChainParams, []),
    "llama_model_load_from_file": (ctypes.c_void_p, [ctypes.c_char_p, _abi.LlamaModelParams]),
    "llama_model_free": (None, [ctypes.c_void_p]),
    "llama_init_from_model": (ctypes.c_void_p, [ctypes.c_void_p, _abi.LlamaContextParams]),
    "llama_free": (None, [ctypes.c_void_p]),
    "llama_model_get_vocab": (ctypes.c_void_p, [ctypes.c_void_p]),
    "llama_vocab_n_tokens": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_vocab_is_eog": (ctypes.c_bool, [ctypes.c_void_p, _abi.llama_token]),
    "llama_vocab_bos": (_abi.llama_token, [ctypes.c_void_p]),
    "llama_vocab_eos": (_abi.llama_token, [ctypes.c_void_p]),
    "llama_vocab_get_add_bos": (ctypes.c_bool, [ctypes.c_void_p]),
    "llama_tokenize": (
        ctypes.c_int32,
        [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
         ctypes.POINTER(_abi.llama_token), ctypes.c_int32, ctypes.c_bool, ctypes.c_bool],
    ),
    "llama_token_to_piece": (
        ctypes.c_int32,
        [ctypes.c_void_p, _abi.llama_token, ctypes.c_char_p, ctypes.c_int32,
         ctypes.c_int32, ctypes.c_bool],
    ),
    "llama_detokenize": (
        ctypes.c_int32,
        [ctypes.c_void_p, ctypes.POINTER(_abi.llama_token), ctypes.c_int32,
         ctypes.c_char_p, ctypes.c_int32, ctypes.c_bool, ctypes.c_bool],
    ),
    "llama_batch_init": (_abi.LlamaBatch, [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]),
    "llama_batch_free": (None, [_abi.LlamaBatch]),
    "llama_decode": (ctypes.c_int32, [ctypes.c_void_p, _abi.LlamaBatch]),
    "llama_encode": (ctypes.c_int32, [ctypes.c_void_p, _abi.LlamaBatch]),
    "llama_n_ctx": (ctypes.c_uint32, [ctypes.c_void_p]),
    "llama_n_batch": (ctypes.c_uint32, [ctypes.c_void_p]),
    "llama_n_seq_max": (ctypes.c_uint32, [ctypes.c_void_p]),
    "llama_n_threads": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_set_n_threads": (None, [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32]),
    "llama_set_embeddings": (None, [ctypes.c_void_p, ctypes.c_bool]),
    "llama_set_abort_callback": (None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]),
    "llama_synchronize": (None, [ctypes.c_void_p]),
    "llama_get_embeddings": (ctypes.POINTER(ctypes.c_float), [ctypes.c_void_p]),
    "llama_get_embeddings_ith": (ctypes.POINTER(ctypes.c_float),
                                 [ctypes.c_void_p, ctypes.c_int32]),
    "llama_get_embeddings_seq": (ctypes.POINTER(ctypes.c_float),
                                 [ctypes.c_void_p, _abi.llama_seq_id]),
    "llama_pooling_type": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_get_memory": (ctypes.c_void_p, [ctypes.c_void_p]),
    "llama_memory_clear": (None, [ctypes.c_void_p, ctypes.c_bool]),
    "llama_memory_seq_rm": (ctypes.c_bool, [ctypes.c_void_p, _abi.llama_seq_id,
                                            _abi.llama_pos, _abi.llama_pos]),
    "llama_memory_seq_keep": (None, [ctypes.c_void_p, _abi.llama_seq_id]),
    "llama_memory_seq_pos_max": (_abi.llama_pos, [ctypes.c_void_p, _abi.llama_seq_id]),
    "llama_sampler_chain_init": (ctypes.c_void_p, [_abi.LlamaSamplerChainParams]),
    "llama_sampler_chain_add": (None, [ctypes.c_void_p, ctypes.c_void_p]),
    "llama_sampler_chain_n": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_sampler_init_greedy": (ctypes.c_void_p, []),
    "llama_sampler_init_dist": (ctypes.c_void_p, [ctypes.c_uint32]),
    "llama_sampler_init_top_k": (ctypes.c_void_p, [ctypes.c_int32]),
    "llama_sampler_init_top_p": (ctypes.c_void_p, [ctypes.c_float, ctypes.c_size_t]),
    "llama_sampler_init_min_p": (ctypes.c_void_p, [ctypes.c_float, ctypes.c_size_t]),
    "llama_sampler_init_temp": (ctypes.c_void_p, [ctypes.c_float]),
    "llama_sampler_init_penalties": (
        ctypes.c_void_p,
        # (n_vocab, penalty_last_n, penalty_repeat, penalty_freq, penalty_present)
        [ctypes.c_int32, ctypes.c_int32, ctypes.c_float, ctypes.c_float, ctypes.c_float],
    ),
    "llama_sampler_init_grammar": (ctypes.c_void_p,
                                   [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]),
    "llama_sampler_sample": (_abi.llama_token,
                             [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32]),
    "llama_sampler_accept": (None, [ctypes.c_void_p, _abi.llama_token]),
    "llama_sampler_reset": (None, [ctypes.c_void_p]),
    "llama_sampler_free": (None, [ctypes.c_void_p]),
    "llama_model_desc": (ctypes.c_int32, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]),
    "llama_model_n_params": (ctypes.c_uint64, [ctypes.c_void_p]),
    "llama_model_size": (ctypes.c_uint64, [ctypes.c_void_p]),
    "llama_model_n_ctx_train": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_model_n_embd": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_model_n_layer": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_model_n_head": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_model_n_head_kv": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_model_ftype": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_ftype_name": (ctypes.c_char_p, [ctypes.c_int32]),
    "llama_model_is_recurrent": (ctypes.c_bool, [ctypes.c_void_p]),
    "llama_model_has_encoder": (ctypes.c_bool, [ctypes.c_void_p]),
    "llama_model_has_decoder": (ctypes.c_bool, [ctypes.c_void_p]),
    "llama_model_chat_template": (ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
    "llama_chat_apply_template": (
        ctypes.c_int32,
        [ctypes.c_char_p, ctypes.POINTER(_abi.LlamaChatMessage), ctypes.c_size_t,
         ctypes.c_bool, ctypes.c_char_p, ctypes.c_int32],
    ),
    "llama_model_meta_count": (ctypes.c_int32, [ctypes.c_void_p]),
    "llama_model_meta_key_by_index": (ctypes.c_int32,
                                      [ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p,
                                       ctypes.c_size_t]),
    "llama_model_meta_val_str_by_index": (ctypes.c_int32,
                                          [ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p,
                                           ctypes.c_size_t]),
    "llama_perf_context": (_abi.LlamaPerfContextData, [ctypes.c_void_p]),
    "llama_perf_context_reset": (None, [ctypes.c_void_p]),
}

_GGML_SIGNATURES: dict[str, tuple[object, list[object]]] = {
    "ggml_backend_load_all": (None, []),
    "ggml_backend_load_all_from_path": (None, [ctypes.c_char_p]),
    "ggml_backend_dev_count": (ctypes.c_size_t, []),
    "ggml_backend_dev_get": (ctypes.c_void_p, [ctypes.c_size_t]),
    "ggml_backend_dev_name": (ctypes.c_char_p, [ctypes.c_void_p]),
    "ggml_backend_dev_description": (ctypes.c_char_p, [ctypes.c_void_p]),
    "ggml_backend_dev_type": (ctypes.c_int32, [ctypes.c_void_p]),
    "ggml_backend_dev_memory": (None, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                       ctypes.POINTER(ctypes.c_size_t)]),
}


def _bind(lib: ctypes.CDLL, name: str, restype: object, argtypes: list[object]) -> bool:
    """Прив'язати одну функцію; ``False``, якщо її немає в цій бібліотеці."""
    try:
        func = getattr(lib, name)
    except AttributeError:
        return False
    func.restype = restype
    func.argtypes = argtypes
    return True


class LlamaLibrary:
    """Завантажені бібліотеки рушія + перевірка ABI.

    Один екземпляр на процес: ``backend_init`` у llama.cpp глобальний, а
    повторне завантаження DLL у той самий процес Windows не звільняє
    раніше виділену пам'ять.
    """

    _instance: "LlamaLibrary | None" = None
    _lock = threading.Lock()

    def __init__(self, root: Path | None = None) -> None:
        library = find_library(root)
        if library is None:
            raise NativeUnavailable(
                "Бібліотеку llama.dll не знайдено. Встанови рушій у розділі "
                "«AI Runtime» або поклади збірку llama.cpp у userdata/runtime."
            )
        self.path = library
        self.folder = library.parent
        _register_dll_dir(self.folder)
        try:
            self.lib = ctypes.WinDLL(str(library)) if os.name == "nt" else ctypes.CDLL(str(library))
        except OSError as exc:                       # pragma: no cover - залежності
            raise NativeUnavailable(f"Не вдалось завантажити {library.name}: {exc}") from exc

        # ggml-функції розкидані по ggml.dll і ggml-base.dll залежно від збірки,
        # тому шукаємо кожну в усіх кандидатах.
        self._ggml_libs: list[ctypes.CDLL] = []
        for name in GGML_DLLS:
            candidate = self.folder / name
            if not candidate.exists():
                continue
            try:
                self._ggml_libs.append(
                    ctypes.WinDLL(str(candidate)) if os.name == "nt"
                    else ctypes.CDLL(str(candidate)))
            except OSError:                          # pragma: no cover
                LOG.warning("Не вдалось завантажити %s", candidate.name, exc_info=True)

        self.missing: list[str] = []
        self._bound: dict[str, object] = {}
        for name, (restype, argtypes) in _LLAMA_SIGNATURES.items():
            if _bind(self.lib, name, restype, argtypes):
                self._bound[name] = getattr(self.lib, name)
            else:
                self.missing.append(name)
        for name, (restype, argtypes) in _GGML_SIGNATURES.items():
            for lib in self._ggml_libs:
                if _bind(lib, name, restype, argtypes):
                    self._bound[name] = getattr(lib, name)
                    break
            else:
                self.missing.append(name)

        # Сумісність ABI: розмір структури, яку повертає сама бібліотека,
        # мусить збігатися з нашим описом. Інакше поля «з'їдуть».
        try:
            actual = ctypes.sizeof(self._bound["llama_model_default_params"].restype)
            expected = ctypes.sizeof(_abi.LlamaModelParams)
            if actual != expected:                   # pragma: no cover - інша версія
                raise NativeUnavailable(
                    f"Несумісна версія llama.dll: llama_model_params має "
                    f"{actual} байт, очікували {expected}."
                )
        except KeyError as exc:                      # pragma: no cover
            raise NativeUnavailable(
                "llama.dll не має llama_model_default_params — це не llama.cpp."
            ) from exc

        self._devices: list[BackendDevice] = []
        self._backends_loaded = False
        self.backend_init()

    # ── життєвий цикл ──────────────────────────────────────────────────────
    def backend_init(self) -> None:
        """Підняти ggml-бекенди (CPU, CUDA) і llama backend."""
        if not self._backends_loaded:
            loader = self._bound.get("ggml_backend_load_all_from_path")
            load_all = self._bound.get("ggml_backend_load_all")
            # Спершу шлях до рушія: так підхоплюються саме наші ggml-cuda.dll
            # і ggml-cpu-*.dll, а не випадкові з PATH.
            if loader is not None:
                loader(str(self.folder).encode("utf-8"))
            count = self._bound.get("ggml_backend_dev_count")
            if (count is None or count() == 0) and load_all is not None:
                load_all()
            self._backends_loaded = True
            self._devices = self._probe_devices()
            LOG.info("Бекенди рушія: %s", ", ".join(d.name for d in self._devices) or "немає")
        self._bound["llama_backend_init"]()

    def _probe_devices(self) -> list[BackendDevice]:
        count = self._bound.get("ggml_backend_dev_count")
        get = self._bound.get("ggml_backend_dev_get")
        name_of = self._bound.get("ggml_backend_dev_name")
        desc_of = self._bound.get("ggml_backend_dev_description")
        type_of = self._bound.get("ggml_backend_dev_type")
        mem_of = self._bound.get("ggml_backend_dev_memory")
        if count is None or get is None or name_of is None:
            return []
        devices: list[BackendDevice] = []
        for index in range(int(count())):
            handle = get(index)
            if not handle:
                continue
            raw_name = name_of(handle) or b""
            raw_desc = desc_of(handle) if desc_of else b""
            kind_code = int(type_of(handle)) if type_of else 0
            free = ctypes.c_size_t(0)
            total = ctypes.c_size_t(0)
            if mem_of is not None:
                mem_of(handle, ctypes.byref(free), ctypes.byref(total))
            devices.append(
                BackendDevice(
                    index=index,
                    name=raw_name.decode("utf-8", "replace"),
                    description=(raw_desc or b"").decode("utf-8", "replace"),
                    kind=_abi.DEVICE_TYPE.get(kind_code, "unknown"),
                    memory_free=int(free.value),
                    memory_total=int(total.value),
                )
            )
        return devices

    # ── доступ ─────────────────────────────────────────────────────────────
    @property
    def devices(self) -> list[BackendDevice]:
        return list(self._devices)

    @property
    def gpu_devices(self) -> list[BackendDevice]:
        return [d for d in self._devices if d.kind in {"gpu", "igpu", "accel"}]

    @property
    def supports_gpu_offload(self) -> bool:
        func = self._bound.get("llama_supports_gpu_offload")
        return bool(func()) if func is not None else bool(self.gpu_devices)

    def system_info(self) -> str:
        func = self._bound.get("llama_print_system_info")
        if func is None:
            return ""
        return (func() or b"").decode("utf-8", "replace").strip()

    def version(self) -> str:
        func = self._bound.get("llama_version")
        if func is None:
            return ""
        return (func() or b"").decode("utf-8", "replace").strip()

    def __getattr__(self, name: str):
        """Зручний доступ до прив'язаних C-функцій: ``lib.llama_decode``."""
        bound = self.__dict__.get("_bound") or {}
        if name in bound:
            return bound[name]
        raise AttributeError(name)

    def has(self, name: str) -> bool:
        return name in (self.__dict__.get("_bound") or {})


# ─────────────────────────────────────────────────────────────────────────────
# Спільний доступ
# ─────────────────────────────────────────────────────────────────────────────

def load_library(root: Path | None = None) -> LlamaLibrary:
    """Повернути (і за потреби створити) екземпляр бібліотеки."""
    with LlamaLibrary._lock:
        if LlamaLibrary._instance is None:
            LlamaLibrary._instance = LlamaLibrary(root)
        return LlamaLibrary._instance


def library_ready(root: Path | None = None) -> bool:
    """Чи можна завантажити рушій — без винятків."""
    try:
        load_library(root)
        return True
    except (NativeUnavailable, OSError):
        return False


def reset_library() -> None:
    """Забути завантажений екземпляр (для тестів і після перевстановлення)."""
    with LlamaLibrary._lock:
        LlamaLibrary._instance = None


def verify_symbols(names: Iterable[str]) -> list[str]:
    """Перевірити, що рушій експортує потрібні функції."""
    lib = load_library()
    return [name for name in names if not lib.has(name)]


__all__ = [
    "BackendDevice",
    "GGML_DLLS",
    "LLAMA_DLL",
    "LlamaLibrary",
    "NativeUnavailable",
    "find_library",
    "library_ready",
    "load_library",
    "reset_library",
    "runtime_dir",
    "verify_symbols",
]

if sys.platform == "win32":                          # pragma: no cover - документація
    LOG.debug("Windows: залежності CUDA шукаються через PATH=%s", runtime_dir())
