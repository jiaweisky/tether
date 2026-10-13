from __future__ import annotations

import asyncio

import pytest
from fakes import FakeAgentClient

from tether.agent.events import (
    ATTACHMENT_OMITTED,
    PERMISSION_ASKED,
    QUESTION_ASKED,
    SESSION_STATUS,
    STEP_ENDED,
    STEP_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    TOOL_CALLED,
    Event,
)
from tether.app import TetherApp
from tether.config import Config
from tether.connectors.fake import FakeConnector
from tether.metrics import metrics
from tether.models import (
    Conversation,
    InboundMessage,
    IncomingInteraction,
    Route,
    Sender,
)


async def make_app(tmp_path, config: Config | None = None, connector=None):
    metrics.reset()  # the registry is process-global; isolate counter assertions
    config = config or Config()
    conn = connector or FakeConnector()
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


class NonStreamingConnector(FakeConnector):
    """A channel that cannot refresh a message in place (like WeCom with no frame)."""

    def supports_streaming(self, conv) -> bool:
        return False


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
    assert conn.acknowledgements == [(value, "✅ Allow once")]


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


@pytest.mark.asyncio
async def test_non_streaming_channel_sends_placeholder_then_final(tmp_path):
    app, conn, client = await make_app(tmp_path, connector=NonStreamingConnector())
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]

    # One interim frame: a non-streaming channel shows a placeholder, not a snapshot.
    await app._turns[sid]._emit(False, "")
    await app._route_event(Event("e2", TEXT_ENDED, {"text": "Hello", "sessionID": sid}))
    await app._route_event(
        Event("e3", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    texts = [m["text"] for m in conn.messages if m["kind"] == "text"]
    assert texts == ["🤔 Thinking…", "Hello"]


@pytest.mark.asyncio
async def test_graceful_stop_flushes_partial_snapshot(tmp_path):
    config = Config.model_validate({"sessions": {"interrupt_on_shutdown": True}})
    app, conn, client = await make_app(tmp_path, config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(Event("e1", TEXT_DELTA, {"delta": "partial", "sessionID": sid}))

    await app.stop()  # with interrupt_on_shutdown: interrupt + flush the snapshot
    assert "partial" in conn.last_text()


@pytest.mark.asyncio
async def test_missing_session_is_recreated(tmp_path):
    app, conn, client = await make_app(tmp_path)
    client.fail_next_prompt_with = "not_found"  # e.g. agentd restarted with a fresh root

    await app._on_message(inbound("hi"))

    # A new session was created and the prompt went to it.
    assert len(client.sessions) == 2
    route = await app.router.get(Conversation(channel="fake", kind="direct", id="d1"))
    assert route is not None
    assert route.session_id in client.sessions
    assert client.prompts and client.prompts[-1]["sid"] == route.session_id


@pytest.mark.asyncio
async def test_stale_interaction_is_ignored(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("do it", kind="group", conv_id="g1"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "p1",
            PERMISSION_ASKED,
            {"id": "per_1", "sessionID": sid, "action": "bash", "resources": ["x"]},
        )
    )
    value = conn.cards[-1].buttons[0].value
    client.permission_reply_error = "not_found"  # already answered/expired on agentd
    conv = Conversation(channel="fake", kind="group", id="g1")
    await app._on_interaction(
        IncomingInteraction(conversation=conv, message_id="c", sender=Sender(id="u1"), value=value)
    )
    route = await app.router.get_by_session(sid)
    assert "per_1" not in route.pending_interactions
    assert client.permission_replies == []


@pytest.mark.asyncio
async def test_interaction_after_restart_attaches_resumed_engine(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("do it", kind="group", conv_id="g1"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "p1",
            PERMISSION_ASKED,
            {"id": "per_1", "sessionID": sid, "action": "bash", "resources": ["x"]},
        )
    )
    value = conn.cards[-1].buttons[0].value

    # Emulate a bridge restart mid-turn: drop the in-memory engine.
    app._turns.pop(sid, None)
    app._turn_queue.pop(sid, None)

    conv = Conversation(channel="fake", kind="group", id="g1")
    await app._on_interaction(
        IncomingInteraction(conversation=conv, message_id="c", sender=Sender(id="u1"), value=value)
    )
    assert sid in app._turns  # a resumed engine was attached
    assert client.permission_replies == [(sid, "per_1", "once")]


@pytest.mark.asyncio
async def test_question_card_click_is_acknowledged(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi", kind="group", conv_id="g1"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "q1",
            QUESTION_ASKED,
            {
                "id": "que_1",
                "sessionID": sid,
                "questions": [
                    {
                        "question": "env?",
                        "header": "Env",
                        "options": [{"label": "dev"}, {"label": "prod"}],
                    }
                ],
            },
        )
    )
    assert conn.cards, "question card should be sent"
    value = conn.cards[-1].buttons[0].value  # first option
    conv = Conversation(channel="fake", kind="group", id="g1")
    await app._on_interaction(
        IncomingInteraction(conversation=conv, message_id="c", sender=Sender(id="u1"), value=value)
    )
    assert client.question_replies == [(sid, "que_1", [["dev"]])]
    assert conn.acknowledgements == [(value, "✅ dev")]


@pytest.mark.asyncio
async def test_turn_start_sends_working_placeholder(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    assert conn.last_text() == "🤔 Thinking…"


@pytest.mark.asyncio
async def test_idle_does_not_leave_thinking_placeholder(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    # A tool ran and the turn ended without any assistant text.
    await app._route_event(Event("t1", TOOL_CALLED, {"tool": "bash", "sessionID": sid}))
    await app._route_event(
        Event("s1", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )
    assert conn.last_text() != "🤔 Thinking…"


@pytest.mark.asyncio
async def test_permission_timeout_auto_replies(tmp_path):
    config = Config()
    config.permissions.timeout_s = 1
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "p1",
            PERMISSION_ASKED,
            {"id": "per_1", "sessionID": sid, "action": "bash", "resources": ["rm -rf /"]},
        )
    )
    await asyncio.sleep(1.3)
    assert client.permission_replies == [(sid, "per_1", "reject")]
    assert any(m["kind"] == "text" and "超时" in m["text"] for m in conn.messages)


@pytest.mark.asyncio
async def test_interim_frame_shows_tool_line(tmp_path):
    config = Config()
    config.streaming.min_interval_ms = 1
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(Event("t1", TOOL_CALLED, {"tool": "bash", "sessionID": sid}))
    await asyncio.sleep(0.1)
    assert "Using" in conn.last_text() and "bash" in conn.last_text()


@pytest.mark.asyncio
async def test_interim_frame_shows_idle_progress(tmp_path):
    config = Config()
    config.streaming.min_interval_ms = 1
    config.streaming.idle_progress_ms = 20
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(Event("e1", TEXT_DELTA, {"delta": "部分回答", "sessionID": sid}))
    await asyncio.sleep(0.25)
    assert "Thinking" in conn.last_text()


@pytest.mark.asyncio
async def test_step_started_shows_working_hint(tmp_path):
    config = Config()
    config.streaming.min_interval_ms = 1
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(Event("s1", STEP_STARTED, {"sessionID": sid}))
    await asyncio.sleep(0.1)
    assert "Thinking" in conn.last_text()


@pytest.mark.asyncio
async def test_permission_card_failure_falls_back_to_numbered_text(tmp_path):
    app, conn, client = await make_app(tmp_path)

    async def boom(*args, **kwargs):
        raise RuntimeError("wecom card rejected")

    conn.send_card = boom
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event("p1", PERMISSION_ASKED, {"id": "per_1", "sessionID": sid, "action": "bash"})
    )
    assert any(m["kind"] == "text" and "1." in m["text"] for m in conn.messages)


@pytest.mark.asyncio
async def test_usage_accumulates_and_context_is_last_step(tmp_path):
    config = Config()
    config.model.context_limit = 1000
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event("s1", STEP_ENDED, {"sessionID": sid, "tokens": {"input": 100, "output": 20}})
    )
    await app._route_event(
        Event(
            "s2",
            STEP_ENDED,
            {
                "sessionID": sid,
                "tokens": {"input": 200, "output": 30, "cache": {"read": 500, "write": 0}},
            },
        )
    )
    await app._route_event(Event("e", TEXT_ENDED, {"text": "done", "sessionID": sid}))
    await app._route_event(
        Event("d", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )
    text = conn.last_text()
    assert "context 700/1.0k" in text  # last step full prompt = input + cache.read
    assert "in 300/out 50" in text  # summed non-cached input / output


def test_route_normalizes_dict_model():
    route = Route(
        conversation=Conversation(channel="x", kind="direct", id="c"),
        session_id="s",
        server_base="http://b",
        agent="a",
        model={"id": "deepseek-flash", "providerID": "", "variant": "default"},
    )
    assert route.model == "deepseek-flash"


@pytest.mark.asyncio
async def test_attachment_omitted_is_noticed(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "a1",
            ATTACHMENT_OMITTED,
            {"sessionID": sid, "name": "big.zip", "reason": "too large"},
        )
    )
    assert any(m["kind"] == "text" and "big.zip" in m["text"] for m in conn.messages)


@pytest.mark.asyncio
async def test_refresh_identity_config_overrides_platform(tmp_path):
    config = Config()
    config.identity.display_name = "荔小枝"
    config.identity.description = "自定义描述"
    app, conn, client = await make_app(tmp_path, config=config)
    route = await app.router.get_or_create(Conversation(channel="fake", kind="direct", id="d1"))
    identity = await app.router.refresh_identity(route, conn)
    assert identity.name == "荔小枝"
    assert identity.description == "自定义描述"
    assert route.bot_name == "荔小枝"
    assert route.context_dirty is True


@pytest.mark.asyncio
async def test_refresh_identity_description_only_override(tmp_path):
    # A description override applies even without a name override, and the
    # platform's name is kept.
    config = Config()
    config.identity.description = "自定义描述"
    app, conn, client = await make_app(tmp_path, config=config)
    route = await app.router.get_or_create(Conversation(channel="fake", kind="direct", id="d1"))
    identity = await app.router.refresh_identity(route, conn)
    assert identity.name == "Assistant"
    assert identity.description == "自定义描述"


@pytest.mark.asyncio
async def test_watchdog_recovers_stale_turn_and_drains_queue(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi", message_id="m1"))
    sid = client.prompts[0]["sid"]
    engine = app._turns[sid]
    # A second message queues behind the (phantom) active turn.
    await app._on_message(inbound("again", message_id="m2"))
    assert app._turn_queue.get(sid)

    # agentd reports the session as no longer running, and the turn is old.
    client.active = set()
    engine.activated_at -= 1000
    await app._recover_stale_turns()

    # The stale turn was finished and the queued turn activated (2nd prompt).
    assert app._turns[sid] is not engine
    assert len(client.prompts) == 2


@pytest.mark.asyncio
async def test_number_reply_to_stale_interaction_is_dropped(tmp_path):
    from tether.engine.hitl import make_pending

    app, conn, client = await make_app(tmp_path)
    msg = inbound("hi", message_id="m1")
    await app._on_message(msg)
    route = await app.router.get(msg.conversation)
    assert route is not None
    route.pending_interactions["per_1"] = make_pending(
        "permission", owner="u1", scope="initiator", request_id="per_1"
    )
    # agentd no longer has this interaction.
    client.permission_reply_error = "not_found"
    await app._on_message(inbound("1", message_id="m2"))
    assert "per_1" not in route.pending_interactions


@pytest.mark.asyncio
async def test_turn_finish_clears_pending_interactions(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi", message_id="m1"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event("p1", PERMISSION_ASKED, {"id": "per_1", "sessionID": sid, "action": "bash"})
    )
    route = await app.router.get_by_session(sid)
    assert route is not None and route.pending_interactions
    # The turn ends (idle): the leftover pending interaction must be cleared.
    await app._route_event(
        Event("d1", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )
    assert not route.pending_interactions
