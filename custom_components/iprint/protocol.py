"""The T02 wire protocol. Pure bytes, no I/O: see docs/PROTOCOL.md for how each value was established."""
from __future__ import annotations

from dataclasses import dataclass

WIDTH_DOTS = 384
BYTES_PER_ROW = WIDTH_DOTS // 8
MAX_ROWS = 4000  # about 50 cm: a runaway automation must not empty the roll

INIT = bytes.fromhex("1B40")
PAPER_CONTINUOUS = bytes.fromhex("1F110B")
COMPRESSION_OFF = bytes.fromhex("1F113500")
FEED = bytes.fromhex("1B6402")

QUERY_FIRMWARE = bytes.fromhex("1F1107")
QUERY_BATTERY = bytes.fromhex("1F1108")
QUERY_SERIAL = bytes.fromhex("1F1109")
QUERY_AUTO_OFF = bytes.fromhex("1F110E")
QUERY_PAPER = bytes.fromhex("1F1111")
QUERY_LID = bytes.fromhex("1F1112")
STATUS_QUERIES = (QUERY_LID, QUERY_PAPER, QUERY_BATTERY)
INFO_QUERIES = (QUERY_FIRMWARE, QUERY_SERIAL, QUERY_AUTO_OFF)

_DENSITY = {"light": (0x01, 0x64), "normal": (0x02, 0x64), "dark": (0x04, 0x64), "darkest": (0x04, 0x96)}
_BATTERY_WARNING = {0xA1: 10, 0xA2: 5, 0xA3: 3}
# type byte -> payload length of a 0x1A status frame
_FRAME_LENGTH = {0x03: 1, 0x04: 1, 0x05: 1, 0x06: 1, 0x07: 3, 0x08: 15, 0x09: 1, 0x0B: 1, 0x0F: 1, 0x17: 1, 0x35: 1}


def density_commands(density: str) -> bytes:
    level, energy = _DENSITY[density]
    return bytes((0x1F, 0x11, 0x02, level, 0x1F, 0x11, 0x37, energy))


def raster_job(rows: bytes, row_count: int, density: str) -> bytes:
    """The command sequence the app sends for one page, in the same order."""
    if row_count < 1 or row_count > MAX_ROWS or row_count > 0xFFFF:
        raise ValueError(f"row count out of range: {row_count}")
    if len(rows) != BYTES_PER_ROW * row_count:
        raise ValueError(f"expected {BYTES_PER_ROW * row_count} bytes, got {len(rows)}")
    header = bytes.fromhex("1D763000") + BYTES_PER_ROW.to_bytes(2, "little") + row_count.to_bytes(2, "little")
    return b"".join((INIT, density_commands(density), PAPER_CONTINUOUS, COMPRESSION_OFF, header, rows, FEED, FEED))


@dataclass
class Status:
    """Everything the printer has told us. None means it has not said."""

    lid_open: bool | None = None
    paper_out: bool | None = None
    battery: int | None = None
    overheated: bool | None = None
    charging: bool | None = None
    firmware: str | None = None
    serial: str | None = None
    auto_off_minutes: int | None = None
    print_ok: bool | None = None
    cancelled: bool = False


def consume_status(data: bytes, status: Status) -> bytes:
    """Apply every complete 0x1A frame to status and return what is left: an incomplete frame waits for its other half.

    A byte it cannot place drops the rest of this read instead of guessing where the next frame starts.
    """
    pos = 0
    while pos < len(data):
        if data[pos] != 0x1A:
            return b""
        if pos + 2 > len(data):
            return data[pos:]
        kind = data[pos + 1]
        length = _FRAME_LENGTH.get(kind)
        if length is None:
            return b""
        if pos + 2 + length > len(data):
            return data[pos:]
        _apply(kind, data[pos + 2:pos + 2 + length], status)
        pos += 2 + length
    return b""


def parse_status(data: bytes, status: Status | None = None) -> Status:
    status = status or Status()
    consume_status(data, status)
    return status


def _apply(kind: int, body: bytes, status: Status) -> None:
    value = body[0]
    if kind == 0x03:
        status.overheated = {0xA8: False, 0xA9: True}.get(value, status.overheated)
    elif kind == 0x04:
        status.battery = _BATTERY_WARNING.get(value, value)
    elif kind == 0x05:
        status.lid_open = {0x98: False, 0x99: True}.get(value, status.lid_open)
    elif kind == 0x06:
        status.paper_out = value == 0x88
    elif kind == 0x07:
        status.firmware = ".".join(str(b) for b in body)
    elif kind == 0x08:
        status.serial = body.decode("ascii", "replace")
    elif kind == 0x09:
        status.auto_off_minutes = value * 5
    elif kind == 0x0B:
        status.cancelled = status.cancelled or value == 0xB8
    elif kind == 0x0F:
        status.print_ok = value == 0x0C
    elif kind == 0x35:
        status.charging = value == 0x02
