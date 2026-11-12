"""Tests for the api2 client."""

import re
from pathlib import Path

import aiohttp
import pytest

from custom_components.alarmeringdroid.api import (
    AlarmeringDroidClient,
    ApiConnectionError,
    ApiResponseError,
)
from custom_components.alarmeringdroid.const import BASE_URL

FIXTURES = Path(__file__).parent / "fixtures"
FIND = re.compile(r".*/find/.*")
POSTCODE = re.compile(r".*/postcode/.*")
UA = "HA-AlarmeringDroid/0.1.0"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
async def client(hass, aioclient_mock):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    return AlarmeringDroidClient(async_get_clientsession(hass), UA)


def requested(aioclient_mock) -> tuple[str, dict]:
    """Return (raw URL string, headers) of the single request made."""
    assert len(aioclient_mock.mock_calls) == 1
    method, url, data, headers = aioclient_mock.mock_calls[0]
    return url.raw_path, headers


async def test_find_url_and_headers(client, aioclient_mock):
    aioclient_mock.get(
        FIND,
        text=load("find_empty.json"),
    )
    await client.find({"regios": [9], "limit": 30})
    path, headers = requested(aioclient_mock)
    assert path.endswith("/find/%7B%22regios%22%3A%5B9%5D%2C%22limit%22%3A30%7D/JSON")
    assert headers["User-Agent"] == UA


async def test_find_parses(client, aioclient_mock):
    aioclient_mock.get(FIND, text=load("find_thread.json"))
    res = await client.find({"limit": 5})
    assert len(res.meldingen) >= 1
    assert isinstance(res.high_id, int)
    assert any(m.get("subitems") for m in res.meldingen)


async def test_find_high_id_null(client, aioclient_mock):
    aioclient_mock.get(FIND, text=load("find_high_id_null.json"))
    assert (await client.find({})).high_id is None


async def test_find_non_json(client, aioclient_mock):
    aioclient_mock.get(
        FIND, text="<br />\n<b>Warning</b>: boom"
    )
    with pytest.raises(ApiResponseError):
        await client.find({})


async def test_find_empty_body(client, aioclient_mock):
    aioclient_mock.get(FIND, text="")
    with pytest.raises(ApiResponseError):
        await client.find({})


@pytest.mark.parametrize("body", ["[]", '{"high_id": 1}', '{"meldingen": "x"}'])
async def test_find_bad_shape(client, aioclient_mock, body):
    aioclient_mock.get(FIND, text=body)
    with pytest.raises(ApiResponseError):
        await client.find({})


async def test_find_http_error(client, aioclient_mock):
    aioclient_mock.get(FIND, status=503)
    with pytest.raises(ApiConnectionError, match="503"):
        await client.find({})


async def test_find_timeout(client, aioclient_mock):
    aioclient_mock.get(FIND, exc=TimeoutError())
    with pytest.raises(ApiConnectionError):
        await client.find({})


async def test_find_client_error(client, aioclient_mock):
    aioclient_mock.get(
        FIND, exc=aiohttp.ClientConnectionError()
    )
    with pytest.raises(ApiConnectionError):
        await client.find({})


async def test_lookup_postcode_found(client, aioclient_mock):
    aioclient_mock.get(
        f"{BASE_URL}/postcode/52.37000/4.89000", text=load("postcode_found.json")
    )
    assert await client.lookup_postcode(52.37, 4.89) == "1012RV"
    path, headers = requested(aioclient_mock)
    assert path.endswith("/postcode/52.37000/4.89000")
    assert headers["User-Agent"] == UA


async def test_lookup_postcode_missing(client, aioclient_mock):
    aioclient_mock.get(
        POSTCODE, text=load("postcode_missing.json")
    )
    assert await client.lookup_postcode(0.1, 0.1) is None
