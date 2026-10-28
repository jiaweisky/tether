"""A bounded, time-expiring set used to drop duplicate inbound events."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable


class DedupCache:
    """Remember keys for a TTL window and report repeats.

    ``is_duplicate`` records the key on first sight and returns ``False``; a
    subsequent call within the window returns ``True``. The oldest entries are
    evicted once the window or the size bound is exceeded.
    """

    def __init__(
        self,
        ttl_s: float = 600.0,
        *,
        maxsize: int = 100_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_s = ttl_s
        self.maxsize = maxsize
        self._clock = clock
        self._items: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, key: str) -> bool:
        now = self._clock()
        self._evict(now)

        if key in self._items:
            return True

        self._items[key] = now
        return False

    def _evict(self, now: float) -> None:
        while self._items:
            _, timestamp = next(iter(self._items.items()))
            if now - timestamp < self.ttl_s and len(self._items) <= self.maxsize:
                break
            self._items.popitem(last=False)
