"""Owns the printer and its queue: one user at a time, whatever comes in first."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
from typing import TypeVar

from PIL import Image

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_DENSITY, DOMAIN, POLL_SECONDS_AWAY, POLL_SECONDS_CONNECTED, POLL_SECONDS_WAITING
from .jobqueue import Job, JobQueue, QueueFull
from .printer import Printer, PrinterError, PrinterNotReady, PrinterUnreachable
from .protocol import Status
from .render import to_rows

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class IPrintCoordinator(DataUpdateCoordinator[Status]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(seconds=POLL_SECONDS_AWAY))
        self.printer = Printer(address)
        self.address = address
        self.density = DEFAULT_DENSITY
        self.firmware: str | None = None
        self.queue = JobQueue()
        self._lock = asyncio.Lock()
        self._store: Store[list[dict]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.queue")

    async def async_load_queue(self) -> None:
        self.queue = JobQueue.from_list(await self._store.async_load())

    async def _async_save_queue(self) -> None:
        await self._store.async_save(self.queue.to_list())

    def _away_interval(self) -> timedelta:
        return timedelta(seconds=POLL_SECONDS_WAITING if len(self.queue) else POLL_SECONDS_AWAY)

    async def _run(self, func: Callable[..., T], *args) -> T:
        return await self.hass.async_add_executor_job(func, *args)

    @staticmethod
    def _job_failed(job: Job, reason: str) -> None:
        _LOGGER.error("Dropped print job '%s': %s. It was not repeated, because it may have printed in part", job.label,
                      reason)

    async def _async_drain(self) -> None:
        """Print what is waiting. Call with the lock held."""
        if not len(self.queue):
            return
        before = len(self.queue)
        await self._run(self.queue.drain, self.printer.print_rows, self._job_failed)
        if len(self.queue) != before:
            await self._async_save_queue()

    async def _async_update_data(self) -> Status:
        async with self._lock:
            try:
                status = await self._run(self.printer.read_status, self.firmware is None)
            except PrinterError as err:
                self.update_interval = self._away_interval()
                raise UpdateFailed(str(err)) from err  # off or out of range: entities go unavailable, nothing more
            self.update_interval = timedelta(seconds=POLL_SECONDS_CONNECTED)
            if status.firmware:
                self.firmware = status.firmware
            if not status.lid_open and not status.paper_out:
                await self._async_drain()
            return status

    def _new_job(self, rows: bytes, count: int, density: str, label: str) -> Job:
        return Job(rows, count, density, label[:60], dt_util.utcnow().isoformat())

    async def async_print_image(self, image: Image.Image, density: str | None = None, label: str = "") -> None:
        """Print now if possible, otherwise wait in the queue. Raises only when the job is really lost."""
        rows, count = await self._run(to_rows, image)
        density = density or self.density
        async with self._lock:
            if len(self.queue):   # keep the order: others were first
                await self._async_enqueue(self._new_job(rows, count, density, label))
                return
            try:
                status = await self._run(self.printer.print_rows, rows, count, density, self.last_update_success)
            except (PrinterNotReady, PrinterUnreachable) as err:
                _LOGGER.info("Queued print job '%s': %s", label, err)
                await self._async_enqueue(self._new_job(rows, count, density, label))
                self.update_interval = self._away_interval()
                self._schedule_refresh()  # a new interval only applies to the next run; the planned one may be minutes off
                return
            except PrinterError as err:
                raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(status)

    async def _async_enqueue(self, job: Job) -> None:
        try:
            self.queue.add(job)
        except QueueFull as err:
            raise HomeAssistantError(str(err)) from err
        await self._async_save_queue()
        self.async_update_listeners()

    async def async_clear_queue(self) -> None:
        async with self._lock:
            self.queue.clear()
            await self._async_save_queue()
        self.async_update_listeners()

    async def async_close(self) -> None:
        async with self._lock:
            await self._run(self.printer.close)

    async def async_feed(self) -> None:
        async with self._lock:
            try:
                await self._run(self.printer.feed)
            except PrinterError as err:
                raise HomeAssistantError(str(err)) from err
