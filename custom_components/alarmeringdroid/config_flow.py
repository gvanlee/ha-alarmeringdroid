"""Config flow and options flow for AlarmeringDroid P2000."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.loader import async_get_integration

from .api import AlarmeringDroidClient, ApiError
from .const import (
    CONF_ALL_LIFELINERS,
    CONF_CAPCODES,
    CONF_DIENSTEN,
    CONF_NAME,
    CONF_POSTCODES,
    CONF_PRIO1_ONLY,
    CONF_REGIOS,
    CONF_SCAN_INTERVAL,
    CONF_ZONE,
    CONF_ZONE_POSTCODE,
    DEFAULT_SCAN_INTERVAL,
    DIENSTEN,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    REGIOS,
)
from .search import (
    SearchConfig,
    build_find_filter,
    normalize_capcodes,
    normalize_postcodes,
)
from .zone import ZoneNotFound, lookup_zone_postcode


def _select(options: dict[int, str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[{"value": str(k), "label": v} for k, v in options.items()],
            multiple=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=3600,
        step=1,
        unit_of_measurement="s",
        mode=NumberSelectorMode.BOX,
    )
)


async def _async_get_client(hass: HomeAssistant) -> AlarmeringDroidClient:
    """Create an API client for validation."""
    integration = await async_get_integration(hass, DOMAIN)
    return AlarmeringDroidClient(
        async_get_clientsession(hass), f"HA-AlarmeringDroid/{integration.version}"
    )


def _filters_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Schema for the filter fields, optionally prefilled."""
    defaults = defaults or {}

    def suggested(key: str) -> dict[str, Any]:
        value = defaults.get(key)
        if value in (None, [], ""):
            return {}
        if isinstance(value, list):
            value = (
                ", ".join(str(v) for v in value)
                if key in (CONF_POSTCODES, CONF_CAPCODES)
                else [str(v) for v in value]
            )
        return {"suggested_value": value}

    return vol.Schema(
        {
            vol.Optional(CONF_REGIOS, description=suggested(CONF_REGIOS)): _select(
                REGIOS
            ),
            vol.Optional(
                CONF_DIENSTEN, description=suggested(CONF_DIENSTEN)
            ): _select(DIENSTEN),
            vol.Optional(
                CONF_POSTCODES, description=suggested(CONF_POSTCODES)
            ): TextSelector(),
            vol.Optional(
                CONF_CAPCODES, description=suggested(CONF_CAPCODES)
            ): TextSelector(),
            vol.Optional(CONF_ZONE, description=suggested(CONF_ZONE)): EntitySelector(
                EntitySelectorConfig(domain="zone")
            ),
            vol.Required(
                CONF_PRIO1_ONLY, default=defaults.get(CONF_PRIO1_ONLY, False)
            ): BooleanSelector(),
            vol.Required(
                CONF_ALL_LIFELINERS, default=defaults.get(CONF_ALL_LIFELINERS, False)
            ): BooleanSelector(),
        }
    )


def _interval_field(default: int) -> dict[Any, Any]:
    return {
        vol.Required(CONF_SCAN_INTERVAL, default=default): vol.All(
            _INTERVAL_SELECTOR, vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
        )
    }


async def async_validate_filters(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate and normalize filter input; return (options, errors)."""
    errors: dict[str, str] = {}
    options: dict[str, Any] = {
        CONF_REGIOS: [int(v) for v in user_input.get(CONF_REGIOS) or []],
        CONF_DIENSTEN: [int(v) for v in user_input.get(CONF_DIENSTEN) or []],
        CONF_POSTCODES: [],
        CONF_CAPCODES: [],
        CONF_ZONE: user_input.get(CONF_ZONE) or None,
        CONF_PRIO1_ONLY: bool(user_input.get(CONF_PRIO1_ONLY, False)),
        CONF_ALL_LIFELINERS: bool(user_input.get(CONF_ALL_LIFELINERS, False)),
    }
    try:
        options[CONF_POSTCODES] = list(
            normalize_postcodes(user_input.get(CONF_POSTCODES) or "")
        )
    except ValueError:
        errors[CONF_POSTCODES] = "invalid_postcode"
    try:
        options[CONF_CAPCODES] = list(
            normalize_capcodes(user_input.get(CONF_CAPCODES) or "")
        )
    except ValueError:
        errors[CONF_CAPCODES] = "invalid_capcode"
    if errors:
        return options, errors

    if not (
        options[CONF_REGIOS]
        or options[CONF_POSTCODES]
        or options[CONF_CAPCODES]
        or options[CONF_ZONE]
    ):
        errors["base"] = "no_location_filter"
        return options, errors

    client = await _async_get_client(hass)
    zone_postcode: str | None = None
    if options[CONF_ZONE]:
        try:
            zone_postcode = await lookup_zone_postcode(
                hass, client, options[CONF_ZONE]
            )
        except ZoneNotFound:
            errors[CONF_ZONE] = "zone_not_found"
        except ApiError:
            errors["base"] = "cannot_connect"
        else:
            if zone_postcode is None:
                errors[CONF_ZONE] = "zone_no_postcode"
        if errors:
            return options, errors
    # Stored so setup can still apply the zone filter when the lookup fails.
    options[CONF_ZONE_POSTCODE] = zone_postcode

    config = SearchConfig.from_entry_data("", options)
    try:
        await client.find(build_find_filter(config, zone_postcode, None))
    except ApiError:
        errors["base"] = "cannot_connect"
    return options, errors


class AlarmeringDroidConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow: name, filters, interval."""

    VERSION = 1

    def __init__(self) -> None:
        self._name: str = ""
        self._options: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AlarmeringDroidOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the search name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._name = user_input[CONF_NAME].strip()
            if self._name:
                return await self.async_step_filters()
            errors[CONF_NAME] = "name_required"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME): vol.All(str, vol.Length(min=1))}
            ),
            errors=errors,
        )

    async def async_step_filters(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate the filters."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._options, errors = await async_validate_filters(
                self.hass, user_input
            )
            if not errors:
                return await self.async_step_interval()
        return self.async_show_form(
            step_id="filters",
            data_schema=_filters_schema(user_input),
            errors=errors,
        )

    async def async_step_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the polling interval and create the entry."""
        if user_input is not None:
            options = {
                **self._options,
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
            }
            return self.async_create_entry(
                title=self._name, data={CONF_NAME: self._name}, options=options
            )
        return self.async_show_form(
            step_id="interval",
            data_schema=vol.Schema(_interval_field(DEFAULT_SCAN_INTERVAL)),
        )


class AlarmeringDroidOptionsFlow(OptionsFlow):
    """Options flow: all filters and the interval on one page."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit filters and interval."""
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options)
        if user_input is not None:
            options, errors = await async_validate_filters(self.hass, user_input)
            if not errors:
                options[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
                return self.async_create_entry(data=options)
            current = dict(user_input)
        interval = current.get(CONF_SCAN_INTERVAL) or DEFAULT_SCAN_INTERVAL
        schema = _filters_schema(current).extend(_interval_field(int(interval)))
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
