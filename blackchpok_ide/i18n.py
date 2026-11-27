"""Dvomovna lokalizatsiia interfeisu BlackChpok IDE (uk / en)."""
from __future__ import annotations

import json
from pathlib import Path

_LANG_FILE = Path.home() / ".blackchpok_lang"
_CURRENT_LANG = "uk"


def get_lang() -> str:
    global _CURRENT_LANG
    try:
        if _LANG_FILE.is_file():
            val = _LANG_FILE.read_text(encoding="utf-8").strip().lower()
            if val in ("uk", "en"):
                _CURRENT_LANG = val
    except Exception:
        pass
    return _CURRENT_LANG


def set_lang(lang: str) -> str:
    global _CURRENT_LANG
    val = "en" if str(lang or "").strip().lower().startswith("en") else "uk"
    _CURRENT_LANG = val
    try:
        _LANG_FILE.write_text(val, encoding="utf-8")
    except Exception:
        pass
    return val


def toggle_lang() -> str:
    return set_lang("en" if get_lang() == "uk" else "uk")


_STRINGS: dict[str, dict[str, str]] = {
    "cat_file": {"uk": "\u0424\u0430\u0439\u043b \u25be", "en": "File \u25be"},
    "cat_edit": {"uk": "\u041f\u0440\u0430\u0432\u043a\u0430 \u25be", "en": "Edit \u25be"},
    "cat_view": {"uk": "\u0412\u0438\u0433\u043b\u044f\u0434 \u25be", "en": "View \u25be"},
    "cat_mode": {"uk": "\u0420\u0435\u0436\u0438\u043c \u25be", "en": "Mode \u25be"},
    "agent": {"uk": "\u25c8 \u0410\u0433\u0435\u043d\u0442 \u25be", "en": "\u25c8 Agent \u25be"},
    "model": {"uk": "\u229f \u043c\u043e\u0434\u0435\u043b\u044c \u25be", "en": "\u229f Model \u25be"},
    "copy": {"uk": "\u2398 \u041a\u043e\u043f\u0456\u044e\u0432\u0430\u0442\u0438", "en": "\u2398 Copy"},
    "retry": {"uk": "\u21bb \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0438", "en": "\u21bb Retry"},
    "edit": {"uk": "\u270e \u0420\u0435\u0434\u0430\u0433\u0443\u0432\u0430\u0442\u0438", "en": "\u270e Edit"},
    "continue": {"uk": "\u25b6 \u041f\u0440\u043e\u0434\u043e\u0432\u0436\u0438\u0442\u0438", "en": "\u25b6 Continue"},
}


def tr(key: str) -> str:
    lang = get_lang()
    entry = _STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("uk") or key
