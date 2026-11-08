"""Decode the raster formats clients send: Apple Raster (URF) and PWG Raster. They share one compression."""
from __future__ import annotations

import struct

from PIL import Image

MAX_PIXELS = 60_000_000  # 8000 x 7500: well past any sane page, and a hard stop for a crafted header


class RasterError(ValueError):
    pass


def _lines(data: bytes, pos: int, width: int, height: int, bytes_per_pixel: int, white: bytes) -> tuple[bytes, int]:
    """Each line: a repeat count, then packets. n <= 127: next pixel n+1 times. n >= 129: 257-n literal pixels.
    n == 128: white to the end of the line."""
    line_bytes = width * bytes_per_pixel
    out = bytearray()
    y = 0
    while y < height:
        if pos >= len(data):
            raise RasterError("raster data ended early")
        repeat = data[pos] + 1
        pos += 1
        line = bytearray()
        while len(line) < line_bytes:
            if pos >= len(data):
                raise RasterError("raster data ended early")
            code = data[pos]
            pos += 1
            if code == 128:
                line += white * ((line_bytes - len(line)) // bytes_per_pixel)
            elif code < 128:
                pixel = data[pos:pos + bytes_per_pixel]
                pos += bytes_per_pixel
                line += pixel * (code + 1)
            else:
                size = (257 - code) * bytes_per_pixel
                line += data[pos:pos + size]
                pos += size
        if len(line) != line_bytes:
            raise RasterError("raster line has the wrong length")
        repeat = min(repeat, height - y)
        out += bytes(line) * repeat
        y += repeat
    return bytes(out), pos


def _image(raw: bytes, width: int, height: int, bits: int) -> Image.Image:
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise RasterError(f"unreasonable page size {width} x {height}")
    return Image.frombytes("L" if bits == 8 else "RGB", (width, height), raw).convert("L")


def decode_urf(data: bytes) -> list[Image.Image]:
    if data[:8] != b"UNIRAST\x00" or len(data) < 12:
        raise RasterError("not an Apple Raster file")
    count = struct.unpack(">I", data[8:12])[0]
    pos, pages = 12, []
    while pos < len(data) and (not count or len(pages) < count):
        if pos + 32 > len(data):
            raise RasterError("page header cut off")
        bits = data[pos]
        width, height = struct.unpack(">II", data[pos + 12:pos + 20])
        pos += 32
        if bits not in (8, 24):
            raise RasterError(f"unsupported depth {bits}")
        if width * height > MAX_PIXELS:
            raise RasterError(f"unreasonable page size {width} x {height}")
        size = bits // 8
        raw, pos = _lines(data, pos, width, height, size, b"\xff" * size)
        pages.append(_image(raw, width, height, bits))
    return pages


def decode_pwg(data: bytes) -> list[Image.Image]:
    if data[:4] != b"RaS2":
        raise RasterError("not a PWG Raster file")
    pos, pages = 4, []
    while pos < len(data):
        if pos + 1796 > len(data):
            raise RasterError("page header cut off")
        head = data[pos:pos + 1796]
        width, height = struct.unpack(">II", head[372:380])
        bits = struct.unpack(">I", head[388:392])[0]
        pos += 1796
        if bits not in (8, 24):
            raise RasterError(f"unsupported depth {bits}")
        if width * height > MAX_PIXELS:
            raise RasterError(f"unreasonable page size {width} x {height}")
        size = bits // 8
        raw, pos = _lines(data, pos, width, height, size, b"\xff" * size)
        pages.append(_image(raw, width, height, bits))
    return pages
