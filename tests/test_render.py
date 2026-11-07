import pytest
from PIL import Image

from iprint.protocol import BYTES_PER_ROW, MAX_ROWS, WIDTH_DOTS
from iprint.render import get_font, render_image, render_text, to_rows


def test_black_dot_on_the_left_is_the_high_bit():
    image = Image.new("1", (WIDTH_DOTS, 1), 1)
    image.putpixel((0, 0), 0)
    rows, count = to_rows(image)
    assert count == 1 and rows[0] == 0x80 and rows[1:] == bytes(BYTES_PER_ROW - 1)


def test_white_paper_sends_no_black_dots():
    rows, _ = to_rows(Image.new("1", (WIDTH_DOTS, 3), 1))
    assert rows == bytes(BYTES_PER_ROW * 3)


def test_wrong_width_is_refused():
    with pytest.raises(ValueError):
        to_rows(Image.new("1", (100, 3), 1))


def test_long_text_wraps_and_grows():
    one = render_text("kurz")
    many = render_text("Ein langer Satz mit Umlauten äöü, der sicher nicht auf eine Zeile passt. " * 3)
    assert one.width == many.width == WIDTH_DOTS
    assert many.height > one.height * 3


def test_word_wider_than_paper_is_broken_not_clipped():
    image = render_text("x" * 200)
    assert image.height > render_text("x").height
    # no ink may be lost past the right edge: the last column stays white because of the margin
    assert all(image.getpixel((WIDTH_DOTS - 1, y)) for y in range(image.height))


def test_newlines_count():
    assert render_text("a\nb\nc").height > render_text("a").height * 2


def test_title_makes_it_taller():
    assert render_text("a", title="Titel").height > render_text("a").height


@pytest.mark.parametrize("text,title", [("", None), ("   \n ", None), ("", "  ")])
def test_nothing_to_print(text, title):
    with pytest.raises(ValueError):
        render_text(text, title=title)


def test_runaway_text_is_refused():
    with pytest.raises(ValueError):
        render_text("zeile\n" * 3000)


def test_image_scales_to_paper_and_keeps_aspect():
    out = render_image(Image.new("RGB", (800, 400), "white"))
    assert out.size == (WIDTH_DOTS, 192) and out.mode == "1"


def test_transparent_background_prints_white_not_black():
    out = render_image(Image.new("RGBA", (384, 10), (0, 0, 0, 0)))
    assert to_rows(out)[0] == bytes(BYTES_PER_ROW * 10)


def test_endless_image_is_refused():
    with pytest.raises(ValueError):
        render_image(Image.new("L", (10, MAX_ROWS)))


def _missing(font, chars):
    """Characters drawn as the font's "no such glyph" box. A box has a size too, so size proves nothing."""
    box = font.getmask("\U0010FFFD")
    signature = (box.size, bytes(box))
    return [c for c in chars if (font.getmask(c).size, bytes(font.getmask(c))) == signature]


def test_german_and_common_signs_are_real_letters():
    assert _missing(get_font(28), "ÄÖÜäöüß€–—„“”‚‘’…°µ§²³·•×÷±→←↑↓✓✗½¼¾©®™éèàçñøåæ") == []


def test_the_box_detector_can_fail():
    """Without this the test above would pass on any font. Pillow's built-in font lacks the umlauts."""
    from PIL import ImageFont
    assert "ä" in _missing(ImageFont.load_default(28), "Aä")
    assert "A" not in _missing(ImageFont.load_default(28), "Aä")
