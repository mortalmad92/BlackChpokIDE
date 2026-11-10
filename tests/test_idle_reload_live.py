"""Модель вивантажується простоєм — і ПІДНІМАЄТЬСЯ назад.

Це головний дефект, через який користувач бачив «модель не стартує».
Реальний лог:

```
19:03:50  Старт рушія: … --port 8080 …
19:08:50  Модель вивантажено після 0 с простою
19:10:31  Адреса 8080 не слухає → модель недоступна
```

Модель стартувала нормально, потім вивантажилась через 5 хв простою — і
БІЛЬШЕ НІКОЛИ не піднялась: ``model_keeper.reload()`` не викликався ніде.

Тест перевіряє обидві половини:

1. політика простою справді вивантажує модель (це правильно — інакше
   відеокарта зайнята 24/7);
2. наступна дія користувача піднімає її назад.

Запуск: python tests/test_idle_reload_live.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-idle-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

FAILURES = 0
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global FAILURES, CHECKS
    CHECKS += 1
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}"
          + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES += 1
    return condition


def skip(name: str, why: str) -> None:
    print(f"[SKIP] {name} — {why}")


def main() -> int:
    from blackchpok_ide import power, runtime
    from blackchpok_ide.config import setup_logging

    setup_logging()

    # ── 1. Логіка політики (без моделі, швидко) ──────────────────────────
    tracker = power.IdleTracker()
    tracker.policy = power.IdlePolicy(enabled=True)
    tracker.policy.idle_seconds = 1          # поріг 1 с для тесту
    tracker.touch()

    check("щойно — не вивантажуємо",
          not tracker.should_unload(busy=False, autonomous=False, loaded=True))
    time.sleep(1.2)
    check("після порогу простій вивантажує",
          tracker.should_unload(busy=False, autonomous=False, loaded=True),
          f"простій {tracker.idle_text}")
    check("автономний режим не вивантажує",
          not tracker.should_unload(busy=False, autonomous=True, loaded=True))
    check("під час роботи агента не вивантажує",
          not tracker.should_unload(busy=True, autonomous=False, loaded=True))
    check("незавантажену модель «вивантажувати» нема сенсу",
          not tracker.should_unload(busy=False, autonomous=False, loaded=False))
    tracker.mark_unloaded()
    check("після вивантаження таймер скидається",
          not tracker.should_unload(busy=False, autonomous=False, loaded=True),
          f"простій {tracker.idle_text}")

    # ── 2. Справжній сервер: вивантаження й підйом ───────────────────────
    if not runtime.engine_installed():
        skip("живий підйом моделі", "рушій llama.cpp не встановлено")
        return _finish()
    models = [p for p in (ROOT / "userdata" / "models").glob("*.gguf")
              if "mmproj" not in p.name.lower()]
    if not models:
        skip("живий підйом моделі", "немає GGUF-моделі")
        return _finish()
    model = sorted(models, key=lambda p: p.stat().st_size)[0]
    print(f"\nМодель: {model.name} ({model.stat().st_size / 2**30:.2f} ГБ)")

    started: list = []

    def start_provider():
        cfg = runtime.ServerConfig(model_path=str(model),
                                   port=runtime.free_port(8080))
        server = runtime.LocalServer(cfg)
        server.start()
        ok, _detail = server.wait_ready(timeout=300)
        if not ok:
            server.stop()
            raise RuntimeError("сервер не піднявся")
        started.append(server)
        holder["server"] = server
        return server

    holder: dict = {"server": None}
    keeper = power.ModelKeeper(
        server_provider=lambda: holder["server"],
        start_provider=start_provider,
        on_status=lambda text: print(f"   · {text}"),
    )
    keeper.touch()

    try:
        start_provider()
        check("модель завантажена", keeper.loaded)

        # Вивантажуємо так, як це робить тік простою.
        unloaded = keeper.unload()
        check("вивантаження спрацювало", unloaded)
        check("після вивантаження модель не завантажена", not keeper.loaded)

        # ── Головна перевірка: підйом назад ─────────────────────────────
        reloaded = keeper.reload()
        check("модель ПІДНЯЛАСЬ назад", reloaded and keeper.loaded,
              f"loaded={keeper.loaded}")

        if reloaded and holder["server"] is not None:
            url = holder["server"].base_url
            check("піднятий сервер відповідає",
                  runtime.server_responds(url, api_key=runtime.MANAGED_API_KEY),
                  url)

        # ── Перевірка в оболонці: прапорець і виклик ────────────────────
        import inspect

        from blackchpok_ide import main_window

        source = inspect.getsource(main_window.BlackChpokIDE._wake_model_if_needed)
        check("оболонка вміє піднімати модель", "keeper.reload()" in source)
        hook = inspect.getsource(main_window.BlackChpokIDE._before_agent_request)
        check("підйом викликається перед запитом", "_wake_model_if_needed" in hook)

    finally:
        for server in started:
            try:
                server.stop()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.8)

    return _finish()


def _finish() -> int:
    print()
    print("=" * 60)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {FAILURES} з {CHECKS}")
        return 1
    print(f"Усі {CHECKS} перевірок пройдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
