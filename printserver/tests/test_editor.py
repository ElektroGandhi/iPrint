"""With questions on, photos wait for a little editing; text documents still print at once. Off: all at once."""
import io
import uuid

from PIL import Image, ImageDraw
import pytest

from iprintd import editor, ipp
from iprintd.server import Service, handle
from test_queues import Collect, request, status


def photo(width=800, height=500):
    image = Image.effect_noise((width // 8, height // 8), 60).resize((width, height), Image.Resampling.BICUBIC)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG")
    return buffer.getvalue()


def service(ask=True):
    return Service(Collect(), "192.0.2.10", 631, uuid.uuid4(), "de", ask)


def test_settings_are_clamped_and_unknown_values_ignored():
    s = editor.Settings.parse({"brightness": "999", "contrast": "-5", "turn": "45", "width": "33", "mode": "x",
                               "top": "abc"})
    assert (s.brightness, s.contrast, s.turn, s.width, s.mode, s.top) == (60, 50, 0, 100, "raster", 0)


@pytest.mark.parametrize("width", editor.WIDTHS)
def test_dots_are_always_paper_wide_and_the_picture_centred(width):
    dots = editor.apply(Image.new("L", (400, 200), 0), editor.Settings(width=width))
    assert dots.width == 384
    inked = dots.convert("L").point(lambda v: 255 - v).getbbox()
    assert inked[2] - inked[0] == 384 * width // 100


def test_turning_a_landscape_photo_makes_it_long():
    flat = editor.apply(Image.new("L", (400, 200), 128), editor.Settings())
    turned = editor.apply(Image.new("L", (400, 200), 128), editor.Settings(turn=90))
    assert turned.height > flat.height * 3


def test_cropping_shortens():
    full = editor.apply(Image.new("L", (300, 300), 128), editor.Settings())
    cut = editor.apply(Image.new("L", (300, 300), 128), editor.Settings(top=40))
    assert cut.height < full.height


def test_a_photo_waits_for_the_editor_and_prints_after():
    svc = service()
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.NAME, "job-name", "Urlaub"),
                                                 (ipp.MIME, "document-format", "image/jpeg")], photo()), "print")
    assert status(answer) == ipp.OK and not svc.handoff.sent and len(svc.handoff.asked) == 1
    url = svc.handoff.asked[0]
    assert "/bild/" in url
    token = url.rsplit("/", 1)[1]
    assert "Helligkeit" in editor.page(token, "Urlaub", "de")
    ok, _ = svc.edit(token, {"contrast": "140", "mode": "raster"})
    assert ok and len(svc.handoff.sent) == 1 and svc.handoff.sent[0].width == 384
    again, _ = svc.edit(token, {})
    assert not again and len(svc.handoff.sent) == 1


def test_too_long_keeps_waiting_so_it_can_be_cropped():
    svc = service()
    tall = Image.new("RGB", (200, 3000), "gray")
    buffer = io.BytesIO()
    tall.save(buffer, "PNG")
    handle(svc, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "image/png")], buffer.getvalue()), "print")
    token = svc.handoff.asked[0].rsplit("/", 1)[1]
    ok, text = svc.edit(token, {})
    assert not ok and "50 cm" in text and svc.choices.get(token) is not None
    ok, _ = svc.edit(token, {"width": "50", "bottom": "45"})
    assert ok and len(svc.handoff.sent) == 1


def test_a_text_note_still_prints_at_once():
    from test_legibility import page_with_text

    svc = service()
    buffer = io.BytesIO()
    page_with_text(1200, 110, lines=4).save(buffer, "PNG")
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "image/png")], buffer.getvalue()), "print")
    assert status(answer) == ipp.OK and len(svc.handoff.sent) == 1 and not svc.handoff.asked


def test_without_questions_a_photo_prints_at_once():
    """The default since 0.2.0b3: nobody has to open a page, so nothing can wait for ever."""
    svc = service(ask=False)
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "image/jpeg")], photo()), "print")
    assert status(answer) == ipp.OK
    assert not svc.handoff.asked and len(svc.handoff.sent) == 1 and svc.handoff.sent[0].width == 384
