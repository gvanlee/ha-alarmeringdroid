"""Tests for search config, normalization and find filter."""

import pytest

from custom_components.alarmeringdroid.search import (
    SearchConfig,
    build_find_filter,
    normalize_capcodes,
    normalize_postcodes,
)


def _cfg(**kw):
    base = dict(
        name="t",
        regios=(),
        diensten=(),
        postcodes=(),
        capcodes=(),
        zone=None,
        prio1_only=False,
        all_lifeliners=False,
        scan_interval=60,
    )
    base.update(kw)
    return SearchConfig(**base)


def test_normalize_postcodes():
    assert normalize_postcodes("1234 ab, 5678,1234AB") == ("1234AB", "5678")
    assert normalize_postcodes("  ") == ()
    for bad in ("0123AB", "12345", "1234A"):
        with pytest.raises(ValueError, match="invalid_postcode"):
            normalize_postcodes(bad)


def test_normalize_capcodes():
    assert normalize_capcodes(" 0126183 ,1404932") == ("0126183", "1404932")
    assert normalize_capcodes("") == ()
    with pytest.raises(ValueError, match="invalid_capcode"):
        normalize_capcodes("12a456")


def test_from_entry_clamps_interval():
    assert SearchConfig.from_entry_data("x", {"scan_interval": 5}).scan_interval == 15
    assert SearchConfig.from_entry_data("x", {}).scan_interval == 60


def test_from_entry_converts_lists():
    c = SearchConfig.from_entry_data(
        "x", {"regios": [9], "capcodes": ["0126183"], "zone": "zone.home"}
    )
    assert c.regios == (9,)
    assert c.capcodes == ("0126183",)
    assert c.zone == "zone.home"
    assert c.has_location
    assert not SearchConfig.from_entry_data("x", {}).has_location


def test_filter_locations_or_ed():
    r = build_find_filter(_cfg(postcodes=("1234AB", "5678")), "2011AB", None)
    assert r["postcode"] == ["1234AB", "5678", "2011AB"]
    assert r["straal"] == 5
    assert "postcode4" not in r


def test_filter_never_sends_prio1_or_freesearch():
    r = build_find_filter(_cfg(prio1_only=True, regios=(9,)), None, None)
    assert "prio1" not in r
    assert "freesearch" not in r


def test_filter_minimal():
    assert build_find_filter(_cfg(regios=(9,)), None, None) == {
        "regios": [9],
        "limit": 30,
    }


def test_filter_lifeliners_and_minid():
    r = build_find_filter(_cfg(all_lifeliners=True), None, 123)
    assert r["lifeliners"] == 1
    assert r["minid"] == 123


def test_capcodes_are_strings():
    r = build_find_filter(_cfg(capcodes=("0126183",)), None, None)
    assert r["capcodes"] == ["0126183"]
