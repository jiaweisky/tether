from __future__ import annotations

import pytest
from pydantic import ValidationError

from tether.config import Config, load_config, validate_startup


def test_bad_streaming_interval_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate({"streaming": {"min_interval_ms": 0}})


def test_bad_enum_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate({"group": {"hitl_scope": "everyone"}})


def test_context_limit_positive():
    with pytest.raises(ValidationError):
        Config.model_validate({"model": {"context_limit": 0}})


def test_isolated_mode_requires_control_and_source():
    config = Config.model_validate({"projects": {"mode": "isolated"}})
    with pytest.raises(ValueError):
        validate_startup(config)
    ok = Config.model_validate(
        {"projects": {"mode": "isolated", "control_url": "http://x", "source_directory": "/src"}}
    )
    validate_startup(ok)  # no raise


def test_default_permissions_auto_approve_tools():
    config = Config()
    for action in ("read", "glob", "grep", "webfetch", "bash", "write", "edit", "apply_patch"):
        assert config.permissions.action_for(action) == "once"
    assert config.permissions.action_for("unknown_tool") == "once"


def test_load_config_from_yaml(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("agent:\n  default_agent: plan\n")
    config = load_config(path)
    assert config.agent.default_agent == "plan"


def test_server_bases_default_and_pool():
    config = Config()
    assert config.server_bases() == [("default", "http://127.0.0.1:8787", None)]
    pooled = Config.model_validate({"server": {"pool": [{"name": "a", "base_url": "http://a"}]}})
    assert pooled.server_bases()[0][0] == "a"


def test_wecom_requires_configured_identity():
    # WeCom exposes neither the bot name nor description, so both are required.
    config = Config.model_validate({"channels": {"wecom": {"enabled": True}}})
    with pytest.raises(ValueError):
        validate_startup(config)

    configured = Config.model_validate(
        {
            "channels": {"wecom": {"enabled": True}},
            "identity": {"display_name": "Bot", "description": "An assistant"},
        }
    )
    validate_startup(configured)


def test_wecom_accepts_per_channel_identity():
    config = Config.model_validate(
        {
            "channels": {
                "wecom": {
                    "enabled": True,
                    "identity": {"display_name": "W", "description": "d"},
                }
            }
        }
    )
    validate_startup(config)  # no raise


def test_invalid_outbound_pattern_is_rejected():
    with pytest.raises(ValueError):
        Config.model_validate({"media": {"outbound": {"patterns": ["[z-a]"]}}})


def test_server_token_prefers_pool_entry_then_top_level():
    config = Config.model_validate(
        {
            "server": {
                "token": "top",
                "pool": [
                    {"name": "a", "base_url": "http://a/", "token": "pool-a"},
                    {"name": "b", "base_url": "http://b"},
                ],
            }
        }
    )
    assert config.server_token("http://a") == "pool-a"
    assert config.server_token("http://a/") == "pool-a"
    # Current behavior: a pool entry with token=None does not inherit the top-level token.
    assert config.server_token("http://b") is None
    assert config.server_token("http://unknown") == "top"
