"""Живе керування застосунком проєкту для агента.

Агент має вміти тестувати додаток напряму в IDE: запустити його, подивитись
скріншот, клікнути по елементу, ввести текст і побачити результат власних
змін. Модуль збирає це докупи:

* ``AppController`` — обгортка над ``web_server.DevServer``: старт/стоп/
  рестарт/статус + журнал запуску;
* ``take_screenshot`` — знімок екрана (усього або вікна за заголовком)
  через Pillow ``ImageGrab``;
* ``find_window`` / ``window_rect`` — пошук вікна Win32 за заголовком;
* ``click_at`` / ``type_text`` — клік і введення через ``SendInput``
  (нативний WinAPI, без зовнішніх залежностей).

Модуль не імпортує tkinter — його можна викликати з потоку агента.
Усі функції повертають рядки-повідомлення, придатні для показу в чаті.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import web_server

LOG = logging.getLogger("blackchpok.appctl")

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
else:  # pragma: no cover - на інших ОС інструменти просто відмовляються
    _user32 = None
    _kernel32 = None

# ── Win32 константи ────────────────────────────────────────────────────────
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


# ── Вікна ──────────────────────────────────────────────────────────────────

def find_window(title: str) -> int:
    """HWND вікна, чий заголовок містить ``title`` (без регістру).

    Раніше тут стояв декоратор ``@_user32.EnumWindows`` — це некоректний
    спосіб указати тип зворотного виклику: Windows отримував функцію
    Python замість покажчика й кидав ``ctypes.ArgumentError``. Через це
    ``app_screenshot`` і ``app_click`` падали замість того, щоб знайти вікно.
    """
    if not IS_WINDOWS or not title:
        return 0
    needle = title.lower()
    found: list[int] = []

    def _visit(hwnd, _lparam) -> bool:
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            if needle in buffer.value.lower():
                found.append(int(hwnd))
                return False
        except Exception:  # noqa: BLE001 - одне вікно не має валити пошук
            return True
        return True

    try:
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                      wintypes.LPARAM)(_visit)
        _user32.EnumWindows(callback, 0)
    except Exception:  # noqa: BLE001 - Win32 не має валити потік агента
        pass
    return found[0] if found else 0


def _EnumWindowsProc(callback):  # noqa: N802 - ім'я WinAPI
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    return proto(callback)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) вікна в екранних координатах."""
    if not IS_WINDOWS or not hwnd:
        return (0, 0, 0, 0)
    rect = wintypes.RECT()
    if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return (0, 0, 0, 0)


# ── Скріншоти ──────────────────────────────────────────────────────────────

def take_screenshot(title: str = "", path: str = "", *,
                    hwnd: int = 0) -> str:
    """Зняти скріншот і зберегти в PNG — БЕЗ зовнішніх бібліотек.

    ``title`` — частина заголовка вікна (порожній = весь екран).
    ``path`` — куди зберегти (порожній = типовий каталог).
    ``hwnd`` — готовий дескриптор вікна (найточніший спосіб).
    Повертає текст для агента зі шляхом до PNG.

    Раніше тут вимагався Pillow, а він у ``requirements.txt`` був
    ЗАКОМЕНТОВАНИЙ: інструмент щоразу відповідав «немає Pillow», і модель
    не могла побачити результат власної роботи. Тепер знімок робить
    :mod:`screenshot` через Win32 GDI, а PNG кодується власним кодом на
    ``zlib``. Залежностей немає.
    """
    from . import screenshot as shot

    target: Path
    if path:
        target = Path(path)
    else:
        from .config import app_data_dir

        target = (app_data_dir() / "screenshots"
                  / f"shot-{int(time.time() * 1000) % 100_000_000}.png")

    # 1. Точний HWND (найнадійніше: не залежить від заголовків на машині).
    #    Важливо: вікно може бути ДОЧІРНІМ (вбудований браузер вставлено в
    #    IDE через ``SetParent``), тому ``EnumWindows`` його не бачить —
    #    описуємо напряму за дескриптором.
    if hwnd:
        info = shot.describe_window(int(hwnd))
        if info is not None and info.width >= 8 and info.height >= 8:
            capture = shot.capture_window(info, target)
            return (f"{capture.text()}\n" if capture.ok
                    else f"✗ {capture.detail}")
        # Вікна немає або воно нульове — пробуємо як прямокутник екрана.
        capture = shot.capture_screen(target, hwnd=int(hwnd))
        return capture.text() if capture.ok else f"✗ {capture.detail}"

    if not title:
        capture = shot.capture_screen(target)
        return capture.text() if capture.ok else f"✗ {capture.detail}"

    # «*» — явний запит на весь екран (модель може обрати його свідомо).
    if title.strip() in ("*", "all", "screen", "екран"):
        capture = shot.capture_screen(target)
        return capture.text() if capture.ok else f"✗ {capture.detail}"

    # 2. За заголовком (звичайні застосунки користувача).
    candidates = shot.find_windows(title)
    if not candidates:
        return (f"✗ Вікно «{title}» не знайдено — застосунок запущено? "
                f"Перевір інструментом app_windows, які вікна є.")
    for info in candidates[:3]:
        capture = shot.capture_window(info, target)
        if capture.ok:
            return (f"{capture.text()}\n"
                    "Далі: подивись цей файл зображенням, щоб оцінити вигляд, "
                    "або покажи його користувачеві.")
        LOG.debug("Знімок вікна %s не вдався: %s", info.line(), capture.detail)
    return (f"✗ Не вдалось зняти «{title}»: вікон знайдено "
            f"({len(candidates)}), але жодне не дало зображення.")


def screenshot_windows() -> str:
    """Перелік вікон, які зараз можна зняти (для агента).

    Навіщо: модель має бачити, ЩО доступне, і не гадати назву вікна
    навмання. Саме через це ``app_screenshot("site")`` раніше не знаходив
    нічого й модель повторювала виклик.
    """
    from . import screenshot as shot

    windows = shot.find_windows(min_size=200)
    if not windows:
        return "Видимих вікон не знайдено."
    lines = ["Доступні вікна (заголовок · клас · розмір):"]
    for info in windows[:25]:
        marker = " ← схоже на браузер" if "Chrome_WidgetWin" in info.class_name else ""
        lines.append(f"• {info.line()}{marker}")
    lines.append("")
    lines.append("Знімок: app_screenshot(title=<частина заголовка>) або "
                 "app_screenshot() для всього екрана.")
    return "\n".join(lines)


# ── Кліки й введення ───────────────────────────────────────────────────────

def click_at(x: int, y: int, *, double: bool = False, right: bool = False) -> str:
    """Клік мишею в абсолютних екранних координатах."""
    if not IS_WINDOWS:
        return "✗ Клік працює лише на Windows."
    if not _set_cursor(x, y):
        return f"✗ Не вдалось перемістити курсор у ({x}, {y})."
    time.sleep(0.05)
    down = MOUSEEVENTF_RIGHTDOWN if right else MOUSEEVENTF_LEFTDOWN
    up = MOUSEEVENTF_RIGHTUP if right else MOUSEEVENTF_LEFTUP
    _send_mouse(down)
    _send_mouse(up)
    if double:
        time.sleep(0.06)
        _send_mouse(down)
        _send_mouse(up)
    place = f"подвійний " if double else ""
    place += "правий " if right else ""
    return f"✓ {place or ''}Клік виконано в ({x}, {y}).".replace("  ", " ")


def _set_cursor(x: int, y: int) -> bool:
    return bool(_user32.SetCursorPos(int(x), int(y)))


def _send_mouse(flags: int) -> None:
    extra = ctypes.POINTER(ctypes.c_ulong)()
    inp = _INPUT(type=INPUT_MOUSE)
    inp.mi = _MOUSEINPUT(0, 0, 0, flags, 0, extra)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def type_text(text: str, *, press_enter: bool = False) -> str:
    """Ввести текст у сфокусоване поле (Unicode через SendInput)."""
    if not IS_WINDOWS:
        return "✗ Введення працює лише на Windows."
    if not text:
        return "✗ Порожній текст для введення."
    sent = 0
    for char in text:
        code = ord(char)
        if code > 0xFFFF:
            continue
        _send_key_unicode(code, up=False)
        _send_key_unicode(code, up=True)
        sent += 1
        time.sleep(0.004)
    if press_enter:
        _send_vk(VK_RETURN)
        time.sleep(0.03)
    return f"✓ Введено {sent} символів" + (" і Enter." if press_enter else ".")


def press_key(key: str = "enter") -> str:
    """Натиснути службову клавішу: enter, esc, tab, f5."""
    if not IS_WINDOWS:
        return "✗ Клавіші працюють лише на Windows."
    keys = {"enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "f5": 0x74}
    code = keys.get(key.strip().lower())
    if code is None:
        return f"✗ Невідома клавіша «{key}» (є: {', '.join(sorted(set(keys)))})."
    _send_vk(code)
    return f"✓ Натиснуто {key}."


def _send_key_unicode(code: int, *, up: bool) -> None:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    extra = ctypes.POINTER(ctypes.c_ulong)()
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.ki = _KEYBDINPUT(0, code, flags, 0, extra)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_vk(vk: int) -> None:
    extra = ctypes.POINTER(ctypes.c_ulong)()
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.ki = _KEYBDINPUT(vk, 0, 0, 0, extra)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    time.sleep(0.02)
    inp.ki = _KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, extra)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


# ── Керування застосунком ──────────────────────────────────────────────────

class AppController:
    """Життєвий цикл застосунку проєкту: старт / стоп / рестарт / статус.

    Один екземпляр живе у вікні IDE і використовується і кнопкою прев'ю,
    і агентними інструментами ``app_start`` / ``app_stop`` / ``app_restart``.
    """

    def __init__(self, root_provider: Callable[[], Optional[Path]]) -> None:
        self.root_provider = root_provider
        self.server: Optional[web_server.DevServer] = None
        self.recipe: Optional[web_server.Recipe] = None
        self._lock = threading.Lock()

    # ── стан ───────────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self.server is not None and self.server.running

    @property
    def url(self) -> str:
        if self.server is None:
            return ""
        return self.server.url

    def detect(self) -> Optional[web_server.Recipe]:
        """Визначити, як запускається проєкт (без старту)."""
        root = self.root_provider() if self.root_provider else None
        if not root:
            return None
        recipe = web_server.detect(Path(root))
        self.recipe = recipe
        return recipe

    def describe(self) -> str:
        """Короткий текст стану для статусбара й інструмента app_status.

        Якщо стек ще не визначали — визначаємо зараз: раніше тут
        поверталось «стек не визначено» навіть для проєкту з
        ``index.html``, бо ``self.recipe`` порожній до першого
        :meth:`detect`. Через це агент бачив безпорадний статус.
        """
        if self.running and self.server is not None:
            return f"запущено · {self.server.url}"
        if self.recipe is None:
            try:
                self.detect()
            except Exception:                    # noqa: BLE001 - статус не має падати
                LOG.debug("Стек не визначено для статусу", exc_info=True)
        if self.recipe is not None and self.recipe.ok:
            return f"зупинено · стек: {self.recipe.label}"
        if self.recipe is not None and self.recipe.reason:
            return f"зупинено · {self.recipe.reason}"
        return "зупинено · стек не визначено"

    # ── керування ──────────────────────────────────────────────────────────
    def start(self) -> tuple[bool, str]:
        """Запустити застосунок. Повертає (успіх, повідомлення)."""
        with self._lock:
            if self.running and self.server is not None:
                return True, f"Вже запущено: {self.server.url}"
            recipe = self.detect()
            if recipe is None:
                return False, "Спочатку відкрий теку проєкту."
            if not recipe.ok:
                return False, recipe.reason or "Не вдалось визначити, як запустити проєкт."
            missing = web_server.missing_tools(recipe)
            if missing:
                return False, f"Бракує програми: {', '.join(missing)}."
            if self.server is not None:
                self.server.stop()
            recipe.port = web_server.free_port(recipe.port or 8000)
            server = web_server.DevServer(recipe)
            ok, detail = server.start()
            if not ok:
                return False, detail
            self.server = server
            ready, note = web_server.wait_for_port(server.port, timeout=45)
            if not ready:
                tail = server.tail(12).strip()
                return False, f"{note}\n{tail[-300:]}" if tail else note
            return True, f"{note} · {server.url}"

    def stop(self) -> str:
        """Зупинити застосунок."""
        with self._lock:
            if self.server is None:
                return "Застосунок не запущено."
            server, self.server = self.server, None
            server.stop()
            return "Застосунок зупинено."

    def restart(self) -> tuple[bool, str]:
        """Перезапустити застосунок (новий порт, свіжий процес)."""
        with self._lock:
            if self.server is not None:
                self.server.stop()
                self.server = None
        return self.start()

    def logs(self, lines: int = 20) -> str:
        """Хвіст журналу запуску (помилки запуску видно одразу)."""
        if self.server is None:
            return "Журнал порожній — застосунок не запущено."
        tail = self.server.tail(lines)
        return tail.strip() or "Журнал порожній."

    def on_close(self) -> None:
        """Прибрати процес при закритті вікна IDE."""
        try:
            if self.server is not None:
                self.server.stop()
        except Exception:  # noqa: BLE001 - закриття не має падати
            pass
        self.server = None


__all__ = [
    "AppController",
    "click_at",
    "find_window",
    "press_key",
    "take_screenshot",
    "type_text",
    "window_rect",
]
