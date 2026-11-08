import struct

import pytest

from iprintd import ipp


def build(operation=ipp.GET_PRINTER_ATTRIBUTES, attrs=(), doc=b"", request_id=7):
    out = struct.pack(">BBHI", 2, 0, operation, request_id) + bytes([ipp.OPERATION])
    out += ipp.attribute(ipp.CHARSET, "attributes-charset", "utf-8")
    out += ipp.attribute(ipp.LANGUAGE, "attributes-natural-language", "en")
    for tag, name, value in attrs:
        out += ipp.attribute(tag, name, value)
    return out + bytes([ipp.END]) + doc


def test_a_request_and_its_document():
    r = ipp.parse_request(build(ipp.PRINT_JOB, [(ipp.NAME, "job-name", "Foto"), (ipp.MIME, "document-format", "image/jpeg")], b"\xff\xd8data"))
    assert (r.operation, r.request_id, r.first("job-name"), r.first("document-format")) == (ipp.PRINT_JOB, 7, "Foto", "image/jpeg")
    assert r.document == b"\xff\xd8data"


def test_several_values_for_one_name():
    r = ipp.parse_request(build(attrs=[(ipp.KEYWORD, "requested-attributes", ["a", "b"])]))
    assert r.attributes["requested-attributes"] == ["a", "b"]


def test_integers_stay_integers():
    assert ipp.parse_request(build(attrs=[(ipp.INTEGER, "job-id", 42)])).first("job-id") == 42


def test_collections_in_a_request_are_skipped_not_misread():
    media = ipp.collection("media-col", [(ipp.KEYWORD, "media-type", "x")])
    data = struct.pack(">BBHI", 2, 0, ipp.PRINT_JOB, 1) + bytes([ipp.JOB]) + media + ipp.attribute(ipp.NAME, "job-name", "after")
    r = ipp.parse_request(data + bytes([ipp.END]))
    assert r.first("job-name") == "after" and "media-type" not in r.attributes


@pytest.mark.parametrize("data", [b"", b"\x02\x00\x00\x0b", build()[:-1], build()[:20]])
def test_cut_off_requests_are_refused(data):
    with pytest.raises(ValueError):
        ipp.parse_request(data)


def test_response_echoes_the_request_id_and_carries_the_message():
    r = ipp.parse_request(build(request_id=99))
    out = ipp.response(r, ipp.DOCUMENT_UNPRINTABLE, "zu klein")
    assert struct.unpack(">HI", out[2:8]) == (ipp.DOCUMENT_UNPRINTABLE, 99)
    assert "zu klein".encode() in out and out[-1] == ipp.END
