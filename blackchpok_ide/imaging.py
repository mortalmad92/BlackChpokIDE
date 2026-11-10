"""Візуальні інструменти: захоплення, обрізання, метадані, порівняння.

Модуль дає моделі змогу працювати із зображеннями як з ДАНИМИ: дізнатися
розміри, вирізати область, порахувати різницю між двома знімками, побачити
ділянки великого скріншота.

Головний принцип: жоден із цих інструментів не «описує» зображення словами
замість моделі. Вони повертають ФАКТИ (розміри, координати, шляхи, числа
різниці), а розуміння вмісту лишається за моделлю, яка отримує зображення
через ``image_url``.

Історія: усі створені артефакти записуються у ``history.json`` поруч із
знімками, щоб можна було знайти «той самий кадр» через кілька кроків.

Модуль не залежить від tkinter.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import multiscale

LOG = logging.getLogger("blackchpok.imaging")

#: Скільки записів історії тримаємо.
HISTORY_LIMIT = 200

#: Скільки PNG-файлів тримаємо на диску (типово).
SHOTS_KEEP = 60

#: Скільки годин знімок вважається потрібним, навіть якщо він старий.
SHOTS_KEEP_HOURS = 24.0


# ─────────────────────────────────────────────────────────────────────────────
# Теки та історія
# ─────────────────────────────────────────────────────────────────────────────

def shots_dir() -> Path:
    """Тека для знімків та похідних зображень."""
    from .config import app_data_dir

    target = app_data_dir() / "screenshots"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return target


def history_path() -> Path:
    return shots_dir() / "history.json"


def load_history() -> list[dict[str, Any]]:
    try:
        data = json.loads(history_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def record(kind: str, path: Path | str, **extra: Any) -> None:
    """Записати артефакт в історію (не ламаючи роботу при збої).

    Після запису прибираємо застарілі знімки: саме тут найкраще знати, що
    щойно створений файл ПОТРІБЕН (він у ``protect``), а все інше можна
    прибирати за правилами :func:`cleanup_shots`.
    """
    entries = load_history()
    entries.append({
        "kind": str(kind),
        "path": str(path),
        "time": time.time(),
        "stamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        **extra,
    })
    try:
        history_path().write_text(
            json.dumps(entries[-HISTORY_LIMIT:], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        LOG.debug("Історію знімків не записано", exc_info=True)
    # Останні кілька артефактів лишаємо завжди: агент щойно їх створив і
    # може використати на наступному кроці.
    protect = [str(item.get("path") or "") for item in entries[-10:]]
    protect.append(str(path))
    try:
        cleanup_shots(protect=protect)
    except Exception:  # noqa: BLE001 - прибирання не має ламати знімок
        LOG.debug("Прибирання знімків не вдалось", exc_info=True)


def recent(limit: int = 10) -> list[dict[str, Any]]:
    return load_history()[-max(1, int(limit)):]


# ─────────────────────────────────────────────────────────────────────────────
# Прибирання старих знімків
# ─────────────────────────────────────────────────────────────────────────────

def cleanup_shots(*, keep: int = SHOTS_KEEP, keep_hours: float = SHOTS_KEEP_HOURS,
                  protect: Optional[list[str]] = None) -> dict[str, int]:
    """Прибрати застарілі PNG-знімки, не чіпаючи потрібних.

    Навіщо. Кожен ``capture_screen``/``web_screenshot`` створював новий
    PNG, і ніщо їх не прибирало. За тиждень роботи в теці накопичувались
    тисячі файлів на гігабайти — а знімок 4K, потрібний моделі, губився
    серед них.

    Правила (усі три мусять збігтися, щоб файл видалили):

    1. файл СТАРІШИЙ за ``keep_hours``;
    2. файл НЕ в останніх ``keep`` файлах теки (свіжі лишаються завжди);
    3. файл НЕ згаданий у ``protect`` (файли, які користувач чи агент щойно
       використали, лишаються навіть старими).

    Повертає ``{"removed": n, "bytes": n, "kept": n}`` — чесні числа для
    журналу, а не «ніби прибрано».
    """
    folder = shots_dir()
    guard = {str(item) for item in (protect or ()) if str(item or "").strip()}
    result = {"removed": 0, "bytes": 0, "kept": 0}
    try:
        files = [item for item in folder.glob("*.png") if item.is_file()]
    except OSError as exc:
        LOG.debug("Теку знімків не прочитано: %s", exc)
        return result
    if not files:
        return result
    # Найновіші — першими; їх не чіпаємо взагалі.
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=_mtime, reverse=True)
    newest = {str(item) for item in files[: max(0, int(keep))]}
    cutoff = time.time() - max(0.0, float(keep_hours)) * 3600.0
    for item in files:
        text = str(item)
        if text in newest or text in guard:
            result["kept"] += 1
            continue
        if _mtime(item) > cutoff:
            result["kept"] += 1
            continue
        try:
            size = item.stat().st_size
            item.unlink()
        except OSError as exc:
            LOG.debug("Знімок %s не прибрано: %s", item, exc)
            result["kept"] += 1
            continue
        result["removed"] += 1
        result["bytes"] += size
    if result["removed"]:
        LOG.info("Прибрано застарілих знімків: %s (%.1f МБ), лишилось %s",
                 result["removed"], result["bytes"] / (1024 ** 2),
                 result["kept"])
        _forget_missing()
    return result


def _forget_missing() -> None:
    """Прибрати з історії записи про файли, яких уже немає.

    Без цього ``list_screenshots`` показував «✗ файлу вже немає» на кожен
    прибраний кадр, і модель намагалась відкрити неіснуючий шлях.
    """
    entries = load_history()
    alive = [item for item in entries
             if item.get("kind") == "crop"
             or Path(str(item.get("path") or "")).exists()]
    if len(alive) == len(entries):
        return
    try:
        history_path().write_text(
            json.dumps(alive[-HISTORY_LIMIT:], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        LOG.debug("Історію знімків не оновлено", exc_info=True)


def same_path(first: str, second: str) -> bool:
    """Чи це той самий файл (Windows не розрізняє регістр у шляхах).

    Раніше ``get_screenshot_metadata`` порівнював рядки напряму, і той
    самий файл, записаний як ``…\\audit4\\big.png`` та ``…\\AUDIT4\\big.png``,
    вважався різними: історія «не знаходилась», хоч записи були.
    """
    if not first or not second:
        return False
    import os

    try:
        a = os.path.normcase(os.path.abspath(str(first)))
        b = os.path.normcase(os.path.abspath(str(second)))
    except (OSError, ValueError):
        return str(first).lower() == str(second).lower()
    return a == b


# ─────────────────────────────────────────────────────────────────────────────
# Метадані
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ImageInfo:
    """Те, що можна дізнатися про файл зображення без його «розуміння»."""

    path: str
    exists: bool = False
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    format: str = ""
    error: str = ""

    @property
    def megapixels(self) -> float:
        return round(self.width * self.height / 1_000_000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "exists": self.exists,
            "width": self.width, "height": self.height,
            "size_bytes": self.size_bytes, "size_kb": round(self.size_bytes / 1024, 1),
            "format": self.format, "megapixels": self.megapixels,
            "error": self.error,
        }

    def text(self) -> str:
        if not self.exists:
            return f"✗ файл не знайдено: {self.path}"
        if self.error:
            return f"✗ {self.error}: {self.path}"
        return (f"{self.path}\n  розмір: {self.width}×{self.height} px "
                f"({self.megapixels} Мп)\n  файл: {self.format}, "
                f"{self.size_bytes / 1024:.1f} КБ")


def image_info(path: Path | str) -> ImageInfo:
    """Прочитати розміри й формат зображення (заголовок файлу, без декодування)."""
    target = Path(path)
    info = ImageInfo(path=str(target))
    try:
        info.size_bytes = target.stat().st_size
    except OSError:
        return info
    info.exists = True
    try:
        head = target.read_bytes()[:32]
    except OSError as exc:
        info.error = str(exc)
        return info
    if head.startswith(multiscale.PNG_SIGNATURE):
        info.format = "PNG"
        if len(head) >= 24:
            info.width, info.height = struct_unpack(head[16:24])
        return info
    if head.startswith(b"\xff\xd8"):
        info.format = "JPEG"
        try:
            info.width, info.height = _jpeg_size(target)
        except (OSError, ValueError):
            info.error = "не вдалось прочитати розміри JPEG"
        return info
    if head.startswith(b"BM"):
        info.format = "BMP"
        try:
            raw = target.read_bytes()[:26]
            info.width = int.from_bytes(raw[18:22], "little", signed=True)
            info.height = abs(int.from_bytes(raw[22:26], "little", signed=True))
        except (OSError, ValueError, IndexError):
            info.error = "не вдалось прочитати розміри BMP"
        return info
    info.format = "невідомий"
    info.error = "формат не розпізнано (очікую PNG/JPEG/BMP)"
    return info


def struct_unpack(raw: bytes) -> tuple[int, int]:
    import struct

    width, height = struct.unpack(">II", raw)
    return int(width), int(height)


def _jpeg_size(path: Path) -> tuple[int, int]:
    """Знайти розміри JPEG у маркерах SOF (без сторонніх бібліотек)."""
    data = path.read_bytes()
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return width, height
        length = int.from_bytes(data[index + 2:index + 4], "big")
        index += 2 + max(2, length)
    raise ValueError("SOF не знайдено")


# ─────────────────────────────────────────────────────────────────────────────
# Обрізання
# ─────────────────────────────────────────────────────────────────────────────

def crop(path: Path | str, box: tuple[int, int, int, int],
         *, out_dir: Path | str | None = None, name: str = "") -> tuple[Optional[Path], str]:
    """Вирізати прямокутник з ОРИГІНАЛУ без масштабування.

    ``box`` — ``(x, y, width, height)`` у пікселях оригіналу.
    Повертає ``(шлях, людський підпис)``.
    """
    source = Path(path)
    info = image_info(source)
    if not info.exists:
        return None, f"✗ файл не знайдено: {source}"
    if info.format != "PNG":
        return None, (f"✗ обрізання підтримується для PNG (файл: {info.format}). "
                      f"Зроби новий знімок — він буде PNG.")
    try:
        width, height, rgb = multiscale.read_png(source)
    except (OSError, ValueError) as exc:
        return None, f"✗ не вдалось прочитати зображення: {exc}"
    x, y, w, h = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
    if w <= 0 or h <= 0:
        return None, f"✗ непридатний розмір області: {w}×{h}"
    x0 = max(0, min(x, width - 1))
    y0 = max(0, min(y, height - 1))
    x1 = min(width, x0 + w)
    y1 = min(height, y0 + h)
    cw, ch, data = multiscale.crop_rgb(rgb, width, height, (x0, y0, x1, y1))
    if cw <= 0 or ch <= 0:
        return None, "✗ область поза межами зображення"
    folder = Path(out_dir) if out_dir else source.parent
    label = name or f"{source.stem}-crop-{x0}_{y0}_{cw}x{ch}"
    target = folder / f"{label}.png"
    try:
        multiscale.write_png(target, cw, ch, data)
    except OSError as exc:
        return None, f"✗ не вдалось зберегти обрізане зображення: {exc}"
    record("crop", target, source=str(source),
           box=[x0, y0, x0 + cw, y0 + ch])
    note = (f"Обрізано {cw}×{ch} px @ ({x0},{y0}) з оригіналу "
            f"{width}×{height} (без масштабування)")
    if (x0, y0, cw, ch) != (x, y, w, h):
        note += f"; запитано ({x},{y}) {w}×{h} — обрізано до меж зображення"
    return target, f"{target}\n{note}"


# ─────────────────────────────────────────────────────────────────────────────
# Порівняння двох знімків
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Difference:
    """Числова різниця між двома зображеннями."""

    ok: bool = False
    width: int = 0
    height: int = 0
    changed_pixels: int = 0
    total_pixels: int = 0
    diff_path: str = ""
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    error: str = ""

    @property
    def percent(self) -> float:
        if not self.total_pixels:
            return 0.0
        return round(self.changed_pixels / self.total_pixels * 100, 2)

    def text(self) -> str:
        if not self.ok:
            return f"✗ {self.error}"
        if not self.changed_pixels:
            return f"Зображення ІДЕНТИЧНІ ({self.width}×{self.height}), змін 0%."
        lines = [
            f"Різниця: {self.percent}% пікселів змінено "
            f"({self.changed_pixels} з {self.total_pixels}), "
            f"розмір {self.width}×{self.height}.",
            f"Карта різниці: {self.diff_path}",
        ]
        if self.boxes:
            lines.append("Ділянки, де щось змінилось (x0,y0,x1,y1):")
            for box in self.boxes[:8]:
                lines.append(f"  • ({box[0]},{box[1]})–({box[2]},{box[3]})")
            if len(self.boxes) > 8:
                lines.append(f"  … і ще {len(self.boxes) - 8}")
        else:
            lines.append("Помітних скупчень змін не виділено — зміни розсіяні.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "width": self.width, "height": self.height,
                "changed_pixels": self.changed_pixels,
                "total_pixels": self.total_pixels, "percent": self.percent,
                "diff_path": self.diff_path, "boxes": self.boxes,
                "error": self.error}


def _cluster_boxes(changed: list[tuple[int, int]], width: int, height: int,
                   *, cell: int = 64) -> list[tuple[int, int, int, int]]:
    """Згрупувати змінені пікселі у прямокутники (проста сітка)."""
    if not changed:
        return []
    grid: dict[tuple[int, int], list[int]] = {}
    for x, y in changed:
        key = (x // cell, y // cell)
        box = grid.get(key)
        if box is None:
            grid[key] = [x, y, x, y]
        else:
            box[0] = min(box[0], x)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x)
            box[3] = max(box[3], y)
    boxes = [(b[0], b[1], b[2] + 1, b[3] + 1) for b in grid.values()]
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


def compare(first: Path | str, second: Path | str, *,
            threshold: int = 24, out_dir: Path | str | None = None) -> Difference:
    """Порахувати піксельну різницю між двома PNG.

    ``threshold`` — наскільки має відрізнятись канал, щоб піксель вважався
    зміненим. 24 дає змогу ігнорувати шум згладжування шрифтів.

    УВАЖНО: pixel diff — це допоміжна величина. Він показує ЛИШЕ «є зміни чи
    ні». Чи зміни правильні, вирішує модель, яка дивиться на зображення.
    """
    result = Difference()
    try:
        w1, h1, rgb1 = multiscale.read_png(first)
        w2, h2, rgb2 = multiscale.read_png(second)
    except (OSError, ValueError) as exc:
        result.error = f"не вдалось прочитати зображення: {exc}"
        return result
    if (w1, h1) != (w2, h2):
        result.error = (f"різні розміри: {w1}×{h1} проти {w2}×{h2}. "
                        f"Порівнювати можна лише однакові за розміром знімки.")
        return result
    result.width, result.height = w1, h1
    result.total_pixels = w1 * h1
    diff = bytearray(w1 * h1 * 3)
    changed: list[tuple[int, int]] = []
    for index in range(0, len(rgb1), 3):
        delta = (abs(rgb1[index] - rgb2[index])
                 + abs(rgb1[index + 1] - rgb2[index + 1])
                 + abs(rgb1[index + 2] - rgb2[index + 2]))
        if delta > threshold:
            pixel = index // 3
            changed.append((pixel % w1, pixel // w1))
            diff[index] = 255
            diff[index + 1] = 60
            diff[index + 2] = 60
        else:
            # Приглушене оригінальне зображення як тло.
            diff[index] = rgb1[index] // 3
            diff[index + 1] = rgb1[index + 1] // 3
            diff[index + 2] = rgb1[index + 2] // 3
    result.changed_pixels = len(changed)
    result.boxes = _cluster_boxes(changed, w1, h1)
    folder = Path(out_dir) if out_dir else Path(first).parent
    target = folder / f"diff-{Path(first).stem}-{Path(second).stem}.png"
    try:
        multiscale.write_png(target, w1, h1, bytes(diff))
        result.diff_path = str(target)
        record("diff", target, first=str(first), second=str(second),
               percent=result.percent)
    except OSError as exc:
        result.error = f"не вдалось зберегти карту різниці: {exc}"
        return result
    result.ok = True
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Multi-scale
# ─────────────────────────────────────────────────────────────────────────────

def inspect_regions(path: Path | str, *, out_dir: Path | str | None = None,
                    size: int = multiscale.TILE_SIZE) -> tuple[Optional[multiscale.Plan], str]:
    """Нарізати великий скріншот на перекривні ділянки з оригіналу.

    Повертає план і людський опис: скільки ділянок, які координати, де файли.
    """
    source = Path(path)
    if not source.exists():
        return None, f"✗ файл не знайдено: {source}"
    plan = multiscale.prepare(source, out_dir=out_dir, size=size)
    if plan.note and not plan.regions:
        return None, f"✗ {plan.note}"
    if not plan.tiles:
        detail = (f"Зображення {plan.width}×{plan.height} вміщається в одну "
                  f"ділянку {size}px — нарізання не потрібне. "
                  f"Аналізуй {plan.overview.path if plan.overview else source}.")
        return plan, detail
    lines = [f"Нарізано {len(plan.tiles)} ділянок по {size}px "
             f"(перекриття {int(multiscale.OVERLAP * 100)}%) "
             f"з оригіналу {plan.width}×{plan.height}:"]
    if plan.overview:
        lines.append(f"  • огляд: {plan.overview.path}")
    total = len(plan.tiles)
    for index, region in enumerate(plan.tiles, start=1):
        # Підпис дає моделі ЗВ'ЯЗОК «файл → прямокутник на оригіналі».
        # Без нього вона описує ділянку окремо й не може сказати, де саме
        # на екрані це було.
        lines.append(
            f"  {index}. {region.path} "
            f"@ ({region.x},{region.y})–({region.x + region.width},"
            f"{region.y + region.height})")
        lines.append("     " + multiscale.region_caption(
            region, total=total, index=index))
    lines.append(multiscale.UNCERTAINTY_RULE)
    record("tiles", source, count=len(plan.tiles),
           width=plan.width, height=plan.height)
    return plan, "\n".join(lines)


__all__ = [
    "Difference",
    "HISTORY_LIMIT",
    "ImageInfo",
    "SHOTS_KEEP",
    "SHOTS_KEEP_HOURS",
    "cleanup_shots",
    "compare",
    "crop",
    "history_path",
    "image_info",
    "inspect_regions",
    "load_history",
    "recent",
    "record",
    "same_path",
    "shots_dir",
]
