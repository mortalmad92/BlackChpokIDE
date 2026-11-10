"""Ізольований замір: той самий контекст, різне розміщення KV-кешу.

Міняємо ЛИШЕ один параметр — де живе кеш (VRAM проти системної RAM) і
його тип. Так видно справжню ціну кожного варіанта, без впливу розміру
контексту.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import hardware as hw, runtime as rt  # noqa: E402

MODEL = ROOT / "userdata" / "models" / "qwen2.5-coder-14b-instruct-q4_k_m.gguf"
PROMPT = "Напиши функцію Python для факторіалу й коротко поясни. Українською."


def ask(port: int, prompt: str, max_tokens: int = 48) -> dict:
    body = json.dumps({
        "model": "iso", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.1,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer local"})
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.load(response)


def measure(plan: hw.LaunchPlan, label: str, port: int) -> dict | None:
    server = rt.LocalServer(rt.ServerConfig(
        model_path=str(MODEL), port=port, plan=plan, alias="iso"))
    try:
        server.start()
        ok, detail = server.wait_ready(timeout=300)
        if not ok:
            print(f"  {label:<34} старт FAIL: {detail[-160:]}")
            return None
        gens, reads = [], []
        for _ in range(3):
            data = ask(port, PROMPT)
            timings = data.get("timings") or {}
            gens.append(float(timings.get("predicted_per_second") or 0.0))
            reads.append(float(timings.get("prompt_per_second") or 0.0))
        gen = statistics.median(gens[1:])
        read = statistics.median(reads[1:])
        vram = plan.vram_hint
        print(f"  {label:<34} генерація {gen:5.1f} ток/с · "
              f"читання {read:5.0f} ток/с · VRAM≈{vram:.1f} ГБ")
        return {"gen": gen, "read": read, "label": label}
    finally:
        try:
            server.stop()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)


def main() -> int:
    profile = hw.detect(ROOT)
    choice = next(c for c in hw.MODEL_CATALOG if "14b" in c.filename.lower())
    threads = 12
    print(f"Залізо: VRAM {profile.vram_gb:.0f} ГБ · RAM {profile.ram_total_gb:.0f} ГБ")
    print(f"Модель: {choice.label} · ваги {choice.approx_gb} ГБ\n")

    variants = [
        (hw.LaunchPlan(999, 8192, threads), "8K  · KV f16 у VRAM"),
        (hw.LaunchPlan(999, 16384, threads), "16K · KV f16 у VRAM"),
        (hw.LaunchPlan(999, 16384, threads, cache_type="q8_0"),
         "16K · KV q8_0 у VRAM"),
        (hw.LaunchPlan(999, 16384, threads, cache_type="q8_0",
                       kv_in_ram=True, batch=256), "16K · KV q8_0 у RAM"),
        (hw.LaunchPlan(999, 32768, threads, cache_type="q8_0",
                       kv_in_ram=True, batch=256), "32K · KV q8_0 у RAM"),
    ]
    port = rt.free_port(8099)
    results = []
    for plan, label in variants:
        got = measure(plan, label, port)
        if got:
            results.append(got)

    print()
    if results:
        best = max(results, key=lambda r: r["gen"])
        print(f"Найшвидший варіант: {best['label']} — {best['gen']:.1f} ток/с")
        for row in results:
            delta = (row["gen"] / best["gen"] - 1) * 100
            print(f"  {row['label']:<34} {delta:+6.0f}% від найшвидшого")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
