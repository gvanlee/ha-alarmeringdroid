"""Tests for the config and options flow."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alarmeringdroid.api import ApiConnectionError
from custom_components.alarmeringdroid.const import DOMAIN

BASE = Path(__file__).parent.parent / "custom_components" / "alarmeringdroid"


@pytest.fixture(autouse=True)
def patched():
    """Patch setup and the API client."""
    with (
        patch(
            "custom_components.alarmeringdroid.async_setup_entry",
            return_value=True,
            create=True,
        ),
        patch(
            "custom_components.alarmeringdroid.async_unload_entry",
            return_value=True,
            create=True,
        ),
        patch(
            "custom_components.alarmeringdroid.config_flow.AlarmeringDroidClient.find",
            new_callable=AsyncMock,
        ) as find,
        patch(
            "custom_components.alarmeringdroid.config_flow.AlarmeringDroidClient.lookup_postcode",
            new_callable=AsyncMock,
        ) as lookup,
    ):
        find.return_value = None
        lookup.return_value = "1234AB"
        yield find, lookup


async def _to_filters(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Thuis"}
    )
    assert result["step_id"] == "filters"
    return result["flow_id"]


async def test_full_flow_creates_entry(hass: HomeAssistant, patched) -> None:
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"regios": ["9"], "postcodes": "1234 ab"}
    )
    assert result["step_id"] == "interval"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"scan_interval": 60}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Thuis"
    assert result["data"] == {"name": "Thuis"}
    assert result["options"]["regios"] == [9]
    assert result["options"]["postcodes"] == ["1234AB"]
    assert result["options"]["scan_interval"] == 60
    assert result["options"]["zone_postcode"] is None
    assert patched[0].await_count == 1


async def test_no_location_filter(hass: HomeAssistant) -> None:
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"diensten": ["1"]}
    )
    assert result["errors"] == {"base": "no_location_filter"}


async def test_invalid_postcode(hass: HomeAssistant) -> None:
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"postcodes": "abc"}
    )
    assert result["errors"] == {"postcodes": "invalid_postcode"}


async def test_invalid_capcode(hass: HomeAssistant) -> None:
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"capcodes": "12"}
    )
    assert result["errors"] == {"capcodes": "invalid_capcode"}


async def test_zone_without_postcode(hass: HomeAssistant, patched) -> None:
    patched[1].return_value = None
    hass.states.async_set("zone.home", "0", {"latitude": 52.0, "longitude": 4.0})
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"zone": "zone.home"}
    )
    assert result["errors"] == {"zone": "zone_no_postcode"}


async def test_zone_with_postcode_passes_to_find(
    hass: HomeAssistant, patched
) -> None:
    hass.states.async_set("zone.home", "0", {"latitude": 52.0, "longitude": 4.0})
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"zone": "zone.home"}
    )
    assert result["step_id"] == "interval"
    assert patched[0].await_args.args[0]["postcode"] == ["1234AB"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"scan_interval": 60}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"]["zone"] == "zone.home"
    assert result["options"]["zone_postcode"] == "1234AB"


async def test_cannot_connect(hass: HomeAssistant, patched) -> None:
    patched[0].side_effect = ApiConnectionError("boom")
    flow_id = await _to_filters(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"regios": ["9"]}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_interval_below_min_rejected(hass: HomeAssistant) -> None:
    flow_id = await _to_filters(hass)
    await hass.config_entries.flow.async_configure(flow_id, {"regios": ["9"]})
    with pytest.raises((InvalidData, vol.Invalid)):
        await hass.config_entries.flow.async_configure(
            flow_id, {"scan_interval": 10}
        )


async def test_options_flow_updates(hass: HomeAssistant, patched) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Thuis",
        data={"name": "Thuis"},
        options={"regios": [9], "postcodes": ["1234AB"], "scan_interval": 60},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"regios": ["1", "2"], "scan_interval": 120},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["regios"] == [1, 2]
    assert entry.options["postcodes"] == []
    assert entry.options["scan_interval"] == 120
    assert entry.options["zone_postcode"] is None


async def test_options_flow_stores_zone_postcode(
    hass: HomeAssistant, patched
) -> None:
    hass.states.async_set("zone.home", "0", {"latitude": 52.0, "longitude": 4.0})
    patched[1].return_value = "5678 cd"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Thuis",
        data={"name": "Thuis"},
        options={"regios": [9], "scan_interval": 60},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"zone": "zone.home", "scan_interval": 60}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["zone"] == "zone.home"
    assert entry.options["zone_postcode"] == "5678CD"


def _keys(obj, prefix=""):
    out = set()
    for k, v in obj.items():
        out.add(prefix + k)
        if isinstance(v, dict):
            out |= _keys(v, prefix + k + ".")
    return out


def test_translations_have_same_keys() -> None:
    sets = [
        _keys(json.loads((BASE / p).read_text()))
        for p in ("strings.json", "translations/en.json", "translations/nl.json")
    ]
    assert sets[0] == sets[1] == sets[2]
    assert "issues.zone_missing.title" in sets[0]


async def test_options_flow_keeps_input_on_error(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Thuis",
        data={"name": "Thuis"},
        options={"regios": [9], "scan_interval": 60},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"postcodes": "12x", "capcodes": "99", "regios": ["2"], "scan_interval": 90},
    )
    assert result["errors"]["postcodes"] == "invalid_postcode"
    suggested = {
        str(k): k.description["suggested_value"]
        for k in result["data_schema"].schema
        if k.description and "suggested_value" in k.description
    }
    assert suggested["postcodes"] == "12x"
    assert suggested["capcodes"] == "99"
    assert suggested["regios"] == ["2"]


async def test_schemas_serialize(hass: HomeAssistant) -> None:
    from homeassistant.helpers import config_validation as cv
    import voluptuous_serialize

    from custom_components.alarmeringdroid.config_flow import (
        _filters_schema,
        _interval_field,
    )

    interval = vol.Schema(_interval_field(60))
    options = _filters_schema().extend(_interval_field(60))
    for schema in (interval, options):
        assert voluptuous_serialize.convert(
            schema, custom_serializer=cv.custom_serializer
        )


async def test_whitespace_name_rejected(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "   "}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"name": "name_required"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "  Thuis  "}
    )
    assert result["step_id"] == "filters"


def test_name_required_error_translated() -> None:
    for p in ("strings.json", "translations/en.json", "translations/nl.json"):
        data = json.loads((BASE / p).read_text())
        assert data["config"]["error"]["name_required"]
