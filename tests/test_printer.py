"""print_rows against a fake socket: the printer must not be told to print into a known problem."""
import errno

import pytest

from phomemo import printer as mod
from phomemo.printer import Printer, PrinterError, PrinterNotReady, PrinterSilent, PrinterUnreachable
from phomemo.protocol import BYTES_PER_ROW, QUERY_BATTERY, QUERY_LID, QUERY_PAPER


class FakeSock:
    def __init__(self, answers, after_job=b"\x1a\x0f\x0c"):
        self.answers = answers
        self.after_job = after_job
        self.sent = []
        self.pending = b""
        self.job_seen = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def sendall(self, data):
        self.sent.append(data)
        if data in self.answers:
            self.pending += self.answers[data]
        elif not self.job_seen:
            self.job_seen = True
            self.pending += self.after_job

    def recv(self, _n):
        data, self.pending = self.pending, b""
        return data


@pytest.fixture
def run(monkeypatch):
    def make(lid=b"\x1a\x05\x98", paper=b"\x1a\x06\x89", after_job=b"\x1a\x0f\x0c", battery=b"\x1a\x04\x49"):
        sock = FakeSock({QUERY_LID: lid, QUERY_PAPER: paper, QUERY_BATTERY: battery}, after_job)
        monkeypatch.setattr(Printer, "_connect", lambda self, patience=0: sock)
        monkeypatch.setattr(mod.select, "select", lambda r, w, x, t: (r if sock.pending else [], [], []))
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(mod, "ANSWER_SECONDS", 0.01)
        monkeypatch.setattr(mod, "FINISH_MARGIN", 0.05)
        monkeypatch.setattr(mod, "ROWS_PER_SECOND_WORST", 1000)
        return sock
    return make


ROWS = bytes(BYTES_PER_ROW * 2)


def test_good_job(run):
    sock = run()
    assert Printer("x").print_rows(ROWS, 2, "dark").print_ok is True
    assert any(b"\x1d\x76\x30\x00" in s for s in sock.sent)


def test_open_lid_sends_no_picture(run):
    sock = run(lid=b"\x1a\x05\x99")
    with pytest.raises(PrinterNotReady):
        Printer("x").print_rows(ROWS, 2, "dark")
    assert not any(b"\x1d\x76\x30\x00" in s for s in sock.sent)


def test_no_paper_sends_no_picture(run):
    sock = run(paper=b"\x1a\x06\x88")
    with pytest.raises(PrinterNotReady):
        Printer("x").print_rows(ROWS, 2, "dark")
    assert not any(b"\x1d\x76\x30\x00" in s for s in sock.sent)


def test_silence_after_the_job_is_an_error_not_a_success(run):
    run(after_job=b"")
    with pytest.raises(PrinterError):
        Printer("x").print_rows(ROWS, 2, "dark")


def test_failed_job_is_reported(run):
    run(after_job=b"\x1a\x0f\x00")
    with pytest.raises(PrinterError):
        Printer("x").print_rows(ROWS, 2, "dark")


def test_unreachable_is_its_own_error(monkeypatch):
    class Dead:
        def __init__(self, *a):
            pass

        def settimeout(self, _t):
            pass

        def connect(self, _a):
            raise OSError("Host is down")

        def close(self):
            pass

    monkeypatch.setattr(mod.socket, "socket", Dead)
    monkeypatch.setattr(mod.socket, "AF_BLUETOOTH", 31, raising=False)
    monkeypatch.setattr(mod.socket, "BTPROTO_RFCOMM", 3, raising=False)
    with pytest.raises(PrinterUnreachable):
        Printer("x").read_status()


def test_silent_printer_is_an_error_when_polled(run):
    """Seen on the real printer: the connection succeeds and no question is answered."""
    run(lid=b"", paper=b"", battery=b"")
    with pytest.raises(PrinterSilent):
        Printer("x").read_status()


def test_silent_printer_gets_no_picture(run):
    sock = run(lid=b"", paper=b"", battery=b"")
    with pytest.raises(PrinterSilent):
        Printer("x").print_rows(ROWS, 2, "dark")
    assert not any(b"\x1d\x76\x30\x00" in s for s in sock.sent)


def _flaky(monkeypatch, failures):
    """A socket whose connect fails like the real printer just after a disconnect."""
    calls = []

    class Sock:
        def __init__(self, *a):
            pass

        def settimeout(self, _t):
            pass

        def connect(self, _a):
            calls.append(1)
            if len(calls) <= len(failures):
                raise OSError(failures[len(calls) - 1], "x")

        def close(self):
            pass

    monkeypatch.setattr(mod.socket, "socket", Sock)
    monkeypatch.setattr(mod.socket, "AF_BLUETOOTH", 31, raising=False)
    monkeypatch.setattr(mod.socket, "BTPROTO_RFCOMM", 3, raising=False)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return calls


def test_busy_then_down_then_up_connects(monkeypatch):
    calls = _flaky(monkeypatch, [errno.EBUSY, errno.EHOSTDOWN, errno.EHOSTDOWN])
    assert Printer("x")._connect(patience=5)
    assert len(calls) == 4


def test_gives_up_when_patience_is_over(monkeypatch):
    _flaky(monkeypatch, [errno.EHOSTDOWN] * 1000)
    with pytest.raises(PrinterUnreachable):
        Printer("x")._connect(patience=0)


def test_other_errors_are_not_retried(monkeypatch):
    calls = _flaky(monkeypatch, [errno.EACCES] * 5)
    with pytest.raises(PrinterUnreachable):
        Printer("x")._connect(patience=30)
    assert len(calls) == 1
