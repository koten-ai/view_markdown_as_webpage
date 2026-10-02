#!/usr/bin/env python3
"""Rasterize the Md mark into PNG, ICNS, and ICO."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "icons"
NAVY = (28, 39, 51, 255)
CYAN = (0, 180, 230, 255)
WHITE = (255, 255, 255, 255)
FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def pick_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def draw_mark(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), NAVY)
    draw = ImageDraw.Draw(img)
    inset = int(size * 0.18)
    radius = int(size * 0.14)
    box = (inset, inset, size - inset, size - inset)
    draw.rounded_rectangle(box, radius=radius, fill=CYAN)
    font = pick_font(max(12, int(size * 0.38)))
    text = "Md"
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    tw, th = x1 - x0, y1 - y0
    draw.text(((size - tw) / 2 - x0, (size - th) / 2 - y0 - size * 0.02), text, font=font, fill=WHITE)
    return img


def write_iconset(master: Image.Image, iconset: Path) -> None:
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    slots = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, px in slots.items():
        master.resize((px, px), Image.Resampling.LANCZOS).save(iconset / name, "PNG")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    master = draw_mark(1024)
    png = OUT / "app.png"
    master.save(png, "PNG")
    master.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "app-256.png", "PNG")
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(OUT / "app.ico", sizes=ico_sizes)
    iconset = OUT / "app.iconset"
    write_iconset(master, iconset)
    icns = OUT / "app.icns"
    iconutil = shutil.which("iconutil")
    if iconutil:
        subprocess.check_call([iconutil, "-c", "icns", str(iconset), "-o", str(icns)])
    else:
        try:
            master.save(icns)
        except Exception as err:
            print("icns not written (%s); PNG and ICO are ready" % err, file=sys.stderr)
    print("wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
