"""Turn whatever a client sent into pages: greyscale pictures, large enough to read text from."""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError
import pypdfium2

from .raster import RasterError, decode_pwg, decode_urf

PDF_WIDTH_PIXELS = 1800
MAX_PAGES = 5


class DocumentError(ValueError):
    """The file cannot be read at all, as opposed to being readable but not printable."""


class TooManyPages(ValueError):
    def __init__(self, pages: int) -> None:
        super().__init__(f"{pages} pages")
        self.pages = pages


def _picture(data: bytes) -> list[Image.Image]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            upright = ImageOps.exif_transpose(image)
            if upright.mode in ("RGBA", "LA", "P"):
                upright = upright.convert("RGBA")
                upright = Image.alpha_composite(Image.new("RGBA", upright.size, "white"), upright)
            return [upright.convert("L")]
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as err:
        raise DocumentError(f"cannot read the picture: {err}") from err


def _pdf(data: bytes) -> list[Image.Image]:
    try:
        pdf = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as err:
        raise DocumentError(f"cannot read the PDF: {err}") from err
    try:
        if len(pdf) > MAX_PAGES:
            raise TooManyPages(len(pdf))
        pages = []
        for page in pdf:
            scale = PDF_WIDTH_PIXELS / max(page.get_width(), 1)
            pages.append(page.render(scale=scale, grayscale=True).to_pil().convert("L"))
        return pages
    finally:
        pdf.close()


def load_pages(data: bytes, mime: str) -> list[Image.Image]:
    """Sort by what the bytes are, since some clients send application/octet-stream."""
    try:
        if data[:5] == b"%PDF-":
            pages = _pdf(data)
        elif data[:8] == b"UNIRAST\x00":
            pages = decode_urf(data)
        elif data[:4] == b"RaS2":
            pages = decode_pwg(data)
        else:
            pages = _picture(data)
    except RasterError as err:
        raise DocumentError(str(err)) from err
    if not pages:
        raise DocumentError("the document has no pages")
    if len(pages) > MAX_PAGES:
        raise TooManyPages(len(pages))
    return pages
