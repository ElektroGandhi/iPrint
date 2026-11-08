"""A return document that offers a shop QR code and a label to print yourself: the person decides, not the printer.

The job waits. Home Assistant shows a notification with a link to a page here, with a preview of both ways and a box
for the identifiers. Built for poor eyesight: large type, strong contrast, big targets, light and dark.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import html
import io
import secrets
import time

from PIL import Image

from .labels import Document, render
from .messages import say

KEEP_SECONDS = 48 * 3600
MAX_WAITING = 20


@dataclass
class Waiting:
    job_id: int
    label: str
    document: Document | None = None
    picture: Image.Image | None = None     # a photo waiting for the editor
    created: float = field(default_factory=time.monotonic)


class Choices:
    def __init__(self) -> None:
        self._waiting: dict[str, Waiting] = {}

    def add(self, waiting: Waiting) -> str:
        self._expire()
        while len(self._waiting) >= MAX_WAITING:
            self._waiting.pop(next(iter(self._waiting)))
        token = secrets.token_urlsafe(16)
        self._waiting[token] = waiting
        return token

    def get(self, token: str) -> Waiting | None:
        self._expire()
        return self._waiting.get(token)

    def take(self, token: str) -> Waiting | None:
        self._expire()
        return self._waiting.pop(token, None)

    def _expire(self) -> None:
        now = time.monotonic()
        for token in [t for t, w in self._waiting.items() if now - w.created > KEEP_SECONDS]:
            self._waiting.pop(token)


def _preview(dots: Image.Image) -> str:
    small = dots.convert("L")
    small = small.resize((small.width // 2, small.height // 2), Image.Resampling.BOX)
    buffer = io.BytesIO()
    small.save(buffer, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


STYLE = """
:root{--bg:#fff;--fg:#111;--muted:#333;--line:#111;--accent:#0b5cad;--card:#f3f3f3;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#fff;--muted:#e6e6e6;--line:#fff;--accent:#7cc0ff;--card:#222;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:22px/1.45 system-ui,sans-serif}
main{max-width:46rem;margin:0 auto;padding:1.2rem 1rem 3rem}
h1{font-size:1.6em;margin:.2em 0 .5em}
p{color:var(--muted)}
fieldset{border:0;padding:0;margin:0}
label.way{display:block;border:3px solid var(--line);border-radius:14px;padding:1rem;margin:1rem 0;background:var(--card);cursor:pointer}
label.way:has(input:checked){border-color:var(--accent);outline:4px solid var(--accent)}
label.way input{width:1.6em;height:1.6em;vertical-align:middle;margin-right:.5em}
.title{font-weight:700;font-size:1.15em}
.hint{display:block;margin:.4em 0 .8em}
.preview{display:block;background:#fff;padding:8px;border-radius:8px;max-height:60vh;overflow:auto}
.preview img{display:block;width:192px;image-rendering:pixelated;margin:auto}
.box{display:flex;gap:.6em;align-items:center;font-size:1.05em;margin:1.2rem 0}
.box input{width:1.6em;height:1.6em}
button{font:inherit;font-weight:700;width:100%;min-height:3.2rem;border:0;border-radius:14px;background:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){button{color:#000}}
"""


def page(token: str, waiting: Waiting, language: str) -> str:
    doc = waiting.document
    ways = []
    for key in ("shop", "label"):
        dots = render(doc, doc.choose(key), captions=True).dots
        checked = " checked" if key == "shop" else ""
        ways.append(
            f'<label class="way"><input type="radio" name="way" value="{key}"{checked}>'
            f'<span class="title">{html.escape(say(language, "way_" + key))}</span>'
            f'<span class="hint">{html.escape(say(language, "way_" + key + "_hint"))}</span>'
            f'<span class="preview"><img alt="" src="{_preview(dots)}"></span></label>')
    title = html.escape(say(language, "page_title"))
    return (f'<!doctype html><html lang="{language}"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
            f'<style>{STYLE}</style><main><h1>{title}</h1>'
            f'<p>{html.escape(say(language, "page_intro", label=waiting.label))}</p>'
            f'<form method="post" action="/wahl/{token}"><fieldset>{"".join(ways)}</fieldset>'
            f'<label class="box"><input type="checkbox" name="captions" value="1" checked>'
            f'{html.escape(say(language, "captions"))}</label>'
            f'<button type="submit">{html.escape(say(language, "print"))}</button></form></main></html>')


def message_page(text: str, language: str) -> str:
    return (f'<!doctype html><html lang="{language}"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>iPrint</title>'
            f'<style>{STYLE}</style><main><h1>{html.escape(text)}</h1></main></html>')
