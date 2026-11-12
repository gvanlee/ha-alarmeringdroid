"""Message model and parsing for the AlarmeringDroid api2 responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from .const import MESSAGE_URL

_LOGGER = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Amsterdam")

_PLAATS_PREFIX = re.compile(r"^(\d{4}[A-Z]{2})\s+")
_DATUM = re.compile(r"^\s*(\d{1,2})-(\d{1,2})")
_TIJD = re.compile(r"(\d{1,2}):(\d{2})")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if result != 0 else None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _opt(value: Any) -> str | None:
    return _text(value) or None


@dataclass(frozen=True)
class Message:
    """A single P2000 message."""

    id: int
    parent_id: int | None
    melding: str
    dienst: str
    dienst_id: int
    regio: str
    regio_id: int
    plaats: str
    postcode: str | None
    straat: str | None
    timestamp: datetime
    prio1: bool
    grip: int
    brandinfo: str | None
    capcodes: tuple[tuple[str, str], ...]
    latitude: float | None
    longitude: float | None

    @property
    def thread_id(self) -> int:
        """Id of the thread (the parent's id for follow-ups)."""
        return self.parent_id or self.id

    @property
    def is_followup(self) -> bool:
        """Whether this message is a follow-up of another message."""
        return self.parent_id is not None

    @property
    def url(self) -> str:
        """Public URL of the message."""
        return MESSAGE_URL.format(id=self.id)

    def as_attributes(self) -> dict[str, Any]:
        """Return the message as state/event attributes."""
        attrs: dict[str, Any] = {
            "id": self.id,
            "melding": self.melding,
            "dienst": self.dienst,
            "dienst_id": self.dienst_id,
            "regio": self.regio,
            "regio_id": self.regio_id,
            "plaats": self.plaats,
            "postcode": self.postcode,
            "straat": self.straat,
            "timestamp": self.timestamp.isoformat(),
            "prio1": self.prio1,
            "grip": self.grip,
            "brandinfo": self.brandinfo,
            "capcodes": [
                {"capcode": code, "omschrijving": desc}
                for code, desc in self.capcodes
            ],
            "parent_id": self.parent_id,
            "url": self.url,
        }
        if self.latitude is not None:
            attrs["latitude"] = self.latitude
        if self.longitude is not None:
            attrs["longitude"] = self.longitude
        return attrs


def parse_timestamp(datum: str | None, tijd: str | None, now: datetime) -> datetime:
    """Build an aware timestamp from dd-mm and HH:MM (first time in a range)."""
    dm = _DATUM.match(_text(datum))
    tm = _TIJD.search(_text(tijd))
    if not dm or not tm:
        return now
    day, month = int(dm.group(1)), int(dm.group(2))
    hour, minute = int(tm.group(1)), int(tm.group(2))
    year = now.year
    for _ in range(5):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=TZ)
        except ValueError:
            year -= 1
            continue
        if candidate > now + timedelta(days=1):
            year -= 1
            continue
        return candidate
    return now


def parse_message(raw: dict, parent_id: int | None, now: datetime) -> Message:
    """Parse one raw api2 message."""
    msg_id = _int(raw.get("id"))
    if not msg_id:
        raise ValueError("message without id")
    plaats = _text(raw.get("plaats"))
    prefix = _PLAATS_PREFIX.match(plaats)
    postcode = _opt(raw.get("postcode"))
    if prefix:
        postcode = postcode or prefix.group(1)
        plaats = plaats[prefix.end():].strip()
    raw_caps = raw.get("capcodes")
    capcodes = tuple(
        (_text(c.get("capcode")), _text(c.get("omschrijving")))
        for c in (raw_caps if isinstance(raw_caps, list) else [])
        if isinstance(c, dict)
    )
    return Message(
        id=msg_id,
        parent_id=parent_id,
        melding=_text(raw.get("melding")),
        dienst=_text(raw.get("dienst")),
        dienst_id=_int(raw.get("dienstid")),
        regio=_text(raw.get("regio")),
        regio_id=_int(raw.get("regioid")),
        plaats=plaats,
        postcode=postcode,
        straat=_opt(raw.get("straat")),
        timestamp=parse_timestamp(raw.get("datum"), raw.get("tijd"), now),
        prio1=_text(raw.get("prio1")) == "1",
        grip=_int(raw.get("grip")),
        brandinfo=_opt(raw.get("brandinfo")),
        capcodes=capcodes,
        latitude=_float(raw.get("lat")),
        longitude=_float(raw.get("lon")),
    )


def flatten_meldingen(raw: list[dict], now: datetime) -> list[Message]:
    """Flatten parents and subitems, unique by id, sorted ascending by id.

    On duplicate ids an occurrence with parent_id set beats a standalone one;
    otherwise the first occurrence wins.
    """
    by_id: dict[int, Message] = {}
    for item in raw:
        try:
            parent = parse_message(item, None, now)
        except (ValueError, TypeError, AttributeError) as err:
            _LOGGER.debug("Skipping malformed melding %r: %s", item, err)
            continue
        candidates = [parent]
        subitems = item.get("subitems")
        for sub in subitems if isinstance(subitems, list) else []:
            try:
                candidates.append(parse_message(sub, parent.id, now))
            except (ValueError, TypeError, AttributeError) as err:
                _LOGGER.debug("Skipping malformed subitem %r: %s", sub, err)
        for msg in candidates:
            existing = by_id.get(msg.id)
            if existing is None or (
                existing.parent_id is None and msg.parent_id is not None
            ):
                by_id[msg.id] = msg
    return sorted(by_id.values(), key=lambda m: m.id)
