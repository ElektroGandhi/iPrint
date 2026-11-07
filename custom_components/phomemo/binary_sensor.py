"""Lid and paper. Both say "problem" when on, so a dashboard can treat them alike."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import PhomemoEntity

SENSORS = (("lid_open", BinarySensorDeviceClass.OPENING), ("paper_out", BinarySensorDeviceClass.PROBLEM))


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(PhomemoBinary(entry.runtime_data, key, cls) for key, cls in SENSORS)


class PhomemoBinary(PhomemoEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, device_class) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        return getattr(self.coordinator.data, self._key) if self.coordinator.data else None
