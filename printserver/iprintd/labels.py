"""Shipping labels (beta). Carrier codes are never shrunk and never re-encoded.

A carrier label is about 100 mm wide, the T02 prints 48 mm. Shrinking the whole label makes Code 128 unreadable
(measured: every Code 128 failed at 0.18 mm per module). Re-encoding is no better: options the encoder does not know are
dropped without a word, and a GS1 code came out as plain Code 128 (measured 08.11.2026).

So each code is taken over from the source as it is: rendered again from the PDF, at a scale where one module is a
whole number of printer dots, at least as large as on the original label. A code wider than the paper is turned by 90°.
A MaxiCode keeps its fixed physical size. Last, every code is read back from the finished dots, after a simulated print,
and must give the same format, symbology identifier and bytes as the original. Otherwise the label is refused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
import pypdfium2
import zxingcpp

F = zxingcpp.BarcodeFormat
WIDTH_DOTS = 384
DOTS_PER_MM = 8
MAX_ROWS = 4000
FIND_DPI = 600
GAP = 24
PT_PER_MM = 72 / 25.4
LINEAR = {F.Code128, F.ITF, F.Code39, F.Code93, F.Codabar, F.EAN13, F.EAN8, F.UPCA}
# Smallest module this printer may use per format, in dots (8 dots = 1 mm). Codes are never made smaller than on the
# original either, so these only matter for sources without a physical size, such as a photo of a label.
MIN_DOTS = {"linear": 3, F.DataMatrix: 4, F.QRCode: 4, F.PDF417: 3, F.Aztec: 4}
MAXICODE_MM = 28.14            # fixed by the standard: 1.11 in, including its margin
QUIET_MODULES = 10             # Code 128 and ITF need ten modules of white on each side ...
QUIET_MM = 5                   # ... and carriers ask for more: DHL 5 mm to the edge, DPD 5 mm. Between two codes there
                               # are 5 + 3 + 5 = 13 mm, more than DHL's 7 and Hermes' 8 mm to a neighbouring code.
MIN_BAR_MM = 25                # DHL, DPD and Hermes: bars at least 25 mm tall
READ_BACK_BLUR = 2.2           # px at 3 px per dot: a worn head on sticker paper
CLUSTER_MM = 30                # codes closer than this belong to one label; a return PDF holds several parts
MARGIN_MM = 35                 # around a label's codes, where its addresses are
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class LabelError(ValueError):
    """The label cannot be printed so that it scans. `key` and `values` pick the message in messages.py."""

    def __init__(self, key: str, **values) -> None:
        super().__init__(f"{key} {values}" if values else key)
        self.key = key
        self.values = values


@dataclass
class Code:
    format: zxingcpp.BarcodeFormat
    identifier: str
    data: bytes
    text: str
    box: tuple[float, float, float, float]   # left, top, right, bottom in mm (in pixels for a picture)
    module_mm: float
    upright: bool = False                     # a linear code printed with vertical bars turned sideways
    orientation: int = 0                      # as the reader saw it, in degrees
    page: int = 0


@dataclass
class Part:
    """One slip: a label with several codes, or a single code with its identifier."""
    codes: list[Code]
    identifier: str = ""
    page: int = 0


@dataclass
class Label:
    dots: Image.Image
    codes: list[Code]
    parts: list[Part] = field(default_factory=list)
    slips: list[Image.Image] = field(default_factory=list)   # one per part: each is its own print job


def _key(code) -> tuple:
    return (code.format, code.symbology_identifier, bytes(code.bytes))


def _runs(line: np.ndarray) -> list[int]:
    """Lengths of equal runs along a line of 0/1 values."""
    edges = np.flatnonzero(np.diff(line)) + 1
    bounds = np.concatenate(([0], edges, [len(line)]))
    return list(np.diff(bounds))


def _module_px(region: np.ndarray, linear: bool) -> float:
    """The narrowest bar or space, measured on the symbol itself rather than assumed from an encoder."""
    dark = (region < 128).astype(np.int8)
    rows = [dark[dark.shape[0] // 2]] if linear else [dark[i] for i in np.linspace(0, dark.shape[0] - 1, 15).astype(int)]
    runs = []
    for row in rows:
        inner = np.flatnonzero(row)
        if inner.size == 0:
            continue
        runs += _runs(row[inner[0]:inner[-1] + 1])
    if not runs:
        raise LabelError("not_scanning", what="?")
    narrow = np.percentile(runs, 10)
    # Single modules, bars and spaces alike. Smoothing thins dark bars and widens light gaps by the same amount, so
    # their mean is right where the narrowest run alone came out 5 % small (0.356 for 0.375 mm, measured).
    singles = [r for r in runs if r < 1.6 * narrow]
    return float(np.mean(singles))


def _bar_extent(page: np.ndarray, x0: int, x1: int, y: int) -> tuple[int, int]:
    """A linear code is reported as a line. Find how far its bars reach up and down."""
    profile = page[y, x0:x1] < 128
    top = bottom = y
    while top > 0 and np.mean((page[top - 1, x0:x1] < 128) == profile) > 0.97:
        top -= 1
    while bottom < page.shape[0] - 1 and np.mean((page[bottom + 1, x0:x1] < 128) == profile) > 0.97:
        bottom += 1
    return top, bottom + 1


class Source:
    """A page to take codes from: a vector PDF page (rendered again at any scale) or a picture (resampled)."""

    def __init__(self, image: Image.Image, mm_per_px: float | None, page: pypdfium2.PdfPage | None = None) -> None:
        self.image = image.convert("L")
        self.mm_per_px = mm_per_px
        self.page = page

    def region(self, box_mm: tuple[float, float, float, float], dots_per_mm: float) -> Image.Image:
        left, top, right, bottom = box_mm
        if self.page is not None:
            height_pt = self.page.get_height()
            width_pt = self.page.get_width()
            crop = (left * PT_PER_MM, height_pt - bottom * PT_PER_MM, width_pt - right * PT_PER_MM, top * PT_PER_MM)
            scale = dots_per_mm / PT_PER_MM
            return self.page.render(scale=scale, grayscale=True, crop=crop).to_pil().convert("L")
        px = [round(v / (self.mm_per_px or 1.0)) for v in box_mm]
        part = self.image.crop(px)
        size = (max(1, round((right - left) * dots_per_mm)), max(1, round((bottom - top) * dots_per_mm)))
        return part.resize(size, Image.Resampling.BOX)


def sources(data: bytes) -> list[Source]:
    """Pages of a label file. PDF pages keep their vector codes; pictures get a size only from their codes."""
    if data[:5] == b"%PDF-":
        pdf = pypdfium2.PdfDocument(data)
        out = []
        for page in pdf:
            image = page.render(scale=FIND_DPI / 72, grayscale=True).to_pil()
            out.append(Source(image, 25.4 / FIND_DPI, page))
        return out
    from io import BytesIO

    try:
        with Image.open(BytesIO(data)) as picture:
            picture.load()
            picture = ImageOps.exif_transpose(picture)
            return [Source(picture, None)]
    except (OSError, Image.DecompressionBombError) as err:
        raise LabelError("broken") from err


def _bullseyes(grey: np.ndarray) -> list[tuple[int, int, float]]:
    """Centres of MaxiCode finder patterns: a light core, then five rings of equal width on each side.

    The reader only decodes a MaxiCode that stands alone in the picture, so on a whole label it finds none (measured).
    Returns (x, y, ring width in px).
    """
    dark = grey < 128
    found = []

    def hits(lines, horizontal):
        for index in range(0, lines.shape[0], 2):
            line = lines[index]
            edges = np.flatnonzero(np.diff(line.astype(np.int8))) + 1
            if len(edges) < 12:
                continue
            bounds = np.concatenate(([0], edges, [len(line)]))
            runs = np.diff(bounds)
            values = line[bounds[:-1]]
            for i in range(5, len(runs) - 5):
                if values[i]:   # the core is light
                    continue
                rings = np.concatenate((runs[i - 5:i], runs[i + 1:i + 6]))
                width = np.median(rings)
                if width < 3 or np.any(np.abs(rings - width) > 0.35 * width):
                    continue
                if not values[i - 1] or not 0.9 * width <= runs[i] <= 2.4 * width:
                    continue
                centre = (bounds[i] + bounds[i + 1]) // 2
                yield (centre, index, float(width)) if horizontal else (index, centre, float(width))

    def round_rings(x: int, y: int, width: float) -> bool:
        """Rings are round: along both diagonals the same light core and three dark rings appear at the same radii.
        Square modules of the same width pass across and down too, and on a diagonal they come out sqrt(2) wider: a
        QR code with 0.75 mm modules fooled a looser check (measured 08.11.2026). So eight more directions, tight."""
        for angle in (22.5, 45, 67.5, 112.5, 135, 157.5, 202.5, 225, 247.5, 292.5, 315, 337.5):
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            samples = []
            for i in range(int(width * 7)):
                px, py = int(round(x + dx * i)), int(round(y + dy * i))
                if not (0 <= px < dark.shape[1] and 0 <= py < dark.shape[0]):
                    return False
                samples.append(bool(dark[py, px]))
            # expected: light core (about 1 ring wide from the centre), then dark, light, dark, light, dark
            runs, value, count = [], samples[0], 0
            for s in samples:
                if s == value:
                    count += 1
                else:
                    runs.append((value, count))
                    value, count = s, 1
            runs.append((value, count))
            if len(runs) < 6 or runs[0][0] or [v for v, _ in runs[1:6]] != [True, False, True, False, True]:
                return False
            if any(abs(n - width) > 0.25 * width for _, n in runs[1:5]):
                return False
        return True

    rows = list(hits(dark, True))
    cols = list(hits(dark.T, False))
    for x, y, width in rows:
        if any(abs(x - cx) <= width and abs(y - cy) <= width for cx, cy, _ in cols) and round_rings(x, y, width):
            if not any(abs(x - fx) <= 4 * width and abs(y - fy) <= 4 * width for fx, fy, _ in found):
                found.append((x, y, width))
    return found


def read_all(image: Image.Image) -> list:
    """Every code in a picture, MaxiCode included. A MaxiCode that is there but does not read raises LabelError."""
    hits = [hit for hit in zxingcpp.read_barcodes(image) if hit.valid]
    grey = np.array(image.convert("L"))
    for x, y, ring in _bullseyes(grey):
        # The symbol is about 38.6 ring widths across. The reader wants it alone, so try a tight cut first:
        # a wide one can catch a neighbouring code (measured on a finished strip).
        got, box = [], None
        for factor in (20.5, 22, 24):
            half = round(ring * factor)
            box = (max(0, x - half), max(0, y - half), min(grey.shape[1], x + half), min(grey.shape[0], y + half))
            got = [h for h in zxingcpp.read_barcodes(image.crop(box), formats=F.MaxiCode) if h.valid]
            if got:
                break
        if not got:
            raise LabelError("maxicode")
        hits.append((got[0], box))
    return hits


TILE_MM, TILE_STEP_MM = 40, 20


def _tiles(source: Source) -> list:
    """The reader misses codes on a whole page: a small DataMatrix on a real DHL label (08.11.2026) only showed up on
    a piece of the page. So the page is also read in overlapping tiles. Returns hits with their tile offset."""
    mm_per_px = source.mm_per_px
    size = round(TILE_MM / mm_per_px) if mm_per_px else 600
    step = round(TILE_STEP_MM / mm_per_px) if mm_per_px else 300
    width, height = source.image.size
    out = []
    for y in range(0, max(1, height - step), step):
        for x in range(0, max(1, width - step), step):
            crop = source.image.crop((x, y, min(width, x + size), min(height, y + size)))
            out += [(hit, x, y) for hit in zxingcpp.read_barcodes(crop) if hit.valid]
    return out


class _Shifted:
    """A hit from a tile, with its position moved into page coordinates."""

    class _P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    class _Pos:
        pass

    def __init__(self, hit, dx: int, dy: int) -> None:
        self._hit = hit
        pos = self._Pos()
        for name in ("top_left", "top_right", "bottom_right", "bottom_left"):
            point = getattr(hit.position, name)
            setattr(pos, name, self._P(point.x + dx, point.y + dy))
        self.position = pos

    def __getattr__(self, name):
        return getattr(self._hit, name)


def find_codes(source: Source) -> list[Code]:
    found, seen = [], set()
    grey = np.array(source.image)
    # no physical size for a picture: work in source pixels and let MIN_DOTS decide the size
    mm_per_px = source.mm_per_px or 1.0
    items = list(read_all(source.image))

    def spot(hit) -> tuple[float, float]:
        points = [hit.position.top_left, hit.position.bottom_right]
        return (sum(p.x for p in points) / 2, sum(p.y for p in points) / 2)

    placed = [(_key(i[0] if isinstance(i, tuple) else i), spot(i[0] if isinstance(i, tuple) else i)) for i in items]
    near_px = 10 / (source.mm_per_px or 0.1)
    for hit, dx, dy in _tiles(source):
        if hit.format == F.MaxiCode:
            continue
        shifted = _Shifted(hit, dx, dy)
        here = spot(shifted)
        # the same code at the same spot was found already; the same code somewhere else is a repeat the document
        # has to know about (a real DHL label carries its DataMatrix twice)
        if any(key == _key(hit) and math.dist(here, there) < near_px for key, there in placed):
            continue
        placed.append((_key(hit), here))
        items.append(shifted)
    kept: list[tuple] = []
    for item in items:
        if isinstance(item, tuple):   # a MaxiCode, located by its finder pattern
            hit, (bx0, by0, bx1, by1) = item
            if _key(hit) in seen:
                continue
            seen.add(_key(hit))
            points = [hit.position.top_left, hit.position.top_right, hit.position.bottom_right, hit.position.bottom_left]
            xs, ys = [bx0 + p.x for p in points], [by0 + p.y for p in points]
            found.append(Code(hit.format, hit.symbology_identifier, bytes(hit.bytes), hit.text,
                              (min(xs) * mm_per_px, min(ys) * mm_per_px, (max(xs) + 1) * mm_per_px,
                               (max(ys) + 1) * mm_per_px), 0.0, orientation=hit.orientation))
            continue
        hit = item
        # The same code at the same spot is one code found twice. The same code elsewhere is a repeat on the page (a
        # real DHL label carries its DataMatrix twice): it goes through, and analyze() keeps it as a double so the
        # overview blanks it too. Judged by content alone, the repeat was lost and showed up shrunk in the overview.
        if not hit.valid or any(key == _key(hit) and math.dist(spot(hit), there) < near_px for key, there in kept):
            continue
        kept.append((_key(hit), spot(hit)))
        seen.add(_key(hit))
        points = [hit.position.top_left, hit.position.top_right, hit.position.bottom_right, hit.position.bottom_left]
        xs, ys = [p.x for p in points], [p.y for p in points]
        x0, x1 = max(0, min(xs)), min(grey.shape[1], max(xs) + 1)
        y0, y1 = max(0, min(ys)), min(grey.shape[0], max(ys) + 1)
        linear = hit.format in LINEAR
        angle = abs(hit.orientation) % 180
        sideways = abs(angle - 90) <= 3
        if min(angle, 180 - angle) > 3 and not sideways and hit.format != F.MaxiCode:
            raise LabelError("angle")
        if linear and not sideways:
            y0, y1 = _bar_extent(grey, x0, x1, (y0 + y1) // 2)
        elif linear:
            x0, x1 = (lambda t: (t[0], t[1]))(_bar_extent(grey.T, y0, y1, (x0 + x1) // 2))
        region = grey[y0:y1, x0:x1]
        if sideways:
            region = region.T
        module = _module_px(region, linear) * mm_per_px
        found.append(Code(hit.format, hit.symbology_identifier, bytes(hit.bytes), hit.text,
                          (x0 * mm_per_px, y0 * mm_per_px, x1 * mm_per_px, y1 * mm_per_px), module,
                          linear and sideways, hit.orientation))
    return found


def _dots_per_module(code: Code, has_size: bool) -> int:
    if not has_size:
        return MIN_DOTS["linear"] if code.format in LINEAR else MIN_DOTS.get(code.format, 4)
    # As large as on the original, rounded up to whole dots (a hair below counts as equal: 8.0 for 0.998 mm), and at
    # least 2 dots. Not the carriers' 0.375 mm: DHL itself printed 0.325 and 0.227 mm on a real return label
    # (08.11.2026), and blowing those up made the label 60 cm long.
    return max(2, math.ceil(code.module_mm * DOTS_PER_MM - 0.15))


def take_over(source: Source, code: Code) -> Image.Image:
    """The code alone, from the source, at whole dots per module, with white quiet zones, turned if too wide."""
    has_size = source.mm_per_px is not None
    if code.format == F.MaxiCode:
        width_mm = code.box[2] - code.box[0]
        dots_per_mm = DOTS_PER_MM * (MAXICODE_MM / width_mm if not has_size else 1.0)
        if has_size and abs(width_mm - MAXICODE_MM) > 4:
            dots_per_mm = DOTS_PER_MM * MAXICODE_MM / width_mm   # scaled on the page: back to its fixed size
    else:
        dots_per_mm = _dots_per_module(code, has_size) / code.module_mm
    image = source.region(code.box, dots_per_mm).point(lambda v: 0 if v < 128 else 255)
    if code.upright:
        image = image.rotate(90, expand=True)   # bars vertical again, so the quiet zones go left and right
    if code.format in LINEAR and image.height < MIN_BAR_MM * DOTS_PER_MM:
        # Bars are the same all the way down, so stretching them loses nothing. Happens after "fit to page".
        image = image.resize((image.width, MIN_BAR_MM * DOTS_PER_MM), Image.Resampling.NEAREST)
    module = max(1, round(code.module_mm * dots_per_mm))
    quiet = max(module * QUIET_MODULES, QUIET_MM * DOTS_PER_MM) if code.format in LINEAR else module * 2
    if code.format == F.MaxiCode:
        quiet = 2 * DOTS_PER_MM   # the standard asks for one hexagon (about 1 mm); a reader looking for it alone likes more
    canvas = Image.new("L", (image.width + 2 * quiet, image.height + 2 * (quiet if code.format not in LINEAR else module * 2)), 255)
    canvas.paste(image, (quiet, (canvas.height - image.height) // 2))
    if canvas.width > WIDTH_DOTS:
        canvas = canvas.rotate(90, expand=True)
    if canvas.width > WIDTH_DOTS:
        raise LabelError("too_large", what=code.format.name)
    return canvas


def _gap(a: Code, b: Code) -> float:
    dx = max(0.0, max(a.box[0], b.box[0]) - min(a.box[2], b.box[2]))
    dy = max(0.0, max(a.box[1], b.box[1]) - min(a.box[3], b.box[3]))
    return math.hypot(dx, dy)


def group(codes: list[Code]) -> list[list[Code]]:
    """Codes close together form one part. In reading order: by page, then top to bottom."""
    parts: list[list[Code]] = []
    for code in codes:
        near = [part for part in parts if any(c.page == code.page and _gap(c, code) <= CLUSTER_MM for c in part)]
        merged = [code] + [c for part in near for c in part]
        parts = [part for part in parts if part not in near] + [merged]
    for part in parts:
        part.sort(key=lambda c: (c.box[1], c.box[0]))
    return sorted(parts, key=lambda part: (part[0].page, min(c.box[1] for c in part), min(c.box[0] for c in part)))


def _region(part: list[Code], others: list[list[Code]], page_mm: tuple[float, float]) -> tuple[float, ...]:
    """The part's codes plus a margin for addresses, but never more than halfway to another part."""
    left = min(c.box[0] for c in part) - MARGIN_MM
    top = min(c.box[1] for c in part) - MARGIN_MM
    right = max(c.box[2] for c in part) + MARGIN_MM
    bottom = max(c.box[3] for c in part) + MARGIN_MM
    box = [min(c.box[0] for c in part), min(c.box[1] for c in part), max(c.box[2] for c in part), max(c.box[3] for c in part)]
    for other in others:
        if other is part or other[0].page != part[0].page:
            continue
        o = (min(c.box[0] for c in other), min(c.box[1] for c in other), max(c.box[2] for c in other),
             max(c.box[3] for c in other))
        if o[2] <= box[0]:
            left = max(left, (o[2] + box[0]) / 2)
        elif o[0] >= box[2]:
            right = min(right, (o[0] + box[2]) / 2)
        elif o[3] <= box[1]:
            top = max(top, (o[3] + box[1]) / 2)
        elif o[1] >= box[3]:
            bottom = min(bottom, (o[1] + box[3]) / 2)
    return (max(0.0, left), max(0.0, top), min(page_mm[0], right), min(page_mm[1], bottom))


def _text_turn(source: Source, region: tuple[float, ...] | None) -> int | None:
    """How the text in a region is turned, from the PDF's text objects: 0, 90, 180 or 270 degrees. None for pictures."""
    if source.page is None:
        return None
    import pypdfium2.raw as raw

    height = source.page.get_height()
    angles = []
    for obj in source.page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
        left, bottom, right, top = obj.get_pos()
        x, y = (left + right) / 2 / PT_PER_MM, (height - (bottom + top) / 2) / PT_PER_MM
        if region is not None and not (region[0] <= x <= region[2] and region[1] <= y <= region[3]):
            continue
        m = obj.get_matrix()
        angles.append(round(math.degrees(math.atan2(m.b, m.a)) / 90) % 4 * 90)
    return max(set(angles), key=angles.count) if angles else None


def overview(source: Source, codes: list[Code], region: tuple[float, ...] | None = None) -> Image.Image:
    """The rest of the label for people: addresses and routing text, upright, scaled to the paper, codes blanked out."""
    image = source.image.copy()
    draw = ImageDraw.Draw(image)
    mm_per_px = source.mm_per_px or 1.0
    for code in codes:
        draw.rectangle([round(v / mm_per_px) for v in code.box], fill=255)
    if region is not None:
        image = image.crop([round(v / mm_per_px) for v in region])
    # A label laid sideways on the page (as in a return PDF) is turned so its text reads normally. The text layer
    # says how; the codes' orientation is only the fallback for pictures (it got the direction wrong once).
    turn = _text_turn(source, region)
    if turn is None:
        turns = [c.orientation for c in codes if c.format in LINEAR] or [c.orientation for c in codes]
        turn = -max(set(turns), key=turns.count) % 360
    if turn:
        image = image.rotate(-turn, expand=True, fillcolor=255)
    box = ImageOps.invert(image).point(lambda v: 255 if v > 60 else 0).getbbox()
    if box is None:
        return Image.new("L", (WIDTH_DOTS, 1), 255)
    image = image.crop(box)
    height = max(1, round(image.height * WIDTH_DOTS / image.width))
    image = image.resize((WIDTH_DOTS, height), Image.Resampling.LANCZOS).point(lambda v: 0 if v < 150 else 255)
    # where the codes were blanked out, long empty bands remain: keep at most 4 mm of them
    rows = np.array(image).min(axis=1) < 128
    keep, blank = [], 0
    for y, inked in enumerate(rows):
        blank = 0 if inked else blank + 1
        if blank <= 4 * DOTS_PER_MM:
            keep.append(y)
    return Image.fromarray(np.array(image)[keep])


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size)


def identifier(source: Source, code: Code) -> str:
    """The name printed next to a single code, so several slips can be told apart.

    From the text beside the code: the PDF's text layer, or OCR for a picture. A token that is part of the code's own
    content wins. Without any text, a short code content is its own name.
    """
    margin = 30
    near = (code.box[0] - margin, code.box[1] - margin, code.box[2] + margin, code.box[3] + margin)
    text = ""
    if source.page is not None:
        height = source.page.get_height()
        text = source.page.get_textpage().get_text_bounded(
            near[0] * PT_PER_MM, height - near[3] * PT_PER_MM, near[2] * PT_PER_MM, height - near[1] * PT_PER_MM)
    def tokens(words: str) -> list[str]:
        return [t for t in re.findall(r"[A-Za-z0-9]{8,40}", words) if re.search(r"\d", t)]

    if not tokens(text):
        # A label embedded as a picture has no text layer (the real DHL return label, 08.11.2026): read it.
        try:
            from .legibility import ocr

            mm_per_px = source.mm_per_px or 1.0
            crop = source.image.crop([max(0, round(v / mm_per_px)) for v in near])
            if code.orientation:
                crop = crop.rotate(code.orientation, expand=True, fillcolor=255)   # text upright for the OCR
            text = " ".join(word.text for word in ocr(crop))
        except Exception:  # noqa: BLE001  no name is better than no slip
            text = ""
    candidates = tokens(text)
    if candidates:
        return max(candidates, key=lambda t: (t in code.text, len(t)))
    if len(code.text) <= 32 and code.text.isprintable() and "/" not in code.text:
        return code.text
    return ""


def _caption(text: str, small: str) -> Image.Image:
    """The identifier as large as fits, a counter above it."""
    size = 44
    while size > 18 and _font(size).getlength(text) > WIDTH_DOTS - 16:
        size -= 2
    image = Image.new("L", (WIDTH_DOTS, size + 30), 255)
    draw = ImageDraw.Draw(image)
    draw.text((8, 0), small, font=_font(18), fill=0)
    if text:
        draw.text((WIDTH_DOTS // 2, 22), text, font=_font(size), fill=0, anchor="mt")
    return image


def _cut_line() -> Image.Image:
    image = Image.new("L", (WIDTH_DOTS, GAP), 255)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH_DOTS, 16):
        draw.rectangle((x, GAP // 2 - 1, x + 7, GAP // 2), fill=0)
    return image


def _centred(part: Image.Image) -> Image.Image:
    strip = Image.new("L", (WIDTH_DOTS, part.height), 255)
    strip.paste(part, ((WIDTH_DOTS - part.width) // 2, 0))
    return strip


def read_back(dots: Image.Image) -> set[tuple]:
    """Codes found after a simulated print. A MaxiCode that is there but does not read counts as missing."""
    big = dots.convert("L").resize((dots.width * 3, dots.height * 3), Image.Resampling.NEAREST)
    printed = big.filter(ImageFilter.GaussianBlur(READ_BACK_BLUR)).point(lambda v: 255 if v > 150 else 0)
    try:
        found = read_all(printed)
    except LabelError:
        found = [hit for hit in zxingcpp.read_barcodes(printed) if hit.valid]
    return {_key(item[0] if isinstance(item, tuple) else item) for item in found}


@dataclass
class Document:
    """A file taken apart: its pages and the parts found on them."""
    pages: list[Source]
    parts: list[Part]
    doubles: list[Code] = field(default_factory=list)   # skipped repeats: blanked in the overview all the same

    def kind(self, part: Part) -> str:
        """label: several codes, to stick on. shop: one 2D code, to show at a shop. code: one linear code, to enclose."""
        if len(part.codes) > 1:
            return "label"
        return "code" if part.codes[0].format in LINEAR else "shop"

    @property
    def needs_choice(self) -> bool:
        """A label to print yourself and a code to have it printed at a shop: those are alternatives, so ask."""
        kinds = {self.kind(part) for part in self.parts}
        return "label" in kinds and "shop" in kinds

    def choose(self, way: str) -> list[Part]:
        """way: "shop" or "label". Codes to enclose come along either way."""
        other = "label" if way == "shop" else "shop"
        return [part for part in self.parts if self.kind(part) != other]


def analyze(data: bytes) -> Document:
    """Find every code on every page and sort them into parts. Raises LabelError when there is nothing to print."""
    pages = sources(data)
    codes, seen, doubles = [], set(), []
    for number, source in enumerate(pages):
        for code in find_codes(source):
            key = (code.format, code.identifier, code.data)
            code.page = number
            if key in seen:   # the same code twice, as on a receipt beside the label
                doubles.append(code)
                continue
            seen.add(key)
            codes.append(code)
    if not codes:
        raise LabelError("no_code")
    groups = group(codes)
    names = {id(g): identifier(pages[g[0].page], g[0]) if len(g) == 1 else "" for g in groups}
    # A lone code without a name of its own (a label's DataMatrix far from its bars) belongs to the nearest part.
    changed = True
    while changed:
        changed = False
        for g in groups:
            if len(g) == 1 and not names[id(g)]:
                others = [o for o in groups if o is not g and o[0].page == g[0].page]
                if others:
                    target = min(others, key=lambda o: (len(o) == 1, min(_gap(g[0], c) for c in o)))
                    target.extend(g)
                    groups = [o for o in groups if o is not g]
                    names[id(target)] = "" if len(target) > 1 else names[id(target)]
                    changed = True
                    break
    groups.sort(key=lambda part: (part[0].page, min(c.box[1] for c in part), min(c.box[0] for c in part)))
    return Document(pages, [Part(g, names[id(g)], g[0].page) for g in groups], doubles)


def render(document: Document, parts: list[Part] | None = None, captions: bool = True) -> Label:
    """One strip: a slip per part, cut lines between. Every code is read back; LabelError if one would not scan."""
    parts = document.parts if parts is None else parts
    groups = [part.codes for part in document.parts]
    slips = []
    for index, part in enumerate(parts, start=1):
        source = document.pages[part.page]
        counter = f"{index}/{len(parts)}"
        if len(part.codes) == 1:
            caption = _caption(part.identifier if captions else "", counter)
            slips.append([caption, _centred(take_over(source, part.codes[0]))])
        else:
            if source.page is not None:
                page_mm = (source.page.get_width() / PT_PER_MM, source.page.get_height() / PT_PER_MM)
            else:
                page_mm = (float(source.image.width), float(source.image.height))
            region = _region(part.codes, groups, page_mm)
            # a shrunk copy of a repeated code would sit in the overview: blank those as well (real DHL label)
            blank = part.codes + [c for c in document.doubles if c.page == part.page]
            slips.append([_caption("", counter), overview(source, blank, region)]
                         + [_centred(take_over(source, code)) for code in part.codes])
    # Each slip is its own print job: they are cut apart anyway, and a label plus its enclosure slip passed 50 cm
    # together on a real DHL return (08.11.2026). The limit and the read-back hold per slip.
    printed = []
    for part, slip in zip(parts, slips):
        blocks = []
        for block_number, block in enumerate(slip):
            blocks.append(block)
            if block_number < len(slip) - 1:
                blocks.append(Image.new("L", (WIDTH_DOTS, GAP), 255))
        rows = sum(block.height for block in blocks)
        if rows > MAX_ROWS:
            raise LabelError("long", cm=f"{rows / DOTS_PER_MM / 10:.0f}")
        strip = Image.new("L", (WIDTH_DOTS, rows), 255)
        y = 0
        for block in blocks:
            strip.paste(block, (0, y))
            y += block.height
        dots = strip.convert("1", dither=Image.Dither.NONE)
        found = read_back(dots)
        missing = [code for code in part.codes if (code.format, code.identifier, code.data) not in found]
        if missing:
            raise LabelError("not_scanning", what=", ".join(c.format.name for c in missing))
        printed.append(dots)
    # one strip for the preview, with cut lines between the slips
    pieces = []
    for number, dots in enumerate(printed):
        if number:
            pieces.append(_cut_line())
        pieces.append(dots.convert("L"))
    whole = Image.new("L", (WIDTH_DOTS, sum(p.height for p in pieces)), 255)
    y = 0
    for piece in pieces:
        whole.paste(piece, (0, y))
        y += piece.height
    codes = [code for part in parts for code in part.codes]
    return Label(whole.convert("1", dither=Image.Dither.NONE), codes, parts, printed)


def build(data: bytes) -> Label:
    """Everything in the file, without asking. The print server asks first when a document offers a choice."""
    return render(analyze(data))
