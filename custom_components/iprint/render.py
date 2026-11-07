"""Turn text and pictures into the 1-bit rows the printer takes."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .protocol import BYTES_PER_ROW, MAX_ROWS, WIDTH_DOTS

MARGIN = 4
# Pillow's built-in font has no umlauts, no ß and no €: they print as boxes. Measured against its .notdef glyph.
FONT_PATH = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"


@lru_cache(maxsize=8)
def get_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def to_rows(image: Image.Image) -> tuple[bytes, int]:
    """1 bit per dot, leftmost dot in the high bit, 1 = black. PIL's mode "1" is the inverse."""
    if image.width != WIDTH_DOTS:
        raise ValueError(f"image must be {WIDTH_DOTS} dots wide, not {image.width}")
    if image.height > MAX_ROWS:
        raise ValueError(f"too long: {image.height} rows, limit {MAX_ROWS}")
    rows = bytes(b ^ 0xFF for b in image.convert("1", dither=Image.Dither.NONE).tobytes())
    if len(rows) != BYTES_PER_ROW * image.height:
        raise ValueError("unexpected row layout")
    return rows, image.height


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if font.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while font.getlength(word) > width:  # a single word wider than the paper
                cut = len(word) - 1
                while cut > 1 and font.getlength(word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def render_text(text: str, title: str | None = None, size: int = 28) -> Image.Image:
    """Word-wrapped text, with an optional title half as large again. Long enough for the text, no longer."""
    if not text.strip() and not (title and title.strip()):
        raise ValueError("nothing to print")
    usable = WIDTH_DOTS - 2 * MARGIN
    blocks: list[tuple[ImageFont.FreeTypeFont, list[str]]] = []
    if title and title.strip():
        font = get_font(int(size * 1.5))
        blocks.append((font, _wrap(title, font, usable)))
    if text.strip():
        font = get_font(size)
        blocks.append((font, _wrap(text, font, usable)))
    height = sum(round(font.size * 1.25) * len(lines) for font, lines in blocks) + 2 * MARGIN
    if height > MAX_ROWS:
        raise ValueError(f"too long: {height} rows, limit {MAX_ROWS}")
    image = Image.new("1", (WIDTH_DOTS, height), 1)
    draw = ImageDraw.Draw(image)
    y = MARGIN
    for font, lines in blocks:
        step = round(font.size * 1.25)
        for line in lines:
            draw.text((MARGIN, y), line, font=font, fill=0)
            y += step
    return image


def render_image(image: Image.Image) -> Image.Image:
    """Scale to the paper width, keep the aspect ratio, dither. Honours the EXIF orientation of photos."""
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        white = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(white, image)
    grey = image.convert("L")
    height = max(1, round(grey.height * WIDTH_DOTS / grey.width))
    if height > MAX_ROWS:
        raise ValueError(f"too long: {height} rows, limit {MAX_ROWS}")
    return grey.resize((WIDTH_DOTS, height), Image.Resampling.LANCZOS).convert("1", dither=Image.Dither.FLOYDSTEINBERG)
