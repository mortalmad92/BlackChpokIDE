"""Жива перевірка: модель піднімається САМА і статус стає ОНЛАЙН.

Повторює справжній старт IDE: вікно, реальні налаштування (вбудований
рушій + автозапуск), справжній GGUF. Нічого не вибирає й не натискає —
рівно те, що бачить користувач, коли просто відкриває програму.
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

# Дані ізольовані, але модель і рушій — СПРАВЖНІ, з робочої теки.
os.environ["BLACKCHPOK_HOME"] = tempfile.mkdtemp(prefix="bchp-autostart-")
os.environ.pop("BLACKCHPOK_NO_SAVE", None)

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001 - вікно могло закритись
            return
        time.sleep(0.02)


def main() -> int:
    import tkinter as tk

    try:
        tk.Tk().destroy()
    except tk.TclError as exc:
        print(f"[SKIP] Немає дисплея: {exc}")
        return 0

    from blackchpok_ide import config, model_hub, runtime
    from blackchpok_ide.native import bridge

    models = [p for p in model_hub.local_models() if "mmproj" not in p.name.lower()]
    if not models:
        print("[SKIP] немає локальних моделей")
        return 0
    model = max(models, key=lambda p: p.stat().st_size)
    print(f"модель: {model.name}\n")

    settings = config.Settings.load()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.first_run_done = True
    settings.ui.restore_session = False
    # Стан, у якому користувач просто відкриває програму.
    settings.engine.native = True
    settings.engine.auto_start = True
    settings.engine.ctx_size = 8192
    settings.engine.model_path = str(model)
    settings.engine.native_model = model.stem
    settings.llm.base_url = bridge.EMBEDDED_URL
    settings.llm.model = model.stem
    settings.llm.api_key = "local"

    from blackchpok_ide.main_window import BlackChpokIDE

    print("будую вікно…")
    app = BlackChpokIDE(settings)
    pump(app, 0.5)

    # Автозапуск іде через after(400) + потік; модель вантажиться ~4 с.
    print("чекаю автозапуск (без жодного кліку)…")
    loaded = False
    deadline = time.time() + 120
    while time.time() < deadline:
        pump(app, 0.25)
        if bridge.runtime().engine.loaded:
            loaded = True
            break

    check("модель завантажилась САМА", loaded,
          f"engine.loaded={bridge.runtime().engine.loaded}")
    if loaded:
        info = bridge.runtime().engine.describe()
        check("вікно контексту справжнє", int(info.get("context_actual", 0)) > 0,
              f"ctx {info.get('context_actual')} · GPU {info.get('gpu_layers')}")

    # Статус у шапці мусить стати ОНЛАЙН без участі користувача.
    pump(app, 3.0)
    try:
        text = app.header_bar.model_status.cget("text")
        colour = str(app.header_bar.model_status.cget("fg"))
    except Exception as exc:  # noqa: BLE001
        text, colour = f"<{exc}>", ""
    print(f"   шапка: «{text}» ({colour})")
    check("шапка показує ОНЛАЙН", "ОНЛАЙН" in text, text)
    check("адреса лишилась вбудована",
          app.settings.llm.base_url == bridge.EMBEDDED_URL,
          app.settings.llm.base_url)
    check("модель у налаштуваннях — справжня",
          app.settings.llm.model == model.stem, app.settings.llm.model)

    # Головна властивість: агент справді відповідає, а не «модель недоступна».
    from blackchpok_ide.llm_client import LLMClient

    client = LLMClient(app.settings.llm.base_url, app.settings.llm.model,
                       app.settings.llm.api_key, timeout=120)
    answer = ""
    try:
        result = client.chat([{"role": "user", "content": "Скажи одне слово: привіт"}],
                             max_tokens=16)
        answer = (result.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        answer = f"<{type(exc).__name__}: {exc}>"
    print(f"   відповідь моделі: {answer[:120]!r}")
    check("модель ВІДПОВІДАЄ на запит", bool(answer) and not answer.startswith("<"),
          answer[:80])

    # Закриваємо ЯК КОРИСТУВАЧ — через on_close(). Прямий destroy() лишає
    # заплановані ``after``-виклики в Tcl, і вони спрацьовують після
    # знищення вікна: «invalid command name ..._drain_ui». Це помилка
    # проби, а не продукту: on_close() скасовує всі таймери.
    app.after(0, app.on_close)
    pump(app, 1.5)
    print()
    print("Автозапуск моделі:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
