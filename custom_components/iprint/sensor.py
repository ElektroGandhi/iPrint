"""Battery level."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from .entity import PhomemoEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PhomemoBattery(entry.runtime_data, "battery"), PhomemoQueue(entry.runtime_data, "queue")])


class PhomemoBattery(PhomemoEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery if self.coordinator.data else None


class PhomemoQueue(PhomemoEntity, SensorEntity):
    """How many jobs wait for the printer. Stays available while the printer is off: that is when it matters."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int:
        return len(self.coordinator.queue)

    @property
    def extra_state_attributes(self) -> dict:
        return {"jobs": [job.label for job in self.coordinator.queue.jobs]}
