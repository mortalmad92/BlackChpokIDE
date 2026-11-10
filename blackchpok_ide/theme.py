"""Тема BlackChpok IDE у стилі Cursor Agents Window.

Дві повноцінні палітри:

* **light** (типова) — теплий off-white/cream фон, темний текст, терракотовий
  акцент і білі картки з тонкими рамками: чисте «преміум»-відчуття.
* **dark** — глибокий графіт (колишня тема проєкту).

Кольори живуть у словнику :data:`PALETTES`, а *змінні модуля* перепризначаються
функцією :func:`set_mode`. Панелі читають ``theme.FG`` під час виконання, тому
нові віджети одразу отримують активну палітру. Для вже намальованих є
:func:`retheme` — обхід усього дерева віджетів із картою «старий колір →
новий». Модуль не тягне логіки застосунку.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ── Палітри ────────────────────────────────────────────────────────────────
# Кожен ключ — роль у інтерфейсі. Додавати новий колір можна лише тут.

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        # тло
        "BG": "#f7f6f2",            # головне тло робочої області (cream)
        "BG_ALT": "#f0efe9",        # навігаційна колонка
        "BG_EDITOR": "#fbfaf7",     # полотно редактора
        "BG_INPUT": "#ffffff",      # поля вводу й композер
        "BG_HOVER": "#eceade",      # наведення
        "BG_ACTIVE": "#e3e1d5",     # активний елемент
        "BG_CARD": "#ffffff",       # картка повідомлення / блока
        "BG_ELEVATED": "#ffffff",   # спливні картки, меню
        # текст
        "FG": "#26251e",
        "FG_DIM": "#6f6d5e",
        "FG_FAINT": "#9d9a89",
        "FG_BRIGHT": "#14130e",
        # акцент: тепла терракота + темна primary-кнопка
        "ACCENT": "#b4532b",
        "ACCENT_HOVER": "#9a4623",
        "ACCENT_SOFT": "#f4e4da",
        "BTN_BG": "#26251e",
        "BTN_FG": "#f7f6f2",
        "BTN_HOVER": "#3c3a2f",
        # стани
        "SUCCESS": "#1e7f45",
        "WARN": "#b7791f",
        "ERROR": "#c0392b",
        "PURPLE": "#7c5cbf",
        # статуси сесій агентів
        "STATUS_WORKING": "#1e7f45",
        "STATUS_DONE": "#9d9a89",
        "STATUS_QUEUED": "#b7791f",
        # деталі
        "LINE_HL": "#f3f1e8",       # підсвітка поточного рядка
        "SELECTION": "#f0e2cf",
        "GUTTER_FG": "#b8b5a4",
        "RAIL_BG": "#f0efe9",
        "SCROLL": "#cfccbe",
        "BORDER": "#e5e3d8",
        "BORDER_SOFT": "#d7d4c6",
        # diff
        "DIFF_ADD_BG": "#e9f6ec",
        "DIFF_ADD_FG": "#1a7f37",
        "DIFF_DEL_BG": "#fdeeee",
        "DIFF_DEL_FG": "#c23a31",
        # рольові кольори чату
        "CHAT_USER": "#a4571f",
        "CHAT_TOOL": "#8a6d1f",
        "CHAT_ERR": "#c0392b",
        "CHAT_OK": "#1e7f45",
        # хардкод-«якір» старого тексту на акцентних кнопках
        "ON_ACCENT": "#f7f6f2",
    },
    "dark": {
        "BG": "#17171a",
        "BG_ALT": "#141416",
        "BG_EDITOR": "#121214",
        "BG_INPUT": "#1e1e22",
        "BG_HOVER": "#232328",
        "BG_ACTIVE": "#2b2b31",
        "BG_CARD": "#1b1b1f",
        "BG_ELEVATED": "#222227",
        "FG": "#dcdce1",
        "FG_DIM": "#94949e",
        "FG_FAINT": "#68686f",
        "FG_BRIGHT": "#f5f5f7",
        "ACCENT": "#7c93f5",
        "ACCENT_HOVER": "#93a6ff",
        "ACCENT_SOFT": "#2a3352",
        "BTN_BG": "#e9e7de",
        "BTN_FG": "#17171a",
        "BTN_HOVER": "#ffffff",
        "SUCCESS": "#5ec98a",
        "WARN": "#e0b25a",
        "ERROR": "#e2706b",
        "PURPLE": "#b68ee0",
        "STATUS_WORKING": "#5ec98a",
        "STATUS_DONE": "#68686f",
        "STATUS_QUEUED": "#e0b25a",
        "LINE_HL": "#1c1c21",
        "SELECTION": "#2c3a63",
        "GUTTER_FG": "#4f4f57",
        "RAIL_BG": "#101012",
        "SCROLL": "#3a3a42",
        "BORDER": "#26262b",
        "BORDER_SOFT": "#34343b",
        "DIFF_ADD_BG": "#16321f",
        "DIFF_ADD_FG": "#5ec98a",
        "DIFF_DEL_BG": "#381a1a",
        "DIFF_DEL_FG": "#e2706b",
        "CHAT_USER": "#9db4f0",
        "CHAT_TOOL": "#e5c07b",
        "CHAT_ERR": "#e2706b",
        "CHAT_OK": "#5ec98a",
        "ON_ACCENT": "#0d1120",
    },
}

#: Тема, яку отримує новий користувач (без збереженого вибору).
DEFAULT_MODE = "dark"

#: Активний режим: "light" | "dark".
_MODE = DEFAULT_MODE

#: Карта «колір до перемальовки → колір після» для :func:`retheme`.
SWAP: dict[str, str] = {}

# ── Змінні модуля (перепризначаються set_mode) ─────────────────────────────
BG = BG_ALT = BG_EDITOR = BG_INPUT = BG_HOVER = BG_ACTIVE = ""
BG_CARD = BG_ELEVATED = ""
FG = FG_DIM = FG_FAINT = FG_BRIGHT = ""
ACCENT = ACCENT_HOVER = ACCENT_SOFT = ""
BTN_BG = BTN_FG = BTN_HOVER = ON_ACCENT = ""
SUCCESS = WARN = ERROR = PURPLE = ""
STATUS_WORKING = STATUS_DONE = STATUS_QUEUED = ""
LINE_HL = SELECTION = GUTTER_FG = RAIL_BG = SCROLL = ""
BORDER = BORDER_SOFT = ""
DIFF_ADD_BG = DIFF_ADD_FG = DIFF_DEL_BG = DIFF_DEL_FG = ""
CHAT_USER = CHAT_TOOL = CHAT_ERR = CHAT_OK = ""

#: Порядок застосування змінних (усі ключі палітри).
_COLOUR_KEYS: tuple[str, ...] = (
    "BG", "BG_ALT", "BG_EDITOR", "BG_INPUT", "BG_HOVER", "BG_ACTIVE",
    "BG_CARD", "BG_ELEVATED", "FG", "FG_DIM", "FG_FAINT", "FG_BRIGHT",
    "ACCENT", "ACCENT_HOVER", "ACCENT_SOFT", "BTN_BG", "BTN_FG", "BTN_HOVER",
    "ON_ACCENT", "SUCCESS", "WARN", "ERROR", "PURPLE",
    "STATUS_WORKING", "STATUS_DONE", "STATUS_QUEUED",
    "LINE_HL", "SELECTION", "GUTTER_FG", "RAIL_BG", "SCROLL",
    "BORDER", "BORDER_SOFT",
    "DIFF_ADD_BG", "DIFF_ADD_FG", "DIFF_DEL_BG", "DIFF_DEL_FG",
    "CHAT_USER", "CHAT_TOOL", "CHAT_ERR", "CHAT_OK",
)

#: Підписи кольорів у налаштуваннях (для діагностики й тестів).
MODES = ("light", "dark")


def current_mode() -> str:
    """Активна тема: ``light`` або ``dark``."""
    return _MODE


def role_of(colour: str) -> str:
    """Ключ палітри за кольором (напр. ``#f7f6f2`` → ``BG``).

    Віджети запам'ятовують кольори ролями, а не значеннями: тоді після
    перемикання теми наведення бере свіжий колір тієї ж ролі, і світлі
    плашки не спливають у темному режимі. Невідомий колір → ``""``.
    """
    clean = (colour or "").strip().lower()
    palette = PALETTES[_MODE]
    for key in _COLOUR_KEYS:
        if palette[key].lower() == clean:
            return key
    return ""


def value_of(role: str, fallback: str = "") -> str:
    """Актуальний колір ролі в поточній темі (або fallback)."""
    if not role:
        return fallback
    return PALETTES[_MODE].get(role, fallback)


def set_mode(mode: str) -> None:
    """Увімкнути палітру й перепризначити змінні модуля.

    Кольори підсвітки синтаксису оновлюються тут же: без цього редактор
    лишався з палітрою попередньої теми (у темному режимі — зі світлими
    кольорами, майже нечитабельними).
    """
    global _MODE
    _MODE = "dark" if str(mode or "").lower().startswith("dark") else "light"
    palette = PALETTES[_MODE]
    globals().update({key: palette[key] for key in _COLOUR_KEYS})
    # Під час імпорту модуля _refresh_syntax ще не визначена — тоді
    # кольори синтаксису виставляє виклик під визначенням.
    refresh = globals().get("_refresh_syntax")
    if callable(refresh):
        refresh()


def _rebuild_swap(old: dict[str, str]) -> None:
    """Побудувати карту перекладу кольорів для retheme()."""
    palette = PALETTES[_MODE]
    mapping: dict[str, str] = {}
    for key in _COLOUR_KEYS:
        before = old.get(key, "")
        after = palette[key]
        if before and before != after:
            mapping[before] = after
    # Хардкоди, які зустрічаються в панелях поверх тем.
    mapping.setdefault("#0d1120", palette["ON_ACCENT"])
    mapping.setdefault("#08101f", palette["ON_ACCENT"])
    mapping.setdefault("#c8b6ff", palette["ACCENT"])
    mapping.setdefault("#7c93f5", palette["ACCENT"])
    globals()["SWAP"] = mapping


set_mode(DEFAULT_MODE)


def retheme(root: tk.Misc) -> None:
    """Перефарбувати вже намальоване вікно під активну палітру.

    Обхід не ідеальний (деякі кастомні малюнки оновляться лише після
    перезапуску), але покриває практично весь інтерфейс без перебудови.
    """
    old = {key: PALETTES["dark" if _MODE == "light" else "light"][key]
           for key in _COLOUR_KEYS}
    mapping = SWAP or {}

    options = ("background", "foreground", "insertbackground",
               "highlightbackground", "highlightcolor",
               "activebackground", "activeforeground", "selectbackground",
               "selectforeground", "disabledforeground")
    stack = list(root.winfo_children())
    seen = 0
    while stack and seen < 20000:
        widget = stack.pop()
        seen += 1
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue
        for option in options:
            try:
                value = str(widget.cget(option))
            except (tk.TclError, AttributeError):
                continue
            target = mapping.get(value)
            if target:
                try:
                    widget.configure(**{option: target})
                except (tk.TclError, AttributeError):
                    continue
        # ── кешовані кольори в атрибутах віджетів ──────────────────────────
        # HoverLabel тримає ``_bg``/``_hover_bg``, NavButton — ``_bg``,
        # PulseDot — ``_colour``: саме з кешу вони фарбуються при наведенні,
        # тож без оновлення атрибутів у темній темі спливає світла плашка.
        changed_cache = False
        for attr, value in list(vars(widget).items()):
            if isinstance(value, str) and value.startswith("#") and len(value) == 7:
                target = mapping.get(value)
                if target:
                    try:
                        setattr(widget, attr, target)
                        changed_cache = True
                    except Exception:  # noqa: BLE001 - атрибут може бути read-only
                        continue
        # Кастомні малюнки (пульс-крапка) перемальовуємо одразу.
        if changed_cache:
            paint = getattr(widget, "_paint_", None)
            if callable(paint):
                try:
                    paint(0.0)
                except (tk.TclError, TypeError):
                    pass
        # ttk-віджети мають власні стилі — їх оновлює Theme.apply().
    # Пульс-крапки тримають кольори в класі — оновимо на місці.
    try:
        from . import pulse

        palette = PALETTES[_MODE]
        pulse.PulseDot._COLOURS.update({
            pulse.PulseDot.IDLE: palette["BORDER_SOFT"],
            pulse.PulseDot.RUNNING: palette["STATUS_WORKING"],
            pulse.PulseDot.DONE: palette["STATUS_WORKING"],
            pulse.PulseDot.FAILED: palette["ERROR"],
        })
    except Exception:  # noqa: BLE001 - дрібниця, не критично
        pass


# ── Система відступів (px) ─────────────────────────────────────────────────
SPACE_XS = 2
SPACE_SM = 4
SPACE_MD = 8
SPACE_LG = 12
SPACE_XL = 16
SPACE_2XL = 24
SPACE_3XL = 36

#: Комфортна ширина центральної колонки діалогу.
#:
#: 920 px було замало: на широкому моніторі розмова виглядала вузькою
#: смужкою посеред екрана, а половина місця просто пустувала. Тепер типово
#: 0 — «займати всю доступну ширину»; обмеження можна повернути в
#: налаштуваннях (``ui.chat_max_width``), якщо хочеться вузької колонки.
CHAT_MAX_WIDTH = 0
#: Максимальна ширина колонки композера (0 = як стрічка).
COMPOSER_MAX_WIDTH = 0
#: Мінімальна висота композера, яку НЕ можна зменшити.
#:
#: У композері пишуть завдання, тож він має бути на екрані завжди —
#: і під час роботи агента теж. Раніше довга відповідь або картка аналізу
#: розтягувала стрічку діалогу, і Tk стискав композер аж до нуля: користувач
#: бачив порожню смугу замість поля вводу. 210 px — це підказки, поле на
#: два-три рядки й рядок моделі/черги.
COMPOSER_HEIGHT = 268
#: Ширина рейки навігації та бічної панелі.
RAIL_WIDTH = 52
#: Панель сесій має вміщати назву чату, час і дві іконки дій (⊟ ×).
#: 264 px для цього замало — назва обрізалась до кількох символів.
SIDEBAR_WIDTH = 300
#: Вузька рейка, коли панель згорнута.
RAIL_COLLAPSED_WIDTH = 52
#: Типова ширина правої колонки живого прев'ю. У ній живе вбудований
#: браузер із рядком адреси, тому 460 px було замало: адреса й кнопки
#: наїжджали одне на одного. 540 лишає місце для поля вводу.
PREVIEW_WIDTH = 540
#: Вузька межа: вужче — ховаємо другорядні кнопки браузера.
PREVIEW_MIN_WIDTH = 380
#: Стеля: ширше — прев'ю з'їдає редактор.
PREVIEW_MAX_WIDTH = 720
#: Колонка контексту: межі, за якими вона вже не має сенсу / вже заважає.
CONTEXT_MIN_WIDTH = 170
CONTEXT_MAX_WIDTH = 360

# ── Підсвітка синтаксису ───────────────────────────────────────────────────
SYNTAX_LIGHT = {
    "keyword": "#a626a4",
    "control": "#a626a4",
    "type": "#b76b01",
    "function": "#3d74c9",
    "string": "#3f7f3f",
    "number": "#b76b01",
    "comment": "#9d9a89",
    "decorator": "#b76b01",
    "constant": "#0f7f8f",
    "operator": "#52514a",
    "builtin": "#0f7f8f",
    "self": "#c0392b",
    "tag": "#c0392b",
    "attribute": "#b76b01",
    "key": "#3d74c9",
    "error": "#c0392b",
}
SYNTAX_DARK = {
    "keyword": "#c678dd",
    "control": "#c678dd",
    "type": "#e5c07b",
    "function": "#61afef",
    "string": "#98c379",
    "number": "#d19a66",
    "comment": "#5c6370",
    "decorator": "#e5c07b",
    "constant": "#56b6c2",
    "operator": "#abb2bf",
    "builtin": "#56b6c2",
    "self": "#e06c75",
    "tag": "#e06c75",
    "attribute": "#d19a66",
    "key": "#61afef",
    "error": "#e2706b",
}

SYNTAX_COLORS = dict(SYNTAX_LIGHT)


def _refresh_syntax() -> None:
    SYNTAX_COLORS.clear()
    SYNTAX_COLORS.update(SYNTAX_DARK if _MODE == "dark" else SYNTAX_LIGHT)


_refresh_syntax()

FONT_CANDIDATES = ("Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New")
UI_FONT_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Tahoma", "DejaVu Sans")


def color_for(key: str, default: str = "") -> str:
    """Колір синтаксису за ключем (для позначок структури)."""
    return SYNTAX_COLORS.get(key or "", default or FG_DIM)


def pick_font(root: tk.Misc, candidates: tuple[str, ...], fallback: str = "Consolas") -> str:
    """Перший шрифт зі списку, який реально встановлений у системі."""
    try:
        installed = {name.lower() for name in tkfont.families(root)}
    except tk.TclError:
        return fallback
    for name in candidates:
        if name.lower() in installed:
            return name
    return fallback


class Theme:
    """Набір шрифтів + застосування ttk-стилів до застосунку."""

    def __init__(self, root: tk.Tk, family: str = "", size: int = 12) -> None:
        self.root = root
        self.mono_family = family or pick_font(root, FONT_CANDIDATES)
        self.ui_family = pick_font(root, UI_FONT_CANDIDATES, "TkDefaultFont")
        self.size = size
        self._build_fonts()

    # ── шрифти ─────────────────────────────────────────────────────────────
    def _build_fonts(self) -> None:
        s = max(9, min(28, int(self.size)))
        ui_base = max(9, s - 2)
        self.mono = tkfont.Font(family=self.mono_family, size=s)
        self.mono_small = tkfont.Font(family=self.mono_family, size=max(8, s - 1))
        self.mono_bold = tkfont.Font(family=self.mono_family, size=s, weight="bold")
        self.ui = tkfont.Font(family=self.ui_family, size=ui_base)
        self.ui_small = tkfont.Font(family=self.ui_family, size=max(8, ui_base - 1))
        self.ui_tiny = tkfont.Font(family=self.ui_family, size=max(7, ui_base - 2))
        self.ui_bold = tkfont.Font(family=self.ui_family, size=ui_base, weight="bold")
        self.ui_title = tkfont.Font(family=self.ui_family, size=ui_base + 4, weight="bold")
        self.ui_h1 = tkfont.Font(family=self.ui_family, size=ui_base + 3, weight="bold")
        self.ui_h2 = tkfont.Font(family=self.ui_family, size=ui_base + 1, weight="bold")
        self.ui_hero = tkfont.Font(family=self.ui_family, size=ui_base + 9, weight="bold")
        self.chat = tkfont.Font(family=self.ui_family, size=ui_base)
        self.chat_body = tkfont.Font(family=self.ui_family, size=ui_base + 1)
        self.chat_code = tkfont.Font(family=self.mono_family, size=max(8, s - 1))

    def set_family(self, family: str, size: int) -> None:
        if family:
            self.mono_family = family
        self.size = size
        self._build_fonts()
        self.apply()

    # ── застосування ───────────────────────────────────────────────────────
    def apply(self) -> None:
        root = self.root
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        _refresh_syntax()
        root.configure(bg=BG)
        self.root.option_add("*Font", self.ui)
        self.root.option_add("*TCombobox*Listbox.background", BG_ELEVATED)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", FG_BRIGHT)
        self.root.option_add("*Menu.background", BG_ELEVATED)
        self.root.option_add("*Menu.foreground", FG)
        self.root.option_add("*Menu.activeBackground", BG_ACTIVE)
        self.root.option_add("*Menu.activeForeground", FG_BRIGHT)
        self.root.option_add("*Menu.borderWidth", 1)
        self.root.option_add("*Menu.relief", "flat")
        self.root.option_add("*selectBackground", SELECTION)
        self.root.option_add("*selectForeground", FG_BRIGHT)

        style.configure(".", background=BG, foreground=FG, fieldbackground=BG_INPUT, borderwidth=0)
        for name, colour in (
            ("TFrame", BG),
            ("Bg.TFrame", BG),
            ("Panel.TFrame", BG_ALT),
            ("Card.TFrame", BG_CARD),
            ("Rail.TFrame", RAIL_BG),
            ("Editor.TFrame", BG_EDITOR),
            ("Border.TFrame", BORDER),
            ("Elevated.TFrame", BG_ELEVATED),
        ):
            style.configure(name, background=colour)

        style.configure("TLabel", background=BG, foreground=FG, font=self.ui)
        style.configure("Panel.TLabel", background=BG_ALT, foreground=FG_DIM, font=self.ui_small)
        style.configure("Card.TLabel", background=BG_CARD, foreground=FG, font=self.ui)
        style.configure("Header.TLabel", background=BG_ALT, foreground=FG_FAINT, font=self.ui_tiny)
        style.configure("Title.TLabel", background=BG, foreground=FG_BRIGHT, font=self.ui_h2)
        style.configure("H1.TLabel", background=BG, foreground=FG_BRIGHT, font=self.ui_h1)
        style.configure("Dim.TLabel", background=BG, foreground=FG_DIM, font=self.ui_small)
        style.configure("Faint.TLabel", background=BG, foreground=FG_FAINT, font=self.ui_small)
        style.configure("Accent.TLabel", background=BG, foreground=ACCENT, font=self.ui_bold)

        # Кнопки: пласкі, з наведенням; окремі «пігулки» й іконки.
        style.configure(
            "TButton",
            background=BG_INPUT,
            foreground=FG,
            borderwidth=0,
            focusthickness=0,
            padding=(SPACE_LG, 6),
            font=self.ui,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("pressed", BG_ACTIVE), ("active", BG_HOVER), ("disabled", BG_INPUT)],
            foreground=[("disabled", FG_FAINT)],
        )
        # Primary-кнопка: темна пігулка на світлій темі (і навпаки).
        style.configure("Accent.TButton", background=BTN_BG, foreground=BTN_FG,
                        font=self.ui_bold, padding=(14, 6))
        style.map("Accent.TButton",
                  background=[("pressed", ACCENT_SOFT), ("active", BTN_HOVER), ("disabled", BG_ACTIVE)],
                  foreground=[("disabled", FG_FAINT)])
        style.configure("Ghost.TButton", background=BG, foreground=FG_DIM, padding=(8, 4),
                        font=self.ui_small)
        style.map("Ghost.TButton", background=[("active", BG_HOVER)], foreground=[("active", FG_BRIGHT)])
        style.configure("Flat.TButton", background=BG_ALT, foreground=FG, padding=(8, 4),
                        font=self.ui_small)
        style.map("Flat.TButton", background=[("active", BG_HOVER)], foreground=[("active", FG_BRIGHT)])
        style.configure("Icon.TButton", background=BG_ALT, foreground=FG_DIM, padding=(7, 4), font=self.ui)
        style.map("Icon.TButton", background=[("active", BG_HOVER)], foreground=[("active", FG_BRIGHT)])
        style.configure("Rail.TButton", background=RAIL_BG, foreground=FG_DIM, padding=(8, 7), font=self.ui)
        style.map("Rail.TButton", background=[("active", BG_HOVER)], foreground=[("active", FG_BRIGHT)])
        style.configure("RailActive.TButton", background=BG_ACTIVE, foreground=FG_BRIGHT,
                        padding=(8, 7), font=self.ui)
        style.map("RailActive.TButton", background=[("active", BG_ACTIVE)])
        style.configure("Pill.TButton", background=BG_INPUT, foreground=FG, padding=(SPACE_LG, 5),
                        font=self.ui_small, borderwidth=1, relief="flat")
        style.map("Pill.TButton", background=[("active", BG_HOVER)], foreground=[("active", FG_BRIGHT)])
        style.configure("Send.TButton", background=BTN_BG, foreground=BTN_FG, padding=(10, 7),
                        font=self.ui_bold)
        style.map("Send.TButton", background=[("active", BTN_HOVER), ("disabled", BG_ACTIVE)],
                  foreground=[("disabled", FG_FAINT)])

        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG, insertcolor=FG_BRIGHT,
                        borderwidth=0, padding=6, relief="flat")
        style.map("TEntry", fieldbackground=[("focus", BG_INPUT)], bordercolor=[("focus", ACCENT_SOFT)],
                  lightcolor=[("focus", ACCENT_SOFT)], darkcolor=[("focus", ACCENT_SOFT)])
        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_INPUT, foreground=FG,
                        arrowcolor=FG_DIM, bordercolor=BORDER, padding=4, relief="flat")
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG_INPUT)],
                  foreground=[("disabled", FG_FAINT)],
                  background=[("active", BG_HOVER)])

        style.configure("TCheckbutton", background=BG, foreground=FG, font=self.ui, focuscolor=BG)
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", FG_BRIGHT)])
        style.configure("Panel.TCheckbutton", background=BG_ALT, foreground=FG, font=self.ui, focuscolor=BG_ALT)
        style.map("Panel.TCheckbutton", background=[("active", BG_ALT)])
        style.configure("Card.TCheckbutton", background=BG_CARD, foreground=FG, font=self.ui, focuscolor=BG_CARD)
        style.map("Card.TCheckbutton", background=[("active", BG_CARD)])

        style.configure("TSeparator", background=BORDER)
        style.configure("TPanedwindow", background=BG, sashthickness=1)
        style.configure("Sash", sashthickness=1, gripcount=0, background=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)

        style.configure(
            "Treeview",
            background=BG_ALT,
            fieldbackground=BG_ALT,
            foreground=FG,
            borderwidth=0,
            rowheight=max(22, self.size + 12),
            font=self.ui_small,
        )
        style.map(
            "Treeview",
            background=[("selected", BG_ACTIVE)],
            foreground=[("selected", FG_BRIGHT)],
        )
        style.configure("Treeview.Heading", background=BG_ALT, foreground=FG_FAINT, relief="flat",
                        font=self.ui_tiny)
        style.map("Treeview.Heading", background=[("active", BG_HOVER)])

        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=BG_ALT, foreground=FG_DIM, padding=(14, 6),
                        font=self.ui_small, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", BG), ("active", BG_HOVER)],
                  foreground=[("selected", FG_BRIGHT)])

        style.configure("Vertical.TScrollbar", background=SCROLL, troughcolor=BG, bordercolor=BG,
                        arrowcolor=FG_FAINT, gripcount=0, width=8, relief="flat", arrowsize=10)
        style.map("Vertical.TScrollbar", background=[("active", FG_FAINT)])
        style.configure("Horizontal.TScrollbar", background=SCROLL, troughcolor=BG, bordercolor=BG,
                        arrowcolor=FG_FAINT, gripcount=0, relief="flat", arrowsize=10)
        style.map("Horizontal.TScrollbar", background=[("active", FG_FAINT)])
        style.configure("TProgressbar", background=ACCENT, troughcolor=BG_INPUT, borderwidth=0,
                        thickness=4)
        style.configure("TSpinbox", fieldbackground=BG_INPUT, foreground=FG, background=BG_INPUT,
                        arrowcolor=FG_DIM, borderwidth=0)
        style.configure("TScale", background=BG, troughcolor=BG_INPUT, borderwidth=0)
        style.configure("TLabelframe", background=BG, foreground=FG_DIM, borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=BG, foreground=FG_DIM, font=self.ui_small)


def switch_mode(mode: str, root: tk.Misc | None = None, theme_obj: "Theme | None" = None) -> None:
    """Перемкнути тему: перепризначити кольори й (за бажанням) перемалювати.

    ``theme_obj`` потрібен, щоб оновити ttk-стилі; ``root`` — щоб обійти
    вже намальовані віджети.
    """
    global SWAP
    old = {key: globals()[key] for key in _COLOUR_KEYS}
    set_mode(mode)
    _rebuild_swap(old)
    if theme_obj is not None:
        theme_obj.apply()
    if root is not None:
        retheme(root)


__all__ = [
    "ACCENT", "ACCENT_HOVER", "ACCENT_SOFT", "BG", "BG_ACTIVE", "BG_ALT", "BG_CARD",
    "BG_EDITOR", "BG_ELEVATED", "BG_HOVER", "BG_INPUT", "BORDER", "BORDER_SOFT",
    "BTN_BG", "BTN_FG", "BTN_HOVER", "CHAT_MAX_WIDTH", "COMPOSER_HEIGHT", "CHAT_ERR", "CHAT_OK", "CHAT_TOOL",
    "CHAT_USER", "COMPOSER_MAX_WIDTH", "DIFF_ADD_BG", "DIFF_ADD_FG", "DIFF_DEL_BG",
    "DIFF_DEL_FG", "ERROR", "FG", "FG_BRIGHT", "FG_DIM", "FG_FAINT", "GUTTER_FG",
    "LINE_HL", "MODES", "ON_ACCENT", "PALETTES", "PREVIEW_MIN_WIDTH", "PREVIEW_WIDTH",
    "PREVIEW_MAX_WIDTH", "CONTEXT_MIN_WIDTH", "CONTEXT_MAX_WIDTH",
    "PURPLE", "RAIL_BG",
    "RAIL_COLLAPSED_WIDTH", "RAIL_WIDTH", "SCROLL", "SELECTION", "SIDEBAR_WIDTH",
    "SPACE_2XL", "SPACE_3XL", "SPACE_LG", "SPACE_MD", "SPACE_SM", "SPACE_XL", "SPACE_XS",
    "STATUS_DONE", "STATUS_QUEUED", "STATUS_WORKING", "SUCCESS", "SYNTAX_COLORS",
    "Theme", "WARN", "color_for", "current_mode", "pick_font", "retheme", "role_of",
    "set_mode", "switch_mode", "value_of",
]
