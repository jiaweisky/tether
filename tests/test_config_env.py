from __future__ import annotations

import pytest

from tether.config import load_config


def write(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text)
    return path


def test_required_env_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("TB_TOKEN", "abc")
    config = load_config(write(tmp_path, "server:\n  token: ${TB_TOKEN}\n"))
    assert config.server.token == "abc"


def test_default_env_is_used_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("TB_MISSING", raising=False)
    config = load_config(write(tmp_path, "server:\n  token: ${TB_MISSING:-fallback}\n"))
    assert config.server.token == "fallback"


def test_required_env_missing_is_an_error(monkeypatch, tmp_path):
    monkeypatch.delenv("TB_NOPE", raising=False)
    with pytest.raises(ValueError):
        load_config(write(tmp_path, "server:\n  token: ${TB_NOPE}\n"))


def test_double_dollar_is_a_literal(tmp_path):
    config = load_config(write(tmp_path, 'server:\n  base_url: "$$literal"\n'))
    assert config.server.base_url == "$literal"


def test_nested_lists_and_maps_are_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("TB_URL", "http://x")
    config = load_config(
        write(tmp_path, 'server:\n  pool:\n    - {name: a, base_url: "${TB_URL}"}\n')
    )
    assert config.server.pool[0].base_url == "http://x"
