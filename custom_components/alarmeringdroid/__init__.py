"""The AlarmeringDroid P2000 integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .config_flow import _async_get_client
from .const import CONF_NAME, DOMAIN
from .coordinator import AlarmeringDroidCoordinator
from .search import SearchConfig
from .zone import ZoneResolver

PLATFORMS = [Platform.SENSOR]

type AlarmeringDroidConfigEntry = ConfigEntry[AlarmeringDroidCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: AlarmeringDroidConfigEntry
) -> bool:
    """Set up one AlarmeringDroid search."""
    config = SearchConfig.from_entry_data(entry.data[CONF_NAME], entry.options)
    client = await _async_get_client(hass)

    resolver: ZoneResolver | None = None
    if config.zone:
        resolver = ZoneResolver(
            hass, client, entry.entry_id, config.name, config.zone
        )
        await resolver.async_resolve()
        entry.async_on_unload(resolver.async_start())

    coordinator = AlarmeringDroidCoordinator(hass, entry, client, config, resolver)
    entry.runtime_data = coordinator

    # Platforms first: the coordinator only reschedules while it has listeners.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_create_background_task(
        hass, coordinator.async_start(), "alarmeringdroid_first_poll"
    )
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: AlarmeringDroidConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: AlarmeringDroidConfigEntry
) -> bool:
    """Unload the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: AlarmeringDroidConfigEntry
) -> None:
    """Delete repair issues belonging to a removed entry."""
    for issue in ("zone_no_postcode", "zone_missing"):
        ir.async_delete_issue(hass, DOMAIN, f"{issue}_{entry.entry_id}")
