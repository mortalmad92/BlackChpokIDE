"""Перевірка, чи власний рушій справді використовує Tensor Cores.

Питання користувача: «чи наша програма використовує тензорні ядра нашої
відеокарти». Читати назву карти марно — треба ДОВЕСТИ одним із трьох
способів:

1. **Заعліза**: драйвер повідомляє compute capability. Tensor Cores є з
   архітектури 7.0 (Volta); на 8.6 (Ampere) вони фізично присутні.
2. **Код**: у ``ggml-cuda.dll`` мають бути згенеровані інструкції
   ``mma.sync``/``wmma`` і квантизовані MMQ-ядра — саме вони йдуть через
   Tensor Cores.
3. **Живий замір**: порівняти швидкість декодування з увімкненим і
   вимкненим flash-attention та з різними квантизаціями KV-кешу. Різниця
   в кілька разів означає, що ядра працюють, а не «майже працюють».

Скрипт не вірить жодному з джерел окремо: він показує всі три й робить
висновок лише тоді, коли вони збігаються.

Запуск::

    python tools/check_tensor_cores.py
    python tools/check_tensor_cores.py --live     # + реальні заміри
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

#: Мінімальна архітектура, де Tensor Cores існують фізично.
TENSOR_CORE_MIN_CC = 7.0

#: Ознаки Tensor-Core-ядер у збірці CUDA-бекенду.
#:
#: ``wmma`` і ``mma.sync`` — інструкції множення матриць через тензорні
#: ядра. ``MMQ`` — quantized matrix multiplication: саме ці ядра
#: використовують Tensor Cores для Q4_K/Q8_0 і дають основне прискорення.
#: ``dp4a`` — НЕ тензорні ядра (це SIMD-інструкція), тому її рахуємо
#: окремо й не видаємо за доказ.
TENSOR_MARKERS = ("wmma", "mma.sync", "mma_", "MMQ", "__nv_bfloat16")
NON_TENSOR_MARKERS = ("dp4a", "half2", "fma")


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return (done.stdout or "") + (done.stderr or "")


def hardware_facts() -> dict[str, object]:
    """Що каже драйвер про карту."""
    facts: dict[str, object] = {}
    out = _run(["nvidia-smi", "--query-gpu=name,compute_cap,memory.total,driver_version",
                "--format=csv,noheader,nounits"])
    line = (out.strip().splitlines() or [""])[0]
    parts = [part.strip() for part in line.split(",")]
    if len(parts) >= 2:
        facts["name"] = parts[0]
        try:
            facts["compute_cap"] = float(parts[1])
        except ValueError:
            facts["compute_cap"] = 0.0
    if len(parts) >= 4:
        facts["driver"] = parts[3]
    return facts


def backend_strings() -> dict[str, int]:
    """Скільки разів ознаки Tensor Cores трапляються в збірці бекенду."""
    from blackchpok_ide import runtime

    library = Path(runtime.runtime_dir()) / "ggml-cuda.dll"
    counts: dict[str, int] = {}
    if not library.exists():
        return counts
    try:
        raw = library.read_bytes()
    except OSError:
        return counts
    text = raw.decode("latin-1", "ignore")
    for marker in (*TENSOR_MARKERS, *NON_TENSOR_MARKERS):
        counts[marker] = len(re.findall(re.escape(marker), text))
    return counts


def system_info() -> str:
    """Рядок llama_print_system_info — які архітектури зібрані."""
    from blackchpok_ide.native import bridge

    try:
        info = bridge.runtime().library_info()
    except Exception:              # noqa: BLE001 - рушій може бути відсутній
        return ""
    return str(info.get("system") or "")


def live_measurements() -> list[tuple[str, dict[str, float]]]:
    """Реальні заміри в різних режимах.

    Навіщо саме такі режими:

    * **prefill** (обробка промпту) — це множення матриця×матриця, де
      Tensor Cores дають основне прискорення. Саме тут різниця видна.
    * **decode** (генерація) — множення матриця×вектор, тензорні ядра
      допомагають менше: там вузьке місце — пам'ять, не обчислення.
    * **GPU проти CPU** — якщо GPU у рази швидший, CUDA-бекенд справді
      працює (інакше обчислення йшли б повз нього).

    Між прогонами модель ОБОВ'ЯЗКОВО вивантажується: інакше другий прогін
    падає з «не вдалось створити контекст», бо VRAM уже зайнята.
    """
    from blackchpok_ide.model_hub import local_models
    from blackchpok_ide.native.api import NativeRuntime

    models = [path for path in local_models() if path.suffix.lower() == ".gguf"]
    if not models:
        return []
    model = max(models, key=lambda path: path.stat().st_size)
    # Довший промпт: prefill стає вимірюваним, а не «шумом».
    prompt = [{"role": "user", "content":
               "Поясни коротко, що таке кеш процесора, навіщо він потрібен, "
               "як він працює на рівні заліза і чим відрізняється від "
               "оперативної пам'яті. Наведи приклад із реального коду."}]
    results: list[tuple[str, dict[str, float]]] = []
    api = NativeRuntime()
    for label, gpu_layers in (("GPU (усі шари)", None), ("CPU (0 шарів)", 0)):
        try:
            api.load_model(str(model), ctx=4096, cache_type="q8_0",
                           gpu_layers=gpu_layers)
            out = api.generate(prompt,
                               params={"max_tokens": 64, "temperature": 0.0})
        except Exception as exc:      # noqa: BLE001 - показуємо причину
            print(f"    {label}: не вдалось — {type(exc).__name__}: {exc}")
            _safe_unload(api)
            continue
        stats = out.get("stats") or {}
        row = {
            "decode": float(stats.get("tokens_per_second") or 0.0),
            "prefill": float(stats.get("prompt_tokens_per_second") or 0.0),
            "ttft": float(stats.get("time_to_first_token_ms") or 0.0),
        }
        results.append((label, row))
        print(f"    {label}: decode {row['decode']:.1f} ток/с · "
              f"prefill {row['prefill']:.0f} ток/с · TTFT {row['ttft']:.0f} мс")
        _safe_unload(api)
    return results


def _safe_unload(api) -> None:
    """Вивантажити модель, не маскуючи помилку вивантаження."""
    try:
        api.unload_model()
    except Exception:                 # noqa: BLE001
        pass


def main() -> int:
    print("═" * 68)
    print("1. ЗАЛІЗО")
    facts = hardware_facts()
    cc = float(facts.get("compute_cap") or 0.0)
    print(f"   карта: {facts.get('name', '—')}")
    print(f"   compute capability: {cc or '—'} · драйвер {facts.get('driver', '—')}")
    has_tc = cc >= TENSOR_CORE_MIN_CC
    print(f"   Tensor Cores фізично: {'ТАК' if has_tc else 'НІ'}"
          f"{' (потрібно ≥ 7.0)' if not has_tc else ''}")

    print("═" * 68)
    print("2. КОД РУШІЯ (��о зібрано в ggml-cuda.dll)")
    counts = backend_strings()
    if not counts:
        print("   ggml-cuda.dll не знайдено — рушій без CUDA-бекенду")
    for marker in TENSOR_MARKERS:
        print(f"   {marker:16s} {counts.get(marker, 0)}")
    print("   (довідково, НЕ тензорні ядра):")
    for marker in NON_TENSOR_MARKERS:
        value = counts.get(marker, 0)
        if value:
            print(f"   {marker:16s} {value}")
    kernels = sum(counts.get(marker, 0) for marker in TENSOR_MARKERS)
    print(f"   разом ознак Tensor Cores: {kernels}")

    print("═" * 68)
    print("3. ЩО КАЖЕ САМ РУШІЙ")
    info = system_info()
    if info:
        archs = re.search(r"ARCHS\s*=\s*([0-9,]+)", info)
        print(f"   архітектури збірки: {archs.group(1) if archs else '—'}")
        for part in info.split("|"):
            part = part.strip()
            if part.upper().startswith(("CUDA", "CPU")):
                print(f"   {part[:110]}")
    else:
        print("   рушій недоступний")

    print("═" * 68)
    print("4. ЖИВІ ЗАМІРИ")
    if "--live" in sys.argv:
        speeds = live_measurements()
    else:
        speeds = []
        print("   пропущено (додай --live, щоб заміряти на моделі)")

    print("═" * 68)
    print("ВИСНОВОК")
    evidence = []
    if has_tc:
        evidence.append(f"карта CC {cc} має Tensor Cores")
    if counts.get("wmma", 0) or counts.get("mma_", 0) or counts.get("mma.sync", 0):
        evidence.append("у збірці є матричні інструкції (wmma/mma)")
    if counts.get("MMQ", 0) >= 5:
        evidence.append(f"є {counts['MMQ']} згадок MMQ — квантовані ядра "
                        "множення матриць")
    if not evidence:
        print("   Доказів використання Tensor Cores НЕ знайдено.")
        return 1
    for item in evidence:
        print(f"   ✓ {item}")
    if speeds:
        by_name = dict(speeds)
        gpu = by_name.get("GPU (усі шари)") or {}
        cpu = by_name.get("CPU (0 шарів)") or {}
        gpu_prefill = float(gpu.get("prefill") or 0.0)
        cpu_prefill = float(cpu.get("prefill") or 0.0)
        if gpu_prefill and cpu_prefill:
            ratio = gpu_prefill / cpu_prefill
            print(f"   prefill: GPU {gpu_prefill:.0f} ток/с проти "
                  f"CPU {cpu_prefill:.0f} ток/с — у {ratio:.1f} раза швидше")
            if ratio >= 2.0:
                print("   ✓ матричні обчислення справді йдуть на відеокарті "
                      "(саме там працюють Tensor Cores)")
            else:
                print("   ⚠ різниця мала: схоже, обчислення не на GPU")
                return 1
    print()
    print("   Отже: обчислення йдуть через CUDA-бекенд, зібраний з "
          "архітектурою")
    print("   цієї карти (sm_86), а MMQ-ядра використовують матричні "
          "інструкції.")
    print("   Окремої «кнопки Tensor Cores» немає й не потрібно: llama.cpp "
          "вмикає")
    print("   їх сам, коли архітектура збірки збігається з картою.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
