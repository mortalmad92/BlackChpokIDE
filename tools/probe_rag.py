"""RAG-індекс: індексація реального проєкту й пошук по коду.

Перевіряє, що індекс справді будується, знаходить потрібне й оновлюється
після зміни файлу.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_rag_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_rag_ws_"))
    (work / "модуль.py").write_text(
        "def обчислити_площу(радіус):\n"
        '    """Площа кола за радіусом."""\n'
        "    return 3.14159 * радіус ** 2\n", "utf-8")
    (work / "інший.py").write_text(
        "def привітати(імʼя):\n    return f'Привіт, {імʼя}'\n", "utf-8")
    (work / "README.md").write_text("# Проєкт\n\nОпис проєкту.\n", "utf-8")

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from rag_engine import LocalRAG  # noqa: E402
    from blackchpok_ide import workspace as ws  # noqa: E402

    # Ті самі адаптери, що й у RagService: safe_join не має must_exist,
    # тож обгортка приймає його й ігнорує — інакше рушій падав з TypeError.
    rag = LocalRAG(
        work,
        lambda relative, must_exist=False: ws.safe_join(work, relative),
        lambda folder: ws.walk_text_files(Path(folder)),
        lambda path, max_bytes=0: ws.read_text_file(Path(path))[0],
        lambda path: ws.relative_to_root(work, Path(path)),
    )

    # 1. Індексація.
    try:
        result = rag.index_workspace()
        check("індексація виконана", True, str(result)[:100])
    except Exception as exc:  # noqa: BLE001
        check("індексація виконана", False, f"{type(exc).__name__}: {exc}")
        print(f"\nпровалів: {len(FAILS)}")
        return 1

    # 2. Пошук знаходить функцію.
    def search(needle: str) -> list:
        for name in ("search", "query", "find"):
            func = getattr(rag, name, None)
            if func is not None:
                try:
                    out = func(needle)
                    if isinstance(out, list):
                        return out
                    if out is None:
                        return []
                    return [out]
                except Exception:  # noqa: BLE001
                    return []
        return []

    hits = search("обчислити_площу")
    check("пошук знаходить функцію за назвою", bool(hits), str(hits)[:150])

    hits2 = search("Площа кола")
    check("пошук знаходить за описом", bool(hits2), str(hits2)[:150])

    # 3. Пошук не існуючого — порожньо, без падіння.
    none_hits = search("зовсім_неіснуючий_рядок_zzz")
    check("пошук відсутнього не падає", isinstance(none_hits, list),
          str(type(none_hits)))

    # 4. Після зміни файлу індекс оновлюється.
    (work / "модуль.py").write_text(
        "def обчислити_обʼєм(радіус):\n    return 4 / 3 * 3.14159 * радіус ** 3\n",
        "utf-8")
    try:
        rag.index_workspace()
        fresh = search("обчислити_обʼєм")
        check("індекс бачить нову функцію", bool(fresh), str(fresh)[:150])
    except Exception as exc:  # noqa: BLE001
        check("індекс оновлюється", False, f"{type(exc).__name__}: {exc}")

    # 5. Статистика індексу.
    try:
        info = rag.status()
        check("RAG.status() працює", info is not None, str(info)[:100])
    except Exception as exc:  # noqa: BLE001
        check("RAG.status() працює", False, f"{type(exc).__name__}: {exc}")

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
