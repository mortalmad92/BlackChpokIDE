"""Назви quantization за ``llama_ftype``.

Копія переліку з ``llama.h`` тієї збірки, що стоїть у ``userdata/runtime``.
Таблиця потрібна, коли ``general.file_type`` у GGUF є, але треба показати
людську назву (``Q4_K - Medium``) без завантаження ваг у пам'ять.
"""

from __future__ import annotations

#: ``enum llama_ftype`` → людська назва.
FTYPE_NAMES: dict[int, str] = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    7: "Q8_0",
    8: "Q5_0",
    9: "Q5_1",
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    19: "IQ2_XXS",
    20: "IQ2_XS",
    21: "Q2_K_S",
    22: "IQ3_XS",
    23: "IQ3_XXS",
    24: "IQ1_S",
    25: "IQ4_NL",
    26: "IQ3_S",
    27: "IQ3_M",
    28: "IQ2_S",
    29: "IQ2_M",
    30: "IQ4_XS",
    31: "IQ1_M",
    32: "BF16",
    36: "TQ1_0",
    37: "TQ2_0",
    38: "MXFP4_MOE",
    39: "NVFP4",
    40: "Q1_0",
    41: "Q2_0",
    42: "F8_E4M3",
    1024: "невідомо",
}

#: Скільки біт на вагу приблизно дає кожен тип (для оцінки розміру й швидкості).
BITS_PER_WEIGHT: dict[str, float] = {
    "F32": 32.0,
    "F16": 16.0,
    "BF16": 16.0,
    "Q8_0": 8.5,
    "Q6_K": 6.6,
    "Q5_K_M": 5.7,
    "Q5_K_S": 5.5,
    "Q5_1": 5.5,
    "Q5_0": 5.5,
    "Q4_K_M": 4.8,
    "Q4_K_S": 4.6,
    "Q4_1": 4.5,
    "Q4_0": 4.5,
    "IQ4_NL": 4.5,
    "IQ4_XS": 4.3,
    "Q3_K_L": 3.9,
    "Q3_K_M": 3.8,
    "Q3_K_S": 3.5,
    "IQ3_M": 3.6,
    "IQ3_S": 3.5,
    "IQ3_XS": 3.3,
    "IQ3_XXS": 3.1,
    "Q2_K": 2.6,
    "Q2_K_S": 2.6,
    "IQ2_M": 2.7,
    "IQ2_S": 2.5,
    "IQ2_XS": 2.4,
    "IQ2_XXS": 2.1,
    "IQ1_M": 1.8,
    "IQ1_S": 1.6,
    "TQ1_0": 1.7,
    "TQ2_0": 2.1,
    "MXFP4_MOE": 4.3,
    "NVFP4": 4.3,
    "Q1_0": 1.1,
    "Q2_0": 2.2,
    "F8_E4M3": 8.0,
}


def ftype_name(ftype: int) -> str:
    """Людська назва типу; порожній рядок, якщо тип невідомий."""
    return FTYPE_NAMES.get(int(ftype), "")


def bits_per_weight(quant: str) -> float:
    """Скільки біт на вагу дає quantization (для прогнозу пам'яті)."""
    key = (quant or "").strip().upper().replace(" ", "_")
    if key in BITS_PER_WEIGHT:
        return BITS_PER_WEIGHT[key]
    # ``Q4_K - Medium`` → ``Q4_K_M``
    compact = key.replace("_-_", "_").replace("-", "_")
    compact = {"Q4_K_MEDIUM": "Q4_K_M", "Q4_K_SMALL": "Q4_K_S",
               "Q5_K_MEDIUM": "Q5_K_M", "Q5_K_SMALL": "Q5_K_S",
               "Q3_K_MEDIUM": "Q3_K_M", "Q3_K_SMALL": "Q3_K_S",
               "Q3_K_LARGE": "Q3_K_L"}.get(compact, compact)
    if compact in BITS_PER_WEIGHT:
        return BITS_PER_WEIGHT[compact]
    for name, bits in BITS_PER_WEIGHT.items():
        if compact.startswith(name):
            return bits
    return 4.8


__all__ = ["BITS_PER_WEIGHT", "FTYPE_NAMES", "bits_per_weight", "ftype_name"]
