"""Вбудований браузер: показ сайту проєкту й перезавантаження при змінах.

Справжній браузер усередині вікна IDE. Використовує те, що є в системі:

1. **WebView2 / Chrome / Edge** — справжнє вікно браузера вбудовується через
   Windows API (``SetParent``); працює без сторонніх пакетів;
2. **запасний варіант** — показ сторінки через ``urllib`` у текстовому
   вигляді, якщо браузера немає.

Живе перезавантаження: після збереження файлу або зміни на диску сторінка
оновлюється сама.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import os
import shutil
import subprocess
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

from . import cdp, theme, web_server, widgets

LOG = logging.getLogger("blackchpok.browser")

IS_WINDOWS = os.name == "nt"

#: Висота «власної» смуги Chromium у режимі ``--app`` (px).
#: Вона малюється всередині клієнтської області, тому прибирається лише
#: зсувом вікна вгору на цю величину (див. ``BrowserView._fit_now``).
CUSTOM_FRAME_HEIGHT = 32

#: Можливі браузери (у порядку переваги).
#: Порядок переваги: Chrome вбудовується стабільно, Edge з WebView2 інколи
#: повертає заголовок вікна після ``SetParent`` і показує порожню сторінку.
BROWSER_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Chrome", (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )),
    ("Brave", (
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    )),
    ("Edge (WebView2)", (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )),
)


def find_browser() -> tuple[str, str]:
    """Знайти браузер: (назва, шлях). Порожні — якщо не знайдено."""
    for name, paths in BROWSER_CANDIDATES:
        for path in paths:
            if Path(path).exists():
                return name, path
    for name, exe in (("Edge", "msedge.exe"), ("Chrome", "chrome.exe")):
        found = shutil.which(exe)
        if found:
            return name, found
    return "", ""


def browsers() -> list[tuple[str, str]]:
    """Усі знайдені браузери."""
    found: list[tuple[str, str]] = []
    for name, paths in BROWSER_CANDIDATES:
        for path in paths:
            if Path(path).exists():
                found.append((name, path))
                break
    return found


# ── Адреси: нормалізація й «відкрити всередині IDE» ────────────────────────

#: Схеми, які справді можна показати у вбудованому вікні браузера.
WEB_SCHEMES = ("http://", "https://", "file://")

#: Будь-яка схема URL: «слово:» на початку (http:, mailto:, vscode:, C:\ — ні).
_SCHEME = __import__("re").compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


#: Пошукова система за замовчуванням.
#:
#: Користувач просив саме google.com.ua. Адреса будується окремою
#: функцією, щоб її можна було замінити в налаштуваннях і не шукати
#: рядок по всьому коду.
SEARCH_URL = "https://www.google.com.ua/search?q={query}"


def search_url(query: str) -> str:
    """Адреса пошуку для фрази (пробіли й кирилиця кодуються)."""
    import urllib.parse

    clean = " ".join((query or "").split())
    if not clean:
        return ""
    return SEARCH_URL.format(query=urllib.parse.quote_plus(clean))


#: Ознаки того, що введене — СЛОВА, а не адреса.
#:
#: «погода київ» чи «python як читати файл» мають пробіли й не мають
#: крапки зі схемою — це пошуковий запит. Інакше браузер намагався
#: відкрити ``https://погода київ`` і показував помилку.
def looks_like_query(text: str) -> bool:
    """Чи це пошуковий запит, а не адреса."""
    clean = (text or "").strip()
    if not clean:
        return False
    low = clean.lower()
    if low.startswith(WEB_SCHEMES) or _SCHEME.match(clean):
        return False
    if low.startswith(("localhost", "127.0.0.1", "[::1]")):
        return False
    # Пробіл майже завжди означає запит; адреси з пробілами трапляються
    # лише в екранованому вигляді (%20) і сюди не потрапляють.
    if " " in clean:
        return True
    # Без пробілу: адреса має крапку й доменну зону, запит — ні.
    return "." not in clean


def normalise_url(text: str) -> str:
    """Перетворити те, що ввів користувач, на повну адресу.

    Розуміє чотири типові випадки, з якими стикається людина:

    * повна адреса (``https://…``) — лишається як є;
    * адреса без схеми (``git-scm.com/download/win``) — додається ``https://``;
    * ``localhost:8080`` або ``127.0.0.1:8000/app`` — додається ``http://``,
      бо локальні сервери майже ніколи не мають TLS;
    * **звичайні слова** («погода київ», «fastapi tutorial») — це пошук,
      і вони йдуть у Google, а не перетворюються на безглузду адресу.

    Порожній рядок → ``""``.
    """
    clean = (text or "").strip()
    if not clean:
        return ""
    low = clean.lower()
    if low.startswith(WEB_SCHEMES):
        return clean
    if low.startswith("localhost") or low.startswith("127.0.0.1") or \
            low.startswith("[::1]"):
        return "http://" + clean
    # Будь-яка інша схема (mailto:, vscode:, ssh:) лишається як є: її
    # не можна відкрити у вбудованому вікні, але й переписувати на https
    # не можна — інакше «mailto:…» перетворюється на безглузду адресу.
    # Перевіряємо ДО додавання https://, бо «localhost:8080» теж схожий на
    # схему «localhost:» — його вже оброблено вище.
    if _SCHEME.match(clean):
        return clean
    # Слова без крапки — це пошуковий запит, а не адреса.
    if looks_like_query(clean):
        return search_url(clean)
    return "https://" + clean


def scheme_of(url: str) -> str:
    """Схема адреси в нижньому регістрі (``""``, якщо її немає)."""
    match = _SCHEME.match((url or "").strip())
    return match.group(0)[:-1].lower() if match else ""


def is_showable(url: str) -> bool:
    """Чи можна показати адресу у вбудованому вікні браузера."""
    return scheme_of(url) in {"http", "https", "file"}


def is_local_url(url: str) -> bool:
    """Чи це адреса локального сервера (127.0.0.1, localhost, file://).

    ``file://`` додано окремо (це файл на диску, а не сервер), решта —
    через :func:`provider_adapters.is_local_url`, ЄДИНУ реалізацію проєкту.
    """
    low = (url or "").strip().lower()
    if low.startswith("file://"):
        return True
    from .provider_adapters import is_local_url as _shared

    return _shared(url)


def file_url(path) -> str:
    """``file://``-адреса для локального файлу (щоб показати HTML з диска)."""
    try:
        return Path(path).resolve().as_uri()
    except (OSError, ValueError):
        return ""


#: Спільний відкривач: його ставить вікно IDE, і тоді КОЖЕН модуль
#: (панель змін, хаб моделей, налаштування) відкриває сторінку всередині
#: застосунку, а не в браузері користувача.
_OPENER: Optional[Callable[[str], bool]] = None


def set_url_opener(opener: Optional[Callable[[str], bool]]) -> None:
    """Призначити функцію, що відкриває адресу у вбудованому браузері."""
    global _OPENER
    _OPENER = opener


def current_url_opener() -> Optional[Callable[[str], bool]]:
    """Поточний відкривач (``None``, якщо вікно ще не підключилось)."""
    return _OPENER


def open_url(url: str, *, fallback: bool = False) -> bool:
    """Відкрити адресу у вбудованому браузері IDE.

    Це єдина точка входу для всього застосунку. Системний браузер
    **не** використовується: раніше саме через нього клік «Встановити git»
    викидав користувача з IDE в чуже вікно.

    ``fallback=True`` дозволяє віддати адресу системі, якщо вбудованого
    відкривача немає (наприклад, модуль викликали з консолі).
    """
    target = normalise_url(url)
    if not target:
        return False
    opener = _OPENER
    if opener is not None:
        try:
            if opener(target):
                return True
        except Exception:  # noqa: BLE001 - відкривач не має валити виклик
            LOG.debug("Вбудований відкривач упав", exc_info=True)
    if fallback:
        try:
            import webbrowser

            return bool(webbrowser.open(target))
        except Exception:  # noqa: BLE001 - системи може не бути
            return False
    return False


# ── Вбудовування вікна браузера (Windows API) ─────────────────────────────

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:  # pragma: no cover - інші системи
    _user32 = None


def _enum_windows() -> list[int]:
    """Усі вікна верхнього рівня (hwnd)."""
    if _user32 is None:
        return []
    handles: list[int] = []
    prototype = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):  # type: ignore[no-untyped-def]
        handles.append(int(hwnd))
        return True

    _user32.EnumWindows(prototype(callback), 0)
    return handles


def _pid_of(hwnd: int) -> int:
    if _user32 is None:
        return 0
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _embed(hwnd: int, parent: int) -> bool:
    """Вбудувати вікно браузера в наше (``SetParent``).

    Порядок критичний: спершу треба зробити вікно **дочірнім**
    (``WS_CHILD``, знявши ``WS_POPUP``), і лише потім викликати
    ``SetParent``. Якщо зробити навпаки, Chromium ігнорує батьківство —
    вікно лишається окремим, і ``GetParent`` повертає 0.
    """
    if _user32 is None:
        return False
    try:
        _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        _user32.SetParent.restype = wintypes.HWND
        _user32.GetParent.argtypes = [wintypes.HWND]
        _user32.GetParent.restype = wintypes.HWND

        GWL_STYLE = -16
        WS_CHILD = 0x40000000
        WS_POPUP = 0x80000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_SYSMENU = 0x00080000
        WS_VISIBLE = 0x10000000

        style = _user32.GetWindowLongW(int(hwnd), GWL_STYLE)
        style = (int(style) & ~WS_POPUP & ~WS_CAPTION & ~WS_THICKFRAME
                 & ~WS_SYSMENU) | WS_CHILD | WS_VISIBLE
        _user32.SetWindowLongW(int(hwnd), GWL_STYLE, style)
        _user32.SetParent(int(hwnd), int(parent))
        _user32.ShowWindow(int(hwnd), 5)  # SW_SHOW
        _user32.UpdateWindow(int(hwnd))

        actual = _user32.GetParent(int(hwnd))
        if not actual:
            LOG.warning("SetParent не застосувався (hwnd=%s)", hwnd)
            return False
        return True
    except (OSError, AttributeError) as exc:
        LOG.warning("Не вдалось вбудувати браузер: %s", exc)
        return False


def _move(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    if _user32 is None:
        return
    try:
        # Типи обов'язкові: без них ctypes ріже 64-бітні значення й
        # MoveWindow мовчки нічого не робить.
        _user32.MoveWindow.argtypes = [
            wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.BOOL,
        ]
        _user32.MoveWindow.restype = wintypes.BOOL
        _user32.MoveWindow(int(hwnd), int(x), int(y), max(1, int(width)),
                           max(1, int(height)), True)
        # Після SetParent вікно може лишитись прихованим — показуємо явно.
        _user32.ShowWindow(int(hwnd), 5)  # SW_SHOW
        _user32.UpdateWindow(int(hwnd))
    except (OSError, AttributeError):
        pass


def _destroy(hwnd: int) -> None:
    if _user32 is None:
        return
    try:
        _user32.DestroyWindow(int(hwnd))
    except (OSError, AttributeError):
        pass


def _post_key(hwnd: int, virtual_key: int) -> bool:
    """Надіслати натискання й відпускання клавіші у вікно (``False`` — не вдалось).

    Використовується як запасний шлях перезавантаження, коли CDP недоступний:
    справжня клавіша F5 у вікні Chromium оновлює саме сторінку, а не
    перезапускає браузер.
    """
    if _user32 is None or not hwnd:
        return False
    try:
        _user32.PostMessageW(int(hwnd), 0x0100, int(virtual_key), 0)  # WM_KEYDOWN
        _user32.PostMessageW(int(hwnd), 0x0101, int(virtual_key), 0)  # WM_KEYUP
        return True
    except (OSError, AttributeError):
        return False


def _class_name(hwnd: int) -> str:
    """Ім'я класу вікна (Chromium має кілька)."""
    if _user32 is None:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(int(hwnd), buffer, 256)
        return buffer.value
    except (OSError, AttributeError):
        return ""


def _find_window_for_pid(pid: int, *, timeout: float = 12.0) -> int:
    """Дочекатись ГОЛОВНОГО вікна браузера для процесу.

    Chromium створює кілька вікон класу ``Chrome_WidgetWin_*``: серед них є
    службові (0×0, приховані) і маленькі допоміжні. Беремо найбільше видиме
    вікно саме класу ``Chrome_WidgetWin_1`` — це й є вікно застосунку.
    """
    deadline = time.monotonic() + timeout
    best = 0
    best_area = 0
    while time.monotonic() < deadline:
        best = 0
        best_area = 0
        for hwnd in _enum_windows():
            if _pid_of(hwnd) != pid:
                continue
            if _user32 is None:
                continue
            try:
                if not _user32.IsWindowVisible(int(hwnd)):
                    continue
                name = _class_name(hwnd)
                if not name.startswith("Chrome_WidgetWin_1"):
                    continue
                rect = wintypes.RECT()
                if not _user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
                    continue
                area = (rect.right - rect.left) * (rect.bottom - rect.top)
                if area > best_area and (rect.right - rect.left) > 200:
                    best_area = area
                    best = int(hwnd)
            except (OSError, AttributeError):
                continue
        if best:
            return best
        time.sleep(0.2)
    return best


def _pick_target(targets: list[dict], wanted: str) -> dict:
    """Обрати вкладку для CDP: спершу ту, що показує потрібну адресу.

    Chromium тримає кілька сторінок: ``about:blank``, службові й ту, яку
    бачить користувач. Брати першу — означає інспектувати порожнечу
    («about:blank») замість сайту.
    """
    if not targets:
        return {}
    needle = (wanted or "").strip().rstrip("/")
    if needle:
        for target in targets:
            url = str(target.get("url") or "").rstrip("/")
            if url and url == needle:
                return target
        for target in targets:
            url = str(target.get("url") or "")
            if needle and needle in url:
                return target
    for target in targets:
        url = str(target.get("url") or "")
        if url and url not in ("about:blank", "chrome://newtab/", ""):
            return target
    return targets[0]


class BrowserView(tk.Frame):
    """Вбудований браузер із живою перезагрузкою."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_status: Optional[Callable[[str], None]] = None,
        bg: str = theme.BG,
    ) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.fonts = fonts
        self._bg = bg
        self.on_status = on_status
        self.url = ""
        self.process: Optional[subprocess.Popen] = None
        self.hwnd = 0
        self._reload_after: Optional[str] = None
        self._width = 1
        self._height = 1
        self._embedded = False
        self._sync_after: Optional[str] = None
        self._embed_after: Optional[str] = None
        self._hwnd_queue: "queue.Queue[int]" = queue.Queue()
        #: Історія переходів у межах вбудованого вікна («назад» працює).
        self._history: list[str] = []
        self._history_at = -1
        #: Порт налагодження Chromium (0 — сторінка недоступна з коду).
        self.debug_port = 0
        #: Жива CDP-сесія: консоль, DOM, знімки (див. :mod:`cdp`).
        self._cdp: Optional["cdp.CdpSession"] = None
        self._cdp_ready = False
        self._build()
        self.after(400, self._sync_size)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg=theme.BG_ALT)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        name, path = find_browser()
        self.engine_label = tk.Label(
            bar, text=f"🌐 {name or 'немає браузера'}",
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
        )
        self.engine_label.grid(row=0, column=0, padx=(10, 8), pady=5)

        # ── адресний рядок: можна перейти на будь-яку адресу, не лише
        #    на сайт проєкту. Саме цього бракувало, коли треба було
        #    показати сторінку завантаження git чи документацію.
        self.address = tk.Entry(
            bar, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=("Segoe UI", 10), bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT,
        )
        self.address.grid(row=0, column=1, sticky="ew", ipady=4, padx=(0, 4))
        self.address.bind("<Return>", lambda _e: self.go_from_address())
        self.address.bind("<Escape>", lambda _e: self._paint_address())
        # Ctrl+V у tk.Entry не завжди доходить, а правого меню немає взагалі:
        # підключаємо явно, як і в хабі моделей.
        widgets.attach_edit_actions(self.address)
        widgets.Tip(self.address,
                    "Адреса або пошуковий запит: локальний сайт, будь-яка "
                    "сторінка, чи просто слова — тоді шукаю в Google")

        self.back_btn = widgets.IconButton(bar, "‹", self.go_back, bg=theme.BG_ALT,
                                           fg=theme.FG, font=("Segoe UI", 13),
                                           tooltip="Назад")
        self.back_btn.grid(row=0, column=2, padx=(0, 2))

        self.forward_btn = widgets.IconButton(
            bar, "›", self.go_forward, bg=theme.BG_ALT,
            fg=theme.FG, font=("Segoe UI", 13), tooltip="Вперед")
        self.forward_btn.grid(row=0, column=3, padx=(0, 2))

        self.go_btn = widgets.IconButton(bar, "→", self.go_from_address, bg=theme.BG_ALT,
                                         fg=theme.FG, font=("Segoe UI", 11),
                                         tooltip="Перейти за адресою")
        self.go_btn.grid(row=0, column=4, padx=(0, 2))

        self.reload_btn = widgets.IconButton(bar, "⟳", self.reload, bg=theme.BG_ALT,
                                             fg=theme.FG, font=("Segoe UI", 12),
                                             tooltip="Перезавантажити сторінку")
        self.reload_btn.grid(row=0, column=5, padx=(0, 2))

        self.live_btn = widgets.IconButton(bar, "◉", self.toggle_live, bg=theme.BG_ALT,
                                           fg=theme.SUCCESS, font=("Segoe UI", 11),
                                           tooltip="Живе оновлення при змінах")
        self.live_btn.grid(row=0, column=6, padx=(0, 2))

        self.open_btn = widgets.IconButton(bar, "↗", self.open_external, bg=theme.BG_ALT,
                                           fg=theme.FG, font=("Segoe UI", 11),
                                           tooltip="Відкрити в системному браузері (потрібно рідко)")
        self.open_btn.grid(row=0, column=7, padx=(0, 8))

        # У вузькій колонці другорядні кнопки ховаються: інакше рядок адреси
        # стискається до кількох символів і ним неможливо користуватись.
        self._toolbar_buttons = {
            "back": self.back_btn,
            "forward": self.forward_btn,
            "go": self.go_btn,
            "reload": self.reload_btn,
            "live": self.live_btn,
            "open": self.open_btn,
        }
        self._compact_toolbar: Optional[bool] = None
        self.bind("<Configure>", self._on_toolbar_resize, add="+")

        # Місце для вбудованого вікна браузера
        self.host = tk.Frame(self, bg=theme.BG, bd=0, highlightthickness=0)
        self.host.grid(row=1, column=0, sticky="nsew")
        self.host.bind("<Configure>", self._on_configure)

        self.placeholder = tk.Label(
            self.host,
            text="Тут буде сайт проєкту.\n\nНатисни «Запустити сайт» — IDE підніме сервер\nі покаже сторінку прямо у вікні.",
            bg=theme.BG, fg=theme.FG_FAINT, font=("Segoe UI", 10), justify="center",
        )
        self.placeholder.place(relx=0.5, rely=0.45, anchor="center")

        self.live = True
        self._paint_live()

    # ── адаптивний тулбар ──────────────────────────────────────────────────
    def _on_toolbar_resize(self, event=None) -> None:
        """Адаптивний тулбар: у вузькій колонці лишаємо адресу й «перейти».

        Без цього на 244 px рядок адреси стискався до 2-3 символів, а
        кнопки займали більше місця, ніж сам вміст.
        """
        width = int(getattr(event, "width", 0) or 0)
        if width <= 1:
            try:
                width = self.winfo_width()
            except tk.TclError:
                return
        if width <= 1:
            return
        compact = width < 420
        if compact == self._compact_toolbar:
            return
        self._compact_toolbar = compact
        hide = ("back", "live", "open") if compact else ()
        for name, button in self._toolbar_buttons.items():
            try:
                if name in hide:
                    button.grid_remove()
                else:
                    button.grid()
            except tk.TclError:
                continue
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _paint_live(self) -> None:
        try:
            self.live_btn.configure(fg=theme.SUCCESS if self.live else theme.FG_FAINT)
        except tk.TclError:
            pass

    def toggle_live(self) -> None:
        self.live = not self.live
        self._paint_live()
        self._notify("Живе оновлення: " + ("увімкнено" if self.live else "вимкнено"))

    # ── відкриття сторінки ─────────────────────────────────────────────────
    def show(self, url: str) -> bool:
        """Показати адресу у вбудованому вікні."""
        target = normalise_url(url)
        if not target:
            return False
        if target != self.url:
            # Нова адреса — нова вкладка: кешована CDP-сесія належала
            # ПОПЕРЕДНІЙ сторінці й показувала б старий документ.
            self._close_cdp()
        self.url = target
        self._remember(target)
        self._paint_address()
        name, path = find_browser()
        if not name:
            self._show_fallback(target)
            return False
        self._launch(path, target)
        return True

    def open_url(self, url: str) -> bool:
        """Публічний перехід на довільну адресу (локальну або з інтернету)."""
        return self.show(url)

    # ── адресний рядок ─────────────────────────────────────────────────────
    def _paint_address(self) -> None:
        """Показати поточну адресу в рядку (не чіпаючи курсор під час вводу)."""
        try:
            if self.address.focus_get() is self.address:
                return
            self.address.delete(0, "end")
            self.address.insert(0, self.url or "")
            self.address.configure(fg=theme.FG)
        except tk.TclError:
            pass

    def go_from_address(self) -> None:
        """Перейти за адресою з рядка."""
        try:
            text = self.address.get().strip()
        except tk.TclError:
            return
        if not text:
            self._notify("Введи адресу — локальну або з інтернету.")
            return
        # Локальний файл на диску теж можна показати: HTML-звіт, згенерований
        # у проєкті, має відкриватись усередині IDE, а не в чужому вікні.
        as_path = Path(text.strip('"'))
        if as_path.exists() and as_path.is_file():
            self.show(as_path.as_uri())
            return
        target = normalise_url(text)
        if not target:
            self._notify("Не схоже на адресу.")
            return
        if not is_showable(target):
            scheme = scheme_of(target) or "ця"
            self._notify(f"Схему «{scheme}» вбудоване вікно не відкриває — "
                         f"підтримуються http, https і file.")
            return
        self.show(target)

    def set_address(self, url: str) -> None:
        """Оновити рядок адреси ззовні (після запуску сервера)."""
        self.url = normalise_url(url)
        self._paint_address()

    # ── історія ────────────────────────────────────────────────────────────
    def _remember(self, url: str) -> None:
        """Запам'ятати адресу для кнопки «назад»."""
        if not url:
            return
        if 0 <= self._history_at < len(self._history) and \
                self._history[self._history_at] == url:
            return
        # Перехід після «назад» обрізає «майбутнє».
        del self._history[self._history_at + 1:]
        self._history.append(url)
        del self._history[:-40]
        self._history_at = len(self._history) - 1

    def go_back(self) -> None:
        """Повернутись на попередню сторінку."""
        if self._history_at <= 0:
            self._notify("Попередньої сторінки немає.")
            return
        self._history_at -= 1
        target = self._history[self._history_at]
        self.url = target
        self._paint_address()
        name, path = find_browser()
        if not name:
            self._show_fallback(target)
            return
        self._launch(path, target)

    def go_forward(self) -> None:
        """Перейти на наступну сторінку (після «Назад»).

        Потрібно, щоб браузер поводився звично: без «Вперед» людина, яка
        випадково натиснула «Назад», мусила вводити адресу заново.
        """
        if self._history_at >= len(self._history) - 1:
            self._notify("Наступної сторінки немає.")
            return
        self._history_at += 1
        target = self._history[self._history_at]
        self.url = target
        self._paint_address()
        name, path = find_browser()
        if not name:
            self._show_fallback(target)
            return
        self._launch(path, target)

    def _kill_stale(self) -> None:
        """Прибити процес браузера, що лишився від попереднього запуску.

        ``taskkill /T /F`` вбиває й дочірні процеси Chromium — інакше вони
        тримають профіль і новий запуск «зливається» зі старим.
        """
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        pid = process.pid
        try:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        time.sleep(0.3)

    def _zoom_for(self, *, width: int, url: str) -> float:
        """Підібрати масштаб сторінки під ширину колонки.

        Навіщо це: у колонці 400-500 px «дорослий» сайт (git-scm.com,
        документація) відкривається в мобільній розкладці — величезні
        заголовки, обрізані меню. Зменшений масштаб показує сторінку так,
        як її бачать на ноутбуці, і нею можна користуватись.

        Локальні сайти проєкту НЕ масштабуємо, поки колонка не зовсім
        вузька: там своя адаптивна верстка, і зайвий масштаб лише псує
        живий прев'ю, яким користуються під час правок.
        """
        local = is_local_url(url)
        wide_enough = width >= 560
        if wide_enough:
            return 1.0
        if local:
            # Локальний сайт: масштаб лише на зовсім вузькій колонці.
            return 0.85 if width < 340 else 1.0
        if width < 360:
            return 0.55
        if width < 460:
            return 0.65
        return 0.8

    def _profile_dir(self) -> Path:
        """Унікальний профіль браузера для вбудовування.

        Кожен запуск отримує власну теку: інакше Chromium чіпляється до
        попереднього екземпляра (або до його «замка» у профілі) і замість
        нового вікна просто завершується.
        """
        try:
            from .config import app_data_dir

            base = app_data_dir() / "browser"
        except Exception:  # noqa: BLE001
            base = Path(os.environ.get("TEMP", ".")) / "bchpok-browser"
        # Старі профілі прибираємо, щоб не розростались.
        try:
            if base.is_dir():
                for old in base.iterdir():
                    if old.is_dir() and time.time() - old.stat().st_mtime > 3600:
                        shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
        folder = base / f"embed-{int(time.time() * 1000) % 10_000_000}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _launch(self, exe: str, url: str) -> None:
        """Запустити браузер у режимі застосунку й вбудувати вікно.

        Разом із вікном відкриваємо ПОРТ НАЛАГОДЖЕННЯ Chromium. Через нього
        працює :mod:`cdp`: консоль, помилки сторінки, DOM-інспектор, знімки
        й перевірка адаптивності. Без цього порту «вбудований браузер» був
        лише картинкою — сторінку неможливо було ані прочитати, ані
        виправити з агента.
        """
        if self.hwnd:
            _destroy(self.hwnd)
            self.hwnd = 0
        if self.process is not None and self.process.poll() is None:
            self.stop()
        # Chromium лишає дочірні процеси: наступний запуск чіпляється до
        # старого вікна замість створення нового.
        self._kill_stale()
        # Стара CDP-сесія належала старому процесу — закриваємо її.
        self._close_cdp()

        # ``--user-data-dir`` на своєму шляху НЕДОСТАТНЬО: Edge/Chrome усе одно
        # чіпляються до вже запущеного екземпляра й пишуть «Відкриття у
        # поточному сеансі браузера», після чого процес завершується. Тому
        # додаємо власну назву профілю й вимикаємо перевикористання сеансу.
        profile = self._profile_dir()
        # Порт налагодження: щоразу новий вільний, лише на localhost.
        self.debug_port = cdp.free_port() if cdp is not None else 0
        args = [
            exe,
            f"--app={url}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,DefaultBrowserCheck,CalculateNativeWinOcclusion",
            f"--user-data-dir={profile}",
            f"--profile-directory=IDE",
            "--no-service-autorun",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-extensions",
            "--disable-default-apps",
            # Greatly обмежуємо стартовий розмір: якщо передати розмір
            # більший за екран, Chromium падає з STATUS_BREAKPOINT
            # (0x80000003) ще до створення вікна.
            f"--window-size={min(900, max(400, self._width))},"
            f"{min(700, max(300, self._height))}",
            "--window-position=0,0",
        ]
        if self.debug_port:
            args.append(f"--remote-debugging-port={self.debug_port}")
            # Порт слухає лише 127.0.0.1: зовнішні сайти не мають доступу.
            args.append("--remote-allow-origins=http://127.0.0.1")
        # Вузька колонка: сторінка отримує мобільну розкладку й виглядає
        # зламаною. Масштаб 0.6-0.75 вписує «дорослий» сайт у 400-500 px,
        # зберігаючи читабельність. Локальні сайти проєкту масштабуємо лише
        # тоді, коли колонка справді вузька — інакше прев'ю «стрибало».
        zoom = self._zoom_for(width=self._width, url=url)
        if zoom and abs(zoom - 1.0) > 0.01:
            args.append(f"--force-device-scale-factor={zoom:.2f}")
        try:
            self.process = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            self._notify(f"Не вдалось запустити браузер: {exc}")
            self._show_fallback(url)
            return

        self._notify("Відкриваю сторінку у вбудованому браузері…")
        pid = self.process.pid
        self._hwnd_queue = queue.Queue()
        threading.Thread(target=self._embed_worker, args=(pid,), daemon=True).start()
        self._poll_embed()

    def _embed_worker(self, pid: int) -> None:
        """Знайти вікно браузера (у фоні) і передати hwnd головному потоку."""
        hwnd = _find_window_for_pid(pid, timeout=14.0)
        # З фонового потоку ненабезпечно навіть self.after — кладемо в чергу,
        # яку розбирає головний цикл.
        self._hwnd_queue.put(hwnd)

    def _poll_embed(self) -> None:
        """Розібрати чергу вбудовування (головний потік)."""
        try:
            hwnd = self._hwnd_queue.get_nowait()
        except queue.Empty:
            try:
                if self._alive():
                    self._embed_after = self.after(150, self._poll_embed)
            except tk.TclError:
                self._embed_after = None
            return
        self._embed_after = None
        if not hwnd:
            self._notify("Браузер відкрито окремо (вбудувати не вдалось).")
            return
        self.hwnd = int(hwnd)
        self._attach_embedded()

    def _attach_embedded(self) -> None:
        if not self.hwnd:
            return
        try:
            self.host.update_idletasks()
            parent = self.host.winfo_id()
        except tk.TclError:
            return
        if not _embed(self.hwnd, parent):
            self._notify("Не вдалось вбудувати вікно браузера.")
            return
        self._embedded = True
        try:
            self.placeholder.place_forget()
        except tk.TclError:
            pass
        # Одразу підганяємо розмір: інакше вікно лишається 0×0 і сторінка
        # виглядає порожньою.
        self._fit_now()
        # І ще кілька разів — поки tkinter не завершить розкладку.
        for delay in (50, 150, 350, 700, 1200, 2000, 3000, 4500):
            try:
                self.after(delay, self._fit_now)
            except tk.TclError:
                break
        # Chromium остаточно формує стиль вікна після завантаження сторінки —
        # знімаємо заголовок ще раз із запасом.
        for delay in (2500, 4000, 6000):
            try:
                if self._alive():
                    self.after(delay, self._strip_frame)
            except tk.TclError:
                break
        self._notify(f"Сторінка відкрита: {self.url}")

    def _strip_frame(self) -> None:
        """Прибрати заголовок і рамку (Chromium повертає їх після SetParent).

        Chromium іноді відновлює стандартний стиль вікна вже після
        ``SetParent``, і тоді всередині панелі з'являється смуга з назвою
        сторінки та кнопками «згорнути/закрити». Тому стиль знімаємо
        повторно — і одразу після вбудовування, і кілька разів із запасом.

        Важливо: ``WS_CHILD`` уже стоїть (його поставив ``_embed``), тому
        тут ми лише знімаємо рамку — не додаємо прапорців наново. Раніше
        в модулі було дві копії цього методу, і друга (з повторним
        ``WS_CHILD``) перемагала: стиль застосовувався, але Chromium його
        ігнорував і смуга лишалась.
        """
        if not self.hwnd or _user32 is None or not self._alive():
            return
        try:
            GWL_STYLE = -16
            WS_CHILD = 0x40000000
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_SYSMENU = 0x00080000
            WS_POPUP = 0x80000000
            WS_VISIBLE = 0x10000000
            style = int(_user32.GetWindowLongW(int(self.hwnd), GWL_STYLE))
            cleaned = (style & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_SYSMENU
                       & ~WS_POPUP) | WS_CHILD | WS_VISIBLE
            if cleaned != style:
                _user32.SetWindowLongW(int(self.hwnd), GWL_STYLE, cleaned)
            # Chromium малює власну «псевдосмугу» (назва сторінки й кнопки)
            # НЕ через WS_CAPTION: у режимі --app вона є частиною клієнтської
            # області вікна. Тому додатково знімаємо розширений стиль вікна
            # з рамкою й забираємо заголовок у самого вікна — інакше над
            # сторінкою лишається рядок «Sample Domain — □ ×».
            GWL_EXSTYLE = -20
            WS_EX_DLGMODALFRAME = 0x00000001
            WS_EX_WINDOWEDGE = 0x00000100
            WS_EX_CLIENTEDGE = 0x00000200
            WS_EX_STATICEDGE = 0x00020000
            ex = int(_user32.GetWindowLongW(int(self.hwnd), GWL_EXSTYLE))
            ex_cleaned = (ex & ~WS_EX_DLGMODALFRAME & ~WS_EX_WINDOWEDGE
                          & ~WS_EX_CLIENTEDGE & ~WS_EX_STATICEDGE)
            if ex_cleaned != ex:
                _user32.SetWindowLongW(int(self.hwnd), GWL_EXSTYLE, ex_cleaned)
            _user32.SetWindowTextW(int(self.hwnd), "")
            # Кадр перемальовується лише після FRAMECHANGED.
            _user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            _user32.SetWindowPos(int(self.hwnd), 0, 0, 0, 0, 0, 0x0027)
        except (OSError, AttributeError):
            pass

    def _fit_now(self) -> None:
        """Підігнати вікно браузера під розмір панелі.

        Після ``SetParent`` координати дочірнього вікна відраховуються від
        батьківського, тому достатньо ``0, 0`` і розмірів панелі.
        """
        if not self.hwnd:
            return
        try:
            self.host.update_idletasks()
            width = self.host.winfo_width()
            height = self.host.winfo_height()
        except tk.TclError:
            return
        if width <= 4 or height <= 4:
            return
        # Chromium інколи повертає заголовок після SetParent — знімаємо щоразу.
        self._strip_frame()
        # ── смуга «назва сторінки + □ ×» ───────────────────────────────────
        # У режимі ``--app`` Chromium малює власну смугу ВСЕРЕДИНІ клієнтської
        # області: це не WS_CAPTION, тому зняття стилів її не прибирає
        # (перевірено: style=0x56030000, тобто ні CAPTION, ні SYSMENU вже
        # немає, а смуга на екрані лишається). Єдиний спосіб прибрати її без
        # сторонніх пакетів — зсунути вікно браузера вгору на її висоту й
        # віддати йому більше висоти: тоді смуга ховається за межами панелі,
        # а сторінка займає рівно відведене місце.
        _move(self.hwnd, 0, -CUSTOM_FRAME_HEIGHT,
              int(width), int(height) + CUSTOM_FRAME_HEIGHT)
        try:
            self._last_fit = (int(width), int(height))
        except AttributeError:
            pass

    def _show_fallback(self, url: str) -> None:
        """Запасний варіант: показати сторінку текстом."""
        try:
            self.placeholder.configure(
                text=f"Браузер не знайдено.\nСторінка: {url}\n\nПостав Chrome або Edge,\nщоб бачити сайт у вікні.")
            self.placeholder.place(relx=0.5, rely=0.45, anchor="center")
        except tk.TclError:
            pass
        self._notify("Браузер не знайдено — встанови Chrome або Edge.")

    # ── розмір вікна ───────────────────────────────────────────────────────
    def _on_configure(self, event) -> None:
        self._width = event.width
        self._height = event.height
        if self._embedded:
            self._fit_now()

    def _sync_size(self) -> None:
        """Тримати вікно браузера точно в межах панелі.

        Планує наступну синхронізацію лише поки віджет існує: інакше після
        закриття вікна в черзі лишаються «мертві» виклики й сиплеться
        ``invalid command name …_sync_size``.
        """
        self._sync_after = None
        if not self._alive() or not self._embedded or not self.hwnd:
            return
        try:
            width = self.host.winfo_width()
            height = self.host.winfo_height()
        except tk.TclError:
            return
        if width > 1 and height > 1:
            # Той самий зсув, що й у _fit_now: інакше періодична синхронізація
            # повертала б смугу Chromium на екран.
            _move(self.hwnd, 0, -CUSTOM_FRAME_HEIGHT,
                  width, height + CUSTOM_FRAME_HEIGHT)
        try:
            self._sync_after = self.after(500, self._sync_size)
        except tk.TclError:
            self._sync_after = None

    def _alive(self) -> bool:
        """Чи існує ще цей віджет."""
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    # ── CDP: доступ до сторінки з коду ─────────────────────────────────────
    def ensure_cdp(self, *, timeout: float = 12.0) -> Optional["cdp.CdpSession"]:
        """Підключитись до сторінки через порт налагодження (з кешуванням).

        Повертає живу сесію або ``None``, якщо браузер не має порту
        налагодження (напр. вбудування не вдалось). Це єдина точка входу
        для панелі, агента й тестів.

        ВАЖЛИВО про вибір вкладки: у браузера може бути кілька сторінок
        (стара, порожня ``about:blank``, нова з сайтом). Раніше бралась
        ``targets[0]`` — і після кількох переходів інспектор дивився в
        порожню вкладку, показуючи ``about:blank``. Тепер обираємо ту, чия
        адреса збігається з поточною (``self.url``), а якщо таких немає —
        першу НЕпорожню.
        """
        if cdp is None:
            return None
        existing = self._cdp
        if existing is not None and existing.connected:
            # Кешована сесія могла лишитись від ІНШОЇ сторінки (попередній
            # перехід, порожня вкладка). Перевіряємо, що вона справді
            # показує нашу адресу, інакше перепідключаємось — інакше
            # інспектор і консоль бачать ``about:blank``.
            wanted = (self.url or "").strip().rstrip("/")
            current = str(existing.page_url() or "").strip().rstrip("/")
            if not wanted or current == wanted or wanted in current:
                return existing
            self._close_cdp()
        if not self.debug_port:
            return None
        if not cdp.wait_for_devtools(self.debug_port, timeout=timeout):
            self._notify("Сторінка недоступна для інспектора: "
                         "порт налагодження не відповів.")
            return None
        # Вкладка з'являється раніше, ніж документ завантажується: на старті
        # Chromium показує ``about:blank``, і якщо прив'язатись до нього,
        # інспектор назавжди бачить порожню сторінку. Тому чекаємо, поки
        # з'явиться вкладка з реальною адресою (або поки не вийде час).
        chosen: dict = {}
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline:
            try:
                targets = cdp.page_targets(self.debug_port)
            except cdp.CdpError:
                targets = []
            candidate = _pick_target(targets, self.url)
            url = str(candidate.get("url") or "")
            if url and url not in ("about:blank", "chrome://newtab/"):
                chosen = candidate
                break
            if not chosen and candidate:
                chosen = candidate
            time.sleep(0.2)
        if not chosen:
            try:
                chosen = _pick_target(cdp.page_targets(self.debug_port), self.url)
            except cdp.CdpError as exc:
                self._notify(f"Інспектор: {exc}")
                return None
        session = cdp.CdpSession(self.debug_port,
                                 page_id=str(chosen.get("id") or ""))
        if not session.connect():
            self._notify(f"Інспектор: {session.last_error}")
            return None
        session.enable()
        # Перевірка «а чи справді ми дивимось на нашу сторінку»: буває, що
        # сесія прив'язалась до вкладки, яка ще не перейшла на адресу
        # (``about:blank``). Тоді перепідключаємось до вкладки з потрібною
        # адресою — інакше інспектор і консоль показують порожнечу.
        wanted = (self.url or "").strip().rstrip("/")
        if wanted and "about:blank" in str(session.page_url() or ""):
            for _attempt in range(12):
                time.sleep(0.25)
                try:
                    fresh = _pick_target(cdp.page_targets(self.debug_port), wanted)
                except cdp.CdpError:
                    break
                url = str(fresh.get("url") or "").rstrip("/")
                if not url or "about:blank" in url:
                    continue
                if str(fresh.get("id") or "") != str(chosen.get("id") or ""):
                    session.close()
                    session = cdp.CdpSession(
                        self.debug_port, page_id=str(fresh.get("id") or ""))
                    if not session.connect():
                        return None
                    session.enable()
                break
        self._cdp = session
        self._cdp_ready = True
        return session

    def _close_cdp(self) -> None:
        session = self._cdp
        self._cdp = None
        self._cdp_ready = False
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - закриття не має падати
                LOG.debug("CDP-сесія не закрилась", exc_info=True)

    # ── перезавантаження ───────────────────────────────────────────────────
    def reload(self) -> None:
        """Перезавантажити сторінку (через CDP, якщо він доступний)."""
        if not self.url:
            self._notify("Спочатку запусти сайт.")
            return
        session = self._cdp
        if session is not None and session.connected and session.reload():
            self._notify("Сторінку перезавантажено.")
            return
        self.show(self.url)

    def schedule_reload(self, delay: int = 450) -> None:
        """Запланувати живе перезавантаження (після зміни файлу)."""
        if not self.live or not self.url:
            return
        if self._reload_after is not None:
            try:
                self.after_cancel(self._reload_after)
            except (tk.TclError, ValueError):
                pass
        try:
            self._reload_after = self.after(delay, self._do_reload)
        except tk.TclError:
            self._reload_after = None

    def _do_reload(self) -> None:
        self._reload_after = None
        # 1. Спершу CDP: він перезавантажує САМЕ СТОРІНКУ, зберігаючи
        #    вкладку, історію й точку, де був користувач. Раніше кожне
        #    оновлення перезапускало процес браузера повністю.
        session = self._cdp
        if session is not None and session.connected and session.reload():
            return
        if self.hwnd:
            # 2. Запасний шлях: F5 у вікно браузера.
            if _post_key(self.hwnd, 0x74):
                return
        self.reload()

    def open_external(self) -> None:
        """Відкрити сторінку в системному браузері."""
        if not self.url:
            return
        import webbrowser

        webbrowser.open(self.url)

    # ── зупинка ────────────────────────────────────────────────────────────
    def stop(self) -> None:
        """Закрити вбудований браузер."""
        self._close_cdp()
        if self._sync_after is not None:
            try:
                self.after_cancel(self._sync_after)
            except (tk.TclError, ValueError):
                pass
            self._sync_after = None
        if self.hwnd:
            _destroy(self.hwnd)
            self.hwnd = 0
        self._embedded = False
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
        self.process = None
        try:
            self.placeholder.place(relx=0.5, rely=0.45, anchor="center")
        except tk.TclError:
            pass

    @property
    def running(self) -> bool:
        return bool(self.hwnd) or (self.process is not None and self.process.poll() is None)

    def destroy(self) -> None:
        """Захисне прибирання: скасувати таймер і закрити браузер.

        ``stop()`` кличе вікно, але панель можуть знищити й напряму
        (перемикання вкладки, закриття IDE). Без цього в черзі Tk
        лишається ``_sync_size`` і сиплеться ``invalid command name``.
        """
        try:
            self.stop()
        except Exception:  # noqa: BLE001 - прибирання не має падати
            pass
        super().destroy()


__all__ = ["BrowserView", "browsers", "find_browser"]
