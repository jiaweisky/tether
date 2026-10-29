from __future__ import annotations

import time

import pytest
from fakes import FakeAgentClient

from tether.agent.events import PERMISSION_ASKED, Event
from tether.app import TetherApp
from tether.config import Config
from tether.connectors.fake import FakeConnector
from tether.models import Conversation, InboundMessage, Sender


async def make_app(tmp_path, config: Config | None = None):
    config = config or Config()
    conn = FakeConnector()
    client = FakeAgentClient()
    app = TetherApp(
        config,
        db_path=str(tmp_path / "t.db"),
        connectors=[conn],
        client_factory=lambda _endpoint: client,
    )
    await app.store.connect()
    app.connectors[conn.name] = conn
    await conn.start(app._on_item)
    return app, conn, client


def inbound(text: str, *, kind="direct", conv_id="d1", message_id="m1", name="Alice"):
    return InboundMessage(
        channel="fake",
        message_id=message_id,
        conversation=Conversation(channel="fake", kind=kind, id=conv_id),
        sender=Sender(id="u1", name=name),
        text=text,
    )


@pytest.mark.asyncio
async def test_reconcile_seeds_incomplete_turn_text(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]

    # Simulate lost live deltas: the durable transcript has the full text.
    client.active.add(sid)
    client.message_store[sid] = [
        {"type": "assistant", "content": [{"type": "text", "text": "complete answer"}]}
    ]
    await app._reconcile("http://fake", client)

    engine = app._turns[sid]
    assert engine.controller.text == "complete answer"


@pytest.mark.asyncio
async def test_reconcile_finishes_turn_without_live_engine(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    # Drop the engine to emulate a bridge restart mid-turn.
    app._turns.pop(sid, None)
    app._turn_queue.pop(sid, None)
    client.active.add(sid)
    client.message_store[sid] = [
        {"type": "assistant", "content": [{"type": "text", "text": "recovered"}]}
    ]
    await app._reconcile("http://fake", client)
    assert conn.last_text() == "recovered"


@pytest.mark.asyncio
async def test_reconcile_restores_and_surfaces_pending_permission(tmp_path):
    from tether.agent.events import PendingPermission

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("do it"))
    sid = client.prompts[0]["sid"]
    client.add_permission(
        PendingPermission(id="per_1", session_id=sid, action="bash", resources=["x"])
    )
    await app._reconcile("http://fake", client)

    route = await app.router.get_by_session(sid)
    assert "per_1" in route.pending_interactions
    assert conn.cards, "a surfaced permission should render a card"


@pytest.mark.asyncio
async def test_restore_hitl_does_not_duplicate_known_pending(tmp_path):
    config = Config()
    config.permissions.auto["bash"] = "ask"
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("do it", kind="group", conv_id="g1"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "p1",
            PERMISSION_ASKED,
            {"id": "per_2", "sessionID": sid, "action": "bash", "resources": ["x"]},
        )
    )
    cards_after_event = len(conn.cards)
    from tether.agent.events import PendingPermission

    client.add_permission(
        PendingPermission(id="per_2", session_id=sid, action="bash", resources=["x"])
    )
    await app._restore_hitl(client)
    assert len(conn.cards) == cards_after_event


@pytest.mark.asyncio
async def test_reconcile_finishes_turn_completed_during_disconnect(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.activated_at = time.monotonic() - 60
    client.message_store[sid] = [
        {"type": "assistant", "content": [{"type": "text", "text": "final during disconnect"}]}
    ]
    # The turn ended while SSE was disconnected, so it is no longer active.
    client.active.discard(sid)

    await app._reconcile(engine.route.server_base, client)

    assert sid not in app._turns
    assert conn.last_text() == "final during disconnect"


@pytest.mark.asyncio
async def test_watchdog_recovers_final_text_before_finishing(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.activated_at = time.monotonic() - 60
    client.message_store[sid] = [
        {"type": "assistant", "content": [{"type": "text", "text": "watchdog final text"}]}
    ]
    client.active.discard(sid)

    await app._recover_stale_turns()

    assert sid not in app._turns
    assert conn.last_text() == "watchdog final text"


@pytest.mark.asyncio
async def test_reconcile_replays_durable_events_missed_by_sse(tmp_path):
    from tether.agent.events import SESSION_STATUS, TEXT_DELTA

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.activated_at = time.monotonic() - 60
    client.active.discard(sid)
    client.replay_events[sid] = [
        Event(
            "e1",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "replayed answer"},
            durable={"aggregateID": sid, "seq": 1, "version": 1},
        ),
        Event(
            "e2",
            SESSION_STATUS,
            {"sessionID": sid, "status": {"type": "idle"}},
            durable={"aggregateID": sid, "seq": 2, "version": 1},
        ),
    ]

    await app._reconcile(engine.route.server_base, client)

    assert sid not in app._turns
    assert conn.last_text() == "replayed answer"
    assert client.replay_requests[0] == (sid, -1)


@pytest.mark.asyncio
async def test_reconcile_uses_route_cursor_across_turns(tmp_path):
    from tether.agent.events import SESSION_STATUS, TEXT_DELTA

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.activated_at = time.monotonic() - 60
    engine.last_seq = 5
    engine.route.last_seq = 5
    client.active.discard(sid)
    client.replay_events[sid] = [
        Event(
            "old",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "stale"},
            durable={"aggregateID": sid, "seq": 4, "version": 1},
        ),
        Event(
            "new",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "fresh"},
            durable={"aggregateID": sid, "seq": 6, "version": 1},
        ),
        Event(
            "idle",
            SESSION_STATUS,
            {"sessionID": sid, "status": {"type": "idle"}},
            durable={"aggregateID": sid, "seq": 7, "version": 1},
        ),
    ]

    client.replay_requests.clear()
    await app._reconcile(engine.route.server_base, client)

    assert client.replay_requests[0] == (sid, 5)
    assert conn.last_text() == "fresh"


@pytest.mark.asyncio
async def test_durable_seq_is_persisted_on_route(tmp_path):
    from tether.agent.events import TEXT_DELTA

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "e1",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "x"},
            durable={"aggregateID": sid, "seq": 9, "version": 1},
        )
    )
    route = await app.router.get_by_session(sid)
    assert route is not None
    assert route.last_seq == 9


@pytest.mark.asyncio
async def test_restore_hitl_clears_pending_that_backend_no_longer_has(tmp_path):
    from tether.models import PendingInteraction

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("do it"))
    sid = client.prompts[0]["sid"]
    route = await app.router.get_by_session(sid)
    assert route is not None
    route.pending_interactions["old"] = PendingInteraction(
        kind="permission",
        owner="u1",
        scope="initiator",
        request_id="old",
    )
    await app.router.save(route)

    await app._restore_hitl(client)

    assert "old" not in route.pending_interactions
    assert "失效" in (conn.last_text() or "")
    persisted = await app.store.get(route.key)
    assert persisted is not None
    assert "old" not in persisted.pending_interactions


@pytest.mark.asyncio
async def test_prime_route_cursor_advances_without_replaying(tmp_path):
    from tether.agent.events import TEXT_DELTA

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    route = await app.router.get_by_session(sid)
    assert route is not None
    route.last_seq = 1
    client.replay_events[sid] = [
        Event(
            "e2",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "old turn"},
            durable={"aggregateID": sid, "seq": 2, "version": 1},
        ),
        Event(
            "e3",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "older"},
            durable={"aggregateID": sid, "seq": 3, "version": 1},
        ),
    ]
    before = conn.last_text()

    await app._prime_route_cursor(client, route)

    assert route.last_seq == 3
    assert conn.last_text() == before


@pytest.mark.asyncio
async def test_restore_hitl_clears_cached_route_without_engine(tmp_path):
    from tether.models import PendingInteraction

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("do it"))
    sid = client.prompts[0]["sid"]
    route = await app.router.get_by_session(sid)
    assert route is not None
    route.pending_interactions["old"] = PendingInteraction(
        kind="question", owner="u1", scope="initiator", request_id="old"
    )
    await app.router.save(route)

    # Simulate a bridge restart: the route cache survives, but no engine does.
    app._turns.pop(sid, None)
    app._turn_queue.pop(sid, None)

    await app._restore_hitl(client)

    cached = await app.router.get_by_session(sid)
    assert cached is not None
    assert "old" not in cached.pending_interactions
    persisted = await app.store.get(route.key)
    assert persisted is not None
    assert "old" not in persisted.pending_interactions


@pytest.mark.asyncio
async def test_reconcile_replay_finish_does_not_duplicate_final_text(tmp_path):
    from tether.agent.events import SESSION_STATUS, TEXT_DELTA

    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.activated_at = time.monotonic() - 60
    client.active.add(sid)  # stale active list from the backend
    client.replay_events[sid] = [
        Event(
            "e1",
            TEXT_DELTA,
            {"sessionID": sid, "delta": "replayed answer"},
            durable={"aggregateID": sid, "seq": 1, "version": 1},
        ),
        Event(
            "e2",
            SESSION_STATUS,
            {"sessionID": sid, "status": {"type": "idle"}},
            durable={"aggregateID": sid, "seq": 2, "version": 1},
        ),
    ]

    await app._reconcile(engine.route.server_base, client)

    matches = [
        item
        for item in conn.messages
        if item["kind"] == "text" and item["text"] == "replayed answer"
    ]
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_final_snapshot_is_scoped_to_current_turn(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.activated_at = time.monotonic() - 60
    client.active.discard(sid)
    client.message_store[sid] = [
        {"type": "user", "content": [{"type": "text", "text": "old"}]},
        {"type": "assistant", "content": [{"type": "text", "text": "old answer"}]},
        {"type": "user", "content": [{"type": "text", "text": "new"}]},
        {"type": "assistant", "content": [{"type": "tool", "state": {"content": []}}]},
    ]

    await app._reconcile(engine.route.server_base, client)

    assert "old answer" not in (conn.last_text() or "")


@pytest.mark.asyncio
async def test_flush_cursors_persists_dirty_cursor(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("start"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    engine.last_seq = 5
    engine.route.last_seq = 1
    engine.cursor_dirty = True

    await app._flush_cursors()

    persisted = await app.store.get(engine.route.key)
    assert persisted is not None
    assert persisted.last_seq == 5
    assert engine.cursor_dirty is False
