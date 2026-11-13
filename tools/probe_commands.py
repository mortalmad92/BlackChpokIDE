"""Виконати команди палітри й знайти ті, що падають.

Команда може бути зареєстрована з правильним підписом і все одно падати
при виконанні: ``AttributeError`` на віджеті, якого немає в цьому режимі,
``NameError`` у рідко використовуваній гілці. Тут кожна команда справді
викликається.

ЧОМУ ОКРЕМИЙ ПРОЦЕС НА КОМАНДУ. Tk вимагає головного потоку, тож
«обгорнути виклик у потік із таймером» неможливо: Tk падає з
``RuntimeError: main thread is not in main loop``. А викликати модальний
діалог у головному потоці означає повісити всю перевірку. Тому кожна
команда виконується в окремому процесі з таймаутом: зависла — вбиваємо й
їдемо далі.

Запуск: ``python tools\probe_commands.py`` — код виходу 1, якщо є падіння.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 25

#: Слова, через які команда НЕ викликається автоматично: діалоги, процеси,
#: мережа, модель, вихід із програми.
SKIP_WORDS = (
    "quit", "exit", "close", "dialog", "open_folder", "save_as", "quick_open",
    "file.open", "export", "import", "settings", "preferences", "about", "help",
    "model", "engine", "runtime", "voice", "mcp", "social", "deploy", "publish",
    "install", "update", "download", "hub", "browser", "preview", "terminal",
    "night", "autonomous", "bench", "screenshot", "record", "server", "test",
    "url", "site", "probe", "vram", "restart", "reload", "folder",
)

#: Код, який виконується в дочірньому процесі: створити вікно, виконати
#: одну команду за ключем, повідомити результат.
#:
#: Це звичайний рядок (не f-string): фігурні дужки тут — синтаксис Python
#: для словників, і подвоювати їх не потрібно. Місце під корінь проєкту
#: позначає ``__ROOT__``.
CHILD = r'''
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, r"__ROOT__")

# ── ІЗОЛЯЦІЯ ДАНИХ ───────────────────────────────────────────────────────
# Без цього дочірній процес читає СПРАВЖНІ ``chats.json``, ``queue.json`` і
# ``settings.json`` користувача. Наслідки заміряно:
#   • ``agent.new_chat`` «зависала» понад 25 с — бо вікно відновлювало
#     активний чат користувача зі 187 повідомленнями (перемальовування
#     транскрипту займає секунди, і команда не встигала);
#   • у справжній черзі з'являлись кроки прогону;
#   • проба залежала від того, що користувач робив у програмі раніше.
# Ставимо ДО імпорту пакета: ``config`` обчислює шляхи під час імпорту.
os.environ.setdefault("BLACKCHPOK_HOME",
                      tempfile.mkdtemp(prefix="probe-cmd-home-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

# ── МОДАЛЬНІ ДІАЛОГИ МУСЯТЬ БУТИ ЗАГЛУШЕНІ ──────────────────────────────
# Без цього будь-яка команда, що відкриває діалог, «зависає»: у
# дочірньому процесі немає користувача, який його закриє. Заміряно:
# ``agent.new_chat`` висіла понад 25 с, бо ``new_chat_session`` кличе
# ``filedialog.askdirectory``. Команда при цьому СПРАВНА — винна проба.
import tkinter.filedialog as _fd
import tkinter.messagebox as _mb
import tkinter.simpledialog as _sd

_mb.askyesno = lambda *a, **k: True
_mb.askokcancel = lambda *a, **k: True
_mb.askyesnocancel = lambda *a, **k: True
_mb.showinfo = lambda *a, **k: None
_mb.showwarning = lambda *a, **k: None
_mb.showerror = lambda *a, **k: None
_sd.askstring = lambda *a, **k: ""
_sd.askinteger = lambda *a, **k: 0
_sd.askfloat = lambda *a, **k: 0.0
# ``askdirectory`` віддає порожній рядок — «користувач скасував». Команда
# доходить до власної гілки скасування, і ми перевіряємо саме те, що вона
# не падає; підсовувати теку означало б вдавати, що теку вибрано.
_fd.askdirectory = lambda *a, **k: ""
_fd.askopenfilename = lambda *a, **k: ""
_fd.asksaveasfilename = lambda *a, **k: ""

from blackchpok_ide import commands
from blackchpok_ide.config import Settings
from blackchpok_ide.main_window import BlackChpokIDE

key = sys.argv[1]
workspace = Path(tempfile.mkdtemp(prefix="probe-cmd-"))
(workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
settings = Settings.load()
settings.remember_workspace(str(workspace))
settings.engine.auto_start = False
settings.llm.auto_detect = False
app = BlackChpokIDE(settings)
app.withdraw()
for _ in range(5):
    app.update_idletasks()
    app.update()
target = next((c for c in commands.all_commands() if c.key == key), None)
if target is None:
    print(json.dumps({"ok": False, "error": "команду не зареєстровано"}))
    raise SystemExit(0)
try:
    target.action()
    app.update_idletasks()
    print(json.dumps({"ok": True}))
except Exception as exc:
    print(json.dumps({"ok": False,
                      "error": type(exc).__name__ + ": " + str(exc)[:200]}))
finally:
    try:
        app.on_close()
    except Exception:
        pass
'''


def main() -> int:
    # Ключі беремо з окремого «сухого» запуску: реєстр наповнює вікно.
    keys = _list_keys()
    if not keys:
        print("Не вдалось отримати список команд")
        return 2
    script = CHILD.replace("__ROOT__", str(ROOT))
    child_path = Path(tempfile.mkdtemp(prefix="probe-cmd-child-")) / "child.py"
    child_path.write_text(script, encoding="utf-8")

    ran = 0
    problems = 0
    skipped = 0
    for key in keys:
        lowered = key.lower()
        if any(word in lowered for word in SKIP_WORDS):
            skipped += 1
            continue
        ran += 1
        try:
            completed = subprocess.run(
                [sys.executable, str(child_path), key],
                capture_output=True, text=True, timeout=TIMEOUT, cwd=str(ROOT),
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            print(f"ЗАВИСЛА {key} (>{TIMEOUT} с)")
            problems += 1
            continue
        payload = ""
        for line in (completed.stdout or "").splitlines():
            if line.strip().startswith("{"):
                payload = line.strip()
        if not payload:
            print(f"БЕЗ ВІДПОВІДІ {key}: {completed.stderr.strip().splitlines()[-1:]}")
            problems += 1
            continue
        try:
            answer = json.loads(payload)
        except ValueError:
            problems += 1
            continue
        if not answer.get("ok"):
            print(f"ЗБІЙ {key}: {answer.get('error')}")
            problems += 1
    print(f"Виконано команд: {ran}, збоїв: {problems}, пропущено: {skipped}")
    return 1 if problems else 0


def _list_keys() -> list[str]:
    """Отримати ключі команд із живої реєстрації (без виконання)."""
    script = (
        f"import sys; sys.path.insert(0, r'{ROOT}')\n"
        "import tempfile\n"
        "from pathlib import Path\n"
        "from blackchpok_ide import commands\n"
        "from blackchpok_ide.config import Settings\n"
        "from blackchpok_ide.main_window import BlackChpokIDE\n"
        "ws = Path(tempfile.mkdtemp())\n"
        "s = Settings.load(); s.remember_workspace(str(ws))\n"
        "s.engine.auto_start = False; s.llm.auto_detect = False\n"
        "app = BlackChpokIDE(s); app.withdraw()\n"
        "print('\\n'.join(c.key for c in commands.all_commands()))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            timeout=90, cwd=str(ROOT), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return []
    return [line.strip() for line in (completed.stdout or "").splitlines()
            if line.strip() and "." in line]


if __name__ == "__main__":
    raise SystemExit(main())
