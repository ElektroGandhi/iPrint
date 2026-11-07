"""Battery level."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from .entity import PhomemoEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PhomemoBattery(entry.runtime_data, "battery")])


class PhomemoBattery(PhomemoEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery if self.coordinator.data else None
