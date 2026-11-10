"""Перевірка стабільності повного циклу: кілька прогонів поспіль.

Локальна модель недетермінована, тож один успішний прогін нічого не
доводить. Запускаємо кілька разів і дивимось, у скількох випадках агент
справді створив файли.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = sys.executable


def main() -> int:
    rounds = 3
    if len(sys.argv) > 1:
        rounds = max(1, int(sys.argv[1]))
    results: list[tuple[int, str]] = []
    for index in range(1, rounds + 1):
        print("=" * 70)
        print(f"прогін {index} з {rounds}")
        print("=" * 70)
        proc = subprocess.run(
            [PY, str(ROOT / "tools" / "check_full_cycle.py")],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        output = proc.stdout + proc.stderr
        # Витягуємо підсумок
        summary = ""
        for line in output.splitlines():
            if "готово за" in line or "Повний цикл:" in line:
                summary = line.strip()
        results.append((proc.returncode, summary))
        for line in output.splitlines():
            if "[FAIL]" in line:
                print("   ", line.strip())
        print(f"   код {proc.returncode} · {summary}")
        print()

    print("=" * 70)
    ok = sum(1 for code, _ in results if code == 0)
    for index, (code, summary) in enumerate(results, start=1):
        print(f"  прогін {index}: {'OK  ' if code == 0 else 'FAIL'} {summary}")
    print("=" * 70)
    print(f"Успішних прогонів: {ok} з {rounds}")
    if ok < rounds:
        print("НЕСТАБІЛЬНО: локальна модель іноді дає план без файлових дій.")
    return 0 if ok == rounds else 1


if __name__ == "__main__":
    raise SystemExit(main())
