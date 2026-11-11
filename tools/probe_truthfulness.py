"""Чи не вигадує агент результат: перевірка «правди» відповіді.

Сценарії, де модель схильна брехати: файл не створено, але відповідь
каже «створено»; інструмент упав, а відповідь каже «готово».
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_truth_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import response_engine as re_  # noqa: E402
from blackchpok_ide.tool_orchestrator import Observation  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


SUCCESS_WORDS = ("Готово", "Виконано", "Створено", "Записано", "Успішно")


def main() -> int:
    # 1. Модель каже «зробив», але жодного інструмента не викликано.
    obs: list[Observation] = []
    text = re_.final_answer("Я створив файл app.py і все працює.", obs)
    check("нема доказів — нема «Готово»",
          not any(w in text for w in SUCCESS_WORDS), text[:180])
    check("є чесне пояснення",
          any(w in text.lower() for w in ("не вдал", "не викон", "інструмент",
                                          "не підтверд", "доказ")), text[:180])

    # 2. Інструмент упав, модель каже «готово».
    failed = [Observation(name="write_file", ok=False, output="",
                          error="Відмовлено в доступі")]
    text = re_.final_answer("Готово, файл створено.", failed)
    check("провал інструмента не стає «Готово»",
          "Відмовлено" in text or "не вдал" in text.lower(), text[:200])
    check("провал згадує інструмент", "write_file" in text, text[:200])

    # 3. Порожній вивід успішного інструмента — не «Готово» з нічого.
    empty = [Observation(name="list_dir", ok=True, output="")]
    text = re_.answer_from_observations(empty).text
    check("порожній результат не вигадує вміст",
          bool(text.strip()) and not any(w in text for w in ("файлів 1", "знайдено 5")),
          text[:150])

    # 4. Сирий протокол не потрапляє в чат.
    raw = '{"tool_calls": [{"function": "write_file"}]} Готово!'
    clean = re_.clean_for_chat(raw)
    check("сирий протокол прибрано",
          "tool_calls" not in clean and '"function"' not in clean, clean[:150])

    # 5. Успішний результат справді показується.
    good = [Observation(name="write_file", ok=True, output="Записано app.py (120 B)")]
    text = re_.answer_from_observations(good).text
    check("успіх показує доказ", "app.py" in text, text[:150])

    # 6. Виняток у спостереженні (traceback) не лякає користувача.
    crashed = [Observation(name="run_command", ok=False, output="",
                           error="Traceback (most recent call last):\n  File \"x.py\"")]
    text = re_.final_answer("", crashed)
    check("стектрейс не вивалюється в чат",
          "Traceback (most recent call last)" not in text, text[:200])
    check("причина все ж названа", "run_command" in text, text[:200])

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
