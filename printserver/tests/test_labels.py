"""Shipping labels: every code must come out of the printer exactly as it went in, and large enough to scan."""
import io

import numpy as np
from PIL import Image
import pytest
import zxingcpp

from iprintd import labels
from iprintd.labels import LabelError, build, read_back
from label_fixtures import LABELS, expected, label_pdf, return_document

F = zxingcpp.BarcodeFormat
CARRIERS = sorted(LABELS)


@pytest.mark.parametrize("carrier", CARRIERS)
def test_the_source_label_itself_reads(carrier):
    """Positive control: if the made-up label did not read at 600 dpi, every later result would mean nothing."""
    assert len(expected(carrier)) == len(LABELS[carrier])


@pytest.mark.parametrize("carrier", CARRIERS)
def test_every_code_survives_identically(carrier):
    label = build(label_pdf(carrier))
    assert label.dots.width == labels.WIDTH_DOTS
    assert label.dots.height <= labels.MAX_ROWS
    assert expected(carrier) <= read_back(label.dots)


@pytest.mark.parametrize("carrier", CARRIERS)
def test_module_size_is_measured_right(carrier):
    """Against the module size this test file drew, not against the measurement itself."""
    truth = {content: module for fmt, content, module, gs1, bar in LABELS[carrier]}
    for code in build(label_pdf(carrier)).codes:
        if code.format == F.MaxiCode:
            continue
        key = next(k for k in truth if k.replace("(", "").replace(")", "") in code.text.replace("(", "").replace(")", ""))
        assert abs(code.module_mm - truth[key]) <= 0.03, (code.format, code.module_mm, truth[key])


@pytest.mark.parametrize("carrier", CARRIERS)
def test_no_code_gets_smaller_than_on_the_original(carrier):
    truth = {content: module for fmt, content, module, gs1, bar in LABELS[carrier]}
    for code in build(label_pdf(carrier)).codes:
        if code.format == F.MaxiCode:
            continue
        key = next(k for k in truth if k.replace("(", "").replace(")", "") in code.text.replace("(", "").replace(")", ""))
        dots = labels._dots_per_module(code, True)
        assert dots / labels.DOTS_PER_MM >= truth[key] - 0.01, (code.format, truth[key], dots)


def test_gs1_stays_gs1():
    """The reason codes are taken over and not re-encoded: an encoder dropped GS1 without a word."""
    ids = {(c.format, c.identifier) for c in build(label_pdf("DHL")).codes}
    assert (F.Code128, "]C1") in ids


def test_shrinking_the_whole_label_would_not_scan():
    """The plain way, for the record: 100 mm squeezed to 48 mm. Code 128 must fail, or this feature is pointless."""
    import pypdfium2

    page = pypdfium2.PdfDocument(label_pdf("Hermes"))[0]
    squeezed = page.render(scale=384 / page.get_width(), grayscale=True).to_pil().point(lambda v: 0 if v < 128 else 255)
    found = read_back(squeezed.convert("1"))
    assert not any(key[0] == F.Code128 for key in found)


def test_fit_to_page_in_a_print_dialog_does_not_matter():
    """A dialog may shrink the label onto a bigger page. Module size is measured, so the code comes out the same."""
    small = build(label_pdf("DPD", scale=0.7))
    assert expected("DPD") <= read_back(small.dots)


def test_no_code_means_no_label():
    pdf = label_pdf("Hermes")
    blank = pdf.replace(b" re f", b" re n")   # paint no rectangles: text only
    with pytest.raises(LabelError):
        build(blank)


def test_a_picture_of_a_label_works_too():
    import pypdfium2

    page = pypdfium2.PdfDocument(label_pdf("Amazon"))[0]
    buffer = io.BytesIO()
    page.render(scale=300 / 72, grayscale=True).to_pil().save(buffer, "PNG")
    label = build(buffer.getvalue())
    assert expected("Amazon") <= read_back(label.dots)


def test_unreadable_file():
    with pytest.raises(LabelError):
        build(b"not a label")


def test_read_back_is_not_fooled_by_an_empty_strip():
    """The check itself must be able to fail."""
    assert read_back(Image.new("1", (384, 400), 1)) == set()


@pytest.mark.parametrize("carrier", ["DHL", "Hermes", "DPD"])
def test_linear_codes_keep_carrier_quiet_zone_and_bar_height(carrier):
    """Hermes asks for 8 mm of white beside the bars, DHL, DPD and Hermes for bars of at least 25 mm."""
    source = labels.sources(label_pdf(carrier, scale=0.7))[0]   # shrunk by a print dialog: bars got shorter
    for code in labels.find_codes(source):
        if code.format not in labels.LINEAR:
            continue
        image = labels.take_over(source, code)
        across, along = (image.width, image.height) if image.width <= image.height else (image.height, image.width)
        assert across >= labels.MIN_BAR_MM * labels.DOTS_PER_MM
        grey = image.convert("L")
        if grey.height > grey.width:      # code runs down the paper: quiet zones are at the top and bottom
            grey = grey.rotate(90, expand=True)
        columns = list(np.array(grey).min(axis=0))
        first_bar = next(i for i, v in enumerate(columns) if v < 128)
        last_bar = len(columns) - 1 - next(i for i, v in enumerate(reversed(columns)) if v < 128)
        assert first_bar >= labels.QUIET_MM * labels.DOTS_PER_MM
        assert len(columns) - 1 - last_bar >= labels.QUIET_MM * labels.DOTS_PER_MM


def test_a_return_document_is_taken_apart():
    """Laid out like a real Amazon return for DHL: label, shop QR code with its RET identifier, code to enclose."""
    doc = labels.analyze(return_document())
    kinds = [(doc.kind(part), part.identifier) for part in doc.parts]
    assert ("label", "") in kinds
    assert ("shop", "RET00340400000000000042") in kinds
    assert ("code", "XyzaQNr5TEST") in kinds
    assert doc.needs_choice
    label = next(part for part in doc.parts if doc.kind(part) == "label")
    assert {c.format.name for c in label.codes} == {"Code128", "DataMatrix"}   # the far DataMatrix joined its label


def test_a_label_alone_needs_no_choice():
    assert not labels.analyze(label_pdf("DHL")).needs_choice


def test_sideways_label_text_is_turned_upright_from_the_text_layer():
    doc = labels.analyze(return_document())
    assert labels._text_turn(doc.pages[1], None) == 90


def test_a_qr_code_from_a_square_grid_is_no_maxicode():
    """A QR code with 0.75 mm modules passed the first ring check (08.11.2026) and refused the whole document."""
    for source in labels.sources(return_document()):
        assert labels._bullseyes(np.array(source.image)) == []


def test_every_slip_is_its_own_strip_and_reads_on_its_own():
    """A label and its enclosure slip passed 50 cm together on a real DHL return (08.11.2026)."""
    doc = labels.analyze(return_document())
    label = labels.render(doc, doc.choose("label"))
    assert len(label.slips) == 2
    for slip, part in zip(label.slips, label.parts):
        assert slip.height <= labels.MAX_ROWS
        assert {(c.format, c.identifier, c.data) for c in part.codes} <= read_back(slip)


def test_a_code_repeated_elsewhere_on_the_page_is_kept_as_a_double():
    """A real DHL return label carries its DataMatrix twice. It is printed once, but the overview must blank both."""
    import pypdfium2

    pdf = label_pdf("Hermes")
    page = pypdfium2.PdfDocument(pdf)[0]
    picture = page.render(scale=300 / 72, grayscale=True).to_pil()
    # paste the label's DataMatrix a second time, far from the first
    dm = [h for h in zxingcpp.read_barcodes(picture) if h.format == F.DataMatrix][0]
    xs = [p.x for p in (dm.position.top_left, dm.position.bottom_right)]
    ys = [p.y for p in (dm.position.top_left, dm.position.bottom_right)]
    box = (min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)
    picture.paste(picture.crop(box), (picture.width - (box[2] - box[0]) - 20, picture.height - (box[3] - box[1]) - 20))
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    doc = labels.analyze(buffer.getvalue())
    assert [c.format for c in doc.doubles] == [F.DataMatrix]
