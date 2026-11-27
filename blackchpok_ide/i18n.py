"""Global bilingual localization engine (Ukrainian <-> English) for BlackChpok IDE."""
from __future__ import annotations

from pathlib import Path
import tkinter as tk

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

_UK_TO_EN: dict[str, str] = {
    "\u0424\u0430\u0439\u043b": "File", "\u0424\u0430\u0439\u043b \u25be": "File \u25be",
    "\u041f\u0440\u0430\u0432\u043a\u0430": "Edit", "\u041f\u0440\u0430\u0432\u043a\u0430 \u25be": "Edit \u25be",
    "\u0412\u0438\u0433\u043b\u044f\u0434": "View", "\u0412\u0438\u0433\u043b\u044f\u0434 \u25be": "View \u25be",
    "\u0420\u0435\u0436\u0438\u043c": "Mode", "\u0420\u0435\u0436\u0438\u043c \u25be": "Mode \u25be",
    "\u0410\u0433\u0435\u043d\u0442": "Agent", "\u25c8 \u0410\u0433\u0435\u043d\u0442 \u25be": "\u25c8 Agent \u25be",
    "\u041c\u043e\u0434\u0435\u043b\u044c": "Model", "\u229f \u043c\u043e\u0434\u0435\u043b\u044c \u25be": "\u229f Model \u25be",
    "\u041d\u043e\u0432\u0438\u0439 \u0447\u0430\u0442": "New chat", "+ \u041d\u043e\u0432\u0438\u0439 \u0447\u0430\u0442": "+ New chat",
    "\u041d\u043e\u0432\u0438\u0439 \u0430\u0433\u0435\u043d\u0442": "New agent",
    "\u0427\u0430\u0442\u0438": "Chats", "\u0410\u0440\u0445\u0456\u0432\u043d\u0456": "Archived", "\u0410\u043a\u0442\u0438\u0432\u043d\u0456": "Active",
    "\u041f\u043e\u0448\u0443\u043a\u2026": "Search\u2026", "\u041f\u043e\u0448\u0443\u043a": "Search",
    "\u0427\u0410\u0422\u0418 \u0419 \u0410\u0413\u0415\u041d\u0422\u0418": "CHATS & AGENTS",
    "\u041a\u041e\u041d\u0422\u0415\u041a\u0421\u0422": "CONTEXT",
    "\u0410\u0413\u0415\u041d\u0422 \u0406 \u041c\u041e\u0414\u0415\u041b\u042c": "AGENT & MODEL",
    "\u041f\u0420\u041e\u0404\u041a\u0422": "PROJECT",
    "\u0406\u041d\u0421\u0422\u0420\u0423\u041c\u0415\u041d\u0422\u0418": "TOOLS",
    "\u0412\u0406\u0414\u041a\u0420\u0418\u0422\u0406 \u0412\u041a\u041b\u0410\u0414\u041a\u0418": "OPEN TABS",
    "\u0424\u0410\u0419\u041b\u0418": "FILES",
    "\u0417\u041c\u0406\u041d\u0418": "CHANGES",
    "\u041d\u0435\u043c\u0430\u0454 \u0432\u0456\u0434\u043a\u0440\u0438\u0442\u0438\u0445 \u0444\u0430\u0439\u043b\u0456\u0432": "No open files",
    "\u041d\u0456\u0447\u043e\u0433\u043e \u043d\u0435 \u0437\u043d\u0430\u0439\u0434\u0435\u043d\u043e": "Nothing found",
    "\u041f\u043e\u0440\u043e\u0436\u043d\u044f \u0441\u0435\u0441\u0456\u044f": "Empty session",
    "\u0412\u0418": "YOU",
    "\u0410\u0413\u0415\u041d\u0422": "AGENT",
    "\u2398 \u041a\u043e\u043f\u0456\u044e\u0432\u0430\u0442\u0438": "\u2398 Copy",
    "\u21bb \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0438": "\u21bb Retry",
    "\u270e \u0420\u0435\u0434\u0430\u0433\u0443\u0432\u0430\u0442\u0438": "\u270e Edit",
    "\u25b6 \u041f\u0440\u043e\u0434\u043e\u0432\u0436\u0438\u0442\u0438": "\u25b6 Continue",
    "\u041d\u0430\u0434\u0456\u0441\u043b\u0430\u0442\u0438": "Send",
    "\u0417\u0443\u043f\u0438\u043d\u0438\u0442\u0438": "Stop",
    "\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u0438": "Clear",
    "\u0417\u0431\u0435\u0440\u0435\u0433\u0442\u0438": "Save",
    "\u0421\u043a\u0430\u0441\u0443\u0432\u0430\u0442\u0438": "Cancel",
    "\u0417\u0430\u043a\u0440\u0438\u0442\u0438": "Close",
    "\u041d\u0430\u043b\u0430\u0448\u0442\u0443\u0432\u0430\u043d\u043d\u044f": "Settings",
    "\u0422\u0435\u0440\u043c\u0456\u043d\u0430\u043b": "Terminal",
    "\u0411\u0440\u0430\u0443\u0437\u0435\u0440": "Browser",
    "\u0416\u0438\u0432\u0438\u0439 \u043f\u0435\u0440\u0435\u0433\u043b\u044f\u0434": "Live Preview",
    "\u0421\u043a\u0456\u043b\u0438": "Skills",
    "\u0427\u0435\u0440\u0433\u0430 \u0437\u0430\u0432\u0434\u0430\u043d\u044c": "Task queue",
    "\u041f\u0430\u043c'\u044f\u0442\u044c": "Memory",
    "\u0413\u043e\u0442\u043e\u0432\u043e": "Ready",
    "\u0412\u0438\u043a\u043e\u043d\u0430\u043d\u043e": "Completed",
    "\u041f\u0440\u0430\u0446\u044e\u0454\u2026": "Working\u2026",
    "\u0423 \u0447\u0435\u0440\u0437\u0456": "Queued",
}
_EN_TO_UK: dict[str, str] = {v: k for k, v in _UK_TO_EN.items()}


def translate_text(text: str, target_lang: str | None = None) -> str:
    if not text or not isinstance(text, str):
        return text
    lang = target_lang or get_lang()
    mapping = _UK_TO_EN if lang == "en" else _EN_TO_UK
    stripped = text.strip()
    if stripped in mapping:
        return text.replace(stripped, mapping[stripped], 1)
    out = text
    for src, dst in sorted(mapping.items(), key=lambda kv: -len(kv)):
        if len(src) >= 4 and src in out:
            out = out.replace(src, dst)
    return out


def tr(key: str) -> str:
    lang = get_lang()
    entry = _STRINGS.get(key)
    if entry:
        return entry.get(lang) or entry.get("uk") or key
    return translate_text(key, lang)


def apply_to_widget_tree(root: tk.Misc | None, target_lang: str | None = None) -> None:
    if root is None:
        return
    lang = target_lang or get_lang()

    def _walk(w: tk.Misc) -> None:
        try:
            if isinstance(w, tk.Menu):
                end_idx = w.index("end")
                if end_idx is not None:
                    for idx in range(end_idx + 1):
                        try:
                            lbl = w.entrycget(idx, "label")
                            if lbl:
                                nl = translate_text(lbl, lang)
                                if nl != lbl:
                                    w.entryconfigure(idx, label=nl)
                        except Exception:
                            pass
            else:
                try:
                    cur_txt = w.cget("text")
                    if isinstance(cur_txt, str) and cur_txt.strip():
                        new_txt = translate_text(cur_txt, lang)
                        if new_txt != cur_txt:
                            w.configure(text=new_txt)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            for ch in w.winfo_children():
                _walk(ch)
        except Exception:
            pass

    _walk(root)
