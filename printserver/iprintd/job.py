"""One document from bytes to verdict. No network in here."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .documents import MAX_PAGES, DocumentError, TooManyPages, load_pages
from .legibility import DOTS_PER_MM, MAX_ROWS, assemble, check_page
from .labels import Document, LabelError, analyze, build, render
from .messages import for_page, say


@dataclass
class Result:
    dots: Image.Image | None = None
    refused: str = ""
    broken: bool = False
    document: Document | None = None
    picture: Image.Image | None = None
    slips: list = None   # shipping label slips, each its own print job


# Without a question, a return offering both ways prints the shop QR code with its identifier: the official way of
# every carrier, the shortest slip, and DHL forbids changed labels (decided 08.11.2026).
DEFAULT_WAY = "shop"


def process_label(data: bytes, language: str, ask: bool = False) -> Result:
    """Shipping label mode: codes at full size, read back identically, or a refusal that says why.
    A document offering both a shop QR code and a label comes back undecided with `ask`, with `document` set;
    without `ask` it prints the shop way."""
    try:
        document = analyze(data)
        if document.needs_choice:
            if ask:
                return Result(document=document)
            return finish_label(document, DEFAULT_WAY, True, language)
        label = render(document)
    except LabelError as err:
        return Result(refused=say(language, f"label_{err.key}", **err.values), broken=err.key == "broken")
    return Result(dots=label.dots, slips=label.slips)


def finish_label(document: Document, way: str, captions: bool, language: str) -> Result:
    try:
        label = render(document, document.choose(way), captions)
        return Result(dots=label.dots, slips=label.slips)
    except LabelError as err:
        return Result(refused=say(language, f"label_{err.key}", **err.values))


def process(data: bytes, mime: str, language: str, ask: bool = False) -> Result:
    """`ask`: a lone photo waits for the editor page instead of printing at once."""
    try:
        pages = load_pages(data, mime)
    except DocumentError:
        return Result(refused=say(language, "broken"), broken=True)
    except TooManyPages as err:
        return Result(refused=say(language, "pages", pages=err.pages, max=MAX_PAGES))
    checked = []
    for page in pages:
        verdict = check_page(page)
        if verdict.dots is None:
            return Result(refused=for_page(language, verdict))
        checked.append(verdict)
    if ask and len(checked) == 1 and not checked[0].is_text:
        return Result(picture=pages[0])   # a photo: the person gets to adjust it first (asked for 08.11.2026)
    strip = assemble(checked)
    if strip.height > MAX_ROWS:
        cm = f"{strip.height / DOTS_PER_MM / 10:.0f}"
        return Result(refused=say(language, "long", cm=cm, max=f"{MAX_ROWS / DOTS_PER_MM / 10:.0f}"))
    return Result(dots=strip)
