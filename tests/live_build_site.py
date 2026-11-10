"""Живий прогін у GUI: агент будує складний сайт у C:\\AI.

Це те, що просив користувач: перевірити агента В ІНТЕРФЕЙСІ на складній
задачі — від створення папки до сайту для публікацій постів із власним
API без PHP і власним сервером.

Сценарій:

1. відкриваємо СПРАВЖНЄ вікно BlackChpok IDE (не headless);
2. створюємо теку проєкту через ``create_project_folder`` (той самий шлях,
   що й кнопка «Створити нову» на екрані вибору теки);
3. пишемо запит у поле чату й натискаємо надсилання (як користувач);
4. чекаємо, доки агент попрацює, і перевіряємо ФАЙЛИ НА ДИСКУ;
5. запускаємо створений сервер і перевіряємо API запитами;
6. знімаємо скріншот вікна — доказ, що все було саме в GUI.

Запуск: python tests/live_build_site.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

TARGET = Path(r"C:\AI\blog2026")
PORT = 8099

failures = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}"
          f"{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1
    return bool(condition)


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def neutralise_dialogs() -> None:
    """Модальні вікна у тесті не мають чекати людину."""
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: TARGET.name if a and "Назва" in str(a[1] if len(a) > 1 else "") else None
    sd.askinteger = lambda *a, **k: 1
    fd.askdirectory = lambda *a, **k: str(TARGET.parent)
    fd.askopenfilename = lambda *a, **k: ""
    fd.asksaveasfilename = lambda *a, **k: ""


BRIEF = """Створи в робочій теці повноцінний сайт для публікацій постів.

Вимоги:
1. Бекенд на Python БЕЗ PHP: власний HTTP-сервер на стандартній бібліотеці
   (http.server), файл app.py. Порт 8099.
2. Власний REST API: GET /api/posts (список), POST /api/posts (створити),
   DELETE /api/posts/<id> (видалити). Дані зберігай у data/posts.json.
3. Фронтенд: index.html + static/style.css + static/app.js. Дизайн 2026:
   темна тема, скляні картки (glassmorphism), градієнти, плавні анімації,
   адаптивна сітка, велика типографіка.
4. Форма створення поста (заголовок + текст) і список постів із кнопкою
   видалення. Усе через fetch до власного API.
5. Не використовуй зовнішні бібліотеки й CDN — усе локальне.

Створи всі файли інструментом write_file. Перевір, що синтаксис Python
правильний. У кінці коротко переліч створені файли."""


def main() -> int:
    neutralise_dialogs()

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()

    settings = Settings.load()
    # Тест має брати СПРАВЖНІ налаштування користувача (модель, адресу
    # сервера). Тестові ``BLACKCHPOK_HOME`` перенаправляють
    # ``settings_path()`` на порожню теку, де модель не вибрана — тоді
    # прогін робив би SKIP, хоч модель на диску є. Читаємо типовий шлях
    # користувача напряму.
    if not str(settings.llm.model or "").strip():
        from blackchpok_ide import config as config_module

        real_path = Path.home() / "AppData" / "Roaming" / "BlackChpokIDE" / "settings.json"
        if real_path.exists():
            real = config_module.Settings.load(real_path)
            settings.llm = real.llm
            settings.engine = real.engine
    if not str(settings.llm.model or "").strip():
        print("[SKIP] Модель не вибрана")
        return 0
    settings.first_run_done = True
    settings.engine.auto_start = False       # сервер уже піднятий окремо
    settings.agent.queue_auto_run = False
    settings.agent.max_steps = 30            # складна задача потребує кроків
    settings.agent.confirm_commands = False
    settings.agent.queue_auto_run = True     # черга має рухатись сама
    settings.agent.auto_split = True
    settings.workspace = str(TARGET)
    settings.project_chosen = True

    from blackchpok_ide.main_window import BlackChpokIDE

    print("=== 1. Відкриваю GUI ===")
    app = BlackChpokIDE(settings)
    app._adopt_local_model = lambda: None
    app.geometry("1560x940")
    pump(app, 2.0)
    check("вікно IDE створено", app.winfo_exists() == 1)
    check("чат на місці", app.chat.winfo_exists() == 1)

    print()
    print("=== 2. Тека проєкту (як кнопка «Створити нову») ===")
    if TARGET.exists():
        import shutil

        shutil.rmtree(TARGET, ignore_errors=True)
    TARGET.mkdir(parents=True, exist_ok=True)
    app.set_workspace(TARGET)
    pump(app, 1.0)
    check("тека проєкту створена", TARGET.is_dir(), str(TARGET))
    check("IDE бачить проєкт", app.has_project(), str(app.settings.workspace))
    app.new_chat_session()
    pump(app, 0.5)

    print()
    print("=== 3. Запит у поле чату (як користувач) ===")
    app.chat.set_text(BRIEF)
    pump(app, 0.3)
    check("запит у полі вводу",
          "сайт для публікацій" in app.chat._composer_text().lower()
          or "сайт" in app.chat._composer_text().lower(),
          app.chat._composer_text()[:60])

    # Показуємо, що етапи з'являються ще до роботи агента.
    app.chat._send_from_box()
    pump(app, 1.5)
    check("етапи задачі показані", len(app.chat.stage_strip.stages) > 0,
          f"{len(app.chat.stage_strip.stages)} етапів")
    # Великий запит іде через план: спершу модель складає кроки, потім
    # черга їх виконує. Тому «агент почав роботу» перевіряємо за станом
    # черги АБО за зайнятістю агента — обидва шляхи справжні.
    busy = bool(app.chat.runner and app.chat.runner.busy)
    queued = len([t for t in app.task_queue.tasks])
    planning = str(app.agent_label.cget("text")) if hasattr(app, "agent_label") else ""
    check("агент почав роботу",
          busy or queued > 0 or "працює" in planning,
          f"busy={busy} задач={queued} стан={planning}")

    print()
    print("=== 4. Чекаю, доки агент попрацює (до 10 хв) ===")
    # Умова завершення має бути НАДІЙНОЮ. Раніше цикл виходив після трьох
    # «вільних» секунд — а між складанням плану й стартом першої задачі
    # агент справді вільний, тож тест обривався раніше, ніж починалась
    # робота, і показував «0 файлів», хоч агент усе створював.
    deadline = time.time() + 600
    started = time.time()
    idle_since = time.time()
    last = ""
    last_files = 0
    while time.time() < deadline:
        pump(app, 1.0)
        busy = bool(app.chat.runner and app.chat.runner.busy)
        pending = [t for t in app.task_queue.tasks
                   if t.status in ("очікує", "виконується")]
        try:
            status = str(app.agent_label.cget("text"))
        except Exception:  # noqa: BLE001 - віджет перемальовано
            status = ""
        planning = "працює" in status
        files = len([p for p in TARGET.rglob("*") if p.is_file()])
        working = busy or pending or planning or bool(app._running_task_id)
        if working or files != last_files:
            idle_since = time.time()
            last_files = files
        if status != last or files != last_files:
            last = status
            print(f"    … {status} · файлів: {files} · у черзі: {len(pending)}")
        # Виходимо, лише коли робота справді закінчилась: агент вільний,
        # черга порожня і стан не змінювався 12 секунд.
        if not working and (time.time() - idle_since) > 12 \
                and (time.time() - started) > 20:
            break
    pump(app, 2.0)
    check("агент завершив роботу",
          not (app.chat.runner and app.chat.runner.busy),
          "хід завершено")

    print()
    print("=== 5. Що агент створив на диску ===")
    files = sorted(p for p in TARGET.rglob("*") if p.is_file())
    for path in files:
        rel = path.relative_to(TARGET).as_posix()
        print(f"    {rel:34} {path.stat().st_size:>8} Б")
    check("створено файли", len(files) >= 3, f"{len(files)} файлів")

    names = {p.relative_to(TARGET).as_posix().lower() for p in files}
    has_backend = any(n.endswith(".py") for n in names)
    has_html = any(n.endswith(".html") for n in names)
    has_api = any("api" in n or n.endswith(".py") for n in names)
    check("є бекенд на Python (без PHP)", has_backend,
          ", ".join(sorted(n for n in names if n.endswith(".py"))[:3]))
    check("немає жодного PHP-файлу",
          not any(n.endswith(".php") for n in names))
    check("є HTML-сторінка", has_html,
          ", ".join(sorted(n for n in names if n.endswith(".html"))[:3]))
    check("є реалізація API", has_api)

    print()
    print("=== 6. Скріншот вікна (доказ, що це GUI) ===")
    try:
        from PIL import ImageGrab

        shots = ROOT / ".buildtmp" / "build-site"
        shots.mkdir(parents=True, exist_ok=True)
        target = shots / "ide-after-agent.png"
        ImageGrab.grab(bbox=(app.winfo_rootx(), app.winfo_rooty(),
                             app.winfo_rootx() + app.winfo_width(),
                             app.winfo_rooty() + app.winfo_height())).save(target)
        check("скріншот збережено", target.exists(), str(target))
    except Exception as exc:  # noqa: BLE001
        check("скріншот збережено", False, str(exc))

    app.destroy()

    print()
    print("=== 7. Запуск створеного сервера й перевірка API ===")
    backend = _find_backend(TARGET)
    if backend is None:
        check("знайдено файл сервера", False, "жодного .py з http.server")
    else:
        check("знайдено файл сервера", True, backend.name)
        _run_server_checks(TARGET, backend)

    print()
    print("Живий прогін у GUI: " + ("успішно" if not failures else f"збоїв {failures}"))
    return 0 if not failures else 1


def _find_backend(project: Path) -> Path | None:
    """Знайти файл, який запускає HTTP-сервер."""
    for path in project.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "HTTPServer" in text or "http.server" in text:
            return path
    return None


def _fetch(url: str, *, method: str = "GET", payload=None, timeout: float = 10):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def _run_server_checks(project: Path, backend: Path) -> None:
    """Підняти створений сервер і перевірити API реальними запитами."""
    import subprocess

    port = PORT
    try:
        text = backend.read_text(encoding="utf-8", errors="replace")
        for token in ("8099", "8000", "8080", "5000"):
            if token in text:
                port = int(token)
                break
    except OSError:
        pass
    print(f"    запускаю {backend.name} на порту {port}…")
    process = subprocess.Popen(
        [sys.executable, str(backend)], cwd=str(project),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
    )
    base = f"http://127.0.0.1:{port}"
    try:
        ready = False
        for _ in range(40):
            time.sleep(0.5)
            code, _body = _fetch(base + "/", timeout=3)
            if code and code > 0:
                ready = True
                break
        check("сервер відповідає на /", ready, base)

        if ready:
            code, body = _fetch(base + "/api/posts")
            check("GET /api/posts відповідає", code == 200, f"HTTP {code}")
            created_id = ""
            code, body = _fetch(base + "/api/posts", method="POST",
                                payload={"title": "Перший пост",
                                         "content": "Привіт від агента"})
            check("POST /api/posts створює пост", code in (200, 201),
                  f"HTTP {code}: {body[:80]}")
            try:
                created = json.loads(body) if body.strip().startswith("{") else {}
                created_id = str(created.get("id", "") or "")
            except Exception:  # noqa: BLE001
                created_id = ""
            code, body = _fetch(base + "/api/posts")
            check("новий пост є у списку",
                  code == 200 and "Перший пост" in body,
                  f"HTTP {code}")
            if created_id:
                code, _body = _fetch(base + f"/api/posts/{created_id}",
                                     method="DELETE")
                check("DELETE /api/posts/<id> видаляє пост",
                      code in (200, 204), f"HTTP {code}")
    finally:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
