"""Cursor, dedupe, thread rules and client-side filters for polled messages."""

from __future__ import annotations

from .const import DIENST_LIFELINER, SEEN_MAX
from .models import Message
from .search import SearchConfig


def _add_bounded(store: dict[int, None], key: int) -> None:
    """Add key to an insertion-ordered dict, evicting the oldest beyond SEEN_MAX."""
    store.pop(key, None)
    store[key] = None
    while len(store) > SEEN_MAX:
        del store[next(iter(store))]


class Tracker:
    """Decide which polled messages are new and relevant."""

    def __init__(self, config: SearchConfig) -> None:
        self._config = config
        self.cursor: int | None = None
        self.seen: dict[int, None] = {}
        self.prio_threads: dict[int, None] = {}

    def matches(self, message: Message) -> bool:
        """Client-side filter only (no dedupe)."""
        cfg = self._config
        lifeliner = cfg.all_lifeliners and message.dienst_id == DIENST_LIFELINER
        if cfg.diensten and message.dienst_id not in cfg.diensten and not lifeliner:
            return False
        if cfg.regios and message.regio_id not in cfg.regios and not lifeliner:
            return False
        if (
            cfg.prio1_only
            and not message.prio1
            and message.thread_id not in self.prio_threads
        ):
            return False
        return True

    def _register_prio(self, messages: list[Message]) -> None:
        for m in messages:
            if m.prio1:
                _add_bounded(self.prio_threads, m.thread_id)

    def prime(self, messages: list[Message]) -> Message | None:
        """Silently mark everything seen; return newest message passing filters."""
        self._register_prio(messages)
        for m in sorted(messages, key=lambda x: x.id):
            _add_bounded(self.seen, m.id)
        if messages:
            self.advance(max(m.id for m in messages))
        for m in sorted(messages, key=lambda x: x.id, reverse=True):
            if self.matches(m):
                return m
        return None

    def process(self, messages: list[Message]) -> list[Message]:
        """Return accepted new messages ascending by id; update state."""
        prev = self.cursor
        self._register_prio(messages)
        accepted: list[Message] = []
        for m in sorted(messages, key=lambda x: x.id):
            if m.id in self.seen or (prev is not None and m.id <= prev):
                continue
            _add_bounded(self.seen, m.id)
            if self.matches(m):
                accepted.append(m)
        if messages:
            self.advance(max(m.id for m in messages))
        return accepted

    def advance(self, high_id: int | None) -> None:
        """Move the cursor forward; it never decreases."""
        if high_id is None:
            return
        if self.cursor is None or high_id > self.cursor:
            self.cursor = high_id
