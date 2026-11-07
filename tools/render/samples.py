#!/usr/bin/env python3
"""Make the sample prints in docs/images with the integration's real code.

Each picture goes through render -> to_rows -> back to dots, so it shows the exact bits that would be sent to the
printer. Nothing here is drawn by hand. Run from the repository root: python3 tools/render/samples.py
"""
import importlib.util
import sys
import types
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "custom_components" / "iprint"
_pkg = types.ModuleType("iprint")
_pkg.__path__ = [str(PKG)]
sys.modules["iprint"] = _pkg
for name in ("const", "protocol", "render"):
    spec = importlib.util.spec_from_file_location(f"iprint.{name}", PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"iprint.{name}"] = module
    spec.loader.exec_module(module)

from iprint.protocol import BYTES_PER_ROW, WIDTH_DOTS  # noqa: E402
from iprint.render import render_image, render_text, to_rows  # noqa: E402

OUT = ROOT / "docs" / "images"
PAPER = (247, 244, 236)
INK = (38, 38, 42)


def dots(image: Image.Image) -> Image.Image:
    """What the printer receives, turned back into a picture: 1 = black, high bit = leftmost dot."""
    rows, count = to_rows(image)
    out = Image.new("L", (WIDTH_DOTS, count), 255)
    pixels = out.load()
    for y in range(count):
        for x in range(WIDTH_DOTS):
            if rows[y * BYTES_PER_ROW + x // 8] & (0x80 >> (x % 8)):
                pixels[x, y] = 0
    return out


def on_paper(image: Image.Image, scale: int = 2) -> Image.Image:
    """Put the dots on thermal paper with a torn edge and a soft shadow, on a transparent background."""
    ink = dots(image).resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    margin, tail = 16 * scale, 18 * scale
    width, height = ink.width + 2 * margin, ink.height + 2 * margin + tail
    paper = Image.new("RGB", (width, height), PAPER)
    paper.paste(Image.new("RGB", ink.size, INK), (margin, margin), ink.point(lambda v: 255 - v))
    mask = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(mask)
    tooth = 8 * scale
    for x in range(0, width, tooth):
        draw.polygon([(x, height), (x + tooth / 2, height - tooth * 0.6), (x + tooth, height)], fill=0)
    pad = 28
    canvas = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 70), (pad, pad + 6), mask)
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(10)))
    canvas.paste(paper, (pad, pad), mask)
    return canvas


def photo_demo() -> Image.Image:
    """A synthetic test picture for the dither: smooth gradients show it better than any photo could."""
    size = 384
    image = Image.new("L", (size, 240))
    pixels = image.load()
    for y in range(240):
        for x in range(size):
            dx, dy = (x - 192) / 192, (y - 120) / 120
            pixels[x, y] = int(255 * max(0.0, min(1.0, 0.5 + 0.5 * dx - 0.35 * (dx * dx + dy * dy) + 0.2 * dy)))
    return image


SAMPLES = {
    "receipt": render_text("No app. No cloud. No ads.\n\n☐ Milk\n☐ Eggs\n☐ Butter\n☐ Coffee\n☑ Thermal paper\n\n"
                           "Printed by Home Assistant", title="Shopping"),
    "morning": render_text("Mon, 20 °C, light rain\n\n08:30 Dentist\n15:00 Pick up parcel\n19:00 Football\n\n"
                           "Bins: paper goes out\nDishwasher: done\nFront door: locked", title="Good morning!"),
    "alert": render_text("Leak sensor, cellar\n03:12\n\nWater detected.\nMain valve closed.", title="⚠ WATER"),
    "label": render_text("Tomato sauce\nbest before 03/2027", title="Pantry", size=30),
    "dither": render_image(photo_demo()),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, image in SAMPLES.items():
        on_paper(image).save(OUT / f"print-{name}.png", optimize=True)
        print(name, image.size)
    # Texture for the 3D render: the plain dots, no shadow.
    ROOT.joinpath("tools/render/build").mkdir(parents=True, exist_ok=True)
    dots(SAMPLES["receipt"]).save(ROOT / "tools/render/build/receipt_dots.png")


if __name__ == "__main__":
    main()
