from __future__ import annotations

from typing import get_args

from tether.agent.events import PendingPermission, PendingQuestion
from tether.config import Config
from tether.engine import hitl
from tether.engine.commands import COMMANDS, CommandKind, help_text, parse_command, unescape_command
from tether.models import Conversation, Sender


def test_parse_stop_command():
    cmd = parse_command("/stop")
    assert cmd is not None and cmd.kind == "stop"
    assert parse_command("  /stop  ") is not None  # surrounding whitespace is fine
    assert parse_command("/STOP") is not None  # case-insensitive
    assert parse_command("hello") is None
    assert parse_command("/unknown") is None


def test_command_requires_an_exact_match():
    assert parse_command("/stop now") is None
    assert parse_command("/status of the build") is None
    assert parse_command("/help me") is None
    assert parse_command("/helpme") is None


def test_parse_send_command_with_argument():
    cmd = parse_command("/send docs/x.md")
    assert cmd is not None and cmd.kind == "send" and cmd.args == "docs/x.md"


def test_send_command_requires_an_argument():
    assert parse_command("/send") is None
    assert parse_command("/send   ") is None


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


def test_parse_new_command():
    cmd = parse_command("/new")
    assert cmd is not None and cmd.kind == "new"


def test_parse_whoami_command():
    cmd = parse_command("/whoami")
    assert cmd is not None and cmd.kind == "whoami"


def test_admins_are_a_superset_for_commands():
    config = Config.model_validate({"group": {"admins": ["admin1"], "command_scope": "initiator"}})
    conv = Conversation(channel="x", kind="group", id="g")
    # An admin may act even when they are not the turn's initiator.
    assert hitl.command_authorized(Sender(id="admin1"), conv, config, active_turn_sender="other")
    # The initiator (scope=initiator) may act.
    assert hitl.command_authorized(Sender(id="other"), conv, config, active_turn_sender="other")
    # A stranger may not.
    assert not hitl.command_authorized(
        Sender(id="stranger"), conv, config, active_turn_sender="other"
    )


def test_parse_status_command():
    cmd = parse_command("/status")
    assert cmd is not None and cmd.kind == "status"


def test_command_is_recognized_after_a_leading_mention():
    # Group messages keep the bot mention in the text.
    assert parse_command("@Bot /stop").kind == "stop"
    assert parse_command("@荔小枝 /new").kind == "new"
    assert parse_command("@_user_1 /status").kind == "status"
    assert parse_command("@Bot hello there") is None


def test_parse_help_command():
    cmd = parse_command("/help")
    assert cmd is not None and cmd.kind == "help"


def test_help_text_lists_every_command():
    text = help_text()
    for kind in ("stop", "new", "whoami", "status", "send", "config", "help"):
        assert f"/{kind}" in text
    assert "/send <path>" in text


def test_parse_config_command():
    default = parse_command("/config")
    assert default is not None and default.kind == "config" and default.args == ""
    every = parse_command("/config --all")
    assert every is not None and every.args == "--all"


def test_help_text_reflects_the_configured_prefix():
    text = help_text("!")
    assert "`!stop`" in text
    assert "/stop" not in text


def test_unescape_command_collapses_a_doubled_prefix():
    assert unescape_command("//help") == ("/help", True)
    assert unescape_command("@bot //new") == ("@bot /new", True)
    assert unescape_command("/help") == ("/help", False)
    assert unescape_command("hello") == ("hello", False)


def test_unescape_command_leaves_plain_text_untouched():
    assert unescape_command("// TODO") == ("// TODO", False)
    assert unescape_command("//server/share") == ("//server/share", False)
    assert unescape_command("//help me") == ("//help me", False)


def test_unescape_command_honours_the_configured_prefix():
    assert unescape_command("!!help", "!") == ("!help", True)
    assert unescape_command("!help", "!") == ("!help", False)


def test_the_command_catalog_matches_the_kind_literal():
    names = [spec.name for spec in COMMANDS]
    assert len(names) == len(set(names)), "a command name is listed twice"
    assert set(names) == set(get_args(CommandKind)), "COMMANDS and CommandKind drifted"
