"""Tests for the most-recent-message sensor."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alarmeringdroid.api import ApiConnectionError, FindResult
from custom_components.alarmeringdroid.const import DOMAIN

ENTITY = "sensor.test_most_recent_message"
OPTIONS = {
    "regios": [9], "diensten": [], "postcodes": [], "capcodes": [],
    "zone": None, "prio1_only": False, "all_lifeliners": False,
    "scan_interval": 60,
}


def raw(id=10, melding="A1 Alkmaar", dienstid="3"):
    return {
        "id": str(id), "melding": melding, "dienstid": dienstid, "regioid": "9",
        "dienst": "Ambulance", "regio": "Kennemerland", "plaats": "Alkmaar",
        "datum": "12-11", "tijd": "17:15", "prio1": "1", "grip": "0",
        "lat": "52.63", "lon": "4.75", "subitems": [],
    }


@pytest.fixture
async def setup_entry(hass: HomeAssistant):
    """Return a factory that sets up an entry with a patched find()."""
    entries = []
    patchers = [patch("random.uniform", return_value=3600)]
    patchers[0].start()

    async def factory(find: AsyncMock):
        patcher = patch(
            "custom_components.alarmeringdroid.api.AlarmeringDroidClient.find",
            find,
        )
        patcher.start()
        patchers.append(patcher)
        entry = MockConfigEntry(
            domain=DOMAIN, title="Test", data={"name": "Test"}, options=OPTIONS
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entries.append(entry)
        return entry

    yield factory
    for entry in entries:
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for patcher in patchers:
        patcher.stop()


async def test_state_and_attributes(hass: HomeAssistant, setup_entry) -> None:
    find = AsyncMock(return_value=FindResult(meldingen=[raw()], high_id=None))
    entry = await setup_entry(find)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "A1 Alkmaar"
    assert state.attributes["dienst"] == "Ambulance"
    assert state.attributes["url"].endswith("/10")
    assert state.attributes["latitude"] == 52.63


async def test_long_text_truncated(hass: HomeAssistant, setup_entry) -> None:
    text = ("x" * 99 + "\n") * 2
    text += "y" * (300 - len(text))
    assert len(text) == 300
    find = AsyncMock(
        return_value=FindResult(meldingen=[raw(melding=text)], high_id=None)
    )
    entry = await setup_entry(find)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert len(state.state) == 255
    assert len(state.attributes["melding"]) == 300


async def test_icon_by_dienst(hass: HomeAssistant, setup_entry) -> None:
    find = AsyncMock(
        return_value=FindResult(meldingen=[raw(dienstid="2")], high_id=None)
    )
    entry = await setup_entry(find)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["icon"] == "mdi:fire-truck"


async def test_unavailable_on_api_error(hass: HomeAssistant, setup_entry) -> None:
    find = AsyncMock(side_effect=ApiConnectionError("boom"))
    entry = await setup_entry(find)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "unavailable"
