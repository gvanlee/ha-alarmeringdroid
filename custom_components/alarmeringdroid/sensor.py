"""Most recent message sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_ICON, DIENST_ICONS, DOMAIN, STATE_MAX_LEN
from .coordinator import AlarmeringDroidCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor for one search."""
    async_add_entities([MostRecentMessageSensor(entry.runtime_data, entry)])


class MostRecentMessageSensor(
    CoordinatorEntity[AlarmeringDroidCoordinator], SensorEntity
):
    """State is the latest message text; attributes carry the details."""

    _attr_has_entity_name = True
    _attr_translation_key = "most_recent_message"

    def __init__(self, coordinator: AlarmeringDroidCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_most_recent_message"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="AlarmeringDroid",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str | None:
        """Return the (truncated) readable message text."""
        data = self.coordinator.data
        return data.text[:STATE_MAX_LEN] if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full message as attributes."""
        data = self.coordinator.data
        return data.as_attributes() if data else {}

    @property
    def icon(self) -> str:
        """Icon by service."""
        data = self.coordinator.data
        return DIENST_ICONS.get(data.dienst_id, DEFAULT_ICON) if data else DEFAULT_ICON
