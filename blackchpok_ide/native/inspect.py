"""Діагностика моделі без завантаження ваг: метадані, quantization, прогнози.

Модуль поєднує два джерела істини:

* :mod:`.gguf` — швидке читання заголовка (архітектура, шари, контекст,
  словник, шаблон чату);
* :mod:`..hardware` — профіль заліза й бюджети RAM/VRAM.

На виході — :class:`ModelReport` із чесними прогнозами: скільки пам'яті
займуть ваги, KV-кеш і буфери, скільки шарів реально покласти на GPU і
чи модель узагалі запуститься на цьому залізі. Нічого не вигадуємо: якщо
метаданих немає, поля лишаються нульовими й позначаються як «невідомо».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hardware import GB, RUNTIME_OVERHEAD_GB, HardwareProfile
from . import gguf

LOG = logging.getLogger("blackchpok.native.inspect")

#: Скільки VRAM лишаємо драйверу й робочому столу.
VRAM_RESERVE_GB = 1.0
#: Резерв системної пам'яті.
RAM_RESERVE_GB = 3.0
#: Частка вільної RAM, яку дозволяємо зайняти моделі.
RAM_SHARE = 0.75
#: Байтів на елемент KV-кешу для різних типів.
KV_BYTES = {"f16": 2.0, "bf16": 2.0, "f32": 4.0, "q8_0": 1.0,
            "q5_1": 0.75, "q5_0": 0.75, "q4_1": 0.625, "q4_0": 0.625,
            "iq4_nl": 0.625}


@dataclass
class ModelReport:
    """Усе, що IDE знає про модель ПЕРЕД завантаженням."""

    path: str = ""
    exists: bool = False
    file_size_gb: float = 0.0
    error: str = ""

    architecture: str = ""
    name: str = ""
    quant: str = ""
    bits_per_weight: float = 4.8
    layer_count: int = 0
    context_train: int = 0
    embedding_length: int = 0
    head_count: int = 0
    head_count_kv: int = 0
    vocab_size: int = 0
    tokenizer_model: str = ""
    parameter_count: int = 0
    has_chat_template: bool = False
    is_embedding: bool = False
    is_vision_projector: bool = False
    meta_version: int = 0

    #: Прогнози для конкретного заліза (0 = не рахували).
    weights_gb: float = 0.0
    kv_gb: float = 0.0
    overhead_gb: float = 0.0
    suggested_ctx: int = 0
    suggested_gpu_layers: int = 0
    suggested_batch: int = 0
    suggested_threads: int = 0
    kv_cache_type: str = "f16"
    kv_in_ram: bool = False
    vram_needed_gb: float = 0.0
    ram_needed_gb: float = 0.0
    fits: str = "unknown"           # gpu | hybrid | cpu | impossible | unknown
    notes: list[str] = field(default_factory=list)
    raw_meta: dict[str, Any] = field(default_factory=dict)

    # ── похідні ────────────────────────────────────────────────────────────
    @property
    def params_b(self) -> float:
        """Параметрів у мільярдах (з метаданих або оцінка за розміром)."""
        if self.parameter_count:
            return self.parameter_count / 1e9
        if self.file_size_gb and self.bits_per_weight:
            return self.file_size_gb * 8.0 * 1024 ** 3 / (self.bits_per_weight * 1e9)
        return 0.0

    @property
    def display_name(self) -> str:
        return self.name or Path(self.path).stem

    def to_dict(self) -> dict[str, Any]:
        data = {
            key: value for key, value in self.__dict__.items()
            if key not in {"raw_meta", "notes"}
        }
        data.update(
            {
                "display_name": self.display_name,
                "params_b": round(self.params_b, 2),
                "notes": list(self.notes),
                "file_size_gb": round(self.file_size_gb, 2),
                "weights_gb": round(self.weights_gb, 2),
                "kv_gb": round(self.kv_gb, 2),
                "overhead_gb": round(self.overhead_gb, 2),
                "vram_needed_gb": round(self.vram_needed_gb, 2),
                "ram_needed_gb": round(self.ram_needed_gb, 2),
            }
        )
        return data

    def summary(self) -> str:
        """Один рядок для списку моделей."""
        parts = [self.display_name]
        if self.quant:
            parts.append(self.quant)
        if self.params_b:
            parts.append(f"{self.params_b:.1f}B")
        if self.context_train:
            parts.append(f"ctx {self.context_train // 1024}K")
        parts.append(f"{self.file_size_gb:.1f} ГБ")
        return " · ".join(parts)


def inspect(path: str | Path, *, profile: HardwareProfile | None = None,
            ctx: int = 0) -> ModelReport:
    """Прочитати метадані моделі й (за потреби) спрогнозувати розміщення.

    ``ctx`` — бажаний контекст; 0 означає «підібрати автоматично».
    """
    target = Path(path)
    report = ModelReport(path=str(target))
    if not target.exists():
        report.error = "Файл не знайдено."
        return report
    report.exists = True
    try:
        report.file_size_gb = target.stat().st_size / GB
    except OSError as exc:
        report.error = str(exc)
        return report

    # Кешований варіант: ``inspect`` викликається для КОЖНОЇ моделі при
    # кожному ``ModelManager.refresh`` (а той — кілька разів за старт).
    # Заміряно: 22 розбори метаданих = 2257 мс із 6.3 с старту.
    # ``verify_integrity`` нижче навмисно лишається на ``read_meta_safe``:
    # там перевіряють ЩОЙНО завантажений файл, і кеш приховав би обрив.
    meta = gguf.read_meta_cached(target)
    if "_error" in meta.values:
        report.error = str(meta.values["_error"])
        return report

    report.meta_version = meta.version
    report.architecture = meta.architecture
    report.name = meta.name
    report.quant = meta.quant
    from ._quant import bits_per_weight

    report.bits_per_weight = bits_per_weight(report.quant)
    report.layer_count = meta.layer_count
    report.context_train = meta.context_length
    report.embedding_length = meta.embedding_length
    report.head_count = meta.head_count
    report.head_count_kv = meta.head_count_kv
    report.vocab_size = meta.vocab_size
    report.tokenizer_model = meta.tokenizer_model
    report.parameter_count = meta.parameter_count
    report.has_chat_template = meta.has_chat_template
    report.is_embedding = meta.is_embedding_model
    report.is_vision_projector = meta.is_vision_projector
    report.raw_meta = {
        "tensor_count": meta.tensor_count,
        "kv_count": meta.kv_count,
        "version": meta.version,
        "tokenizer_model": meta.tokenizer_model,
    }
    if not report.layer_count:
        report.notes.append("У метаданих немає кількості шарів — offload рахуємо за оцінкою.")
    if not report.has_chat_template:
        report.notes.append("Немає шаблону чату в GGUF: потрібен адаптер формату повідомлень.")

    if profile is not None:
        predict(report, profile, ctx=ctx)
    return report


def kv_cache_gb(report: ModelReport, ctx: int, cache_type: str = "f16") -> float:
    """Точний обсяг KV-кешу з метаданих моделі.

    Формула llama.cpp: на кожен токен і шар зберігаються K і V по
    ``head_count_kv * embedding_length / head_count`` елементів.
    """
    if not (report.layer_count and report.head_count and ctx > 0):
        return 0.0
    head_dim = report.embedding_length / max(report.head_count, 1)
    kv_heads = min(report.head_count_kv or report.head_count, report.head_count)
    elements = report.layer_count * kv_heads * head_dim * 2      # K + V
    bytes_per_element = KV_BYTES.get(cache_type, 2.0)
    return elements * ctx * bytes_per_element / GB


def predict(report: ModelReport, profile: HardwareProfile,
            *, ctx: int = 0) -> ModelReport:
    """Заповнити прогнози розміщення моделі для заданого заліза."""
    report.weights_gb = report.file_size_gb
    report.overhead_gb = RUNTIME_OVERHEAD_GB
    report.suggested_threads = max(2, min(profile.cpu_threads or 4, 16))

    vram_budget = max(0.0, (profile.vram_gb or 0.0) - VRAM_RESERVE_GB)
    ram_total = profile.ram_total_gb or 0.0
    ram_budget = max(0.0, min(ram_total - RAM_RESERVE_GB, ram_total * RAM_SHARE))

    if report.is_vision_projector:
        report.fits = "projector"
        report.notes.append("Це файл проєктора (mmproj), а не окрема модель.")
        return report

    # 1. Підбір контексту: найбільший, що лишає місце під ваги.
    choices = _ctx_candidates(report.context_train, ctx)
    chosen_ctx, chosen_cache, kv_in_ram = _pick_ctx(report, choices, vram_budget, ram_budget)
    report.suggested_ctx = chosen_ctx
    report.kv_cache_type = chosen_cache
    report.kv_in_ram = kv_in_ram
    report.kv_gb = kv_cache_gb(report, chosen_ctx, chosen_cache)
    report.suggested_batch = 512 if vram_budget >= 8 else 256

    # 2. Скільки шарів покласти на GPU.
    full_vram = report.weights_gb + report.kv_gb + report.overhead_gb
    if vram_budget <= 0:
        report.fits = "cpu"
        report.suggested_gpu_layers = 0
        report.ram_needed_gb = report.weights_gb + report.kv_gb + report.overhead_gb
        report.notes.append("GPU не знайдено — генерація йтиме на CPU.")
    elif full_vram <= vram_budget:
        report.fits = "gpu"
        # ``-1`` = «усі шари РАЗОМ із вихідним шаром». Передавати рівно
        # ``layer_count`` не можна: у llama.cpp це число блоків
        # трансформера, а lm_head лишається на CPU. Заміряно на 14B Q4_K_M
        # (RTX 3060): 48 → 25.6 ток/с, ``-1`` → 31.2 ток/с.
        report.suggested_gpu_layers = -1
        report.vram_needed_gb = full_vram
        report.ram_needed_gb = report.overhead_gb
    else:
        layers = _partial_layers(report, vram_budget)
        report.suggested_gpu_layers = layers
        if layers >= max(4, report.layer_count // 3 if report.layer_count else 4):
            report.fits = "hybrid"
            share = layers / max(report.layer_count, 1)
            report.vram_needed_gb = (report.weights_gb * share + report.kv_gb * share
                                     + report.overhead_gb)
            report.ram_needed_gb = (report.weights_gb * (1 - share) + report.kv_gb * share
                                    + report.overhead_gb)
            report.notes.append(
                f"Модель не влазить у VRAM повністю: {layers} з "
                f"{report.layer_count} шарів на GPU.")
        elif report.weights_gb + report.kv_gb + report.overhead_gb <= ram_budget:
            report.fits = "cpu"
            report.suggested_gpu_layers = max(0, layers)
            report.ram_needed_gb = report.weights_gb + report.kv_gb + report.overhead_gb
            report.notes.append("Замало VRAM для відчутного прискорення — режим CPU.")
        else:
            report.fits = "impossible"
            report.ram_needed_gb = report.weights_gb + report.kv_gb + report.overhead_gb
            report.notes.append(
                f"Не вистачає пам'яті: потрібно ~{report.ram_needed_gb:.1f} ГБ, "
                f"доступно ~{max(vram_budget, ram_budget):.1f} ГБ.")
    if report.fits != "impossible" and report.ram_needed_gb > ram_budget > 0:
        report.notes.append(
            f"Прогноз RAM {report.ram_needed_gb:.1f} ГБ перевищує бюджет "
            f"{ram_budget:.1f} ГБ — можливий swap.")
    return report


def _ctx_candidates(context_train: int, want: int) -> list[int]:
    """Драбина контекстів: від більшого до меншого, з урахуванням тренування.

    ВАЖЛИВО про явний ``want``. Раніше при заданому ``ctx`` поверталось
    РІВНО ОДНЕ значення (``[min(want, ceiling)]``), і ``_pick_ctx`` фізично
    не міг зменшити контекст: якщо він не влазив у VRAM, функція все одно
    віддавала його ж як ``fallback``. Тобто «підбір під залізо» не працював
    саме тоді, коли він найпотрібніший — коли користувач явно попросив
    великий контекст (заміряно: запит 32768 при 12 ГБ VRAM давав 32768 же).

    Тепер явний ``want`` — це СТЕЛЯ драбини: беремо найбільший із тих, що
    не перевищують прохання. Хто просить менше за нижній щабель (напр.
    3000), отримує рівно своє число.
    """
    ladder = [32768, 24576, 16384, 12288, 8192, 6144, 4096, 2048]
    ceiling = context_train or 32768
    steps = [value for value in ladder if value <= ceiling]
    if want:
        wanted = min(int(want), ceiling)
        steps = [value for value in steps if value <= wanted]
        if not steps or steps[0] < wanted:
            steps = sorted({wanted, *steps}, reverse=True)
        return steps
    return steps or [2048]


def _pick_ctx(report: ModelReport, choices: list[int],
              vram_budget: float, ram_budget: float) -> tuple[int, str, bool]:
    """Обрати контекст і тип KV-кешу, які реально влізають."""
    fallback = choices[-1] if choices else 2048
    # Спершу повністю у VRAM зі стиснутим кешем (дає більший контекст).
    for cache in ("q8_0", "f16"):
        for ctx in choices:
            kv = kv_cache_gb(report, ctx, cache)
            if report.weights_gb + kv + RUNTIME_OVERHEAD_GB <= vram_budget:
                return ctx, cache, False
    # Далі — ваги у VRAM, кеш у RAM (--no-kv-offload).
    for ctx in choices:
        kv = kv_cache_gb(report, ctx, "q8_0")
        if report.weights_gb + RUNTIME_OVERHEAD_GB <= vram_budget and \
                kv + RUNTIME_OVERHEAD_GB <= ram_budget:
            return ctx, "q8_0", True
    # Останнє: усе в RAM.
    for ctx in choices:
        kv = kv_cache_gb(report, ctx, "q8_0")
        if report.weights_gb + kv + RUNTIME_OVERHEAD_GB <= ram_budget:
            return ctx, "q8_0", False
    return fallback, "q8_0", False


def _partial_layers(report: ModelReport, vram_budget: float) -> int:
    """Скільки шарів влазить у VRAM, якщо ваги не влазять повністю."""
    if not report.layer_count:
        return 0
    per_layer = report.weights_gb / report.layer_count
    if per_layer <= 0:
        return 0
    free = vram_budget - report.overhead_gb - report.kv_gb * 0.5
    if free <= 0:
        return 0
    return max(0, min(report.layer_count, int(free / per_layer)))


# ─────────────────────────────────────────────────────────────────────────────
# Пакетна перевірка
# ─────────────────────────────────────────────────────────────────────────────

def inspect_many(paths: list[str | Path], *,
                 profile: HardwareProfile | None = None) -> list[ModelReport]:
    """Прочитати кілька файлів; збій одного не валить решту."""
    reports: list[ModelReport] = []
    for path in paths:
        try:
            reports.append(inspect(path, profile=profile))
        except Exception as exc:                     # noqa: BLE001 - список не має падати
            LOG.debug("Не вдалось прочитати %s", path, exc_info=True)
            reports.append(ModelReport(path=str(path), error=f"{type(exc).__name__}: {exc}"))
    return reports


def verify_integrity(path: str | Path, *, expected_size: int = 0,
                     chunk: int = 1 << 20) -> dict[str, Any]:
    """Перевірити цілісність файлу моделі.

    Перевіряємо три речі, які реально ловлять обірване завантаження:
    магія GGUF на початку, читабельність метаданих і (якщо відомий)
    очікуваний розмір. Повний SHA-256 рахується лише на вимогу — на
    14-гігабайтному файлі це десятки секунд, і робити це мовчки не можна.
    """
    target = Path(path)
    result: dict[str, Any] = {"path": str(target), "ok": False, "problems": []}
    if not target.exists():
        result["problems"].append("Файл відсутній.")
        return result
    try:
        size = target.stat().st_size
    except OSError as exc:
        result["problems"].append(f"Немає доступу: {exc}")
        return result
    result["size_bytes"] = size
    result["size_gb"] = round(size / GB, 2)
    if size == 0:
        result["problems"].append("Файл порожній.")
        return result
    if expected_size and size != expected_size:
        result["problems"].append(
            f"Розмір {size} не збігається з очікуваним {expected_size} "
            f"(не докачано {max(0, expected_size - size)} байт).")
    if not gguf.looks_like_gguf(target):
        result["problems"].append("Немає магії GGUF — це не файл моделі або він обірваний.")
        return result
    meta = gguf.read_meta_safe(target)
    if "_error" in meta.values:
        result["problems"].append(f"Метадані не читаються: {meta.values['_error']}")
        return result
    result["architecture"] = meta.architecture
    result["quant"], result["layers"] = meta.quant, meta.layer_count
    result["tensors"] = meta.tensor_count
    if meta.tensor_count <= 0:
        result["problems"].append("У файлі немає тензорів — ваги не завантажені.")
    result["ok"] = not result["problems"]
    return result


def sha256_of(path: str | Path, *, chunk: int = 1 << 20,
              on_progress: "Any | None" = None) -> str:
    """SHA-256 файлу (для звірки з опублікованим хешем)."""
    import hashlib

    digest = hashlib.sha256()
    total = Path(path).stat().st_size
    done = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
            done += len(block)
            if on_progress is not None:
                on_progress(done, total)
    return digest.hexdigest()


__all__ = [
    "KV_BYTES",
    "ModelReport",
    "inspect",
    "inspect_many",
    "kv_cache_gb",
    "predict",
    "sha256_of",
    "verify_integrity",
]
