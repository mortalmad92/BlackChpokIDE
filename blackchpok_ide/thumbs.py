"""Малі іконки зображень: прев'ю прикріплених файлів у композері.

Навіщо окремий модуль. Донедавну смуга прикріплень показувала лише рядок
«🖼 shot.png»: користувач не бачив, ЩО саме він прикріпив. Прикріпити не
той скріншот було легко, а помітити це — лише після відповіді моделі.

Тепер кожне прикріплене зображення показується МАЛОЮ ІКОНКОЮ (як у
сучасних агентних редакторах). Правила прості й чесні:

1. **PNG і GIF** Tk декодує сам (``tk.PhotoImage``) — без залежностей, і
   для 4K-скриншота це швидко, бо декодує C-код Tk, а не Python.
2. **JPEG, WebP, BMP** Tk НЕ читає (перевірено на Tk 9.0.4: усі три дають
   ``couldn't recognize data in image file``). Для них потрібен Pillow —
   він у проєкті НЕобов'язковий (див. ``requirements.txt``). Якщо Pillow
   немає, модуль чесно повертає ``None``, і інтерфейс малює запасний
   значок 🖼 з іменем файлу замість вигаданої «картинки».
3. **PPM-трюк не працює**: ``tk.PhotoImage(data=…)`` приймає PNG-байти,
   але ``data=`` з PPM відхиляє («couldn't recognize image data»), тож
   конвертувати через власний кодер нема сенсу — тільки PNG.

Модуль не тягне tkinter на імпорті: ``tkinter`` і ``PIL`` підвантажуються
всередині функцій. Завдяки цьому його можна перевіряти тестом без вікна.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger("blackchpok.thumbs")

#: Сторона іконки в пікселях. 44 px читабельні на 150–200 % масштабі
#: Windows і не роблять смугу прикріплень вищою за рядок композера.
THUMB_PX = 44

#: Скільки іконок тримаємо в кеші панелі (більше — кеш чиститься).
CACHE_LIMIT = 64


def _suffix(path: Path) -> str:
    return path.suffix.lower()


def pillow_available() -> bool:
    """Чи встановлено Pillow (потрібен лише для JPEG/WebP/BMP)."""
    try:
        import PIL  # noqa: F401 - перевірка наявності
    except Exception:                                    # noqa: BLE001
        return False
    return True


def can_show(path: Path | str) -> bool:
    """Чи можна взагалі показати іконку цього файлу.

    Використовується інтерфейсом, щоб заздалегідь знати, малювати
    картинку чи запасний значок — без спроби декодування на кожен
    малюнок смуги.
    """
    target = Path(path)
    if _suffix(target) in (".png", ".gif"):
        return True
    if _suffix(target) in (".jpg", ".jpeg", ".webp", ".bmp"):
        return pillow_available()
    return False


def preview_png_bytes(path: Path | str, max_px: int = THUMB_PX) -> Optional[bytes]:
    """PNG-байти зменшеної копії — через Pillow, без tkinter.

    Потрібно для форматів, які Tk не читає. Повертає ``None``, якщо Pillow
    немає або файл пошкоджений: інтерфейс тоді покаже запасний значок, а
    не порожнє місце.
    """
    try:
        from PIL import Image
    except Exception:                                    # noqa: BLE001
        return None
    target = Path(path)
    try:
        with Image.open(target) as image:
            # RGBA — найбезпечніший режим: палітра, CMYK і 16-бітний PNG
            # конвертуються без втрати прозорості.
            copy = image.convert("RGBA")
            copy.thumbnail((max(1, int(max_px)), max(1, int(max_px))))
            buffer = io.BytesIO()
            copy.save(buffer, format="PNG")
    except (OSError, ValueError, MemoryError) as exc:
        LOG.debug("Мініатюру %s не створено: %s", target, exc)
        return None
    return buffer.getvalue()


def _fit_step(width: int, height: int, max_px: int) -> int:
    """У скільки разів зменшити (цілочисельно, без втрати якості)."""
    longest = max(int(width or 0), int(height or 0))
    limit = max(1, int(max_px))
    if longest <= limit:
        return 1
    # ``subsample`` приймає лише ціле: беремо найменший крок, за якого
    # результат усе ще більший за межу, і додаємо одиницю.
    return min(64, max(2, longest // limit + 1))


def _photo_from_tk(widget: Any, target: Path, max_px: int):
    """Завантажити PNG/GIF напряму через Tk (без Pillow)."""
    import tkinter as tk

    try:
        photo = tk.PhotoImage(master=widget, file=str(target))
    except tk.TclError as exc:
        LOG.debug("Tk не прочитав %s: %s", target, exc)
        return None
    step = _fit_step(photo.width(), photo.height(), max_px)
    if step <= 1:
        return photo
    try:
        return photo.subsample(step, step)
    except tk.TclError:
        return photo


def _photo_from_png_bytes(widget: Any, data: bytes):
    """``tk.PhotoImage`` з готових PNG-байтів."""
    import tkinter as tk

    try:
        return tk.PhotoImage(master=widget, data=data)
    except tk.TclError as exc:
        LOG.debug("Tk не прочитав PNG-байти: %s", exc)
        return None


def load(widget: Any, path: Path | str, *, max_px: int = THUMB_PX,
         cache: Optional[dict] = None):
    """``tk.PhotoImage`` з іконкою файлу (``None`` — показати значок).

    ``cache`` — словник панелі: ключ містить шлях і ``mtime``, тож
    перемальовування смуги не декодує той самий файл удруге. Кеш саме
    зовнішній, а не модульний: ``PhotoImage`` належить конкретному
    інтерпретатору Tk, і після ``destroy()`` глобальний кеш віддавав би
    «мертві» картинки (у тестах це виглядає як випадкове падіння).
    """
    target = Path(path)
    try:
        stamp = target.stat().st_mtime_ns
    except OSError:
        return None
    key = (str(target), stamp, int(max_px))
    if cache is not None and key in cache:
        return cache[key]
    photo = None
    if _suffix(target) in (".png", ".gif"):
        photo = _photo_from_tk(widget, target, max_px)
    if photo is None:
        data = preview_png_bytes(target, max_px)
        if data:
            photo = _photo_from_png_bytes(widget, data)
    if cache is not None and photo is not None:
        if len(cache) >= CACHE_LIMIT:
            cache.clear()
        cache[key] = photo
    return photo


__all__ = [
    "CACHE_LIMIT",
    "THUMB_PX",
    "can_show",
    "load",
    "pillow_available",
    "preview_png_bytes",
]
