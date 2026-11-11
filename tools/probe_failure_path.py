"""Що бачить користувач, коли ВСІ дії агента впали.

Сценарій: модель просить прочитати неіснуючий файл, інструмент падає.
Перевіряємо, що відповідь чесно каже про невдачу, а не «Готово».
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_fail_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import response_engine as re_  # noqa: E402
from blackchpok_ide.tool_orchestrator import Observation  # noqa: E402


def main() -> int:
    obs = [Observation(name="read_file", ok=False, output="",
                       error="Файл не існує: немає_такого.py")]
    print("== answer_from_observations (усе впало)")
    draft = re_.answer_from_observations(obs)
    print(repr(draft.text[:400]))
    print("порожньо:", not draft.text.strip())

    print("\n== explain_failure (окремо)")
    print(re_.explain_failure("", obs)[:400])

    print("\n== final_answer")
    try:
        text = re_.final_answer("", obs)
        print(repr(text[:400]))
    except Exception as exc:  # noqa: BLE001
        print(f"падіння: {type(exc).__name__}: {exc}")

    # Чи є в тексті слово успіху при повній невдачі?
    joined = " ".join(filter(None, [draft.text, re_.explain_failure("", obs),
                                    re_.final_answer("", obs) or ""]))
    bad = [w for w in ("Готово", "Виконано.", "Успішно") if w in joined]
    print("\nслова успіху в тексті невдачі:", bad or "немає")
    return 0


if __name__ == "__main__":
    sys.exit(main())
