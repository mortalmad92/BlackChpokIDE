"""Живі перевірки BlackChpok IDE на справжній локальній моделі.

Ці перевірки НЕ підміняють модель заглушкою: вони йдуть на реальний
локальний сервер і виконують справжні файлові дії. Саме тому вони окремо
від ``tests/run_all.py`` — їм потрібен запущений сервер моделі.

Запуск:
    .venv\\Scripts\\python.exe tools\\check_live.py            # усі
    .venv\\Scripts\\python.exe tools\\check_live.py controls    # окремі

Доступні перевірки:
    controls     — кожна кнопка, меню й панель центру завдань
    setting      — поле «Розмір контексту» в налаштуваннях
    server       — підхоплення вже запущеного сервера моделі
    launch       — IDE сама запускає рушій із правильним планом
    plan         — план справді складає модель (різні запити → різні плани)
    cycle        — повний цикл: план → виконання → файли → звіт
    replan       — перепланування залишку роботи
    plain        — прості людські фрази створюють справжні файли
    heal         — агент сам виправляє зламаний ним же код
    eval         — 10 архетипів задач: створення, правка, виправлення,
                   дописування, тести, читання, перейменування, кілька робіт,
                   документація, захист від зайвих змін
    context      — запуск рушія з різними режимами контексту
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Коли файл запускають напряму (``python tools/check_live.py``), теки
# проєкту немає в ``sys.path``, і ``import blackchpok_ide`` падає — тоді
# «модель не відповідає» показувалось навіть із живим сервером.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PY = sys.executable

CHECKS: dict[str, tuple[str, str]] = {
    "controls": ("Керування й панелі", "check_controls.py"),
    "setting": ("Поле контексту в налаштуваннях", "check_context_setting.py"),
    "server": ("Підхоплення сервера моделі", "check_server_adopt.py"),
    "plan": ("План від моделі (не шаблон)", "check_plan_from_model.py"),
    "cycle": ("Повний цикл із файлами", "check_full_cycle.py"),
    "replan": ("Перепланування залишку", "check_replan_live.py"),
    "launch": ("Самозапуск моделі рушієм IDE", "check_self_launch.py"),
    "nomodel": ("Робота без моделі (чесні відмови)", "check_no_model.py"),
    "plain": ("Прості фрази → справжні файли", "check_plain_language_live.py"),
    "heal": ("Самовиправлення зламаного коду", "check_self_heal_live.py"),
    "eval": ("10 архетипів задач (бенчмарк)", "eval_agent.py"),
    "context": ("Контекст наживо (16K/32K)", "check_context_live.py"),
}

DEFAULT_ORDER = ("controls", "setting", "server", "launch", "plan", "cycle",
                 "replan", "plain", "heal", "eval", "context", "nomodel")


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _model_ready() -> bool:
    """Чи є запущений сервер моделі — без нього живі перевірки не мають сенсу.

    Перевіряємо саме ``/v1/models`` З КЛЮЧЕМ: керований llama-server
    віддає 401 без ``Authorization``, і без ключа перевірка хибно казала
    «модель не відповідає», хоч сервер працює.
    """
    import json
    import urllib.request

    try:
        from blackchpok_ide.config import Settings

        llm = Settings.load().llm
        base = str(llm.base_url or "").rstrip("/")
        if not base.endswith("/v1"):
            base = base + "/v1"
        for key in (llm.api_key, "", "local"):
            try:
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                request = urllib.request.Request(base + "/models",
                                                 headers=headers)
                with urllib.request.urlopen(request, timeout=5) as response:
                    data = json.load(response)
                if data.get("data"):
                    return True
            except Exception:  # noqa: BLE001 - пробуємо наступний ключ
                continue
        return False
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    _utf8()
    wanted = [item for item in sys.argv[1:] if not item.startswith("-")] \
        or list(DEFAULT_ORDER)
    unknown = [name for name in wanted if name not in CHECKS]
    if unknown:
        print("Невідомі перевірки:", ", ".join(unknown))
        print("Доступні:", ", ".join(CHECKS))
        return 2

    if not _model_ready():
        print("Модель не відповідає — живі перевірки пропущено.")
        print("Запусти локальну модель (Хаб моделей або llama-server) і повтори.")
        return 0

    results: list[tuple[str, bool]] = []
    for name in wanted:
        title, script = CHECKS[name]
        print("=" * 70)
        print(f"{title}  ({script})")
        print("=" * 70)
        proc = subprocess.run([PY, str(ROOT / "tools" / script)], cwd=str(ROOT))
        ok = proc.returncode == 0
        results.append((title, ok))
        print(("[OK] " if ok else "[FAIL] ") + title)
        print()

    print("=" * 70)
    for title, ok in results:
        print(("[OK] " if ok else "[FAIL] ") + title)
    failed = [title for title, ok in results if not ok]
    print("=" * 70)
    print("Усі живі перевірки пройдено." if not failed
          else f"Провалено: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
