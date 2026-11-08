"""Decide whether a page stays readable at 48 mm, then make the dots.

Two independent checks, both on text found by OCR in the page as sent:

1. Size. A word's height after scaling, against the limit: 1.4 mm for paper held at 300 mm. That is 16 arc minutes,
   the usual minimum for reading (reading distance / 215). The T02 has 8 dots per mm, so 11 dots.
2. Read-back. OCR the final black-and-white dots. If it cannot find the words any more, neither will you.

A page counts as a picture, and always passes, when text is absent or covers very little of it: a photo of a street
with a shop sign is still a photo.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess

from PIL import Image, ImageChops, ImageOps

WIDTH_DOTS = 384
DOTS_PER_MM = 8
MAX_ROWS = 4000
PAGE_GAP = 24
MIN_WORD_DOTS = 11             # 1.4 mm, see above
MAX_SMALL_SHARE = 0.20         # some fine print is fine; a page of it is not
MIN_READ_BACK = 0.60
MIN_WORDS_FOR_TEXT = 5
MIN_TEXT_COVERAGE = 0.05
MIN_CONFIDENCE = 60
OCR_MIN_WIDTH = 1200
READ_BACK_SCALE = 4
OCR_LANGUAGES = "deu+eng"
OCR_TIMEOUT = 90


@dataclass
class Word:
    text: str
    height: int
    width: int


@dataclass
class Page:
    """A page's verdict. `reason` is one of "small", "unreadable", or empty."""
    dots: Image.Image | None
    is_text: bool
    words: int = 0
    small_share: float = 0.0
    median_mm: float = 0.0
    read_back: float = 1.0
    reason: str = ""


def ocr(image: Image.Image, timeout: int = OCR_TIMEOUT) -> list[Word]:
    """Words Tesseract is reasonably sure of. Raises when Tesseract itself fails: that must not pass as "no text"."""
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, "PNG")
    result = subprocess.run(["tesseract", "stdin", "stdout", "-l", OCR_LANGUAGES, "--psm", "3", "tsv"],
                            input=buffer.getvalue(), capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"tesseract failed: {result.stderr[:200]!r}")
    words = []
    for line in result.stdout.decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        try:
            confidence = float(cols[10])
            width, height = int(cols[8]), int(cols[9])
        except ValueError:
            continue
        if confidence >= MIN_CONFIDENCE and len(re.sub(r"\W", "", text)) >= 2:
            words.append(Word(text, height, width))
    return words


def trim(page: Image.Image) -> Image.Image:
    """Cut empty margins, so a small label on a big page fills the paper instead of being refused."""
    grey = page.convert("L")
    box = ImageChops.invert(grey).point(lambda v: 255 if v > 40 else 0).getbbox()
    if box is None:
        return grey
    pad = max(8, grey.width // 100)
    return grey.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(grey.width, box[2] + pad),
                      min(grey.height, box[3] + pad)))


def _normal(text: str) -> str:
    return re.sub(r"\W", "", text).lower()


def _overlap(found: list[Word], expected: list[Word]) -> float:
    if not expected:
        return 1.0
    available = {}
    for word in found:
        key = _normal(word.text)
        available[key] = available.get(key, 0) + 1
    hits = 0
    for word in expected:
        key = _normal(word.text)
        if available.get(key, 0) > 0:
            available[key] -= 1
            hits += 1
    return hits / len(expected)


def _scaled(image: Image.Image) -> Image.Image:
    height = max(1, round(image.height * WIDTH_DOTS / image.width))
    return image.resize((WIDTH_DOTS, height), Image.Resampling.LANCZOS)


def _as_text(image: Image.Image) -> Image.Image:
    """Dither turns small letters to mush; a plain threshold keeps their edges."""
    return ImageOps.autocontrast(_scaled(image), cutoff=1).point(lambda v: 255 if v > 150 else 0).convert("1")


def _as_picture(image: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(_scaled(image), cutoff=1).convert("1", dither=Image.Dither.FLOYDSTEINBERG)


def _text_verdict(image: Image.Image, words: list[Word], scale: float, turned: bool = False) -> Page:
    heights = sorted(word.height * scale for word in words)
    small = sum(1 for h in heights if h < MIN_WORD_DOTS) / len(heights)
    median = heights[len(heights) // 2] / DOTS_PER_MM
    page = Page(None, True, len(words), small, median)
    if small > MAX_SMALL_SHARE:
        page.reason = "small"
        return page
    dots = _as_text(image)
    big = dots.convert("L").resize((dots.width * READ_BACK_SCALE, dots.height * READ_BACK_SCALE),
                                   Image.Resampling.BICUBIC)
    if turned:  # OCR reads upright lines. A person turns the strip in the hand.
        big = big.rotate(-90, expand=True)
    page.read_back = _overlap(ocr(big), words)
    if page.read_back < MIN_READ_BACK:
        page.reason = "unreadable"
        return page
    page.dots = dots
    return page


def check_page(page: Image.Image) -> Page:
    """Upright first. A wide document gets a second chance turned sideways, where its letters come out larger."""
    trimmed = trim(page)
    probe = trimmed
    if probe.width < OCR_MIN_WIDTH:
        factor = OCR_MIN_WIDTH / probe.width
        probe = probe.resize((OCR_MIN_WIDTH, max(1, round(probe.height * factor))), Image.Resampling.LANCZOS)
    words = ocr(probe)
    coverage = sum(w.width * w.height for w in words) / max(1, probe.width * probe.height)
    if len(words) < MIN_WORDS_FOR_TEXT or coverage < MIN_TEXT_COVERAGE:
        sideways = trimmed.width > trimmed.height
        return Page(_as_picture(trimmed.rotate(90, expand=True) if sideways else trimmed), False, len(words))
    scale = WIDTH_DOTS / probe.width
    upright = _text_verdict(trimmed, words, scale)
    if upright.dots is not None or trimmed.width <= trimmed.height:
        return upright
    turned = trimmed.rotate(90, expand=True)
    sideways = _text_verdict(turned, words, WIDTH_DOTS / probe.height, turned=True)
    return sideways if sideways.dots is not None else upright


def assemble(pages: list[Page]) -> Image.Image:
    """All pages on one strip: one job, so nothing can come between them."""
    rows = sum(p.dots.height for p in pages) + PAGE_GAP * (len(pages) - 1)
    strip = Image.new("1", (WIDTH_DOTS, rows), 1)
    y = 0
    for page in pages:
        strip.paste(page.dots, (0, y))
        y += page.dots.height + PAGE_GAP
    return strip
