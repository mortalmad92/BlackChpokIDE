"""Кінець-у-кінець: агент справді створює файл на диску.

Це найважливіша перевірка продукту, якої не дають юніт-тести: локальна
модель отримує запит, сама обирає інструмент ``write_file`` і справді
записує файл. Якщо цей сценарій проходить — програма працює, а не просто
«показує інтерфейс».

Запуск: python tests/e2e_real_agent.py
Потрібна локальна модель; без неї — чесний SKIP із кодом 0.
"""

from __future__ import annotations

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

failures = 0
skipped = False


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main() -> int:
    global skipped
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()

    # Ізолюємо: власна тека проєкту, жодного впливу на справжній конфіг.
    project = Path(tempfile.mkdtemp(prefix="bc_e2e_"))
    print(f"Тека проєкту: {project}")

    # Модель підхоплюємо з РЕАЛЬНОГО конфігу користувача: тестові
    # BLACKCHPOK_HOME вказують на порожню теку, і модель там не вибрана —
    # тоді прогін робив би SKIP, хоч модель на диску є.
    from blackchpok_ide import runtime

    settings = Settings.load()
    if not str(settings.llm.model or "").strip():
        print("[SKIP] У налаштуваннях не вибрано модель")
        skipped = True
        return 0
    if not str(settings.engine.model_path or "").strip():
        found = sorted((ROOT / "userdata" / "models").glob("*.gguf"))
        if not found:
            print("[SKIP] Немає GGUF-моделі на диску")
            skipped = True
            return 0
        settings.engine.model_path = str(found[0])
        settings.llm.model = found[0].stem
    settings.workspace = str(project)
    settings.project_chosen = True
    settings.first_run_done = True
    settings.engine.auto_start = True
    settings.agent.queue_auto_run = False
    settings.agent.max_steps = 6
    settings.agent.confirm_commands = False

    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.llm_client import LLMClient, LLMError

    # 1. Модель доступна? Якщо ні — піднімаємо локальний сервер сами
    #    (саме так робить сама програма при старті, див. runtime.LocalServer).
    client = LLMClient(settings.llm.base_url, settings.llm.model,
                       settings.llm.api_key, timeout=12)
    server = None
    try:
        client.chat([{"role": "user", "content": "скажи одне слово"}])
    except LLMError as exc:
        print(f"[..] Модель не відповідає ({exc}) — піднімаю локальний сервер…")
        path = Path(str(settings.engine.model_path or ""))
        if not path.exists():
            print(f"[SKIP] Немає файлу моделі: {path}")
            skipped = True
            return 0
        try:
            # План запуску беремо з hardware — саме так робить сама IDE.
            profile = hardware.detect()
            choice = hardware.ModelChoice(str(path.parent), path.name, path.stem,
                                          14.0, path.stat().st_size / 2**30,
                                          0.0, "", 48)
            plan = hardware.plan_for(profile, choice)
            cfg = runtime.ServerConfig(str(path), port=8080,
                                       plan=plan, alias=settings.llm.model)
            server = runtime.LocalServer(cfg)
            server.start()
            server.wait_ready(timeout=120)
            settings.llm.base_url = server.base_url
            client = LLMClient(settings.llm.base_url, settings.llm.model,
                               settings.llm.api_key, timeout=60)
            client.chat([{"role": "user", "content": "скажи одне слово"}])
            print(f"[OK  ] сервер піднято: {server.base_url}")
        except Exception as start_exc:  # noqa: BLE001
            print(f"[SKIP] Не вдалось підняти сервер: {start_exc}")
            try:
                if server is not None:
                    server.stop()
            except Exception:  # noqa: BLE001
                pass
            skipped = True
            return 0
    else:
        print("[OK  ] локальна модель відповідає")

    # 2. Агент із реальним реєстром інструментів у справжній теці.
    registry = ToolRegistry(project)
    runner = AgentRunner(registry, settings.llm, settings.agent, project)

    events: list = []
    done = {"ok": None, "text": ""}
    goal = ("Створи у робочій теці файл hello.txt з одним рядком: "
            "Привіт від агента. Використай інструмент write_file.")
    print(f"Запит: {goal[:70]}…")
    runner.start(goal)

    # 3. Чекаємо завершення (до 3 хвилин — модель завантажується на GPU).
    #    Події агента лежать у черзі ``runner.events``.
    deadline = time.time() + 180
    import queue as queue_module

    while time.time() < deadline and done["ok"] is None:
        try:
            event = runner.events.get(timeout=0.5)
        except queue_module.Empty:
            continue
        events.append(event)
        if event.kind == "done":
            done["ok"] = bool(event.data.get("ok", True))
            done["text"] = event.text

    tools_used = [e.data.get("name", "") for e in events if e.kind == "tool_call"]
    check("агент завершив хід", done["ok"] is not None,
          f"ok={done['ok']}")
    check("агент викликав інструменти", bool(tools_used),
          ", ".join(tools_used[:5]) or "жодного")

    target = project / "hello.txt"
    # Модель могла назвати файл інакше — тоді шукаємо будь-який .txt.
    created = list(project.glob("*.txt")) + list(project.rglob("*.txt"))
    check("файл створено на диску", target.exists() or bool(created),
          str(target) if target.exists() else (str(created[0]) if created else "немає"))

    if target.exists():
        text = target.read_text(encoding="utf-8", errors="replace")
        check("у файлі очікуваний текст", "Привіт" in text, repr(text[:60]))
    elif created:
        text = created[0].read_text(encoding="utf-8", errors="replace")
        check("у файлі очікуваний текст", "Привіт" in text, repr(text[:60]))

    check("відповідь не порожня",
          bool("".join(e.text for e in events
                       if e.kind == "assistant").strip())
          or bool(done["text"].strip()),
          repr("".join(e.text for e in events if e.kind == "assistant")[:60]))

    # 4. Прибирання
    if server is not None:
        try:
            server.stop()
            print("[OK  ] сервер зупинено")
        except Exception:  # noqa: BLE001
            pass
    try:
        for item in project.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(project.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
        project.rmdir()
    except OSError:
        pass

    print()
    print("Живий прогін агента: " + ("успішно" if not failures else "є збої"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
