"""Перевірка документації: чи згадані в ній імена справді існують у коді.

Це не «тест на стиль», а захист від головної проблеми документації —
описати функцію, якої немає. Скрипт збирає всі виклики вигляду
``name(`` з ``docs/*.md`` і ``research/*.md``, відкидає вбудовані
імена Python і перевіряє, чи є решта в коді пакета.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILTINS = set("""
print len str int float open list dict set range json type main init super self
value name path text data read write add get run call save load search update
delete verify status close backup restore model file sqlite3 enumerate isinstance
format join split strip lower upper replace startswith endswith min max sum abs
round sorted zip any all next iter hash id repr tuple bool bytes object property
staticmethod classmethod dataclass field Path deque Counter defaultdict Mapping
Sequence Optional Callable Any Tuple List Dict Set Union Literal TypeVar Generic
Protocol cast wraps lru_cache partial reduce chain groupby count cycle repeat tee
cache cached_property contextmanager suppress StringIO BytesIO mkdtemp makedirs
remove rmdir unlink exists isfile isdir glob rglob stat resolve absolute
expanduser relative_to parts suffix stem parent parents iterdir walk copytree
copy2 move disk_usage which environ getenv sleep time monotonic perf_counter
strftime strptime localtime gmtime mktime fromtimestamp now today datetime date
timezone exec eval compile input help dir vars globals locals setattr getattr
hasattr delattr callable issubclass divmod pow chr ord bin hex oct ascii
""".split())


def main() -> int:
    code = "\n".join(
        item.read_text(encoding="utf-8", errors="replace")
        for item in (ROOT / "blackchpok_ide").rglob("*.py")
    )
    missing: list[tuple[str, str]] = []
    for folder in ("docs", "research"):
        directory = ROOT / folder
        if not directory.exists():
            continue
        for document in sorted(directory.glob("*.md")):
            text = document.read_text(encoding="utf-8", errors="replace")
            for name in sorted(set(re.findall(r"\b([a-z_][a-z0-9_]{3,})\(", text))):
                if name in BUILTINS or name in code:
                    continue
                missing.append((f"{folder}/{document.name}", name))
    for document, name in missing:
        print(f"{document}: {name}()")
    print(f"перевірено документів: {len(list((ROOT / 'docs').glob('*.md')))} "
          f"+ {len(list((ROOT / 'research').glob('*.md')))}; "
          f"підозрілих згадок: {len(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
