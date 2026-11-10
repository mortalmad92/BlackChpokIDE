"""Рівний контекст, лише тип KV-кешу: f16 проти q8_0.

Якщо q8_0 справді швидший при однаковому контексті — типовим варто робити
саме його, а не f16 (менше VRAM І швидше).
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


def ask(port: int) -> dict:
    body = json.dumps({
        "model": "eq", "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 64, "temperature": 0.1,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer local"})
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.load(response)


def measure(plan: hw.LaunchPlan, label: str, port: int) -> float | None:
    server = rt.LocalServer(rt.ServerConfig(
        model_path=str(MODEL), port=port, plan=plan, alias="eq"))
    try:
        server.start()
        ok, detail = server.wait_ready(timeout=300)
        if not ok:
            print(f"  {label:<28} FAIL {detail[-140:]}")
            return None
        gens = []
        for _ in range(4):
            data = ask(port)
            gens.append(float((data.get("timings") or {})
                              .get("predicted_per_second") or 0.0))
        gen = statistics.median(gens[1:])
        print(f"  {label:<28} {gen:5.1f} ток/с  (прогони: "
              f"{', '.join(f'{v:.1f}' for v in gens)})")
        return gen
    finally:
        try:
            server.stop()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)


def main() -> int:
    threads = 12
    port = rt.free_port(8099)
    print("Рівний контекст 8192, різний тип KV-кешу:\n")
    f16 = measure(hw.LaunchPlan(999, 8192, threads), "8K · f16", port)
    q8 = measure(hw.LaunchPlan(999, 8192, threads, cache_type="q8_0"),
                 "8K · q8_0", port)
    print()
    print("Рівний контекст 4096:\n")
    f16b = measure(hw.LaunchPlan(999, 4096, threads), "4K · f16", port)
    q8b = measure(hw.LaunchPlan(999, 4096, threads, cache_type="q8_0"),
                  "4K · q8_0", port)
    print()
    for label, a, b in (("8K", f16, q8), ("4K", f16b, q8b)):
        if a and b:
            verdict = "швидше" if b > a else "повільніше"
            print(f"{label}: q8_0 {verdict} за f16 на {abs(b - a):.1f} ток/с "
                  f"({b / a:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
