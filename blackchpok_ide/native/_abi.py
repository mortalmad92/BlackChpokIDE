"""Базові ctypes-структури та прототипи llama.cpp (GGML).

Модуль — «фундамент» власного рушія: тут оголошені C-структури та сигнатури
функцій з ``llama.h`` / ``ggml-backend.h`` тієї версії, яку BLACKCHPOK IDE
ставить у ``userdata/runtime``. Жодної логіки — лише опис ABI.

Розкладка структур відповідає апстрім-заголовкам llama.cpp (build 12129,
версія 0.9.0-dev). Якщо рушій оновиться й змінить поля, :mod:`._bindings`
перевірить збіг через ``llama_model_default_params`` — розміри структур
читаються з самої бібліотеки, тому розбіжність видно одразу, а не через
«дивні» падіння посеред генерації.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    Structure,
    c_bool,
    c_char_p,
    c_float,
    c_int8,
    c_int32,
    c_int64,
    c_size_t,
    c_uint32,
    c_uint64,
    c_void_p,
)

#: Типи-псевдоніми llama.cpp.
llama_token = c_int32
llama_pos = c_int32
llama_seq_id = c_int32


class LlamaModelParams(Structure):
    """``struct llama_model_params`` (порядок полів — як у llama.h)."""

    _fields_ = [
        ("devices", c_void_p),
        ("tensor_buft_overrides", c_void_p),
        ("n_gpu_layers", c_int32),
        ("split_mode", c_int32),
        ("load_mode", c_int32),
        ("lazy_mode", c_int32),
        ("main_gpu", c_int32),
        ("tensor_split", c_void_p),
        ("progress_callback", c_void_p),
        ("progress_callback_user_data", c_void_p),
        ("kv_overrides", c_void_p),
        ("vocab_only", c_bool),
        ("check_tensors", c_bool),
        ("use_extra_bufts", c_bool),
        ("no_host", c_bool),
        ("no_alloc", c_bool),
        ("load_mtp", c_bool),
    ]


class LlamaContextParams(Structure):
    """``struct llama_context_params``.

    ``flash_attn_type``, ``type_k``/``type_v`` — int, бо це C-``enum``.
    Значення див. у :data:`FLASH_ATTN` і :data:`GGML_TYPE`.
    """

    _fields_ = [
        ("n_ctx", c_uint32),
        ("n_batch", c_uint32),
        ("n_ubatch", c_uint32),
        ("n_seq_max", c_uint32),
        ("n_rs_seq", c_uint32),
        ("n_outputs_max", c_uint32),
        ("n_outputs_max_per_seq", c_uint32),
        ("n_threads", c_int32),
        ("n_threads_batch", c_int32),
        ("ctx_type", c_int32),
        ("rope_scaling_type", c_int32),
        ("pooling_type", c_int32),
        ("attention_type", c_int32),
        ("flash_attn_type", c_int32),
        ("rope_freq_base", c_float),
        ("rope_freq_scale", c_float),
        ("yarn_ext_factor", c_float),
        ("yarn_attn_factor", c_float),
        ("yarn_beta_fast", c_float),
        ("yarn_beta_slow", c_float),
        ("yarn_orig_ctx", c_uint32),
        ("defrag_thold", c_float),
        ("cb_eval", c_void_p),
        ("cb_eval_user_data", c_void_p),
        ("type_k", c_int32),
        ("type_v", c_int32),
        ("moe_cache_size", c_size_t),
        ("abort_callback", c_void_p),
        ("abort_callback_data", c_void_p),
        ("embeddings", c_bool),
        ("offload_kqv", c_bool),
        ("no_perf", c_bool),
        ("op_offload", c_bool),
        ("swa_full", c_bool),
        ("kv_unified", c_bool),
        ("samplers", c_void_p),
        ("n_samplers", c_size_t),
        ("ctx_other", c_void_p),
    ]


class LlamaBatch(Structure):
    """``struct llama_batch`` — пакет токенів для ``llama_decode``."""

    _fields_ = [
        ("n_tokens", c_int32),
        ("token", POINTER(llama_token)),
        ("embd", POINTER(c_float)),
        ("pos", POINTER(llama_pos)),
        ("n_seq_id", POINTER(c_int32)),
        ("seq_id", POINTER(POINTER(llama_seq_id))),
        ("logits", POINTER(c_int8)),
    ]


class LlamaSamplerChainParams(Structure):
    """``struct llama_sampler_chain_params``."""

    _fields_ = [("no_perf", c_bool)]


class LlamaChatMessage(Structure):
    """``struct llama_chat_message`` — пара роль/вміст для шаблону чату."""

    _fields_ = [("role", c_char_p), ("content", c_char_p)]


class GgmlBackendDeviceProps(Structure):
    """``struct ggml_backend_dev_props`` — повний опис пристрою.

    ``devices``/``caps`` вкладені структурами, але нам потрібні лише
    ``name``, ``description``, ``type``; решту лишаємо сирими байтами, щоб
    не залежати від точного розміру вкладених полів.
    """

    _fields_ = [
        ("name", c_char_p),
        ("description", c_char_p),
        ("memory_free", c_size_t),
        ("memory_total", c_size_t),
        ("type", c_int32),
    ]


class LlamaPerfContextData(Structure):
    """``struct llama_perf_context_data`` — таймінги контексту."""

    _fields_ = [
        ("t_start_ms", ctypes.c_double),
        ("t_load_ms", ctypes.c_double),
        ("t_p_eval_ms", ctypes.c_double),
        ("t_eval_ms", ctypes.c_double),
        ("n_p_eval", c_int32),
        ("n_eval", c_int32),
        ("n_reused", c_int32),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Переліки (значення — з llama.h / ggml.h тієї самої збірки)
# ─────────────────────────────────────────────────────────────────────────────

#: ``enum llama_flash_attn_type``
FLASH_ATTN = {"auto": -1, "off": 0, "on": 1}

#: ``enum llama_pooling_type``
POOLING = {"unspecified": -1, "none": 0, "mean": 1, "cls": 2, "last": 3, "rank": 4}

#: ``enum llama_split_mode``
SPLIT_MODE = {"none": 0, "layer": 1, "row": 2, "tensor": 3}

#: ``enum llama_load_mode``
LOAD_MODE = {"auto": -1, "none": 0, "mmap": 1, "mlock": 2, "mmap_mlock": 3, "dio": 4}

#: ``enum llama_lazy_mode``
LAZY_MODE = {"off": 0, "auto": 1, "on": 2}

#: Потрібні нам значення ``enum ggml_type`` (типи KV-кешу).
GGML_TYPE = {
    "f32": 0,
    "f16": 1,
    "q4_0": 2,
    "q4_1": 3,
    "q5_0": 6,
    "q5_1": 7,
    "q8_0": 8,
    "bf16": 30,
}

#: ``enum ggml_backend_dev_type``
DEVICE_TYPE = {0: "cpu", 1: "gpu", 2: "igpu", 3: "accel", 4: "meta"}

#: Повернення ``llama_decode``, коли генерацію скасували через abort callback.
DECODE_ABORTED = 2

__all__ = [
    "DECODE_ABORTED",
    "DEVICE_TYPE",
    "FLASH_ATTN",
    "GGML_TYPE",
    "GgmlBackendDeviceProps",
    "LAZY_MODE",
    "LOAD_MODE",
    "LlamaBatch",
    "LlamaChatMessage",
    "LlamaContextParams",
    "LlamaModelParams",
    "LlamaPerfContextData",
    "LlamaSamplerChainParams",
    "POOLING",
    "SPLIT_MODE",
    "c_int64",
    "c_uint64",
    "llama_pos",
    "llama_seq_id",
    "llama_token",
]
