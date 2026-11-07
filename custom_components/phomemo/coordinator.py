"""Polls the printer now and then and serialises every use of it: the printer takes one client at a time."""
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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_DENSITY, DOMAIN, POLL_MINUTES
from .printer import Printer, PrinterError
from .protocol import Status
from .render import to_rows

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class PhomemoCoordinator(DataUpdateCoordinator[Status]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(minutes=POLL_MINUTES))
        self.printer = Printer(address)
        self.address = address
        self.density = DEFAULT_DENSITY
        self.firmware: str | None = None
        self._lock = asyncio.Lock()

    async def _locked(self, func: Callable[..., T], *args) -> T:
        async with self._lock:
            return await self.hass.async_add_executor_job(func, *args)

    async def _async_update_data(self) -> Status:
        try:
            status = await self._locked(self.printer.read_status, self.firmware is None)
        except PrinterError as err:
            raise UpdateFailed(str(err)) from err  # off or out of range: entities go unavailable, nothing more
        if status.firmware:
            self.firmware = status.firmware
        return status

    async def async_print_image(self, image: Image.Image, density: str | None = None) -> None:
        """Send one page. Raises for the user when it did not end up on paper."""
        rows, count = await self.hass.async_add_executor_job(to_rows, image)
        try:
            status = await self._locked(self.printer.print_rows, rows, count, density or self.density)
        except PrinterError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(status)

    async def async_feed(self) -> None:
        try:
            await self._locked(self.printer.feed)
        except PrinterError as err:
            raise HomeAssistantError(str(err)) from err


