"""A little editing for photos before they print. Not an image editor: the few knobs that make a thermal print better.

The preview is the printer's own dots, so what the page shows is what comes out.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import io
from urllib.parse import urlencode

from PIL import Image, ImageEnhance, ImageOps

from .legibility import MAX_ROWS, WIDTH_DOTS
from .messages import say

TURNS = (0, 90, 180, 270)
WIDTHS = (100, 75, 50)


@dataclass
class Settings:
    brightness: int = 0      # -60 .. 60
    contrast: int = 100      # 50 .. 200 %
    turn: int = 0            # clockwise
    top: int = 0             # cut off, % of the height or width
    bottom: int = 0
    left: int = 0
    right: int = 0
    mode: str = "raster"     # raster: dots for photos; kanten: hard black and white for drawings and text
    width: int = 100         # % of the paper width

    @classmethod
    def parse(cls, values: dict) -> "Settings":
        """Anything out of range is clamped, anything unknown ignored: the page is in the open home network."""
        def number(name: str, low: int, high: int, default: int) -> int:
            try:
                return max(low, min(high, int(values.get(name, default))))
            except (TypeError, ValueError):
                return default
        turn = number("turn", 0, 270, 0)
        width = number("width", 0, 1000, 100)   # only the offered widths count; anything else is the default
        return cls(number("brightness", -60, 60, 0), number("contrast", 50, 200, 100),
                   turn if turn in TURNS else 0, number("top", 0, 45, 0), number("bottom", 0, 45, 0),
                   number("left", 0, 45, 0), number("right", 0, 45, 0),
                   "kanten" if values.get("mode") == "kanten" else "raster", width if width in WIDTHS else 100)


def apply(picture: Image.Image, settings: Settings) -> Image.Image:
    """The dots the printer will get: 384 wide, the picture centred at the chosen width."""
    image = picture.convert("L")
    if settings.turn:
        image = image.rotate(-settings.turn, expand=True)
    w, h = image.size
    box = (w * settings.left // 100, h * settings.top // 100, w - w * settings.right // 100, h - h * settings.bottom // 100)
    if box[2] - box[0] > 8 and box[3] - box[1] > 8:
        image = image.crop(box)
    image = ImageEnhance.Brightness(image).enhance(1 + settings.brightness / 100)
    image = ImageEnhance.Contrast(image).enhance(settings.contrast / 100)
    width = WIDTH_DOTS * settings.width // 100
    height = max(1, round(image.height * width / image.width))
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    if settings.mode == "kanten":
        image = ImageOps.autocontrast(image, cutoff=1).point(lambda v: 255 if v > 150 else 0).convert("1")
    else:
        image = image.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    strip = Image.new("1", (WIDTH_DOTS, image.height), 1)
    strip.paste(image, ((WIDTH_DOTS - width) // 2, 0))
    return strip


def too_long(dots: Image.Image) -> bool:
    return dots.height > MAX_ROWS


def preview_png(dots: Image.Image) -> bytes:
    buffer = io.BytesIO()
    dots.convert("L").save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


STYLE = """
:root{--bg:#fff;--fg:#111;--muted:#333;--line:#111;--accent:#0b5cad;--card:#f3f3f3;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#fff;--muted:#e6e6e6;--line:#fff;--accent:#7cc0ff;--card:#222;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:22px/1.45 system-ui,sans-serif}
main{max-width:46rem;margin:0 auto;padding:1.2rem 1rem 3rem}
h1{font-size:1.6em;margin:.2em 0 .5em}
.preview{background:#fff;border:3px solid var(--line);border-radius:12px;padding:8px;max-height:55vh;overflow:auto}
.preview img{display:block;width:100%;max-width:384px;image-rendering:pixelated;margin:auto}
label{display:block;margin:1rem 0 .2rem;font-weight:700}
input[type=range]{width:100%;height:2.4rem}
.row{display:flex;flex-wrap:wrap;gap:.5rem}
.row label{font-weight:400;margin:0;display:flex;align-items:center;gap:.4em;border:3px solid var(--line);border-radius:12px;padding:.5rem .8rem;background:var(--card)}
.row input{width:1.4em;height:1.4em}
button{font:inherit;font-weight:700;width:100%;min-height:3.2rem;border:0;border-radius:14px;background:var(--accent);color:#fff;margin-top:1.4rem}
button.second{background:transparent;color:var(--fg);border:3px solid var(--line)}
@media (prefers-color-scheme:dark){button{color:#000}button.second{color:var(--fg)}}
"""

SCRIPT = """
const form=document.querySelector('form'),img=document.querySelector('#vorschau');let t;
function update(){clearTimeout(t);t=setTimeout(()=>{img.src=form.dataset.preview+'?'+new URLSearchParams(new FormData(form))},250)}
form.addEventListener('input',update);
document.querySelector('#zurueck').addEventListener('click',e=>{e.preventDefault();form.reset();update()});
"""


def page(token: str, label: str, language: str) -> str:
    t = lambda key, **v: html.escape(say(language, key, **v))  # noqa: E731
    default = urlencode(Settings().__dict__)

    def slider(name: str, low: int, high: int, value: int) -> str:
        return (f'<label for="{name}">{t("edit_" + name)}</label>'
                f'<input type="range" id="{name}" name="{name}" min="{low}" max="{high}" value="{value}">')

    def choices(name: str, items: list[tuple[str, str]], checked: str) -> str:
        boxes = "".join(f'<label><input type="radio" name="{name}" value="{value}"{" checked" if value == checked else ""}>'
                        f'{html.escape(text)}</label>' for value, text in items)
        return f'<label>{t("edit_" + name)}</label><div class="row">{boxes}</div>'

    return (f'<!doctype html><html lang="{language}"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{t("edit_title")}</title>'
            f'<style>{STYLE}</style><main><h1>{t("edit_title")}</h1><p>{t("edit_intro", label=label)}</p>'
            f'<div class="preview"><img id="vorschau" alt="{t("edit_preview")}" src="/bild/{token}/vorschau?{default}"></div>'
            f'<form method="post" action="/bild/{token}" data-preview="/bild/{token}/vorschau">'
            + choices("mode", [("raster", say(language, "edit_raster")), ("kanten", say(language, "edit_kanten"))], "raster")
            + slider("brightness", -60, 60, 0) + slider("contrast", 50, 200, 100)
            + choices("turn", [(str(a), f"{a}°") for a in TURNS], "0")
            + choices("width", [(str(w), f"{w} %") for w in WIDTHS], "100")
            + slider("top", 0, 45, 0) + slider("bottom", 0, 45, 0) + slider("left", 0, 45, 0) + slider("right", 0, 45, 0)
            + f'<button type="submit">{t("print")}</button>'
            f'<button class="second" id="zurueck" type="button">{t("edit_reset")}</button></form>'
            f'<script>{SCRIPT}</script></main></html>')
