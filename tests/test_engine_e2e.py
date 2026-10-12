from __future__ import annotations

import pytest
from fakes import FakeAgentClient

from tether.agent.events import (
    PERMISSION_ASKED,
    SESSION_STATUS,
    TEXT_DELTA,
    TEXT_ENDED,
    Event,
)
from tether.app import TetherApp
from tether.config import Config
from tether.connectors.fake import FakeConnector
from tether.models import (
    Conversation,
    InboundMessage,
    IncomingInteraction,
    Sender,
)


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


def inbound(
    text: str,
    *,
    kind="direct",
    conv_id="d1",
    message_id="m1",
    name="Alice",
    sender_id="u1",
    attachments=None,
) -> InboundMessage:
    return InboundMessage(
        channel="fake",
        message_id=message_id,
        conversation=Conversation(channel="fake", kind=kind, id=conv_id),
        sender=Sender(id=sender_id, name=name),
        text=text,
        attachments=attachments or [],
    )


@pytest.mark.asyncio
async def test_direct_turn_streams_and_finishes(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    assert client.prompts and client.prompts[0]["delivery"] == "queue"
    assert "<bridge-context>" in client.prompts[0]["prompt"]
    sid = client.prompts[0]["sid"]

    await app._route_event(Event("e1", TEXT_DELTA, {"delta": "Hel", "sessionID": sid}))
    await app._route_event(Event("e2", TEXT_DELTA, {"delta": "lo", "sessionID": sid}))
    await app._route_event(Event("e3", TEXT_ENDED, {"text": "Hello", "sessionID": sid}))
    await app._route_event(
        Event("e4", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    assert conn.last_text() == "Hello"
    assert app.metrics.get("turns") == 1
    assert sid not in app._turns


@pytest.mark.asyncio
async def test_group_users_share_one_session(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("first", kind="group", conv_id="g1", name="Alice"))
    await app._on_message(
        inbound("second", kind="group", conv_id="g1", message_id="m2", name="Bob")
    )
    assert len(client.sessions) == 1
    assert "[Alice]: first" in client.prompts[0]["prompt"]
    assert "[Bob]: second" in client.prompts[1]["prompt"]
    assert client.prompts[0]["sid"] == client.prompts[1]["sid"]


@pytest.mark.asyncio
async def test_permission_card_and_click(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("run it", kind="group", conv_id="g1"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "p1",
            PERMISSION_ASKED,
            {"id": "per_1", "sessionID": sid, "action": "bash", "resources": ["rm -rf x"]},
        )
    )
    assert conn.cards, "permission card should be sent"
    value = conn.cards[-1].buttons[0].value
    conv = Conversation(channel="fake", kind="group", id="g1")
    await app._on_interaction(
        IncomingInteraction(
            conversation=conv, message_id="card1", sender=Sender(id="u1"), value=value
        )
    )
    assert client.permission_replies == [(sid, "per_1", "once")]


@pytest.mark.asyncio
async def test_auto_permission_for_read(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("read"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "p1",
            PERMISSION_ASKED,
            {"id": "per_9", "sessionID": sid, "action": "read", "resources": []},
        )
    )
    assert client.permission_replies == [(sid, "per_9", "once")]
    assert not conn.cards


@pytest.mark.asyncio
async def test_stop_command_interrupts(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("long task"))
    sid = client.prompts[0]["sid"]
    await app._on_message(inbound("/stop", message_id="m2"))
    assert sid in client.interrupted
    assert conn.last_text() == "🛑 Stopped."


@pytest.mark.asyncio
async def test_inline_attachment_becomes_prompt_file(tmp_path):
    app, conn, client = await make_app(tmp_path)
    att = conn.register_attachment("h1", b"\x89PNG data", mime="image/png", name="x.png")
    await app._on_message(inbound("look", attachments=[att]))
    files = client.prompts[0]["files"]
    assert len(files) == 1
    assert files[0]["mediaSource"] == "inline"
    assert files[0]["uri"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_duplicate_message_deduped(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("once"))
    await app._on_message(inbound("once"))
    assert len(client.prompts) == 1


@pytest.mark.asyncio
async def test_access_allowlist_blocks(tmp_path):
    config = Config.model_validate({"access": {"allow_users": ["someone-else"]}})
    app, conn, client = await make_app(tmp_path, config)
    await app._on_message(inbound("hi"))
    assert not client.prompts


@pytest.mark.asyncio
async def test_queued_turn_does_not_clobber_active_turn(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("first", kind="group", conv_id="g1", sender_id="alice"))
    await app._on_message(
        inbound("second", kind="group", conv_id="g1", message_id="m2", name="Bob", sender_id="bob")
    )
    route = await app.router.get(Conversation(channel="fake", kind="group", id="g1"))
    assert route is not None
    # The active turn still belongs to Alice; Bob's message is queued FIFO.
    assert route.active_turn_sender == "alice"
    assert route.queue_depth == 2
    assert client.prompts[1]["delivery"] == "queue"

    # Finishing the first turn promotes the queued one and moves attribution.
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event("z", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )
    assert route.active_turn_sender == "bob"
    assert route.queue_depth == 1


@pytest.mark.asyncio
async def test_first_prompt_is_never_steer(tmp_path):
    config = Config.model_validate({"sessions": {"busy_delivery": "steer"}})
    app, conn, client = await make_app(tmp_path, config)
    await app._on_message(inbound("hi"))
    assert client.prompts[0]["delivery"] == "queue"


@pytest.mark.asyncio
async def test_same_user_steer_when_enabled(tmp_path):
    config = Config.model_validate({"group": {"cross_user_delivery": "steer_same_user"}})
    app, conn, client = await make_app(tmp_path, config)
    await app._on_message(inbound("first", kind="group", conv_id="g1", sender_id="alice"))
    await app._on_message(
        inbound("more", kind="group", conv_id="g1", message_id="m2", sender_id="alice")
    )
    assert client.prompts[1]["delivery"] == "steer"
