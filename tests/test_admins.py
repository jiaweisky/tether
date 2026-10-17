from __future__ import annotations

import pytest

from tether.config import Config, validate_startup
from tether.engine import hitl
from tether.models import Conversation, Sender


def _config(data: dict | None = None, **kwargs) -> Config:
    return Config.model_validate(data if data is not None else kwargs)


def test_global_admins_are_the_fallback():
    config = _config({"group": {"admins": ["g"]}})
    assert config.admins_for("wecom") == ["g"]
    assert config.admins_for("feishu") == ["g"]
    assert config.admins_for("wechat", "assistant") == ["g"]


def test_channel_override_and_explicit_empty_list():
    config = _config(
        {
            "group": {"admins": ["g"]},
            "access": {"admins": {"wecom": ["w"], "feishu": []}},
        }
    )
    assert config.admins_for("wecom") == ["w"]
    assert config.admins_for("feishu") == []  # explicit: no admins
    assert config.admins_for("qq") == ["g"]


def test_wechat_admins_are_scoped_per_account():
    config = _config(
        {
            "group": {"admins": ["g"]},
            "channels": {
                "wechat": {
                    "bots": [
                        {
                            "id": "a",
                            "identity": {"display_name": "A"},
                            "login_via": [{"channel": "wecom", "user": "ua"}],
                        },
                        {
                            "id": "b",
                            "identity": {"display_name": "B"},
                            "login_via": [{"channel": "wecom", "user": "ub"}],
                        },
                    ]
                }
            },
            "access": {"admins": {"wechat": {"a": ["wa"], "b": ["wb"]}}},
        }
    )
    assert config.admins_for("wechat", "a") == ["wa"]
    assert config.admins_for("wechat", "b") == ["wb"]
    # Unconfigured account falls back to the global list.
    assert config.admins_for("wechat", "c") == ["g"]


def test_unknown_wechat_admin_slot_is_rejected():
    config = _config(
        {
            "channels": {
                "wechat": {
                    "bots": [
                        {
                            "id": "a",
                            "identity": {"display_name": "A"},
                            "login_via": [{"channel": "wecom", "user": "ua"}],
                        }
                    ]
                }
            },
            "access": {"admins": {"wechat": {"missing": ["x"]}}},
        }
    )
    with pytest.raises(ValueError):
        validate_startup(config)


def test_empty_admin_id_is_rejected():
    config = _config({"access": {"admins": {"wecom": [" "]}}})
    with pytest.raises(ValueError):
        validate_startup(config)


def test_hitl_and_commands_use_channel_admins():
    config = _config(
        {
            "group": {"admins": ["global"], "command_scope": "admins"},
            "access": {"admins": {"feishu": ["feishu-admin"]}},
        }
    )
    conv = Conversation(channel="feishu", kind="group", id="g1")
    pending = hitl.make_pending(
        "permission", owner="alice", scope="admins", request_id="r"
    )
    assert hitl.is_authorized(
        pending,
        Sender(id="feishu-admin"),
        conv,
        config,
        active_turn_sender="alice",
    )
    assert not hitl.is_authorized(
        pending,
        Sender(id="global"),
        conv,
        config,
        active_turn_sender="alice",
    )
    assert hitl.command_authorized(
        Sender(id="feishu-admin"), conv, config, active_turn_sender="alice"
    )
    assert not hitl.command_authorized(
        Sender(id="global"), conv, config, active_turn_sender="alice"
    )
