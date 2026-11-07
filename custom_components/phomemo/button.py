"""Feed paper; print a test page. Neither depends on the last poll: the printer may just have been switched on."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.button import ButtonEntity

from .entity import PhomemoEntity
from .render import render_text


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PhomemoFeed(entry.runtime_data, "feed"), PhomemoTestPage(entry.runtime_data, "test_page")])


class _AlwaysAvailable(PhomemoEntity):
    @property
    def available(self) -> bool:
        return True


class PhomemoFeed(_AlwaysAvailable, ButtonEntity):
    async def async_press(self) -> None:
        await self.coordinator.async_feed()


class PhomemoTestPage(_AlwaysAvailable, ButtonEntity):
    async def async_press(self) -> None:
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        image = await self.hass.async_add_executor_job(render_text, f"Home Assistant\n{when}\nÄÖÜ äöü ß", "Phomemo T02")
        await self.coordinator.async_print_image(image)
