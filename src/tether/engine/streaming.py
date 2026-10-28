"""Throttle and coalesce streaming updates for one turn.

Because most IM platforms can only refresh a message by re-sending its full
content, this controller keeps the latest snapshot and emits it on a timer using
a trailing-edge strategy: updates within the interval are merged, and only the
newest snapshot is ever sent. A boundary in the text (a paragraph or code-fence
break) can force an early flush, and rate-limited sends widen the interval.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from tether.metrics import metrics
from tether.util.logging import get_logger

log = get_logger("tether.streaming")

EmitFn = Callable[[bool, str], Awaitable[None]]

# Substrings that mark a natural place to flush the current snapshot early.
_BOUNDARIES = ("\n\n", "。", "！", "？", ".\n", "```")


class Clock(Protocol):
    def now(self) -> float: ...
    async def sleep(self, delay: float) -> None: ...


class RealClock:
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)


class RateLimited(Exception):
    """Raised by the emit callback when the platform rate-limits the update."""


class StreamingController:
    def __init__(
        self,
        emit: EmitFn,
        *,
        interval_s: float = 0.7,
        boundary_flush: bool = True,
        max_live_chars: int = 4000,
        rate_limit_backoff: float = 2.0,
        max_interval_s: float = 5.0,
        idle_progress_s: float = 2.0,
        idle_status: str = "🤔 Thinking…",
        clock: Clock | None = None,
    ) -> None:
        self._emit = emit
        self._interval = interval_s
        self._min_interval = interval_s
        self._max_interval = max_interval_s
        self._backoff = rate_limit_backoff
        self._boundary_flush = boundary_flush
        self._max_live_chars = max_live_chars
        self._idle_progress_s = idle_progress_s
        self._idle_status = idle_status
        self._clock = clock or RealClock()

        self.text = ""
        self.reasoning = ""
        self._tool_line: str | None = None
        self._status: str | None = None

        self._dirty = False
        self._closed = False
        self._force = False
        self._live_disabled = False
        self._last = 0.0
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._worker: asyncio.Task[None] | None = None

    # -- producer ----------------------------------------------------------
    def push_text(self, delta: str) -> None:
        if not delta:
            return
        self.text += delta
        self._invalidate()
        if self._boundary_flush and any(boundary in delta for boundary in _BOUNDARIES):
            self._force = True

    def push_reasoning(self, delta: str) -> None:
        if not delta:
            return
        self.reasoning += delta
        self._invalidate()

    def note_tool(self, name: str) -> None:
        self._tool_line = f"🔧 Using `{name}`"
        self._invalidate()

    def clear_tool(self) -> None:
        if self._tool_line is None:
            return
        self._tool_line = None
        self._invalidate()

    def snapshot(self) -> str:
        parts = [self.reasoning, self._tool_line, self.text]
        return "\n\n".join(part for part in parts if part)

    def live_status(self) -> str:
        """Transient lines shown while the turn is still working.

        The tool line and the idle "thinking" hint are display-only: they are
        appended to interim frames and dropped from the final flush.
        """
        parts = [line for line in (self._tool_line, self._status) if line]
        return "\n".join(parts)

    def mark_working(self) -> None:
        """Authoritative activity: a step/part just started, show the hint now.

        Called for ``step.started`` / ``text.started`` / ``reasoning.started``
        (and ``session.status busy``), so the indicator reflects the agent's real
        state instead of only the idle timer.
        """
        if self._closed or self._live_disabled:
            return
        self._status = self._idle_status
        self._dirty = True
        self._idle.clear()
        self._ensure_worker()
        self._wake.set()

    def _invalidate(self) -> None:
        self._status = None
        if len(self.text) >= self._max_live_chars:
            self._live_disabled = True
        self._dirty = True
        self._idle.clear()
        self._ensure_worker()
        self._wake.set()

    # -- worker ------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._loop())

    async def _loop(self) -> None:
        try:
            while not self._closed:
                await self._wake.wait()
                self._wake.clear()
                while self._should_emit():
                    await self._pace()
                    await self._emit_interim()
                self._idle.set()
                await self._maybe_idle_progress()
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise
        except Exception:  # pragma: no cover - defensive
            log.exception("streaming_worker_failed")

    async def _maybe_idle_progress(self) -> None:
        """When the turn is quiet, show a "working" hint so it doesn't look stalled."""
        if self._closed or self._idle_progress_s <= 0 or not self.snapshot():
            return
        waiter = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait({waiter}, timeout=self._idle_progress_s)
        finally:
            if not waiter.done():
                waiter.cancel()
        if self._closed or self._wake.is_set() or not self.snapshot():
            return
        self._status = self._idle_status
        try:
            await self._emit(False, self.snapshot())
            self._last = self._clock.now()
        except RateLimited:
            self._interval = min(self._max_interval, self._interval * self._backoff)
        except Exception:  # noqa: BLE001 - keep the turn alive
            self._live_disabled = True

    def _should_emit(self) -> bool:
        return self._dirty and not self._live_disabled and not self._closed

    async def _pace(self) -> None:
        """Wait out the remaining interval unless a boundary requested a flush."""
        if not self._force:
            elapsed = self._clock.now() - self._last
            delay = max(0.0, self._interval - elapsed)
            if delay:
                await self._clock.sleep(delay)
        self._force = False

    async def _emit_interim(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        try:
            await self._emit(False, self.snapshot())
            self._last = self._clock.now()
            self._interval = max(self._min_interval, self._interval / self._backoff)
        except RateLimited:
            metrics.inc("rate_limit_hits")
            self._interval = min(self._max_interval, self._interval * self._backoff)
            log.warning("streaming_rate_limited", interval=self._interval)
        except Exception:  # noqa: BLE001 - stop live updates; the final flush still sends
            self._live_disabled = True
            log.warning("streaming_emit_failed", exc_info=True)

    # -- lifecycle ---------------------------------------------------------
    def begin_segment(self) -> None:
        """Drop accumulated output so the next flush opens a fresh message.

        Used after an interaction (permission/question) is answered: the message
        opened before the user's reply is already sealed, and the agent's
        continuation must go into a new message below that reply.
        """
        self.text = ""
        self.reasoning = ""
        self._tool_line = None
        self._status = None
        self._dirty = False
        self._force = False
        self._live_disabled = False

    async def finalize(self) -> None:
        """Stop the timer and emit the final snapshot."""
        self._closed = True
        self._wake.set()
        await self._cancel_worker()
        self._idle.set()
        await self._emit(True, self.snapshot())

    async def close(self) -> None:
        """Stop the timer and discard any pending snapshot."""
        self._closed = True
        self._wake.set()
        await self._cancel_worker()

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def _cancel_worker(self) -> None:
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
