"""IPP wire format (RFC 8010). Bytes in, bytes out, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

# Delimiter tags
OPERATION, JOB, END, PRINTER, UNSUPPORTED = 0x01, 0x02, 0x03, 0x04, 0x05
# Value tags
INTEGER, BOOLEAN, ENUM = 0x21, 0x22, 0x23
RESOLUTION, RANGE, BEG_COLLECTION, END_COLLECTION = 0x32, 0x33, 0x34, 0x37
TEXT, NAME, KEYWORD, URI, URI_SCHEME, CHARSET, LANGUAGE, MIME, MEMBER = 0x41, 0x42, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A
NO_VALUE = 0x13
# Operations
PRINT_JOB, VALIDATE_JOB, CREATE_JOB, SEND_DOCUMENT = 0x0002, 0x0004, 0x0005, 0x0006
CANCEL_JOB, GET_JOB_ATTRIBUTES, GET_JOBS, GET_PRINTER_ATTRIBUTES = 0x0008, 0x0009, 0x000A, 0x000B
# Status
OK, BAD_REQUEST, NOT_FOUND, DOCUMENT_FORMAT_NOT_SUPPORTED = 0x0000, 0x0400, 0x0406, 0x040A
TOO_LARGE, DOCUMENT_FORMAT_ERROR, DOCUMENT_UNPRINTABLE = 0x0408, 0x0411, 0x041B
INTERNAL_ERROR, OPERATION_NOT_SUPPORTED, TEMPORARY_ERROR, NOT_ACCEPTING = 0x0500, 0x0501, 0x0505, 0x0506


class Resolution:
    def __init__(self, dpi: int) -> None:
        self.dpi = dpi


@dataclass
class Request:
    version: tuple[int, int]
    operation: int
    request_id: int
    attributes: dict[str, list] = field(default_factory=dict)
    document: bytes = b""

    def first(self, name: str, default=None):
        values = self.attributes.get(name)
        return values[0] if values else default


def parse_request(data: bytes) -> Request:
    """Read a request. Collections are skipped: nothing here needs them, and this printer has one paper path."""
    if len(data) < 9:
        raise ValueError("IPP request too short")
    major, minor, operation, request_id = struct.unpack(">BBHI", data[:8])
    pos, attributes, name, depth = 8, {}, None, 0
    while True:
        if pos >= len(data):
            raise ValueError("IPP request ended without an end tag")
        tag = data[pos]
        pos += 1
        if tag == END:
            break
        if tag <= 0x0F:
            name = None
            continue
        if pos + 2 > len(data):
            raise ValueError("IPP attribute cut off")
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        raw_name = data[pos:pos + length]
        pos += length
        if pos + 2 > len(data):
            raise ValueError("IPP attribute cut off")
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        raw = data[pos:pos + length]
        if len(raw) != length:
            raise ValueError("IPP value cut off")
        pos += length
        if tag == BEG_COLLECTION:
            depth += 1
            continue
        if tag == END_COLLECTION:
            depth -= 1
            continue
        if depth:
            continue
        if raw_name:
            name = raw_name.decode("utf-8", "replace")
            attributes[name] = []
        if name is None:
            raise ValueError("IPP value without a name")
        attributes[name].append(_decode(tag, raw))
    return Request((major, minor), operation, request_id, attributes, data[pos:])


def _decode(tag: int, raw: bytes):
    if tag in (INTEGER, ENUM) and len(raw) == 4:
        return struct.unpack(">i", raw)[0]
    if tag == BOOLEAN and len(raw) == 1:
        return raw[0] != 0
    if tag >= 0x35:
        return raw.decode("utf-8", "replace")
    return raw


def _encode(tag: int, value) -> bytes:
    if tag in (INTEGER, ENUM):
        return struct.pack(">i", value)
    if tag == BOOLEAN:
        return b"\x01" if value else b"\x00"
    if tag == RESOLUTION:
        return struct.pack(">iiB", value.dpi, value.dpi, 3)
    if tag == RANGE:
        return struct.pack(">ii", *value)
    if tag == NO_VALUE:
        return b""
    return str(value).encode("utf-8")


def _value(tag: int, name: str, value) -> bytes:
    raw_name = name.encode()
    raw = _encode(tag, value)
    return struct.pack(">BH", tag, len(raw_name)) + raw_name + struct.pack(">H", len(raw)) + raw


def attribute(tag: int, name: str, values) -> bytes:
    """One attribute with one or more values. Further values carry an empty name, as the format demands."""
    if not isinstance(values, (list, tuple)) or tag == RANGE and isinstance(values, tuple):
        values = [values]
    out = _value(tag, name, values[0])
    for value in values[1:]:
        out += _value(tag, "", value)
    return out


def collection(name: str, members: list[tuple[int, str, object]], first: bool = True) -> bytes:
    """One collection value. `members` may hold nested byte strings made by collection(.., member=...)."""
    out = _value(BEG_COLLECTION, name if first else "", "")
    for tag, member, value in members:
        out += _value(MEMBER, "", member)
        if tag == BEG_COLLECTION:
            out += _value(BEG_COLLECTION, "", "")
            for inner_tag, inner_member, inner_value in value:
                out += _value(MEMBER, "", inner_member) + _value(inner_tag, "", inner_value)
            out += _value(END_COLLECTION, "", "")
        else:
            out += _value(tag, "", value)
    return out + _value(END_COLLECTION, "", "")


def response(request: Request, status: int, message: str = "", groups: list[tuple[int, bytes]] | None = None) -> bytes:
    version = request.version if request.version[0] in (1, 2) else (2, 0)
    out = struct.pack(">BBHI", version[0], min(version[1], 1), status, request.request_id)
    out += bytes([OPERATION]) + attribute(CHARSET, "attributes-charset", "utf-8")
    out += attribute(LANGUAGE, "attributes-natural-language", "en")
    if message:
        out += attribute(TEXT, "status-message", message[:255])
    for group, content in groups or []:
        out += bytes([group]) + content
    return out + bytes([END])
