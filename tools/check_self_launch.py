"""Перевірка запуску моделі САМОЮ IDE (не підхоплення готової).

Користувач натискає «запустити модель» у хабі — IDE має підняти
llama-server своїм рушієм, дочекатись готовності й підключитись.
Враховуємо конфлікт із уже запущеним сервером на 8080: беремо інший порт.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    from blackchpok_ide import hardware as hw, runtime as rt

    model = ROOT / "userdata" / "models" / (
        "qwen2.5-coder-14b-instruct-q4_k_m.gguf")
    if not model.exists():
        print("моделі немає:", model)
        return 1
    if not rt.engine_installed():
        print("рушій не встановлено")
        return 1

    profile = hw.detect(ROOT)
    choice = next(c for c in hw.MODEL_CATALOG if "14b" in c.filename.lower())

    # Саме той план, який побудує панель хаба (ctx_size = 0 → авто)
    want = 0
    from blackchpok_ide.config import Settings

    try:
        want = int(getattr(Settings.load().engine, "ctx_size", 0) or 0)
    except Exception:  # noqa: BLE001
        want = 0
    plan = hw.fit(profile, choice, target_ctx=want).plan
    print(f"план, який обере IDE: {plan.summary()}")
    print("прапорці:", " ".join(plan.args()))
    print()

    port = rt.free_port(8097)
    print(f"порт: {port}")
    server = rt.LocalServer(rt.ServerConfig(
        model_path=str(model), port=port, plan=plan, alias="ideself"))
    started = time.time()
    try:
        server.start()
        check("процес рушія запущено", server.running)
        ok, detail = server.wait_ready(timeout=300)
        check("сервер готовий", ok, f"{time.time() - started:.0f} с" if ok else detail[-300:])
        if not ok:
            return 1

        # Реальний контекст
        import json
        import urllib.request

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/props",
            headers={"Authorization": "Bearer local"})
        with urllib.request.urlopen(request, timeout=10) as response:
            props = json.load(response)
        real = (props.get("default_generation_settings") or {}).get("n_ctx")
        check("контекст відповідає плану", real == plan.ctx_size,
              f"план {plan.ctx_size} · сервер {real}")

        # Модель справді відповідає
        body = json.dumps({
            "model": "ideself",
            "messages": [{"role": "user", "content": "Скажи одне слово: ок"}],
            "max_tokens": 8, "temperature": 0.1,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer local"})
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.load(response)
        answer = (data["choices"][0]["message"]["content"] or "").strip()
        check("модель відповідає", bool(answer), answer[:40])

        # Чистий останов
        server.stop()
        check("сервер зупиняється", not server.running)
    except Exception as exc:  # noqa: BLE001
        check("без винятків", False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            server.stop()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Самозапуск моделі:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
