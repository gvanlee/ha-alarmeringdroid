"""Tests for the polling coordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.alarmeringdroid.api import (
    ApiConnectionError,
    FindResult,
)
from custom_components.alarmeringdroid.const import DOMAIN, EVENT_MESSAGE
from custom_components.alarmeringdroid.coordinator import (
    AlarmeringDroidCoordinator,
)
from custom_components.alarmeringdroid.search import SearchConfig


def raw(id, subitems=None):
    return {
        "id": str(id), "melding": f"m{id}", "dienstid": "3", "regioid": "9",
        "dienst": "Ambulance", "regio": "Kennemerland", "plaats": "Alkmaar",
        "datum": "12-11", "tijd": "17:15", "prio1": "0", "grip": "0",
        "subitems": subitems or [],
    }


def result(*items, high_id=None):
    return FindResult(meldingen=list(items), high_id=high_id)


def config(**kw):
    base = dict(
        name="t", regios=(9,), diensten=(), postcodes=(), capcodes=(),
        zone=None, prio1_only=False, all_lifeliners=False, scan_interval=60,
    )
    base.update(kw)
    return SearchConfig(**base)


def make(hass: HomeAssistant, client, cfg=None, zone=None):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return AlarmeringDroidCoordinator(hass, entry, client, cfg or config(), zone)


async def test_first_poll_silent(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10), raw(11)))
    coord = make(hass, client)
    events = async_capture_events(hass, EVENT_MESSAGE)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.data.id == 11
    assert events == []
    assert "minid" not in client.find.await_args.args[0]


async def test_second_poll_fires_events(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10), raw(11)))
    coord = make(hass, client)
    await coord.async_refresh()
    events = async_capture_events(hass, EVENT_MESSAGE)
    client.find.return_value = result(raw(12))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert client.find.await_args.args[0]["minid"] == 11
    assert len(events) == 1
    data = events[0].data
    assert data["entry_id"] == coord._entry.entry_id
    assert data["search_name"] == "t"
    assert data["is_followup"] is False
    assert data["melding"] == "m12"
    assert coord.data.id == 12


async def test_followup_event(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    coord = make(hass, client)
    await coord.async_refresh()
    events = async_capture_events(hass, EVENT_MESSAGE)
    client.find.return_value = result(raw(10, [raw(13)]))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["is_followup"] is True
    assert events[0].data["parent_id"] == 10
    assert coord.data.id == 13


async def test_no_new_keeps_data(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    coord = make(hass, client)
    await coord.async_refresh()
    events = async_capture_events(hass, EVENT_MESSAGE)
    client.find.return_value = result()
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.data.id == 10
    assert events == []


async def test_empty_first_poll_still_primes(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result())
    coord = make(hass, client)
    await coord.async_refresh()
    events = async_capture_events(hass, EVENT_MESSAGE)
    client.find.return_value = result(raw(20))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_failed_priming_stays_unprimed(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(side_effect=ApiConnectionError("x"))
    coord = make(hass, client)
    await coord.async_refresh()
    events = async_capture_events(hass, EVENT_MESSAGE)
    client.find = AsyncMock(return_value=result(raw(10)))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert events == []
    assert coord.data.id == 10


async def test_backoff(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(side_effect=ApiConnectionError("down"))
    coord = make(hass, client)
    seen = []
    for _ in range(5):
        await coord.async_refresh()
        assert coord.last_update_success is False
        seen.append(coord.update_interval)
    assert seen == [timedelta(seconds=s) for s in (120, 240, 480, 600, 600)]
    client.find = AsyncMock(return_value=result(raw(10)))
    await coord.async_refresh()
    assert coord.last_update_success is True
    assert coord.update_interval == timedelta(seconds=60)


async def test_zone_unresolved_no_request(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    zone = MagicMock(postcode=None)
    cfg = config(regios=(), zone="zone.home")
    coord = make(hass, client, cfg, zone)
    await coord.async_refresh()
    assert coord.last_update_success is False
    client.find.assert_not_called()


async def test_zone_unresolved_with_other_filters_no_request(
    hass: HomeAssistant,
) -> None:
    """Never poll with the zone's AND-ed location filter dropped."""
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    zone = MagicMock(postcode=None)
    coord = make(hass, client, config(zone="zone.home", capcodes=("123456",)), zone)
    await coord.async_refresh()
    assert coord.last_update_success is False
    client.find.assert_not_called()


async def test_zone_configured_without_resolver_no_request(
    hass: HomeAssistant,
) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    coord = make(hass, client, config(zone="zone.home"), None)
    await coord.async_refresh()
    assert coord.last_update_success is False
    client.find.assert_not_called()


async def test_no_location_no_request(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    coord = make(hass, client, config(regios=(), diensten=(3,)))
    await coord.async_refresh()
    assert coord.last_update_success is False
    client.find.assert_not_called()


async def test_zone_resolved_adds_postcode(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10)))
    zone = MagicMock(postcode="1234AB")
    coord = make(hass, client, config(zone="zone.home"), zone)
    await coord.async_refresh()
    assert coord.last_update_success is True
    assert client.find.await_args.args[0]["postcode"] == ["1234AB"]
    assert client.find.await_args.args[0]["regios"] == [9]


async def test_cursor_advances_to_high_id(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result(raw(10), high_id=999))
    coord = make(hass, client)
    await coord.async_refresh()
    client.find.return_value = result(high_id=999)
    await coord.async_refresh()
    assert client.find.await_args.args[0]["minid"] == 999


async def test_incident_prio1_on_followup_of_prio1_thread(
    hass: HomeAssistant,
) -> None:
    client = MagicMock()
    client.find = AsyncMock(return_value=result())
    coord = make(hass, client)
    await coord.async_refresh()
    events = async_capture_events(hass, EVENT_MESSAGE)
    client.find.return_value = result({**raw(30), "prio1": "1"})
    await coord.async_refresh()
    client.find.return_value = result(
        {**raw(30), "prio1": "1", "subitems": [raw(31)]}
    )
    await coord.async_refresh()
    client.find.return_value = result(raw(40))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == [30, 31, 40]
    assert [e.data["prio1"] for e in events] == [True, False, False]
    assert [e.data["incident_prio1"] for e in events] == [True, True, False]
