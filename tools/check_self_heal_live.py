"""Перевірка самовиправлення: агент помічає зламаний код і лагодить його.

Найважливіша властивість якості. Локальна модель регулярно пише код із
помилкою (апостроф у лапках, зайва дужка). Користувач не має про це
дізнаватись — агент мусить виправити сам.
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


import py_compile
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Фрази, які найчастіше ведуть до апострофів у коді.
PHRASES = (
    "створи файл hello.py який питає ім'я і вітає користувача",
    "зроби програму яка питає як звати і виводить привітання",
)


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

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures += 1

    for phrase in PHRASES:
        workspace = Path(tempfile.mkdtemp(prefix="selfheal-"))
        print()
        print("=" * 74)
        print(f"«{phrase}»")
        print("=" * 74)

        settings = Settings.load()
        settings.workspace = str(workspace)
        settings.first_run_done = True
        settings.project_chosen = True
        # Автозапуск лишаємо УВІМКНЕНИМ: перевірка має поводитись як
        # справжній користувач. Раніше тут стояло ``auto_start = False``, і
        # перший сценарій завершувався за 8 с без жодного файлу — модель
        # просто не була завантажена.
        settings.engine.auto_start = True
        settings.agent.queue_auto_run = False
        settings.agent.max_steps = 14   # місце на виправлення
        settings.ui.view = "workspace"

        from blackchpok_ide.main_window import BlackChpokIDE

        app = BlackChpokIDE(settings)
        app.geometry("1400x860")
        statuses: list[str] = []
        original = app.chat._handle_event

        def spy(event, _orig=original):
            if event.kind == "status":
                statuses.append(str(event.text or "")[:80])
            return _orig(event)

        app.chat._handle_event = spy
        try:
            pump(app, 1.8)
            app.hide_welcome()
            pump(app, 0.4)
            idle = 0.0
            while app.agent.busy and idle < 90:
                pump(app, 0.5)
                idle += 0.5

            app.chat._send(phrase, plan_step=True)
            # Виправлення синтаксису додає цикли, тож часу треба більше:
            # один хід моделі — це 15–40 с, а виправлень може бути два.
            waited = 0.0
            while app.agent.busy and waited < 600:
                pump(app, 0.5)
                waited += 0.5
            pump(app, 0.5)
            print(f"   агент завершив за {waited:.0f} с")

            files = [p for p in workspace.iterdir()
                     if p.suffix == ".py" and p.is_file()]
            check("файл створено", bool(files), str([f.name for f in files]))
            if not files:
                continue

            target = files[0]
            body = target.read_text(encoding="utf-8", errors="replace")
            print(f"   вміст {target.name}:")
            for line in body.splitlines()[:6]:
                print(f"     {line}")
            try:
                py_compile.compile(str(target), doraise=True)
                ok = True
                detail = "компілюється"
            except Exception as exc:  # noqa: BLE001
                ok = False
                detail = str(exc)[:160]
            check("код синтаксично правильний", ok, detail)
            check("агент попереджав про помилку або перевірку",
                  any("синтаксис" in s.lower() or "виправл" in s.lower()
                      for s in statuses) or ok,
                  f"статусів: {len(statuses)}")
        finally:
            try:
                app.agent.cancel()
                app.task_queue.clear()
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
            shutil.rmtree(workspace, ignore_errors=True)

    print()
    print("=" * 74)
    print("Самовиправлення коду:", "успішно" if failures == 0
          else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
