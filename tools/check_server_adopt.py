"""Перевірка підхоплення вже запущеного сервера моделі.

Користувач часто тримає llama-server або LM Studio запущеним. IDE має
знайти його сама й не піднімати другий процес.
"""

from __future__ import annotations
# ── ІЗОЛЯЦІЯ ДАНИХ ───────────────────────────────────────────────────────
# Інструмент будує СПРАВЖНЄ вікно IDE. Без власного ``BLACKCHPOK_HOME``
# вікно читає ``<app_data>/chats.json`` і відновлює активний чат
# КОРИСТУВАЧА — з ЙОГО текою. Наслідок заміряно: тестовий агент писав
# файли в проєкт користувача, а перевірка дивилась у пісочницю.
# Ставимо ДО звернення до пакета: ``config`` рахує шляхи під час імпорту.
import os as _os
import tempfile as _tempfile

_os.environ.setdefault("BLACKCHPOK_HOME",
                       _tempfile.mkdtemp(prefix="tool-home-"))
_os.environ["BLACKCHPOK_NO_SAVE"] = "1"


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


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            return
        time.sleep(0.01)


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import runtime
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.project_chosen = True
    # Модель уже працює на 8080 — IDE не має піднімати власну.
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1400x860")
    try:
        pump(app, 2.0)
        app.hide_welcome()
        pump(app, 0.6)

        # Вбудований рушій (`native://blackchpok`) не має HTTP-адреси:
        # питаємо його, а не мережу. Раніше тут перевірявся лише
        # `_server_alive` — і перевірка падала на робочому рушії, який
        # ще не завантажив модель (вона вантажиться на перший запит).
        alive = app._server_alive(fresh=True) or (
            runtime.embedded_url(app.settings.llm.base_url)
            and runtime.embedded_engine_available())
        check("модель готова відповідати", alive,
              "рушій підніме на перший запит")
        check("IDE не підняла власний процес",
              getattr(app, "_managed_server", None) is None,
              str(getattr(app, "_managed_server", None)))

        model, kind = app._model_summary()
        check("модель видно в панелі", bool(model) and model != "не вибрана",
              f"{model} · {kind}")

        # Перевірка моделей через провайдерів
        app.probe_providers()
        waited = 0.0
        while getattr(app, "_probe", None) is not None and waited < 60:
            pump(app, 0.5)
            waited += 0.5
        pump(app, 0.5)
        known = app._known_models()
        check("IDE знає моделі сервера", len(known) > 0,
              f"{len(known)}: {known[:3]}")

        # Автовибір моделі, якщо в налаштуваннях порожньо
        saved_model = app.settings.llm.model
        app.settings.llm.model = ""
        app._adopt_local_model()
        pump(app, 0.3)
        adopted = app.settings.llm.model
        check("IDE підхоплює модель сама", bool(adopted), adopted or "—")
        app.settings.llm.model = saved_model

        # Вимірювання контексту з реального сервера
        used, limit = app._context_usage()
        check("ліміт контексту відомий", True, f"використано {used} з {limit}")
    finally:
        try:
            app.agent.cancel()
            app.destroy()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Підхоплення сервера:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
