"""Setup by address. HA's Bluetooth discovery only sees BLE, so the T02 cannot be discovered from here.

The flow proves the address by asking the printer for its status; nothing is stored for a printer it could not reach.
"""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import CONF_NOTIFY, CONF_PRINT_SERVER, CONF_WEBHOOK_ID, DOMAIN
from .printer import Printer, PrinterError

_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


class PhomemoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IPrintOptionsFlow()

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


class IPrintOptionsFlow(OptionsFlow):
    """The optional print server (beta). The address stays the same when it is switched off and on again."""

    _new_id: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = self.config_entry.options
        # One id for this dialog: showing a new one on each step would store a different one than the user copied.
        self._new_id = self._new_id or webhook.async_generate_id()
        webhook_id = options.get(CONF_WEBHOOK_ID) or self._new_id
        if user_input is not None:
            return self.async_create_entry(data={**user_input, CONF_WEBHOOK_ID: webhook_id})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_PRINT_SERVER, default=options.get(CONF_PRINT_SERVER, False)): bool,
                vol.Optional(CONF_NOTIFY, default=options.get(CONF_NOTIFY, "")): str,
            }),
            description_placeholders={"path": webhook.async_generate_path(webhook_id)},
        )
