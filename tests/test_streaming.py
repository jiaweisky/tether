from __future__ import annotations

import asyncio

import pytest

from tether.engine.streaming import StreamingController


@pytest.mark.asyncio
async def test_finalize_emits_final_snapshot():
    emits: list[tuple[bool, str]] = []

    async def emit(final: bool, snapshot: str) -> None:
        emits.append((final, snapshot))

    controller = StreamingController(emit, interval_s=0.05)
    controller.push_text("Hello")
    controller.push_text(" world")
    await controller.wait_idle()
    await controller.finalize()
    assert emits[-1] == (True, "Hello world")


@pytest.mark.asyncio
async def test_interim_updates_are_merged():
    emits: list[tuple[bool, str]] = []

    async def emit(final: bool, snapshot: str) -> None:
        emits.append((final, snapshot))

    controller = StreamingController(emit, interval_s=0.02)
    controller.push_text("a")
    await asyncio.sleep(0.05)
    controller.push_text("b")
    await asyncio.sleep(0.05)
    await controller.finalize()
    assert emits[-1][1] == "ab"
    assert any(not final and snap for final, snap in emits)


@pytest.mark.asyncio
async def test_reasoning_shares_snapshot():
    emits: list[tuple[bool, str]] = []

    async def emit(final: bool, snapshot: str) -> None:
        emits.append((final, snapshot))

    controller = StreamingController(emit, interval_s=10.0)
    controller.push_reasoning("think")
    controller.push_text("answer")
    await controller.finalize()
    assert emits[-1] == (True, "think\n\nanswer")


@pytest.mark.asyncio
async def test_max_live_chars_disables_interim_but_final_kept():
    emits: list[tuple[bool, str]] = []

    async def emit(final: bool, snapshot: str) -> None:
        emits.append((final, snapshot))

    controller = StreamingController(emit, interval_s=0.01, max_live_chars=5)
    controller.push_text("0123456789")
    await asyncio.sleep(0.05)
    await controller.finalize()
    assert all(final for final, _ in emits)
    assert emits[-1][1] == "0123456789"


@pytest.mark.asyncio
async def test_emit_failure_disables_live_updates_but_final_sent():
    calls: list[tuple[bool, str]] = []

    async def emit(final: bool, snapshot: str) -> None:
        if not final:
            raise RuntimeError("invalid req_id")
        calls.append((final, snapshot))

    controller = StreamingController(emit, interval_s=0.01)
    controller.push_text("a")
    await asyncio.sleep(0.05)
    await controller.finalize()
    assert calls == [(True, "a")]


@pytest.mark.asyncio
async def test_idle_progress_sets_and_clears_status():
    emits: list[tuple[bool, str]] = []

    async def emit(final: bool, snapshot: str) -> None:
        emits.append((final, snapshot))

    controller = StreamingController(emit, interval_s=0.01, idle_progress_s=0.03)
    controller.push_text("answer")
    await asyncio.sleep(0.1)
    assert "Thinking" in controller.live_status()
    assert any(not final for final, _ in emits)
    controller.push_text(" more")
    assert controller.live_status() == ""
