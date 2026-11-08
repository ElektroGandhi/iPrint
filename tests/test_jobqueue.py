"""The queue promises three things: order, nothing lost silently, nothing printed twice."""
import json

import pytest

from iprint.jobqueue import MAX_JOBS, MAX_LABEL_JOBS, Job, JobQueue, QueueFull
from iprint.printer import PrinterError, PrinterNotReady, PrinterSilent, PrinterUnreachable


def job(name="a"):
    return Job(b"\x00\xff" * 48, 2, "dark", name, "2026-11-07T15:00:00+00:00")


def filled(*names):
    queue = JobQueue()
    for name in names:
        queue.add(job(name))
    return queue


def labels(queue):
    return [j.label for j in queue.jobs]


class Printer:
    """Plays a script: one entry per call, an exception to raise or None for success."""

    def __init__(self, *script):
        self.script, self.printed = list(script), []

    def __call__(self, rows, count, density):
        outcome = self.script.pop(0) if self.script else None
        if outcome:
            raise outcome
        self.printed.append(rows)


def nothing_failed(job_, reason):
    raise AssertionError(f"unexpected failure: {reason}")


def test_jobs_print_in_order_and_leave_the_queue():
    queue = filled("a", "b", "c")
    order = []
    assert queue.drain(lambda rows, count, density: order.append(queue.jobs[0].label), nothing_failed) == 3
    assert order == ["a", "b", "c"] and len(queue) == 0


def test_the_limit_is_five():
    assert MAX_JOBS == 5


def test_sixth_job_is_refused_and_says_so():
    queue = filled(*"abcde")
    with pytest.raises(QueueFull):
        queue.add(job("f"))
    assert labels(queue) == list("abcde")


@pytest.mark.parametrize("error", [PrinterUnreachable("off"), PrinterSilent("asleep"), PrinterNotReady("lid open")])
def test_printer_not_available_keeps_the_job_and_stops(error):
    queue = filled("a", "b")
    printer = Printer(error)
    assert queue.drain(printer, nothing_failed) == 0
    assert labels(queue) == ["a", "b"] and printer.printed == []


def test_stops_midway_and_keeps_the_rest_in_order():
    queue = filled("a", "b", "c")
    assert queue.drain(Printer(None, PrinterUnreachable("gone")), nothing_failed) == 1
    assert labels(queue) == ["b", "c"]


def test_a_job_lost_while_printing_is_not_repeated_and_is_reported():
    """It may have printed in part. Sending it again could print it twice."""
    queue = filled("a", "b")
    reports = []
    printer = Printer(PrinterError("connection lost while printing"))
    assert queue.drain(printer, lambda j, why: reports.append((j.label, why))) == 1
    assert labels(queue) == [] and len(printer.printed) == 1
    assert reports == [("a", "connection lost while printing")]


def test_survives_a_restart_as_json():
    queue = filled("a", "b")
    again = JobQueue.from_list(json.loads(json.dumps(queue.to_list())))
    assert labels(again) == ["a", "b"]
    assert again.jobs[0] == queue.jobs[0]


def test_stored_job_is_compressed():
    big = Job(bytes(48 * 2000), 2000, "dark", "a", "t")
    assert len(json.dumps(big.to_dict())) < 2000


@pytest.mark.parametrize("damaged", [[{"rows": "not base64!!"}], [{"label": "no rows"}], [{"rows": "AAAA", "row_count": 1,
                                     "density": "dark", "label": "a", "created": "t"}], ["text"]])
def test_damaged_store_does_not_stop_startup(damaged):
    assert len(JobQueue.from_list(damaged)) == 0


def test_empty_store():
    assert len(JobQueue.from_list(None)) == 0


def test_a_good_job_survives_a_damaged_neighbour():
    good = job("good").to_dict()
    assert labels(JobQueue.from_list([{"rows": "x"}, good])) == ["good"]


def test_clear():
    queue = filled("a")
    queue.clear()
    assert len(queue) == 0


def test_labels_get_twice_the_room_and_do_not_eat_the_normal_queue():
    """Asked for 08.11.2026: the label queue about twice as large."""
    assert MAX_LABEL_JOBS == 2 * MAX_JOBS
    queue = JobQueue()
    for i in range(MAX_LABEL_JOBS):
        queue.add(Job(b"\x00" * 48, 1, "dark", f"label{i}", "t", "label"))
    with pytest.raises(QueueFull):
        queue.add(Job(b"\x00" * 48, 1, "dark", "one more", "t", "label"))
    queue.add(job("normal"))    # a full label queue leaves room for a normal print
    assert len(queue) == MAX_LABEL_JOBS + 1


def test_kind_survives_a_restart():
    import json
    queue = JobQueue([Job(b"\x00" * 48, 1, "dark", "l", "t", "label")])
    assert JobQueue.from_list(json.loads(json.dumps(queue.to_list()))).jobs[0].kind == "label"
