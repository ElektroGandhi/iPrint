"""The job must only count as handed over when the integration itself says so."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from PIL import Image
import pytest

from iprintd.handoff import Handoff, Offline, QueueFull

DOTS = Image.new("1", (384, 10), 1)


def serve(status):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.handle_request, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/"


def test_accepted():
    Handoff(serve(201)).send(DOTS, "x")


def test_a_plain_200_is_not_success():
    """What Home Assistant answers to an unknown webhook. Real failure: the job was gone and the client heard "printed"."""
    with pytest.raises(Offline):
        Handoff(serve(200)).send(DOTS, "x")


def test_full_queue_is_its_own_answer():
    with pytest.raises(QueueFull):
        Handoff(serve(507)).send(DOTS, "x")


def test_nobody_home():
    with pytest.raises(Offline):
        Handoff("http://127.0.0.1:9/").send(DOTS, "x")
