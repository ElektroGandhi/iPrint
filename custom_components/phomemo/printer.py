"""Blocking RFCOMM client. Bluetooth classic is outside HA's BLE stack, so this talks to a kernel socket directly.

Every call opens its own connection (1.3 s measured) and closes it again: the printer takes one client at a time and
the phone app must stay usable. Call from an executor.
"""
from __future__ import annotations

import errno
import select
import socket
import time

from .const import RFCOMM_CHANNEL
from .protocol import FEED, INFO_QUERIES, STATUS_QUERIES, Status, parse_status, raster_job

CONNECT_TIMEOUT = 15
# Measured right after a disconnect: EBUSY at first, then EHOSTDOWN for up to 32 s, from a printer that is on and
# working. A failed attempt takes about 5 s. So one failure means nothing, and only a job is worth a long wait.
PATIENCE_JOB = 45
PATIENCE_POLL = 20
_RETRY_ERRNOS = {errno.EBUSY, errno.EHOSTDOWN, errno.ETIMEDOUT, errno.ECONNREFUSED}
ANSWER_SECONDS = 0.6
CHUNK = 1024
CHUNK_PAUSE = 0.02
# Measured: 160 rows in 3.9 s. Allow a slow, cold printer well beyond that.
ROWS_PER_SECOND_WORST = 15
FINISH_MARGIN = 15


class PrinterError(Exception):
    """The printer could not be reached or did not finish. The message is meant for the user."""


class PrinterUnreachable(PrinterError):
    """Off, out of range, or busy with another client."""


class PrinterSilent(PrinterUnreachable):
    """The radio accepts the connection but nothing answers. Measured after about two idle hours on the charger."""


class PrinterNotReady(PrinterError):
    """Reachable, but printing now would waste the job."""


def _read(sock: socket.socket, seconds: float) -> bytes:
    data = b""
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        if select.select([sock], [], [], min(left, 0.2))[0]:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
    return data


class Printer:
    def __init__(self, address: str, channel: int = RFCOMM_CHANNEL) -> None:
        self.address = address
        self.channel = channel

    def _connect(self, patience: float = PATIENCE_JOB) -> socket.socket:
        deadline = time.monotonic() + patience
        while True:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(CONNECT_TIMEOUT)
            try:
                sock.connect((self.address, self.channel))
            except OSError as err:
                sock.close()
                # A socket timeout carries no errno, so it has to be named on its own (seen on the real printer).
                retry = isinstance(err, TimeoutError) or err.errno in _RETRY_ERRNOS
                if not retry or time.monotonic() >= deadline:
                    raise PrinterUnreachable(f"Printer {self.address} not reachable: {err}") from err
                time.sleep(1)
            else:
                return sock

    def _ask(self, sock: socket.socket, queries: tuple[bytes, ...], status: Status) -> Status:
        for query in queries:
            sock.sendall(query)
            parse_status(_read(sock, ANSWER_SECONDS), status)
        if status.lid_open is None and status.paper_out is None and status.battery is None:
            raise PrinterSilent(f"Printer {self.address} connects but does not answer; switch it off and on")
        return status

    def read_status(self, with_info: bool = False) -> Status:
        try:
            with self._connect(PATIENCE_POLL) as sock:
                status = self._ask(sock, STATUS_QUERIES, Status())
                return self._ask(sock, INFO_QUERIES, status) if with_info else status
        except PrinterError:
            raise
        except OSError as err:
            raise PrinterUnreachable(f"Connection to {self.address} lost: {err}") from err

    def feed(self) -> None:
        try:
            with self._connect() as sock:
                sock.sendall(FEED)
        except PrinterError:
            raise
        except OSError as err:
            raise PrinterUnreachable(f"Connection to {self.address} lost: {err}") from err

    def print_rows(self, rows: bytes, row_count: int, density: str) -> Status:
        """Check the printer, send one page and wait for it to say it has finished."""
        job = raster_job(rows, row_count, density)
        with self._connect() as sock:
            try:
                status = self._ask(sock, STATUS_QUERIES, Status())
            except OSError as err:
                raise PrinterUnreachable(f"Connection to {self.address} lost: {err}") from err
            if status.lid_open:
                raise PrinterNotReady("The printer lid is open")
            if status.paper_out:
                raise PrinterNotReady("The printer is out of paper")
            status.print_ok = None
            try:
                for start in range(0, len(job), CHUNK):
                    sock.sendall(job[start:start + CHUNK])
                    time.sleep(CHUNK_PAUSE)
                deadline = time.monotonic() + row_count / ROWS_PER_SECOND_WORST + FINISH_MARGIN
                buffer = b""
                while status.print_ok is None and not status.cancelled and time.monotonic() < deadline:
                    buffer += _read(sock, 0.5)
                    parse_status(buffer, status)
            except OSError as err:
                raise PrinterError(f"Connection lost while printing: {err}") from err
        if status.cancelled:
            raise PrinterError("Printing was cancelled at the printer")
        if status.print_ok is None:
            raise PrinterError("The printer never reported the end of the job")
        if not status.print_ok:
            raise PrinterError("The printer reported a failed job")
        return status
