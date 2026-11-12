"""Tests for the zone resolver."""

from unittest.mock import AsyncMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.alarmeringdroid.api import ApiConnectionError
from custom_components.alarmeringdroid.const import DOMAIN
from custom_components.alarmeringdroid.zone import (
    ZoneNotFound,
    ZoneResolver,
    lookup_zone_postcode,
)

ENTRY = "entry1"


def _set_zone(hass: HomeAssistant, lat=52.37, lon=4.89, **extra) -> None:
    hass.states.async_set(
        "zone.home", "0", {"latitude": lat, "longitude": lon, **extra}
    )


def _resolver(hass, client) -> ZoneResolver:
    return ZoneResolver(hass, client, ENTRY, "Thuis", "zone.home")


def _issue(hass, issue_id):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_resolve_success(hass: HomeAssistant) -> None:
    _set_zone(hass)
    client = AsyncMock()
    client.lookup_postcode.return_value = "1012ab"
    resolver = _resolver(hass, client)
    await resolver.async_resolve()
    assert resolver.postcode == "1012AB"
    client.lookup_postcode.assert_awaited_once_with(52.37, 4.89)
    assert not ir.async_get(hass).issues


async def test_resolve_no_postcode_creates_issue_keeps_last(
    hass: HomeAssistant,
) -> None:
    _set_zone(hass)
    client = AsyncMock()
    client.lookup_postcode.return_value = "1012AB"
    resolver = _resolver(hass, client)
    await resolver.async_resolve()
    client.lookup_postcode.return_value = None
    await resolver.async_resolve()
    assert resolver.postcode == "1012AB"
    issue = _issue(hass, f"zone_no_postcode_{ENTRY}")
    assert issue is not None
    assert issue.translation_key == "zone_no_postcode"
    assert issue.translation_placeholders == {"search": "Thuis", "zone": "zone.home"}
    assert not issue.is_fixable


async def test_invalid_postcode_counts_as_none(hass: HomeAssistant) -> None:
    _set_zone(hass)
    client = AsyncMock()
    client.lookup_postcode.return_value = "garbage"
    resolver = _resolver(hass, client)
    await resolver.async_resolve()
    assert resolver.postcode is None
    assert _issue(hass, f"zone_no_postcode_{ENTRY}") is not None
    assert await lookup_zone_postcode(hass, client, "zone.home") is None


async def test_issue_cleared_on_success(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.lookup_postcode.return_value = "1012AB"
    resolver = _resolver(hass, client)
    await resolver.async_resolve()  # no state yet
    assert _issue(hass, f"zone_missing_{ENTRY}") is not None
    _set_zone(hass)
    await resolver.async_resolve()
    assert resolver.postcode == "1012AB"
    assert not ir.async_get(hass).issues


async def test_zone_missing(hass: HomeAssistant) -> None:
    client = AsyncMock()
    resolver = _resolver(hass, client)
    await resolver.async_resolve()
    assert resolver.postcode is None
    issue = _issue(hass, f"zone_missing_{ENTRY}")
    assert issue is not None
    assert issue.translation_key == "zone_missing"
    client.lookup_postcode.assert_not_called()


async def test_lookup_zone_postcode_not_found(hass: HomeAssistant) -> None:
    with pytest.raises(ZoneNotFound):
        await lookup_zone_postcode(hass, AsyncMock(), "zone.nope")
    hass.states.async_set("zone.bad", "0", {})
    with pytest.raises(ZoneNotFound):
        await lookup_zone_postcode(hass, AsyncMock(), "zone.bad")


async def test_api_error_keeps_last_no_issue(hass: HomeAssistant) -> None:
    _set_zone(hass)
    client = AsyncMock()
    client.lookup_postcode.return_value = "1012AB"
    resolver = _resolver(hass, client)
    await resolver.async_resolve()
    client.lookup_postcode.side_effect = ApiConnectionError("boom")
    await resolver.async_resolve()
    assert resolver.postcode == "1012AB"
    assert not ir.async_get(hass).issues


async def test_reresolve_only_on_coordinate_change(hass: HomeAssistant) -> None:
    _set_zone(hass)
    client = AsyncMock()
    client.lookup_postcode.return_value = "1012AB"
    resolver = _resolver(hass, client)
    await resolver.async_resolve()
    unsub = resolver.async_start()
    _set_zone(hass, friendly_name="Other")
    await hass.async_block_till_done()
    assert client.lookup_postcode.await_count == 1
    _set_zone(hass, lat=52.40)
    await hass.async_block_till_done()
    assert client.lookup_postcode.await_count == 2
    hass.states.async_remove("zone.home")
    await hass.async_block_till_done()
    assert _issue(hass, f"zone_missing_{ENTRY}") is not None
    unsub()
