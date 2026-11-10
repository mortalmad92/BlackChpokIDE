"""Скріншоти БЕЗ зовнішніх бібліотек: Win32 GDI + власний PNG-кодер.

Проблема, яку це вирішує. ``app_screenshot`` вимагав Pillow, а Pillow у
``requirements.txt`` був **закоментований**. Тобто інструмент існував, був
описаний у схемах і каталозі для моделі — і щоразу відповідав «немає
Pillow». Модель не могла подивитись на результат своєї роботи: саме тому
агент «вгадував», як виглядає сторінка, замість того, щоб побачити її.

Рішення: знімаємо через Win32 (``PrintWindow`` / ``BitBlt``) і кодуємо PNG
самі (``zlib`` — стандартна бібліотека). Жодних залежностей.

Що вміє:

* ``capture_window`` — вікно за HWND (працює для вбудованого Chromium);
* ``capture_screen`` — увесь екран або прямокутник;
* ``find_windows`` — пошук вікон за заголовком, КЛАСОМ або PID;
* ``to_png`` — кодування BMP-буфера у PNG.

Модуль не тягне tkinter і нічого не робить під час імпорту.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

LOG = logging.getLogger("blackchpok.screenshot")

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
else:  # pragma: no cover - на інших ОС усе чесно відмовляє
    wintypes = None                     # type: ignore[assignment]
    _user32 = None
    _gdi32 = None

#: ``PrintWindow`` з цим прапорцем малює й ті частини, що поза екраном.
PW_RENDERFULLCONTENT = 0x00000002
#: ``BitBlt``: копіювати пікселі як є.
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


@dataclass
class WindowInfo:
    """Одне знайдене вікно."""

    hwnd: int
    title: str
    class_name: str
    pid: int
    width: int
    height: int

    def line(self) -> str:
        return (f"«{self.title or '(без заголовка)'}» · клас {self.class_name} · "
                f"{self.width}×{self.height} · pid {self.pid}")


# ─────────────────────────────────────────────────────────────────────────────
# Пошук вікон
# ─────────────────────────────────────────────────────────────────────────────

def _window_text(hwnd: int) -> str:
    if not _user32:
        return ""
    try:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:  # noqa: BLE001
        return ""


def _class_name(hwnd: int) -> str:
    if not _user32:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value
    except Exception:  # noqa: BLE001
        return ""


def _window_pid(hwnd: int) -> int:
    if not _user32:
        return 0
    try:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:  # noqa: BLE001
        return 0


def _size(hwnd: int) -> tuple[int, int]:
    if not _user32:
        return (0, 0)
    try:
        rect = wintypes.RECT()
        if _user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return (max(0, rect.right - rect.left), max(0, rect.bottom - rect.top))
    except Exception:  # noqa: BLE001
        pass
    return (0, 0)


def iter_windows(*, visible_only: bool = True) -> Iterator[WindowInfo]:
    """Перебрати всі вікна верхнього рівня."""
    if not _user32:
        return
    collected: list[WindowInfo] = []

    def visit(hwnd, _param) -> bool:
        try:
            if visible_only and not _user32.IsWindowVisible(hwnd):
                return True
            width, height = _size(hwnd)
            if width < 8 or height < 8:
                return True
            collected.append(WindowInfo(
                hwnd=int(hwnd), title=_window_text(hwnd),
                class_name=_class_name(hwnd), pid=_window_pid(hwnd),
                width=width, height=height))
        except Exception:  # noqa: BLE001
            return True
        return True

    try:
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                      wintypes.LPARAM)(visit)
        _user32.EnumWindows(callback, 0)
    except Exception:  # noqa: BLE001
        return
    for item in collected:
        yield item


def describe_window(hwnd: int) -> Optional[WindowInfo]:
    """Описати вікно за дескриптором — навіть якщо воно ДОЧІРНЄ.

    Чому окремо від :func:`find_windows`: вбудований браузер IDE вставлено
    в наше вікно через ``SetParent``, тож він **дочірній**. ``EnumWindows``
    перебирає лише вікна верхнього рівня, тому пошук його не бачив зовсім,
    і знімок мовчки падав на «весь екран» — у чаті користувача з'являвся
    знімок усього робочого столу замість його сайту.
    """
    if not IS_WINDOWS or not hwnd:
        return None
    try:
        if not _user32.IsWindow(int(hwnd)):
            return None
        width, height = _size(int(hwnd))
        return WindowInfo(hwnd=int(hwnd), title=_window_text(int(hwnd)),
                          class_name=_class_name(int(hwnd)),
                          pid=_window_pid(int(hwnd)),
                          width=width, height=height)
    except Exception:  # noqa: BLE001
        return None


def find_windows(query: str = "", *, pid: int = 0,
                 class_name: str = "", min_size: int = 120) -> list[WindowInfo]:
    """Знайти вікна за заголовком / класом / PID.

    Навіщо всі три способи: у вбудованого браузера IDE **заголовок
    очищено** (``SetWindowTextW(hwnd, "")``), тож пошук за назвою його не
    знаходив — і знімок сторінки був неможливий. За класом
    (``Chrome_WidgetWin_1``) або за PID вікно знаходиться завжди.
    """
    needle = (query or "").strip().lower()
    wanted_class = (class_name or "").strip().lower()
    found: list[WindowInfo] = []
    for window in iter_windows():
        if window.width < min_size or window.height < min_size:
            continue
        if pid and window.pid != pid:
            continue
        if wanted_class and wanted_class not in window.class_name.lower():
            continue
        if needle:
            haystack = f"{window.title} {window.class_name}".lower()
            if not all(token in haystack for token in needle.split()):
                continue
        found.append(window)
    # Більші вікна — першими: головне вікно застосунку зазвичай найбільше.
    found.sort(key=lambda item: item.width * item.height, reverse=True)
    return found


# ──────────────────────────────────────────────────────────────────────────────
# Захоплення пікселів
# ─────────────────────────────────────────────────────────────────────────────

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _grab(hwnd: int, width: int, height: int, *, screen_rect=None,
          use_print_window: bool = True) -> Optional[bytes]:
    """Захопити пікселі у форматі BGRA (згори вниз).

    ``use_print_window`` — спосіб ``PrintWindow``: він малює вікно навіть
    якщо воно перекрите іншими вікнами. Для вбудованого Chromium це
    єдиний надійний шлях.
    """
    if not _gdi32 or not _user32:
        return None
    hdc_screen = _user32.GetDC(hwnd if hwnd else 0)
    if not hdc_screen:
        return None
    mem_dc = _gdi32.CreateCompatibleDC(hdc_screen)
    bitmap = _gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    if not mem_dc or not bitmap:
        _user32.ReleaseDC(hwnd, hdc_screen)
        return None
    old = _gdi32.SelectObject(mem_dc, bitmap)
    try:
        drawn = False
        if use_print_window and hwnd:
            drawn = bool(_user32.PrintWindow(int(hwnd), mem_dc,
                                             PW_RENDERFULLCONTENT))
        if not drawn:
            if screen_rect:
                left, top, right, bottom = screen_rect
                _gdi32.BitBlt(mem_dc, 0, 0, width, height, hdc_screen,
                              left, top, SRCCOPY)
            elif hwnd:
                _gdi32.BitBlt(mem_dc, 0, 0, width, height, hdc_screen,
                              0, 0, SRCCOPY)
        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height          # від'ємна = згори вниз
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = _gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer,
                                  ctypes.byref(header), DIB_RGB_COLORS)
        if not copied:
            return None
        return buffer.raw
    finally:
        try:
            _gdi32.SelectObject(mem_dc, old)
            _gdi32.DeleteObject(bitmap)
            _gdi32.DeleteDC(mem_dc)
        except Exception:  # noqa: BLE001
            pass
        _user32.ReleaseDC(hwnd, hdc_screen)


def _looks_blank(raw: bytes) -> bool:
    """Чи знімок порожній (усе чорне або усе однакове).

    ``PrintWindow`` іноді повертає порожнє полотно (наприклад, коли вікно
    ще не домалювалось). Тоді треба спробувати інший спосіб, а не віддавати
    користувачу чорний прямокутник.
    """
    if not raw or len(raw) < 4000:
        return True
    step = max(4, len(raw) // 4000 // 4 * 4)
    seen = set()
    for index in range(0, len(raw) - 3, step):
        seen.add(raw[index:index + 3])
        if len(seen) > 2:
            return False
    return True


def to_png(width: int, height: int, bgra: bytes, *, quality: int = 6) -> bytes:
    """Закодувати BGRA у PNG (без Pillow)."""
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        base = row * stride
        raw.append(0)                       # фільтр «none»
        line = bgra[base:base + stride]
        # BGRA → RGB
        raw.extend(b"".join(
            bytes((line[col + 2], line[col + 1], line[col]))
            for col in range(0, len(line), 4)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), quality))
            + chunk(b"IEND", b""))


@dataclass
class Capture:
    """Результат знімка."""

    ok: bool
    path: str = ""
    width: int = 0
    height: int = 0
    detail: str = ""
    window: Optional[WindowInfo] = None

    def text(self) -> str:
        if not self.ok:
            return f"✗ {self.detail}"
        return (f"Скріншот {self.width}×{self.height}: {self.path}"
                + (f" · вікно {self.window.line()}" if self.window else ""))


def _save(path: Path, width: int, height: int, bgra: bytes) -> Capture:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(to_png(width, height, bgra))
    except OSError as exc:
        return Capture(False, detail=f"не вдалось зберегти: {exc}")
    return Capture(True, path=str(path), width=width, height=height)


def capture_window(info: WindowInfo, path: Path) -> Capture:
    """Зняти конкретне вікно (навіть перекрите)."""
    if not IS_WINDOWS:
        return Capture(False, detail="скріншоти працюють лише на Windows")
    width, height = info.width, info.height
    if width < 8 or height < 8:
        return Capture(False, detail=f"вікно має нульовий розмір ({width}×{height})")
    raw = _grab(info.hwnd, width, height, use_print_window=True)
    if raw is None or _looks_blank(raw):
        # Другий шлях: копіювання з екрана за прямокутником вікна.
        rect = None
        try:
            box = wintypes.RECT()
            if _user32.GetWindowRect(int(info.hwnd), ctypes.byref(box)):
                rect = (box.left, box.top, box.right, box.bottom)
        except Exception:  # noqa: BLE001
            rect = None
        raw = _grab(info.hwnd, width, height, screen_rect=rect,
                    use_print_window=False)
    if raw is None:
        return Capture(False, detail="Win32 не повернув зображення")
    if _looks_blank(raw):
        return Capture(False, detail="вікно порожнє (не домалювалось або приховане)")
    result = _save(path, width, height, raw)
    result.window = info
    return result


def capture_screen(path: Path, rect: Optional[tuple[int, int, int, int]] = None,
                   *, hwnd: int = 0) -> Capture:
    """Зняти весь екран (або прямокутник / вікно через BitBlt).

    ``rect`` — ``(left, top, right, bottom)`` у пікселях екрана.

    УВАЖНО: саме права/нижня межа, а не ширина/висота. Раніше виклики з
    ``(x, y, width, height)`` мовчки давали знімок не того розміру:
    ``capture_region(100, 100, 300, 200)`` повертав область 200×100
    (``right-left = 300-100``, ``bottom-top = 200-100``). Це не помічалось,
    бо інструмент рапортував «успішно», а координати в ньому — ті самі
    числа, що передали. Тепер виклики, які мають на увазі розмір, зобов'язані
    перевести його в межі (:func:`rect_from_size`).
    """
    if not IS_WINDOWS or not _user32:
        return Capture(False, detail="скріншоти працюють лише на Windows")
    if rect:
        left, top, right, bottom = rect
        width, height = max(1, right - left), max(1, bottom - top)
    else:
        width = _user32.GetSystemMetrics(0)
        height = _user32.GetSystemMetrics(1)
    raw = _grab(hwnd, width, height, screen_rect=rect or (0, 0, width, height),
                use_print_window=False)
    if raw is None:
        return Capture(False, detail="Win32 не повернув зображення екрана")
    return _save(path, width, height, raw)


def rect_from_size(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Перевести «x, y, ширина, висота» у межі ``(left, top, right, bottom)``.

    Саме цю функцію мають викликати інструменти: людина (і модель) думає
    розміром області, а Win32 — межами. Без явного перетворення помилка
    непомітна: знімок виходить, просто іншого розміру.
    """
    left, top = int(x), int(y)
    return (left, top, left + max(0, int(width)), top + max(0, int(height)))


def shrink_png(width: int, height: int, bgra: bytes, *, step: int = 2) -> tuple[int, int, bytes]:
    """Зменшити зображення вдвічі-вчетверо (без бібліотек).

    Потрібно для передачі моделі: base64 від 4K-скріншота — це понад
    10 МБ у запиті, і локальний сервер його не приймає. Усереднюємо
    блоки ``step × step`` пікселів — якість для оцінки вигляду сторінки
    цілком достатня, а розмір падає в ``step²`` разів.
    """
    if step < 2 or width < 4 or height < 4:
        return width, height, bgra
    out_w = max(1, width // step)
    out_h = max(1, height // step)
    out = bytearray(out_w * out_h * 4)
    area = step * step
    for row in range(out_h):
        src_y = row * step
        dst_row = row * out_w * 4
        for col in range(out_w):
            src_x = col * step
            b = g = r = a = 0
            for dy in range(step):
                base = ((src_y + dy) * width + src_x) * 4
                for dx in range(step):
                    index = base + dx * 4
                    b += bgra[index]
                    g += bgra[index + 1]
                    r += bgra[index + 2]
                    a += bgra[index + 3]
            target = dst_row + col * 4
            out[target] = b // area
            out[target + 1] = g // area
            out[target + 2] = r // area
            out[target + 3] = a // area
    return out_w, out_h, bytes(out)


def reduce_png(raw: bytes, *, target_mb: float = 2.0) -> bytes:
    """Зменшити PNG-файл у пам'яті до заданого розміру.

    Декодує PNG власним кодом (zlib), усереднює пікселі й кодує назад.
    Потрібно, щоб відправити моделі скріншот 4K: без зменшення запит
    виходить на 10+ МБ, і сервер відповідає помилкою.
    """
    decoded = decode_png(raw)
    if decoded is None:
        return raw
    width, height, bgra = decoded
    result = raw
    step = 2
    while step <= 8:
        new_w, new_h, pixels = shrink_png(width, height, bgra, step=step)
        encoded = to_png(new_w, new_h, pixels)
        if len(encoded) / (1024 ** 2) <= target_mb:
            return encoded
        result = encoded
        step += 1
    return result


def decode_png(raw: bytes) -> Optional[tuple[int, int, bytes]]:
    """Розкодувати PNG (8 біт, RGB/RGBA, без інтерлейсу) у BGRA.

    Підтримуємо саме те, що створюємо самі (``to_png``) і що віддає
    Win32-захоплення. Для складніших PNG повертаємо ``None`` — тоді
    викликач використає файл як є.
    """
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    position = 8
    width = height = 0
    bit_depth = color_type = 0
    idat = bytearray()
    try:
        while position + 8 <= len(raw):
            length = struct.unpack(">I", raw[position:position + 4])[0]
            tag = raw[position + 4:position + 8]
            data = raw[position + 8:position + 8 + length]
            position += 12 + length
            if tag == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(
                    ">IIBB", data[:10])
            elif tag == b"IDAT":
                idat.extend(data)
            elif tag == b"IEND":
                break
    except (struct.error, IndexError):
        return None
    if bit_depth != 8 or color_type not in (2, 6) or not idat:
        return None
    try:
        plain = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    if len(plain) < height * (stride + 1):
        return None
    out = bytearray(width * height * 4)
    previous = bytearray(stride)
    offset = 0
    for row in range(height):
        filter_type = plain[offset]
        offset += 1
        line = bytearray(plain[offset:offset + stride])
        offset += stride
        # Знімаємо фільтр рядка (стандартні 5 типів PNG).
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - up_left
                pa, pb, pc = abs(estimate - left), abs(estimate - up), \
                    abs(estimate - up_left)
                predictor = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else up_left)
                line[index] = (line[index] + predictor) & 0xFF
        previous = line
        target = row * width * 4
        for column in range(width):
            source = column * channels
            out[target + column * 4] = line[source + 2]      # B
            out[target + column * 4 + 1] = line[source + 1]  # G
            out[target + column * 4 + 2] = line[source]      # R
            out[target + column * 4 + 3] = (
                line[source + 3] if channels == 4 else 255)
    return width, height, bytes(out)


def shrink_png_file(source: Path, target: Path, *, limit_mb: float = 2.0) -> bool:
    """Зменшити PNG-файл на диску (для передачі моделі)."""
    try:
        raw = Path(source).read_bytes()
    except OSError:
        return False
    if len(raw) / (1024 ** 2) <= limit_mb:
        return False
    reduced = reduce_png(raw, target_mb=limit_mb)
    if reduced == raw:
        return False
    try:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(reduced)
    except OSError:
        return False
    return True


__all__ = [
    "Capture",
    "WindowInfo",
    "capture_screen",
    "capture_window",
    "decode_png",
    "find_windows",
    "iter_windows",
    "reduce_png",
    "shrink_png",
    "shrink_png_file",
    "to_png",
]
