"""Against real Tesseract, on pages with known text. This is the point of the service, so nothing is faked here."""
import io

from PIL import Image, ImageDraw, ImageFont
import pypdfium2
import pytest

from iprintd.job import process
from iprintd.legibility import MIN_WORD_DOTS, WIDTH_DOTS, check_page, ocr, trim

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PROSE = ("Die Rechnung für den Monat Oktober beträgt insgesamt zweihundert Euro und ist bis zum Ende "
         "des nächsten Monats auf das bekannte Konto zu überweisen").split()


def page_with_text(width, size, lines=6):
    """A page `width` wide filled with prose at font size `size`."""
    font = ImageFont.truetype(FONT, size)
    image = Image.new("L", (width, (lines + 1) * int(size * 1.5)), 255)
    draw = ImageDraw.Draw(image)
    margin = width // 40
    y, line = size // 2, []
    placed = 0
    for word in PROSE * 40:
        candidate = " ".join(line + [word])
        if font.getlength(candidate) > width - 2 * margin:
            draw.text((margin, y), " ".join(line), font=font, fill=0)
            y += int(size * 1.5)
            line, placed = [word], placed + 1
            if placed >= lines:
                break
        else:
            line.append(word)
    return image


def dots_of_font(printed_size):
    """A portrait page that, scaled to the paper, has letters of about this font size in dots."""
    factor = 5
    lines = WIDTH_DOTS // int(printed_size * 1.5) + 2
    return page_with_text(WIDTH_DOTS * factor, printed_size * factor, lines=lines)


def noise_photo(width=1600, height=1000):
    image = Image.effect_noise((width // 8, height // 8), 60).resize((width, height), Image.Resampling.BICUBIC)
    return image.convert("L")


def pdf_bytes(pil_page):
    doc = pypdfium2.PdfDocument.new()
    page = doc.new_page(595, 842)
    obj = pypdfium2.PdfImage.new(doc)
    bitmap = pypdfium2.PdfBitmap.from_pil(pil_page.convert("RGB"))
    obj.set_bitmap(bitmap)
    obj.set_matrix(pypdfium2.PdfMatrix().scale(555, 555 * pil_page.height / pil_page.width).translate(20, 200))
    page.insert_obj(obj)
    page.gen_content()
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_ocr_sees_this_text_at_all():
    """Positive control. Without this, every later "no text found" would prove nothing."""
    found = {w.text.lower() for w in ocr(page_with_text(1800, 60))}
    assert {"rechnung", "monat"} <= found


def test_ocr_failure_is_an_error_not_no_text(monkeypatch):
    monkeypatch.setattr("iprintd.legibility.OCR_LANGUAGES", "doesnotexist")
    with pytest.raises(RuntimeError):
        ocr(page_with_text(800, 40))


def test_a_full_a4_page_of_normal_text_is_refused():
    """11 pt on A4 is what people print. On 48 mm it would be about 1 mm of font."""
    a4 = page_with_text(1654, 30, lines=30)
    verdict = check_page(a4)
    assert verdict.dots is None and verdict.reason == "small" and verdict.median_mm < 1.4


def test_large_text_passes_and_keeps_paper_width():
    verdict = check_page(dots_of_font(28))
    assert verdict.dots is not None and verdict.is_text and verdict.dots.width == WIDTH_DOTS
    assert verdict.small_share == 0


def test_the_limit_works_from_both_sides():
    assert check_page(dots_of_font(9)).dots is None
    assert check_page(dots_of_font(22)).dots is not None


def test_small_label_on_big_page_is_trimmed_and_passes():
    """A label is legible at 48 mm even if the page around it is A4: empty margins must not count against it."""
    sheet = Image.new("L", (1654, 2339), 255)
    sheet.paste(page_with_text(600, 44, lines=4), (500, 900))
    assert trim(sheet).width < 800
    assert check_page(sheet).dots is not None


def test_a_photo_passes_dithered_and_turned_to_fill_the_paper():
    verdict = check_page(noise_photo())
    assert verdict.dots is not None and not verdict.is_text
    assert verdict.dots.width == WIDTH_DOTS and verdict.dots.height > WIDTH_DOTS  # landscape was turned
    black = verdict.dots.convert("L").histogram()[0] / (verdict.dots.width * verdict.dots.height)
    assert 0.1 < black < 0.9  # dithered, not one solid block


def test_photo_with_a_little_text_is_still_a_photo():
    photo = noise_photo()
    ImageDraw.Draw(photo).rectangle((100, 100, 420, 150), fill=255)
    ImageDraw.Draw(photo).text((105, 105), "Bäckerei Müller Brot und mehr hier", font=ImageFont.truetype(FONT, 16), fill=0)
    assert check_page(photo).dots is not None


def test_wide_small_table_gets_its_second_chance_sideways():
    wide = page_with_text(2400, 44, lines=4)   # upright: 44 * 384 / 2400 = 7 dots, too small
    verdict = check_page(wide)
    assert verdict.dots is not None and verdict.dots.height > verdict.dots.width


def test_a_refusal_says_why_in_the_language_asked_for():
    data = io.BytesIO()
    page_with_text(1654, 30, lines=30).save(data, "PNG")
    assert "Schrift" in process(data.getvalue(), "image/png", "de").refused
    assert "too small" in process(data.getvalue(), "image/png", "en").refused


def test_pdf_goes_the_same_way():
    assert process(pdf_bytes(page_with_text(1654, 30, lines=30)), "application/pdf", "en").refused
    assert process(pdf_bytes(page_with_text(1200, 110, lines=4)), "application/pdf", "en").dots is not None


def test_broken_file_is_refused_as_broken():
    result = process(b"this is neither picture nor document", "image/jpeg", "en")
    assert result.broken and result.refused


def test_six_pages_are_refused_before_any_ocr():
    doc = pypdfium2.PdfDocument.new()
    for _ in range(6):
        doc.new_page(100, 100)
    out = io.BytesIO()
    doc.save(out)
    assert "6 pages" in process(out.getvalue(), "application/pdf", "en").refused


def test_the_limit_is_what_the_vision_rule_says():
    """Reading distance 300 mm / 215 = 1.4 mm at 8 dots per mm."""
    assert MIN_WORD_DOTS == round(300 / 215 * 8)
