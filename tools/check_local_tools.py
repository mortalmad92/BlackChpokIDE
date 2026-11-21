"""Smoke run of the custom local-model tools (ASCII only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blackchpok_ide import extensions as ext  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def call(store, name, arguments):
    tool = store.get_tool(name)
    if tool is None:
        return False, "no such tool: " + name
    return ext.run_custom_tool(tool, arguments)


def show(title, ok, text):
    print("\n[" + title + "] ok=" + str(ok))
    print(text[:400])


def main() -> int:
    store = ext.ExtensionStore(ROOT)
    print("tools:", [item.name for item in store.tools()])

    show("content_guard broken",
         *call(store, "content_guard",
               {"path": "a.py", "content": "def f(:\n    pass\n"}))
    show("content_guard good",
         *call(store, "content_guard",
               {"path": "a.py", "content": "def f():\n    return 1\n"}))
    show("content_guard truncated",
         *call(store, "content_guard",
               {"path": "a.py",
                "content": "def f():\n    if x:\nf len(y) > 3:"}))
    show("exact_snippet",
         *call(store, "exact_snippet",
               {"path": "blackchpok_ide/agent.py",
                "needle": "REPEAT_LIMIT = 3", "before": 1, "after": 1}))
    show("project_digest", *call(store, "project_digest", {}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
