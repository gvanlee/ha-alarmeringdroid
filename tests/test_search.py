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


@pytest.mark.parametrize("bad", [None, "abc"])
def test_from_entry_bad_interval_uses_default(bad):
    assert SearchConfig.from_entry_data("x", {"scan_interval": bad}).scan_interval == 60


def test_from_entry_bare_strings_not_split_into_chars():
    c = SearchConfig.from_entry_data(
        "x",
        {"postcodes": "1234AB", "capcodes": "0126183", "regios": "9", "diensten": "1,2"},
    )
    assert c.postcodes == ("1234AB",)
    assert c.capcodes == ("0126183",)
    assert c.regios == (9,)
    assert c.diensten == (1, 2)


def test_from_entry_coerces_elements():
    c = SearchConfig.from_entry_data(
        "x", {"regios": ["9"], "capcodes": [126183, "0126183"]}
    )
    assert c.regios == (9,)
    assert c.capcodes == ("126183", "0126183")
    assert all(isinstance(x, str) for x in c.capcodes)


def test_from_entry_renormalizes_and_drops_invalid():
    c = SearchConfig.from_entry_data(
        "x",
        {
            "postcodes": ["1234 ab", "bogus", "1234AB"],
            "capcodes": ["12a", "0126183"],
            "regios": ["x", 3],
        },
    )
    assert c.postcodes == ("1234AB",)
    assert c.capcodes == ("0126183",)
    assert c.regios == (3,)
