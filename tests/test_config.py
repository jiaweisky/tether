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


def test_server_endpoints_resolve_backend_auth_and_ids():
    config = Config.model_validate(
        {
            "server": {
                "backend": "opencode",
                "pool": [
                    {
                        "id": "work",
                        "name": "work",
                        "base_url": "http://a/",
                        "auth": {"type": "basic", "username": "u", "password": "p"},
                        "working_directory": "/work",
                    },
                    {
                        "name": "legacy",
                        "backend": "agentd",
                        "base_url": "http://b",
                        "token": "tok",
                    },
                ],
            }
        }
    )
    work, legacy = config.server_endpoints()
    assert work.id == "work"
    assert work.backend == "opencode"
    assert work.base_url == "http://a"
    assert work.auth is not None and work.auth.type == "basic"
    assert work.working_directory == "/work"
    assert legacy.id == "legacy"
    assert legacy.backend == "agentd"
    assert legacy.auth is not None and legacy.auth.token == "tok"
    assert config.endpoint_for_base("http://a/") == work
    assert config.endpoint_for_base("http://missing") is None


def test_default_endpoint_uses_top_level_auth():
    config = Config.model_validate({"server": {"backend": "opencode", "token": "t"}})
    endpoint = config.server_endpoints()[0]
    assert endpoint.id == "default"
    assert endpoint.backend == "opencode"
    assert endpoint.auth is not None and endpoint.auth.token == "t"


def test_validate_server_endpoint_ids_and_working_directories():
    duplicate = Config.model_validate(
        {
            "server": {
                "pool": [
                    {"id": "same", "name": "a", "base_url": "http://a"},
                    {"id": "same", "name": "b", "base_url": "http://b"},
                ]
            }
        }
    )
    with pytest.raises(ValueError, match="duplicate server endpoint id"):
        validate_startup(duplicate)

    relative = Config.model_validate(
        {
            "server": {
                "pool": [
                    {"name": "a", "base_url": "http://a", "working_directory": "relative"}
                ]
            }
        }
    )
    with pytest.raises(ValueError, match="must be absolute"):
        validate_startup(relative)


def test_validate_multiple_endpoints_per_base_requires_opencode():
    opencode = Config.model_validate(
        {
            "server": {
                "backend": "opencode",
                "pool": [
                    {"id": "a", "name": "a", "base_url": "http://same"},
                    {"id": "b", "name": "b", "base_url": "http://same"},
                ],
            }
        }
    )
    validate_startup(opencode)  # no raise

    mixed = Config.model_validate(
        {
            "server": {
                "pool": [
                    {"id": "a", "name": "a", "base_url": "http://same"},
                    {
                        "id": "b",
                        "name": "b",
                        "backend": "opencode",
                        "base_url": "http://same",
                    },
                ]
            }
        }
    )
    with pytest.raises(ValueError, match="only opencode"):
        validate_startup(mixed)


def test_validate_isolated_opencode_projects(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    base = tmp_path / "worktrees"
    base.mkdir()
    projects = {
        "mode": "isolated",
        "backend": "opencode",
        "endpoint": "oc",
        "isolation": "worktree",
        "source_directory": str(source),
        "base_dir": str(base),
    }
    server = {
        "pool": [
            {
                "id": "oc",
                "name": "oc",
                "backend": "opencode",
                "base_url": "http://oc",
            }
        ]
    }
    validate_startup(Config.model_validate({"projects": projects, "server": server}))

    missing = {**projects, "endpoint": "missing"}
    with pytest.raises(ValueError, match="requires projects.endpoint"):
        validate_startup(Config.model_validate({"projects": missing, "server": server}))

    wrong_backend = Config.model_validate(
        {
            "projects": {**projects, "endpoint": "agent"},
            "server": {
                "pool": [{"id": "agent", "name": "agent", "base_url": "http://a"}]
            },
        }
    )
    with pytest.raises(ValueError, match="opencode endpoint"):
        validate_startup(wrong_backend)

    with pytest.raises(ValueError, match="isolation=worktree"):
        validate_startup(
            Config.model_validate(
                {"projects": {**projects, "isolation": "copy"}, "server": server}
            )
        )

    with pytest.raises(ValueError, match="sandbox.process"):
        validate_startup(
            Config.model_validate(
                {
                    "projects": {**projects, "sandbox": {"process": "seatbelt"}},
                    "server": server,
                }
            )
        )
