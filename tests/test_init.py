"""Tests for entry setup, unload and reload."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alarmeringdroid.api import ApiConnectionError, FindResult
from custom_components.alarmeringdroid.const import DOMAIN

OPTIONS = {
    "regios": [9], "diensten": [], "postcodes": [], "capcodes": [],
    "zone": None, "prio1_only": False, "all_lifeliners": False,
    "scan_interval": 60,
}


def make_entry(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test", data={"name": "Test"},
        options=options or OPTIONS,
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    with (
        patch(
            "custom_components.alarmeringdroid.api.AlarmeringDroidClient.find",
            AsyncMock(return_value=FindResult(meldingen=[], high_id=None)),
        ),
        patch("random.uniform", return_value=3600),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        state = hass.states.get("sensor.test_most_recent_message")
        assert state is not None
        assert state.state == "unknown"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_options_change_reloads(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    with (
        patch(
            "custom_components.alarmeringdroid.api.AlarmeringDroidClient.find",
            AsyncMock(return_value=FindResult(meldingen=[], high_id=None)),
        ),
        patch("random.uniform", return_value=3600),
        patch(
            "custom_components.alarmeringdroid.AlarmeringDroidCoordinator",
            wraps=__import__(
                "custom_components.alarmeringdroid.coordinator",
                fromlist=["AlarmeringDroidCoordinator"],
            ).AlarmeringDroidCoordinator,
        ) as coord_cls,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert coord_cls.call_count == 1
        hass.config_entries.async_update_entry(
            entry, options={**OPTIONS, "scan_interval": 120}
        )
        await hass.async_block_till_done()
        assert coord_cls.call_count == 2
        assert entry.state is ConfigEntryState.LOADED
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_remove_entry_deletes_repair_issues(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    registry = ir.async_get(hass)
    for issue in ("zone_no_postcode", "zone_missing"):
        ir.async_create_issue(
            hass, DOMAIN, f"{issue}_{entry.entry_id}",
            is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=issue,
            translation_placeholders={"zone": "zone.x", "search": "Test"},
        )
    assert registry.async_get_issue(DOMAIN, f"zone_missing_{entry.entry_id}")
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, f"zone_missing_{entry.entry_id}") is None
    assert (
        registry.async_get_issue(DOMAIN, f"zone_no_postcode_{entry.entry_id}")
        is None
    )


ZONE_OPTIONS = {**OPTIONS, "regios": [], "zone": "zone.home"}
FIND = "custom_components.alarmeringdroid.api.AlarmeringDroidClient.find"
LOOKUP = "custom_components.alarmeringdroid.api.AlarmeringDroidClient.lookup_postcode"


def _set_zone(hass: HomeAssistant) -> None:
    hass.states.async_set("zone.home", "0", {"latitude": 52.0, "longitude": 4.0})


async def test_zone_api_error_without_stored_postcode_retries(
    hass: HomeAssistant,
) -> None:
    _set_zone(hass)
    entry = make_entry(hass, ZONE_OPTIONS)
    find = AsyncMock(return_value=FindResult(meldingen=[], high_id=None))
    with (
        patch(FIND, find),
        patch(LOOKUP, AsyncMock(side_effect=ApiConnectionError("down"))),
        patch("random.uniform", return_value=3600),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    find.assert_not_called()


async def test_zone_missing_without_stored_postcode_retries(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(hass, ZONE_OPTIONS)
    with (
        patch(FIND, AsyncMock()),
        patch(LOOKUP, AsyncMock()),
        patch("random.uniform", return_value=3600),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"zone_missing_{entry.entry_id}"
    )


async def test_zone_api_error_uses_stored_postcode(hass: HomeAssistant) -> None:
    _set_zone(hass)
    entry = make_entry(
        hass, {**ZONE_OPTIONS, "regios": [9], "zone_postcode": "1234AB"}
    )
    find = AsyncMock(return_value=FindResult(meldingen=[], high_id=None))
    with (
        patch(FIND, find),
        patch(LOOKUP, AsyncMock(side_effect=ApiConnectionError("down"))),
        patch("random.uniform", return_value=3600),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        await entry.runtime_data.async_refresh()
        assert find.await_args.args[0]["postcode"] == ["1234AB"]
        assert find.await_args.args[0]["regios"] == [9]
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_zone_fresh_lookup_overrides_stored_postcode(
    hass: HomeAssistant,
) -> None:
    _set_zone(hass)
    entry = make_entry(hass, {**ZONE_OPTIONS, "zone_postcode": "1234AB"})
    find = AsyncMock(return_value=FindResult(meldingen=[], high_id=None))
    with (
        patch(FIND, find),
        patch(LOOKUP, AsyncMock(return_value="5678CD")),
        patch("random.uniform", return_value=3600),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await entry.runtime_data.async_refresh()
        assert find.await_args.args[0]["postcode"] == ["5678CD"]
        # Runtime re-resolves are never written back to the entry options.
        assert entry.options["zone_postcode"] == "1234AB"
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_without_zone_deletes_zone_issues(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    registry = ir.async_get(hass)
    for issue in ("zone_no_postcode", "zone_missing"):
        ir.async_create_issue(
            hass, DOMAIN, f"{issue}_{entry.entry_id}",
            is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=issue,
            translation_placeholders={"zone": "zone.x", "search": "Test"},
        )
    with (
        patch(FIND, AsyncMock(return_value=FindResult(meldingen=[], high_id=None))),
        patch("random.uniform", return_value=3600),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get_issue(DOMAIN, f"zone_missing_{entry.entry_id}") is None
        assert (
            registry.async_get_issue(DOMAIN, f"zone_no_postcode_{entry.entry_id}")
            is None
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
