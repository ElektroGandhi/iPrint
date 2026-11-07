"""Blocking RFCOMM client. Bluetooth classic is outside HA's BLE stack, so this talks to a kernel socket directly.

The connection stays open, as it does in the phone app. Measured on a T02:
- One held connection answered 12 of 12 questions over 6 minutes and printed at once.
- Reconnecting every few seconds succeeded 3 times in 15: after a disconnect the printer refuses new connections with
  EBUSY, EHOSTDOWN or a timeout, sometimes for more than 30 s.
- An answer takes 0.4 to 4.8 s, so a late answer means nothing and silence needs a long wait.

Not thread safe: the caller runs one call at a time, in an executor.
"""
from __future__ import annotations

import errno
import select
import socket
import time

from .const import RFCOMM_CHANNEL
from .protocol import FEED, INFO_QUERIES, STATUS_QUERIES, Status, consume_status, raster_job

CONNECT_TIMEOUT = 15
SEND_TIMEOUT = 30
PATIENCE_JOB = 45
PATIENCE_POLL = 20
ANSWER_TIMEOUT = 10
QUERY_GAP = 0.1
CHUNK = 1024
CHUNK_PAUSE = 0.02
# Measured: 1845 rows in 25.6 s. Allow a slow, cold printer well beyond that.
ROWS_PER_SECOND_WORST = 15
FINISH_MARGIN = 15
_RETRY_ERRNOS = {errno.EBUSY, errno.EHOSTDOWN, errno.ETIMEDOUT, errno.ECONNREFUSED, errno.ECONNRESET}


class PrinterError(Exception):
    """The printer could not be reached or did not finish. The message is meant for the user."""


class PrinterUnreachable(PrinterError):
    """Off, out of range, or busy with another client."""


class PrinterSilent(PrinterUnreachable):
    """The radio accepts the connection but nothing answers. Measured after about two idle hours on the charger."""


class PrinterNotReady(PrinterError):
    """Reachable, but printing now would waste the job."""


class Printer:
    def __init__(self, address: str, channel: int = RFCOMM_CHANNEL) -> None:
        self.address = address
        self.channel = channel
        self._sock: socket.socket | None = None
        self._buffer = b""

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._buffer = b""

    def _open_socket(self, patience: float) -> socket.socket:
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
                time.sleep(3)  # hammering makes it worse
            else:
                sock.settimeout(SEND_TIMEOUT)
                return sock

    def _ensure_connected(self, patience: float) -> None:
        if self._sock is None:
            self._sock = self._open_socket(patience)
            self._buffer = b""

    def _pump(self, status: Status, seconds: float) -> None:
        """Read whatever arrives for this long. Frames may come split or several at once."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) >= 0:
            if select.select([self._sock], [], [], min(left, 0.2))[0]:
                chunk = self._sock.recv(1024)
                if not chunk:
                    raise ConnectionResetError("closed by the printer")
                self._buffer = consume_status(self._buffer + chunk, status)
                return
            if left <= 0:
                return

    def _ask(self, queries: tuple[bytes, ...], status: Status, wanted: tuple[str, ...]) -> None:
        for query in queries:
            self._sock.sendall(query)
            time.sleep(QUERY_GAP)
        deadline = time.monotonic() + ANSWER_TIMEOUT
        while any(getattr(status, name) is None for name in wanted) and time.monotonic() < deadline:
            self._pump(status, 0.2)

    def _status(self, with_info: bool) -> Status:
        status = Status()
        self._pump(status, 0.05)  # anything the printer said on its own since the last call
        self._ask(STATUS_QUERIES, status, ("lid_open", "paper_out", "battery"))
        if status.lid_open is None and status.paper_out is None and status.battery is None:
            raise PrinterSilent(f"Printer {self.address} connects but does not answer; switch it off and on")
        if with_info:
            self._ask(INFO_QUERIES, status, ("firmware",))
        return status

    def _fresh_status(self, patience: float, with_info: bool = False) -> Status:
        """Status over the open connection; if that one has died unnoticed, one new connection."""
        had_connection = self._sock is not None
        self._ensure_connected(patience)
        try:
            return self._status(with_info)
        except PrinterSilent:
            self.close()
            raise
        except OSError as err:
            self.close()
            if not had_connection:
                raise PrinterUnreachable(f"Connection to {self.address} lost: {err}") from err
        self._ensure_connected(patience)
        try:
            return self._status(with_info)
        except OSError as err:
            self.close()
            raise PrinterUnreachable(f"Connection to {self.address} lost: {err}") from err
        except PrinterSilent:
            self.close()
            raise

    def read_status(self, with_info: bool = False) -> Status:
        return self._fresh_status(PATIENCE_POLL, with_info)

    def feed(self) -> None:
        self._fresh_status(PATIENCE_JOB)
        try:
            self._sock.sendall(FEED)
        except OSError as err:
            self.close()
            raise PrinterUnreachable(f"Connection to {self.address} lost: {err}") from err

    def print_rows(self, rows: bytes, row_count: int, density: str, patient: bool = True) -> Status:
        """Check the printer, send one page and wait for it to say it has finished.

        PrinterNotReady and PrinterUnreachable mean that nothing was sent. Any other error means that sending had begun,
        and such a job must never be repeated: that could print it twice. `patient=False` makes one connection attempt
        only, for a printer already known to be away.
        """
        job = raster_job(rows, row_count, density)
        status = self._fresh_status(PATIENCE_JOB if patient else 0)
        if status.lid_open:
            raise PrinterNotReady("The printer lid is open")
        if status.paper_out:
            raise PrinterNotReady("The printer is out of paper")
        status.print_ok = None
        status.cancelled = False
        try:
            for start in range(0, len(job), CHUNK):
                self._sock.sendall(job[start:start + CHUNK])
                time.sleep(CHUNK_PAUSE)
            deadline = time.monotonic() + row_count / ROWS_PER_SECOND_WORST + FINISH_MARGIN
            while status.print_ok is None and not status.cancelled and time.monotonic() < deadline:
                self._pump(status, 0.5)
        except OSError as err:
            self.close()
            raise PrinterError(f"Connection lost while printing: {err}") from err
        if status.cancelled:
            raise PrinterError("Printing was cancelled at the printer")
        if status.print_ok is None:
            raise PrinterError("The printer never reported the end of the job")
        if not status.print_ok:
            raise PrinterError("The printer reported a failed job")
        return status
