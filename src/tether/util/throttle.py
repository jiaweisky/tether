"""Asynchronous token-bucket rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class TokenBucket:
    """Allow at most ``rate_per_min`` acquisitions per minute.

    A ``None`` rate disables limiting. ``acquire`` waits until a token is
    available, refilling at a steady rate with an initial burst of one minute's
    worth of tokens.
    """

    def __init__(
        self,
        rate_per_min: int | None,
        *,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate_per_s = (rate_per_min / 60.0) if rate_per_min else None
        self.capacity = float(burst if burst is not None else (rate_per_min or 0))
        self._tokens = self.capacity
        self._clock = clock
        self._last = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        rate = self.rate_per_s
        if rate is None or self.capacity <= 0:
            return
        async with self._lock:
            available = self._refill(rate)
            if available < 1:
                await asyncio.sleep((1 - available) / rate)
                self._refill(rate)
            self._tokens = max(0.0, self._tokens - 1)

    def _refill(self, rate: float) -> float:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * rate)
        self._last = now
        return self._tokens
