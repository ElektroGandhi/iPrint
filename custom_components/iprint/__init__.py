"""Phomemo T02 thermal printer over Bluetooth classic (RFCOMM)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError
import voluptuous as vol

from homeassistant.components import webhook as ha_webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType

from .const import CONF_PRINT_SERVER, CONF_WEBHOOK_ID, DENSITIES, DOMAIN, SERVICE_CLEAR_QUEUE, SERVICE_FEED, SERVICE_PRINT_IMAGE, SERVICE_PRINT_TEXT
from .coordinator import IPrintCoordinator
from .render import render_image, render_text
from .webhook import async_register as async_register_webhook

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NOTIFY, Platform.SELECT, Platform.SENSOR]
RETRY_AFTER_SETUP = 45
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type IPrintConfigEntry = ConfigEntry[IPrintCoordinator]

_TARGET = {vol.Optional(ATTR_DEVICE_ID): cv.string, vol.Optional("density"): vol.In(DENSITIES)}
TEXT_SCHEMA = vol.Schema({**_TARGET, vol.Required("text"): cv.string, vol.Optional("title"): cv.string,
                          vol.Optional("size", default=28): vol.All(vol.Coerce(int), vol.Range(min=14, max=96))})
IMAGE_SCHEMA = vol.Schema({**_TARGET, vol.Required("path"): cv.string})
FEED_SCHEMA = vol.Schema({vol.Optional(ATTR_DEVICE_ID): cv.string})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> IPrintCoordinator:
    entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN)]
    device_id = call.data.get(ATTR_DEVICE_ID)
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        entries = [e for e in entries if device and e.entry_id in device.config_entries]
    if len(entries) != 1:
        raise ServiceValidationError("Name exactly one printer (device_id) or configure only one")
    return entries[0].runtime_data


def _load_picture(path: str):
    try:
        with Image.open(path) as image:
            return render_image(image)
    except (OSError, UnidentifiedImageError, ValueError) as err:
        raise HomeAssistantError(f"Cannot print {path}: {err}") from err


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def print_text(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        try:
            image = await hass.async_add_executor_job(
                render_text, call.data["text"], call.data.get("title"), call.data["size"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        await coordinator.async_print_image(image, call.data.get("density"), call.data.get("title") or call.data["text"])

    async def print_image(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        path = call.data["path"]
        if not Path(path).is_absolute() or not hass.config.is_allowed_path(path):
            raise ServiceValidationError(f"{path} is not in allowlist_external_dirs")
        image = await hass.async_add_executor_job(_load_picture, path)
        await coordinator.async_print_image(image, call.data.get("density"), Path(path).name)

    async def feed(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_feed()

    async def clear_queue(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_clear_queue()

    hass.services.async_register(DOMAIN, SERVICE_PRINT_TEXT, print_text, TEXT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PRINT_IMAGE, print_image, IMAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_FEED, feed, FEED_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_QUEUE, clear_queue, FEED_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IPrintConfigEntry) -> bool:
    coordinator = IPrintCoordinator(hass, entry, entry.data[CONF_ADDRESS])
    await coordinator.async_load_queue()
    # Deliberately no first_refresh that must succeed: a printer that is switched off is the normal case.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if entry.options.get(CONF_PRINT_SERVER):
        async_register_webhook(hass, coordinator, entry.options[CONF_WEBHOOK_ID])
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    if not coordinator.last_update_success:
        # The setup dialog has just closed its connection, and the printer refuses new ones for a while after that.
        async def _retry(_now) -> None:
            await coordinator.async_refresh()

        entry.async_on_unload(async_call_later(hass, RETRY_AFTER_SETUP, _retry))
    return True


async def _options_changed(hass: HomeAssistant, entry: IPrintConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IPrintConfigEntry) -> bool:
    if entry.options.get(CONF_PRINT_SERVER):
        ha_webhook.async_unregister(hass, entry.options[CONF_WEBHOOK_ID])
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_close()
    return unloaded
