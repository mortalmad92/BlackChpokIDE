"""Скасування генерації у СПРАВЖНЬОМУ рушії: чи не розходиться KV-кеш.

Навіщо окремо від ``probe_cancel.py``. Той перевіряє агента проти
НЕІСНУЮЧОГО HTTP-сервера: жодного ``llama_decode`` не відбувається, тож
найнебезпечніший дефект вбудованого рушія він побачити не міг.

Дефект, який цей скрипт ловить (відтворено на RTX 3060, Qwen2.5-Coder-14B):

    скасування посеред prefill
    → рушій ЛИШАЄ пораховані ubatch-і в пам'яті (так документовано в llama.h)
    → мітка CacheManager каже 0, llama_memory_seq_pos_max каже 1535
    → наступний хід декодує з позиції 0 поверх наявних даних
    → llama_decode повертає -1 («inconsistent sequence positions»)
    → LLMError → агент повторює ТУ САМУ зіпсовану генерацію
    → контекст заклинює до перезавантаження моделі

Ззовні це «модель замовкла, програма зависла». Правильна поведінка:
скасування не псує стан, і наступний хід проходить без ``код -1``.

Запуск:
    python tools/probe_kv_cancel.py            # бере першу локальну модель
    python tools/probe_kv_cancel.py qwen2.5    # будь-яка підрядком у назві
    python tools/probe_kv_cancel.py qwen2.5 1.5   # інша затримка скасування

Потрібна завантажена модель у ``userdata/models`` і встановлений рушій.
Код виходу: 0 — стан здоровий, 1 — розсинхрон або зламаний наступний хід.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.8

    try:
        from blackchpok_ide import model_hub
        from blackchpok_ide.native.api import NativeRuntime
    except Exception as exc:                        # noqa: BLE001
        print(f"Не імпортується рушій: {exc}")
        return 1

    models = [path for path in model_hub.local_models()
              if "mmproj" not in path.name.lower()
              and (not wanted or wanted.lower() in path.name.lower())]
    if not models:
        print("Немає локальних моделей"
              + (f" з «{wanted}»" if wanted else "")
              + ". Завантаж модель у розділі «Хаб моделей».")
        return 2
    target = models[0]
    print(f"Модель: {target.name}")

    api = NativeRuntime()
    if not api.engine.available:
        print("Рушій llama.cpp не встановлено (розділ «AI Runtime»).")
        return 2
    info = api.load_model(str(target), ctx=16384, gpu_layers=-1)
    context = api.engine.context
    lib = api.engine.lib
    print(f"Завантажено: ctx {info.get('context_actual')}, "
          f"GPU-шарів {info.get('gpu_layers')}\n")

    def kv_tokens() -> int:
        """Скільки токенів СПРАВДІ лежить у KV-кеші рушія (за рушієм)."""
        memory = lib.llama_get_memory(context.handle)
        if not memory:
            return -1
        position = int(lib.llama_memory_seq_pos_max(memory, 0))
        return 0 if position < 0 else position + 1

    result: dict[str, object] = {}

    def worker() -> None:
        try:
            for chunk in api.generate_stream(
                    [{"role": "user",
                      "content": "Опиши детально архітектуру рушія інференсу. " * 120}],
                    params={"max_tokens": 300, "temperature": 0.7}):
                if chunk.get("done"):
                    result["finish"] = chunk.get("finish_reason")
        except BaseException as exc:                # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"

    run = threading.Thread(target=worker, name="probe-kv", daemon=False)
    run.start()
    time.sleep(delay)
    print(f"Скасовую через {delay} с…")
    api.cancel_generation()
    run.join(timeout=180)

    finish = str(result.get("finish") or "")
    error = str(result.get("error") or "")
    print(f"  результат: finish={finish or '—'} помилка={error or '—'}")

    real_tokens = kv_tokens()
    mirror = int(context.cache.length) if context.cache is not None else 0
    print(f"  KV-кеш рушія: {real_tokens} токенів")
    print(f"  мітка CacheManager: {mirror} токенів")
    # Дзеркало мусить бути узгодженим із рушієм: після ``resync`` воно
    # порожнє (вміст токенів невідомий), але тоді ``prepare`` чистить кеш
    # і позиції лишаються правильними.
    check("скасування не дало помилки", not error, error[:120])
    check("мітка не «вища» за рушій", mirror <= real_tokens or mirror == 0,
          f"мітка {mirror} проти {real_tokens}")

    # ── Головна перевірка: наступний хід після скасування ─────────────────
    print("\nНаступний хід після скасування…")
    ok = False
    try:
        for chunk in api.generate_stream(
                [{"role": "user", "content": "Скажи одним словом: працює."}],
                params={"max_tokens": 8, "temperature": 0.0}):
            if chunk.get("done"):
                print(f"  finish: {chunk.get('finish_reason')}")
                ok = True
    except BaseException as exc:                    # noqa: BLE001
        print(f"  ПОМИЛКА: {type(exc).__name__}: {exc}")
    check("наступний хід після скасування працює", ok,
          "саме тут був «код -1» через розсинхрон KV")

    try:
        api.unload_model()
    except BaseException:                           # noqa: BLE001
        pass

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    if not FAILS:
        print("\nСтан здоровий: скасування не псує контекст.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
