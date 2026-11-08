import struct

import pytest

from iprintd.raster import MAX_PIXELS, RasterError, decode_pwg, decode_urf


def urf(width, height, lines, bits=8):
    head = bytes([bits, 0, 0, 0]) + bytes(8) + struct.pack(">III", width, height, 203) + bytes(8)
    return b"UNIRAST\x00" + struct.pack(">I", 1) + head + lines


def pwg(width, height, lines, bits=8):
    head = bytearray(1796)
    head[372:380] = struct.pack(">II", width, height)
    head[388:392] = struct.pack(">I", bits)
    return b"RaS2" + bytes(head) + lines


@pytest.mark.parametrize("decode,make", [(decode_urf, urf), (decode_pwg, pwg)])
def test_repeat_literal_and_white_fill(decode, make):
    # line 1: three of 0x00, then literal 0x10 0x20, then white to the end. Repeated twice in all.
    page = decode(make(8, 2, bytes([1, 2, 0x00, 255, 0x10, 0x20, 128])))[0]
    row = list(page.tobytes())[:8]
    assert row == [0, 0, 0, 0x10, 0x20, 255, 255, 255]
    assert list(page.tobytes())[8:] == row


@pytest.mark.parametrize("decode,make", [(decode_urf, urf), (decode_pwg, pwg)])
def test_colour_becomes_grey(decode, make):
    page = decode(make(1, 1, bytes([0, 0, 255, 0, 0]), bits=24))[0]
    assert page.mode == "L" and 60 < page.getpixel((0, 0)) < 90


@pytest.mark.parametrize("decode,make", [(decode_urf, urf), (decode_pwg, pwg)])
def test_cut_off_data_is_an_error(decode, make):
    with pytest.raises(RasterError):
        decode(make(8, 2, bytes([0, 2])))


@pytest.mark.parametrize("decode,make", [(decode_urf, urf), (decode_pwg, pwg)])
def test_a_crafted_huge_page_is_refused_before_any_memory_is_used(decode, make):
    with pytest.raises(RasterError):
        decode(make(MAX_PIXELS, 2, b""))


def test_wrong_magic():
    with pytest.raises(RasterError):
        decode_urf(b"nope")
