"""notify.send_message prints the message. That is what makes the printer usable from any automation."""
from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.exceptions import ServiceValidationError

from .entity import PhomemoEntity
from .render import render_text


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PhomemoNotify(entry.runtime_data, "printer")])


class PhomemoNotify(PhomemoEntity, NotifyEntity):
    @property
    def available(self) -> bool:
        return True  # try anyway: the printer may just have been switched on

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        try:
            image = await self.hass.async_add_executor_job(render_text, message, title)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        await self.coordinator.async_print_image(image, label=title or message)
