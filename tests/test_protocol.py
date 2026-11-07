"""Frames below were read off a real T02 (firmware 1.0.0) unless a comment says otherwise."""
import pytest

from iprint.protocol import BYTES_PER_ROW, MAX_ROWS, Status, consume_status, density_commands, parse_status, raster_job


def h(text):
    return bytes.fromhex(text)


def test_real_answers():
    s = parse_status(h("1a 05 98 1a 06 89 1a 04 49"))
    assert (s.lid_open, s.paper_out, s.battery) == (False, False, 73)


def test_real_firmware_and_auto_off():
    s = parse_status(h("1a 07 01 00 00 1a 09 0c"))
    assert (s.firmware, s.auto_off_minutes) == ("1.0.0", 60)


def test_real_end_of_job():
    assert parse_status(h("1a 0f 0c")).print_ok is True


def test_real_chip_frame_followed_by_low_battery_warning():
    s = parse_status(h("1a 17 03 1a 04 a2"))
    assert s.battery == 5


@pytest.mark.parametrize("frame,attr,want", [
    ("1a 05 99", "lid_open", True),      # from the app's decoder
    ("1a 06 88", "paper_out", True),
    ("1a 03 a9", "overheated", True),
    ("1a 0f 00", "print_ok", False),
    ("1a 0b b8", "cancelled", True),
    ("1a 35 02", "charging", True),
    ("1a 35 01", "charging", False),
])
def test_app_decoder(frame, attr, want):
    assert getattr(parse_status(h(frame)), attr) == want


def test_unknown_frame_stops_instead_of_misreading_the_rest():
    s = parse_status(h("1a 7f 05 98 1a 06 88"))
    assert s == Status()


def test_truncated_frame_is_ignored():
    assert parse_status(h("1a 08 51 31")) == Status()


def test_status_accumulates():
    s = parse_status(h("1a 05 98"))
    parse_status(h("1a 04 10"), s)
    assert (s.lid_open, s.battery) == (False, 16)


def test_job_matches_what_printed_on_the_real_printer():
    rows = bytes(BYTES_PER_ROW * 160)
    job = raster_job(rows, 160, "dark")
    want = h("1b40 1f110204 1f113764 1f110b 1f113500 1d763000 3000 a000")
    assert job.startswith(want)
    assert job[len(want):len(want) + len(rows)] == rows
    assert job.endswith(h("1b6402 1b6402"))


def test_row_count_is_little_endian():
    job = raster_job(bytes(BYTES_PER_ROW * 300), 300, "dark")
    assert h("1d763000 3000 2c01") in job


@pytest.mark.parametrize("count", [0, MAX_ROWS + 1])
def test_row_limit(count):
    with pytest.raises(ValueError):
        raster_job(bytes(BYTES_PER_ROW * max(count, 0)), count, "dark")


def test_wrong_data_length():
    with pytest.raises(ValueError):
        raster_job(bytes(BYTES_PER_ROW - 1), 1, "dark")


def test_darkest_uses_higher_energy():
    assert density_commands("darkest") == h("1f110204 1f113796")


def test_a_frame_split_across_reads_is_kept():
    s = Status()
    rest = consume_status(h("1a 05 98 1a 04"), s)
    assert s.lid_open is False and s.battery is None and rest == h("1a 04")
    assert consume_status(rest + h("49"), s) == b"" and s.battery == 73


def test_a_lone_first_byte_is_kept():
    assert consume_status(h("1a"), Status()) == h("1a")


def test_rubbish_is_dropped_not_kept_forever():
    assert consume_status(h("ff 00"), Status()) == b""
