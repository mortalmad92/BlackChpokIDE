"""Перевірка рушія статистики змін (``blackchpok_ide.diff_stats``).

Скрипт без pytest: кожна перевірка друкує ``[OK  ]`` або ``[FAIL]``,
``main()`` повертає код виходу. Тимчасові теки створюються в
``<repo>\\.buildtmp\\<unique>`` і прибираються в кінці.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest.mock
import uuid
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import diff_stats as ds  # noqa: E402

failures = 0
TEMP_ROOT = ROOT / ".buildtmp"


def check(name: str, ok: bool, detail: str = "") -> None:
    """Надрукувати результат однієї перевірки."""
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def temp_dir(tag: str) -> Path:
    """Створити унікальну тимчасову теку під .buildtmp."""
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    folder = TEMP_ROOT / f"dstats-{tag}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Записати текст, створивши батьківські теки."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding, newline="\n")
    return path


# --------------------------------------------------------------------------- #
# 1-2. count_line_diff
# --------------------------------------------------------------------------- #


def test_count_line_diff_basic() -> None:
    """Базові додання/видалення та однакові файли."""
    added, removed = ds.count_line_diff("a\nb\nc\n", "a\nb\nc\n")
    check("count_line_diff: ідентичні файли -> (0, 0)", (added, removed) == (0, 0), f"{added}/{removed}")

    added, removed = ds.count_line_diff("a\nb\n", "a\nb\nc\nd\n")
    check("count_line_diff: два додані рядки", (added, removed) == (2, 0), f"+{added} -{removed}")

    added, removed = ds.count_line_diff("a\nb\nc\n", "a\nc\n")
    check("count_line_diff: один видалений рядок", (added, removed) == (0, 1), f"+{added} -{removed}")

    added, removed = ds.count_line_diff("a\nb\nc\n", "a\nB\nc\n")
    check("count_line_diff: заміна рядка -> +1 -1", (added, removed) == (1, 1), f"+{added} -{removed}")

    added, removed = ds.count_line_diff("", "x\ny\n")
    check("count_line_diff: порожній старий файл", (added, removed) == (2, 0), f"+{added} -{removed}")


def test_count_line_diff_huge() -> None:
    """Великий файл (30 000 рядків) рахується швидко й розумно."""
    old = "\n".join(f"рядок {index}" for index in range(30_000)) + "\n"
    lines = old.splitlines()
    lines[15_000] = "рядок ЗМІНЕНО"
    new = "\n".join(lines) + "\n"

    started = time.perf_counter()
    added, removed = ds.count_line_diff(old, new)
    elapsed = time.perf_counter() - started

    check("count_line_diff: 30 000 рядків < 2 с", elapsed < 2.0, f"{elapsed:.2f} с")
    check(
        "count_line_diff: великий файл дає осмислену різницю",
        0 <= added <= 2 and 0 <= removed <= 2,
        f"+{added} -{removed}",
    )
    # Зсув усього файлу на один рядок не має давати 30 000 видалень.
    shifted = "нова шапка\n" + old
    started = time.perf_counter()
    added, removed = ds.count_line_diff(old, shifted)
    elapsed = time.perf_counter() - started
    check("count_line_diff: вставка на початку великого файлу < 2 с", elapsed < 2.0, f"{elapsed:.2f} с")
    check(
        "count_line_diff: вставка на початку дає мало змін",
        added == 1 and removed <= 5,
        f"+{added} -{removed}",
    )

    # Хвіст за межами 20 000 рядків теж рахується (додано 100 рядків у кінці).
    longer = old + "".join(f"додаток {index}\n" for index in range(100))
    started = time.perf_counter()
    added, removed = ds.count_line_diff(old, longer)
    elapsed = time.perf_counter() - started
    check("count_line_diff: великий хвіст < 2 с", elapsed < 2.0, f"{elapsed:.2f} с")
    check("count_line_diff: 100 рядків у кінці -> +100 -0", (added, removed) == (100, 0), f"+{added} -{removed}")


# --------------------------------------------------------------------------- #
# 3. Форматування
# --------------------------------------------------------------------------- #


def test_formatting() -> None:
    """stat_text і summary_text у стилі IDE."""
    one = ds.FileChange("a.py", 13, 0)
    check("FileChange.stat_text == '+13 -0'", one.stat_text == "+13 -0", one.stat_text)
    check("FileChange.total == 13", one.total == 13, str(one.total))
    check("FileChange.status_label (modified)", one.status_label == "змінений", one.status_label)
    check("FileChange.status_label (added)", ds.FileChange("b.py", 3, 2, "added").status_label == "новий")
    check("FileChange.status_label (deleted)", ds.FileChange("c.py", 0, 5, "deleted").status_label == "видалений")
    check(
        "FileChange.status_label (renamed)",
        ds.FileChange("d.py", 1, 1, "renamed").status_label == "перейменований",
    )
    check("FileChange приклад '+0 -7'", ds.FileChange("e.py", 0, 7).stat_text == "+0 -7")

    change_set = ds.ChangeSet(files=[ds.FileChange("a.py", 2_655, 528)])
    check("ChangeSet.summary_text == '+2 655 -528'", change_set.summary_text == "+2 655 -528", change_set.summary_text)
    check("ChangeSet.added/removed", (change_set.added, change_set.removed) == (2_655, 528))
    check("ChangeSet маленькі числа без пробілу", ds.ChangeSet(files=[ds.FileChange("a.py", 13, 0)]).summary_text == "+13 -0")
    check("ChangeSet.is_empty для порожнього", ds.ChangeSet().is_empty)
    check("ChangeSet.is_empty == False для непорожнього", not change_set.is_empty)


# --------------------------------------------------------------------------- #
# 4. diff_file_pair
# --------------------------------------------------------------------------- #


def test_diff_file_pair() -> None:
    """Обидва файли, лише новий, лише старий."""
    folder = temp_dir("pair")
    try:
        old = write(folder / "a.py.bak", "один\nдва\nтри\n")
        new = write(folder / "a.py", "один\nдва\nтри\nчотири\n")
        change = ds.diff_file_pair(old, new, display="a.py")
        check(
            "diff_file_pair: обидва існують -> +1 -0, modified",
            (change.added, change.removed, change.status) == (1, 0, "modified"),
            f"{change.stat_text} {change.status}",
        )
        check("diff_file_pair: display використано", change.path == "a.py", change.path)

        fresh = write(folder / "fresh.py", "x\ny\nz\n")
        change = ds.diff_file_pair(None, fresh, display="fresh.py")
        check(
            "diff_file_pair: лише новий -> весь файл доданий",
            (change.added, change.removed, change.status) == (3, 0, "added"),
            f"{change.stat_text} {change.status}",
        )

        gone = write(folder / "gone.py.bak", "p\nq\n")
        change = ds.diff_file_pair(gone, None, display="gone.py")
        check(
            "diff_file_pair: лише старий -> весь файл видалений",
            (change.added, change.removed, change.status) == (0, 2, "deleted"),
            f"{change.stat_text} {change.status}",
        )

        change = ds.diff_file_pair(folder / "gone.py.bak", folder / "no-such.py", display="no-such.py")
        check(
            "diff_file_pair: цільовий файл зник -> deleted",
            change.status == "deleted" and change.removed == 2,
            f"{change.stat_text} {change.status}",
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 5. make_unified_diff
# --------------------------------------------------------------------------- #


def test_make_unified_diff() -> None:
    """Заголовки, +/- рядки та маркер обрізання."""
    old = "def main():\n    return 1\n"
    new = "def main():\n    return 2\n    # новий коментар\n"
    text = ds.make_unified_diff(old, new, path="app/main.py")
    check("make_unified_diff: заголовок --- a/app/main.py", "--- a/app/main.py" in text)
    check("make_unified_diff: заголовок +++ b/app/main.py", "+++ b/app/main.py" in text)
    plus = [line for line in text.splitlines() if line.startswith("+") and not line.startswith("+++")]
    minus = [line for line in text.splitlines() if line.startswith("-") and not line.startswith("---")]
    check("make_unified_diff: є рядки + і -", bool(plus) and bool(minus), f"+{len(plus)} -{len(minus)}")
    check("make_unified_diff: новий рядок видно", any("новий коментар" in line for line in plus))

    big_old = "\n".join(f"рядок {index}" for index in range(800))
    big_new = "\n".join(f"рядок {index} змінено" for index in range(800))
    big_text = ds.make_unified_diff(big_old, big_new, path="big.py", max_lines=60)
    lines = big_text.splitlines()
    check("make_unified_diff: обрізано до max_lines + маркер", len(lines) <= 61, f"{len(lines)} рядків")
    check(
        "make_unified_diff: український маркер обрізання",
        "… (показано перші 60 рядків)" in big_text,
        lines[-1] if lines else "",
    )

    check("make_unified_diff: без змін -> порожній рядок", ds.make_unified_diff("a\nb\n", "a\nb\n") == "")


# --------------------------------------------------------------------------- #
# 6. preview_edit
# --------------------------------------------------------------------------- #


def test_preview_edit() -> None:
    """Успішна правка, відсутній та неоднозначний фрагмент."""
    text = "import os\n\n\ndef main():\n    print('старий')\n    return 0\n"
    ok, diff, counts = ds.preview_edit(text, "    print('старий')\n", "    print('новий')\n", path="a.py")
    added, removed = counts
    check("preview_edit: успіх -> ok=True", ok is True, str(ok))
    check("preview_edit: успіх -> added/removed > 0", added > 0 and removed > 0, f"+{added} -{removed}")
    check("preview_edit: diff містить новий текст", "новий" in diff, diff.splitlines()[0] if diff else "")

    ok, message, counts = ds.preview_edit(text, "невідомий рядок", "щось", path="a.py")
    check("preview_edit: фрагмент не знайдено -> ok=False", ok is False)
    check("preview_edit: пояснення українською", "не знайдено" in message, message)
    check("preview_edit: counts == (0, 0) при помилці", counts == (0, 0), str(counts))

    doubled = "x = 1\nx = 1\ny = 2\n"
    ok, message, counts = ds.preview_edit(doubled, "x = 1", "x = 9", path="b.py")
    check("preview_edit: неоднозначний фрагмент -> ok=False", ok is False)
    check("preview_edit: повідомлення містить кількість збігів", "2" in message, message)


# --------------------------------------------------------------------------- #
# 7. read_text_safe
# --------------------------------------------------------------------------- #


def test_read_text_safe() -> None:
    """Бінарний вміст і відсутній файл -> None."""
    folder = temp_dir("read")
    try:
        binary = folder / "bin.dat"
        binary.write_bytes(b"\x00\x01\x02BINARY\x00tail")
        check("read_text_safe: NUL-байти -> None", ds.read_text_safe(binary) is None)
        check("read_text_safe: відсутній файл -> None", ds.read_text_safe(folder / "nope.txt") is None)

        good = write(folder / "good.txt", "привіт\nсвіт\n")
        check("read_text_safe: звичайний текст читається", ds.read_text_safe(good) == "привіт\nсвіт\n")

        big = write(folder / "big.txt", "x" * 5_000)
        check("read_text_safe: завеликий файл -> None", ds.read_text_safe(big, limit_bytes=1_000) is None)
        check("read_text_safe: тека -> None", ds.read_text_safe(folder) is None)

        utf16 = folder / "utf16.txt"
        utf16.write_bytes("скорочено A".encode("utf-16"))  # BOM + NUL у кожному ASCII-байті
        check("read_text_safe: UTF-16 з NUL -> None", ds.read_text_safe(utf16) is None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 8. backup_changes
# --------------------------------------------------------------------------- #


def test_backup_changes() -> None:
    """Резервні копії: змінений, видалений файл і .bak у .buildtmp."""
    folder = temp_dir("backup")
    try:
        write(folder / "a.py.bak", "рядок 1\nрядок 2\nрядок 3\n")
        write(folder / "a.py", "рядок 1\nрядок 2\nрядок 3\nрядок 4\nрядок 5\n")

        write(folder / "gone.py.bak", "старий вміст\n")

        nested = folder / ".buildtmp" / "inner"
        write(nested / "skip.py.bak", "a\n")
        write(nested / "skip.py", "a\nb\n")

        write(folder / "same.py.bak", "однаково\n")
        write(folder / "same.py", "однаково\n")

        change_set = ds.backup_changes(folder)
        by_path = {item.path: item for item in change_set.files}
        check("backup_changes: source == 'backup'", change_set.source == "backup", change_set.source)
        check("backup_changes: знайдено рівно 2 файли", len(change_set.files) == 2, str(sorted(by_path)))

        modified = by_path.get("a.py")
        check("backup_changes: a.py присутній", modified is not None, str(sorted(by_path)))
        if modified is not None:
            check(
                "backup_changes: a.py -> modified +2 -0",
                (modified.status, modified.added, modified.removed) == ("modified", 2, 0),
                f"{modified.status} {modified.stat_text}",
            )

        deleted = by_path.get("gone.py")
        check("backup_changes: файл без поточної версії -> deleted", deleted is not None and deleted.status == "deleted",
              deleted.status if deleted else "відсутній")
        if deleted is not None:
            check("backup_changes: gone.py -> -1", deleted.removed == 1, deleted.stat_text)

        check("backup_changes: .bak у .buildtmp ігнорується", "skip.py" not in by_path and not any(
            ".buildtmp" in item.path for item in change_set.files
        ), str(sorted(by_path)))
        check("backup_changes: однаковий файл не потрапляє", "same.py" not in by_path, str(sorted(by_path)))

        ordered = ds.backup_changes(folder, limit=1)
        check("backup_changes: limit обмежує кількість", len(ordered.files) == 1, str(len(ordered.files)))
        total = change_set.added + change_set.removed
        check("backup_changes: підсумок рахується", total == 3, str(total))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 9-10. detect_changes і ChangeSet.top
# --------------------------------------------------------------------------- #


def test_detect_changes() -> None:
    """Без git працює джерело 'backup'; порожня тека дає порожній набір."""
    # Тека ПОЗА репозиторієм: раніше тут був temp_dir(), а він створює теку
    # в .buildtmp, тобто ВСЕРЕДИНІ цього ж репозиторію. Поки git не було,
    # різниці не було; після встановлення git тека успадкувала репозиторій
    # вище й джерелом ставав 'git' (а .buildtmp ще й у .gitignore, тому
    # змін було нуль). Тепер перевіряємо саме те, що заявлено, — роботу без git.
    folder = Path(tempfile.mkdtemp(prefix="dstats-detect-"))
    try:
        empty = ds.detect_changes(folder)
        check("detect_changes: порожня тека -> is_empty", empty.is_empty, str(len(empty.files)))
        check(
            "detect_changes: джерело з fallback-набору",
            empty.source in {"backup", "mtime", "git"},
            empty.source,
        )
        check("detect_changes: повертає ChangeSet", isinstance(empty, ds.ChangeSet))
        check("detect_changes: generated_at заповнено", empty.generated_at > 0)

        write(folder / "b.py.bak", "a\n")
        write(folder / "b.py", "a\nb\nc\n")
        filled = ds.detect_changes(folder)
        check(
            "detect_changes: знайдено зміну через резервну копію",
            filled.source == "backup" and len(filled.files) == 1,
            f"{filled.source} {len(filled.files)}",
        )

        only_backup = ds.detect_changes(folder, prefer_git=False)
        check("detect_changes: prefer_git=False -> 'backup'", only_backup.source == "backup", only_backup.source)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_change_set_top() -> None:
    """top(2) — не більше двох і за спаданням total."""
    files = [
        ds.FileChange("small.py", 1, 0),
        ds.FileChange("big.py", 100, 20),
        ds.FileChange("mid.py", 10, 5),
        ds.FileChange("tiny.py", 0, 0),
    ]
    change_set = ds.ChangeSet(files=files, source="git")
    top_two = change_set.top(2)
    check("ChangeSet.top(2): рівно 2 елементи", len(top_two) == 2, str(len(top_two)))
    check(
        "ChangeSet.top(2): відсортовано за total спадаюче",
        [item.path for item in top_two] == ["big.py", "mid.py"],
        str([item.path for item in top_two]),
    )
    check("ChangeSet.top: набір не мутується", len(change_set.files) == 4, str(len(change_set.files)))
    check("ChangeSet.top(0) -> []", change_set.top(0) == [])
    check("ChangeSet.top(99) -> усі файли", len(change_set.top(99)) == 4)
    check("ChangeSet.by_status('added') працює", ds.ChangeSet(files=[ds.FileChange("n.py", 1, 0, "added")]).by_status("added")[0].path == "n.py")


# --------------------------------------------------------------------------- #
# 11. git_changes без git
# --------------------------------------------------------------------------- #


def test_git_changes() -> None:
    """git_changes не падає: None або коректний ChangeSet із source='git'."""
    folder = temp_dir("git")
    try:
        write(folder / "plain.py", "x = 1\n")
        try:
            result = ds.git_changes(folder, timeout=10.0)
            raised = ""
        except Exception as exc:  # noqa: BLE001 — саме відсутність винятку й перевіряємо
            result = None
            raised = f"{type(exc).__name__}: {exc}"
        check("git_changes: не викидає винятків", raised == "", raised)
        check(
            "git_changes: None або ChangeSet(source='git')",
            result is None or (isinstance(result, ds.ChangeSet) and result.source == "git"),
            "None" if result is None else result.source,
        )
        if result is not None:
            check(
                "git_changes: усі шляхи відносні й не службові",
                all(not item.path.startswith(("/", "\\")) for item in result.files),
                str([item.path for item in result.files][:5]),
            )
        check("git_changes: неіснуюча тека -> None", ds.git_changes(folder / "no-such-dir", timeout=10.0) is None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_git_parsing() -> None:
    """Розбір porcelain/numstat без справжнього git (синтетичні відповіді)."""
    raw = (
        " M src/app.py\0?? new.py\0R  lib/new.py\0lib/old.py\0"
        "D  gone.py\0 M .buildtmp/x.py\0 M a.pyc\0 M keep.bak\0"
    )
    parsed = ds._parse_porcelain_z(raw)
    check("porcelain -z: розібрано 7 записів", len(parsed) == 7, str(len(parsed)))
    check(
        "porcelain -z: перейменування дає старий шлях",
        ("R ", "lib/new.py", "lib/old.py") in parsed,
        str(parsed[2]),
    )

    numstat = "12\t3\tsrc/app.py\n-\t-\tlogo.png\n5\t1\tdocs/{old.md => new.md}\n"
    with unittest.mock.patch.object(ds, "_run_git", lambda *args, **kwargs: numstat):
        mapping = ds._numstat_map(Path("."), ["diff", "--numstat", "HEAD"], 5.0)
    check("numstat: звичайний файл +12 -3", mapping.get("src/app.py") == (12, 3, False), str(mapping.get("src/app.py")))
    check("numstat: бінарний файл позначено", mapping.get("logo.png") == (0, 0, True), str(mapping.get("logo.png")))
    check(
        "numstat: стислий шлях «{old => new}» розгорнуто",
        mapping.get("docs/old.md") == (5, 1, False) and mapping.get("docs/new.md") == (5, 1, False),
        str(sorted(key for key in mapping if key.startswith("docs/"))),
    )

    folder = temp_dir("gitfake")
    try:
        write(folder / "new.py", "a\nb\nc\n")
        status = " M src/app.py\0?? new.py\0R  lib/new.py\0lib/old.py\0 M .buildtmp/x.py\0 M old.pyc\0"

        def fake_git(root: Path, args: list[str], timeout: float) -> str | None:
            if args and args[0] == "status":
                return status
            if args[:2] == ["diff", "--numstat"]:
                return "12\t3\tsrc/app.py\n"
            return None

        with unittest.mock.patch.object(ds, "_run_git", fake_git):
            change_set = ds.git_changes(folder, timeout=5.0)
        check("git_changes (синтетика): source == 'git'", change_set is not None and change_set.source == "git",
              change_set.source if change_set else "None")
        found = {item.path: item for item in (change_set.files if change_set else [])}
        check("git_changes: службові шляхи відкинуто", ".buildtmp/x.py" not in found and "old.pyc" not in found, str(sorted(found)))
        check(
            "git_changes: modified +12 -3",
            found.get("src/app.py") is not None
            and (found["src/app.py"].added, found["src/app.py"].removed, found["src/app.py"].status) == (12, 3, "modified"),
            found["src/app.py"].stat_text if "src/app.py" in found else "відсутній",
        )
        check(
            "git_changes: невідстежений файл -> added +3",
            found.get("new.py") is not None and (found["new.py"].added, found["new.py"].status) == (3, "added"),
            found["new.py"].stat_text if "new.py" in found else "відсутній",
        )
        check(
            "git_changes: перейменування -> renamed",
            found.get("lib/new.py") is not None and found["lib/new.py"].status == "renamed",
            found["lib/new.py"].status if "lib/new.py" in found else "відсутній",
        )
        check("git_changes: підсумок +27 -6", change_set.summary_text == "+27 -6" if change_set else False,
              change_set.summary_text if change_set else "None")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Точка входу
# --------------------------------------------------------------------------- #


def main() -> int:
    """Запустити всі перевірки й повернути код виходу."""
    started = time.perf_counter()
    print("=== Перевірка blackchpok_ide.diff_stats ===")
    test_count_line_diff_basic()
    test_count_line_diff_huge()
    test_formatting()
    test_diff_file_pair()
    test_make_unified_diff()
    test_preview_edit()
    test_read_text_safe()
    test_backup_changes()
    test_detect_changes()
    test_change_set_top()
    test_git_changes()
    test_git_parsing()
    elapsed = time.perf_counter() - started
    print(f"--- {elapsed:.2f} с, провалів: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
