"""???????? ?????? ? ????? Lucide/Cursor ??? BlackChpok IDE."""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageTk

_CACHE: dict[tuple[str, str, int], ImageTk.PhotoImage] = {}

GLYPH_MAP: dict[str, str] = {
    "\uff0b": "plus", "+": "plus",
    "\u2398": "folder_open", "\U0001f4c2": "folder_open",
    "\u2913": "save", "\U0001f4be": "save",
    "\u25a4": "files", "\U0001f5c2": "files",
    "\u2315": "search", "\U0001f50d": "search",
    "\u00b1": "git", "\u2442": "git",
    "\u25eb": "database",
    "\u2726": "sparkles",
    "\u2692": "wrench",
    "\u2261": "list",
    "\u221e": "infinity",
    "\u2318": "command",
    "\u2699": "settings",
    "\u25b6": "play",
    "\u23f9": "stop", "\u25a0": "stop",
    "\u2328": "terminal",
    "\U0001f310": "globe",
    "\U0001f4f1": "phone",
    "\U0001f4df": "tablet",
    "\U0001f5a5": "desktop",
    "\u27f3": "refresh", "\u21bb": "refresh",
    "\u2197": "external",
    "\u25ce": "chat", "\u25c9": "inspect",
    "\u26a0": "alert",
    "\u22a0": "camera",
    "\u26f6": "maximize",
    "\u2715": "close", "\u00d7": "close",
    "\u25c8": "brand",
    "\u21b6": "undo",
    "\u21b7": "redo",
}

def resolve_glyph(text: str) -> tuple[str | None, str]:
    s = str(text or "").strip()
    if not s:
        return None, ""
    if s in GLYPH_MAP:
        return GLYPH_MAP[s], ""
    first = s[0]
    if first in GLYPH_MAP:
        rest = s[1:].strip()
        if len(rest) <= 10:
            return GLYPH_MAP[first], rest
    return None, s

def _rgba(hex_col: str) -> tuple[int, int, int, int]:
    c = str(hex_col or "#CBD5E1").strip().lstrip("#")
    if len(c) == 6:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255
    return 203, 213, 225, 255

COLOR_PALETTE: dict[str, str] = {
    "plus": "#22C55E",
    "folder_open": "#F59E0B",
    "save": "#3B82F6",
    "files": "#38BDF8",
    "search": "#06B6D4",
    "git": "#A855F7",
    "database": "#FB923C",
    "sparkles": "#FACC15",
    "wrench": "#94A3B8",
    "list": "#818CF8",
    "infinity": "#2DD4BF",
    "command": "#E879F9",
    "settings": "#CBD5E1",
    "play": "#10B981",
    "stop": "#EF4444",
    "terminal": "#84CC16",
    "globe": "#0EA5E9",
    "phone": "#38BDF8",
    "tablet": "#A78BFA",
    "desktop": "#60A5FA",
    "refresh": "#38BDF8",
    "external": "#94A3B8",
    "inspect": "#F472B6",
    "alert": "#FBBF24",
    "camera": "#34D399",
    "maximize": "#CBD5E1",
    "close": "#F87171",
    "brand": "#38BDF8", "trash": "#F87171", "paperclip": "#38BDF8", "mic": "#A78BFA", "trash": "#F87171", "paperclip": "#38BDF8", "mic": "#A78BFA", "bug": "#EF4444", "send": "#38BDF8", "clear": "#F59E0B", "image": "#2DD4BF", "check": "#22C55E", "archive": "#F59E0B", "chat": "#38BDF8", "sidebar": "#94A3B8", "spinner": "#FACC15", "back": "#60A5FA", "forward": "#60A5FA",
}

COLOR_PALETTE: dict[str, str] = {
    "plus": "#22C55E", "folder_open": "#F59E0B", "save": "#3B82F6", "files": "#38BDF8",
    "search": "#06B6D4", "git": "#A855F7", "database": "#FB923C", "sparkles": "#FACC15",
    "wrench": "#94A3B8", "list": "#818CF8", "infinity": "#2DD4BF", "command": "#E879F9",
    "settings": "#CBD5E1", "play": "#10B981", "stop": "#EF4444", "terminal": "#84CC16",
    "globe": "#0EA5E9", "phone": "#38BDF8", "tablet": "#A78BFA", "desktop": "#60A5FA",
    "refresh": "#38BDF8", "external": "#94A3B8", "inspect": "#F472B6", "alert": "#FBBF24",
    "camera": "#34D399", "maximize": "#CBD5E1", "close": "#F87171", "brand": "#38BDF8",
}

def get_icon(name: str, color: str = "#CBD5E1", size: int = 16) -> ImageTk.PhotoImage:
    base_hex = COLOR_PALETTE.get(name, color)
    key = (name, base_hex, size)
    if key in _CACHE:
        return _CACHE[key]
    scale = 4
    S = size * scale
    w = max(8, int(round(2.3 * scale)))
    col = _rgba(base_hex)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    p, q, mid = int(S * 0.16), S - int(S * 0.16), S // 2
    bg = (18, 22, 30, 255)

    if name == "plus":
        d.rounded_rectangle([p + 6, p, q - 6, q], radius=10, outline=col, width=w)
        d.line([(mid, p + 18), (mid, q - 18)], fill=col, width=w)
        d.line([(p + 20, mid), (q - 20, mid)], fill=col, width=w)
    elif name == "folder_open":
        d.polygon([(p, p + 12), (p + 24, p + 12), (p + 34, p + 22), (q, p + 22), (q, q - 6), (p, q - 6)], fill=col)
    elif name == "save":
        d.rounded_rectangle([p + 4, p + 4, q - 4, q - 4], radius=12, fill=col)
        d.rectangle([p + 20, p + 4, q - 20, mid - 4], fill=bg)
        d.rounded_rectangle([p + 18, mid + 8, q - 18, q - 10], radius=6, fill=(240, 248, 255, 255))
    elif name == "files":
        d.rounded_rectangle([p + 4, p + 4, q - 16, q - 14], radius=10, outline=col, width=w)
        d.rounded_rectangle([p + 18, p + 18, q - 4, q - 4], radius=10, fill=col)
    elif name == "search":
        r = int(S * 0.25)
        cx, cy = int(S * 0.43), int(S * 0.43)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=w + 2)
        d.line([(cx + int(r * 0.72), cy + int(r * 0.72)), (q - 2, q - 2)], fill=col, width=w + 3)
    elif name == "git":
        d.ellipse([p, p, q, q], fill=col)
        d.ellipse([mid - 26, mid - 16, mid + 26, mid + 24], fill=bg)
        d.polygon([(mid - 24, mid - 10), (mid - 20, mid - 30), (mid - 8, mid - 16)], fill=bg)
        d.polygon([(mid + 24, mid - 10), (mid + 20, mid - 30), (mid + 8, mid - 16)], fill=bg)
        d.rectangle([mid - 10, mid + 18, mid + 10, q], fill=bg)
    elif name == "database":
        d.ellipse([p + 6, p + 2, q - 6, p + 24], fill=col)
        d.rounded_rectangle([p + 6, mid - 10, q - 6, mid + 12], radius=8, fill=col)
        d.rounded_rectangle([p + 6, q - 24, q - 6, q - 2], radius=8, fill=col)
    elif name == "sparkles":
        d.polygon([(mid, p), (mid + 12, mid - 12), (q, mid), (mid + 12, mid + 12), (mid, q), (mid - 12, mid + 12), (p, mid), (mid - 12, mid - 12)], fill=col)
    elif name == "wrench":
        d.line([(p + 10, q - 10), (q - 18, p + 18)], fill=col, width=w + 4)
        d.arc([q - 44, p, q, p + 44], 40, 310, fill=col, width=w + 2)
    elif name == "list":
        for yy in (p + 12, mid, q - 12):
            d.ellipse([p + 2, yy - 6, p + 14, yy + 6], fill=col)
            d.rounded_rectangle([p + 24, yy - 5, q - 2, yy + 5], radius=4, fill=col)
    elif name == "infinity":
        d.ellipse([p, mid - 18, mid + 5, mid + 18], outline=col, width=w + 2)
        d.ellipse([mid - 5, mid - 18, q, mid + 18], outline=col, width=w + 2)
    elif name == "command":
        b = 18
        d.rounded_rectangle([p + b, p + b, q - b, q - b], radius=4, outline=col, width=w)
        for cx, cy in ((p, p), (q - b, p), (p, q - b), (q - b, q - b)):
            d.ellipse([cx, cy, cx + b, cy + b], outline=col, width=w)
    elif name == "settings":
        import math
        for ang in range(0, 360, 45):
            rad = math.radians(ang)
            d.line([(mid + int(math.cos(rad) * 24), mid + int(math.sin(rad) * 24)), (mid + int(math.cos(rad) * 38), mid + int(math.sin(rad) * 38))], fill=col, width=w + 2)
        d.ellipse([mid - 26, mid - 26, mid + 26, mid + 26], fill=col)
        d.ellipse([mid - 11, mid - 11, mid + 11, mid + 11], fill=bg)
    elif name == "play":
        d.polygon([(p + 10, p + 4), (q - 4, mid), (p + 10, q - 4)], fill=col)
    elif name == "stop":
        d.rounded_rectangle([p + 8, p + 8, q - 8, q - 8], radius=10, fill=col)
    elif name == "terminal":
        d.rounded_rectangle([p + 2, p + 6, q - 2, q - 6], radius=12, fill=col)
        d.line([(p + 18, p + 26), (mid - 4, mid), (p + 18, q - 26)], fill=bg, width=w)
        d.line([(mid + 4, q - 26), (q - 18, q - 26)], fill=bg, width=w)
    elif name == "globe":
        d.ellipse([p + 2, p + 2, q - 2, q - 2], outline=col, width=w + 1)
        d.ellipse([mid - 18, p + 2, mid + 18, q - 2], outline=col, width=w)
        d.line([(p + 2, mid), (q - 2, mid)], fill=col, width=w)
    elif name == "phone":
        d.rounded_rectangle([p + 16, p, q - 16, q], radius=10, outline=col, width=w)
        d.line([(mid - 8, q - 10), (mid + 8, q - 10)], fill=col, width=w)
    elif name == "tablet":
        d.rounded_rectangle([p + 8, p, q - 8, q], radius=10, outline=col, width=w)
        d.ellipse([mid - 4, q - 12, mid + 4, q - 4], fill=col)
    elif name == "desktop":
        d.rounded_rectangle([p + 2, p + 2, q - 2, q - 16], radius=8, outline=col, width=w)
        d.line([(mid, q - 16), (mid, q - 2)], fill=col, width=w)
        d.line([(mid - 18, q - 2), (mid + 18, q - 2)], fill=col, width=w)
    elif name == "refresh":
        d.arc([p + 4, p + 4, q - 4, q - 4], 35, 325, fill=col, width=w + 1)
        d.polygon([(q - 6, p + 8), (q + 2, p + 28), (q - 22, p + 24)], fill=col)
    elif name == "external":
        d.line([(mid, p + 4), (q - 4, p + 4), (q - 4, mid)], fill=col, width=w)
        d.line([(mid - 4, mid + 4), (q - 4, p + 4)], fill=col, width=w)
        d.arc([p + 4, p + 10, q - 10, q - 4], 90, 270, fill=col, width=w)
    elif name == "inspect":
        d.ellipse([p + 6, p + 6, q - 6, q - 6], outline=col, width=w)
        d.ellipse([mid - 10, mid - 10, mid + 10, mid + 10], fill=col)
    elif name == "alert":
        d.polygon([(mid, p + 2), (q - 2, q - 2), (p + 2, q - 2)], fill=col)
        d.line([(mid, mid - 8), (mid, q - 18)], fill=bg, width=w)
    elif name == "camera":
        d.rounded_rectangle([p + 2, p + 12, q - 2, q - 4], radius=10, fill=col)
        d.ellipse([mid - 14, mid - 8, mid + 14, mid + 20], fill=bg)
    elif name == "maximize":
        for cx, cy, dx, dy in ((p + 4, p + 4, 1, 1), (q - 4, p + 4, -1, 1), (p + 4, q - 4, 1, -1), (q - 4, q - 4, -1, -1)):
            d.line([(cx, cy), (cx + dx * 18, cy)], fill=col, width=w)
            d.line([(cx, cy), (cx, cy + dy * 18)], fill=col, width=w)
    elif name == "close":
        d.line([(p + 8, p + 8), (q - 8, q - 8)], fill=col, width=w + 1)
        d.line([(q - 8, p + 8), (p + 8, q - 8)], fill=col, width=w + 1)
    elif name == "brand":
        d.rounded_rectangle([p, p, q, q], radius=16, fill=(30, 41, 59, 255), outline=(56, 189, 248, 255), width=max(5, w))
        d.polygon([(mid, p + 10), (q - 10, mid), (mid, q - 10), (p + 10, mid)], fill=(56, 189, 248, 255))
        d.polygon([(mid, p + 20), (q - 20, mid), (mid, q - 20), (p + 20, mid)], fill=(168, 85, 247, 255))
        d.ellipse([mid - 6, mid - 6, mid + 6, mid + 6], fill=(248, 250, 252, 255))
    elif name == "send":
        d.line([(mid, q - 8), (mid, p + 12)], fill=col, width=w + 2)
        d.line([(p + 14, mid - 4), (mid, p + 10), (q - 14, mid - 4)], fill=col, width=w + 2)
    elif name == "clear":
        d.polygon([(p + 18, p + 12), (q - 4, p + 12), (q - 4, q - 12), (p + 18, q - 12), (p + 2, mid)], outline=col, width=w)
        d.line([(mid - 2, mid - 8), (mid + 12, mid + 8)], fill=col, width=w)
        d.line([(mid + 12, mid - 8), (mid - 2, mid + 8)], fill=col, width=w)
    elif name == "bug":
        # ????? (3 ?????, 3 ??????)
        for dy, dx in ((-6, 26), (8, 30), (22, 25)):
            d.line([(mid - dx, mid + dy - 4), (mid - 14, mid + dy)], fill=col, width=max(5, w - 2))
            d.line([(mid + 14, mid + dy), (mid + dx, mid + dy - 4)], fill=col, width=max(5, w - 2))
        # ?????? ?? ??????
        d.ellipse([mid - 11, p + 4, mid + 11, p + 24], fill=(226, 232, 240, 255))
        d.line([(mid - 5, p + 6), (mid - 14, p - 4)], fill=(226, 232, 240, 255), width=max(4, w - 3))
        d.line([(mid + 5, p + 6), (mid + 14, p - 4)], fill=(226, 232, 240, 255), width=max(4, w - 3))
        # ???????? ?????? ????
        d.ellipse([mid - 20, p + 16, mid + 20, q - 2], fill=col)
        # ????? ???? ? ????? ?????
        d.line([(mid, p + 18), (mid, q - 3)], fill=bg, width=max(4, w - 3))
        for sx, sy in ((-9, 28), (9, 28), (-10, 44), (10, 44)):
            d.ellipse([mid + sx - 3, p + sy - 3, mid + sx + 3, p + sy + 3], fill=bg)
    elif name == "trash":
        d.line([(p + 10, p + 14), (q - 10, p + 14)], fill=col, width=w)
        d.rounded_rectangle([mid - 10, p + 4, mid + 10, p + 14], radius=3, outline=col, width=max(4, w - 2))
        d.rounded_rectangle([p + 14, p + 14, q - 14, q - 4], radius=6, outline=col, width=w)
        d.line([(mid - 6, p + 24), (mid - 6, q - 12)], fill=col, width=max(4, w - 3))
        d.line([(mid + 6, p + 24), (mid + 6, q - 12)], fill=col, width=max(4, w - 3))
    elif name == "paperclip":
        d.rounded_rectangle([p + 16, p + 6, q - 16, q - 6], radius=14, outline=col, width=w)
        d.line([(mid, p + 20), (mid, q - 16)], fill=col, width=max(4, w - 2))
    elif name == "mic":
        d.rounded_rectangle([mid - 10, p + 4, mid + 10, mid + 10], radius=10, fill=col)
        d.arc([mid - 18, p + 8, mid + 18, mid + 20], 0, 180, fill=col, width=w)
        d.line([(mid, mid + 20), (mid, q - 4)], fill=col, width=w)
    elif name == "image":
        d.rounded_rectangle([p + 2, p + 6, q - 2, q - 6], radius=10, outline=col, width=w)
        d.ellipse([p + 14, p + 16, p + 28, p + 30], fill=(250, 204, 21, 255))
        d.polygon([(p + 8, q - 10), (mid - 4, mid + 2), (mid + 10, q - 10)], fill=col)
        d.polygon([(mid - 2, q - 10), (q - 18, mid - 6), (q - 8, q - 10)], fill=col)
    elif name == "check":
        d.line([(p + 6, mid + 2), (mid - 4, q - 10), (q - 6, p + 10)], fill=col, width=w + 2)
    elif name == "archive":
        d.rounded_rectangle([p + 2, p + 6, q - 2, p + 22], radius=6, fill=col)
        d.rounded_rectangle([p + 6, p + 24, q - 6, q - 6], radius=8, outline=col, width=w)
        d.line([(mid - 12, mid + 4), (mid + 12, mid + 4)], fill=col, width=w)
    elif name == "chat":
        d.rounded_rectangle([p + 2, p + 6, q - 2, q - 14], radius=12, fill=col)
        d.polygon([(p + 16, q - 14), (p + 10, q - 2), (p + 30, q - 14)], fill=col)
        for dx in (-14, 0, 14):
            d.ellipse([mid + dx - 3, mid - 7, mid + dx + 3, mid - 1], fill=bg)
    elif name == "sidebar":
        d.rounded_rectangle([p + 2, p + 4, q - 2, q - 4], radius=8, outline=col, width=w)
        d.line([(p + 24, p + 6), (p + 24, q - 6)], fill=col, width=w)
    elif name == "spinner":
        d.arc([p + 4, p + 4, q - 4, q - 4], 30, 290, fill=col, width=w + 2)
        d.ellipse([mid - 6, mid - 6, mid + 6, mid + 6], fill=col)
    elif name == "back":
        d.line([(q - 14, p + 10), (p + 12, mid), (q - 14, q - 10)], fill=col, width=w + 2)
    elif name == "forward":
        d.line([(p + 14, p + 10), (q - 12, mid), (p + 14, q - 10)], fill=col, width=w + 2)
    elif name == "undo":
        d.arc([p + 8, mid - 12, q - 4, q - 2], 180, 360, fill=col, width=w + 1)
        d.polygon([(p + 4, mid), (p + 24, mid - 14), (p + 24, mid + 14)], fill=col)
    elif name == "redo":
        d.arc([p + 4, mid - 12, q - 8, q - 2], 180, 360, fill=col, width=w + 1)
        d.polygon([(q - 4, mid), (q - 24, mid - 14), (q - 24, mid + 14)], fill=col)

    if img.getbbox() is None:
        d.polygon([(mid, p + 8), (q - 8, mid), (mid, q - 8), (p + 8, mid)], outline=col, width=w)
    if img.getbbox() is None:
        d.polygon([(mid, p + 8), (q - 8, mid), (mid, q - 8), (p + 8, mid)], outline=col, width=w)
    out = img.resize((size, size), Image.Resampling.LANCZOS)
    tk_img = ImageTk.PhotoImage(out)
    _CACHE[key] = tk_img
    return tk_img

GLYPH_MAP.update({
    "\U0001f41e": "bug",
    "\u229f": "archive", "\u2442": "git", "\u21bb": "refresh", "\u21ba": "undo",
    "\u270e": "wrench", "\u2605": "sparkles", "\u2606": "sparkles",
    "\u25cd": "inspect", "\U0001f5d1": "trash", "\U0001f4ce": "paperclip", "\U0001f3a4": "mic", "\U0001f399": "mic", "\U0001f5bc": "image", "\u2713": "check", "\u2717": "close", "\u2630": "sidebar", "\u25d0": "spinner", "\u2039": "back", "\u203a": "forward", "\u25d4": "settings", "\u2191": "send", "\u232b": "clear", "\U0001f5c0": "folder_open", "\u25c9": "inspect", "\u2197": "external", "\u2b07": "save", "\u2192": "forward", "\u22ef": "list", "\U0001f5c2": "files",
    "\u25c6": "brand", "\u25c7": "brand", "\u25cb": "inspect",
})

def apply_to_tree(root, size: int = 18) -> None:
    """?????????? ???????? ???????? ?????? ?? ????????? ???????? ? ???? Label/Button ????????."""
    try:
        stack = [root]
        while stack:
            w = stack.pop()
            try:
                stack.extend(w.winfo_children())
            except Exception:
                pass
            if w.winfo_class() == "Toplevel":
                continue
            cls = w.winfo_class()
            if cls in ("Label", "Button") and not getattr(w, "_vec_locked", False):
                try:
                    txt = str(w.cget("text") or "")
                    if not txt or w.cget("image"):
                        continue
                    gname, rest = resolve_glyph(txt.lstrip())
                    if not gname and len(txt.strip()) > 1:
                        ch = txt.strip()[0]
                        if ch in GLYPH_MAP:
                            gname, rest = GLYPH_MAP[ch], txt.strip()[1:].strip()
                    if gname:
                        is_hdr = "HeaderBar" in str(w)
                        sz = (20 if rest else 42) if is_hdr else (16 if rest else size)
                        img = get_icon(gname, color="#CBD5E1", size=sz)
                        w._vec_img_ref = img
                        w._vec_locked = True
                        if rest:
                            w.configure(image=img, text=" " + rest, compound="left", width=0, height=0)
                        else:
                            w.configure(image=img, text="", compound="center", width=0, height=0)
                except Exception:
                    pass
    except Exception:
        pass

_TK_HOOKED = False

def install_global_tk_hook() -> None:
    """??????? (0 ??) ??????? ???????? ??????? ?? ????????? ???????? ?????? ? __init__ ?? .configure()."""
    global _TK_HOOKED
    if _TK_HOOKED:
        return
    _TK_HOOKED = True
    import tkinter as _tk
    _orig_label_init = _tk.Label.__init__
    _orig_btn_init = _tk.Button.__init__
    _orig_label_cfg = _tk.Label.configure
    _orig_btn_cfg = _tk.Button.configure

    def _patch_widget(self, kw):
        if "text" not in kw or kw.get("image"):
            return
        txt = str(kw.get("text") or "")
        if not txt:
            return
        gname, rest = resolve_glyph(txt.lstrip())
        if not gname and len(txt.strip()) >= 1:
            ch = txt.strip()
            if ch in GLYPH_MAP:
                gname, rest = GLYPH_MAP[ch], txt.strip()[1:].strip()
        if gname:
            in_hdr = "headerbar" in str(self).lower()
            sz = (20 if rest else 34) if in_hdr else (15 if rest else 18)
            img = get_icon(gname, color="#CBD5E1", size=sz)
            self._vec_img_ref = img
            self._vec_locked = True
            kw["image"] = img
            kw["width"] = 0
            kw["height"] = 0
            if rest:
                kw["text"] = " " + rest
                kw["compound"] = "left"
            else:
                kw["text"] = ""
                kw["compound"] = "center"

    def _new_label_init(self, master=None, cnf={}, **kw):
        _patch_widget(self, kw)
        _orig_label_init(self, master, cnf, **kw)

    def _new_btn_init(self, master=None, cnf={}, **kw):
        _patch_widget(self, kw)
        _orig_btn_init(self, master, cnf, **kw)

    def _new_label_cfg(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw.update(cnf)
            cnf = None
        _patch_widget(self, kw)
        return _orig_label_cfg(self, **kw) if cnf is None else _orig_label_cfg(self, cnf, **kw)

    def _new_btn_cfg(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw.update(cnf)
            cnf = None
        _patch_widget(self, kw)
        return _orig_btn_cfg(self, **kw) if cnf is None else _orig_btn_cfg(self, cnf, **kw)

    _tk.Label.__init__ = _new_label_init
    _tk.Button.__init__ = _new_btn_init
    _tk.Label.configure = _tk.Label.config = _new_label_cfg
    _tk.Button.configure = _tk.Button.config = _new_btn_cfg
    try:
        from tkinter import ttk as _ttk
        _orig_ttk_btn_init = _ttk.Button.__init__
        def _new_ttk_btn_init(self, master=None, **kw):
            txt = str(kw.get("text") or "")
            if txt and not kw.get("image"):
                gname, rest = resolve_glyph(txt.lstrip())
                if not gname and txt.strip() and txt.strip() in GLYPH_MAP:
                    gname, rest = GLYPH_MAP[txt.strip()], txt.strip()[1:].strip()
                if gname:
                    img = get_icon(gname, color="#CBD5E1", size=16)
                    self._vec_img_ref = img
                    kw["image"] = img
                    kw.pop("width", None)
                    kw["text"] = (" " + rest) if rest else ""
                    kw["compound"] = "left" if rest else "image"
            _orig_ttk_btn_init(self, master, **kw)
        _ttk.Button.__init__ = _new_ttk_btn_init
    except Exception:
        pass

def clear_cache() -> None:
    """???????? ??? ??????? ?????? ??? ????? ?????????? ????."""
    _CACHE.clear()
