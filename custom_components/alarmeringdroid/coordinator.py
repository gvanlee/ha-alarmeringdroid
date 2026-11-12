"""Polling coordinator: silent priming, event firing and back-off."""

from __future__ import annotations

from datetime import timedelta
import asyncio
import logging
import random

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AlarmeringDroidClient, ApiError
from .const import DOMAIN, EVENT_MESSAGE, MAX_BACKOFF, STAGGER_MAX
from .models import Message, flatten_meldingen
from .search import SearchConfig, build_find_filter
from .tracker import Tracker
from .zone import ZoneResolver

_LOGGER = logging.getLogger(__name__)


class AlarmeringDroidCoordinator(DataUpdateCoordinator[Message | None]):
    """Poll api2 for one search and fire an event per new message."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AlarmeringDroidClient,
        config: SearchConfig,
        zone: ZoneResolver | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {config.name}",
            update_interval=timedelta(seconds=config.scan_interval),
        )
        self._entry = entry
        self._client = client
        self._config = config
        self._zone = zone
        self.tracker = Tracker(config)
        self._primed = False
        self._failures = 0

    async def async_start(self) -> None:
        """Stagger the first poll so searches don't hit the server together."""
        await asyncio.sleep(random.uniform(0, STAGGER_MAX))
        await self.async_refresh()

    async def _async_update_data(self) -> Message | None:
        cfg = self._config
        zone_pc = self._zone.postcode if self._zone else None
        if not cfg.has_location:
            raise UpdateFailed("search has no location filter")
        if cfg.zone and zone_pc is None:
            # Polling without the zone would drop an AND-ed location filter.
            raise UpdateFailed("zone postcode not resolved")

        minid = self.tracker.cursor if self._primed else None
        try:
            result = await self._client.find(build_find_filter(cfg, zone_pc, minid))
        except ApiError as err:
            self._failures += 1
            backoff = min(cfg.scan_interval * 2**self._failures, MAX_BACKOFF)
            self.update_interval = timedelta(
                seconds=max(cfg.scan_interval, backoff)
            )
            raise UpdateFailed(str(err)) from err

        self._failures = 0
        self.update_interval = timedelta(seconds=cfg.scan_interval)

        messages = flatten_meldingen(result.meldingen, dt_util.now())
        if not self._primed:
            latest = self.tracker.prime(messages)
            self.tracker.advance(result.high_id)
            # Without a cursor the next poll would be an unbounded scan; stay
            # unprimed (silent) until the server gives us a starting point.
            self._primed = self.tracker.cursor is not None
            return latest

        new = self.tracker.process(messages)
        self.tracker.advance(result.high_id)
        for m in new:
            self.hass.bus.async_fire(
                EVENT_MESSAGE,
                {
                    "entry_id": self._entry.entry_id,
                    "search_name": cfg.name,
                    "is_followup": m.is_followup,
                    "incident_prio1": self.tracker.in_prio_incident(m),
                    **m.as_attributes(),
                },
            )
        return new[-1] if new else self.data
