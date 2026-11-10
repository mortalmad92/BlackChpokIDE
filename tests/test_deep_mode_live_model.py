"""Перевірка режиму глибокого аналізу на СПРАВЖНІЙ локальній моделі.

Жодних заглушок: тест піднімає `llama-server` із локальним GGUF, чекає
готовності, складає план реальною моделлю й перевіряє, що план стосується
фактичного стеку проєкту.

Навіщо: на фейковому клієнті все зеленіло, а на живій моделі виявились дві
справжні вади, які він не ловив:

1. `wants_deep_plan` не вмикався на реальному завданні з кількома вимогами;
2. план вигадував чужий стек (HTML/CSS/JS для Tkinter-проєкту).

Запуск:
    python tests/test_deep_mode_live_model.py
    python tests/test_deep_mode_live_model.py --url http://127.0.0.1:8080/v1 --model qwen14b

Якщо моделі немає — тест ЧЕСНО ПРОПУСКАЄТЬСЯ (код 0) і пише, чого бракує.
Тихо «зелений» він не стає: причина видима в підсумку.
"""

from __future__ import annotations

import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0
skipped = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def skip(name: str, reason: str) -> None:
    global skipped
    skipped += 1
    print(f"[SKIP] {name} — {reason}")


def server_models(url: str, *, timeout: float = 3.0) -> list[str]:
    """Список моделей на OpenAI-сумісному сервері (порожній, якщо недоступний)."""
    base = url.rstrip("/")
    request = urllib.request.Request(base + "/models")
    request.add_header("Authorization", "Bearer local")
    try:
        import json

        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - сервер може бути відсутній
        return []
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [str(item.get("id") or "") for item in items if isinstance(item, dict)]


def start_server_if_needed() -> tuple[object, str, str]:
    """Підняти локальний сервер, якщо він ще не працює.

    Повертає (сервер_або_None, base_url, назва_моделі). Сервер треба
    зупинити після тесту — інакше він тримає 8 ГБ у пам'яті.
    """
    from blackchpok_ide import hardware as hw
    from blackchpok_ide import model_hub as hub
    from blackchpok_ide import runtime as rt

    models = [p for p in hub.local_models() if p.suffix.lower() == ".gguf"]
    if not models:
        return None, "", ""
    profile = hw.detect()
    choice = hw.recommend(profile)
    plan = hw.fit(profile, choice).plan
    # Беремо найбільшу локальну модель: вона ж і рекомендована для цього заліза.
    model = max(models, key=lambda p: p.stat().st_size if p.exists() else 0)
    port = rt.free_port(8080)
    config = rt.ServerConfig(model_path=str(model), port=port, plan=plan,
                             alias="livetest")
    server = rt.LocalServer(config)
    print(f"[..] Піднімаю llama-server: {model.name} на порту {port}…")
    server.start()
    ok, detail = server.wait_ready(timeout=300)
    if not ok:
        server.stop()
        return None, "", ""
    print(f"[..] Сервер готовий: {detail}")
    return server, server.base_url, "livetest"


def main() -> int:
    global failures
    url = "http://127.0.0.1:8080/v1"
    model = ""
    for index, arg in enumerate(sys.argv[1:], start=1):
        if arg == "--url" and index < len(sys.argv) - 1:
            url = sys.argv[index + 1]
        elif arg == "--model" and index < len(sys.argv) - 1:
            model = sys.argv[index + 1]

    from types import SimpleNamespace

    from blackchpok_ide import deep_mode as dm
    from blackchpok_ide.llm_client import LLMClient

    server = None
    try:
        # ── 1. Чи є жива модель
        names = server_models(url)
        if not names:
            server, url, auto_model = start_server_if_needed()
            if server is None:
                skip("жива модель", f"немає ні запущеного сервера ({url}), "
                                    f"ні локального GGUF у теці моделей")
                print()
                print(f"Глибокий аналіз на живій моделі: ПРОПУЩЕНО ({skipped})")
                return 0
            names = server_models(url)
            model = model or auto_model
        if not model:
            model = names[0]
        check("модель доступна", bool(model), f"{model} @ {url}")
        print(f"[..] Модель: {model}")

        llm = SimpleNamespace(base_url=url, model=model, api_key="local")

        # ── 2. Живий зв'язок (без цього решта перевірок нічого не варта)
        client = LLMClient(url, model, "local", temperature=0.1, max_tokens=64,
                           timeout=120)
        result = client.chat([{"role": "user",
                               "content": "Відповідай одним словом: столиця України?"}])
        answer = (result.content or "").strip()
        check("модель відповідає", bool(answer), answer[:60])

        # ── 3. Рішення про режим на реальному завданні
        #    Саме тут фейковий тест не бачив проблеми: справжнє завдання
        #    з кількома вимогами не проходило старий поріг.
        real_task = (
            "Потрібно обєднати вкладки чати і агенти в одне. Зроби щоб були "
            "іконки закриття чатів біля кожного чату та архівування. Зроби "
            "адаптивний розмір чату і відповідей в залежності до екрану."
        )
        check("складна задача вмикає режим", dm.wants_deep_plan(real_task),
              f"{len(real_task)} символів")
        check("коротке дорученн�� не вмикає",
              not dm.wants_deep_plan("запусти тести"))

        # ── 4. План реальною моделлю БЕЗ контексту проєкту
        started = time.time()
        bare_steps, bare_error = dm.plan_tasks(real_task, llm, timeout=240)
        bare_seconds = time.time() - started
        check("план без контексту склався", bool(bare_steps),
              f"{len(bare_steps)} кроків за {bare_seconds:.1f} с, помилка: "
              f"{bare_error or '—'}")

        # ── 5. План із контекстом проєкту
        started = time.time()
        steps, error = dm.plan_tasks(real_task, llm, timeout=240, root=ROOT)
        seconds = time.time() - started
        check("план із контекстом склався", bool(steps),
              f"{len(steps)} кроків за {seconds:.1f} с, помилка: {error or '—'}")
        check("план не порожній і не задовгий",
              1 <= len(steps) <= dm.MAX_TASKS, f"{len(steps)}")
        print(f"[..] Тривалість плану: {seconds:.1f} с")
        for index, step in enumerate(steps[:8], start=1):
            print(f"     {index}. {step[:100]}")

        # ── 6. План стосується СПРАВЖНЬОГО стеку
        #    Головна перевірка: для Python/Tkinter-проєкту план не має
        #    пропонувати HTML/CSS/JavaScript — саме так було до виправлення.
        joined = " ".join(steps).lower()
        web_marks = ("html", "css", "javascript", "js-код", "<div", "стилі css")
        invented = [mark for mark in web_marks if mark in joined]
        check("план не вигадав веб-стек", not invented, f"знайдено: {invented}")

        mentions_project = any(
            token in joined for token in ("blackchpok_ide", ".py", "python",
                                          "chat_panel", "main.py", "unittest")
        )
        check("план згадує реальні файли проєкту", mentions_project,
              f"перший крок: {steps[0][:70] if steps else '—'}")

        # Порівняння: з контекстом план має бути більш «про проєкт».
        if bare_steps:
            bare_joined = " ".join(bare_steps).lower()
            bare_project = any(token in bare_joined
                               for token in ("blackchpok_ide", "chat_panel",
                                             "main.py", "unittest"))
            check("контекст покращує відповідність проєкту",
                  mentions_project or not bare_project,
                  f"без контексту: {bare_project}, з контекстом: {mentions_project}")

        # ── 7. Сесія: стани задач рухаються
        session = dm.DeepSession(goal=real_task)
        session.set_tasks(steps)
        check("задачі з плану створені", len(session.tasks) == len(steps),
              str(len(session.tasks)))
        first = session.start_work()
        check("перша задача стартувала", first is not None and first.running)
        session.mark(first.index, dm.STATE_DONE)
        check("підсумок після першої", "1 готово" in session.summary(),
              session.summary())
        session.finish(ok=True)
        check("сесія завершилась", session.done, session.phase)

        # ── 8. Збій моделі обробляється чесно
        bad_llm = SimpleNamespace(base_url="http://127.0.0.1:9/v1",
                                  model="nope", api_key="x")
        steps_bad, error_bad = dm.plan_tasks("щось", bad_llm, timeout=8)
        check("недоступна модель дає помилку, а не виняток",
              steps_bad == [] and bool(error_bad), error_bad[:80])
    except Exception:  # noqa: BLE001 - показуємо повний стек
        traceback.print_exc()
        failures += 1
    finally:
        if server is not None:
            try:
                server.stop()
                print("[..] Сервер зупинено")
            except Exception:  # noqa: BLE001
                pass

    print()
    if skipped:
        print(f"Глибокий аналіз на живій моделі: пропущено ({skipped})")
    elif failures == 0:
        print("Глибокий аналіз на живій моделі: успішно")
    else:
        print(f"Глибокий аналіз на живій моделі: помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
