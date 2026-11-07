"""Print darkness, remembered across restarts."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DENSITIES
from .entity import PhomemoEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PhomemoDensity(entry.runtime_data, "density")])


class PhomemoDensity(PhomemoEntity, SelectEntity, RestoreEntity):
    _attr_options = list(DENSITIES)
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in DENSITIES:
            self.coordinator.density = last.state

    @property
    def available(self) -> bool:
        return True

    @property
    def current_option(self) -> str:
        return self.coordinator.density

    async def async_select_option(self, option: str) -> None:
        self.coordinator.density = option
        self.async_write_ha_state()
