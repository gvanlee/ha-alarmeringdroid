"""Thin async client for the AlarmeringDroid api2 API."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import BASE_URL, REQUEST_TIMEOUT


class ApiError(Exception):
    """Base error for the AlarmeringDroid API."""


class ApiConnectionError(ApiError):
    """Network failure, timeout or non-200 status."""


class ApiResponseError(ApiError):
    """Response could not be understood."""


@dataclass(frozen=True)
class FindResult:
    """Result of a find request."""

    meldingen: list[dict[str, Any]]
    high_id: int | None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


class AlarmeringDroidClient:
    """Client for the api2 endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_agent: str,
        base_url: str = BASE_URL,
    ) -> None:
        self._session = session
        self._user_agent = user_agent
        self._base_url = base_url

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with self._session.get(
                # encoded=True: send the percent-encoded path exactly as built
                URL(url, encoded=True),
                headers={"User-Agent": self._user_agent},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise ApiConnectionError(f"HTTP status {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ApiConnectionError(f"Request failed: {err!r}") from err

        if not text.strip():
            raise ApiResponseError("Empty response body")
        try:
            data = json.loads(text)
        except ValueError as err:
            raise ApiResponseError("Response is not valid JSON") from err
        if not isinstance(data, dict):
            raise ApiResponseError("Response is not a JSON object")
        return data

    async def find(self, filter_: dict[str, Any]) -> FindResult:
        """Run a find query."""
        encoded = quote(json.dumps(filter_, separators=(",", ":")), safe="")
        data = await self._get_json(f"{self._base_url}/find/{encoded}/JSON")
        meldingen = data.get("meldingen")
        if not isinstance(meldingen, list):
            raise ApiResponseError("Response has no 'meldingen' list")
        return FindResult(meldingen=meldingen, high_id=_to_int(data.get("high_id")))

    async def lookup_postcode(self, lat: float, lon: float) -> str | None:
        """Return the uppercase postcode nearest to a point, or None."""
        data = await self._get_json(f"{self._base_url}/postcode/{lat:.5f}/{lon:.5f}")
        postcode = data.get("postcode")
        if not isinstance(postcode, str) or not postcode.strip():
            return None
        return postcode.strip().upper()
