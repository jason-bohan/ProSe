#!/usr/bin/env python3
"""Offline visual check of plugin.c's parametric faces -- no hardware needed.

Ports face_render/mood_face_params/boxer_face_params from ../plugin.c
line-for-line (integer math, C toward-zero division) and renders a contact
sheet to face_preview.png next to this script. KEEP THE PORT IN SYNC when
editing the C recipes, then rerun: python tools/face_preview.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

FACE_W, FACE_H = 32, 24
ROW_BYTES = FACE_W // 2
PIXEL_OFFSET = 64
DATA_SIZE = PIXEL_OFFSET + ROW_BYTES * FACE_H
SHADE, SHADE_DIM = 14, 9


def trunc(a: int, b: int) -> int:  # C integer division: toward zero
    q = abs(a) // abs(b)
    return q if a * b >= 0 else -q


def set_pixel(buf: bytearray, x: int, y: int, shade: int) -> None:
    if x < 0 or x >= FACE_W or y < 0 or y >= FACE_H:
        return
    index = PIXEL_OFFSET + y * ROW_BYTES + (x >> 1)
    if x & 1:
        buf[index] = (buf[index] & 0xF0) | (shade & 0x0F)
    else:
        buf[index] = (buf[index] & 0x0F) | ((shade & 0x0F) << 4)


def fill_rect(buf, x0, y0, w, h, shade):
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            set_pixel(buf, x, y, shade)


def line(buf, x0, y0, x1, y1, shade):
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        set_pixel(buf, x0, y0, shade)
        if x0 == x1 and y0 == y1:
            break
        twice = 2 * err
        if twice > -dy:
            err -= dy
            x0 += sx
        if twice < dx:
            err += dx
            y0 += sy


def ring(buf, cx, cy, radius, shade):
    inner, outer = (radius - 1) ** 2, (radius + 1) ** 2
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            d = (x - cx) ** 2 + (y - cy) ** 2
            if inner <= d <= outer:
                set_pixel(buf, x, y, shade)


DAZED_WAVE = [0, 1, 2, 2, 1, 0, -1, -2, -2, -1, 0, 1, 2, 2, 1, 0, -1, -2, -2, -1, 0]


def face_render(buf: bytearray, p: dict) -> None:
    for i in range(PIXEL_OFFSET, DATA_SIZE):
        buf[i] = 0
    if p["dazed"]:
        ring(buf, 10, 8, 2, SHADE)
        ring(buf, 22, 8, 2, SHADE)
        set_pixel(buf, 10, 8, SHADE_DIM)
        set_pixel(buf, 22, 8, SHADE_DIM)
        for x in range(21):
            set_pixel(buf, 6 + x, 18 + DAZED_WAVE[x], SHADE)
            set_pixel(buf, 6 + x, 19 + DAZED_WAVE[x], SHADE)
        return
    eye_height = 1 + p["eye_open"] * 5 // 255
    eye_top = 8 - eye_height // 2
    fill_rect(buf, 8, eye_top, 4, eye_height, SHADE)
    fill_rect(buf, 20, eye_top, 4, eye_height, SHADE)
    if p["brow_tilt"] <= -40:
        line(buf, 7, 3, 14, 6, SHADE_DIM)
        line(buf, 25, 3, 18, 6, SHADE_DIM)
    elif p["brow_tilt"] >= 40:
        line(buf, 7, 6, 14, 3, SHADE_DIM)
        line(buf, 25, 6, 18, 3, SHADE_DIM)
    if p["mouth_open"] >= 90:
        half_w = 3 + p["mouth_open"] // 20
        half_h = 1 + p["mouth_open"] // 45
        fill_rect(buf, 16 - half_w, 17 - half_h, half_w * 2, half_h * 2, SHADE)
    else:
        amp = trunc(p["mouth_curve"] * 4, 127)
        for x in range(6, 27):
            t = x - 16
            y = 18 + trunc(amp * (100 - t * t), 100)
            set_pixel(buf, x, y, SHADE)
            set_pixel(buf, x, y + 1, SHADE)


def mood_face_params(label: int, intensity: int) -> dict:
    p = dict(mouth_curve=0, mouth_open=0, eye_open=205, brow_tilt=0, dazed=0)
    if label == 0:
        p["mouth_curve"] = 45
    elif label == 1:
        p["mouth_curve"] = 95
    elif label == 2:
        p["mouth_curve"], p["brow_tilt"], p["mouth_open"] = -40, 50, 35
    elif label == 3:
        p["mouth_curve"], p["brow_tilt"], p["mouth_open"] = -10, -45, 25
    elif label == 4:
        p["mouth_curve"], p["brow_tilt"] = -70, -95
        p["mouth_open"] = 30 + intensity * 30
    p["mouth_open"] = min(p["mouth_open"], 200)
    return p


def boxer_face_params(momentum: int) -> dict:
    p = dict(mouth_curve=trunc((momentum - 50) * 5, 4), mouth_open=0,
             eye_open=210, brow_tilt=0, dazed=0)
    if momentum >= 65:
        p["eye_open"] = 245
        p["mouth_curve"] += 30
    elif momentum <= 35:
        p["dazed"], p["eye_open"], p["mouth_curve"] = 1, 150, 0
    return p


def to_image(buf: bytearray, scale: int = 6) -> Image.Image:
    img = Image.new("RGBA", (FACE_W, FACE_H), (0, 0, 0, 0))
    px = img.load()
    for y in range(FACE_H):
        for x in range(FACE_W):
            i = PIXEL_OFFSET + y * ROW_BYTES + (x >> 1)
            shade = buf[i] & 0x0F if x & 1 else buf[i] >> 4
            if shade:
                v = shade * 17
                px[x, y] = (v, v, v, 255)
    return img.resize((FACE_W * scale, FACE_H * scale), Image.NEAREST)


MOODS = [("calm", 0, 1), ("confident", 1, 3), ("tense", 2, 3),
         ("defensive", 3, 3), ("frustrated", 4, 5), ("neutral", 5, 0)]
cells = []
for name, label, intensity in MOODS:
    buf = bytearray(DATA_SIZE)
    face_render(buf, mood_face_params(label, intensity))
    cells.append((f"mood {name} {intensity}/5", buf))
for m in (80, 50, 20):
    buf = bytearray(DATA_SIZE)
    face_render(buf, boxer_face_params(m))
    cells.append((f"boxer mom={m}", buf))
blink = mood_face_params(1, 3)
blink["eye_open"] = 0
buf = bytearray(DATA_SIZE)
face_render(buf, blink)
cells.append(("confident BLINK", buf))

CELL_W, CELL_H, PAD, LABEL_H = 32 * 6, 24 * 6, 10, 16
cols = 5
rows = (len(cells) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (CELL_W + PAD) + PAD,
                          rows * (CELL_H + LABEL_H + PAD) + PAD), (14, 14, 16))
draw = ImageDraw.Draw(sheet)
for i, (label, buf) in enumerate(cells):
    cx = PAD + (i % cols) * (CELL_W + PAD)
    cy = PAD + (i // cols) * (CELL_H + LABEL_H + PAD)
    cell = Image.new("RGBA", (CELL_W, CELL_H), (30, 30, 34, 255))
    cell.alpha_composite(to_image(buf), (0, 0))
    sheet.paste(cell.convert("RGB"), (cx, cy))
    draw.text((cx + 2, cy + CELL_H + 2), label, fill=(250, 180, 19))
out = str(Path(__file__).resolve().parent / "face_preview.png")
sheet.save(out)
print("wrote", out)
