"""Search configuration, input normalization and find-filter builder."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from .const import (
    CONF_ALL_LIFELINERS,
    CONF_CAPCODES,
    CONF_DIENSTEN,
    CONF_POSTCODES,
    CONF_PRIO1_ONLY,
    CONF_REGIOS,
    CONF_SCAN_INTERVAL,
    CONF_ZONE,
    DEFAULT_SCAN_INTERVAL,
    FIND_LIMIT,
    MIN_SCAN_INTERVAL,
    RADIUS_KM,
)

_POSTCODE_RE = re.compile(r"^[1-9]\d{3}([A-Z]{2})?$")
_CAPCODE_RE = re.compile(r"^\d{6,9}$")


@dataclass(frozen=True)
class SearchConfig:
    """One configured search."""

    name: str
    regios: tuple[int, ...]
    diensten: tuple[int, ...]
    postcodes: tuple[str, ...]
    capcodes: tuple[str, ...]
    zone: str | None
    prio1_only: bool
    all_lifeliners: bool
    scan_interval: int

    @classmethod
    def from_entry_data(cls, name: str, options: Mapping[str, Any]) -> SearchConfig:
        """Build a config from stored entry options."""
        interval = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return cls(
            name=name,
            regios=tuple(options.get(CONF_REGIOS) or ()),
            diensten=tuple(options.get(CONF_DIENSTEN) or ()),
            postcodes=tuple(options.get(CONF_POSTCODES) or ()),
            capcodes=tuple(options.get(CONF_CAPCODES) or ()),
            zone=options.get(CONF_ZONE) or None,
            prio1_only=bool(options.get(CONF_PRIO1_ONLY, False)),
            all_lifeliners=bool(options.get(CONF_ALL_LIFELINERS, False)),
            scan_interval=max(MIN_SCAN_INTERVAL, int(interval)),
        )

    @property
    def has_location(self) -> bool:
        """Return True if any location criterion is set."""
        return bool(self.regios or self.postcodes or self.capcodes or self.zone)


def _split(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def normalize_postcodes(text: str) -> tuple[str, ...]:
    """Parse a comma separated postcode list."""
    result: list[str] = []
    for part in _split(text):
        code = re.sub(r"\s+", "", part).upper()
        if not _POSTCODE_RE.match(code):
            raise ValueError("invalid_postcode")
        if code not in result:
            result.append(code)
    return tuple(result)


def normalize_capcodes(text: str) -> tuple[str, ...]:
    """Parse a comma separated capcode list (kept as strings)."""
    result: list[str] = []
    for part in _split(text):
        if not _CAPCODE_RE.match(part):
            raise ValueError("invalid_capcode")
        if part not in result:
            result.append(part)
    return tuple(result)


def build_find_filter(
    config: SearchConfig, zone_postcode: str | None, minid: int | None
) -> dict[str, Any]:
    """Build the api2 find filter.

    prio1 is deliberately never sent: the server would apply it to the
    matched row and hide prio1=0 follow-ups of a prio-1 thread. Prio-1
    filtering is done client-side.
    """
    result: dict[str, Any] = {}
    if config.regios:
        result["regios"] = list(config.regios)
    if config.diensten:
        result["diensten"] = list(config.diensten)
    postcodes = list(config.postcodes)
    if zone_postcode and zone_postcode not in postcodes:
        postcodes.append(zone_postcode)
    if postcodes:
        result["postcode"] = postcodes
        result["straal"] = RADIUS_KM
    if config.capcodes:
        result["capcodes"] = list(config.capcodes)
    if config.all_lifeliners:
        result["lifeliners"] = 1
    if minid is not None:
        result["minid"] = minid
    result["limit"] = FIND_LIMIT
    return result
