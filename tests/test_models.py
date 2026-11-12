"""Tests for message parsing."""

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.alarmeringdroid.models import (
    flatten_meldingen,
    parse_message,
    parse_timestamp,
)

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 7, 2, 15, 0, tzinfo=TZ)


def child_raw():
    return {
        "id": "3642467", "melding": "B 12401 RITNR 27839 2134 HOOFDDORP Ontslag",
        "dienstid": "3", "regioid": "9", "dienst": "Ambulance",
        "regio": "Kennemerland", "plaats": "Hoofddorp", "straat": "",
        "datum": "02-07", "tijd": "14:08", "lat": "52.31263", "lon": "4.65055",
        "prio1": "0", "brandinfo": None, "grip": "0",
        "capcodes": [
            {"capcode": "0126401", "omschrijving": "???"},
            {"capcode": "0126999", "omschrijving": "Monitorcode"},
        ],
        "capstring": "...",
    }


def parent_raw():
    return {
        "id": "3642436", "melding": "B 12183 RITNR 27836 2134 HOOFDDORP Overplaatsing",
        "dienstid": "3", "regioid": "9", "dienst": "Ambulance",
        "regio": "Kennemerland", "plaats": "Hoofddorp", "straat": "",
        "datum": "02-07", "tijd": "14:03 - 14:08", "lat": "52.31263",
        "lon": "4.65055", "prio1": "0", "brandinfo": None, "grip": "0",
        "capcodes": [
            {"capcode": "0126183", "omschrijving": "Ambulance VZA Hoofddorp 183"},
            {"capcode": "0126999", "omschrijving": "Monitorcode"},
        ],
        "capstring": "...",
        "subitems": [child_raw()],
    }


def test_parse_basic():
    m = parse_message(parent_raw(), None, NOW)
    assert m.id == 3642436
    assert m.dienst_id == 3
    assert m.regio == "Kennemerland"
    assert m.latitude == 52.31263
    assert m.prio1 is False
    assert m.capcodes[0] == ("0126183", "Ambulance VZA Hoofddorp 183")


def test_flatten_parent_with_subitems():
    msgs = flatten_meldingen([parent_raw()], NOW)
    assert [m.id for m in msgs] == [3642436, 3642467]
    assert msgs[1].parent_id == 3642436
    assert msgs[1].is_followup is True
    assert msgs[0].is_followup is False
    assert msgs[1].thread_id == 3642436


def test_flatten_dedupes_ids():
    standalone_child = child_raw()
    msgs = flatten_meldingen(
        [standalone_child, parent_raw(), parent_raw()], NOW
    )
    assert [m.id for m in msgs] == [3642436, 3642467]
    # the occurrence with parent_id set wins over the standalone one
    assert msgs[1].parent_id == 3642436
    # and first occurrence wins among equals
    a, b = parent_raw(), parent_raw()
    a["melding"], b["melding"] = "first", "second"
    msgs = flatten_meldingen([a, b], NOW)
    assert [m.melding for m in msgs if m.id == 3642436] == ["first"]


def test_plaats_prefix_stripped():
    raw = parent_raw()
    raw["plaats"] = "2134AB  Hoofddorp"
    assert parse_message(raw, None, NOW).plaats == "Hoofddorp"


def test_garbage_values():
    raw = parent_raw()
    raw.update(lat="", lon=None, grip="", straat="")
    m = parse_message(raw, None, NOW)
    assert m.latitude is None
    assert m.longitude is None
    assert m.grip == 0
    assert m.straat is None
    raw.update(lat="0", lon="0")
    assert parse_message(raw, None, NOW).latitude is None


def test_missing_id():
    raw = parent_raw()
    raw["id"] = None
    try:
        parse_message(raw, None, NOW)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_timestamp_parent_range():
    assert parse_timestamp("02-07", "14:03 - 14:08", NOW) == datetime(
        2026, 7, 2, 14, 3, tzinfo=TZ
    )


def test_timestamp_new_year():
    now = datetime(2027, 1, 1, 0, 1, tzinfo=TZ)
    ts = parse_timestamp("31-12", "23:59", now)
    assert ts == datetime(2026, 12, 31, 23, 59, tzinfo=TZ)


def test_timestamp_garbage():
    assert parse_timestamp("", "14:00", NOW) == NOW
    assert parse_timestamp("02-07", None, NOW) == NOW


def test_timestamp_leap_day():
    now = datetime(2027, 3, 1, 12, 0, tzinfo=TZ)
    assert parse_timestamp("29-02", "10:00", now) == datetime(
        2024, 2, 29, 10, 0, tzinfo=TZ
    )


def test_as_attributes():
    m = parse_message(parent_raw(), None, NOW)
    attrs = m.as_attributes()
    assert attrs["url"] == "https://www.alarmeringdroid.nl/toonmelding/3642436"
    assert attrs["timestamp"] == "2026-07-02T14:03:00+02:00"
    assert attrs["capcodes"][0] == {
        "capcode": "0126183", "omschrijving": "Ambulance VZA Hoofddorp 183"
    }
    assert attrs["latitude"] == 52.31263
    raw = parent_raw()
    raw["lat"] = ""
    attrs = parse_message(raw, None, NOW).as_attributes()
    assert "latitude" not in attrs
    assert set(attrs) == {
        "id", "melding", "dienst", "dienst_id", "regio", "regio_id", "plaats",
        "postcode", "straat", "timestamp", "prio1", "grip", "brandinfo",
        "capcodes", "parent_id", "url", "longitude",
    }
