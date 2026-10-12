from __future__ import annotations

from tether.agent.events import PendingPermission, PendingQuestion
from tether.config import Config
from tether.engine import hitl
from tether.engine.commands import parse_command
from tether.models import Conversation, Sender


def test_parse_stop_command():
    cmd = parse_command("/stop")
    assert cmd is not None and cmd.kind == "stop"
    assert parse_command("hello") is None
    assert parse_command("/unknown") is None
    assert parse_command("  /stop now ") is not None


def test_permission_value_roundtrip():
    value = hitl.encode_value("permission", "ses_1", "per_1", reply="once")
    decoded = hitl.decode_value(value)
    assert decoded == {"kind": "permission", "sid": "ses_1", "rid": "per_1", "reply": "once"}


def test_permission_card_buttons():
    perm = PendingPermission(
        id="per_1", session_id="ses_1", action="bash", resources=["rm -rf build"]
    )
    card = hitl.permission_card(perm)
    labels = [b.text for b in card.buttons]
    assert labels == ["Allow once", "Always allow", "Deny"]


def test_question_numbered_text():
    q = PendingQuestion.from_json(
        {
            "id": "que_1",
            "sessionID": "ses_1",
            "questions": [{"question": "Env?", "options": [{"label": "dev"}, {"label": "prod"}]}],
        }
    )
    text, options = hitl.question_numbered_text(q)
    assert "1. dev" in text and "2. prod" in text
    assert options == ["dev", "prod"]


def test_authorization_initiator_scope():
    config = Config()
    conv = Conversation(channel="fake", kind="group", id="g1")
    pending = hitl.make_pending("permission", owner="alice", scope="initiator", request_id="r")
    alice = Sender(id="alice")
    bob = Sender(id="bob")
    assert hitl.is_authorized(pending, alice, conv, config, active_turn_sender="alice")
    assert not hitl.is_authorized(pending, bob, conv, config, active_turn_sender="alice")


def test_authorization_admins_scope():
    config = Config.model_validate({"group": {"admins": ["admin1"], "hitl_scope": "admins"}})
    conv = Conversation(channel="fake", kind="group", id="g1")
    pending = hitl.make_pending("permission", owner="alice", scope="admins", request_id="r")
    assert hitl.is_authorized(
        pending, Sender(id="admin1"), conv, config, active_turn_sender="alice"
    )
    assert not hitl.is_authorized(
        pending, Sender(id="bob"), conv, config, active_turn_sender="alice"
    )


def test_direct_chat_always_authorized():
    config = Config()
    conv = Conversation(channel="fake", kind="direct", id="d1")
    pending = hitl.make_pending("permission", owner="alice", scope="initiator", request_id="r")
    assert hitl.is_authorized(
        pending, Sender(id="anyone"), conv, config, active_turn_sender="alice"
    )


def test_command_scope_admins():
    config = Config.model_validate({"group": {"command_scope": "admins", "admins": ["a1"]}})
    conv = Conversation(channel="fake", kind="group", id="g1")
    assert hitl.command_authorized(Sender(id="a1"), conv, config, active_turn_sender="bob")
    assert not hitl.command_authorized(Sender(id="bob"), conv, config, active_turn_sender="bob")
