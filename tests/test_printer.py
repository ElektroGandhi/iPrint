"""The client against a scripted socket. The cases are the ones the real printer showed."""
import errno

import pytest

from iprint import printer as mod
from iprint.printer import Printer, PrinterError, PrinterNotReady, PrinterSilent, PrinterUnreachable
from iprint.protocol import BYTES_PER_ROW, QUERY_BATTERY, QUERY_LID, QUERY_PAPER

OK = {QUERY_LID: b"\x1a\x05\x98", QUERY_PAPER: b"\x1a\x06\x89", QUERY_BATTERY: b"\x1a\x04\x49"}
ROWS = bytes(BYTES_PER_ROW * 2)
PICTURE = b"\x1d\x76\x30\x00"


class FakeSock:
    def __init__(self, answers=None, after_job=b"\x1a\x0f\x0c", delay=0, split=False, dead=False):
        self.answers = dict(OK if answers is None else answers)
        self.after_job, self.delay, self.split, self.dead = after_job, delay, split, dead
        self.sent, self.pending, self.job_seen, self.closed, self.polls = [], b"", False, False, 0

    def sendall(self, data):
        if self.dead:
            raise BrokenPipeError(errno.EPIPE, "gone")
        self.sent.append(data)
        if data in self.answers:
            self.pending += self.answers[data]
        elif PICTURE in data or (self.job_seen is False and len(data) > 8):
            self.job_seen = True
            self.pending += self.after_job

    def readable(self):
        self.polls += 1
        return bool(self.pending) and self.polls > self.delay

    def recv(self, _n):
        size = 2 if self.split else len(self.pending)
        data, self.pending = self.pending[:size], self.pending[size:]
        return data

    def close(self):
        self.closed = True

    def settimeout(self, _t):
        pass


@pytest.fixture
def world(monkeypatch):
    """Time passes instantly; connections come from a list, so each test says what the printer does next."""
    clock = {"t": 0.0}
    socks = []

    def sleep(seconds):
        clock["t"] += seconds

    def select_(r, w, x, timeout):
        clock["t"] += max(timeout, 0.01)
        return (r if r[0].readable() else [], [], [])

    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mod.time, "sleep", sleep)
    monkeypatch.setattr(mod.select, "select", select_)
    opened = []

    def open_socket(self, patience):
        opened.append(patience)
        if not socks:
            raise PrinterUnreachable("no more connections")
        return socks.pop(0)

    monkeypatch.setattr(Printer, "_open_socket", open_socket)
    return socks, opened


def sent_picture(sock):
    return any(PICTURE in s for s in sock.sent)


def test_good_job(world):
    sock = FakeSock()
    world[0].append(sock)
    assert Printer("x").print_rows(ROWS, 2, "dark").print_ok is True
    assert sent_picture(sock)


def test_connection_stays_open_between_calls(world):
    socks, opened = world
    sock = FakeSock()
    socks.append(sock)
    printer = Printer("x")
    printer.read_status()
    printer.read_status()
    printer.print_rows(ROWS, 2, "dark")
    assert len(opened) == 1 and not sock.closed and printer.connected


def test_late_answers_count(world):
    """Up to 4.8 s was measured. Calling that silence would take the printer offline for nothing."""
    sock = FakeSock(delay=20)   # 20 polls of 0.2 s = 4 s
    world[0].append(sock)
    status = Printer("x").read_status()
    assert (status.lid_open, status.paper_out, status.battery) == (False, False, 73)


def test_answers_in_pieces_count(world):
    sock = FakeSock(split=True)
    world[0].append(sock)
    assert Printer("x").read_status().battery == 73


def test_open_lid_sends_no_picture(world):
    sock = FakeSock({**OK, QUERY_LID: b"\x1a\x05\x99"})
    world[0].append(sock)
    with pytest.raises(PrinterNotReady):
        Printer("x").print_rows(ROWS, 2, "dark")
    assert not sent_picture(sock)


def test_no_paper_sends_no_picture(world):
    sock = FakeSock({**OK, QUERY_PAPER: b"\x1a\x06\x88"})
    world[0].append(sock)
    with pytest.raises(PrinterNotReady):
        Printer("x").print_rows(ROWS, 2, "dark")
    assert not sent_picture(sock)


def test_silence_after_the_job_is_an_error_not_a_success(world):
    world[0].append(FakeSock(after_job=b""))
    with pytest.raises(PrinterError):
        Printer("x").print_rows(ROWS, 2, "dark")


def test_failed_job_is_reported(world):
    world[0].append(FakeSock(after_job=b"\x1a\x0f\x00"))
    with pytest.raises(PrinterError):
        Printer("x").print_rows(ROWS, 2, "dark")


def test_silent_printer_is_an_error_and_the_connection_is_dropped(world):
    """Seen on the real printer: the connection succeeds and no question is answered."""
    sock = FakeSock({})
    world[0].append(sock)
    printer = Printer("x")
    with pytest.raises(PrinterSilent):
        printer.read_status()
    assert sock.closed and not printer.connected


def test_silent_printer_gets_no_picture(world):
    sock = FakeSock({})
    world[0].append(sock)
    with pytest.raises(PrinterSilent):
        Printer("x").print_rows(ROWS, 2, "dark")
    assert not sent_picture(sock)


def test_dead_connection_is_replaced_once(world):
    socks, opened = world
    socks.append(FakeSock())
    printer = Printer("x")
    printer.read_status()
    printer._sock.dead = True
    good = FakeSock()
    socks.append(good)
    assert printer.print_rows(ROWS, 2, "dark").print_ok is True
    assert sent_picture(good) and len(opened) == 2


def test_a_job_lost_halfway_is_not_sent_again(world):
    socks, opened = world

    class DiesOnPicture(FakeSock):
        def sendall(self, data):
            if len(data) > 8:
                raise BrokenPipeError(errno.EPIPE, "gone")
            super().sendall(data)

    socks.append(DiesOnPicture())
    printer = Printer("x")
    with pytest.raises(PrinterError):
        printer.print_rows(ROWS, 2, "dark")
    assert len(opened) == 1 and not printer.connected


def test_impatient_job_tries_once_for_a_printer_known_to_be_away(world):
    socks, opened = world
    with pytest.raises(PrinterUnreachable):
        Printer("x").print_rows(ROWS, 2, "dark", False)
    assert opened == [0]


def test_close_when_never_connected_is_fine():
    Printer("x").close()


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
                failure = failures[len(calls) - 1]
                raise failure if isinstance(failure, OSError) else OSError(failure, "x")

        def close(self):
            pass

    monkeypatch.setattr(mod.socket, "socket", Sock)
    monkeypatch.setattr(mod.socket, "AF_BLUETOOTH", 31, raising=False)
    monkeypatch.setattr(mod.socket, "BTPROTO_RFCOMM", 3, raising=False)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return calls


def test_busy_then_down_then_up_connects(monkeypatch):
    calls = _flaky(monkeypatch, [errno.EBUSY, errno.EHOSTDOWN, errno.ECONNRESET])
    assert Printer("x")._open_socket(patience=5)
    assert len(calls) == 4


def test_socket_timeout_is_retried(monkeypatch):
    """socket.settimeout raises TimeoutError("timed out") with errno None. Real failure, 07.11.2026."""
    calls = _flaky(monkeypatch, [TimeoutError("timed out")])
    assert Printer("x")._open_socket(patience=5)
    assert len(calls) == 2


def test_gives_up_when_patience_is_over(monkeypatch):
    _flaky(monkeypatch, [errno.EHOSTDOWN] * 1000)
    with pytest.raises(PrinterUnreachable):
        Printer("x")._open_socket(patience=0)


def test_other_errors_are_not_retried(monkeypatch):
    calls = _flaky(monkeypatch, [errno.EACCES] * 5)
    with pytest.raises(PrinterUnreachable):
        Printer("x")._open_socket(patience=30)
    assert len(calls) == 1
