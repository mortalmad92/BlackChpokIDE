"""Integrity check: every created file exists, compiles and is not truncated."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FILES = [
    "blackchpok_ide/local_guard.py",
    "tests/test_local_guard.py",
    "tools/check_skills_usage.py",
    "tools/check_local_tools.py",
    "tools/make_local_tools.py",
    ".agents/skills/local-models/SKILL.md",
    ".agents/skills/loop-breaker/SKILL.md",
    ".agents/skills/context-diet/SKILL.md",
    ".agents/skills/honest-report/SKILL.md",
    ".agents/tools/exact_snippet/TOOL.json",
    ".agents/tools/exact_snippet/tool.py",
    ".agents/tools/content_guard/TOOL.json",
    ".agents/tools/content_guard/tool.py",
    ".agents/tools/project_digest/TOOL.json",
    ".agents/tools/project_digest/tool.py",
]

TAILS = {
    "blackchpok_ide/local_guard.py": "def report(",
    "tests/test_local_guard.py": "unittest.main()",
    "tools/check_skills_usage.py": "raise SystemExit(main())",
    "tools/check_local_tools.py": "raise SystemExit(main())",
}


def main() -> int:
    problems = []
    for path in FILES:
        if not os.path.isfile(path):
            problems.append("MISSING " + path)
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        if not text.strip():
            problems.append("EMPTY " + path)
            continue
        if path.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as exc:
                problems.append("BAD JSON " + path + ": " + str(exc))
            continue
        if path.endswith(".py"):
            try:
                compile(text, path, "exec", dont_inherit=True)
            except SyntaxError as exc:
                problems.append("BAD PY " + path + ": " + str(exc))
                continue
        tail = TAILS.get(path)
        if tail and tail not in text:
            problems.append("TRUNCATED " + path + " (no tail marker)")
        if path.endswith("SKILL.md") and not text.startswith("---"):
            problems.append("BAD SKILL " + path)
        print("ok  %-52s %6d bytes" % (path, len(text)))

    print()
    if problems:
        for item in problems:
            print("PROBLEM", item)
        return 1
    print("all files on disk, compilable, not truncated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
