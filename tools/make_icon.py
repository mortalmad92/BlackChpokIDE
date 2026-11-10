"""Створити assets/icon.ico для застосунку (без зовнішніх файлів).

Запуск: python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "assets" / "icon.ico"


def make_icon(size: int = 256) -> "object":
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # темне коло-фон
    margin = int(size * 0.03)
    draw.ellipse((margin, margin, size - margin, size - margin), fill=(30, 30, 30, 255))

    # акцентна рамка
    ring = int(size * 0.055)
    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        outline=(0, 122, 204, 255),
        width=ring,
    )

    # стилізовані дужки коду
    stroke = max(6, int(size * 0.055))
    left = [
        (int(size * 0.40), int(size * 0.30)),
        (int(size * 0.27), int(size * 0.50)),
        (int(size * 0.40), int(size * 0.70)),
    ]
    right = [
        (int(size * 0.60), int(size * 0.30)),
        (int(size * 0.73), int(size * 0.50)),
        (int(size * 0.60), int(size * 0.70)),
    ]
    for points in (left, right):
        draw.line(points, fill=(212, 212, 212, 255), width=stroke, joint="curve")

    # крапка-курсор
    dot = int(size * 0.06)
    draw.ellipse(
        (size // 2 - dot, size // 2 - dot, size // 2 + dot, size // 2 + dot),
        fill=(0, 122, 204, 255),
    )
    return image


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Потрібен Pillow: pip install pillow", file=sys.stderr)
        return 1
    image = make_icon(256)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    image.save(TARGET, format="ICO", sizes=sizes)
    # PNG-версія для документації
    image.save(TARGET.with_suffix(".png"), format="PNG")
    print(f"готово: {TARGET} ({TARGET.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
