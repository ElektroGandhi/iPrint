"""Two printers on one service: /ipp/print for documents, /ipp/label for shipping labels."""
import struct
import uuid

from iprintd import ipp
from iprintd.server import Service, handle
from label_fixtures import label_pdf, return_document
from iprintd import labels


class Collect:
    """Stands in for Home Assistant and keeps what would have been printed."""

    def __init__(self):
        self.sent, self.refused, self.asked = [], [], []

    def ask(self, label, url):
        self.asked.append(url)

    def send(self, dots, label, queue="print"):
        self.sent.append(dots)

    def report_refusal(self, label, reason):
        self.refused.append(reason)


def service(language="de", ask=False):
    return Service(Collect(), "192.0.2.10", 631, uuid.uuid4(), language, ask)


def request(operation, attrs=(), doc=b""):
    out = struct.pack(">BBHI", 2, 0, operation, 1) + bytes([ipp.OPERATION])
    out += ipp.attribute(ipp.CHARSET, "attributes-charset", "utf-8")
    out += ipp.attribute(ipp.LANGUAGE, "attributes-natural-language", "en")
    for tag, name, value in attrs:
        out += ipp.attribute(tag, name, value)
    return ipp.parse_request(out + bytes([ipp.END]) + doc)


def status(answer: bytes) -> int:
    return struct.unpack(">H", answer[2:4])[0]


def test_label_queue_calls_itself_so_and_offers_carrier_paper():
    answer = handle(service(), request(ipp.GET_PRINTER_ATTRIBUTES), "label")
    assert "Versandetikett".encode() in answer
    assert b"iso_a4_210x297mm" in answer and b"oe_t02-short_48x100mm" not in answer
    assert b"/ipp/label" in answer


def test_document_queue_is_unchanged():
    answer = handle(service(), request(ipp.GET_PRINTER_ATTRIBUTES), "print")
    assert b"oe_t02-short_48x100mm" in answer and "Versandetikett".encode() not in answer


def test_a_label_sent_to_the_label_queue_prints_as_a_label():
    svc = service()
    pdf = label_pdf("Hermes")
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.NAME, "job-name", "Paket"),
                                                 (ipp.MIME, "document-format", "application/pdf")], pdf), "label")
    assert status(answer) == ipp.OK
    assert len(svc.handoff.sent) == 1 and svc.handoff.sent[0].width == 384
    assert b"/ipp/label/" in answer   # the job belongs to the label printer


def test_a_letter_sent_to_the_label_queue_is_refused_with_a_reason():
    from PIL import Image, ImageDraw
    import io

    page = Image.new("L", (800, 600), 255)
    ImageDraw.Draw(page).text((40, 40), "Nur ein Brief, kein Etikett", fill=0)
    buffer = io.BytesIO()
    page.save(buffer, "PNG")
    svc = service()
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "image/png")], buffer.getvalue()), "label")
    assert status(answer) == ipp.DOCUMENT_UNPRINTABLE
    assert svc.handoff.refused and "Versandcode" in svc.handoff.refused[0]
    assert not svc.handoff.sent


def test_a_return_document_with_both_ways_waits_for_a_choice():
    """Asked for 08.11.2026: shop QR code or label to print yourself, then ask. Nothing is printed before."""
    svc = service(ask=True)
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.NAME, "job-name", "Ruecksendung"),
                                                 (ipp.MIME, "document-format", "application/pdf")], return_document()), "label")
    assert status(answer) == ipp.OK
    assert not svc.handoff.sent and len(svc.handoff.asked) == 1
    assert b"job-hold-until-specified" in answer
    token = svc.handoff.asked[0].rsplit("/", 1)[1]
    from iprintd.choice import page
    html = page(token, svc.choices.get(token), "de")
    assert "QR-Code für den Shop" in html and "Etikett selbst aufkleben" in html and 'type="checkbox"' in html
    ok, _ = svc.decide(token, "shop", True)
    assert ok and len(svc.handoff.sent) == 2   # two slips, each its own job: shop code, code to enclose
    found = [{key[0].name for key in labels.read_back(slip)} for slip in svc.handoff.sent]
    assert found == [{"QRCode"}, {"Code128"}]   # each slip reads on its own, and no label among them
    again, text = svc.decide(token, "shop", True)
    assert not again and len(svc.handoff.sent) == 2   # sending the form twice prints nothing twice


def test_the_label_way_prints_the_label_and_the_code_to_enclose():
    svc = service(ask=True)
    handle(svc, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "application/pdf")], return_document()), "label")
    token = svc.handoff.asked[0].rsplit("/", 1)[1]
    ok, _ = svc.decide(token, "label", False)
    found = set().union(*({key[0].name for key in labels.read_back(slip)} for slip in svc.handoff.sent))
    assert ok and len(svc.handoff.sent) == 2 and found == {"Code128", "DataMatrix"}


def test_without_questions_a_return_prints_the_shop_way_at_once():
    """The default since 0.2.0b3 (decided 08.11.2026): a question nobody saw held a real return for ever."""
    svc = service()
    answer = handle(svc, request(ipp.PRINT_JOB, [(ipp.NAME, "job-name", "Ruecksendung"),
                                                 (ipp.MIME, "document-format", "application/pdf")], return_document()), "label")
    assert status(answer) == ipp.OK and b"job-hold-until-specified" not in answer
    assert not svc.handoff.asked and len(svc.handoff.sent) == 2
    found = [{key[0].name for key in labels.read_back(slip)} for slip in svc.handoff.sent]
    assert found == [{"QRCode"}, {"Code128"}]   # shop code with its identifier, code to enclose; no label
