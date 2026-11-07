"""Jobs waiting for the printer. No Home Assistant in here, so all of it can be tested."""
from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
import zlib

from .printer import PrinterError, PrinterNotReady, PrinterUnreachable

MAX_JOBS = 5


class QueueFull(Exception):
    """Say so instead of dropping a job without a word."""


@dataclass
class Job:
    rows: bytes
    row_count: int
    density: str
    label: str
    created: str

    def to_dict(self) -> dict:
        return {"rows": base64.b64encode(zlib.compress(self.rows)).decode(), "row_count": self.row_count,
                "density": self.density, "label": self.label, "created": self.created}

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(zlib.decompress(base64.b64decode(data["rows"])), data["row_count"], data["density"],
                   data["label"], data["created"])


class JobQueue:
    def __init__(self, jobs: list[Job] | None = None) -> None:
        self.jobs = jobs or []

    def __len__(self) -> int:
        return len(self.jobs)

    def add(self, job: Job) -> None:
        if len(self.jobs) >= MAX_JOBS:
            raise QueueFull(f"The print queue is full ({MAX_JOBS} jobs)")
        self.jobs.append(job)

    def clear(self) -> None:
        self.jobs.clear()

    def to_list(self) -> list[dict]:
        return [job.to_dict() for job in self.jobs]

    @classmethod
    def from_list(cls, data: list[dict] | None) -> "JobQueue":
        """Skip what cannot be read: a damaged file must not stop the integration from starting."""
        jobs = []
        for item in data or []:
            try:
                jobs.append(Job.from_dict(item))
            except (KeyError, TypeError, ValueError, zlib.error):
                continue
        return cls(jobs[:MAX_JOBS])

    def drain(self, print_rows: Callable[[bytes, int, str], object], failed: Callable[[Job, str], None]) -> int:
        """Print in order until the queue is empty or the printer cannot go on. Returns the number printed.

        Not ready or unreachable happens before anything is sent, so the job stays. Any other error comes after sending
        began: the job leaves the queue, because repeating it could print it twice.
        """
        printed = 0
        while self.jobs:
            job = self.jobs[0]
            try:
                print_rows(job.rows, job.row_count, job.density)
            except (PrinterNotReady, PrinterUnreachable):
                break
            except PrinterError as err:
                self.jobs.pop(0)
                failed(job, str(err))
                continue
            self.jobs.pop(0)
            printed += 1
        return printed
