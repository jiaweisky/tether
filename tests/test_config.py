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


def test_inline_limit_over_max_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate({"media": {"inline_limit_bytes": 100, "max_bytes": 50}})


def test_context_limit_positive():
    with pytest.raises(ValidationError):
        Config.model_validate({"model": {"context_limit": 0}})


def test_shared_isolation_with_writable_agent_fails_fast():
    config = Config.model_validate({"projects": {"isolation": "shared"}})
    with pytest.raises(ValueError):
        validate_startup(config, writable_agents={"build"})


def test_unknown_agent_in_writable_fails():
    config = Config.model_validate({"agent": {"writable": {"ghost": True}}})
    with pytest.raises(ValueError):
        validate_startup(config, known_agents={"build"})


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
