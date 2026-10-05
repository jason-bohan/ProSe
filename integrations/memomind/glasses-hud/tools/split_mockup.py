#!/usr/bin/env python3
"""Splits a 2x2 expression mockup into icons/{happy,neutral,upset,dazed}.png.

Usage: python tools/split_mockup.py path/to/mockup.png

Takes the largest alpha-connected shape in each quadrant (dropping stray
specks and the transparent background), fits it into an exact 32x24 RGBA
canvas without distorting the aspect ratio, and writes the four icon PNGs
that tools/png_to_gmp_icon.py consumes. Rerun png_to_gmp_icon.py after.
"""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image

ICON_WIDTH = 32
ICON_HEIGHT = 24
QUADRANT_NAMES = ("happy", "neutral", "upset", "dazed")

HERE = Path(__file__).resolve().parent
ICONS_DIR = HERE.parent / "icons"


def largest_blob_bbox(mask: list[list[bool]]) -> tuple[int, int, int, int] | None:
    height = len(mask)
    width = len(mask[0])
    seen = [[False] * width for _ in range(height)]
    best: tuple[int, int, int, int] | None = None
    best_count = 0
    for start_y in range(height):
        for start_x in range(width):
            if not mask[start_y][start_x] or seen[start_y][start_x]:
                continue
            seen[start_y][start_x] = True
            queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
            count = 0
            min_x = start_x
            max_x = start_x
            min_y = start_y
            max_y = start_y
            while queue:
                x, y = queue.popleft()
                count += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if (
                        0 <= nx < width
                        and 0 <= ny < height
                        and mask[ny][nx]
                        and not seen[ny][nx]
                    ):
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            if count > best_count:
                best_count = count
                best = (min_x, min_y, max_x, max_y)
    return best


def fit_to_canvas(icon: Image.Image) -> Image.Image:
    scale = min(ICON_WIDTH / icon.width, ICON_HEIGHT / icon.height)
    new_width = max(1, round(icon.width * scale))
    new_height = max(1, round(icon.height * scale))
    resized = icon.resize((new_width, new_height), Image.LANCZOS)
    canvas = Image.new("RGBA", (ICON_WIDTH, ICON_HEIGHT), (0, 0, 0, 0))
    canvas.paste(resized, ((ICON_WIDTH - new_width) // 2, (ICON_HEIGHT - new_height) // 2))
    return canvas


def split_quadrant(image: Image.Image, x0: int, y0: int) -> Image.Image:
    width = image.width // 2
    height = image.height // 2
    region = image.crop((x0, y0, x0 + width, y0 + height))
    alpha = region.getchannel("A")
    mask = [[alpha.getpixel((x, y)) > 0 for x in range(width)] for y in range(height)]
    bbox = largest_blob_bbox(mask)
    if bbox is None:
        raise ValueError(f"no icon found in quadrant at ({x0},{y0})")
    return region.crop((bbox[0], bbox[1], bbox[2] + 1, bbox[3] + 1))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/split_mockup.py path/to/mockup.png")
    source = Path(sys.argv[1])
    image = Image.open(source).convert("RGBA")
    if image.width < 64 or image.height < 64:
        raise SystemExit(f"{source} is too small to contain four icons")
    half_width = image.width // 2
    half_height = image.height // 2
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    origins = ((0, 0), (half_width, 0), (0, half_height), (half_width, half_height))
    for name, (x0, y0) in zip(QUADRANT_NAMES, origins, strict=True):
        icon = fit_to_canvas(split_quadrant(image, x0, y0))
        path = ICONS_DIR / f"{name}.png"
        icon.save(path)
        print(f"Wrote {path} ({ICON_WIDTH}x{ICON_HEIGHT})")


if __name__ == "__main__":
    main()
