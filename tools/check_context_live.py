"""Перевірка реальної роботи контексту під навантаженням.

Запускає справжній llama-server із планом, який обирає IDE, і міряє
реальні тайминги на довгому промпті (наближеному до роботи агента).

Запуск:  .venv\\Scripts\\python.exe tools\\check_context_live.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import hardware as hw, runtime as rt  # noqa: E402


def ask(port: int, model: str, prompt: str, *, max_tokens: int = 24) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer local"})
    started = time.time()
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.load(response)
    data["_wall"] = time.time() - started
    return data


def main() -> int:
    profile = hw.detect(ROOT)
    choice = next(c for c in hw.MODEL_CATALOG if "14b" in c.filename.lower())
    model = ROOT / "userdata" / "models" / (
        "qwen2.5-coder-14b-instruct-q4_k_m.gguf")
    if not model.exists():
        print("моделі немає:", model)
        return 1

    failures = 0
    for want in (16384, 32768):
        plan = hw.fit(profile, choice, target_ctx=want).plan
        port = rt.free_port(8099)
        print(f"\n=== налаштування {want}: {plan.summary()} · порт {port}")
        server = rt.LocalServer(rt.ServerConfig(
            model_path=str(model), port=port, plan=plan, alias="ctxtest"))
        try:
            server.start()
            ok, detail = server.wait_ready(timeout=300)
            print(f"   старт: {'OK' if ok else 'FAIL'}")
            if not ok:
                print("   ", detail[-400:])
                failures += 1
                continue
            # Фактичний контекст, з яким РЕАЛЬНО працює сервер
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/props",
                headers={"Authorization": "Bearer local"})
            with urllib.request.urlopen(request, timeout=15) as response:
                props = json.load(response)
            real_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            print(f"   n_ctx сервера: {real_ctx}")
            if real_ctx != plan.ctx_size:
                print(f"   FAIL: план {plan.ctx_size}, а сервер {real_ctx}")
                failures += 1

            # Довгий промпт: ~700 функцій ≈ 15–20k токенів
            filler = "\n".join(f"def f{i}(x): return x + {i}" for i in range(700))
            data = ask(port, "ctxtest",
                       f"Ось код:\n{filler}\n\nСкільки функцій? Відповідай числом.")
            usage = data.get("usage") or {}
            timings = data.get("timings") or {}
            answer = (data["choices"][0]["message"]["content"] or "").strip()
            print(f"   промпт {usage.get('prompt_tokens')} ток · "
                  f"відповідь {usage.get('completion_tokens')} ток · "
                  f"{data['_wall']:.0f} с")
            print(f"   читання {timings.get('prompt_per_second', 0):.0f} ток/с · "
                  f"генерація {timings.get('predicted_per_second', 0):.1f} ток/с")
            print(f"   відповідь: {answer[:70]!r}")
            if not answer:
                print("   FAIL: порожня відповідь")
                failures += 1
        finally:
            try:
                server.stop()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)

    print()
    print("Контекст наживо:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
