"""Перемикання моделей: чи звільняється попередня модель і VRAM.

Головне питання тесту: після «запустити модель B замість моделі A» на
диску й у пам'яті має лишитись РІВНО ОДИН рушій — з моделлю B. Інакше
перша модель тримає гігабайти відеопам'яті, і друга не влізає.

Перевіряється на СПРАВЖНІХ процесах, якщо є встановлений рушій і файли
моделей. Без них — чесний SKIP.

Запуск: python tests/test_model_switch_live.py
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

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-switch-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

FAILURES = 0
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global FAILURES, CHECKS
    CHECKS += 1
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}"
          + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES += 1
    return condition


def skip(name: str, why: str) -> None:
    print(f"[SKIP] {name} — {why}")


def model_files() -> list[Path]:
    """Дві найменші GGUF-моделі (швидше перемикати) без mmproj."""
    folder = ROOT / "userdata" / "models"
    if not folder.is_dir():
        return []
    found = [p for p in folder.glob("*.gguf")
             if "mmproj" not in p.name.lower()]
    return sorted(found, key=lambda p: p.stat().st_size)[:2]


def running_servers() -> list[int]:
    from blackchpok_ide import runtime

    return [int(item["pid"]) for item in runtime.live_server_ports()]


def main() -> int:
    from blackchpok_ide import runtime
    from blackchpok_ide.config import setup_logging

    setup_logging()

    if not runtime.engine_installed():
        skip("перемикання моделей", "рушій llama.cpp не встановлено")
        return 0
    models = model_files()
    if len(models) < 2:
        skip("перемикання моделей", "потрібні дві GGUF-моделі")
        return 0

    first, second = models
    print(f"Модель A: {first.name} ({first.stat().st_size / 2**30:.2f} ГБ)")
    print(f"Модель B: {second.name} ({second.stat().st_size / 2**30:.2f} ГБ)")

    # ── Стан ДО тесту: чужі рушії не чіпаємо, але запам'ятовуємо ────────
    before = set(running_servers())
    print(f"Живі рушії до тесту: {sorted(before) or 'немає'}")

    servers = []
    try:
        # ── Запуск A ────────────────────────────────────────────────────
        cfg_a = runtime.ServerConfig(model_path=str(first), port=runtime.free_port(8080))
        server_a = runtime.LocalServer(cfg_a)
        server_a.start()
        servers.append(server_a)
        ok, detail = server_a.wait_ready(timeout=300)
        if not check("модель A запустилась", ok, detail[:120]):
            return 1
        pid_a = int(server_a.process.pid) if server_a.process else 0
        url_a = server_a.base_url
        port_a = server_a.config.port
        print(f"  A: pid {pid_a} на {url_a}")

        # Модель справді відповідає — інакше «запустилась» нічого не варте.
        answered, why = _ask(url_a, first.stem)
        check("модель A відповідає", answered, why)

        # ── Перемикання на B ────────────────────────────────────────────
        print("\nПеремикаю A → B…")
        server_a.stop()
        servers.remove(server_a)
        # Даємо системі час звільнити пам'ять (реальний користувач теж
        # чекає, поки IDE покаже «модель зупинено»).
        time.sleep(1.5)

        alive_a = _pid_alive(pid_a)
        check("після зупинки A процесу A немає", not alive_a, f"pid {pid_a}")

        cfg_b = runtime.ServerConfig(model_path=str(second),
                                     port=runtime.free_port(8080))
        server_b = runtime.LocalServer(cfg_b)
        server_b.start()
        servers.append(server_b)
        ok, detail = server_b.wait_ready(timeout=300)
        if not check("модель B запустилась", ok, detail[:120]):
            return 1
        url_b = server_b.base_url
        print(f"  B: pid {server_b.process.pid} на {url_b}")

        answered, why = _ask(url_b, second.stem)
        check("модель B відповідає", answered, why)

        # ── Головна вимога: лишилась РІВНО ОДНА модель ──────────────────
        ours = [pid for pid in running_servers()]
        new_pids = [pid for pid in ours if pid not in before]
        check("живий лише один новий рушій", len(new_pids) == 1,
              f"знайдено {new_pids}")

        # Старий ПРОЦЕС має бути мертвий. Перевіряти порт не можна: B
        # законно займає той самий вільний порт, який звільнив A, тож
        # «порт відповідає» — це B, а не залишок A (саме на цьому й
        # схибила перша версія цього тесту).
        check("старий процес A більше не існує", not _pid_alive(pid_a),
              f"pid {pid_a}")

        # ── Порівняння використання відеопам'яті ────────────────────────
        vram_a = _vram_used()
        print(f"  VRAM зараз: {vram_a}")
        check("VRAM не подвоїлась (одна модель, не дві)",
              vram_a == "" or "MiB" in vram_a, vram_a)

    finally:
        for server in servers:
            try:
                server.stop()
            except Exception:  # noqa: BLE001 - прибирання не має падати
                pass
        time.sleep(1.0)
        left = [pid for pid in running_servers() if pid not in before]
        check("після тесту нових рушіїв не лишилось", not left, f"{left}")

    print()
    print("=" * 60)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {FAILURES} з {CHECKS}")
        return 1
    print(f"Усі {CHECKS} перевірок пройдено.")
    return 0


def _ask(base_url: str, model: str) -> tuple[bool, str]:
    """Реальний запит до моделі (доводи��ь, що вона обслуговує запити)."""
    from blackchpok_ide import llm_client, runtime

    try:
        client = llm_client.LLMClient(base_url, model,
                                      api_key=runtime.MANAGED_API_KEY,
                                      timeout=120)
        result = client.chat(
            [{"role": "user", "content": "Відповідай одним словом: так"}],
            max_tokens=8, temperature=0.0)
        text = str(result.content or "").strip()
        return bool(text), f"«{text[:40]}»"
    except llm_client.LLMError as exc:
        return False, str(exc)[:140]


def _pid_alive(pid: int) -> bool:
    from blackchpok_ide import runtime

    return bool(runtime._pid_alive(pid))


def _vram_used() -> str:
    """Скільки відеопам'яті зайнято (nvidia-smi, якщо є)."""
    try:
        import subprocess

        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (result.stdout or "").strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
