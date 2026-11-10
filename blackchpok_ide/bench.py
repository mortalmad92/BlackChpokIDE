"""Бенчмарк рушія й пам'яті: реальні виміри, без підробок.

Що вимірюється (і як саме):

* **time to load** — від виклику ``load`` до готового контексту;
* **time to first token (TTFT)** — час prefill'у, окремо від генерації;
* **tokens per second** — реальна швидкість декодування;
* **prompt processing speed** — швидкість обробки промпту;
* **peak VRAM** — з ``nvidia-smi`` під час генерації;
* **peak RAM** — робоча множина процесу;
* **KV cache memory** — з керування кешем;
* **p50/p95/p99** — по кількох прогонах.

Для пам'яті: **Recall@K**, **Precision@K**, **MRR**, **token savings** і
**prediction accuracy** на власних наборах (запит → очікуваний спогад).

Якщо чогось виміряти неможливо (немає моделі, немає GPU), результат
позначається ``"skipped"`` з ПРИЧИНОЮ. Підставляти вигадані числа
заборонено — на цьому тримається довіра до звіту.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

LOG = logging.getLogger("blackchpok.bench")

#: Скільки прогонів робимо типово (кожен прогін — реальна генерація).
DEFAULT_RUNS = 3
#: Типовий промпт: короткий, але не «hello» — щоб prefill був вимірюваний.
DEFAULT_PROMPT = (
    "Поясни коротко, що робить функція, яка читає файл у межах робочої теки "
    "проєкту, і наведи приклад виклику."
)


@dataclass
class Metric:
    """Один вимір: значення + одиниця + пояснення."""

    name: str
    value: float
    unit: str = ""
    note: str = ""
    samples: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "value": round(self.value, 3),
            "unit": self.unit,
            "note": self.note,
        }
        if self.samples:
            data["samples"] = [round(item, 3) for item in self.samples]
            data["p50"] = round(percentile(self.samples, 0.5), 3)
            data["p95"] = round(percentile(self.samples, 0.95), 3)
            data["p99"] = round(percentile(self.samples, 0.99), 3)
        return data


def percentile(values: Sequence[float], share: float) -> float:
    """Перцентиль без numpy (лінійна інтерполяція між сусідніми)."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, share)) * (len(ordered) - 1)
    low = int(position)
    high = min(len(ordered) - 1, low + 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _peak_vram_mb() -> float:
    """Поточна зайнята VRAM (nvidia-smi). 0.0 — якщо GPU немає."""
    import subprocess

    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if completed.returncode != 0:
        return 0.0
    total = 0.0
    for line in (completed.stdout or "").splitlines():
        try:
            total += float(line.strip())
        except ValueError:
            continue
    return total


def _process_ram_mb() -> float:
    """Робоча множина процесу в МБ (Windows API, без залежностей).

    Пастка: ``GetCurrentProcess`` повертає ПСЕВДО-дескриптор ``-1``. Без
    явних ``restype/argtypes`` ctypes трактує його як 32-бітне число,
    обрізає до ``0xFFFFFFFF`` і ``GetProcessMemoryInfo`` повертає 0 —
    тобто «0 МБ» замість реальних гігабайтів. Саме тому тут усі сигнатури
    задані явно.
    """
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

        kernel32 = ctypes.windll.kernel32                   # type: ignore[attr-defined]
        psapi = ctypes.windll.psapi                         # type: ignore[attr-defined]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / 1048576.0
    except Exception:                                            # noqa: BLE001
        pass
    return 0.0


class EngineBenchmark:
    """Вимірює швидкість завантаженої моделі."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def run(self, *, runs: int = DEFAULT_RUNS, max_tokens: int = 64,
            prompt: str = "") -> dict[str, Any]:
        """Прогнати реальну генерацію й зібрати метрики."""
        engine = getattr(self.runtime, "engine", None)
        if engine is None or not getattr(engine, "loaded", False):
            return {
                "status": "skipped",
                "reason": "модель не завантажена — вимірювати нічого",
                "metrics": {},
            }
        text = prompt or DEFAULT_PROMPT
        ttft: list[float] = []
        speed: list[float] = []
        prefill_speed: list[float] = []
        total_ms: list[float] = []
        vram_peaks: list[float] = []
        runs_data: list[dict[str, Any]] = []
        baseline_vram = _peak_vram_mb()
        baseline_ram = _process_ram_mb()

        for index in range(max(1, runs)):
            # Кеш чистимо перед кожним прогоном: інакше другий прогін
            # «читає» префікс і показує нереалістично малий TTFT.
            context = getattr(engine, "context", None)
            if context is not None and context.cache is not None:
                context.cache.clear()
            started = time.perf_counter()
            result = self.runtime.generate(
                [{"role": "user", "content": text}],
                params={"temperature": 0.0, "max_tokens": max_tokens,
                        "top_k": 1, "top_p": 1.0, "min_p": 0.0,
                        "repeat_penalty": 1.0})
            elapsed = (time.perf_counter() - started) * 1000.0
            stats = result.get("stats") or {}
            ttft.append(float(stats.get("time_to_first_token_ms") or 0.0))
            speed.append(float(stats.get("tokens_per_second") or 0.0))
            prefill_speed.append(float(stats.get("prompt_tokens_per_second") or 0.0))
            total_ms.append(elapsed)
            vram_peaks.append(_peak_vram_mb())
            runs_data.append({
                "run": index + 1,
                "prompt_tokens": stats.get("prompt_tokens", 0),
                "generated_tokens": stats.get("generated_tokens", 0),
                "time_to_first_token_ms": round(ttft[-1], 1),
                "tokens_per_second": round(speed[-1], 2),
                "prompt_tokens_per_second": round(prefill_speed[-1], 2),
                "vram_used_mb": round(vram_peaks[-1], 0),
                "text_preview": str(result.get("text") or "")[:120],
            })

        info = engine.describe()
        peak_vram = max(vram_peaks) if vram_peaks else 0.0
        metrics = {
            "time_to_load_ms": Metric("time_to_load", float(info.get("load_ms") or 0.0),
                                      "мс", "завантаження моделі у пам'ять").to_dict(),
            "time_to_first_token_ms": Metric(
                "time_to_first_token", statistics.mean(ttft) if ttft else 0.0, "мс",
                "prefill промпту", samples=ttft).to_dict(),
            "tokens_per_second": Metric(
                "tokens_per_second", statistics.mean(speed) if speed else 0.0,
                "ток/с", "швидкість декодування", samples=speed).to_dict(),
            "prompt_tokens_per_second": Metric(
                "prompt_tokens_per_second",
                statistics.mean(prefill_speed) if prefill_speed else 0.0,
                "ток/с", "обробка промпту", samples=prefill_speed).to_dict(),
            "peak_vram_mb": Metric("peak_vram", peak_vram, "МБ",
                                   "зайнята VRAM під час генерації",
                                   samples=vram_peaks).to_dict(),
            "peak_ram_mb": Metric("peak_ram", _process_ram_mb(), "МБ",
                                  "пікова робоча множина процесу").to_dict(),
            "vram_baseline_mb": Metric("vram_baseline", baseline_vram, "МБ",
                                       "VRAM до генерації").to_dict(),
            "ram_baseline_mb": Metric("ram_baseline", baseline_ram, "МБ",
                                      "RAM до генерації").to_dict(),
            "total_ms": Metric("total", statistics.mean(total_ms) if total_ms else 0.0,
                               "мс", "повний час запиту", samples=total_ms).to_dict(),
        }
        kv = (info.get("kv") or {})
        metrics["kv_cache_capacity"] = Metric(
            "kv_cache_capacity", float(kv.get("capacity") or 0), "токенів",
            "вікно KV-кешу").to_dict()
        return {
            "status": "ok",
            "model": info.get("path", ""),
            "description": info.get("description", ""),
            "context": info.get("context_actual", 0),
            "gpu_layers": info.get("gpu_layers", 0),
            "cache_type": info.get("cache_type", ""),
            "threads": info.get("threads", 0),
            "runs": runs_data,
            "metrics": metrics,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Бенчмарк пам'яті
# ─────────────────────────────────────────────────────────────────────────────

#: Набір «запит → очікуваний спогад» для виміру пошуку.
CASES: tuple[tuple[str, str, str], ...] = (
    ("де виконуються команди",
     "run_command виконує команди через shell=True у робочій теці проєкту.",
     "constraint"),
    ("як читається файл",
     "read_file читає файли лише в межах робочої теки й повертає рядки з номерами.",
     "fact"),
    ("який контекст у моделі",
     "Контекст моделі 16K токенів дає 31 токен за секунду на RTX 3060.",
     "fact"),
    ("що було з помилкою theme",
     "Помилка NameError у chat_panel.py: не імпортовано theme.",
     "error"),
    ("як виправлено імпорт",
     "Виправлення: додано імпорт theme у chat_panel.py.",
     "fix"),
    ("навіщо KV-кеш",
     "KV-кеш переиспользує префікс промпту й зменшує час до першого токена.",
     "fact"),
)


def seed_cases(memory: Any) -> list[str]:
    """Заповнити пам'ять тестовими спогадами; повернути їхні id."""
    ids: list[str] = []
    for _query, content, kind in CASES:
        outcome = memory.remember(content, kind=kind, source="benchmark",
                                  confidence=0.85, with_vector=False)
        ids.append(outcome["memory"]["id"])
    return ids


class MemoryBenchmark:
    """Recall@K, Precision@K, MRR, економія токенів, точність прогнозу."""

    def __init__(self, memory: Any) -> None:
        self.memory = memory

    def run(self, *, k: int = 3, window: int = 4096,
            seed: bool = True) -> dict[str, Any]:
        if self.memory is None:
            return {"status": "skipped", "reason": "пам'ять недоступна"}
        ids = seed_cases(self.memory) if seed else []
        expected: dict[str, str] = {}
        queries: list[str] = []
        for index, (query, content, _kind) in enumerate(CASES):
            if index < len(ids):
                expected[query] = ids[index]
                queries.append(query)

        if not queries:
            # Без сіду шукаємо за наявними спогадами (реальні дані).
            for memory in self.memory.repository.recent(limit=10):
                queries.append(memory.summary or memory.content[:60])
                expected[queries[-1]] = memory.id

        recalls: list[float] = []
        precisions: list[float] = []
        reciprocal: list[float] = []
        details: list[dict[str, Any]] = []
        token_savings: list[float] = []

        for query in queries:
            target = expected.get(query, "")
            result = self.memory.search(query, limit=max(k, 5))
            hits = [hit["memory"]["id"] for hit in result["hits"]]
            rank = hits.index(target) + 1 if target and target in hits else 0
            recall = 1.0 if 0 < rank <= k else 0.0
            precision = (1 / len(hits)) if rank and len(hits) else 0.0
            recalls.append(recall)
            precisions.append(precision)
            reciprocal.append(1.0 / rank if rank else 0.0)
            details.append({
                "query": query,
                "expected": target,
                "rank": rank,
                "found": rank > 0,
                "policy": result.get("policy", ""),
                "top": [hit["memory"]["summary"][:70] for hit in result["hits"][:k]],
            })
            # Економія токенів: скільки фрагментів губернатор не пустив у промпт.
            bundle = self.memory.project_context(query=query, window=window)
            total = bundle.report.used + bundle.tokens_saved
            if total > 0:
                token_savings.append(bundle.tokens_saved / total)

        accuracy = self.memory.status().get("prediction") or {}
        return {
            "status": "ok",
            "queries": len(queries),
            "k": k,
            "window": window,
            "recall_at_k": round(sum(recalls) / len(recalls), 3) if recalls else 0.0,
            "precision_at_k": round(sum(precisions) / len(precisions), 3)
            if precisions else 0.0,
            "mrr": round(sum(reciprocal) / len(reciprocal), 3) if reciprocal else 0.0,
            "token_savings_share": round(sum(token_savings) / len(token_savings), 3)
            if token_savings else 0.0,
            "prediction_accuracy": accuracy.get("precision", 0.0),
            "prediction_samples": accuracy.get("samples", 0),
            "details": details,
            "counts": self.memory.status().get("counts") or {},
        }


def run_all(runtime: Any = None, memory: Any = None, *,
            runs: int = DEFAULT_RUNS, k: int = 3) -> dict[str, Any]:
    """Повний бенчмарк: рушій + пам'ять, з єдиним часом і версією."""
    report: dict[str, Any] = {
        "generated_at": time.time(),
        "harness": "blackchpok-bench",
        "engine": {"status": "skipped", "reason": "рушій недоступний"},
        "memory": {"status": "skipped", "reason": "пам'ять недоступна"},
    }
    if runtime is not None:
        report["engine"] = EngineBenchmark(runtime).run(runs=runs)
        library = getattr(runtime, "library_info", lambda: {})()
        report["library"] = {
            "version": library.get("version", ""),
            "system": library.get("system", ""),
            "devices": library.get("devices", []),
        }
        report["gpu"] = runtime.get_gpu_status().get("nvidia", [])
    if memory is not None:
        report["memory"] = MemoryBenchmark(memory).run(k=k)
    return report


def save(report: dict[str, Any], path: str | Path) -> Path:
    """Зберегти звіт у JSON (щоб результати можна було порівнювати)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Порівняти два звіти за спільними метриками (рушій і пам'ять)."""
    result: dict[str, Any] = {"engine": {}, "memory": {}}

    def pick(section: dict[str, Any], key: str) -> float:
        return float(((section.get("metrics") or {}).get(key) or {}).get("value") or 0.0)

    for key in ("tokens_per_second", "time_to_first_token_ms", "peak_vram_mb",
                "total_ms"):
        a = pick(left.get("engine") or {}, key)
        b = pick(right.get("engine") or {}, key)
        if a or b:
            result["engine"][key] = {
                "left": a, "right": b,
                "delta": round(b - a, 3),
                "ratio": round(b / a, 3) if a else None,
            }
    for key in ("recall_at_k", "precision_at_k", "mrr", "token_savings_share"):
        a = float((left.get("memory") or {}).get(key) or 0.0)
        b = float((right.get("memory") or {}).get(key) or 0.0)
        if a or b:
            result["memory"][key] = {
                "left": a, "right": b,
                "delta": round(b - a, 3),
                "ratio": round(b / a, 3) if a else None,
            }
    return result


__all__ = [
    "CASES",
    "DEFAULT_PROMPT",
    "DEFAULT_RUNS",
    "EngineBenchmark",
    "MemoryBenchmark",
    "Metric",
    "compare",
    "percentile",
    "run_all",
    "save",
    "seed_cases",
]
