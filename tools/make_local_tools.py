"""Тимчасовий генератор TOOL.json для власних інструментів (лише ASCII)."""

import json
import os

BASE = os.path.join(".agents", "tools")

TOOLS = {
    "exact_snippet": {
        "description": "\u041f\u043e\u0432\u0435\u0440\u0442\u0430\u0454 \u0442\u043e\u0447\u043d\u0438\u0439 \u0442\u0435\u043a\u0441\u0442 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0430 \u0444\u0430\u0439\u043b\u0443 \u0434\u043b\u044f edit_file (\u0437 \u0432\u0456\u0434\u0441\u0442\u0443\u043f\u0430\u043c\u0438 \u0439 \u043b\u0430\u043f\u043a\u0430\u043c\u0438).",
        "props": {"path": ("string", "\u0424\u0430\u0439\u043b \u0432\u0456\u0434\u043d\u043e\u0441\u043d\u043e \u043a\u043e\u0440\u0435\u043d\u044f"),
                  "needle": ("string", "\u0420\u044f\u0434\u043e\u043a \u0430\u0431\u043e \u0439\u043e\u0433\u043e \u0447\u0430\u0441\u0442\u0438\u043d\u0430"),
                  "before": ("integer", "\u0420\u044f\u0434\u043a\u0456\u0432 \u0432\u0438\u0449\u0435"),
                  "after": ("integer", "\u0420\u044f\u0434\u043a\u0456\u0432 \u043d\u0438\u0436\u0447\u0435"),
                  "limit": ("integer", "\u0421\u043a\u0456\u043b\u044c\u043a\u0438 \u0437\u0431\u0456\u0433\u0456\u0432")},
        "req": ["path", "needle"],
        "src": "edit_file \u043f\u0430\u0434\u0430\u0454 \u043d\u0430 \u043d\u0435\u0442\u043e\u0447\u043d\u043e\u043c\u0443 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0456",
    },
    "content_guard": {
        "description": "\u041f\u0435\u0440\u0435\u0432\u0456\u0440\u044f\u0454 \u0432\u043c\u0456\u0441\u0442 \u041f\u0415\u0420\u0415\u0414 write_file: \u043e\u0431\u0440\u0456\u0437\u0430\u043d\u0438\u0439 \u0445\u0432\u0456\u0441\u0442, \u0434\u0443\u0436\u043a\u0438, \u0441\u0438\u043d\u0442\u0430\u043a\u0441\u0438\u0441 Python.",
        "props": {"path": ("string", "\u041a\u0443\u0434\u0438 \u043f\u0438\u0441\u0430\u0442\u0438"),
                  "content": ("string", "\u041f\u043e\u0432\u043d\u0438\u0439 \u0432\u043c\u0456\u0441\u0442 \u0444\u0430\u0439\u043b\u0443")},
        "req": ["content"],
        "src": "\u043e\u0431\u0440\u0456\u0437\u0430\u043d\u0438\u0439 write_file \u0437\u0430\u0442\u0435\u0440 \u043a\u0456\u043d\u0435\u0446\u044c \u0444\u0430\u0439\u043b\u0443",
    },
    "project_digest": {
        "description": "\u0421\u0442\u0438\u0441\u043b\u0438\u0439 \u0431\u0440\u0438\u0444\u0456\u043d\u0433 \u043f\u0440\u043e\u0454\u043a\u0442\u0443: \u0441\u0442\u0435\u043a, \u0442\u043e\u0447\u043a\u0430 \u0432\u0445\u043e\u0434\u0443, \u0442\u0435\u0441\u0442\u0438, \u0442\u0435\u043a\u0438.",
        "props": {"path": ("string", "\u0422\u0435\u043a\u0430 \u043f\u0440\u043e\u0454\u043a\u0442\u0443"),
                  "limit": ("integer", "\u0421\u043a\u0456\u043b\u044c\u043a\u0438 \u0444\u0430\u0439\u043b\u0456\u0432 \u0437\u0433\u0430\u0434\u0430\u0442\u0438")},
        "req": [],
        "src": "\u043c\u0430\u043b\u0438\u0439 \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0457 \u043c\u043e\u0434\u0435\u043b\u0456",
    },
}


def main() -> None:
    for name, cfg in TOOLS.items():
        folder = os.path.join(BASE, name)
        os.makedirs(folder, exist_ok=True)
        doc = {
            "format": 1,
            "name": name,
            "description": cfg["description"],
            "parameters": {
                "type": "object",
                "properties": {key: {"type": kind, "description": text}
                               for key, (kind, text) in cfg["props"].items()},
                "required": cfg["req"],
            },
            "created_at": 0,
            "source": cfg["src"],
            "runs": 0,
            "ok_runs": 0,
            "last_error": "",
            "enabled": True,
        }
        path = os.path.join(folder, "TOOL.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=True, indent=2)
        # Перевірка одразу: файл мусить читатись назад.
        with open(path, encoding="utf-8") as handle:
            json.load(handle)
        print("ok", name, os.path.getsize(path))


if __name__ == "__main__":
    main()
