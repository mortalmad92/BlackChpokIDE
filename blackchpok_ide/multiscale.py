"""Багатомасштабний аналіз скріншотів: огляд + перекривні ділянки.

Навіщо. Повноекранний знімок 3440×1440 після стискання до ліміту запиту
втрачає дрібний текст: модель бачить «щось схоже на панель», але не читає
написів і починає ВИГАДУВАТИ. Перевірено: на зображенні 800×552 модель
читала дрібний український текст бездоганно, а на 3440×1440 — ні.

Рішення: не зменшувати все зображення, а різати ОРИГІНАЛ на ділянки, кожна
з яких за розміром близька до «зручної» для моделі. Кожна ділянка
зберігається окремим файлом із ТОЧНИМИ координатами відносно оригіналу.

Ключові принципи:

1. **Ріжемо з оригіналу**, а не зі зменшеної копії — інакше дрібний текст
   втрачається ще до нарізання.
2. **Перекриття** між ділянками, щоб елемент на межі не розрізався навпіл.
3. **Координати** кожної ділянки зберігаються в системі ОРИГІНАЛУ.
4. **Пропорції не спотворюються**: масштаб по X і Y однаковий.
5. Модель може сказати «не розібрав» — і це нормальна відповідь.

Модуль не залежить від tkinter і не робить мережевих викликів.
"""

from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

LOG = logging.getLogger("blackchpok.multiscale")

#: Ширина/висота ділянки, зручна для моделі.
#:
#: 1024 — компроміс: дрібний текст інтерфейсу лишається читабельним, а
#: кількість ділянок для 3440×1440 не перевищує ~12, тобто аналіз не
#: перетворюється на десятки запитів.
TILE_SIZE = 1024
#: Перекриття між сусідніми ділянками (частка від TILE_SIZE).
OVERLAP = 0.18
#: Максимум ділянок, щоб аналіз лишався практичним.
MAX_TILES = 16
#: Менше цього — окрема ділянка не потрібна.
MIN_TILE = 64


@dataclass
class Region:
    """Одна ділянка зображення з координатами в системі оригіналу."""

    path: str
    x: int
    y: int
    width: int
    height: int
    #: Людський підпис: де саме ця ділянка («лівий верх», «центр»).
    label: str = ""
    #: Чи це загальний огляд (зменшене ціле зображення).
    overview: bool = False
    #: Розмір ОРИГІНАЛУ, з якого вирізано ділянку.
    #:
    #: Потрібен для підпису: без нього ``region_caption`` писав «на
    #: оригіналі 1024×1024» (розмір самої ділянки), і модель вважала, що
    #: весь екран — це один квадрат 1024×1024.
    origin_width: int = 0
    origin_height: int = 0

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def describe(self) -> str:
        kind = "огляд" if self.overview else "ділянка"
        return (f"{kind} {self.width}×{self.height} "
                f"@ ({self.x},{self.y})–({self.x + self.width},{self.y + self.height})"
                + (f" · {self.label}" if self.label else ""))

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "x": self.x, "y": self.y,
                "width": self.width, "height": self.height,
                "label": self.label, "overview": self.overview,
                "origin_width": self.origin_width,
                "origin_height": self.origin_height}


@dataclass
class Plan:
    """План аналізу: загальний огляд + ділянки."""

    source: str = ""
    width: int = 0
    height: int = 0
    overview: Optional[Region] = None
    tiles: list[Region] = field(default_factory=list)
    note: str = ""

    @property
    def regions(self) -> list[Region]:
        return ([self.overview] if self.overview else []) + list(self.tiles)

    def summary(self) -> str:
        if not self.tiles:
            return f"{self.width}×{self.height}: одного кадру досить"
        return (f"{self.width}×{self.height}: огляд + {len(self.tiles)} ділянок "
                f"(по {TILE_SIZE}px, перекриття {int(OVERLAP * 100)}%)")


# ─────────────────────────────────────────────────────────────────────────────
# Читання PNG без сторонніх бібліотек
# ─────────────────────────────────────────────────────────────────────────────

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: Path | str) -> tuple[int, int, bytearray]:
    """Прочитати PNG у RGB-буфер ``(width, height, pixels)``.

    Підтримує 8-бітні truecolor (RGB/RGBA) із фільтрами 0–4. Саме такий
    формат пишемо самі (:func:`screenshot.to_png`) і саме його віддають
    знімки Windows. Інтерлейс не підтримується — для скріншотів він не
    використовується.
    """
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("не PNG-файл")
    pos = len(PNG_SIGNATURE)
    width = height = 0
    bit_depth = color_type = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", body[:10])
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
    if not width or not height:
        raise ValueError("пошкоджений IHDR")
    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError(f"непідтримуваний формат PNG: depth={bit_depth}, "
                         f"color={color_type}")
    channels = 3 if color_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(width * height * 3)
    previous = bytearray(stride)
    offset = 0
    for row in range(height):
        if offset >= len(raw):
            break
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        if filter_type == 1:            # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:          # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:          # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:          # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up_left = previous[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(left, previous[i], up_left)) & 0xFF
        previous = line
        base = row * width * 3
        if channels == 3:
            out[base:base + width * 3] = line
        else:
            for col in range(width):
                src = col * 4
                dst = base + col * 3
                out[dst] = line[src]
                out[dst + 1] = line[src + 1]
                out[dst + 2] = line[src + 2]
    return width, height, out


def write_png(path: Path | str, width: int, height: int, rgb: bytes) -> Path:
    """Записати RGB-буфер у PNG (власний кодер, без Pillow)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)                   # фільтр «none» — швидко й без втрат
        raw.extend(rgb[row * stride:(row + 1) * stride])

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    target.write_bytes(PNG_SIGNATURE + chunk(b"IHDR", header)
                       + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                       + chunk(b"IEND", b""))
    return target


def crop_rgb(rgb: bytes, width: int, height: int,
             box: tuple[int, int, int, int]) -> tuple[int, int, bytes]:
    """Вирізати прямокутник з ОРИГІНАЛУ (без масштабування)."""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    w, h = max(0, x1 - x0), max(0, y1 - y0)
    if w <= 0 or h <= 0:
        return 0, 0, b""
    stride = width * 3
    out = bytearray(w * h * 3)
    for row in range(h):
        src = (y0 + row) * stride + x0 * 3
        dst = row * w * 3
        out[dst:dst + w * 3] = rgb[src:src + w * 3]
    return w, h, bytes(out)


def resize_rgb(rgb: bytes, width: int, height: int,
               target_w: int, target_h: int) -> tuple[int, int, bytes]:
    """Зменшити зображення у цілу кількість разів (box-average).

    Використовується ЛИШЕ для загального огляду. Ділянки для детального
    читання ніколи не проходять через цю функцію.
    """
    target_w = max(1, int(target_w))
    target_h = max(1, int(target_h))
    if target_w >= width and target_h >= height:
        return width, height, rgb
    out = bytearray(target_w * target_h * 3)
    x_ratio = width / target_w
    y_ratio = height / target_h
    stride = width * 3
    for ty in range(target_h):
        y0 = int(ty * y_ratio)
        y1 = max(y0 + 1, int((ty + 1) * y_ratio))
        for tx in range(target_w):
            x0 = int(tx * x_ratio)
            x1 = max(x0 + 1, int((tx + 1) * x_ratio))
            r = g = b = 0
            count = 0
            for sy in range(y0, min(y1, height)):
                base = sy * stride
                for sx in range(x0, min(x1, width)):
                    index = base + sx * 3
                    r += rgb[index]
                    g += rgb[index + 1]
                    b += rgb[index + 2]
                    count += 1
            index = (ty * target_w + tx) * 3
            if count:
                out[index] = r // count
                out[index + 1] = g // count
                out[index + 2] = b // count
    return target_w, target_h, bytes(out)


# ─────────────────────────────────────────────────────────────────────────────
# Планування ділянок
# ─────────────────────────────────────────────────────────────────────────────

def _label_for(x: int, y: int, width: int, height: int,
               box: tuple[int, int, int, int] | None = None) -> str:
    """Людський підпис ділянки за її положенням на ОРИГІНАЛІ.

    Рахуємо за ЦЕНТРОМ ділянки, а не за її лівим верхнім кутом: раніше
    нижня ділянка з координатою ``y=416`` на зображенні 1440 px отримувала
    підпис «лівий верх» (бо 416 < 1440/3), і модель шукала вміст не там.
    Тепер підпис відповідає тому, де ділянка справді лежить.
    """
    horizontal = ("лівий", "центр", "правий")
    vertical = ("верх", "середина", "низ")
    if box is not None:
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
    else:
        cx = x + width / 2
        cy = y + height / 2
    col = 0 if cx < width / 3 else (2 if cx > 2 * width / 3 else 1)
    row = 0 if cy < height / 3 else (2 if cy > 2 * height / 3 else 1)
    return f"{horizontal[col]} {vertical[row]}" if row != 1 else f"{horizontal[col]} центр"


def tile_boxes(width: int, height: int, *,
               size: int = TILE_SIZE, overlap: float = OVERLAP,
               limit: int = MAX_TILES) -> list[tuple[int, int, int, int]]:
    """Порахувати прямокутники ділянок із перекриттям.

    Ділянки ріжуться з оригіналу за координатами, тому жодного
    масштабування немає: роздільна здатність зберігається повністю.
    """
    if width <= size and height <= size:
        return []
    step = max(MIN_TILE, int(size * (1.0 - overlap)))
    xs: list[int] = []
    x = 0
    while x < width:
        xs.append(min(x, max(0, width - size)))
        if x + size >= width:
            break
        x += step
    ys: list[int] = []
    y = 0
    while y < height:
        ys.append(min(y, max(0, height - size)))
        if y + size >= height:
            break
        y += step
    boxes: list[tuple[int, int, int, int]] = []
    for y in ys:
        for x in xs:
            boxes.append((x, y, min(width, x + size), min(height, y + size)))
    # Забагато ділянок — збільшуємо крок (менше запитів до моделі).
    while len(boxes) > limit:
        step_adjusted = int(step * 1.35) + 1
        if step_adjusted >= width and step_adjusted >= height:
            break
        xs2: list[int] = []
        x = 0
        while x < width:
            xs2.append(min(x, max(0, width - size)))
            if x + size >= width:
                break
            x += step_adjusted
        ys2: list[int] = []
        y = 0
        while y < height:
            ys2.append(min(y, max(0, height - size)))
            if y + size >= height:
                break
            y += step_adjusted
        boxes = [(x, y, min(width, x + size), min(height, y + size))
                 for y in ys2 for x in xs2]
        step = step_adjusted
    return boxes


def prepare(path: Path | str, *, out_dir: Path | str | None = None,
            size: int = TILE_SIZE) -> Plan:
    """Підготувати план аналізу й нарізати ділянки з оригіналу.

    Повертає :class:`Plan` із загальним оглядом (зменшеним) і ділянками
    (повна роздільна здатність). Усі координати — в системі оригіналу.
    """
    source = Path(path)
    plan = Plan(source=str(source))
    try:
        width, height, rgb = read_png(source)
    except (OSError, ValueError, zlib.error) as exc:
        plan.note = f"не вдалось прочитати зображення: {exc}"
        LOG.info("Multi-scale недоступний: %s", plan.note)
        return plan
    plan.width, plan.height = width, height

    folder = Path(out_dir) if out_dir else source.parent / f"{source.stem}-tiles"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        plan.note = "не вдалось створити теку для ділянок"
        return plan

    # Загальний огляд: зменшене ЦІЛЕ зображення, щоб модель зрозуміла композицію.
    longest = max(width, height)
    if longest > 1400:
        scale = 1400 / longest
        ow, oh, small = resize_rgb(rgb, width, height,
                                   int(width * scale), int(height * scale))
    else:
        ow, oh, small = width, height, rgb
    try:
        overview_path = write_png(folder / "overview.png", ow, oh, small)
        plan.overview = Region(str(overview_path), 0, 0, width, height,
                               label="загальний огляд", overview=True,
                               origin_width=width, origin_height=height)
    except OSError as exc:
        plan.note = f"огляд не збережено: {exc}"

    boxes = tile_boxes(width, height, size=size)
    for index, box in enumerate(boxes, start=1):
        cw, ch, data = crop_rgb(rgb, width, height, box)
        if cw < MIN_TILE or ch < MIN_TILE:
            continue
        target = folder / f"tile-{index:02d}.png"
        try:
            write_png(target, cw, ch, data)
        except OSError as exc:
            LOG.debug("Ділянку не збережено: %s", exc)
            continue
        plan.tiles.append(Region(
            str(target), box[0], box[1], cw, ch,
            label=_label_for(box[0], box[1], width, height, box=box),
            origin_width=width, origin_height=height))
    if not plan.tiles and not plan.overview:
        plan.note = "зображення завелике, а ділянки не створились"
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Підказки для моделі
# ─────────────────────────────────────────────────────────────────────────────

#: Інструкція, яка забороняє вигадувати нерозбірливий текст.
UNCERTAINTY_RULE = (
    "Якщо напис або елемент нечитабельні — напиши «не розібрано» і вкажи, "
    "де саме. НЕ вигадуй текст, якого не видно. Краще визнати, що не видно, "
    "ніж припустити."
)


def region_caption(region: Region, *, total: int = 0, index: int = 0) -> str:
    """Підпис до ділянки: модель мусить знати, ЗВІДКИ це зображення."""
    position = f"ділянка {index} з {total}" if total else "ділянка"
    original = (f"на оригіналі {region.origin_width}×{region.origin_height}px"
                if region.origin_width and region.origin_height
                else "координати — у пікселях ОРИГІНАЛУ")
    return (f"[{position}] {region.label}: прямокутник "
            f"x={region.x}..{region.x + region.width}, "
            f"y={region.y}..{region.y + region.height} "
            f"{original}. "
            + UNCERTAINTY_RULE)


def merge_report(parts: Iterable[dict[str, Any]]) -> str:
    """Зібрати звіт із відповідей по ділянках із прив'язкою до координат.

    Це крок F у схемі multi-scale аналізу: відповіді моделі по кожній
    ділянці об'єднуються в один звіт, і кожен фрагмент зберігає свої
    координати на ОРИГІНАЛІ — інакше «десь на екрані» неможливо
    перевести назад у конкретний елемент інтерфейсу.
    """
    lines: list[str] = []
    unreadable: list[str] = []
    for item in parts:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        where = item.get("label") or "ділянка"
        box = item.get("box")
        place = (f" @ ({box[0]},{box[1]})–({box[2]},{box[3]})"
                 if isinstance(box, (list, tuple)) and len(box) == 4 else "")
        lines.append(f"### {where}{place}\n{text}")
        # Явне «не розібрано» від моделі — це теж результат, і в підсумку
        # він мусить бути окремо: інакше невпевненість губиться між
        # упевненими описами й виглядає як повне розуміння екрана.
        lowered = text.lower()
        if any(marker in lowered for marker in ("не розібрано", "не вдалося",
                                                "нечитабельн", "не розібрав")):
            unreadable.append(f"{where}{place}")
    if unreadable:
        lines.append("\n**Нерозбірливі ділянки (за словами моделі):** "
                     + "; ".join(unreadable))
    return "\n\n".join(lines)


__all__ = [
    "MAX_TILES",
    "MIN_TILE",
    "OVERLAP",
    "Plan",
    "Region",
    "TILE_SIZE",
    "UNCERTAINTY_RULE",
    "crop_rgb",
    "merge_report",
    "prepare",
    "read_png",
    "region_caption",
    "resize_rgb",
    "tile_boxes",
    "write_png",
]
