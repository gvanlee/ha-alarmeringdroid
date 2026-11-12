"""Resolve a zone entity to the postcode at its center."""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from .api import AlarmeringDroidClient, ApiError
from .const import DOMAIN
from .search import normalize_postcodes

_LOGGER = logging.getLogger(__name__)


class ZoneNotFound(Exception):
    """Zone state or its coordinates are not available."""


def _normalize(value: str | None) -> str | None:
    """Return a single normalized postcode, or None if absent/invalid."""
    if not value:
        return None
    try:
        codes = normalize_postcodes(value)
    except ValueError:
        return None
    return codes[0] if len(codes) == 1 else None


async def lookup_zone_postcode(
    hass: HomeAssistant, client: AlarmeringDroidClient, entity_id: str
) -> str | None:
    """Return the normalized postcode at the zone center, or None."""
    state = hass.states.get(entity_id)
    if state is None:
        raise ZoneNotFound(entity_id)
    lat = state.attributes.get("latitude")
    lon = state.attributes.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ZoneNotFound(entity_id)
    return _normalize(await client.lookup_postcode(float(lat), float(lon)))


class ZoneResolver:
    """Keeps the postcode of a zone up to date and manages repair issues."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AlarmeringDroidClient,
        entry_id: str,
        search_name: str,
        entity_id: str,
        postcode: str | None = None,
    ) -> None:
        self._hass = hass
        self._client = client
        self._entry_id = entry_id
        self._search_name = search_name
        self._entity_id = entity_id
        self.postcode: str | None = _normalize(postcode)

    @property
    def _no_postcode_id(self) -> str:
        return f"zone_no_postcode_{self._entry_id}"

    @property
    def _missing_id(self) -> str:
        return f"zone_missing_{self._entry_id}"

    def _create_issue(self, issue_id: str, key: str) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={
                "search": self._search_name,
                "zone": self._entity_id,
            },
        )

    async def async_resolve(self) -> None:
        """Look up the zone postcode and update state and issues."""
        try:
            postcode = await lookup_zone_postcode(
                self._hass, self._client, self._entity_id
            )
        except ZoneNotFound:
            ir.async_delete_issue(self._hass, DOMAIN, self._no_postcode_id)
            self._create_issue(self._missing_id, "zone_missing")
            return
        except ApiError as err:
            _LOGGER.warning(
                "Postcode lookup for %s failed: %s", self._entity_id, err
            )
            return
        if postcode is None:
            ir.async_delete_issue(self._hass, DOMAIN, self._missing_id)
            self._create_issue(self._no_postcode_id, "zone_no_postcode")
            return
        self.postcode = postcode
        ir.async_delete_issue(self._hass, DOMAIN, self._no_postcode_id)
        ir.async_delete_issue(self._hass, DOMAIN, self._missing_id)

    def async_start(self) -> Callable[[], None]:
        """Track the zone; re-resolve when its coordinates change."""

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            old = event.data["old_state"]
            new = event.data["new_state"]
            if new is not None and old is not None:
                if (
                    old.attributes.get("latitude") == new.attributes.get("latitude")
                    and old.attributes.get("longitude")
                    == new.attributes.get("longitude")
                ):
                    return
            self._hass.async_create_task(
                self.async_resolve(), f"alarmeringdroid zone resolve {self._entity_id}"
            )

        return async_track_state_change_event(
            self._hass, [self._entity_id], _changed
        )
