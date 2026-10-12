from __future__ import annotations

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
        client_factory=lambda base, token: client,
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
    app, conn, client = await make_app(tmp_path)
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
