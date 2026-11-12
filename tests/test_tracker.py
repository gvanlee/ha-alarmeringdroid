"""Tests for the tracker (cursor, dedupe, thread and client-side filters)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.alarmeringdroid.models import Message
from custom_components.alarmeringdroid.search import SearchConfig
from custom_components.alarmeringdroid.tracker import Tracker

TZ = ZoneInfo("Europe/Amsterdam")


def msg(id, parent=None, dienst=3, regio=9, prio1=False):
    return Message(
        id=id, parent_id=parent, melding="m", dienst="d", dienst_id=dienst,
        regio="r", regio_id=regio, plaats="p", postcode=None, straat=None,
        timestamp=datetime(2026, 7, 2, 15, 0, tzinfo=TZ), prio1=prio1, grip=0,
        brandinfo=None, capcodes=(), latitude=None, longitude=None,
    )


def config(**kw):
    base = dict(
        name="t", regios=(), diensten=(), postcodes=(), capcodes=(), zone=None,
        prio1_only=False, all_lifeliners=False, scan_interval=60,
    )
    base.update(kw)
    return SearchConfig(**base)


def ids(messages):
    return [m.id for m in messages]


def test_prime_is_silent_and_sets_cursor():
    t = Tracker(config())
    assert t.cursor is None
    newest = t.prime([msg(10), msg(11)])
    assert newest.id == 11
    assert t.cursor == 11
    assert t.process([msg(10), msg(11)]) == []


def test_new_message_once():
    t = Tracker(config())
    t.prime([msg(10)])
    assert ids(t.process([msg(12)])) == [12]
    assert t.process([msg(12)]) == []


def test_followup_returned_as_parent():
    t = Tracker(config())
    t.prime([msg(10)])
    assert ids(t.process([msg(10), msg(13, parent=10)])) == [13]


def test_old_parent_never_fires():
    t = Tracker(config())
    t.prime([msg(50)])
    assert ids(t.process([msg(5), msg(51, parent=5)])) == [51]


def test_thread_child_other_dienst_dropped():
    t = Tracker(config(diensten=(3,)))
    assert t.process([msg(60, dienst=3), msg(61, parent=60, dienst=2)]) == [msg(60, dienst=3)]
    assert t.process([msg(61, parent=60, dienst=2)]) == []
    assert 61 in t.seen


def test_prio_follows_thread():
    t = Tracker(config(prio1_only=True))
    t.prime([msg(70, prio1=True)])
    assert ids(t.process([msg(70, prio1=True), msg(71, parent=70)])) == [71]
    assert t.process([msg(72)]) == []


def test_prime_returns_newest_matching_using_prio_threads():
    t = Tracker(config(prio1_only=True))
    newest = t.prime([msg(70, prio1=True), msg(71, parent=70), msg(72)])
    assert newest.id == 71


def test_prime_returns_none_when_nothing_matches():
    t = Tracker(config(diensten=(1,)))
    assert t.prime([msg(10)]) is None
    assert t.cursor == 10


def test_prio_registered_for_old_messages_in_process():
    t = Tracker(config(prio1_only=True))
    t.prime([msg(100)])
    # old prio1 parent (below cursor) still flags its thread
    assert ids(t.process([msg(5, prio1=True), msg(101, parent=5)])) == [101]


def test_lifeliner_toggle():
    on = Tracker(config(regios=(9,), diensten=(2,), all_lifeliners=True))
    assert ids(on.process([msg(80, dienst=5, regio=1)])) == [80]
    off = Tracker(config(regios=(9,), diensten=(2,), all_lifeliners=False))
    assert off.process([msg(80, dienst=5, regio=1)]) == []


def test_regio_filter():
    t = Tracker(config(regios=(9,)))
    assert ids(t.process([msg(1, regio=9), msg(2, regio=3)])) == [1]


def test_duplicate_ids_in_one_response():
    t = Tracker(config())
    assert ids(t.process([msg(90), msg(90)])) == [90]


def test_results_ascending():
    t = Tracker(config())
    assert ids(t.process([msg(3), msg(1), msg(2)])) == [1, 2, 3]


def test_advance_never_decreases():
    t = Tracker(config())
    t.cursor = 100
    t.advance(None)
    assert t.cursor == 100
    t.advance(50)
    assert t.cursor == 100
    t.advance(150)
    assert t.cursor == 150


def test_advance_from_none():
    t = Tracker(config())
    t.advance(7)
    assert t.cursor == 7


def test_cursor_moves_in_process():
    t = Tracker(config(diensten=(1,)))
    t.prime([msg(10, dienst=1)])
    t.process([msg(20, dienst=3)])
    assert t.cursor == 20


def test_seen_bounded():
    t = Tracker(config())
    t.process([msg(i) for i in range(1, 1501)])
    assert len(t.seen) <= 1000
    assert 1500 in t.seen and 1 not in t.seen


def test_prio_threads_bounded():
    t = Tracker(config())
    t.process([msg(i, prio1=True) for i in range(1, 1501)])
    assert len(t.prio_threads) <= 1000
    assert 1500 in t.prio_threads
