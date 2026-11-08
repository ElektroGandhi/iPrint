"""The pages over real HTTP. Calling the page functions directly missed a crash in the request handler (08.11.2026)."""
import io
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image
import pytest

from iprintd import ipp
from iprintd.server import Service, handle, make_server
from label_fixtures import return_document
from test_queues import Collect, request


@pytest.fixture
def running():
    service = Service(Collect(), "127.0.0.1", 0, uuid.uuid4(), "de")
    server = make_server(service, 0)
    port = server.server_address[1]
    service.admin = f"http://127.0.0.1:{port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield service, f"http://127.0.0.1:{port}"
    server.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=60) as answer:
        return answer.status, answer.headers.get("Content-Type"), answer.read()


def post(url, form):
    data = urllib.parse.urlencode(form).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=60) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_choice_page_over_http_then_print(running):
    service, base = running
    handle(service, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "application/pdf")], return_document()), "label")
    path = urllib.parse.urlparse(service.handoff.asked[0]).path
    status, kind, body = get(base + path)
    assert status == 200 and "text/html" in kind and "QR-Code für den Shop".encode() in body
    status, text = post(base + path, {"way": "shop", "captions": "1"})
    assert status == 200 and "Wird gedruckt" in text and len(service.handoff.sent) == 2
    status, _ = post(base + path, {"way": "shop"})
    assert status == 404


def test_editor_page_preview_and_print_over_http(running):
    service, base = running
    buffer = io.BytesIO()
    Image.effect_noise((100, 60), 60).resize((800, 480)).convert("RGB").save(buffer, "JPEG")
    handle(service, request(ipp.PRINT_JOB, [(ipp.MIME, "document-format", "image/jpeg")], buffer.getvalue()), "print")
    path = urllib.parse.urlparse(service.handoff.asked[0]).path
    status, kind, body = get(base + path)
    assert status == 200 and "Helligkeit".encode() in body
    status, kind, png = get(base + path + "/vorschau?contrast=150&turn=90")
    assert status == 200 and kind == "image/png" and Image.open(io.BytesIO(png)).width == 384
    status, text = post(base + path, {"contrast": "120"})
    assert status == 200 and len(service.handoff.sent) == 1


def test_home_page_and_unknown_token(running):
    _, base = running
    assert get(base + "/")[0] == 200
    with pytest.raises(urllib.error.HTTPError):
        get(base + "/wahl/gibtsnicht")
