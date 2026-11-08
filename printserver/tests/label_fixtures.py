"""Made-up shipping labels, 100 x 150 mm, built the way carrier PDFs are: codes as vector rectangles, text in
Helvetica, a MaxiCode as an embedded picture. Every number here is invented; none of them is a real parcel."""
from __future__ import annotations

import zlib

import numpy as np
import zxingcpp

F = zxingcpp.BarcodeFormat
PT = 72 / 25.4
PAGE_W, PAGE_H = 100.0, 150.0
LINEAR = {F.Code128, F.ITF}

# carrier -> list of (format, content, module mm, gs1, bar height mm)
LABELS = {
    "DHL": [(F.Code128, "(00)340434161234567890", 0.375, True, 22), (F.ITF, "12345678901231", 0.5, False, 18),
            (F.ITF, "123456789012", 0.5, False, 18), (F.DataMatrix, "DHL" + "0123456789" * 6, 0.5, False, 0)],
    "Hermes": [(F.Code128, "H1001234567890123456", 0.375, False, 25),
               (F.DataMatrix, "HERMES" + "ABCDEFGHIJ" * 5, 0.5, False, 0)],
    "DPD": [(F.Code128, "%0012345012345678901234567276", 0.33, False, 25),
            (F.DataMatrix, "DPD" + "9876543210" * 8, 0.42, False, 0)],
    "GLS": [(F.DataMatrix, "GLS" + "".join(chr(65 + (i * 7) % 26) for i in range(150)), 0.5, False, 0),
            (F.Code128, "123456789012", 0.5, False, 20)],
    "UPS": [(F.MaxiCode, "[)>\x1e01\x1d96123450000\x1d276\x1d066\x1d1Z99999999\x1dUPSN\x1d123456\x1d001\x1e\x04",
             0.0, False, 0),
            (F.Code128, "1Z999AA10123456784", 0.38, False, 25),
            (F.PDF417, "".join(chr(48 + i % 10) for i in range(120)), 0.33, False, 0)],
    "Amazon": [(F.Code128, "TBA123456789000", 0.38, False, 25),
               (F.QRCode, "https://example.invalid/return/" + "a1b2c3d4" * 4, 0.5, False, 0)],
}


def _matrix(fmt, content, gs1):
    code = zxingcpp.create_barcode(content, fmt, gs1=True) if gs1 else zxingcpp.create_barcode(content, fmt)
    m = np.array(code.to_image(scale=1, add_quiet_zones=False))
    return m[:1] if fmt in LINEAR else m


def _rects(matrix, left, top, module, bar_height):
    """PDF rectangle operators for the dark modules, in points, from the top left of the page."""
    ops = []
    rows = matrix.shape[0]
    for r in range(rows):
        row, x = matrix[r], 0
        while x < len(row):
            if row[x] == 0:
                start = x
                while x < len(row) and row[x] == 0:
                    x += 1
                height = bar_height if rows == 1 else module
                y_mm = top + (0 if rows == 1 else r * module)
                ops.append(f"{(left + start * module) * PT:.3f} {(PAGE_H - y_mm - height) * PT:.3f} "
                           f"{(x - start) * module * PT:.3f} {height * PT:.3f} re")
            else:
                x += 1
    return " ".join(ops) + " f"


def label_pdf(carrier: str, scale: float = 1.0) -> bytes:
    """One label. `scale` shrinks or grows everything on the page, as a print dialog's "fit to page" would."""
    content, images, y = [], [], 34.0
    for fmt, data, module, gs1, bar in LABELS[carrier]:
        if fmt == F.MaxiCode:
            picture = np.array(zxingcpp.create_barcode(data, fmt).to_image(scale=8, add_quiet_zones=False))
            images.append((picture, 6.0, y, 28.14 * picture.shape[0] / picture.shape[1] * 1.0, 28.14))
            y += 28.14 + 6
            continue
        m = _matrix(fmt, data, gs1)
        content.append(_rects(m, 6.0, y, module, bar))
        y += (bar if m.shape[0] == 1 else m.shape[0] * module) + 7
    text = ("BT /F1 9 Tf {x:.1f} {y:.1f} Td ({t}) Tj ET")
    lines = [(f"{carrier} PAKET", 14, 8), ("Empfaenger: Erika Mustermann", 9, 16), ("Musterweg 1, 12345 Musterstadt", 9, 21),
             ("Absender: Max Muster, Beispielallee 2", 6, 26)]
    for t, size, ymm in lines:
        content.append(text.replace("9 Tf", f"{size} Tf").format(x=6 * PT, y=(PAGE_H - ymm) * PT, t=t))
    stream = " ".join(content)
    if scale != 1.0:
        stream = f"{scale:.4f} 0 0 {scale:.4f} 0 {(PAGE_H * PT) * (1 - scale):.3f} cm " + stream
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    xobjects = []
    for index, (picture, x, top, h, w) in enumerate(images):
        raw = zlib.compress(picture.astype(np.uint8).tobytes())
        objects.append((f"<< /Type /XObject /Subtype /Image /Width {picture.shape[1]} /Height {picture.shape[0]} "
                        f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length {len(raw)} >>", raw))
        name = f"/Im{index}"
        xobjects.append(f"{name} {len(objects)} 0 R")
        place = f"q {w * PT * scale:.3f} 0 0 {h * PT * scale:.3f} {x * PT * scale:.3f} " \
                f"{(PAGE_H - (top + h) * scale) * PT if scale == 1.0 else (PAGE_H * PT) * (1 - scale) + (PAGE_H - top - h) * PT * scale:.3f} cm {name} Do Q"
        stream += " " + place
    page_stream = stream.encode("latin-1")
    objects.append((f"<< /Length {len(page_stream)} >>", page_stream))
    resources = f"<< /Font << /F1 4 0 R >> /XObject << {' '.join(xobjects)} >> >>"
    objects[2] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W * PT:.3f} {PAGE_H * PT:.3f}] "
                  f"/Resources {resources} /Contents {len(objects)} 0 R >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        if isinstance(obj, tuple):
            out += f"{number} 0 obj\n{obj[0]}\nstream\n".encode() + obj[1] + b"\nendstream\nendobj\n"
        else:
            out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def expected(carrier: str) -> set[tuple]:
    """What a reader finds in the source: format, symbology identifier, bytes."""
    import pypdfium2

    page = pypdfium2.PdfDocument(label_pdf(carrier))[0]
    image = page.render(scale=600 / 72, grayscale=True).to_pil()
    found = {(h.format, h.symbology_identifier, bytes(h.bytes)) for h in zxingcpp.read_barcodes(image) if h.valid}
    # The reader finds a MaxiCode only on its own, so cut it out where this file placed it (6 mm left, 34 mm down).
    if any(fmt == F.MaxiCode for fmt, *_ in LABELS[carrier]):
        mm = 600 / 25.4
        crop = image.crop((int(2 * mm), int(30 * mm), int(38 * mm), int(66 * mm)))
        found |= {(h.format, h.symbology_identifier, bytes(h.bytes))
                  for h in zxingcpp.read_barcodes(crop, formats=F.MaxiCode) if h.valid}
    return found


def _text(t: str, x_mm: float, y_mm: float, size: float, page_h: float) -> str:
    safe = t.replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 {size} Tf {x_mm * PT:.2f} {(page_h - y_mm) * PT:.2f} Td ({safe}) Tj ET"


def _code_ops(fmt, data, module, gs1, bar, left, top, page_h):
    m = _matrix(fmt, data, gs1)
    ops = _rects(m, left, top, module, bar)
    if page_h != PAGE_H:   # _rects measures from a 150 mm page; move it onto this page
        ops = f"q 1 0 0 1 0 {(page_h - PAGE_H) * PT:.3f} cm {ops} Q"
    return ops, (bar if m.shape[0] == 1 else m.shape[0] * module)


def return_document() -> bytes:
    """Made up, laid out like an Amazon return PDF for DHL (seen 08.11.2026): three A4 pages.

    1: instructions only. 2: turned by 90°, a QR code with its RET identifier on the left half, the DHL label with two
    DataMatrix and three GS1-128 codes on the right half. 3: one Code 128 with its identifier, to go inside the parcel.
    """
    a4w, a4h = 210.0, 297.0
    pages = []
    pages.append(" ".join(_text(t, 20, 30 + i * 8, 10, a4h) for i, t in enumerate(
        ["Weitere Hinweise zum Versand des Pakets", "Drucke das Etikett aus.", "Bringe das Paket zur Post."])))
    # page 2: draw everything on an upright 297 x 210 sheet, then turn it onto the A4 page
    sheet = []
    qr_id = "RET00340400000000000042"
    ops, h = _code_ops(F.QRCode, "https://example.invalid/dhl/" + qr_id, 0.75, False, 0, 20, 120, a4w)
    sheet += [ops, _text(qr_id, 20, 120 + h + 6, 9, a4w), _text("DHL druckt fuer Sie", 20, 112, 9, a4w)]
    sheet += [_text("DHL Retoure", 160, 20, 14, a4w), _text("An: Muster Retouren GmbH", 160, 32, 11, a4w),
              _text("Beispielstrasse 9, 30000 Musterstadt", 160, 39, 11, a4w)]
    ops, h1 = _code_ops(F.DataMatrix, "DHLRET" + "0123456789" * 6, 0.5, False, 0, 255, 16, a4w)
    sheet.append(ops)
    ops, h2 = _code_ops(F.Code128, "(403)27630559+99000900000000", 0.375, True, 25, 160, 70, a4w)
    sheet.append(ops)
    ops, h3 = _code_ops(F.Code128, "(00)340434600000000042", 0.375, True, 25, 160, 108, a4w)
    sheet.append(ops)
    sheet.append(_text("Sendungsnummer: (00)340434600000000042", 160, 138, 7, a4w))
    turned = " ".join(sheet)
    # rotate the 297 x 210 sheet by 90° onto the 210 x 297 page
    pages.append(f"q 0 1 -1 0 {a4w * PT:.3f} 0 cm {turned} Q")
    ops, h = _code_ops(F.Code128, "XyzaQNr5TEST", 0.5, False, 30, 55, 40, a4h)
    pages.append(" ".join([_text("XyzaQNr5TEST", 90, 36, 10, a4h), ops,
                           _text("Nummer des Amazon Ruecksendeetiketts XyzaQNr5TEST", 55, 80, 10, a4h)]))
    return _pdf(pages, a4w, a4h)


def _pdf(streams: list[str], w_mm: float, h_mm: float) -> bytes:
    """A plain PDF with one content stream per page and Helvetica as /F1."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for stream in streams:
        raw = stream.encode("latin-1")
        objects.append((f"<< /Length {len(raw)} >>", raw))
        content = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w_mm * PT:.3f} {h_mm * PT:.3f}] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        if isinstance(obj, tuple):
            out += f"{number} 0 obj\n{obj[0]}\nstream\n".encode() + obj[1] + b"\nendstream\nendobj\n"
        else:
            out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
