from __future__ import annotations

import asyncio

import pytest
from fakes import FakeAgentClient

from tether.agent.errors import AgentError
from tether.agent.events import (
    ATTACHMENT_OMITTED,
    PERMISSION_ASKED,
    QUESTION_ASKED,
    QUESTION_REPLIED,
    SESSION_STATUS,
    STEP_ENDED,
    STEP_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    TOOL_CALLED,
    TOOL_SUCCESS,
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


def ask_bash_config() -> Config:
    config = Config()
    config.permissions.auto["bash"] = "ask"
    return config


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


def egress_config(tmp_path) -> Config:
    """Config that auto-forwards produced files inside ``tmp_path``."""
    return Config.model_validate(
        {
            "server": {"working_directory": str(tmp_path)},
            "media": {"outbound": {"auto_files": True, "patterns": ["{working_dir}/**"]}},
        }
    )


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
    config = Config()
    config.permissions.auto["bash"] = "ask"
    app, conn, client = await make_app(tmp_path, config=config)
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
    assert conn.last_text() == "🛑 Stopped the current turn."


@pytest.mark.asyncio
async def test_inline_attachment_becomes_prompt_file(tmp_path):
    app, conn, client = await make_app(tmp_path)
    att = conn.register_attachment("h1", b"\x89PNG data", mime="image/png", name="x.png")
    await app._on_message(inbound("look", attachments=[att]))
    files = client.prompts[0]["files"]
    assert len(files) == 1
    assert files[0]["name"] == "x.png"
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
    app, conn, client = await make_app(tmp_path, config=ask_bash_config())
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
    app, conn, client = await make_app(tmp_path, config=ask_bash_config())
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
    config.permissions.auto["bash"] = "ask"
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
    config = Config()
    config.permissions.auto["bash"] = "ask"
    app, conn, client = await make_app(tmp_path, config=config)

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
async def test_prompt_request_error_detail_is_shown(tmp_path):
    app, conn, client = await make_app(tmp_path)
    client.fail_next_prompt_with = (
        "too_large",
        "request body exceeds the 1048576-byte limit",
        413,
    )
    await app._on_message(inbound("hi"))
    assert "request body exceeds the 1048576-byte limit" in conn.last_text()


@pytest.mark.asyncio
async def test_attachment_omitted_is_noticed(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    await app._route_event(
        Event(
            "a1",
            ATTACHMENT_OMITTED,
            {
                "sessionID": sid,
                "name": "big.zip",
                "reason": "too_large",
                "detail": "limit 33554432 bytes",
            },
        )
    )
    text = "\n".join(m["text"] for m in conn.messages if m["kind"] == "text")
    assert "big.zip" in text and "size limit" in text and "33554432" in text


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
    app, conn, client = await make_app(tmp_path, config=ask_bash_config())
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


@pytest.mark.asyncio
async def test_continuation_after_question_opens_new_message(tmp_path):
    """After a HITL answer, the agent's continuation goes to a new message.

    The streamed message was opened before the user's reply, so re-editing it
    would place the answer above that reply.
    """
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]

    await app._route_event(Event("t1", TEXT_DELTA, {"delta": "First part", "sessionID": sid}))
    await app._route_event(
        Event(
            "q1",
            QUESTION_ASKED,
            {
                "id": "que_1",
                "sessionID": sid,
                "questions": [{"question": "env?", "header": "Env", "options": [{"label": "dev"}]}],
            },
        )
    )
    await app._route_event(Event("q2", QUESTION_REPLIED, {"requestID": "que_1", "sessionID": sid}))
    await app._route_event(Event("t2", TEXT_DELTA, {"delta": "Second part", "sessionID": sid}))
    await app._route_event(
        Event("e4", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    texts = [m for m in conn.messages if m["kind"] == "text"]
    first = next(m for m in texts if m["text"] == "First part")
    second = next(m for m in texts if m["text"] == "Second part")
    assert first["id"] != second["id"]
    # The first message is sealed, not extended with the continuation.
    assert all("Second part" not in m["text"] for m in texts if m["id"] == first["id"])


@pytest.mark.asyncio
async def test_tool_output_file_is_sent_to_the_user(tmp_path):
    app, conn, client = await make_app(tmp_path, config=egress_config(tmp_path))
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]

    produced = tmp_path / "segments.csv"
    produced.write_text("a,b\n1,2\n")
    await app._route_event(
        Event(
            "t1",
            TOOL_SUCCESS,
            {"tool": "write", "sessionID": sid, "outputPaths": [str(produced)]},
        )
    )
    await app._route_event(
        Event("t2", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    media = [m for m in conn.messages if m["kind"] == "media"]
    assert media, "the produced file should be delivered to the user"
    assert media[0]["media"].name == "segments.csv"


@pytest.mark.asyncio
async def test_multi_question_form_card_and_submit(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
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
                        "question": "when?",
                        "header": "Time",
                        "options": [{"label": "A"}, {"label": "B"}],
                    },
                    {
                        "question": "more?",
                        "header": "More",
                        "multiple": True,
                        "options": [{"label": "X"}, {"label": "Y"}],
                    },
                ],
            },
        )
    )
    assert conn.cards, "a multi-question form card should be sent (not numbered text)"
    card = conn.cards[-1]
    assert len(card.questions) == 2

    await app._on_interaction(
        IncomingInteraction(
            conversation=Conversation(channel="fake", kind="direct", id="d1"),
            message_id="c",
            sender=Sender(id="u1"),
            value=card.submit_value,
            form={"q0": "A", "q1_0": True},
        )
    )
    assert client.question_replies == [(sid, "que_1", [["A"], ["X"]])]


@pytest.mark.asyncio
async def test_written_file_reported_in_structured_output_is_sent(tmp_path):
    app, conn, client = await make_app(tmp_path, config=egress_config(tmp_path))
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]

    produced = tmp_path / "plan.md"
    produced.write_text("# Plan\n")
    await app._route_event(
        Event(
            "t1",
            TOOL_SUCCESS,
            {
                "tool": "write",
                "sessionID": sid,
                "structured": {
                    "operation": "write",
                    "resource": str(produced),
                    "target": str(produced),
                },
            },
        )
    )
    await app._route_event(
        Event("t2", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    media = [m for m in conn.messages if m["kind"] == "media"]
    assert media, "a file named by a write tool should be delivered"
    assert media[0]["media"].name == "plan.md"


@pytest.mark.asyncio
async def test_new_command_restarts_the_session_for_an_admin(tmp_path):
    config = Config.model_validate({"group": {"admins": ["u1"]}})
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    old = client.prompts[0]["sid"]

    await app._on_message(inbound("/new", message_id="m2"))

    assert client.deleted == [old]
    route = await app.router.get(Conversation(channel="fake", kind="direct", id="d1"))
    assert route is not None and route.session_id != old


@pytest.mark.asyncio
async def test_new_command_is_rejected_without_admin(tmp_path):
    app, conn, client = await make_app(tmp_path)  # no admins configured
    await app._on_message(inbound("hi"))
    old = client.prompts[0]["sid"]

    await app._on_message(inbound("/new", message_id="m2"))

    assert client.deleted == []
    route = await app.router.get(Conversation(channel="fake", kind="direct", id="d1"))
    assert route is not None and route.session_id == old
    assert "admin" in conn.last_text().lower()


@pytest.mark.asyncio
async def test_stop_with_no_conversation_says_nothing_to_stop(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("/stop"))
    assert "Nothing to stop" in conn.last_text()
    assert not client.prompts  # never forwarded to the agent


@pytest.mark.asyncio
async def test_new_with_no_conversation_says_nothing_to_reset(tmp_path):
    config = Config.model_validate({"group": {"admins": ["u1"]}})
    app, conn, _client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("/new"))
    assert "Nothing to reset" in conn.last_text()


@pytest.mark.asyncio
async def test_a_failing_command_replies_friendly_and_is_not_forwarded(tmp_path, monkeypatch):
    app, conn, client = await make_app(tmp_path)

    async def boom(msg, connector):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(app, "_handle_status", boom)
    await app._on_message(inbound("/status"))
    assert "went wrong" in conn.last_text()
    assert not client.prompts


@pytest.mark.asyncio
async def test_whoami_command_replies_with_the_sender_id(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("/whoami"))
    assert "u1" in conn.last_text()
    assert not client.prompts  # the command is not forwarded to the agent


@pytest.mark.asyncio
async def test_help_command_lists_commands_and_is_not_forwarded(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("/help"))
    text = conn.last_text()
    for kind in ("stop", "new", "whoami", "status", "help"):
        assert f"/{kind}" in text
    assert not client.prompts


@pytest.mark.asyncio
async def test_double_prefix_forwards_a_literal_command_to_the_agent(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("//help"))
    assert client.prompts, "escaped text must reach the agent"
    assert "/help" in client.prompts[0]["prompt"]
    assert "Commands (prefix" not in conn.last_text()


@pytest.mark.asyncio
async def test_double_prefix_stop_does_not_interrupt(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    await app._on_message(inbound("//stop", message_id="m2"))
    assert client.interrupted == []
    assert "/stop" in client.prompts[-1]["prompt"]


@pytest.mark.asyncio
async def test_a_command_with_extra_words_is_forwarded_not_intercepted(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("/status of the build"))
    assert client.prompts, "a near-miss must reach the agent"
    assert "/status of the build" in client.prompts[0]["prompt"]
    assert "Status" not in conn.last_text()  # no bridge status reply


@pytest.mark.asyncio
async def test_config_command_is_admin_only_and_direct_only(tmp_path):
    config = Config.model_validate(
        {"group": {"admins": ["u1"]}, "server": {"token": "s3cr3t-value"}}
    )
    app, conn, client = await make_app(tmp_path, config=config)

    await app._on_message(inbound("/config", kind="group", conv_id="g1"))
    assert "direct chat" in conn.last_text()

    await app._on_message(inbound("/config", sender_id="u2", message_id="m2"))
    assert "admin" in conn.last_text().lower()

    # default: only the current agentd server, not the bridge config
    await app._on_message(inbound("/config", sender_id="u1", message_id="m3"))
    default = "\n".join(m["text"] for m in conn.messages if m["kind"] == "text")
    assert '"agentd"' in default and '"tether"' not in default

    # --all: bridge + full agentd, with the bridge secret redacted
    await app._on_message(inbound("/config --all", sender_id="u1", message_id="m4"))
    every = "\n".join(m["text"] for m in conn.messages if m["kind"] == "text")
    assert '"tether"' in every and '"agentd"' in every
    assert "***" in every and "s3cr3t-value" not in every

    # an unknown option is reported, not silently ignored
    await app._on_message(inbound("/config --nope", sender_id="u1", message_id="m5"))
    assert "Unknown option" in conn.last_text()
    assert not client.prompts  # never forwarded to the agent


def test_config_chunks_are_fenced_and_within_limit():
    import json

    from tether.app import _config_chunks

    dump = json.dumps({"key": "v" * 200}, indent=2)
    chunks = _config_chunks(dump, 80)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.startswith("```json\n") and chunk.endswith("\n```")
        assert len(chunk) <= 80
    bodies = [c[len("```json\n") : -len("\n```")] for c in chunks]
    assert "".join(bodies) == dump  # chunking is lossless
    assert _config_chunks(dump, 0) == [f"```json\n{dump}\n```"]  # 0 = no limit


@pytest.mark.asyncio
async def test_send_command_delivers_an_allowed_file(tmp_path):
    config = Config.model_validate(
        {
            "server": {"working_directory": str(tmp_path)},
            "media": {"outbound": {"patterns": ["{working_dir}/**"]}},
        }
    )
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    (tmp_path / "report.csv").write_text("a,b\n")
    await app._on_message(inbound("/send report.csv", message_id="m2"))

    media = [m for m in conn.messages if m["kind"] == "media"]
    assert media and media[-1]["media"].name == "report.csv"
    assert len(client.prompts) == 1  # /send is not forwarded to the agent


@pytest.mark.asyncio
async def test_send_command_accepts_a_quoted_path_with_spaces(tmp_path):
    config = Config.model_validate(
        {
            "server": {"working_directory": str(tmp_path)},
            "media": {"outbound": {"patterns": ["{working_dir}/**"]}},
        }
    )
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    (tmp_path / "a b.csv").write_text("x")
    await app._on_message(inbound('/send "a b.csv"', message_id="m2"))

    media = [m for m in conn.messages if m["kind"] == "media"]
    assert media and media[-1]["media"].name == "a b.csv"
    assert len(client.prompts) == 1


@pytest.mark.asyncio
async def test_send_command_blocks_a_disallowed_file(tmp_path):
    (tmp_path / "docs").mkdir()
    config = Config.model_validate(
        {
            "server": {"working_directory": str(tmp_path)},
            "media": {"outbound": {"patterns": [f"{tmp_path}/docs/**"]}},
        }
    )
    app, conn, _client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    (tmp_path / "secret.csv").write_text("x")
    await app._on_message(inbound("/send secret.csv", message_id="m2"))

    assert not [m for m in conn.messages if m["kind"] == "media"]
    assert "Not sent" in conn.last_text()


@pytest.mark.asyncio
async def test_send_command_reports_a_missing_file(tmp_path):
    config = Config.model_validate(
        {
            "server": {"working_directory": str(tmp_path)},
            "media": {"outbound": {"patterns": ["{working_dir}/**"]}},
        }
    )
    app, conn, _client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    await app._on_message(inbound("/send nope.csv", message_id="m2"))

    assert "No such file" in conn.last_text()


@pytest.mark.asyncio
async def test_auto_forwarded_file_outside_patterns_is_blocked(tmp_path):
    (tmp_path / "allowed").mkdir()
    config = Config.model_validate(
        {
            "server": {"working_directory": str(tmp_path)},
            "media": {"outbound": {"auto_files": True, "patterns": [f"{tmp_path}/allowed/**"]}},
        }
    )
    app, conn, client = await make_app(tmp_path, config=config)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]

    produced = tmp_path / "secret.csv"
    produced.write_text("x")
    await app._route_event(
        Event(
            "t1",
            TOOL_SUCCESS,
            {"tool": "write", "sessionID": sid, "outputPaths": [str(produced)]},
        )
    )
    await app._route_event(
        Event("t2", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    assert not [m for m in conn.messages if m["kind"] == "media"]
    assert "Not sent" not in conn.last_text()  # auto-forwarded files are not reported
    assert metrics.counters.get("media_outbound_blocked") == 1


@pytest.mark.asyncio
async def test_config_hot_reload_applies_admins(tmp_path):
    from tether.config import load_config

    path = tmp_path / "c.yaml"
    path.write_text("group:\n  admins: []\n")
    config = load_config(str(path))
    app, conn, client = await make_app(tmp_path, config=config)
    app._config_path = str(path)

    path.write_text('group:\n  admins: ["u9"]\n')
    app._reload_config()

    assert app.config.group.admins == ["u9"]


@pytest.mark.asyncio
async def test_status_command_reports_and_redacts(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    await app._on_message(inbound("/status", message_id="m2"))
    direct = conn.last_text()
    assert "Status" in direct
    assert "agent=build" in direct
    assert "agentd:" in direct and "context:" in direct
    assert "vtest" in direct and "pid 1" in direct  # agentd /api/info

    await app._on_message(inbound("hi", kind="group", conv_id="g1", message_id="m3"))
    await app._on_message(inbound("/status", kind="group", conv_id="g1", message_id="m4"))
    group = conn.last_text()
    assert "group" in group and "agent=build" in group
    assert "agentd:" not in group and "workdir:" not in group
    assert "context:" not in group and "project:" not in group


@pytest.mark.asyncio
async def test_status_shows_agentd_unreachable(tmp_path, monkeypatch):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))

    async def boom():
        raise AgentError("unavailable", "down")

    monkeypatch.setattr(client, "get_info", boom)
    await app._on_message(inbound("/status", message_id="m2"))
    assert "(unreachable)" in conn.last_text()


@pytest.mark.asyncio
async def test_read_only_tool_denial_is_friendly_and_reported_once(tmp_path):
    app, conn, client = await make_app(tmp_path)
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]
    for event_id in ("t1", "t2"):
        await app._route_event(
            Event(
                event_id,
                "session.next.tool.failed",
                {
                    "sessionID": sid,
                    "error": {"message": "permission blocked"},
                    "tool": "write",
                },
            )
        )
    text = "\n".join(m["text"] for m in conn.messages if m["kind"] == "text")
    assert text.count("当前为只读模式") == 1
    assert "A tool failed" not in text


@pytest.mark.asyncio
async def test_tool_edits_send_only_the_final_file_version(tmp_path):
    app, conn, client = await make_app(tmp_path, config=egress_config(tmp_path))
    await app._on_message(inbound("hi"))
    sid = client.prompts[0]["sid"]

    doc = tmp_path / "doc.md"
    doc.write_text("v1")
    edit = {"sessionID": sid, "structured": {"files": [{"file": str(doc), "status": "modified"}]}}
    await app._route_event(Event("t1", TOOL_SUCCESS, edit))
    doc.write_text("v2")
    await app._route_event(Event("t2", TOOL_SUCCESS, edit))
    await app._route_event(
        Event("t3", SESSION_STATUS, {"sessionID": sid, "status": {"type": "idle"}})
    )

    media = [m for m in conn.messages if m["kind"] == "media"]
    # An edit-tool file is delivered, and only once, with its final content.
    assert len(media) == 1
    assert media[0]["media"].data == b"v2"

@pytest.mark.asyncio
async def test_connector_health_publishes_the_transport_state(tmp_path):
    app, conn, _ = await make_app(tmp_path)

    app._check_connectors()
    assert metrics.gauges.get("connector_connected_fake") == 1.0
    assert "fake" not in app._connector_down_since

    conn._connected = False
    app._check_connectors()
    assert metrics.gauges.get("connector_connected_fake") == 0.0
    assert "fake" in app._connector_down_since  # an outage is now being tracked

    conn._connected = True
    app._check_connectors()
    assert metrics.gauges.get("connector_connected_fake") == 1.0
    assert "fake" not in app._connector_down_since  # cleared on recovery
