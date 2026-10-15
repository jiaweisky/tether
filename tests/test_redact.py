from __future__ import annotations

from tether.util.redact import redact_secrets


def test_redact_masks_secret_keys_only():
    source = {
        "server": {"token": "abc", "base_url": "http://x", "pool": []},
        "channels": {"wecom": {"secret": "s3cr3t", "bot_id": "b1"}},
        "projects": {"control_token": "t"},
        "nested": {"apiKey": "k", "list": [{"password": "p"}]},
    }
    out = redact_secrets(source)
    assert out["server"]["token"] == "***"
    assert out["server"]["base_url"] == "http://x"
    assert out["channels"]["wecom"]["secret"] == "***"
    assert out["channels"]["wecom"]["bot_id"] == "b1"
    assert out["projects"]["control_token"] == "***"
    assert out["nested"]["apiKey"] == "***"
    assert out["nested"]["list"][0]["password"] == "***"


def test_redact_leaves_unset_values_alone():
    assert redact_secrets({"token": "", "secret": None}) == {"token": "", "secret": None}
