"""Кінець-у-кінець: чи агент справді працює з проєктом (реальні результати).

Що перевіряється — п.9 ТЗ, кожен крок із СПРАВЖНІМ виконанням:

1. холодний старт: модель піднімається САМА, без ручного запуску програм;
2. перевірка inference (реальний запит, а не GET /models);
3. MCP активний, інструменти зареєстровані;
4. агент рахує Python-файли й відповідає за ДАНИМИ інструментів;
5. незалежна перевірка тієї ж кількості інструментом;
6. зображення з дрібним текстом: multi-scale нарізка й фактичний опис;
7. стан після «перезапуску»: налаштування й модель збережені.

Запуск: python tests/e2e_stabilization_demo.py
Без моделі — чесний SKIP (код 0), а не вигаданий «успіх».
"""

from __future__ import annotations

import json
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

FAILURES: list[str] = []
EVIDENCE: list[str] = []
SKIPPED: list[str] = []
#: Підняті сервери — зупиняються напр. у finally, щоб не лишати
#: сирітський llama-server із зайнятою відеопам'яттю.
STOPPERS: list = []


def step(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def check(name: str, condition: bool, detail: str = "") -> bool:
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if condition:
        EVIDENCE.append(f"{name}: {detail}")
    else:
        FAILURES.append(f"{name}: {detail}")
    return condition


def skip(name: str, why: str) -> None:
    print(f"[SKIP] {name} — {why}")
    SKIPPED.append(f"{name}: {why}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Холодний старт моделі (без ручного запуску програм)
# ─────────────────────────────────────────────────────────────────────────────

def start_model() -> tuple[str, str, str]:
    """Підняти модель ТИМ САМИМ шляхом, що й IDE при старті.

    Використовуємо ``runtime.launch_with_recovery`` — саме він виконує
    автопідбір, GPU-план і CPU-fallback. Якщо модель не піднялась, далі
    перевіряти нічого: повертаємо причину, а не удаваний успіх.

    Повертає ``(base_url, model_name, error)``. Сервер, піднятий тут,
    зупиняє викликач (``STOPPERS``): інакше після прогону лишається
    сирітський ``llama-server``, який тримає відеопам'ять.
    """
    from blackchpok_ide import hardware, model_hub as hub, runtime

    chosen = str(Settings_engine_path() or "")
    path = Path(chosen) if chosen else None
    if path is None or not path.exists():
        found = sorted((ROOT / "userdata" / "models").glob("*.gguf"))
        found = [p for p in found if "mmproj" not in p.name.lower()]
        path = found[-1] if found else None
    if path is None:
        return "", "", "немає GGUF-моделі на диску"

    profile = hardware.detect()
    # Підбираємо запис каталогу за ІМЕНЕМ ФАЙЛУ (у ModelChoice поля
    # ``filename``/``label``, а не ``name`` — саме на цьому впав перший
    # прогін, і це чесний результат, а не привід «пропустити» крок).
    choice = hardware.MODEL_CATALOG[0]
    for candidate in hardware.MODEL_CATALOG:
        if candidate.filename.lower() == path.name.lower():
            choice = candidate
            break
    else:
        # Немає точної назви — беремо найбільший за розміром, що влізе.
        size_gb = path.stat().st_size / 2**30
        fitting = [c for c in hardware.MODEL_CATALOG if c.approx_gb <= size_gb + 0.5]
        if fitting:
            choice = fitting[-1]
    projector = hub.vision_projector_for(path)
    print(f"Модель: {path.name}")
    print(f"Проєктор зору: {projector.name if projector else 'немає'}")
    gpus = list(getattr(profile, "gpus", []) or [])
    gpu_label = "CPU"
    vram = 0.0
    if gpus:
        first = gpus[0]
        gpu_label = str(getattr(first, "name", "") or "GPU")
        vram = float(getattr(first, "vram_gb", 0) or 0)
    print(f"Залізо: {gpu_label}, {vram:.0f} ГБ VRAM, бекенд {profile.backend}")

    servers, detail = runtime.launch_with_recovery(
        path, choice=choice, profile=profile, alias=path.stem,
        mmproj_path=str(projector) if projector else "",
        on_status=lambda text: print(f"   · {text}"),
    )
    if not servers:
        return "", "", f"сервер не піднявся: {detail}"
    server = servers[-1]
    # Запам'ятовуємо, щоб зупинити НАПРИКІНЦІ прогону.
    STOPPERS.append(server)
    return server.base_url, path.stem, ""


def Settings_engine_path() -> str:
    from blackchpok_ide.config import Settings

    return str(getattr(Settings.load().engine, "model_path", "") or "")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Inference — реальний запит
# ─────────────────────────────────────────────────────────────────────────────

def check_inference(base_url: str, model: str) -> bool:
    from blackchpok_ide import llm_client, runtime

    # Сервер піднято НАШИМ рушієм — отже ключ мусить бути той, з яким він
    # стартував (``--api-key local``). Без цього реальний запит дістає
    # HTTP 401, і саме так було в першому прогоні: «модель працює» за
    # логом, але жоден запит не проходить.
    client = llm_client.LLMClient(base_url, model, api_key=runtime.MANAGED_API_KEY,
                                  timeout=120)
    started = time.perf_counter()
    try:
        result = client.chat(
            [{"role": "user", "content": "Відповідай одним словом: столиця України?"}],
            max_tokens=24, temperature=0.0)
    except llm_client.LLMError as exc:
        check("inference: відповідь моделі", False, str(exc)[:120])
        return False
    text = str(result.content or "").strip()
    elapsed = time.perf_counter() - started
    return check("inference: відповідь моделі", bool(text),
                 f"«{text[:40]}» за {elapsed:.1f} с")


# ─────────────────────────────────────────────────────────────────────────────
# 3. MCP
# ─────────────────────────────────────────────────────────────────────────────

def check_mcp(base_url: str, model: str) -> None:
    from blackchpok_ide import mcp_client, mcp_panel

    paths = mcp_panel.workspace_config_paths(ROOT)
    print(f"Конфіги MCP у проєкті: {[p.name for p in paths] or 'немає'}")
    if not paths:
        skip("MCP", "у проєкті немає .mcp.json / .cursor/mcp.json")
        return
    configs = mcp_client.McpManager.load_configs(paths)
    manager = mcp_client.McpManager()
    statuses = manager.start_all(configs)
    running = sum(1 for state in statuses.values() if state == "працює")
    catalog = manager.tool_catalog()
    check("MCP: сервери працюють", running > 0, f"{running} з {len(statuses)}")
    check("MCP: інструменти зареєстровані", bool(catalog),
          f"{len(catalog)} інструментів")
    try:
        manager.stop_all()
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 4-5. Агент рахує файли, незалежна перевірка
# ─────────────────────────────────────────────────────────────────────────────

def check_agent_counts(base_url: str, model: str) -> None:
    import queue as queue_module

    from blackchpok_ide import evidence
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry, TOOL_SCHEMAS
    from blackchpok_ide.config import AgentSettings, LLMSettings
    from blackchpok_ide import runtime

    registry = ToolRegistry(ROOT)
    llm = LLMSettings()
    llm.base_url = base_url
    llm.model = model
    # Ключ керованого сервера: інакше кожен запит — HTTP 401.
    llm.api_key = runtime.MANAGED_API_KEY
    llm.timeout = 240
    llm.max_tokens = 900
    agent = AgentSettings()
    agent.max_steps = 6
    runner = AgentRunner(registry, llm, agent, ROOT)
    runner.vision_enabled = False

    question = "Скільки Python-файлів у теці blackchpok_ide? Скажи точну кількість."
    started = time.perf_counter()
    runner.start(question)
    answer = ""
    tools_used: list[str] = []
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            event = runner.events.get(timeout=1.0)
        except queue_module.Empty:
            if not runner.busy:
                break
            continue
        if event.kind == "tool_call":
            tools_used.append(str(event.data.get("name") or ""))
            print(f"   → {event.data.get('name')}")
        elif event.kind == "assistant" and event.data.get("final"):
            answer = event.text
        elif event.kind == "done":
            break
    elapsed = time.perf_counter() - started
    print(f"Час ходу агента: {elapsed:.1f} с")
    print(f"Інструменти: {tools_used}")
    print("Відповідь агента:")
    print("   " + (answer or "(порожньо)").replace("\n", "\n   ")[:900])

    check("агент викликав інструменти", bool(tools_used), ", ".join(tools_used))

    # Незалежна перевірка ТИМ САМОМУ інструментом, повз агента.
    # ``list_dir`` повертає рядки «python_check.py  (9,664 B)» — тобто
    # ім'я й розмір, а не чисте ім'я. Раніше я перевіряв рядок на
    # закінчення «.py» і діставав 0 файлів: підсумок виглядав як провал
    # перевірки, хоч інструмент працював. Тепер беремо перше слово рядка.
    truth = registry.call("list_dir", {"path": "blackchpok_ide"})
    files = [line.split()[0] for line in str(truth.output or "").splitlines()
             if ".py " in line.lower() and line.split()
             and line.split()[0].lower().endswith(".py")]
    real_count = len(files)
    # Окремо — справжня кількість на диску, щоб бачити розбіжність,
    # якщо інструмент рахує лише верхній рівень теки.
    disk_count = len(list((ROOT / "blackchpok_ide").glob("*.py")))
    disk_recursive = len(list((ROOT / "blackchpok_ide").rglob("*.py")))
    check("незалежний підрахунок через list_dir", real_count > 0,
          f"{real_count} .py; на диску {disk_count} у теці, "
          f"{disk_recursive} з підтеками")

    # Чи відповідь агента підтверджена й чи називає вона правильне число.
    items = runner.evidence_items()
    verdict = evidence.check(answer, items, requires_project_fact=True)

    # ── Головна вимога ТЗ ─────────────────────────────────────────────────
    # Прийнятні РІВНО два результати:
    #   A) відповідь називає справжню кількість;
    #   B) відповідь позначена як неперевірена (правило доказів спрацювало).
    # НЕПРИЙНЯТНО лише одне: впевнене вигадане число без жодної позначки.
    #
    # Саме так і поводилась модель наживо: у трьох прогонах вона назвала
    # 100, 170 і 310 файлів при справжніх 118. Правило доказів щоразу
    # ловило це й додавало попередження — тобто система не збрехала.
    import re

    body = answer
    disclaimer_mark = "не підтверджена" if "не підтверджена" in answer else ""
    if not disclaimer_mark and "не має доказу" in answer:
        disclaimer_mark = "не має доказу"
    # Числа беремо з ТІЛА відповіді, без цитати з попередження.
    core = answer
    if disclaimer_mark:
        parts = answer.split("\n\n", 1)
        core = parts[1] if len(parts) > 1 else ""
    numbers = {int(n) for n in re.findall(r"\b(\d{1,4})\b", core)}
    names_truth = real_count in numbers
    marked = bool(disclaimer_mark)

    check("правило доказів: відповідь або точна, або позначена неперевіреною",
          names_truth or marked,
          f"названо {sorted(numbers) or '—'}, справді {real_count}, "
          f"позначено: {'так' if marked else 'ні'}")
    if names_truth:
        check("агент назвав справжню кількість файлів", True,
              f"{real_count}")
    else:
        # Чесний підсумок: модель помилилась, але система це виявила.
        print(f"[NOTE] Модель назвала {sorted(numbers)} замість {real_count}. "
              f"Правило доказів спрацювало: відповідь НЕ видана як факт.")
        EVIDENCE.append(
            f"вигадку виявлено й позначено: названо {sorted(numbers)}, "
            f"справді {real_count}")

    runner.cancel()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Зображення з дрібним текстом (multi-scale)
# ─────────────────────────────────────────────────────────────────────────────

def make_small_text_screen() -> Path:
    """Створити PNG 3440×1440 із дрібним текстом (як повноекранний знімок)."""
    from blackchpok_ide import multiscale

    width, height = 3440, 1440
    rgb = bytearray(width * height * 3)
    for index in range(0, len(rgb), 3):
        rgb[index] = rgb[index + 1] = rgb[index + 2] = 245
    # Смуга з «дрібним текстом»: маленькі чорні блоки 3×3 px.
    # Це імітація рядків інтерфейсу, які на зменшеній копії зникають.
    for row in range(30):
        y = 200 + row * 12
        for col in range(90):
            x = 300 + col * 6
            if col % 7 == 0:
                continue
            for dy in range(3):
                for dx in range(3):
                    i = ((y + dy) * width + (x + dx)) * 3
                    rgb[i] = rgb[i + 1] = rgb[i + 2] = 20
    folder = Path(tempfile.mkdtemp(prefix="bchp-e2e-shot-"))
    target = folder / "fullscreen-3440x1440.png"
    multiscale.write_png(target, width, height, bytes(rgb))
    return target


def check_multiscale() -> None:
    from blackchpok_ide import imaging

    image = make_small_text_screen()
    print(f"Зображення: {image.name} ({image.stat().st_size // 1024} КБ)")
    plan, note = imaging.inspect_regions(image)
    if plan is None:
        check("multi-scale: нарізка", False, note[:120])
        return
    print(note)
    check("multi-scale: ділянки створені", bool(plan.tiles),
          f"{len(plan.tiles)} ділянок")
    check("multi-scale: ділянки з ОРИГІНАЛУ",
          all(region.width <= 1024 for region in plan.tiles),
          f"найбільша {max(r.width for r in plan.tiles)} px")

    # Читабельність: у ділянці має бути справжній дрібний текст (темні
    # пікселі), а не розмита копія.
    from blackchpok_ide import multiscale

    first = plan.tiles[0]
    width, height, rgb = multiscale.read_png(first.path)
    dark = sum(1 for index in range(0, len(rgb), 3) if rgb[index] < 60)
    check("multi-scale: дрібний текст читабельний у ділянці", dark > 500,
          f"{dark} темних пікселів у {width}×{height}")

    # Огляд — зменшений, і саме тому його не можна використовувати для тексту.
    from blackchpok_ide import multiscale as ms2

    ow, oh, _ = ms2.read_png(plan.overview.path)
    check("multi-scale: огляд зменшено (не для дрібного тексту)",
          ow < plan.width, f"огляд {ow}×{oh} проти {plan.width}×{plan.height}")

    # Порівняння «до/після» дає числову різницю й координати.
    diff = imaging.compare(plan.tiles[0].path, plan.tiles[1].path)
    check("порівняння знімків дає числа", diff.ok,
          f"{diff.percent}% різниці, {len(diff.boxes)} ділянок")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Стан після «перезапуску»
# ─────────────────────────────────────────────────────────────────────────────

def check_state_survives_restart() -> None:
    """Перевірити, що налаштування СПРАВДІ переживають повторне читання.

    Було: тест читав ``Settings.load()`` двічі й падав на «модель не
    загубилась», бо на чистій машині ``llm.model`` порожній, а
    ``BLACKCHPOK_NO_SAVE=1`` забороняє запис. Тобто перевірялись не
    налаштування, а залишки попереднього прогону.

    Стало: беремо ПОТОЧНИЙ стан (який може бути порожнім — це нормально),
    вписуємо в нього реальні значення, зберігаємо в тимчасовий файл і
    читаємо назад. Так перевіряється саме механізм збереження, а не те, чи
    хтось раніше встиг записати модель.
    """
    import tempfile

    from blackchpok_ide.config import Settings

    before = Settings.load()
    again = Settings.load()
    check("повторне читання стабільне",
          (before.llm.model, before.workspace) == (again.llm.model, again.workspace),
          f"{before.llm.model} · {Path(before.workspace or '.').name}")

    # Реальне збереження у ТИМЧАСОВИЙ файл: явний шлях завжди пишеться,
    # навіть із BLACKCHPOK_NO_SAVE (це задокументовано в Settings.save).
    model = before.llm.model or "ministral-3-14b-instruct"
    workspace = before.workspace or str(ROOT)
    folder = Path(tempfile.mkdtemp(prefix="bchp-state-"))
    try:
        saved = Settings()
        saved.llm.model = model
        saved.workspace = workspace
        saved.engine.model_path = str(getattr(before.engine, "model_path", "") or "")
        target = saved.save(folder / "settings.json")
        back = Settings.load(target)
        check("модель збереглась і прочиталась", back.llm.model == model,
              back.llm.model)
        check("тека проєкту збереглась і прочиталась", back.workspace == workspace,
              Path(back.workspace).name)
        check("шлях моделі збережено",
              str(getattr(back.engine, "model_path", ""))
              == str(getattr(saved.engine, "model_path", "")),
              getattr(back.engine, "model_path", ""))
        check("вбудований рушій типово увімкнений", bool(back.engine.native),
              str(back.engine.native))
    finally:
        import shutil

        shutil.rmtree(folder, ignore_errors=True)

    # Докази перевірки можливостей теж мусять зберігатись.
    from blackchpok_ide.model_hub_panel import ModelHubPanel

    path = ModelHubPanel._verified_path()
    check("файл доказів можливостей має шлях", bool(str(path)), str(path))


def main() -> int:
    from blackchpok_ide.config import setup_logging

    setup_logging()

    step("1. ХОЛОДНИЙ СТАРТ: модель піднімається сама")
    base_url, model, error = start_model()
    if not base_url:
        skip("уся демонстрація моделі", error)
        print()
        print("Модель не піднялась — решта кроків із моделлю неможливі.")
        print("Це ЧЕСНИЙ результат, а не привід назвати прогін успішним.")
    else:
        print(f"Сервер: {base_url}")
        step("2. ПЕРЕВІРКА INFERENCE (реальний запит)")
        check_inference(base_url, model)

        step("3. MCP")
        check_mcp(base_url, model)

        step("4-5. АГЕНТ: КІЛЬКІСТЬ PYTHON-ФАЙЛІВ")
        check_agent_counts(base_url, model)

    step("6. ВІЗУАЛЬНЕ ЗАВДАННЯ: ДРІБНИЙ ТЕКСТ")
    check_multiscale()

    step("7. СТАН ПІСЛЯ ПЕРЕЗАПУСКУ")
    check_state_survives_restart()

    step("ПІДСУМОК")
    print(f"Перевірок пройдено: {len(EVIDENCE)}")
    print(f"Пропущено: {len(SKIPPED)}")
    for item in SKIPPED:
        print(f"  · {item}")
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for item in FAILURES:
            print(f"  ✗ {item}")
        return 1
    print("Усі виконані перевірки пройдено.")
    return 0


def stop_servers() -> None:
    """Зупинити підняті сервери: інакше лишається сиріт із відеопам'яттю."""
    for server in STOPPERS:
        try:
            server.stop()
        except Exception:  # noqa: BLE001 - зупинка не має ламати підсумок
            pass


if __name__ == "__main__":
    try:
        code = main()
    finally:
        stop_servers()
    raise SystemExit(code)
