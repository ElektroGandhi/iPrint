"""Setup by address. HA's Bluetooth discovery only sees BLE, so the T02 cannot be discovered from here.

The flow proves the address by asking the printer for its status; nothing is stored for a printer it could not reach.
"""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .printer import Printer, PrinterError

_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


class PhomemoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper().replace("-", ":")
            if not _MAC.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                printer = Printer(address)
                try:
                    await self.hass.async_add_executor_job(printer.read_status)
                except PrinterError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.hass.async_add_executor_job(printer.close)
                    return self.async_create_entry(title=f"T02 {address[-5:]}", data={CONF_ADDRESS: address})
        return self.async_show_form(step_id="user", errors=errors,
                                    data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}))
