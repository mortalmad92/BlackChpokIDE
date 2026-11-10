"""Замір вузьких місць програми: імпорт, старт вікна, службові оновлення.

Нічого не вгадуємо — міряємо. Кожен рядок показує реальний час.

Запуск:  .venv\\Scripts\\python.exe tools/profile_app.py
"""

from __future__ import annotations

import cProfile
import io
import pstats
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PY = sys.executable


def measure_imports() -> None:
    """Найповільніші модулі при імпорті вікна."""
    print("=" * 74)
    print("1. ІМПОРТ: які модулі найдовше вантажаться")
    print("=" * 74)
    code = (
        "import sys, time\n"
        "sys.argv=['x']\n"
        "t0=time.perf_counter()\n"
        "import blackchpok_ide.main_window\n"
        "total=time.perf_counter()-t0\n"
        "mods=[(n, m.__dict__.get('__loader__')) for n,m in sys.modules.items()]\n"
        "print(f'__TOTAL__{total:.3f}')\n"
    )
    proc = subprocess.run([PY, "-X", "importtime", "-c", code],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))
    rows: list[tuple[int, str]] = []
    total = 0.0
    for line in proc.stderr.splitlines():
        if line.startswith("__TOTAL__"):
            total = float(line[len("__TOTAL__"):])
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        try:
            self_us = int(parts[0].replace("import time:", "").strip())
        except ValueError:
            continue
        name = parts[2].strip()
        if name.startswith("blackchpok_ide."):
            rows.append((self_us, name))
    print(f"усього імпорт: {total:.2f} с")
    rows.sort(reverse=True)
    print("\nнайдорожчі власні модулі (мкс):")
    for self_us, name in rows[:12]:
        print(f"  {self_us:>7} мкс  {name}")


def measure_window() -> None:
    """Скільки коштує створити вікно й кожне службове оновлення."""
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    print()
    print("=" * 74)
    print("2. ВІКНО: вартість створення й оновлень")
    print("=" * 74)

    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.project_chosen = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    started = time.perf_counter()
    app = BlackChpokIDE(settings)
    built = time.perf_counter() - started

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                app.update()
            except Exception:  # noqa: BLE001
                return
            time.sleep(0.01)

    pump(1.5)
    app.hide_welcome()
    pump(0.3)
    while app.agent.busy:
        pump(0.3)

    print(f"створення вікна: {built * 1000:.0f} мс")

    actions = [
        ("_update_queue_badge", app._update_queue_badge),
        ("task_center.refresh", app.task_center.refresh),
        ("context.refresh (повний)", app.context.refresh),
        ("context._refresh_agent", app.context._refresh_agent),
        ("_apply_sash_positions", app._apply_sash_positions),
        ("chat_list.refresh", app.chat_list.refresh),
        ("_refresh_context", app._refresh_context),
        ("_sync_chat_title", app._sync_chat_title),
        ("_agent_status_text", lambda: app._agent_status_text()),
        ("_server_context_limit", app._server_context_limit),
    ]
    print("\nвартість одного виклику (мс, середнє з 3, прогріте вікно):")
    slow: list[tuple[float, str]] = []
    # Прогрів: перший виклик завжди дорожчий (кеші, ліниві імпорти).
    for _label, action in actions:
        try:
            action()
        except Exception:  # noqa: BLE001
            pass
    try:
        app.update()
    except Exception:  # noqa: BLE001
        pass
    for label, action in actions:
        started = time.perf_counter()
        for _ in range(3):
            try:
                action()
            except Exception:  # noqa: BLE001
                pass
        spent = (time.perf_counter() - started) / 3 * 1000
        slow.append((spent, label))
        print(f"  {spent:8.2f}  {label}")
    # Малювання міряємо ОКРЕМО: update() запускає й чужі after-таймери
    # (насос черги, тік автономного режиму), і в замір потрапляла не наша
    # робота. ``update_idletasks`` робить лише відкладене малювання.
    started = time.perf_counter()
    try:
        app.update_idletasks()
    except Exception:  # noqa: BLE001
        pass
    paint = (time.perf_counter() - started) * 1000
    print(f"  {paint:8.2f}  (малювання після оновлень, update_idletasks)")

    # Кадри під час роботи насоса
    print("\nкадри під час простою (5 с):")
    worst = 0.0
    end = time.time() + 5
    frames = 0
    while time.time() < end:
        t0 = time.perf_counter()
        try:
            app.update()
        except Exception:  # noqa: BLE001
            break
        worst = max(worst, time.perf_counter() - t0)
        frames += 1
        time.sleep(0.01)
    print(f"  кадрів: {frames}, найдовший: {worst * 1000:.0f} мс")

    slow.sort(reverse=True)
    print(f"\nнайдорожче оновлення: {slow[0][1]} ({slow[0][0]:.1f} мс)")

    try:
        app.agent.cancel()
        app.destroy()
    except Exception:  # noqa: BLE001
        pass


def measure_startup_profile() -> None:
    """Профіль створення вікна: де саме витрачається час."""
    print()
    print("=" * 74)
    print("3. ПРОФІЛЬ створення вікна (top-15 функцій)")
    print("=" * 74)

    script = ROOT / ".buildtmp" / "_prof_window.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "import sys, time, cProfile, pstats, io\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import tkinter.filedialog as fd, tkinter.messagebox as mb\n"
        "mb.askyesno=lambda *a,**k:True; mb.showinfo=lambda *a,**k:None\n"
        "mb.showwarning=lambda *a,**k:None; mb.showerror=lambda *a,**k:None\n"
        "fd.askdirectory=lambda *a,**k:''\n"
        "from blackchpok_ide.config import Settings, setup_logging\n"
        "setup_logging()\n"
        "s = Settings.load()\n"
        f"s.workspace = {str(ROOT)!r}\n"
        "s.first_run_done=True; s.project_chosen=True\n"
        "s.engine.auto_start=False; s.agent.queue_auto_run=False\n"
        "s.ui.view='workspace'\n"
        "from blackchpok_ide.main_window import BlackChpokIDE\n"
        "pr = cProfile.Profile()\n"
        "pr.enable()\n"
        "app = BlackChpokIDE(s)\n"
        "pr.disable()\n"
        "buf = io.StringIO()\n"
        "pstats.Stats(pr, stream=buf).sort_stats('cumulative').print_stats(15)\n"
        "print(buf.getvalue())\n"
        "app.agent.cancel(); app.destroy()\n",
        encoding="utf-8")
    proc = subprocess.run([PY, str(script)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    text = proc.stdout
    keep = []
    for line in text.splitlines():
        if "cumulative" in line or "ncalls" in line or "blackchpok_ide" in line:
            keep.append(line)
    print("\n".join(keep[:22]) or text[-1500:])


def main() -> int:
    measure_imports()
    measure_window()
    measure_startup_profile()
    print()
    print("=" * 74)
    print("Готово. Числа вище — реальні заміри на цій машині.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
